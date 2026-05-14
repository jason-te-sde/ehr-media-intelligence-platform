# EHR Media Intelligence Platform — Master Plan

> Top-down execution plan covering all 5 tasks of the Onye AI Full-stack assessment.
> Detailed per-task plans: [TASK1_PLAN.md](TASK1_PLAN.md), [TASK2_PLAN.md](TASK2_PLAN.md), [TASK3_PLAN.md](TASK3_PLAN.md), [TASK4_PLAN.md](TASK4_PLAN.md), [TASK5_PLAN.md](TASK5_PLAN.md). The same workflow pattern (issues → branches → PRs → squash-merge) applies to every task.

---

## 0. Executive Summary

Build an AI-powered pipeline that ingests messy EHR records, normalizes them to **HL7 FHIR R4**, generates **LLM-authored clinical summaries**, exposes a **semantic search API**, and surfaces results through a **Tailwind/JS clinician UI**. The product is a public GitHub repo with clean issue/PR history, unit tests, README, and a 1-page write-up.

Five tasks correspond to five vertical layers in the architecture, each owning a Python package, its own tests, and its own GitHub milestone.

---

## 1. High-Level Architecture

### 1.1 Layered View (bottom-up = data flow direction)

```
┌─────────────────────────────────────────────────────────────────┐
│  L5  Frontend  (Tailwind CSS + Vanilla JS)            Task 5     │
│      Search bar · Result cards · Detail modal · Filters          │
└────────────────────────────┬─────────────────────────────────────┘
                             │  fetch()  POST /search, GET /patient/{id}
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  L4  FastAPI server                                              │
│      /search    (Task 4)    /patient/{id}  (Task 5)              │
│      /health                /docs (OpenAPI)                      │
└──────────┬────────────────────────────────┬─────────────────────┘
           │                                │
           ▼                                ▼
   ┌──────────────────┐           ┌──────────────────────────┐
   │  ChromaDB        │           │  SQLite                  │
   │  vector index    │           │  ├─ bundles              │
   │  Task 4          │           │  ├─ summaries (cached)   │
   └────────┬─────────┘           │  └─ ingestion_audit      │
            │                     └────────────┬─────────────┘
            │ embed(text)                      │
            │                                  ▼
            │                       ┌────────────────────────┐
            │                       │  Claude API            │
            │                       │  Summarization (Task 3) │
            │                       └────────────┬───────────┘
            │                                    │
            │                                    ▼
            │                       ┌────────────────────────┐
            │                       │  FHIR R4 Bundles       │
            │                       │  fhir.resources        │
            │                       │  Task 2                │
            │                       └────────────┬───────────┘
            │                                    │
            └────────── embeddings ──────────────┤
                                                 ▼
                                    ┌────────────────────────┐
                                    │  CanonicalPatient[]    │
                                    │  Pydantic v2 + audit log│
                                    │  Task 1                │
                                    └────────────┬───────────┘
                                                 │
                                                 ▼
                                    ┌────────────────────────┐
                                    │  Raw EHR datasets       │
                                    │  Synthea + MIMIC-IV demo│
                                    └────────────────────────┘
```

### 1.2 Why this shape

- **Each layer publishes a Pydantic model and consumes the layer below's model.** This makes the pipeline strongly typed end-to-end and gives downstream tasks a stable contract.
- **SQLite + local file store** instead of Postgres/S3 → matches assessment's "lightweight, local" requirement, zero ops burden.
- **ChromaDB** is embedded (no separate server) and persists to disk → same ergonomics as SQLite, but built for vectors.
- **FastAPI** gives auto-generated OpenAPI docs (free `/docs` page) — useful for evaluators inspecting the endpoint.
- **Vanilla JS + Tailwind via CDN** keeps the frontend buildless and shippable in a single `index.html` — fastest path to a working demo.

### 1.3 Repo Layout

