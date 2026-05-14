"""Programmatic quality guards for AI-generated clinical summaries."""

from __future__ import annotations

from .models import ClinicalSummary

MAX_WORDS_DEFAULT = 200


def count_words(summary: ClinicalSummary) -> int:
    """Count words across all free-text fields (chief_concern, diagnoses, media, anomalies, disclaimer)."""
    text = " ".join([
        summary.chief_concern,
        *summary.key_diagnoses,
        *summary.recent_media,
        *summary.anomalies,
        summary.disclaimer,
    ])
    return len(text.split())


def validate_word_count(summary: ClinicalSummary, max_words: int = MAX_WORDS_DEFAULT) -> bool:
    return count_words(summary) <= max_words


def has_disclaimer(summary: ClinicalSummary) -> bool:
    return bool(summary.disclaimer.strip())
