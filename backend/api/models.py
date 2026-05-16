"""Pydantic request/response models for the API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

ResourceType = Literal["Summary", "DocumentReference", "DiagnosticReport"]


class SearchRequest(BaseModel):
    query: str = Field(
        default="",
        description=(
            "Natural-language clinical query. Empty string is allowed when "
            "any filter (resource_types, date_from, date_to) is set — the "
            "endpoint then returns the most recent matches by date."
        ),
    )
    resource_types: list[ResourceType] | None = Field(
        default=None,
        description="If set, restrict results to these FHIR resource types.",
    )
    date_from: date | None = Field(
        default=None,
        description="Inclusive lower bound on resource_date.",
    )
    date_to: date | None = Field(
        default=None,
        description="Inclusive upper bound on resource_date.",
    )
    top_k: int = Field(default=5, ge=1, le=20)
    dedupe_patients: bool = Field(
        default=True,
        description=(
            "If True (default) return at most one hit per patient — the one "
            "with the highest relevance score. Set False to see every matched "
            "FHIR resource separately."
        ),
    )


class SearchHit(BaseModel):
    patient_id: str
    mrn: str
    display_name: str
    resource_type: ResourceType
    resource_date: date | None
    relevance_score: float = Field(ge=0.0, le=1.0)
    snippet: str
    summary_snippet: str = Field(
        default="",
        description=(
            "Short excerpt of the patient's AI summary chief_concern. "
            "Empty if no summary cached. Cards prefer this over `snippet`."
        ),
    )
    summary_source: Literal["ai", "extractive", "none"] = "none"


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    query_time_ms: int
