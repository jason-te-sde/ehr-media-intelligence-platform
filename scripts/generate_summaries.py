"""Batch generate clinical summaries for every persisted FHIR Bundle.

Reads bundles from Task 2's ``bundles`` table, calls the active LLM
provider on cache misses, writes results into the ``summaries`` table.
Re-runs are near-instant because every bundle is a cache hit.

Provider is picked from ``LLM_PROVIDER`` (default ``ollama``); override
via ``--provider`` flag.

Usage::

    python scripts/generate_summaries.py [--limit N] [--provider ollama|anthropic]
"""

from __future__ import annotations

import argparse
import sys
from time import perf_counter

try:  # pragma: no cover
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from backend.fhir.store import list_patient_ids, load_bundle
from backend.summarize.cache import cache_key, get_cached, init_db, save
from backend.summarize.providers import ProviderError, get_provider
from backend.summarize.quality import count_words, validate_word_count

DEFAULT_DB_PATH = "store/store.db"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite store path")
    p.add_argument("--limit", type=int, default=None, help="process only the first N bundles")
    p.add_argument("--provider", default=None,
                   help="override LLM_PROVIDER env (e.g. ollama, anthropic)")
    args = p.parse_args(argv)

    try:
        provider = get_provider(args.provider)
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    ok, msg = provider.healthcheck()
    if not ok:
        print(f"error: provider '{provider.info.id}' unhealthy: {msg}", file=sys.stderr)
        return 2
    print(f"using provider: {provider.info.id} / model {provider.info.model}")

    init_db(args.db)
    patient_ids = list_patient_ids(args.db)
    if args.limit:
        patient_ids = patient_ids[: args.limit]
    if not patient_ids:
        print(f"error: no rows in `bundles` table at {args.db}. Run scripts/build_bundles.py first.",
              file=sys.stderr)
        return 1

    stats = {"hits": 0, "misses": 0, "errors": 0, "over_word_limit": 0}
    t0 = perf_counter()
    total = len(patient_ids)
    for idx, pid in enumerate(patient_ids, start=1):
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

        t_call = perf_counter()
        try:
            summary = provider.summarize(bundle)
            if not validate_word_count(summary):
                stats["over_word_limit"] += 1
                print(f"  WARN {pid}: {count_words(summary)} words > 200; retrying",
                      file=sys.stderr)
                summary = provider.summarize(bundle)
            save(key, pid, summary, args.db)
            stats["misses"] += 1
            print(f"  [{idx}/{total}] {pid} -> {perf_counter() - t_call:.1f}s  cc={summary.chief_concern[:60]!r}",
                  flush=True)
        except Exception as exc:
            print(f"  ERROR {pid}: {exc}", file=sys.stderr)
            stats["errors"] += 1

    elapsed = perf_counter() - t0
    print(f"\nProcessed {len(patient_ids)} bundles in {elapsed:.1f}s")
    print(f"  cache hits:         {stats['hits']}")
    print(f"  new summaries:      {stats['misses']}")
    print(f"  word-limit retries: {stats['over_word_limit']}")
    print(f"  errors:             {stats['errors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
