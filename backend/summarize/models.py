"""Output schema for Claude-generated clinical summaries.

A summary is the structured deliverable surfaced to clinicians via the
search UI in Task 5. It must always include an AI disclaimer; the cap
on word count (≤ 200) is enforced by ``quality.validate_word_count``
after generation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConfidenceLevel = Literal["low", "medium", "high"]


class ClinicalSummary(BaseModel):
    chief_concern: str = Field(
        description="One-sentence primary clinical issue."
    )
    key_diagnoses: list[str] = Field(
        default_factory=list,
        description="Up to 5 specific diagnoses, most specific first.",
    )
    recent_media: list[str] = Field(
        default_factory=list,
        description="Imaging/labs from the last 6 months, format \"<study> <date>\".",
    )
    anomalies: list[str] = Field(
        default_factory=list,
        description="Flagged out-of-range or critical findings; empty list if none.",
    )
    disclaimer: str = Field(
        description="AI-generated, not a clinical decision — always non-empty.",
    )
    confidence: ConfidenceLevel = Field(
        default="medium",
        description="Self-rated confidence (low|medium|high) — low when source data is sparse.",
    )
    word_count: int = Field(
        ge=0,
        description="Total word count across all free-text fields; validated by quality.py.",
    )
    model: str = Field(
        description="LLM model name used to generate this summary.",
    )
    generated_at: datetime
