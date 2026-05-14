"""Anthropic SDK wrapper that turns a FHIR Bundle into a validated ``ClinicalSummary``.

The Anthropic client is constructed lazily so importing this module never
fails when ``ANTHROPIC_API_KEY`` is unset (useful for tests that mock).
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Any

import anthropic
from anthropic import APIStatusError
from fhir.resources.bundle import Bundle

from .models import ClinicalSummary
from .prompts import SYSTEM_PROMPT, render_user_prompt

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 1024
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazily build and reuse the Anthropic client. Honors ANTHROPIC_API_KEY."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def set_client(client: anthropic.Anthropic) -> None:
    """Override the module-level client (used by tests to inject a mock)."""
    global _client
    _client = client


def _trim_bundle_for_prompt(bundle: Bundle, max_chars: int = 50_000) -> str:
    """Serialize a bundle to JSON, truncating overly long payloads to control token cost.

    Synthea bundles can run to several thousand resources / hundreds of KB.
    Truncation keeps the head (Patient + earliest Encounters/Conditions) which
    is what's most useful for a chief-concern + diagnoses summary.
    """
    j = bundle.model_dump_json(exclude_none=True)
    if len(j) <= max_chars:
        return j
    return j[:max_chars] + '..."}]}'   # not strictly valid JSON; LLM treats it as a clipped sample


def _extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of the model's response.

    Even with the strong "JSON only" system prompt some models occasionally
    wrap output in a markdown code fence. We strip that and parse.
    """
    # Strip ```json ... ``` fences if present
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        # otherwise find the first {...} balanced block
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"no JSON object in model response: {text[:200]!r}")
        text = text[start : end + 1]
    return json.loads(text)


def _retry_call(fn, *, attempts: int = MAX_ATTEMPTS):
    """Run ``fn()`` with exponential backoff on retryable Anthropic errors."""
    delay = 1.0
    for i in range(1, attempts + 1):
        try:
            return fn()
        except APIStatusError as e:
            if e.status_code not in RETRYABLE_STATUS or i == attempts:
                raise
            sleep_for = delay + random.uniform(0, 0.5)
            logger.warning("anthropic %s (attempt %d/%d), sleeping %.1fs", e.status_code, i, attempts, sleep_for)
            time.sleep(sleep_for)
            delay *= 2


def summarize_bundle(
    bundle: Bundle,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ClinicalSummary:
    """Call Claude to produce a validated ``ClinicalSummary`` for one bundle."""
    client = _get_client()
    bundle_json = _trim_bundle_for_prompt(bundle)
    user_prompt = render_user_prompt(bundle_json)

    def _do_call():
        return client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

    response = _retry_call(_do_call)
    text = response.content[0].text if response.content else ""
    payload = _extract_json_object(text)
    payload.setdefault("model", model)
    payload.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    return ClinicalSummary(**payload)
