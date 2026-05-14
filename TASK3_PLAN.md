# Task 3 — AI-Powered Clinical Summarization

> Generate concise, structured clinical summaries from FHIR Bundles using the Claude API; cache aggressively; include an AI-generated disclaimer.

GitHub workflow conventions are identical to [TASK1_PLAN.md](TASK1_PLAN.md) §2 and §5.

---

## 1. Context

**What the assessment asks** (Task 3 checklist):
- Use the Claude API (or OpenAI) to summarize each patient's document history
- Summary must include: chief concern, key diagnoses, recent media records (imaging, labs), flagged anomalies
- ≤ 200 words, clinically accurate, prompt-engineered
- Cache summaries by patient ID + record hash to avoid redundant API calls on re-runs
- Include a confidence/disclaimer field noting the output is AI-generated and not a clinical decision

**Why this matters.** A clinician triaging 50 patients doesn't want to read 50 full bundles. A 150-word structured summary surfaced in search results gives them 5-second triage. The cache is non-negotiable — every Claude call costs real money, and re-running the pipeline shouldn't re-bill. The disclaimer is a clinical-safety requirement; we treat it as part of the schema, not a UI footer.

**Input.** FHIR Bundles from Task 2's `bundles` table.

**Output.** SQLite table `summaries(cache_key PK, patient_id, summary_json TEXT, model, created_at)`. The `summary_json` deserializes into a `ClinicalSummary` Pydantic model.

---

## 2. Data Strategy

No new datasets — we summarize the bundles produced by Task 2.

**Sampling strategy** during development:
- Iterate prompt design against 5 hand-picked patients (varied conditions: cardiac, oncology, healthy baseline) to avoid burning API budget on bad prompts
- Run full 100-patient batch only once the prompt is locked
- All API calls happen serially (not parallel) to stay under rate limits and keep cost predictable

---

## 3. Issue Inventory (Task 3)

Six issues. Sequence begins after Task 2 closes.

| # | Title | Labels | Depends on | Acceptance |
|---|---|---|---|---|
| **16** | `feat(summarize): ClinicalSummary schema + prompt templates` | `feature` `task-3` | Task 2 closed | `models.py` exports `ClinicalSummary` Pydantic model; `prompts.py` exports `SYSTEM_PROMPT`, `USER_PROMPT_TEMPLATE`, `FEW_SHOT_EXAMPLES`; word-count constraint baked into prompt |
| **17** | `feat(summarize): anthropic client wrapper with retry` | `feature` `task-3` | #16 | `client.py` exposes `summarize_bundle(bundle: Bundle) -> ClinicalSummary`; uses JSON mode; retries on 429/5xx with exponential backoff; surfaces `ANTHROPIC_API_KEY` from env |
| **18** | `feat(summarize): SQLite summary cache` | `feature` `task-3` | #17 | `cache.py` exposes `get_cached(key)` / `save(key, summary)`; cache key = `sha256(patient_id + bundle_json)`; cache hit avoids any API call |
| **19** | `feat(summarize): batch script` | `feature` `task-3` | #18 | `scripts/generate_summaries.py` iterates bundles, checks cache, calls Claude on misses, persists; prints summary stats (hit rate, total tokens, cost estimate) |
| **20** | `test(summarize): schema + word-count + cache tests` | `tests` `task-3` | #17, #18 | Mocked-API tests cover: word-count ≤ 200, all required fields present, disclaimer non-empty, cache hit returns without API call; ≥ 6 tests |
| **21** | `docs: Task 3 README + quality validation write-up` | `docs` `task-3` | #19, #20 | README section on prompt design + cache design; write-up draft covers "how we validated AI summary quality" (spot-check methodology, word-count enforcement, disclaimer pattern) |

---

## 4. Module Design

### 4.1 Final Task-3 Directory Layout

```
backend/summarize/
├── __init__.py
├── models.py                   # issue #16 — ClinicalSummary
├── prompts.py                  # issue #16 — templates
├── client.py                   # issue #17 — anthropic wrapper
├── cache.py                    # issue #18 — SQLite cache
└── quality.py                  # issue #20 — validators (word count, schema)

scripts/generate_summaries.py   # issue #19

backend/tests/
└── test_summarize.py           # issue #20
```

