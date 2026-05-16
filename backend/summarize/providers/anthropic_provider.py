"""Anthropic Claude-backed LLM provider (wraps the existing client.py)."""

from __future__ import annotations

import os

from fhir.resources.R4B.bundle import Bundle

from .. import client as anthropic_client
from ..models import ClinicalSummary
from .base import LLMProvider, ProviderError, ProviderInfo

DEFAULT_MODEL = "claude-haiku-4-5"


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL
        self.info = ProviderInfo(
            id="anthropic",
            name="Anthropic Claude",
            model=self.model,
            needs_api_key=True,
            local=False,
        )

    def healthcheck(self) -> tuple[bool, str]:
        if not os.getenv("ANTHROPIC_API_KEY"):
            return False, "ANTHROPIC_API_KEY not set."
        return True, f"Anthropic key present; model '{self.model}'."

    def summarize(self, bundle: Bundle) -> ClinicalSummary:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise ProviderError(
                "ANTHROPIC_API_KEY not set on the server.",
                hint="Export it before starting uvicorn, or switch provider to ollama.",
                status=400,
            )
        try:
            return anthropic_client.summarize_bundle(bundle, model=self.model)
        except Exception as exc:
            raise ProviderError(f"Anthropic call failed: {exc}", status=502) from exc
