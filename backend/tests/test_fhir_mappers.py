"""Tests for the FHIR resource mappers."""

from __future__ import annotations

from datetime import date

import pytest
from fhir.resources.documentreference import DocumentReference
from fhir.resources.patient import Patient

from backend.fhir.mappers.diagnostic_report import to_diagnostic_report
from backend.fhir.mappers.document_reference import decode_attachment, to_document_reference
from backend.fhir.mappers.patient import canonical_to_patient, extract_mrn
from backend.ingestion.models import CanonicalPatient


@pytest.fixture
def cp() -> CanonicalPatient:
    return CanonicalPatient(
        record_id="abc-123",
        mrn="MRN-00012345",
        given_name="Ada",
        family_name="Lovelace",
        dob=date(1815, 12, 10),
        gender="female",
        source_format="json",
        raw_record={},
    )


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------

def test_patient_mrn_identifier_roundtrip(cp: CanonicalPatient):
    p = canonical_to_patient(cp)
    assert p.id == "abc-123"
    assert p.gender == "female"
    assert p.birthDate.isoformat() == "1815-12-10"
    assert extract_mrn(p) == "MRN-00012345"


def test_patient_unknown_gender_becomes_none():
    cp = CanonicalPatient(
        mrn="MRN-00000001",
        given_name="X", family_name="Y",
        dob=None, gender="unknown", source_format="json", raw_record={},
    )
    p = canonical_to_patient(cp)
    assert p.gender is None
    assert p.birthDate is None


# ---------------------------------------------------------------------------
# DocumentReference
# ---------------------------------------------------------------------------

def test_document_reference_subject_uses_urn_uuid():
    dr = to_document_reference("note text", patient_id="abc-123")
    assert dr.subject.reference == "urn:uuid:abc-123"
    assert dr.status == "current"


def test_document_reference_text_roundtrip_in_memory():
    dr = to_document_reference("Patient reports chest pain.", patient_id="abc-123")
    assert decode_attachment(dr) == "Patient reports chest pain."


def test_document_reference_text_roundtrip_through_json():
    original = "Patient with hypertension, well controlled on lisinopril 10mg daily."
    dr = to_document_reference(original, patient_id="abc-123")
    j = dr.model_dump_json()
    dr2 = DocumentReference.model_validate_json(j)
    assert decode_attachment(dr2) == original


# ---------------------------------------------------------------------------
# DiagnosticReport
# ---------------------------------------------------------------------------

def test_diagnostic_report_subject_uses_urn_uuid():
    dx = to_diagnostic_report("Mild anemia.", patient_id="abc-123", category="LAB")
    assert dx.subject.reference == "urn:uuid:abc-123"
    assert dx.status == "final"
    assert dx.conclusion == "Mild anemia."