### 4.2 `models.py` — Output schema

```python
class ClinicalSummary(BaseModel):
    chief_concern: str           # 1 sentence
    key_diagnoses: list[str]     # ≤ 5
    recent_media: list[str]      # e.g. ["Chest X-ray 2024-08-12", "CBC 2024-09-01"]
    anomalies: list[str]         # flagged items, can be empty
    disclaimer: str              # always present, never empty
    word_count: int              # validated ≤ 200 in quality.py
    model: str                   # e.g. "claude-haiku-4-5"
    generated_at: datetime
```

### 4.3 `prompts.py`

```python
SYSTEM_PROMPT = """You are a clinical summarization assistant. You read FHIR bundles and produce concise, structured summaries for clinicians. You never invent facts. Output must be valid JSON matching the provided schema. Total prose must not exceed 200 words. Always include an AI-disclaimer."""

USER_PROMPT_TEMPLATE = """FHIR bundle for one patient:

{bundle_json}

Produce a JSON summary matching this schema:
{schema_json}

Constraints:
- chief_concern: one sentence describing the primary clinical issue
- key_diagnoses: up to 5, most specific first
- recent_media: imaging/labs from the last 6 months, format "<study> <date>"
- anomalies: any flagged out-of-range labs or critical findings; empty list if none
- disclaimer: a one-sentence statement that this summary is AI-generated and not a clinical decision
- Total word count across all free-text fields must be ≤ 200 words"""

FEW_SHOT_EXAMPLES = [...]   # 1-2 example bundle → summary pairs to lock format
```

### 4.4 `client.py`

```python
from datetime import datetime, timezone
from anthropic import Anthropic

client = Anthropic()   # reads ANTHROPIC_API_KEY from env

def summarize_bundle(bundle: Bundle, model: str = "claude-haiku-4-5") -> ClinicalSummary:
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            *FEW_SHOT_EXAMPLES,
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                bundle_json=bundle.model_dump_json(indent=2),
                schema_json=ClinicalSummary.model_json_schema(),
            )},
        ],
    )
    payload = json.loads(response.content[0].text)
    return ClinicalSummary(**payload, model=model, generated_at=datetime.now(timezone.utc))
```

Retry strategy (tenacity or hand-rolled): exponential backoff on `APIStatusError` with status in `{429, 500, 502, 503, 504}`, max 3 attempts.

### 4.5 `cache.py`

```python
DDL = """
CREATE TABLE IF NOT EXISTS summaries (
    cache_key TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def cache_key(patient_id: str, bundle_json: str) -> str:
    return hashlib.sha256(f"{patient_id}:{bundle_json}".encode()).hexdigest()

def get_cached(key: str) -> ClinicalSummary | None: ...
def save(key: str, patient_id: str, summary: ClinicalSummary): ...
```

### 4.6 `quality.py`

```python
def validate_word_count(summary: ClinicalSummary, max_words: int = 200) -> bool:
    text = " ".join([
        summary.chief_concern,
        *summary.key_diagnoses,
        *summary.recent_media,
        *summary.anomalies,
        summary.disclaimer,
    ])
    return len(text.split()) <= max_words

def assert_disclaimer_present(summary: ClinicalSummary) -> bool:
    return bool(summary.disclaimer.strip())
```

### 4.7 `scripts/generate_summaries.py`

```python
def main():
    init_db()                                  # creates `summaries` cache table
    patient_ids = list_patient_ids()           # from Task 2's `bundles` table
    stats = {"hits": 0, "misses": 0, "errors": 0}
    for pid in patient_ids:
        bundle = load_bundle(pid)              # fhir.resources Bundle
        key = cache_key(pid, bundle.model_dump_json())
        cached = get_cached(key)
        if cached:
            stats["hits"] += 1
            continue
        try:
            summary = summarize_bundle(bundle)
            if not validate_word_count(summary):
                print(f"WARN {pid}: word count over 200, regenerating with stricter prompt")
                summary = summarize_bundle(bundle)   # one retry
            save(key, pid, summary)
            stats["misses"] += 1
        except Exception as e:
            print(f"ERROR {pid}: {e}")
            stats["errors"] += 1
    print(stats)
```

