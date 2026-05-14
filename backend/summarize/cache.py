"""SQLite cache for AI-generated clinical summaries.

The cache key is ``sha256(patient_id + bundle_json)`` so any change to
the source bundle invalidates the cache automatically. Re-running the
batch script after a fully-populated run becomes a no-op: every patient
is a cache hit and zero Anthropic calls are made.

Lives in the same ``store/store.db`` SQLite file as Tasks 1-2; the table
is independent.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from .models import ClinicalSummary

DEFAULT_DB_PATH = "store/store.db"

_DDL_SUMMARIES = """
CREATE TABLE IF NOT EXISTS summaries (
    cache_key    TEXT PRIMARY KEY,
    patient_id   TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    model        TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_summaries_patient ON summaries (patient_id);
"""


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Create the summaries table and its patient_id index."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_DDL_SUMMARIES)


def cache_key(patient_id: str, bundle_json: str) -> str:
    """Stable hex digest used as the primary key."""
    return hashlib.sha256(f"{patient_id}:{bundle_json}".encode("utf-8")).hexdigest()


def get_cached(key: str, db_path: str | Path = DEFAULT_DB_PATH) -> ClinicalSummary | None:
    """Return the cached summary for ``key`` or ``None`` on miss."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT summary_json FROM summaries WHERE cache_key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    return ClinicalSummary.model_validate_json(row[0])


def save(
    key: str,
    patient_id: str,
    summary: ClinicalSummary,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    """Upsert a summary by ``cache_key``."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO summaries (cache_key, patient_id, summary_json, model)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                summary_json = excluded.summary_json,
                model = excluded.model
            """,
            (key, patient_id, summary.model_dump_json(), summary.model),
        )


def get_for_patient(patient_id: str, db_path: str | Path = DEFAULT_DB_PATH) -> ClinicalSummary | None:
    """Convenience lookup by patient (returns the most recent if multiple).

    Used by Tasks 4-5 which know a patient_id but not a specific cache key.
    Returns ``None`` if the table doesn't exist yet (no summaries generated).
    """
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT summary_json FROM summaries
            WHERE patient_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (patient_id,),
        ).fetchone()
    if row is None:
        return None
    return ClinicalSummary.model_validate_json(row[0])
