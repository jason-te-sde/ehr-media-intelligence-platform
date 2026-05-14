"""End-to-end ingestion pipeline.

Wires parser → cleaner → deduplicate, writes an audit report to
``audit_report.json``, and persists ``CanonicalPatient`` instances to
SQLite so downstream tasks (FHIR mapping, summarization, search) can
consume them without re-running the ingestion.

CLI entry::

    python -m backend.ingestion.pipeline <path>

``path`` may be a JSON file, a directory of JSON Bundles (Synthea-style),
or a CSV / CSV.gz file.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path

from .cleaner import clean_record, deduplicate
from .models import CanonicalPatient, SourceFormat
from .parsers.csv_parser import parse_csv_file
from .parsers.json_parser import parse_json

DEFAULT_DB_PATH = "store/store.db"
DEFAULT_AUDIT_PATH = "audit_report.json"

_DDL_CANONICAL = """
CREATE TABLE IF NOT EXISTS canonical_patients (
    record_id      TEXT PRIMARY KEY,
    mrn            TEXT NOT NULL,
    patient_json   TEXT NOT NULL,
    source_format  TEXT NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Create the canonical_patients table if it doesn't exist."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(_DDL_CANONICAL)


def save_canonical_patients(
    patients: Iterable[CanonicalPatient],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Upsert ``patients`` into the ``canonical_patients`` table. Returns count written."""
    init_db(db_path)
    n = 0
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO canonical_patients (record_id, mrn, patient_json, source_format)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(record_id) DO UPDATE SET
                mrn = excluded.mrn,
                patient_json = excluded.patient_json,
                source_format = excluded.source_format
            """,
            [
                (p.record_id, p.mrn, p.model_dump_json(), p.source_format)
                for p in patients
            ],
        )
        n = conn.total_changes
    return n


def load_canonical_patients(db_path: str | Path = DEFAULT_DB_PATH) -> list[CanonicalPatient]:
    """Load every ``CanonicalPatient`` previously persisted by this pipeline."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT patient_json FROM canonical_patients").fetchall()
    return [CanonicalPatient.model_validate_json(row[0]) for row in rows]


# ---------------------------------------------------------------------------
# Audit report
# ---------------------------------------------------------------------------

def write_audit_report(
    patients: Iterable[CanonicalPatient],
    path: str | Path = DEFAULT_AUDIT_PATH,
) -> dict:
    """Write a per-record JSON audit summary; return aggregate stats."""
    records = []
    stats = {"total": 0, "with_audit_entries": 0, "by_reason": {}}
    for p in patients:
        stats["total"] += 1
        if p.audit_log:
            stats["with_audit_entries"] += 1
            for entry in p.audit_log:
                stats["by_reason"][entry.reason] = stats["by_reason"].get(entry.reason, 0) + 1
        records.append({
            "record_id": p.record_id,
            "mrn": p.mrn,
            "source_format": p.source_format,
            "audit_log": [e.model_dump() for e in p.audit_log],
        })
    out = {"stats": stats, "records": records}
    Path(path).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return stats


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _detect_format(path: Path) -> tuple[SourceFormat, list[dict]]:
    """Decide which parser to use based on file extension / directory shape."""
    if path.is_dir() or path.suffix.lower() == ".json":
        return "json", parse_json(path)
    suffix = "".join(path.suffixes).lower()
    if suffix.endswith(".csv") or suffix.endswith(".csv.gz"):
        return "csv", parse_csv_file(path)
    raise ValueError(f"{path}: unsupported file type")


def run_pipeline(
    path: str | Path,
    db_path: str | Path = DEFAULT_DB_PATH,
    audit_path: str | Path = DEFAULT_AUDIT_PATH,
) -> list[CanonicalPatient]:
    """Parse → clean → deduplicate → persist. Returns the final list."""
    path = Path(path)
    fmt, raw_records = _detect_format(path)
    cleaned = [clean_record(r, fmt) for r in raw_records]
    unique = deduplicate(cleaned)
    write_audit_report(unique, audit_path)
    save_canonical_patients(unique, db_path)
    return unique


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m backend.ingestion.pipeline <path-to-json-or-csv>", file=sys.stderr)
        return 2
    target = Path(argv[0])
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return 1
    patients = run_pipeline(target)
    print(f"Ingested {len(patients)} patients from {target}")
    print(f"  audit report: {DEFAULT_AUDIT_PATH}")
    print(f"  SQLite store: {DEFAULT_DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