---

## 5. Quality Validation Approach (for the write-up)

How we know summaries are clinically useful:

1. **Schema enforcement**: every summary parses into `ClinicalSummary` or it doesn't get saved. No free-form blobs.
2. **Word-count guard**: hard cap of 200 across all free-text fields. Over-length summaries trigger one retry with stricter prompt; persistent failures are logged.
3. **Disclaimer presence**: enforced as non-empty in schema validation.
4. **Manual spot-check**: 5 randomly selected summaries diffed against their source bundles. Reviewer checks: chief concern matches an actual problem in the bundle; diagnoses are present in `Condition` resources (or coded inferences from labs); no hallucinated medications.
5. **Negative test**: take a bundle, blank out all clinical content, send to Claude; assert the output is mostly empty / "no clinical information provided" — not hallucinated.

These checks live in `quality.py` (programmatic) and the README write-up (manual methodology).

---

## 6. Verification (Task 3 Overall Acceptance)

Milestone "Task 3: AI Summarization" closes when **all** of these are true:

- [ ] All 6 issues closed and corresponding PRs merged into `main`
- [ ] `pytest backend/tests/test_summarize.py -v` passes (≥ 6 tests green, all with mocked Claude)
- [ ] `python scripts/generate_summaries.py` populates `summaries` table for all 100 patients
- [ ] Re-running shows 100% cache hits (`hits=100, misses=0, errors=0`)
- [ ] Spot-check 5 random summaries: each ≤ 200 words, all 5 required fields populated, disclaimer present and meaningful
- [ ] Total API spend < $1 for the 100-patient run (verified via Anthropic console)
- [ ] README documents prompt design + cache design + quality methodology
- [ ] Main shows 6 well-titled commits for Task 3

---

## 7. Time Estimate

| Issue | Estimate |
|---|---|
| #16 Schema + prompts | 20 min |
| #17 Client wrapper + retry | 15 min |
| #18 Cache | 10 min |
| #19 Batch script | 15 min (+ wait time during full run) |
| #20 Tests | 15 min |
| #21 Docs + write-up | 15 min |
| **Total** | **~90 min** (plus ~5 min real time waiting on API calls) |

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Claude API rate limit hit during 100-patient batch | Medium | Medium | Serial calls only; exponential backoff; cache aggressively so retries are cheap |
| Free tier exhausted | Low | High | Use `claude-haiku-4-5` (cheapest); test on 5-patient subset first |
| Prompt yields invalid JSON | Medium | Medium | JSON mode + schema in prompt + few-shot examples; on parse failure, log and retry once |
| Summary hallucinates facts | Medium | High | Strong "never invent facts" system prompt; spot-check methodology; negative test with empty bundle |
| Cache invalidation when bundle re-generated upstream | Low | Low | Cache key includes full bundle hash, so any change invalidates automatically |
| `ANTHROPIC_API_KEY` accidentally committed | Low | High | `.env` in gitignore; `.env.example` in repo; pre-commit hook scanning for `sk-ant-` strings (optional) |

---

## 9. Open Questions

- ❓ **Which Claude model?** Default to `claude-haiku-4-5` (fastest, cheapest, good enough for structured summarization). Escalate to `claude-sonnet-4-6` only if Haiku output quality is poor in the 5-patient pilot.
- ❓ **What if a bundle has no clinical content (e.g., a brand-new Patient with no Condition/Observation)?** Decision: still call Claude, but expect output like `chief_concern="No clinical history on record"`. Negative test covers this case.
- ❓ **Should we redact PHI before sending to Claude?** Synthea has no PHI; MIMIC demo is already deidentified. For safety, we still strip patient names from the bundle before sending — only MRN and clinical content go to the API.
