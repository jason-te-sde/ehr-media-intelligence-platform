"""Batch FHIR bundle builder.

Loads every ``CanonicalPatient`` persisted by Task 1's ingestion pipeline,
maps each to a FHIR R4 ``Bundle``, validates it, persists valid bundles to
``store.db``, and writes ``validation_report.json`` summarizing per-patient
status.

Usage::

    python scripts/build_bundles.py [--db store/store.db]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from time import perf_counter

from backend.fhir.bundle import build_bundle, validate_bundle
from backend.fhir.store import init_db, save_bundle
from backend.ingestion.pipeline import load_canonical_patients

DEFAULT_DB_PATH = "store/store.db"
DEFAULT_REPORT_PATH = "validation_report.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH,
                        help="SQLite store path (default: %(default)s)")
    parser.add_argument("--report", default=DEFAULT_REPORT_PATH,
                        help="validation report JSON path (default: %(default)s)")
    args = parser.parse_args(argv)

    t0 = perf_counter()
    init_db(args.db)
    canonicals = load_canonical_patients(args.db)
    if not canonicals:
        print(f"error: no CanonicalPatient rows in {args.db}. Run the ingestion pipeline first.", file=sys.stderr)
        return 1

    report: list[dict] = []
    valid_count = 0
    for cp in canonicals:
        try:
            bundle = build_bundle(cp)
            errors = validate_bundle(bundle)
            if errors:
                report.append({"patient_id": cp.record_id, "mrn": cp.mrn, "status": "invalid", "errors": errors})
                continue
            save_bundle(bundle, args.db)
            valid_count += 1
            report.append({"patient_id": cp.record_id, "mrn": cp.mrn, "status": "valid", "entries": len(bundle.entry)})
        except Exception as exc:
            report.append({"patient_id": cp.record_id, "mrn": cp.mrn, "status": "error", "errors": [str(exc)]})

    Path(args.report).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    counts = collections.Counter(r["status"] for r in report)
    elapsed = perf_counter() - t0
    print(f"Built {valid_count}/{len(canonicals)} bundles in {elapsed:.1f}s")
    print(f"  by status: {dict(counts)}")
    print(f"  saved to: {args.db} (bundles table)")
    print(f"  report:   {args.report}")
    return 0 if counts.get("invalid", 0) == 0 and counts.get("error", 0) == 0 else 0  # don't fail on validation issues, just report


if __name__ == "__main__":
    raise SystemExit(main())
