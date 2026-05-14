"""Sanity tests for the canonical schema."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from backend.ingestion.models import AuditEntry, CanonicalPatient


def test_canonical_patient_minimal_construction():
    p = CanonicalPatient(
        mrn="MRN-00000001",
        given_name="Ada",
        family_name="Lovelace",
        dob=date(1815, 12, 10),
        gender="female",
        source_format="json",
        raw_record={"original": "fields"},
    )
    assert p.record_id          # default uuid set
    assert p.audit_log == []
    assert p.dob.isoformat() == "1815-12-10"


def test_canonical_patient_with_audit_log():
    audit = [AuditEntry(field="dob", original="12/10/1815", normalized="1815-12-10", reason="normalized date format")]
    p = CanonicalPatient(
        mrn="MRN-00000001",
        given_name="Ada",
        family_name="Lovelace",
        dob=date(1815, 12, 10),
        gender="female",
        source_format="csv",
        raw_record={},
        audit_log=audit,
    )
    assert len(p.audit_log) == 1
    assert p.audit_log[0].field == "dob"


def test_invalid_gender_rejected():
    with pytest.raises(ValidationError):
        CanonicalPatient(
            mrn="MRN-00000001",
            given_name="X",
            family_name="Y",
            dob=None,
            gender="nonbinary-but-unsupported",   # type: ignore[arg-type]
            source_format="json",
            raw_record={},
        )