```
ehr-media-intelligence-platform/
├── backend/
│   ├── ingestion/          # Task 1 — raw → CanonicalPatient
│   ├── fhir/               # Task 2 — CanonicalPatient → FHIR Bundle + SQLite store
│   ├── summarize/          # Task 3 — Bundle → ClinicalSummary (Claude API + cache)
│   ├── search/             # Task 4 — Bundle + Summary → vector index
│   ├── api/                # Task 4 + 5 — FastAPI app wiring everything together
│   └── tests/              # one test_*.py per module
├── frontend/               # Task 5 — index.html + app.js + tailwind via CDN
├── data/                   # gitignored, Synthea + MIMIC downloads
├── scripts/                # download_data.sh, build_bundles.py, generate_summaries.py, build_index.py
├── store/                  # gitignored — store.db (SQLite) + chroma/ (ChromaDB)
├── docs/                   # screenshots, write-up assets
├── requirements.txt
├── pyproject.toml
├── .gitignore
├── LICENSE
├── README.md
├── PROJECT_PLAN.md         # this file — top-down overview
├── TASK1_PLAN.md           # Task 1 detailed plan
├── TASK2_PLAN.md           # Task 2 detailed plan
├── TASK3_PLAN.md           # Task 3 detailed plan
├── TASK4_PLAN.md           # Task 4 detailed plan
└── TASK5_PLAN.md           # Task 5 detailed plan
```

---

## 2. Data Model Lineage

```
RawRecord (dict)                  ← raw JSON entry / CSV row
    │ Task 1: clean + normalize
    ▼
CanonicalPatient (Pydantic v2)    ← stable internal contract
    │ Task 2: map to FHIR R4
    ▼
FHIR Bundle (fhir.resources)      ← Patient + DocumentReference + DiagnosticReport
    │ Task 3: summarize via LLM
    ▼
ClinicalSummary (Pydantic v2)     ← chief_concern, diagnoses, media, anomalies, disclaimer
    │ Task 4: embed
    ▼
EmbeddedRecord (ChromaDB)         ← vector + metadata (patient_id, resource_type, date)
    │ Task 4: query
    ▼
SearchResult (Pydantic v2)        ← top-5 ranked, with relevance scores
    │ Task 5: render
    ▼
Result Card / Detail Modal (DOM)
```

Each arrow is a Python function with full type hints. End-to-end, the system can be traced by reading 5 Pydantic models.

---

## 3. Tech Stack (locked)

| Layer | Choice | Why |
|---|---|---|
| **Language** | Python 3.11 | Required by assessment; modern typing |
| **Data validation** | Pydantic v2 (≥ 2.0) | Required; fast, modern, plays well with FastAPI |
| **Date parsing** | `python-dateutil` | Tolerant parser for messy EHR date formats |
| **FHIR** | `fhir.resources` (≥ 7.1.0) | Required; Pydantic v2-native FHIR R4 schemas |
| **LLM SDK** | `anthropic` (Claude) | Free tier acceptable per assessment; better instruction following than free-tier OpenAI |
| **Retry / backoff** | `tenacity` (or hand-rolled) | Robust retries for Claude API + transient failures |
| **Embeddings** | `sentence-transformers` (`all-MiniLM-L6-v2`) | Required; 384-dim, runs locally on CPU, no API cost |
| **Vector store** | `chromadb` (embedded) | Required option; no server, persists to disk |
| **Web framework** | FastAPI | Required; OpenAPI auto-docs |
| **ASGI server** | `uvicorn` | Standard FastAPI runner |
| **DB** | SQLite (stdlib `sqlite3`) | Required; zero-config, file-based |
| **Testing** | `pytest` + `httpx` (for FastAPI TestClient) | Required |
| **Frontend** | Tailwind CSS (CDN) + Vanilla JS | Buildless; fastest path; React adds complexity without paying for itself in this scope |
| **HTTP** | Fetch API | Required |

---

## 4. Task-by-Task Plan

Each task gets: **What** (deliverable), **Why** (design rationale), **How** (approach + libraries + key files), **Verify** (acceptance criteria).

### Task 1 — Data Ingestion & Cleaning

**What.** Read raw EHR records from JSON and CSV, clean inconsistencies, output a list of `CanonicalPatient` Pydantic models with a per-record audit log.

**Why.** Real EHR exports are dirty: 4 date formats, 6 gender codes, MRN strings with leading zeros stripped, duplicate records from migrations. Every downstream task assumes a clean canonical record — fixing dirt later is exponentially more expensive than fixing it once at the front door. The audit log gives reviewers transparency into what we changed.

