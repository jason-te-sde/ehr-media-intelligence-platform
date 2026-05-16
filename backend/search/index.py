"""ChromaDB persistence + querying for the semantic search index.

The collection is keyed by composite document ids of the form
``<patient_id>::<resource_type>::<resource_id>``. Metadata stored
alongside each embedding:

- ``patient_id`` — bundle's Patient.id
- ``mrn`` — for display
- ``resource_type`` — "Summary" | "DocumentReference" | "DiagnosticReport"
- ``resource_date`` — ISO date string (for display only)
- ``resource_timestamp`` — Unix int seconds (for $gte/$lte filtering;
  ChromaDB does not support comparison on strings)
- ``display_name`` — patient name shown in result cards
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from .embed import embed, embed_batch

DEFAULT_PATH = "store/chroma"
COLLECTION_NAME = "ehr_records"

ResourceType = str   # narrowed to "Summary" | "DocumentReference" | "DiagnosticReport" by callers


@dataclass
class IndexedDoc:
    """One row going into the vector index."""

    id: str
    text: str
    snippet: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None


@dataclass
class QueryHit:
    """One ranked hit returned from ``query``."""

    id: str
    distance: float                     # ChromaDB cosine distance (0 = identical)
    metadata: dict[str, Any]
    document: str                       # the indexed snippet

    @property
    def relevance_score(self) -> float:
        # cosine distance is in [0, 2]; map back to [-1, 1] then clamp to [0, 1].
        score = 1.0 - self.distance
        if score < 0:
            return 0.0
        if score > 1:
            return 1.0
        return score


def _client(path: str | Path = DEFAULT_PATH) -> ClientAPI:
    Path(path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def get_or_create_collection(path: str | Path = DEFAULT_PATH) -> Collection:
    return _client(path).get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection(path: str | Path = DEFAULT_PATH) -> None:
    """Drop the collection (used by tests + a fresh build)."""
    c = _client(path)
    try:
        c.delete_collection(COLLECTION_NAME)
    except Exception:
        pass


UPSERT_BATCH_SIZE = 5000   # ChromaDB hard cap is 5461; leave headroom.


def add_documents(docs: list[IndexedDoc], path: str | Path = DEFAULT_PATH) -> int:
    """Upsert (id, embedding, metadata, snippet) for each doc. Returns count."""
    if not docs:
        return 0
    coll = get_or_create_collection(path)
    # Some docs may arrive without embeddings — compute them in batch.
    missing = [d for d in docs if d.embedding is None]
    if missing:
        vecs = embed_batch([d.text for d in missing])
        for d, v in zip(missing, vecs, strict=True):
            d.embedding = v
    for i in range(0, len(docs), UPSERT_BATCH_SIZE):
        chunk = docs[i : i + UPSERT_BATCH_SIZE]
        coll.upsert(
            ids=[d.id for d in chunk],
            embeddings=[d.embedding for d in chunk],
            metadatas=[d.metadata for d in chunk],
            documents=[d.snippet for d in chunk],
        )
    return len(docs)


def existing_ids(path: str | Path = DEFAULT_PATH) -> set[str]:
    """Return every id currently in the collection (used for idempotent re-runs)."""
    coll = get_or_create_collection(path)
    return set(coll.get(include=[]).get("ids") or [])


def query(
    text: str,
    where: dict[str, Any] | None = None,
    top_k: int = 5,
    path: str | Path = DEFAULT_PATH,
) -> list[QueryHit]:
    """Embed the query, run a ChromaDB nearest-neighbor search, return ranked hits."""
    coll = get_or_create_collection(path)
    embedding = embed(text)
    raw = coll.query(
        query_embeddings=[embedding],
        n_results=top_k,
        where=where or None,
    )
    ids = (raw.get("ids") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    return [
        QueryHit(id=i, distance=d, metadata=m, document=doc)
        for i, d, m, doc in zip(ids, distances, metadatas, documents, strict=True)
    ]


def list_by_filter(
    where: dict[str, Any],
    top_k: int = 5,
    path: str | Path = DEFAULT_PATH,
) -> list[QueryHit]:
    """Return matching docs sorted newest-first by ``resource_timestamp``.

    Used when the user supplies only filters and no free-text query — there's
    no embedding to rank against, so we fall back to recency. ChromaDB has no
    server-side ORDER BY, so we over-fetch and sort in Python.
    """
    coll = get_or_create_collection(path)
    # Cap the over-fetch so we don't drag huge result sets into memory.
    raw = coll.get(where=where, limit=top_k * 20, include=["metadatas", "documents"])
    ids = raw.get("ids") or []
    metadatas = raw.get("metadatas") or []
    documents = raw.get("documents") or []
    rows = [
        QueryHit(id=i, distance=0.0, metadata=m, document=d)
        for i, m, d in zip(ids, metadatas, documents, strict=True)
    ]
    rows.sort(key=lambda h: h.metadata.get("resource_timestamp") or 0, reverse=True)
    return rows[:top_k]
