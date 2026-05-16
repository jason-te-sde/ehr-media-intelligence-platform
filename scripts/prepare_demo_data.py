"""Build a tiny self-contained demo dataset for public deployment.

Output (default: ``demo/``):
- ``store.db``  — SQLite with ~25 patients, their FHIR Bundles, and extractive
  summaries (the fallback path, no LLM key needed).
- ``chroma/``   — ChromaDB index over the same 25 patients' notes + reports
  + extractive summaries.

The full dataset is 1.4 GB; this trim hits ~120 MB so it fits comfortably in
Hugging Face Spaces / Render / Fly.io free tiers.

Usage:
    python scripts/prepare_demo_data.py --limit 25 --target demo/
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

from backend.fhir.mappers.document_reference import decode_attachment
from backend.fhir.store import init_db as init_bundles_db, list_patient_ids, load_bundle
from backend.summarize.cache import cache_key, init_db as init_cache_db, save
from backend.summarize.extractive import build_extractive_summary
from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.documentreference import DocumentReference

SRC_DB = "store/store.db"
SRC_CHROMA = "store/chroma"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=25,
                    help="how many patients to include in the demo")
    ap.add_argument("--target", type=Path, default=Path("demo"),
                    help="output directory")
    args = ap.parse_args()

    if not Path(SRC_DB).exists():
        print(f"error: source {SRC_DB} not found. Run scripts/build_bundles.py first.",
              file=sys.stderr)
        return 1

    target: Path = args.target
    target.mkdir(parents=True, exist_ok=True)
    out_db = target / "store.db"
    out_chroma = target / "chroma"

    # 1. Copy the SQLite shell + retain only the chosen patients.
    if out_db.exists():
        out_db.unlink()
    shutil.copy(SRC_DB, out_db)

    pids = list_patient_ids(str(out_db))[: args.limit]
    keep = ",".join(f"'{p}'" for p in pids)

    with sqlite3.connect(out_db) as conn:
        conn.execute(f"DELETE FROM canonical_patients WHERE record_id NOT IN (SELECT record_id FROM canonical_patients ORDER BY record_id LIMIT {args.limit})")
        conn.execute(f"DELETE FROM bundles WHERE patient_id NOT IN ({keep})")
        conn.execute(f"DELETE FROM summaries WHERE patient_id NOT IN ({keep})")
        conn.commit()
        conn.execute("VACUUM")

    # 2. Pre-fill extractive summaries for any patient that doesn't already
    # have an AI one. Makes the modal useful without an LLM key.
    init_cache_db(str(out_db))
    init_bundles_db(str(out_db))
    filled = 0
    for pid in pids:
        bundle = load_bundle(pid, str(out_db))
        if bundle is None:
            continue
        notes = [decode_attachment(e.resource) for e in bundle.entry
                 if isinstance(e.resource, DocumentReference)]
        reports = [(e.resource.conclusion or "") for e in bundle.entry
                   if isinstance(e.resource, DiagnosticReport)]
        s = build_extractive_summary(notes, reports)
        if s is None:
            continue
        bundle_json = bundle.model_dump_json()
        key = cache_key(pid, bundle_json)
        # Only insert if not already there (preserves real AI summaries).
        with sqlite3.connect(out_db) as c:
            existing = c.execute("SELECT 1 FROM summaries WHERE cache_key = ?", (key,)).fetchone()
        if existing:
            continue
        save(key, pid, s, str(out_db))
        filled += 1
    print(f"  pre-filled {filled} extractive summaries")

    # 3. Build a fresh ChromaDB on the trimmed store.
    if out_chroma.exists():
        shutil.rmtree(out_chroma)
    out_chroma.mkdir(parents=True)
    # Reuse build_index by pointing it at our paths.
    import subprocess
    subprocess.run(
        [sys.executable, "scripts/build_index.py",
         "--db", str(out_db), "--chroma", str(out_chroma)],
        check=True,
    )

    # 4. Report sizes.
    db_size = out_db.stat().st_size / 1024 / 1024
    chroma_size = sum(p.stat().st_size for p in out_chroma.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"\nDemo dataset ready at {target}/")
    print(f"  store.db    {db_size:6.1f} MB ({len(pids)} patients)")
    print(f"  chroma/     {chroma_size:6.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
