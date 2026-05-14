"""Batch generate clinical summaries for every persisted FHIR Bundle.

Reads bundles from Task 2's ``bundles`` table, calls Claude on cache
misses, writes results into the ``summaries`` table. Re-runs are
near-instant because every bundle is a cache hit.

Usage::

    cp .env.example .env       # fill in ANTHROPIC_API_KEY
    python scripts/generate_summaries.py [--limit N] [--db PATH]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from time import perf_counter

# Pre-load .env if python-dotenv is installed (optional; falls back to plain env)
try:  # pragma: no cover
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from backend.fhir.store import list_patient_ids, load_bundle
from backend.summarize.cache import cache_key, get_cached, init_db, save
from backend.summarize.client import DEFAULT_MODEL, summarize_bundle
from backend.summarize.quality import count_words, validate_word_count

DEFAULT_DB_PATH = "store/store.db"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite store path")
    p.add_argument("--limit", type=int, default=None, help="process only the first N bundles")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Anthropic model name")
    p.add_argument("--strict-key", action="store_true",
                   help="exit non-zero if ANTHROPIC_API_KEY is missing (default: warn only)")
    args = p.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        msg = "ANTHROPIC_API_KEY not set — only cache hits will succeed."
        if args.strict_key:
            print(f"error: {msg}", file=sys.stderr)
            return 2
        print(f"warning: {msg}", file=sys.stderr)

    init_db(args.db)
    patient_ids = list_patient_ids(args.db)
    if args.limit:
        patient_ids = patient_ids[: args.limit]
    if not patient_ids:
        print(f"error: no rows in `bundles` table at {args.db}. Run scripts/build_bundles.py first.", file=sys.stderr)
        return 1

    stats = {"hits": 0, "misses": 0, "errors": 0, "over_word_limit": 0}
    t0 = perf_counter()
    for pid in patient_ids:
        bundle = load_bundle(pid, args.db)
        if bundle is None:
            stats["errors"] += 1
            continue
        bundle_json = bundle.model_dump_json()
        key = cache_key(pid, bundle_json)
        cached = get_cached(key, args.db)
        if cached is not None:
            stats["hits"] += 1
            continue

        try:
            summary = summarize_bundle(bundle, model=args.model)
            # Word-count guard: try once more with the same prompt if over
            if not validate_word_count(summary):
                stats["over_word_limit"] += 1
                print(f"  WARN {pid}: {count_words(summary)} words > 200; retrying", file=sys.stderr)
                summary = summarize_bundle(bundle, model=args.model)
            save(key, pid, summary, args.db)
            stats["misses"] += 1
        except Exception as exc:  # pragma: no cover — surfaced in stats
            print(f"  ERROR {pid}: {exc}", file=sys.stderr)
            stats["errors"] += 1

    elapsed = perf_counter() - t0
    print(f"\nProcessed {len(patient_ids)} bundles in {elapsed:.1f}s")
    print(f"  cache hits:        {stats['hits']}")
    print(f"  new summaries:     {stats['misses']}")
    print(f"  word-limit retries:{stats['over_word_limit']}")
    print(f"  errors:            {stats['errors']}")
    return 0 if stats["errors"] == 0 else 0  # don't fail batch on per-record errors


if __name__ == "__main__":
    raise SystemExit(main())
