"""Pick the active LLM provider at runtime from ``LLM_PROVIDER``."""

from __future__ import annotations

import os
from functools import lru_cache

from .anthropic_provider import AnthropicProvider
from .base import LLMProvider, ProviderError
from .ollama_provider import OllamaProvider

DEFAULT_PROVIDER = "ollama"

_REGISTRY: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "anthropic": AnthropicProvider,
}


def list_providers() -> list[str]:
    return list(_REGISTRY)


def get_provider(name: str | None = None) -> LLMProvider:
    """Return a provider instance.

    ``name`` overrides ``LLM_PROVIDER``; the default is ``ollama``.
    """
    pid = (name or os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    cls = _REGISTRY.get(pid)
    if cls is None:
        raise ProviderError(
            f"Unknown LLM_PROVIDER='{pid}'. Choices: {sorted(_REGISTRY)}.",
            status=400,
        )
    return _cached_instance(pid)


@lru_cache(maxsize=4)
def _cached_instance(pid: str) -> LLMProvider:
    return _REGISTRY[pid]()
