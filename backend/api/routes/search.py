"""POST /search — semantic search across all indexed FHIR documents + summaries."""

from __future__ import annotations

from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any

from fastapi import APIRouter

from backend.api.models import SearchHit, SearchRequest, SearchResponse
from backend.search.index import query as index_query

router = APIRouter(prefix="/search", tags=["search"])


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


@router.post("", response_model=SearchResponse, summary="Semantic search across patient records")
def search(req: SearchRequest) -> SearchResponse:
    t0 = perf_counter()
    where = _build_where(req)
    hits = index_query(req.query, where=where, top_k=req.top_k)
    response_hits = [
        SearchHit(
            patient_id=h.metadata.get("patient_id", ""),
            mrn=h.metadata.get("mrn", ""),
            display_name=h.metadata.get("display_name", ""),
            resource_type=h.metadata.get("resource_type", "Summary"),
            resource_date=_parse_iso_date(h.metadata.get("resource_date")),
            relevance_score=h.relevance_score,
            snippet=h.document,
        )
        for h in hits
    ]
    return SearchResponse(
        hits=response_hits,
        query_time_ms=int((perf_counter() - t0) * 1000),
    )
