"""GET /patient/{id} — full detail view backing the frontend modal.

Also exposes ``POST /patient/{id}/summarize`` which triggers an on-demand
Claude call (cached in SQLite). The button in the frontend modal hits this
endpoint so clinicians can opt into AI summaries patient-by-patient rather
than running the batch script ahead of time.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.patient import Patient
from pydantic import BaseModel

from backend.fhir.mappers.document_reference import decode_attachment
from backend.fhir.mappers.patient import extract_mrn
from backend.fhir.store import load_bundle
from backend.summarize.cache import cache_key, get_for_patient, save
from backend.summarize.extractive import build_extractive_summary
from backend.summarize.models import ClinicalSummary
from backend.summarize.providers import ProviderError, get_provider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patient", tags=["patient"])

LinkedType = Literal["DocumentReference", "DiagnosticReport"]


class LinkedResource(BaseModel):
    resource_type: LinkedType
    resource_id: str
    date: date | None
    title: str
    content: str = ""


class PatientDetail(BaseModel):
    patient_id: str
    mrn: str
    display_name: str
    dob: date | None
    gender: str | None
    summary: ClinicalSummary | None
    summary_source: Literal["ai", "extractive", "none"] = "none"
    linked_resources: list[LinkedResource]


def _display_name(p: Patient) -> str:
    if not p.name:
        return "Unknown"
    n = p.name[0]
    given = (n.given or [""])[0]
    family = n.family or ""
    return f"{given} {family}".strip() or "Unknown"


def _parse_date(value) -> date | None:
    """Coerce FHIR date/dateTime/instant/string into a calendar date."""
    if value is None:
        return None
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    # datetime (FHIR dateTime/instant) — drop the time-of-day component
    if hasattr(value, "date"):
        return value.date()
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        return None


@router.get("/{patient_id}", response_model=PatientDetail)
def get_patient(patient_id: str) -> PatientDetail:
    bundle = load_bundle(patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"patient {patient_id} not found")

    patient = next((e.resource for e in bundle.entry if isinstance(e.resource, Patient)), None)
    if patient is None:
        raise HTTPException(status_code=500, detail="bundle missing Patient resource")

    linked: list[LinkedResource] = []
    note_texts: list[str] = []
    report_texts: list[str] = []
    for entry in bundle.entry:
        r = entry.resource
        if isinstance(r, DocumentReference):
            text = decode_attachment(r)
            note_texts.append(text)
            linked.append(LinkedResource(
                resource_type="DocumentReference",
                resource_id=r.id,
                date=_parse_date(r.date),
                title=(r.type.text if r.type else None) or "Clinical Note",
                content=text,
            ))
        elif isinstance(r, DiagnosticReport):
            cat_text = "Report"
            if r.category and r.category[0].coding:
                cat_text = r.category[0].coding[0].display or r.category[0].text or cat_text
            conclusion = r.conclusion or ""
            report_texts.append(conclusion)
            linked.append(LinkedResource(
                resource_type="DiagnosticReport",
                resource_id=r.id,
                date=_parse_date(r.effectiveDateTime),
                title=cat_text,
                content=conclusion,
            ))

    linked.sort(key=lambda lr: lr.date or date.min, reverse=True)

    ai_summary = get_for_patient(patient_id)
    summary_source: Literal["ai", "extractive", "none"] = "none"
    summary: ClinicalSummary | None = None
    if ai_summary is not None:
        summary = ai_summary
        summary_source = "ai"
    else:
        summary = build_extractive_summary(note_texts, report_texts)
        if summary is not None:
            summary_source = "extractive"

    return PatientDetail(
        patient_id=patient.id,
        mrn=extract_mrn(patient) or "",
        display_name=_display_name(patient),
        dob=_parse_date(patient.birthDate),
        gender=patient.gender,
        summary=summary,
        summary_source=summary_source,
        linked_resources=linked,
    )


class SummarizeResponse(BaseModel):
    summary: ClinicalSummary
    cached: bool
    provider: str


@router.post("/{patient_id}/summarize", response_model=SummarizeResponse)
def summarize_patient(
    patient_id: str,
    force: bool = False,
    provider: str | None = None,
) -> SummarizeResponse:
    """Generate (or return cached) AI summary for one patient.

    The active provider comes from ``LLM_PROVIDER`` (default ``ollama``);
    pass ``?provider=anthropic`` to override per-request. ``?force=true``
    bypasses the cache.
    """
    bundle = load_bundle(patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"patient {patient_id} not found")

    try:
        llm = get_provider(provider)
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    if not force:
        cached = get_for_patient(patient_id)
        if cached is not None:
            return SummarizeResponse(summary=cached, cached=True, provider=llm.info.id)

    ok, msg = llm.healthcheck()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    try:
        summary = llm.summarize(bundle)
    except ProviderError as exc:
        logger.warning("provider %s failed: %s", llm.info.id, exc)
        detail = str(exc) + (f" {exc.hint}" if exc.hint else "")
        raise HTTPException(status_code=exc.status, detail=detail) from exc
    except Exception as exc:
        logger.exception("provider %s unexpected error", llm.info.id)
        raise HTTPException(status_code=502, detail=f"AI summary failed: {exc}") from exc

    key = cache_key(patient_id, bundle.model_dump_json(exclude_none=True))
    save(key, patient_id, summary)
    return SummarizeResponse(summary=summary, cached=False, provider=llm.info.id)
