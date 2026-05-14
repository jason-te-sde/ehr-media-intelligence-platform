"""Prompt scaffolding for Claude-based clinical summarization.

The system prompt enforces clinical tone and structured JSON output.
The user prompt embeds the FHIR bundle JSON (optionally trimmed by the
client wrapper) and the target schema so the model can self-check.
"""

from __future__ import annotations

import json

from .models import ClinicalSummary

SYSTEM_PROMPT = """You are a clinical summarization assistant. You read FHIR R4 bundles and produce concise, structured summaries for clinicians.

Rules:
- Output MUST be a single JSON object matching the provided schema. No prose outside the JSON.
- Never invent facts. If the bundle is missing a field, leave the corresponding output array empty or write "No clinical history on record".
- Total prose word count across all string and array fields MUST be at most 200 words.
- Always include a non-empty `disclaimer` stating that the summary is AI-generated and not a clinical decision.
- key_diagnoses: at most 5 entries, most specific first.
- recent_media: imaging/labs from roughly the last 6 months, formatted as "<study> <YYYY-MM-DD>".
- anomalies: flagged out-of-range or critical findings; use an empty list if none.
- chief_concern: ONE sentence describing the primary clinical issue."""


USER_PROMPT_TEMPLATE = """FHIR bundle for one patient (truncated if very large):

```json
{bundle_json}
```

Produce a JSON summary matching this schema:

```json
{schema_json}
```

Remember: at most 200 total words; never invent facts; the `disclaimer` field is mandatory and non-empty."""


def render_user_prompt(bundle_json: str) -> str:
    """Substitute the bundle JSON and target schema into the user-prompt template."""
    return USER_PROMPT_TEMPLATE.format(
        bundle_json=bundle_json,
        schema_json=json.dumps(ClinicalSummary.model_json_schema(), indent=2),
    )
