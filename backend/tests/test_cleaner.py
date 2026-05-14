"""Edge-case tests for the ingestion cleaner (per TASK1_PLAN §7.7)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from backend.ingestion.cleaner import (
    clean_record,
    deduplicate,
    normalize_dob,
    normalize_gender,
    normalize_mrn,
)
from backend.ingestion.models import CanonicalPatient

FIXTURE = Path(__file__).parent / "data" / "edge_cases.json"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Multi-format dates → same date(1990, 1, 15)
# ---------------------------------------------------------------------------

def test_multi_format_dates_normalize_to_same_value(rows):
    cleaned = [clean_record(r, "json") for r in rows[:3]]
    assert all(p.dob == date(1990, 1, 15) for p in cleaned)
    # MM/DD/YYYY and DD-Mon-YYYY get audit entries; YYYY-MM-DD is already canonical
    audit_dob_changes = [any(e.field == "dob" for e in p.audit_log) for p in cleaned]
    assert sum(audit_dob_changes) >= 2


# ---------------------------------------------------------------------------
# 2. Missing DOB → dob=None + audit entry
# ---------------------------------------------------------------------------

def test_missing_dob_logs_audit(rows):
    grace = rows[3]
    p = clean_record(grace, "json")
    assert p.dob is None
    assert any(e.field == "dob" and "missing" in e.reason for e in p.audit_log)


# ---------------------------------------------------------------------------
# 3. Duplicate records → 1 kept + drop logged
# ---------------------------------------------------------------------------

def test_duplicate_records_collapse_with_audit(rows):
    cleaned = [clean_record(r, "json") for r in rows[:3]]
    unique = deduplicate(cleaned)
    assert len(unique) == 1
    survivor = unique[0]
    drop_entries = [e for e in survivor.audit_log if e.reason.startswith("duplicate dropped")]
    assert len(drop_entries) == 2     # two duplicates dropped onto the survivor


# ---------------------------------------------------------------------------
# 4. Gender codes: M/1/MALE → "male"; "??" → "unknown"; "F"/"2"/"female" → "female"
# ---------------------------------------------------------------------------

def test_gender_codes_normalize():
    assert normalize_gender("M") == "male"
    assert normalize_gender("1") == "male"
    assert normalize_gender("MALE") == "male"
    assert normalize_gender("F") == "female"
    assert normalize_gender("2") == "female"
    assert normalize_gender("female") == "female"
    assert normalize_gender("??") == "unknown"
    assert normalize_gender("") == "unknown"
    assert normalize_gender(None) == "unknown"


# ---------------------------------------------------------------------------
# 5. MRN formats: "12345" / "MRN-00012345" / "  012345  " → "MRN-00012345"
# ---------------------------------------------------------------------------

def test_mrn_formats_normalize_to_canonical(rows):
    for r in rows[:3]:
        p = clean_record(r, "json")
        assert p.mrn == "MRN-00012345"
    # Direct unit checks too
    assert normalize_mrn("12345") == "MRN-00012345"
    assert normalize_mrn("MRN-00012345") == "MRN-00012345"
    assert normalize_mrn("  012345  ") == "MRN-00012345"
    assert normalize_mrn("") == "MRN-00000000"


# ---------------------------------------------------------------------------
# 6. Missing family_name → "UNKNOWN" + audit, no crash
# ---------------------------------------------------------------------------

def test_missing_family_name_handled(rows):
    mary = rows[4]
    p = clean_record(mary, "json")
    assert isinstance(p, CanonicalPatient)
    assert p.family_name == "UNKNOWN"
    assert any(e.field == "family_name" and "missing" in e.reason for e in p.audit_log)


# ---------------------------------------------------------------------------
# Bonus: unparseable DOB doesn't crash and is audit-logged
# ---------------------------------------------------------------------------

def test_unparseable_dob_logged_not_crashed(rows):
    turing = rows[7]
    parsed, err = normalize_dob(turing["BIRTHDATE"])
    assert parsed is None
    assert err and "unparseable" in err
    p = clean_record(turing, "json")
    assert p.dob is None
    assert any("unparseable" in e.reason for e in p.audit_log)
