"""SQLite persistence for FHIR Bundles.

Each bundle is stored as one row keyed by the contained ``Patient.id``.
The Bundle is serialized as JSON (``bundle.model_dump_json()``) so the
row is fully self-describing — Task 3 (summarization) and Task 4
(semantic search) can re-hydrate it without depending on Task 1's
canonical_patients table.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.patient import Patient

DEFAULT_DB_PATH = "store/store.db"

_DDL_BUNDLES = """
CREATE TABLE IF NOT EXISTS bundles (
    patient_id   TEXT PRIMARY KEY,
    bundle_json  TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Create the bundles table if it doesn't exist."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(_DDL_BUNDLES)


def _patient_id_from_bundle(bundle: Bundle) -> str:
    """Pull the contained Patient.id (used as the table's primary key)."""
    for entry in bundle.entry or []:
        if isinstance(entry.resource, Patient):
            if not entry.resource.id:
                raise ValueError("Bundle's Patient resource has no id")
            return entry.resource.id
    raise ValueError("Bundle contains no Patient resource")


def save_bundle(bundle: Bundle, db_path: str | Path = DEFAULT_DB_PATH) -> str:
    """Upsert ``bundle`` into the store keyed by its Patient.id. Returns the key."""
    init_db(db_path)
    patient_id = _patient_id_from_bundle(bundle)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO bundles (patient_id, bundle_json)
            VALUES (?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                bundle_json = excluded.bundle_json
            """,
            (patient_id, bundle.model_dump_json()),
        )
    return patient_id


def load_bundle(patient_id: str, db_path: str | Path = DEFAULT_DB_PATH) -> Bundle | None:
    """Load one bundle by patient id, or ``None`` if not present."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT bundle_json FROM bundles WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()
    if row is None:
        return None
    return Bundle.model_validate_json(row[0])


def list_patient_ids(db_path: str | Path = DEFAULT_DB_PATH) -> list[str]:
    """Return the ids of every persisted bundle."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT patient_id FROM bundles").fetchall()
    return [r[0] for r in rows]