**How.**
- **Schema**: `CanonicalPatient(record_id, mrn, given_name, family_name, dob, gender, source_format, raw_record, audit_log)` + `AuditEntry`
- **Cleaners**: `normalize_dob` (uses `dateutil.parser`), `normalize_gender` (lookup table), `normalize_mrn` (regex + zero-pad), `deduplicate` (fingerprint by `(family_name, dob, mrn)`)
- **Parsers**: `json_parser` handles FHIR Bundle + NDJSON; `csv_parser` handles Synthea + MIMIC headers via alias map
- **Data**: Synthea 100-pt sample (FHIR JSON + CSV) + MIMIC-IV demo CSV; `edge_cases.json` for unit tests
- **Files**: `backend/ingestion/{models,cleaner,pipeline}.py` + `parsers/{json,csv}_parser.py`
- **8 issues**, detailed in [TASK1_PLAN.md](TASK1_PLAN.md)

**Verify.**
- `pytest backend/tests/test_cleaner.py -v` → 6/6 pass
- `python -m backend.ingestion.pipeline data/synthea/fhir/` → ~100 `CanonicalPatient` records
- `audit_report.json` shows real cleaning actions

**Estimated time**: ~100 min

---

### Task 2 — FHIR R4 Normalization

**What.** For each `CanonicalPatient`, generate a valid FHIR R4 `Bundle` containing at least `Patient`, `DocumentReference`, and `DiagnosticReport` resources. Validate against the FHIR R4 spec and store in SQLite.

**Why.** FHIR is the lingua franca of modern EHR interop — Epic, Cerner, athenahealth all expose FHIR APIs. By committing to FHIR R4 internally, every downstream consumer (summarization, search, future integrations) speaks a standard rather than our custom schema. Validation ensures we don't silently produce broken bundles that fail at integration time.

**How.**
- **Library**: `fhir.resources` (Pydantic v2-based) — gives schema validation for free
- **Mapping**: `canonical_to_fhir(patient: CanonicalPatient) -> Bundle`
  - `Patient`: identifier (MRN), name, gender, birthDate
  - `DocumentReference`: one per attached document/note; `subject` references the `Patient`
  - `DiagnosticReport`: one per lab result/imaging note; `subject` references the `Patient`, `result` references contained `Observation`s
- **Storage**: `store.db` (SQLite) with table `bundles(patient_id PK, bundle_json TEXT, created_at)`
- **Validation report**: collect any `ValidationError`s into `validation_report.json` with per-bundle pass/fail
- **Files**: `backend/fhir/{mapper,validator,store}.py`

