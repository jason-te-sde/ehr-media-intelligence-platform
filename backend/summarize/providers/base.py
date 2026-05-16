"""Abstract LLM provider interface for clinical summarization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from fhir.resources.R4B.bundle import Bundle

from ..models import ClinicalSummary


class ProviderError(RuntimeError):
    """Raised when an LLM provider can't fulfill a request.

    The route turns this into a structured 4xx/5xx so the frontend
    can show an actionable banner (missing API key, model not
    installed, network down, ...).
    """

    def __init__(self, message: str, *, hint: str | None = None, status: int = 502):
        super().__init__(message)
        self.hint = hint
        self.status = status


@dataclass
class ProviderInfo:
    """Static description of a provider (surfaced via GET /providers)."""

    id: str                  # short slug: "ollama" | "anthropic"
    name: str                # display name: "Ollama (local)" | "Anthropic Claude"
    model: str               # currently configured model id
    needs_api_key: bool      # whether ANTHROPIC_API_KEY-style secret is required
    local: bool              # runs on this machine (no outbound call)


class LLMProvider(ABC):
    """Common surface every provider must implement."""

    info: ProviderInfo

    @abstractmethod
    def summarize(self, bundle: Bundle) -> ClinicalSummary:
        """Produce a validated ``ClinicalSummary`` for one FHIR bundle.

        Raises ``ProviderError`` if the provider is misconfigured or
        the upstream call fails.
        """

    @abstractmethod
    def healthcheck(self) -> tuple[bool, str]:
        """Return ``(ok, message)``; called by ``GET /providers``.

        Should be cheap (no model call) — ping the API root, check
        whether the configured model is present, etc.
        """
