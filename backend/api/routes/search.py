"""POST /search — semantic search across all indexed FHIR documents + summaries."""

from __future__ import annotations

from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any

from fastapi import APIRouter

from fastapi import HTTPException

from backend.api.models import SearchHit, SearchRequest, SearchResponse
from backend.search.index import list_by_filter, query as index_query
from backend.summarize.cache import get_for_patient

router = APIRouter(prefix="/search", tags=["search"])

SUMMARY_SNIPPET_LEN = 220


def _date_to_ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _build_where(req: SearchRequest) -> dict[str, Any] | None:
    """Convert SearchRequest filters → ChromaDB ``where`` clause."""
    conditions: list[dict[str, Any]] = []
    if req.resource_types:
        conditions.append({"resource_type": {"$in": list(req.resource_types)}})
    if req.date_from is not None:
        conditions.append({"resource_timestamp": {"$gte": _date_to_ts(req.date_from)}})
    if req.date_to is not None:
        # Inclusive upper bound — add one day's worth of seconds, then $lt.
        end_ts = _date_to_ts(req.date_to) + 86400 - 1
        conditions.append({"resource_timestamp": {"$lte": end_ts}})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _parse_iso_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _summary_snippet(s) -> str:
    """Render an AI summary's chief_concern + top diagnoses as a short blurb."""
    if s is None:
        return ""
    bits: list[str] = []
    if s.chief_concern:
        bits.append(s.chief_concern)
    if s.key_diagnoses:
        bits.append("Diagnoses: " + "; ".join(s.key_diagnoses[:3]))
    text = " — ".join(bits)
    if len(text) > SUMMARY_SNIPPET_LEN:
        text = text[: SUMMARY_SNIPPET_LEN - 1].rstrip() + "…"
    return text


DEDUPE_FETCH_MULT = 5   # over-fetch this many * top_k so dedupe leaves enough rows


@router.post("", response_model=SearchResponse, summary="Semantic search across patient records")
def search(req: SearchRequest) -> SearchResponse:
    t0 = perf_counter()
    where = _build_where(req)
    q = (req.query or "").strip()
    has_filter = where is not None
    if not q and not has_filter:
        raise HTTPException(
            status_code=400,
            detail="Provide a `query`, or at least one of resource_types / date_from / date_to.",
        )

    # PDF: "returns the top-5 ranked *patient* record matches". Without dedupe
    # a single patient who matches the query in multiple resources crowds out
    # all other patients (5 cards, all the same person). Over-fetch then
    # collapse to one card per patient — keep the highest-scored hit.
    fetch_k = req.top_k * DEDUPE_FETCH_MULT if req.dedupe_patients else req.top_k
    if q:
        raw = index_query(q, where=where, top_k=fetch_k)
    else:
        # Empty query + filters: sort matching docs newest-first.
        raw = list_by_filter(where, top_k=fetch_k)

    if req.dedupe_patients:
        best_by_patient: dict[str, Any] = {}
        for h in raw:
            pid = h.metadata.get("patient_id", "")
            if pid and (pid not in best_by_patient
                        or h.relevance_score > best_by_patient[pid].relevance_score):
                best_by_patient[pid] = h
        hits = sorted(best_by_patient.values(),
                      key=lambda x: x.relevance_score, reverse=True)[: req.top_k]
    else:
        hits = raw[: req.top_k]

    # Batch-fetch one cached summary per unique patient so every card can
    # render an AI-summary snippet (PDF Task 5: "AI summary snippet").
    unique_pids = {h.metadata.get("patient_id", "") for h in hits}
    summaries: dict[str, Any] = {pid: get_for_patient(pid) for pid in unique_pids if pid}

    response_hits: list[SearchHit] = []
    for h in hits:
        pid = h.metadata.get("patient_id", "")
        s = summaries.get(pid)
        response_hits.append(SearchHit(
            patient_id=pid,
            mrn=h.metadata.get("mrn", ""),
            display_name=h.metadata.get("display_name", ""),
            resource_type=h.metadata.get("resource_type", "Summary"),
            resource_date=_parse_iso_date(h.metadata.get("resource_date")),
            relevance_score=h.relevance_score,
            snippet=h.document,
            summary_snippet=_summary_snippet(s),
            summary_source="ai" if s is not None else "none",
        ))
    return SearchResponse(
        hits=response_hits,
        query_time_ms=int((perf_counter() - t0) * 1000),
    )
