"""Canonical intermediate schema for the EHR ingestion pipeline.

Every downstream task (FHIR mapping, AI summarization, semantic search)
consumes ``CanonicalPatient`` instances. Anything not representable here
must be added to the schema before it can be used downstream.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


Gender = Literal["male", "female", "other", "unknown"]
SourceFormat = Literal["json", "csv"]


class AuditEntry(BaseModel):
    """One mutation applied to a record by the cleaning pipeline."""

    field: str
    original: str | None
    normalized: str | None
    reason: str


class CanonicalPatient(BaseModel):
    """A cleaned, validated patient record ready for FHIR mapping."""

    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mrn: str
    given_name: str
    family_name: str
    dob: date | None
    gender: Gender
    source_format: SourceFormat
    raw_record: dict[str, Any]
    audit_log: list[AuditEntry] = Field(default_factory=list)
