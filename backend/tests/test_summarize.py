"""Tests for the summarization layer (schema + client + cache + quality).

The Anthropic SDK is mocked end-to-end — no real API calls are made.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.fhir.bundle import build_bundle
from backend.fhir.store import init_db as init_bundle_db
from backend.fhir.store import save_bundle
from backend.ingestion.models import CanonicalPatient
from backend.summarize import client as client_mod
from backend.summarize.cache import cache_key, get_cached, init_db as init_cache_db
from backend.summarize.cache import save as cache_save
from backend.summarize.client import _extract_json_object, summarize_bundle
from backend.summarize.models import ClinicalSummary
from backend.summarize.quality import count_words, has_disclaimer, validate_word_count


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_summary(disclaimer: str = "AI-generated, not a clinical decision.", **overrides) -> ClinicalSummary:
    base = dict(
        chief_concern="Stable hypertension on monotherapy.",
        key_diagnoses=["Hypertension"],
        recent_media=["BMP 2024-09-14"],
        anomalies=[],
        disclaimer=disclaimer,
        word_count=18,
        model="claude-haiku-4-5",
        generated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return ClinicalSummary(**base)


def _mock_anthropic(payload: dict) -> MagicMock:
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(payload))]
    fake = MagicMock()
    fake.messages.create.return_value = response
    return fake


def _make_canonical() -> CanonicalPatient:
    return CanonicalPatient(
        record_id="patient-1",
        mrn="MRN-00000001",
        given_name="A",
        family_name="B",
        dob=date(2000, 1, 1),
        gender="female",
        source_format="json",
        raw_record={},
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_clinical_summary_constructs():
    s = _make_summary()
    assert s.chief_concern.startswith("Stable")
    assert s.disclaimer != ""


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

def test_count_words_includes_all_free_text():
    s = _make_summary(
        chief_concern="A B",
        key_diagnoses=["C", "D E"],
        recent_media=["F"],
        anomalies=["G", "H"],
        disclaimer="I J",
    )
    assert count_words(s) == 10   # 2 + 1 + 2 + 1 + 1 + 1 + 2


def test_validate_word_count_under_and_over():
    s = _make_summary(disclaimer=" ".join(["x"] * 500))
    assert not validate_word_count(s)
    assert validate_word_count(_make_summary())


def test_has_disclaimer_rejects_blank():
    assert not has_disclaimer(_make_summary(disclaimer=""))
    assert not has_disclaimer(_make_summary(disclaimer="   "))
    assert has_disclaimer(_make_summary())


# ---------------------------------------------------------------------------
# Client — JSON extraction + end-to-end (mocked)
# ---------------------------------------------------------------------------

def test_extract_json_object_handles_fenced_response():
    assert _extract_json_object('```json\n{"a":1}\n```') == {"a": 1}


def test_extract_json_object_handles_prose_wrapped_response():
    assert _extract_json_object('Sure! Here it is: {"a":2} — done.') == {"a": 2}


def test_summarize_bundle_calls_anthropic_and_validates(monkeypatch):
    fake = _mock_anthropic({
        "chief_concern": "Type 2 DM, stable.",
        "key_diagnoses": ["T2DM"],
        "recent_media": ["HbA1c 2024-10-12"],
        "anomalies": [],
        "disclaimer": "AI-generated, not a clinical decision.",
        "word_count": 12,
    })
    client_mod.set_client(fake)
    bundle = build_bundle(_make_canonical())
    summary = summarize_bundle(bundle, model="claude-haiku-4-5")
    assert summary.chief_concern.startswith("Type 2")
    assert summary.model == "claude-haiku-4-5"
    fake.messages.create.assert_called_once()


# ---------------------------------------------------------------------------
# Cache — hit avoids API
# ---------------------------------------------------------------------------

def test_cache_hit_avoids_api_call(tmp_path: Path):
    db = str(tmp_path / "cache_test.db")
    init_cache_db(db)
    init_bundle_db(db)

    cp = _make_canonical()
    bundle = build_bundle(cp)
    save_bundle(bundle, db)

    pre_seeded = _make_summary()
    key = cache_key(cp.record_id, bundle.model_dump_json())
    cache_save(key, cp.record_id, pre_seeded, db)

    # Cached lookup returns it
    got = get_cached(key, db)
    assert got is not None
    assert got.chief_concern == pre_seeded.chief_concern

    # And the API client is never invoked when the cache is consulted
    fake = MagicMock()
    client_mod.set_client(fake)
    assert get_cached(key, db) is not None
    fake.messages.create.assert_not_called()
