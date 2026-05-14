"""Tests for the FHIR Bundle SQLite store."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backend.fhir.bundle import build_bundle
from backend.fhir.store import init_db, list_patient_ids, load_bundle, save_bundle
from backend.ingestion.models import CanonicalPatient


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    p = tmp_path / "test_fhir.db"
    init_db(p)
    return str(p)


def _make_canonical(record_id: str, mrn: str) -> CanonicalPatient:
    return CanonicalPatient(
        record_id=record_id,
        mrn=mrn,
        given_name="X",
        family_name="Y",
        dob=date(2000, 1, 1),
        gender="female",
        source_format="json",
        raw_record={},
    )


def test_save_and_load_roundtrip(db_path: str):
    cp = _make_canonical("p1", "MRN-00000001")
    saved_id = save_bundle(build_bundle(cp), db_path)
    assert saved_id == "p1"

    loaded = load_bundle("p1", db_path)
    assert loaded is not None
    assert loaded.type == "collection"
    assert len(loaded.entry) == 1
    assert loaded.entry[0].resource.id == "p1"


def test_load_missing_returns_none(db_path: str):
    assert load_bundle("nope", db_path) is None


def test_list_patient_ids_returns_all_saved(db_path: str):
    for i in range(3):
        save_bundle(build_bundle(_make_canonical(f"p{i}", f"MRN-0000000{i}")), db_path)
    ids = sorted(list_patient_ids(db_path))
    assert ids == ["p0", "p1", "p2"]


def test_upsert_preserves_one_row_per_patient(db_path: str):
    cp = _make_canonical("p1", "MRN-00000001")
    save_bundle(build_bundle(cp), db_path)
    save_bundle(build_bundle(cp), db_path)
    assert list_patient_ids(db_path) == ["p1"]
