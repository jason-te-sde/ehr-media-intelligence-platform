"""Build the semantic-search vector index.

Reads every FHIR Bundle from ``bundles`` and every cached
``ClinicalSummary`` from ``summaries``, extracts three indexable text
streams per patient (the AI summary, each DocumentReference, each
DiagnosticReport), embeds them with all-MiniLM-L6-v2, and upserts into
ChromaDB at ``store/chroma``.

Usage::

    pip install -e .                          # so backend.* resolves
    python scripts/build_bundles.py           # produces store/store.db `bundles`
    python scripts/generate_summaries.py      # populates `summaries`
    python scripts/build_index.py             # indexes everything

Idempotent — re-running skips any document id already in the collection.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from time import perf_counter

from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.patient import Patient

from backend.fhir.mappers.document_reference import decode_attachment
from backend.fhir.mappers.patient import extract_mrn
from backend.fhir.store import list_patient_ids, load_bundle
from backend.search.embed import embed_batch
from backend.search.index import IndexedDoc, add_documents, existing_ids
from backend.summarize.cache import get_for_patient
from backend.summarize.models import ClinicalSummary

DEFAULT_DB_PATH = "store/store.db"
DEFAULT_CHROMA_PATH = "store/chroma"
SNIPPET_LEN = 200


def _display_name(p: Patient) -> str:
    if not p.name:
        return "Unknown"
    n = p.name[0]
    given = (n.given or [""])[0]
    family = n.family or ""
    return f"{given} {family}".strip() or "Unknown"


def _summary_text(s: ClinicalSummary) -> str:
    pieces = [s.chief_concern]
    pieces.extend(s.key_diagnoses)
    pieces.extend(s.recent_media)
    pieces.extend(s.anomalies)
    return " ".join(p for p in pieces if p)


def _parse_iso_to_ts(value) -> int:
    """Coerce a FHIR date/dateTime/str into a Unix int. Returns 0 when unknown."""
    if value is None:
        return 0
    if hasattr(value, "isoformat"):
        # could be date or datetime
        try:
            return int(datetime.fromisoformat(value.isoformat()).replace(tzinfo=timezone.utc).timestamp())
        except (TypeError, ValueError):
            return 0
    text = str(value).strip()
    if not text:
        return 0
    for fmt in (None,):  # try fromisoformat first
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            pass
    # bare date like "2024-08-12"
    try:
        return int(datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return 0


def _make_doc(*, id: str, text: str, patient_id: str, mrn: str, display_name: str,
              resource_type: str, resource_date: str | None) -> IndexedDoc:
    snippet = text[:SNIPPET_LEN]
    ts = _parse_iso_to_ts(resource_date)
    return IndexedDoc(
        id=id,
        text=text,
        snippet=snippet,
        metadata={
            "patient_id": patient_id,
            "mrn": mrn,
            "display_name": display_name,
            "resource_type": resource_type,
            "resource_date": str(resource_date) if resource_date else "",
            "resource_timestamp": ts,
        },
    )


def _build_docs_for_patient(patient_id: str, db_path: str) -> list[IndexedDoc]:
    bundle = load_bundle(patient_id, db_path)
    if bundle is None:
        return []
    # The bundle's Patient is first by construction (see Task 2 §4.5).
    patient = bundle.entry[0].resource
    if not isinstance(patient, Patient):
        # Defensive — find it
        patient = next((e.resource for e in bundle.entry if isinstance(e.resource, Patient)), None)
        if patient is None:
            return []
    mrn = extract_mrn(patient) or ""
    name = _display_name(patient)

    out: list[IndexedDoc] = []

    # 1. AI summary
    summary = get_for_patient(patient_id, db_path)
    if summary is not None:
        text = _summary_text(summary)
        if text:
            out.append(_make_doc(
                id=f"{patient_id}::Summary",
                text=text,
                patient_id=patient_id, mrn=mrn, display_name=name,
                resource_type="Summary",
                resource_date=summary.generated_at.date().isoformat(),
            ))

    # 2. DocumentReferences in the bundle
    for entry in bundle.entry[1:]:
        r = entry.resource
        if isinstance(r, DocumentReference):
            text = decode_attachment(r)
            if not text:
                continue
            out.append(_make_doc(
                id=f"{patient_id}::DocumentReference::{r.id}",
                text=text,
                patient_id=patient_id, mrn=mrn, display_name=name,
                resource_type="DocumentReference",
                resource_date=str(r.date) if r.date else None,
            ))

    # 3. DiagnosticReports
    for entry in bundle.entry[1:]:
        r = entry.resource
        if isinstance(r, DiagnosticReport):
            text = r.conclusion or ""
            if not text:
                continue
            out.append(_make_doc(
                id=f"{patient_id}::DiagnosticReport::{r.id}",
                text=text,
                patient_id=patient_id, mrn=mrn, display_name=name,
                resource_type="DiagnosticReport",
                resource_date=str(r.effectiveDateTime) if r.effectiveDateTime else None,
            ))

    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--chroma", default=DEFAULT_CHROMA_PATH)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true",
                   help="re-embed even ids already in the collection")
    args = p.parse_args(argv)

    patient_ids = list_patient_ids(args.db)
    if args.limit:
        patient_ids = patient_ids[: args.limit]
    if not patient_ids:
        print(f"error: no rows in `bundles` table at {args.db}. Run scripts/build_bundles.py first.", file=sys.stderr)
        return 1

    t0 = perf_counter()
    already = set() if args.force else existing_ids(args.chroma)

    pending: list[IndexedDoc] = []
    for pid in patient_ids:
        for d in _build_docs_for_patient(pid, args.db):
            if d.id in already:
                continue
            pending.append(d)

    if not pending:
        print("nothing to do — all docs already indexed (use --force to re-embed).")
        return 0

    # Embed in one big batch for speed
    print(f"embedding {len(pending)} new documents...")
    vecs = embed_batch([d.text for d in pending])
    for d, v in zip(pending, vecs, strict=True):
        d.embedding = v

    added = add_documents(pending, path=args.chroma)
    elapsed = perf_counter() - t0
    print(f"\nIndexed {added} new documents in {elapsed:.1f}s")
    print(f"  collection now contains: {len(existing_ids(args.chroma))} ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
