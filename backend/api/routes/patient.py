"""GET /patient/{id} — full detail view backing the frontend modal."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from fhir.resources.diagnosticreport import DiagnosticReport
from fhir.resources.documentreference import DocumentReference
from fhir.resources.patient import Patient
from pydantic import BaseModel

from backend.fhir.mappers.patient import extract_mrn
from backend.fhir.store import load_bundle
from backend.summarize.cache import get_for_patient
from backend.summarize.models import ClinicalSummary

router = APIRouter(prefix="/patient", tags=["patient"])

LinkedType = Literal["DocumentReference", "DiagnosticReport"]


class LinkedResource(BaseModel):
    resource_type: LinkedType
    resource_id: str
    date: date | None
    title: str


class PatientDetail(BaseModel):
    patient_id: str
    mrn: str
    display_name: str
    dob: date | None
    gender: str | None
    summary: ClinicalSummary | None
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
    for entry in bundle.entry:
        r = entry.resource
        if isinstance(r, DocumentReference):
            linked.append(LinkedResource(
                resource_type="DocumentReference",
                resource_id=r.id,
                date=_parse_date(r.date),
                title=(r.type.text if r.type else None) or "Clinical Note",
            ))
        elif isinstance(r, DiagnosticReport):
            cat_text = "Report"
            if r.category and r.category[0].coding:
                cat_text = r.category[0].coding[0].display or r.category[0].text or cat_text
            linked.append(LinkedResource(
                resource_type="DiagnosticReport",
                resource_id=r.id,
                date=_parse_date(r.effectiveDateTime),
                title=cat_text,
            ))

    return PatientDetail(
        patient_id=patient.id,
        mrn=extract_mrn(patient) or "",
        display_name=_display_name(patient),
        dob=_parse_date(patient.birthDate),
        gender=patient.gender,
        summary=get_for_patient(patient_id),
        linked_resources=linked,
    )
