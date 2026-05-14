"""Pydantic request/response models for the API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

ResourceType = Literal["Summary", "DocumentReference", "DiagnosticReport"]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural-language clinical query.")
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


class SearchHit(BaseModel):
    patient_id: str
    mrn: str
    display_name: str
    resource_type: ResourceType
    resource_date: date | None
    relevance_score: float = Field(ge=0.0, le=1.0)
    snippet: str


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    query_time_ms: int
