"""Tests for FHIR Bundle assembly + validation."""

from __future__ import annotations

import base64
from datetime import date

import pytest
from fhir.resources.diagnosticreport import DiagnosticReport
from fhir.resources.documentreference import DocumentReference
from fhir.resources.patient import Patient

from backend.fhir.bundle import build_bundle, extract_documents, extract_reports, validate_bundle
from backend.ingestion.models import CanonicalPatient


def _make_canonical(raw: dict | None = None) -> CanonicalPatient:
    return CanonicalPatient(
        record_id="abc-123",
        mrn="MRN-00012345",
        given_name="Ada",
        family_name="Lovelace",
        dob=date(1815, 12, 10),
        gender="female",
        source_format="json",
        raw_record=raw or {},
    )


def _synthetic_synthea_bundle(patient_synthea_id: str = "syn-1") -> dict:
    """Hand-rolled minimal Synthea-like bundle for extract_documents/reports."""
    encoded_note = base64.b64encode(b"Chest X-ray: no acute findings.").decode("ascii")
    encoded_report = base64.b64encode(b"Lab summary: WBC 7.5, Hgb 13.4, normal panel.").decode("ascii")
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": patient_synthea_id}},
            {"resource": {
                "resourceType": "DocumentReference",
                "subject": {"reference": f"urn:uuid:{patient_synthea_id}"},
                "type": {"text": "Imaging Report"},
                "date": "2024-08-12T00:00:00Z",
                "content": [{"attachment": {"contentType": "text/plain", "data": encoded_note}}],
            }},
            {"resource": {
                "resourceType": "DiagnosticReport",
                "subject": {"reference": f"urn:uuid:{patient_synthea_id}"},
                "category": [{"coding": [{"display": "Laboratory"}]}],
                "effectiveDateTime": "2024-08-13",
                "presentedForm": [{"data": encoded_report}],
            }},
            # An unrelated DocumentReference for a different patient — should be filtered out
            {"resource": {
                "resourceType": "DocumentReference",
                "subject": {"reference": "urn:uuid:other-patient"},
                "content": [{"attachment": {"data": encoded_note}}],
            }},
        ],
    }


# ---------------------------------------------------------------------------
# extract_documents / extract_reports
# ---------------------------------------------------------------------------

def test_extract_documents_pulls_only_matching_patient():
    raw = {"_fhir_bundle": _synthetic_synthea_bundle()}
    docs = extract_documents(raw)
    assert len(docs) == 1
    assert "Chest X-ray" in docs[0]["text"]
    assert docs[0]["type"] == "Imaging Report"


def test_extract_reports_decodes_presented_form():
    raw = {"_fhir_bundle": _synthetic_synthea_bundle()}
    reports = extract_reports(raw)
    assert len(reports) == 1
    assert "WBC" in reports[0]["conclusion"]
    assert reports[0]["category"] == "Laboratory"


def test_extract_empty_when_no_bundle():
    assert extract_documents({}) == []
    assert extract_reports({}) == []


# ---------------------------------------------------------------------------
# build_bundle
# ---------------------------------------------------------------------------

def test_build_bundle_patient_only_for_empty_source():
    cp = _make_canonical()
    b = build_bundle(cp)
    assert b.type == "collection"
    assert len(b.entry) == 1
    assert isinstance(b.entry[0].resource, Patient)
    assert b.entry[0].fullUrl == "urn:uuid:abc-123"


def test_build_bundle_emits_document_and_report_for_synthea_source():
    cp = _make_canonical(raw={"_fhir_bundle": _synthetic_synthea_bundle()})
    b = build_bundle(cp)
    types = [type(e.resource).__name__ for e in b.entry]
    assert types[0] == "Patient"
    assert "DocumentReference" in types
    assert "DiagnosticReport" in types

    # Every non-Patient resource's subject reference should target the bundle's Patient
    patient_full_url = b.entry[0].fullUrl   # urn:uuid:abc-123
    target_ref = patient_full_url
    for e in b.entry[1:]:
        assert e.resource.subject.reference == target_ref


# ---------------------------------------------------------------------------
# validate_bundle
# ---------------------------------------------------------------------------

def test_validate_bundle_clean_for_minimal_bundle():
    cp = _make_canonical()
    b = build_bundle(cp)
    assert validate_bundle(b) == []
