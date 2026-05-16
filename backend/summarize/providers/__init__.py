"""LLM provider abstraction for clinical summarization.

The platform supports multiple LLM backends. The active provider is picked
at runtime from ``LLM_PROVIDER`` (default: ``ollama``). Each provider
turns a ``Bundle`` into a validated ``ClinicalSummary`` and is otherwise
swappable — the API route, cache, and frontend stay identical.
"""

from .base import LLMProvider, ProviderError
from .factory import get_provider, list_providers

__all__ = ["LLMProvider", "ProviderError", "get_provider", "list_providers"]
