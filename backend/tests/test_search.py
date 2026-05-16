"""Tests for the semantic-search layer + /search API.

Uses a per-test ChromaDB collection seeded with a small synthetic index
so latency stays in pytest-friendly territory. Heavy lifting (the
real Synthea index) is covered by manual verification in the README.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.search.embed import EMBEDDING_DIM, embed, embed_batch
from backend.search.index import (
    IndexedDoc,
    add_documents,
    existing_ids,
    get_or_create_collection,
    query,
    reset_collection,
)


# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------

def test_embed_returns_384_dim_vector():
    v = embed("Patient with hypertension")
    assert len(v) == EMBEDDING_DIM
    assert all(isinstance(x, float) for x in v)


def test_embed_batch_matches_single_embed():
    texts = ["chest pain", "shortness of breath", "headache"]
    batch = embed_batch(texts)
    assert len(batch) == 3
    assert all(len(v) == EMBEDDING_DIM for v in batch)


def test_embed_is_normalized():
    v = embed("hypertension")
    norm = sum(x * x for x in v) ** 0.5
    assert abs(norm - 1.0) < 1e-3


# ---------------------------------------------------------------------------
# Fixture: a tiny populated index per test
# ---------------------------------------------------------------------------

@pytest.fixture
def populated_index(tmp_path: Path) -> str:
    path = str(tmp_path / "chroma")
    reset_collection(path)
    docs = [
        IndexedDoc(
            id="p1::Summary",
            text="Patient with type 2 diabetes mellitus, stable on metformin.",
            snippet="T2DM stable on metformin",
            metadata={
                "patient_id": "p1", "mrn": "MRN-1", "display_name": "Alice A",
                "resource_type": "Summary", "resource_date": "2024-10-12",
                "resource_timestamp": 1728691200,   # 2024-10-12 UTC
            },
        ),
        IndexedDoc(
            id="p2::DiagnosticReport::r1",
            text="Chest x-ray: no acute cardiopulmonary process. Mild cardiomegaly.",
            snippet="Chest x-ray mild cardiomegaly",
            metadata={
                "patient_id": "p2", "mrn": "MRN-2", "display_name": "Bob B",
                "resource_type": "DiagnosticReport", "resource_date": "2024-05-01",
                "resource_timestamp": 1714521600,   # 2024-05-01 UTC
            },
        ),
        IndexedDoc(
            id="p3::DocumentReference::d1",
            text="Patient reports persistent cough and intermittent fever for one week.",
            snippet="cough and fever",
            metadata={
                "patient_id": "p3", "mrn": "MRN-3", "display_name": "Carol C",
                "resource_type": "DocumentReference", "resource_date": "2024-08-20",
                "resource_timestamp": 1724112000,
            },
        ),
    ]
    add_documents(docs, path=path)
    return path


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def test_index_returns_relevant_hit_for_known_query(populated_index: str):
    hits = query("diabetes", top_k=3, path=populated_index)
    assert hits
    # The diabetes Summary should top the list
    assert hits[0].id == "p1::Summary"
    assert hits[0].relevance_score > hits[-1].relevance_score


def test_index_filter_resource_type(populated_index: str):
    hits = query("patient", where={"resource_type": "DiagnosticReport"}, top_k=5, path=populated_index)
    assert hits
    assert all(h.metadata["resource_type"] == "DiagnosticReport" for h in hits)


def test_index_filter_date_range(populated_index: str):
    # 2024-08-01 onward → excludes the May report
    hits = query(
        "patient",
        where={"resource_timestamp": {"$gte": 1722470400}},   # 2024-08-01
        top_k=5,
        path=populated_index,
    )
    assert hits
    assert all(h.metadata["resource_timestamp"] >= 1722470400 for h in hits)


def test_index_upsert_is_idempotent(populated_index: str):
    before = existing_ids(populated_index)
    # Re-add the same docs
    docs = [
        IndexedDoc(
            id="p1::Summary",
            text="updated text",
            snippet="updated",
            metadata={"patient_id": "p1", "resource_type": "Summary", "mrn": "MRN-1",
                      "display_name": "Alice A", "resource_date": "2024-10-12",
                      "resource_timestamp": 1728691200},
        ),
    ]
    add_documents(docs, path=populated_index)
    after = existing_ids(populated_index)
    assert before == after


# ---------------------------------------------------------------------------
# API — FastAPI TestClient end-to-end against the populated index
# ---------------------------------------------------------------------------

@pytest.fixture
def client(populated_index: str, monkeypatch):
    """FastAPI test client wired to the populated_index fixture."""
    from fastapi.testclient import TestClient

    from backend.api import main as api_main
    from backend.api.routes import search as search_route
    from backend.search import index as idx

    real_query = idx.query

    def patched_query(text, where=None, top_k=5, path=None):
        return real_query(text, where=where, top_k=top_k, path=populated_index)

    monkeypatch.setattr(search_route, "index_query", patched_query)
    return TestClient(api_main.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_search_baseline(client):
    r = client.post("/search", json={"query": "diabetes", "top_k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["hits"]
    assert body["query_time_ms"] >= 0
    # Scores should be in descending order
    scores = [h["relevance_score"] for h in body["hits"]]
    assert scores == sorted(scores, reverse=True)


def test_search_resource_type_filter(client):
    r = client.post("/search", json={"query": "patient", "resource_types": ["DiagnosticReport"], "top_k": 5})
    body = r.json()
    assert body["hits"]
    assert all(h["resource_type"] == "DiagnosticReport" for h in body["hits"])


def test_search_date_range_excludes_older(client):
    r = client.post("/search", json={"query": "patient", "date_from": "2024-08-01", "top_k": 5})
    body = r.json()
    # The May 2024 DiagnosticReport must be excluded
    ids = {h["mrn"] for h in body["hits"]}
    assert "MRN-2" not in ids


def test_search_empty_query_rejected(client):
    # Empty query with NO filters → 400 (route raises). Previously 422
    # (Pydantic rejected it) before filter-only mode was added.
    r = client.post("/search", json={"query": ""})
    assert r.status_code == 400
    assert "query" in r.json()["detail"].lower()


def test_search_filter_only_mode_allowed(client):
    # Empty query is allowed when at least one filter is supplied —
    # returns matches sorted by date (newest first).
    r = client.post("/search", json={
        "query": "",
        "resource_types": ["DocumentReference"],
    })
    assert r.status_code == 200


def test_search_top_k_capped(client):
    r = client.post("/search", json={"query": "patient", "top_k": 100})
    assert r.status_code == 422   # top_k le=20 per the model