**Issues** (7, see [TASK2_PLAN.md](TASK2_PLAN.md) §3):
1. `feat(fhir): Patient resource mapping` (#9)
2. `feat(fhir): DocumentReference + DiagnosticReport mapping` (#10)
3. `feat(fhir): bundle assembly + validation` (#11)
4. `feat(fhir): SQLite bundle store` (#12)
5. `feat(fhir): batch pipeline + validation report` (#13)
6. `test(fhir): mapping + validation + store tests` (#14)
7. `docs: Task 2 README + design notes` (#15)

**Verify.**
- All 100 Synthea patients produce valid bundles
- `validation_report.json` shows 100% pass (or surfaces real validation issues we then fix)
- `sqlite3 store.db "SELECT COUNT(*) FROM bundles"` → 100
- `pytest backend/tests/test_fhir.py -v` → all pass

**Estimated time**: ~105 min

---

### Task 3 — AI-Powered Clinical Summarization

**What.** For each FHIR bundle, generate a ≤200-word clinical summary covering chief concern, key diagnoses, recent media records, and flagged anomalies. Cache results to avoid redundant API spend. Return a `ClinicalSummary` Pydantic model with an explicit AI-generated disclaimer.

**Why.** Clinicians lose time scrolling through long document lists. A pre-computed summary surfaced in search results gives them a 5-second triage view. The cache is critical: each Claude call costs money and adds latency, so re-running the pipeline shouldn't re-bill us. The disclaimer is required by clinical-safety conventions — never let an AI output masquerade as a clinician's judgment.

**How.**
- **Library**: `anthropic` Python SDK
- **Model**: `claude-haiku-4-5` (cheap, fast, sufficient for structured summarization) — fall back to `claude-sonnet-4-6` if quality is poor
- **Prompt engineering**:
  - System prompt sets clinician-tone, 200-word cap, structured JSON output schema
  - User prompt = serialized FHIR bundle (trimmed to relevant fields)
  - Use **JSON mode** so the model returns `{chief_concern, diagnoses, recent_media, anomalies, disclaimer}` directly
  - Few-shot 1-2 examples to lock the format
- **Cache key**: `hash(patient_id + sha256(bundle_json))` → if hit, skip API call
- **Cache table**: `summaries(cache_key PK, patient_id, summary_json TEXT, model, created_at)`
- **Quality validation approach** (for the write-up):
  - Spot-check 5 summaries manually against the source bundle
  - Assert `len(summary.split()) <= 200`
  - Assert all required fields populated
  - Confidence/disclaimer field present and non-empty
- **Files**: `backend/summarize/{prompts,client,cache,quality}.py` + `scripts/generate_summaries.py` (batch script)

**Issues** (6, see [TASK3_PLAN.md](TASK3_PLAN.md) §3):
1. `feat(summarize): ClinicalSummary schema + prompt templates` (#16)
2. `feat(summarize): anthropic client wrapper with retry` (#17)
3. `feat(summarize): SQLite summary cache` (#18)
4. `feat(summarize): batch script` (#19)
5. `test(summarize): schema + word-count + cache tests` (#20)
6. `docs: Task 3 README + quality validation write-up` (#21)

**Verify.**
- `python scripts/generate_summaries.py` populates `summaries` table for all 100 bundles
- Re-running shows 100% cache hits, zero new API calls
- Spot-check 5 random summaries: each ≤ 200 words, contains all 5 required fields, includes disclaimer
- Total API spend < $1 on the full 100-patient run

**Estimated time**: ~90 min (plus a few minutes waiting on API calls)

---

### Task 4 — Semantic Search

**What.** Build a FastAPI backend exposing `POST /search` that takes a free-text query and returns the top-5 ranked patient record matches with relevance scores. Support filters by FHIR resource type and date range. Embed all FHIR document text + AI summaries into ChromaDB at startup (or via a build script).

**Why.** Keyword search misses paraphrase ("MI" vs "myocardial infarction" vs "heart attack"). Embeddings let clinicians query in natural language. ChromaDB is the right scale for 100s–1000s of records — no need for Pinecone/Weaviate. Filters are essential for clinical workflows ("show me chest X-rays from last month").

**How.**
- **Embedding model**: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, ~80 MB, runs locally on CPU in ms)
- **Indexed documents** per patient:
  - The AI summary text
  - Each `DocumentReference.content` text
  - Each `DiagnosticReport.conclusion` text
- **Metadata stored alongside each embedding**: `patient_id`, `mrn`, `resource_type`, `resource_date`, `display_name`
- **Index build script**: `scripts/build_index.py` — idempotent, hash-based change detection
- **API contract**:
  ```python
  class SearchRequest(BaseModel):
      query: str
      resource_types: list[str] | None = None
      date_from: date | None = None
      date_to: date | None = None
      top_k: int = 5
  
  class SearchHit(BaseModel):
      patient_id: str
      mrn: str
      resource_type: str
      resource_date: date | None
      relevance_score: float
      summary_snippet: str
  
  class SearchResponse(BaseModel):
      hits: list[SearchHit]
      query_time_ms: int
  ```
- **Performance**: ChromaDB's HNSW index returns top-5 over 50 records in <50ms; embedding the query adds ~30ms → total <100ms, well under the 2-second requirement
- **Files**: `backend/search/{embed,index,query}.py` + `backend/api/main.py` (FastAPI app) + `scripts/build_index.py`

**Issues** (7, see [TASK4_PLAN.md](TASK4_PLAN.md) §3):
1. `feat(search): embedding wrapper with all-MiniLM-L6-v2` (#22)
2. `feat(search): ChromaDB collection + persistence` (#23)
3. `feat(search): build_index batch script` (#24)
4. `feat(api): FastAPI scaffold + health + static mount` (#25)
5. `feat(api): POST /search with filters + scoring` (#26)
6. `test(search): retrieval + filter + timing tests` (#27)
7. `docs: Task 4 README + API reference` (#28)

**Verify.**
- `python scripts/build_index.py` indexes all 100 patients (~200 documents)
- `uvicorn backend.api.main:app` starts server
- `curl -X POST localhost:8000/search -d '{"query":"chest pain"}'` returns 5 hits with descending scores
- Filter test: passing `resource_types=["DiagnosticReport"]` excludes `DocumentReference` hits
- Timing: average response < 500ms on the 100-patient set
- `pytest backend/tests/test_search.py` → all pass

**Estimated time**: ~125 min

---

### Task 5 — Frontend Search & Summary UI

**What.** Clinician-facing single-page web app: search bar → ranked result cards → detail modal with full AI summary. Filter dropdowns for resource type and date range. Responsive, accessible (ARIA + keyboard), with loading and empty states.

**Why.** A search API is only useful if humans can drive it. Tailwind makes the layout work look professional in ~50 lines of HTML; vanilla JS keeps the bundle to zero. Accessibility isn't optional in clinical software — screen-reader users and keyboard-only users matter.

**How.**
- **Stack**: Single `frontend/index.html` + `frontend/app.js` + Tailwind via CDN. No build step.
- **Layout** (Tailwind):
  - Header: app title + filter row (resource-type chips, date range inputs)
  - Main: search bar (top, sticky) + result list (vertical stack of cards)
  - Card: patient name + MRN, record date, resource-type badge, relevance score bar, summary snippet
  - Modal: full summary + linked FHIR resource list, opens on card click
- **JS structure**:
  - `state` object: `{query, filters, results, loading, selected_patient}`
  - `searchHandler` debounced 300ms; calls `fetch('/search')`
  - `renderResults()` (re-renders the list)
  - `openDetail(patientId)` calls `/patient/{id}` for the full summary + resource list
- **Accessibility**:
  - `<input role="search" aria-label="Search patient records">`
  - Result cards use `<article tabindex="0">` so they're keyboard-navigable
  - Modal traps focus, `Esc` closes
  - Loading uses `aria-live="polite"`
  - Empty state has explanatory text ("No matches — try a different query")
- **Backend additions for Task 5**: a `GET /patient/{id}` endpoint that returns the full summary + resource list (small extension to the FastAPI app from Task 4)
- **Files**: `frontend/index.html`, `frontend/app.js`, `frontend/styles.css` (small overrides if needed)

**Issues** (7, see [TASK5_PLAN.md](TASK5_PLAN.md) §3):
1. `feat(api): GET /patient/{id} detail endpoint` (#29)
2. `feat(frontend): index.html scaffold + Tailwind CDN` (#30)
3. `feat(frontend): search bar + result card list` (#31)
4. `feat(frontend): filter controls (resource type + date range)` (#32)
5. `feat(frontend): patient detail modal` (#33)
6. `feat(frontend): a11y polish + loading + empty states` (#34)
7. `docs: Task 5 README + screenshot` (#35)

**Verify.**
- Browse to `localhost:8000/` (FastAPI serves the static dir): UI loads
- Typing in search bar with 300ms debounce → cards render
- Clicking a card → modal opens with full summary
- Filtering by resource type → result count drops to expected subset
- Keyboard-only navigation: Tab through cards, Enter opens modal, Esc closes
- Lighthouse accessibility score ≥ 90
- Manual test on iPhone-width viewport: cards stack, search remains usable

**Estimated time**: ~115 min

---

## 5. Cross-Cutting Concerns

### 5.1 Testing Strategy
- **Unit tests per module**: `backend/tests/test_<module>.py` mirrors `backend/<module>/`
- **No mocking of internal Pydantic models** — keep tests close to runtime behavior
- **Mock external APIs** (Claude) using `respx` or hand-rolled stubs to avoid hitting the wallet during CI
- **Integration test** for full pipeline: `tests/test_integration.py` runs ingest → FHIR → (mocked) summarize → search on a 3-patient subset

### 5.2 Error Handling
- **Ingestion**: never crash on a bad row — log to audit, return partial
- **FHIR validation**: surface errors in `validation_report.json`, don't drop bundles
- **Claude API**: exponential backoff on 429/5xx, max 3 retries
- **Search**: return empty `hits[]` (HTTP 200) on no matches, not 404

### 5.3 Security & Privacy
- **No real PHI**: Synthea is synthetic; MIMIC demo is deidentified. Document this in README.
- **API key handling**: `ANTHROPIC_API_KEY` from env only, never committed; `.env.example` shows the variable name
- **`.gitignore`**: `.env`, `data/`, `store/`, `audit_report.json`, `validation_report.json`

### 5.4 Performance
- Search response < 500ms (target: 100ms)
- Index build < 30s for 100 patients
- Pipeline end-to-end (ingest → FHIR → embed) < 60s for 100 patients excluding Claude calls

---

## 6. GitHub Workflow Recap

Same pattern as Task 1 (full detail in [TASK1_PLAN.md](TASK1_PLAN.md) §2):

- 1 milestone per task (`Task 1` … `Task 5`)
- 1 issue per cohesive feature → 1 branch (`<type>/<#>-<slug>`) → 1 PR (squash-merge)
- Conventional Commits
- Labels: `task-N`, `setup`, `feature`, `tests`, `docs`, `infra`
- Final `main` history ≈ 35 commits (6–8 per task), all well-titled

CI (GitHub Actions) skipped per current decision; could be added retroactively as a stretch issue.

---

## 7. Total Time & Issue Count

| Task | Issues | Estimated Time |
|---|---|---|
| Task 1 — Ingestion & Cleaning | 8 (#1–#8) | 100 min |
| Task 2 — FHIR R4 Normalization | 7 (#9–#15) | 105 min |
| Task 3 — AI Summarization | 6 (#16–#21) | 90 min |
| Task 4 — Semantic Search | 7 (#22–#28) | 125 min |
| Task 5 — Frontend UI | 7 (#29–#35) | 115 min |
| Phase 0 (repo setup, labels, milestones) | — | 5 min |
| **Total** | **35 issues** | **~9 hours** |

---

## 8. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Synthea download URL changes | Medium | Low | Verify with `WebFetch` before issue execution; have backup mirror noted |
| Claude API rate limits during batch summarization | Medium | Medium | Exponential backoff; serial (not parallel) calls; cache aggressively |
| `fhir.resources` strict validation rejects our mappings | Medium | Medium | Iterate on mapping until validation report is clean; surface issues rather than suppress |
| ChromaDB persistence directory permissions | Low | Low | `store/` gitignored and recreated by build script |
| Frontend CDN (Tailwind) outage during grading | Low | Medium | Fallback: vendor minified Tailwind into repo as backup |
| Anthropic key exhausted on free tier | Medium | Medium | Use Haiku (cheaper); test on 5-patient subset first before full batch |

---

## 9. Out of Scope (Explicit Non-Goals)

- Authentication / authorization (no clinician login)
- Multi-tenant data isolation
- Real-time updates / WebSockets
- Production deployment (Docker, k8s, etc.)
- Internationalization
- Audit logging beyond ingestion (no API access logs)
- HIPAA-compliant infrastructure

These would all be valuable in a real product but are explicitly outside the scope of a code assessment.

---

## 10. Open Questions (Confirmed)

- ✅ Repo: `ehr-media-intelligence-platform`, public
- ✅ `gh` CLI: logged in
- ✅ CI: skipped for now
- ✅ Language: English for all docs/comments
- ✅ Data sources: Synthea + MIMIC-IV demo + hand-crafted edge cases

---

## 11. Ready to Execute

All 5 detailed task plans are written and consistency-checked. Order of execution:

1. **Phase 0**: Create GitHub repo + all 5 milestones + labels (5 min)
2. **Task 1**: Issues #1–#8 per [TASK1_PLAN.md](TASK1_PLAN.md)
3. **Task 2**: Issues #9–#15 per [TASK2_PLAN.md](TASK2_PLAN.md)
4. **Task 3**: Issues #16–#21 per [TASK3_PLAN.md](TASK3_PLAN.md)
5. **Task 4**: Issues #22–#28 per [TASK4_PLAN.md](TASK4_PLAN.md)
6. **Task 5**: Issues #29–#35 per [TASK5_PLAN.md](TASK5_PLAN.md)

We tackle one task at a time, fully closing its milestone before starting the next. This keeps the main branch always in a deployable state and gives natural review checkpoints.
