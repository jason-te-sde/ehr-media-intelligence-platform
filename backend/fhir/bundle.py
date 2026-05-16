"""Assemble FHIR R4 ``Bundle`` resources from cleaned ``CanonicalPatient``\\ s.

A bundle contains a single ``Patient`` resource plus any
``DocumentReference`` / ``DiagnosticReport`` resources we can lift from the
original source (Synthea bundles carry these directly; MIMIC patients have
no free-text and produce a Patient-only bundle).

References inside the bundle use ``urn:uuid:<id>`` fullUrls so they resolve
internally without an external base URL.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from fhir.resources.R4B.bundle import Bundle, BundleEntry

from backend.ingestion.models import CanonicalPatient

from .mappers.diagnostic_report import to_diagnostic_report
from .mappers.document_reference import to_document_reference
from .mappers.encounter import from_source as encounter_from_source
from .mappers.patient import canonical_to_patient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source extraction — Synthea / MIMIC differ in raw_record shape.
# ---------------------------------------------------------------------------

def _synthea_patient_id(raw: dict[str, Any]) -> str | None:
    """Return the original Synthea Patient.id from an attached FHIR Bundle."""
    bundle = raw.get("_fhir_bundle")
    if not bundle:
        return None
    for entry in bundle.get("entry", []):
        r = entry.get("resource") or {}
        if r.get("resourceType") == "Patient":
            return r.get("id")
    return None


def _b64decode_or_empty(data: str | bytes | None) -> str:
    if not data:
        return ""
    if isinstance(data, str):
        data = data.encode("ascii")
    try:
        return base64.b64decode(data).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _encounter_id_from_ref(ref: str | None) -> str | None:
    """Strip 'urn:uuid:' / 'Encounter/' prefix; return the bare UUID."""
    if not ref:
        return None
    for prefix in ("urn:uuid:", "Encounter/"):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref or None


def extract_documents(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ``{text, type, date, encounter_id}`` dicts pulled from a raw source record."""
    out: list[dict[str, Any]] = []
    bundle = raw.get("_fhir_bundle")
    if not bundle:
        return out
    syn_id = _synthea_patient_id(raw)
    for entry in bundle.get("entry", []):
        r = entry.get("resource") or {}
        if r.get("resourceType") != "DocumentReference":
            continue
        subj_ref = (r.get("subject") or {}).get("reference", "")
        # Synthea uses urn:uuid:<id>; other sources may use Patient/<id>. Match either.
        if syn_id and syn_id not in subj_ref:
            continue
        content = (r.get("content") or [{}])[0] or {}
        attachment = content.get("attachment") or {}
        text = _b64decode_or_empty(attachment.get("data"))
        if not text:
            continue
        ctx = r.get("context") or {}
        enc_refs = ctx.get("encounter") or []
        enc_id = _encounter_id_from_ref(enc_refs[0].get("reference")) if enc_refs else None
        out.append({
            "text": text,
            "type": (r.get("type") or {}).get("text") or "Clinical Note",
            "date": r.get("date"),
            "encounter_id": enc_id,
        })
    return out


def extract_reports(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ``{conclusion, category, date, encounter_id}`` dicts from a raw source record."""
    out: list[dict[str, Any]] = []
    bundle = raw.get("_fhir_bundle")
    if not bundle:
        return out
    syn_id = _synthea_patient_id(raw)
    for entry in bundle.get("entry", []):
        r = entry.get("resource") or {}
        if r.get("resourceType") != "DiagnosticReport":
            continue
        subj_ref = (r.get("subject") or {}).get("reference", "")
        if syn_id and syn_id not in subj_ref:
            continue

        # Synthea stores the human-readable note in presentedForm[0].data (base64).
        # If absent, fall back to a top-level conclusion string.
        forms = r.get("presentedForm") or []
        text = _b64decode_or_empty(forms[0].get("data")) if forms else ""
        if not text:
            text = r.get("conclusion") or ""
        if not text:
            continue

        category = "LAB"
        cats = r.get("category") or []
        if cats:
            coding = (cats[0].get("coding") or [{}])[0]
            category = coding.get("display") or cats[0].get("text") or category

        enc_id = _encounter_id_from_ref((r.get("encounter") or {}).get("reference"))
        out.append({
            "conclusion": text,
            "category": category,
            "date": r.get("effectiveDateTime"),
            "encounter_id": enc_id,
        })
    return out


def extract_encounters(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the patient's Encounter resources as raw dicts (Synthea shape)."""
    out: list[dict[str, Any]] = []
    bundle = raw.get("_fhir_bundle")
    if not bundle:
        return out
    syn_id = _synthea_patient_id(raw)
    for entry in bundle.get("entry", []):
        r = entry.get("resource") or {}
        if r.get("resourceType") != "Encounter":
            continue
        subj_ref = (r.get("subject") or {}).get("reference", "")
        if syn_id and syn_id not in subj_ref:
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------

def build_bundle(canonical: CanonicalPatient) -> Bundle:
    """Build a ``collection``-type FHIR R4 Bundle for one patient.

    Resources included: ``Patient`` (1), ``Encounter`` (n), ``DocumentReference``
    (n), ``DiagnosticReport`` (n). Encounter ids are preserved from the source
    so DocumentReference.context.encounter / DiagnosticReport.encounter
    references resolve against the bundle's own entries.
    """
    patient = canonical_to_patient(canonical)
    entries: list[BundleEntry] = [BundleEntry(
        fullUrl=f"urn:uuid:{patient.id}",
        resource=patient,
    )]

    encounter_ids_in_bundle: set[str] = set()
    for enc_raw in extract_encounters(canonical.raw_record):
        try:
            enc = encounter_from_source(enc_raw, patient.id)
        except Exception as exc:
            logger.warning("skip Encounter for %s: %s", patient.id, exc)
            continue
        entries.append(BundleEntry(fullUrl=f"urn:uuid:{enc.id}", resource=enc))
        encounter_ids_in_bundle.add(enc.id)

    for doc in extract_documents(canonical.raw_record):
        # Only point at an Encounter we actually have in the bundle so the
        # reference always resolves; otherwise leave context.encounter unset.
        enc_id = doc.get("encounter_id")
        enc_id = enc_id if enc_id in encounter_ids_in_bundle else None
        dr = to_document_reference(
            text=doc["text"],
            patient_id=patient.id,
            doc_type=doc.get("type") or "Clinical Note",
            date=doc.get("date"),
            encounter_id=enc_id,
        )
        entries.append(BundleEntry(fullUrl=f"urn:uuid:{dr.id}", resource=dr))

    for rep in extract_reports(canonical.raw_record):
        enc_id = rep.get("encounter_id")
        enc_id = enc_id if enc_id in encounter_ids_in_bundle else None
        dx = to_diagnostic_report(
            conclusion=rep["conclusion"],
            patient_id=patient.id,
            category=rep.get("category") or "LAB",
            date=rep.get("date"),
            encounter_id=enc_id,
        )
        entries.append(BundleEntry(fullUrl=f"urn:uuid:{dx.id}", resource=dx))

    return Bundle(type="collection", entry=entries)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_bundle(bundle: Bundle) -> list[str]:
    """Roundtrip the bundle through JSON. Empty return list = valid."""
    try:
        j = bundle.model_dump_json()
        Bundle.model_validate_json(j)
        return []
    except Exception as exc:   # pragma: no cover — surfaced in validation_report
        return [str(exc)]
