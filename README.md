# EHR Media Intelligence Platform

> Onye AI Full-stack internship code assessment — an AI-powered pipeline that ingests messy EHR records, normalizes them to HL7 FHIR R4, generates LLM-authored clinical summaries, exposes a semantic search API, and surfaces results through a clinician-facing web UI.

**Status:** Tasks 1-3 complete (ingestion + FHIR + Claude summarization). Tasks 4-5 to follow.

---

## Setup

Requires Python 3.11+.

```bash
git clone https://github.com/jason-te-sde/ehr-media-intelligence-platform.git
cd ehr-media-intelligence-platform

python3 -m venv .venv          # or python3.11 / python3.14
source .venv/bin/activate
pip install -r requirements.txt
```

## Downloading the datasets

The pipeline expects three public EHR datasets under `data/` (gitignored). Fetch them with:

```bash
bash scripts/download_data.sh
```

The script is idempotent — re-runs skip datasets already on disk. Datasets fetched:

| Dataset | Size | Role | Source |
|---|---|---|---|
| Synthea FHIR R4 sample | ~90 MB | Primary JSON input (FHIR Bundles) | [synthea-sample-data](https://github.com/synthetichealth/synthea-sample-data) |
| Synthea CSV sample | ~56 MB | Primary CSV input (multi-table) | same |
| MIMIC-IV demo | ~16 MB | Real-world deidentified CSV | [PhysioNet](https://physionet.org/content/mimic-iv-demo/2.2/) |

Synthea data is fully synthetic (no PHI). MIMIC-IV demo is deidentified under HIPAA Safe Harbor and freely redistributable.

---

## Running the ingestion pipeline (Task 1)

Run on any of the supported inputs. The CLI auto-detects format by extension/directory.

```bash
# Synthea FHIR Bundles directory (555 patients)
python -m backend.ingestion.pipeline data/synthea/fhir/fhir

# Synthea CSV
python -m backend.ingestion.pipeline data/synthea/csv/csv/patients.csv

# MIMIC-IV demo (gzipped CSV)
python -m backend.ingestion.pipeline data/mimic_iv_demo/mimic-iv-clinical-database-demo-2.2/hosp/patients.csv.gz
```

Each run produces:

- **`store/store.db`** — SQLite database with the `canonical_patients` table (upserted by `record_id`)
- **`audit_report.json`** — per-record audit entries plus aggregate stats keyed by `by_reason`

Verify the SQLite write:

```bash
sqlite3 store/store.db "SELECT source_format, COUNT(*) FROM canonical_patients GROUP BY source_format"
```

## Building FHIR R4 Bundles (Task 2)

Once Task 1 has populated `canonical_patients`, build the FHIR Bundles:

```bash
pip install -e .                       # makes `backend.*` importable from scripts/
python scripts/build_bundles.py
```

Each `CanonicalPatient` is mapped to a `Bundle` (`type = "collection"`) containing a `Patient` resource and — when the source has them — `DocumentReference` and `DiagnosticReport` resources. Inside the bundle, every `subject` reference uses `urn:uuid:{patient_id}` so it resolves against the entry `fullUrl`.

Outputs:
- **`store/store.db`** — adds the `bundles` table (one row per patient, `bundle_json` is the full FHIR JSON)
- **`validation_report.json`** — per-patient pass/fail with `entries` count or error details

Verify:

```bash
sqlite3 store/store.db "SELECT COUNT(*) FROM bundles"
sqlite3 store/store.db "SELECT json_extract(bundle_json, '$.type') AS type, COUNT(*) FROM bundles GROUP BY type"
```

Verified on the full 655-patient cohort: 655/655 valid in ~32s, 56279 total FHIR resources persisted (avg 86/bundle for Synthea, 1 for MIMIC).

## Generating AI Clinical Summaries (Task 3)

Set up the Anthropic key and run the batch script:

```bash
cp .env.example .env             # then fill in ANTHROPIC_API_KEY=sk-ant-...
python scripts/generate_summaries.py [--limit N]
```

For each FHIR Bundle in `store/store.db`, the script:

1. Computes `cache_key = sha256(patient_id + bundle_json)`
2. Hits cache → done (zero API spend on re-runs)
3. Calls **Claude Haiku 4.5** with a strict system prompt (JSON-only, ≤200 words, never invent facts, always include AI disclaimer)
4. Parses + validates the JSON into a `ClinicalSummary` model
5. Word-count guard: if over 200, retry once with the same prompt
6. Saves to the `summaries` table

A `ClinicalSummary` has: `chief_concern`, `key_diagnoses[]`, `recent_media[]`, `anomalies[]`, `disclaimer`, `word_count`, `model`, `generated_at`.

Inspect the cache:

```bash
sqlite3 store/store.db "SELECT COUNT(*) FROM summaries"
sqlite3 store/store.db "SELECT chief_concern FROM summaries WHERE patient_id='<id>'"
```

## Running the tests

```bash
pytest -v
```

34 tests across ingestion (10), FHIR (16), and summarize (8). All pass on Python 3.14, pydantic 2.13, fhir.resources 8.2, anthropic 0.102.

---

## Project layout

```
backend/
├── ingestion/                    # Task 1 — raw → CanonicalPatient
│   ├── models.py                 # AuditEntry, CanonicalPatient (Pydantic v2)
│   ├── cleaner.py                # normalize_dob/gender/mrn, clean_record, deduplicate
│   ├── parsers/
│   │   ├── json_parser.py        # FHIR Bundle + NDJSON + JSON-array
│   │   └── csv_parser.py         # CSV + .csv.gz
│   └── pipeline.py               # parse → clean → dedup → audit → SQLite (CLI entry)
├── fhir/                         # Task 2 — CanonicalPatient → FHIR Bundle
│   ├── mappers/
│   │   ├── patient.py
│   │   ├── document_reference.py
│   │   └── diagnostic_report.py
│   ├── bundle.py                 # extract_documents/reports, build_bundle, validate_bundle
│   └── store.py                  # SQLite `bundles` table
├── summarize/                    # Task 3 — Bundle → ClinicalSummary
│   ├── models.py                 # ClinicalSummary (Pydantic v2)
│   ├── prompts.py                # SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
│   ├── client.py                 # anthropic wrapper, retry, JSON extraction
│   ├── cache.py                  # SQLite `summaries` table (keyed by bundle hash)
│   └── quality.py                # word-count + disclaimer guards
└── tests/
    ├── test_models.py
    ├── test_cleaner.py
    ├── test_fhir_mappers.py
    ├── test_fhir_bundle.py
    ├── test_fhir_store.py
    ├── test_summarize.py
    └── data/edge_cases.json

scripts/
├── download_data.sh              # idempotent dataset fetch
├── build_bundles.py              # CanonicalPatient[] → FHIR Bundle[] → SQLite
└── generate_summaries.py         # FHIR Bundle[] → Claude → ClinicalSummary[] → SQLite

data/                             # gitignored, populated by the download script
store/                            # gitignored, SQLite + (future) ChromaDB
```

---

## Design notes (Task 1)

**Why Synthea + MIMIC-IV demo (not hand-crafted samples).** Real public datasets exercise the cleaner's edge cases naturally — varied date formats, deidentified blanks, format-specific identifier schemes. Synthea is FHIR-native so it feeds directly into Task 2; MIMIC's CSV-with-gzip path covers a real-world dirty case (deidentified fields → empty values → audit log captures the gaps). A hand-crafted `edge_cases.json` fixture is kept for unit tests to deterministically cover corners the real data doesn't hit (e.g. multiple date formats for the same person, unparseable dates).

**Why `python-dateutil` for date parsing.** EHR exports mix `MM/DD/YYYY`, `YYYY-MM-DD`, `DD-Mon-YYYY`, and locale-specific variants. `dateutil.parser.parse` is the de-facto standard for tolerant parsing — handles all of these without a hand-rolled regex zoo. `normalize_dob` returns `(date | None, error_reason | None)` so the audit log can record _why_ parsing failed instead of swallowing the exception.

**Audit log as a delta, not a redo log.** Cleaner functions append to `audit_log` only when they actually change a value. This means an empty audit log is meaningful (record was already canonical) and the log size correlates with how dirty a record was. The dedup pass uses this directly: when two records share a fingerprint, the one with the fewer audit entries wins because it carried more correct original data.

**Field-alias table over per-source adapters.** Synthea (`FIRST`, `LAST`, `BIRTHDATE`, `GENDER`), MIMIC (`subject_id`, `gender`), and generic EHR (`dob`, `mrn`, `patient_id`) name fields differently. Instead of writing one cleaner per source, `cleaner.py` reads from each canonical key through a fallback chain. Adding a new source = adding aliases to one table.

**SQLite as a hand-off interface.** Task 2 (FHIR mapping) consumes Task 1's output. Returning a Python list from `run_pipeline()` only works if the caller is in the same process. Persisting `CanonicalPatient` to SQLite means batch scripts in Task 2/3/4 can be re-run independently without re-ingesting. The table key is `record_id` (uuid4); the patient body is the full Pydantic JSON, so the schema doesn't have to track every Pydantic field individually.

**FHIR Bundle structure for downstream Task 2.** Each Synthea patient's full Bundle (containing not just the `Patient` resource but also `Encounter`, `Observation`, `Condition`, etc.) is attached to `raw_record["_fhir_bundle"]`. When Task 2 builds its own normalized FHIR bundles, it pulls clinical content from there instead of re-fetching.

---

## Design notes (Task 2)

**Why `Bundle.type = "collection"`.** FHIR offers several bundle types (`document`, `message`, `transaction`, `batch`, `searchset`, `collection`). Our use case — a logical grouping of one patient's clinical artifacts for downstream search/summarization — matches `collection` exactly. We're not POSTing a transaction, not serving search results, and not exchanging messages.

**`urn:uuid:` references throughout.** Bundle entries carry a `fullUrl` and resources inside reference each other. Two reference styles are common: external (`Patient/{id}` resolving against a base URL) and internal (`urn:uuid:{id}` resolving against another `fullUrl` in the same bundle). We use the internal form so each bundle is self-contained — Task 3 and Task 4 can hand a bundle to any FHIR-aware tool without needing to specify a base URL.

**Lift Synthea's own DocumentReferences and DiagnosticReports, don't synthesize.** Synthea bundles already carry `DocumentReference` resources (free-text history-and-physical notes encoded as base64 attachments) and `DiagnosticReport` resources (lab summaries in `presentedForm`). `extract_documents` / `extract_reports` pull these out, decode the base64, and re-emit fresh resources via our mappers so all references retarget to our canonical `Patient.id`. This keeps clinical content authentic without copying any Synthea-specific identifiers forward.

**Validation as a roundtrip, not a static check.** `fhir.resources` enforces field types at construction time, so a bundle that *can* be built is already valid against the FHIR R4 schema. `validate_bundle` adds a JSON serialize → deserialize round-trip which catches the rare cases where the in-memory model is fine but cannot be losslessly persisted. The result is captured per-patient in `validation_report.json` so any failures surface in the build run instead of silently being dropped.

**Bundles as the source of truth for downstream tasks.** Once a bundle is in the `bundles` table, the upstream `canonical_patients` row is no longer needed for AI summarization or semantic search — the bundle contains everything a clinician would care about. This is why Task 3 and Task 4 will read from `bundles` directly rather than re-running ingestion or mapping.

---

## Design notes (Task 3)

**Why Claude Haiku 4.5.** Structured summarization with a strict schema is a constrained task — the model mostly needs to follow instructions and extract facts. Haiku is the cheapest tier with strong instruction-following, so the full 655-patient batch stays under a dollar. We can escalate to Sonnet 4.6 later by passing `--model claude-sonnet-4-6` to `generate_summaries.py`; nothing else changes.

**Prompt-as-contract.** The system prompt embeds the entire output JSON schema and the constraints (≤200 words, never invent facts, mandatory disclaimer). The user prompt embeds the bundle JSON and the same schema for self-check. Combined with Pydantic's `model_validate` on parse, that's three independent layers of structure enforcement: prompt instructions, prompt schema, runtime validation.

**Cache key = patient + bundle hash.** `sha256(patient_id + bundle_json)` means any change in the upstream bundle invalidates exactly the affected entries and nothing else. Re-running the pipeline is idempotent and cheap; running the entire 655-patient cohort costs ~$0 on re-run. The key also doesn't bake in the model name, so switching to Sonnet later means a single full re-summarization — which is what we'd want, since results would change.

**Quality validation methodology.** Three programmatic guards run on every summary: (1) Pydantic schema validation ensures every required field is present and well-typed; (2) `validate_word_count` rejects summaries over 200 words across all free-text fields combined; (3) `has_disclaimer` rejects empty disclaimers. A manual spot-check methodology lives in the writeup: pick 5 random `(bundle, summary)` pairs, diff the summary against the bundle's `Condition` and `Observation` resources, look for hallucinated diagnoses or medications. The negative test (a bundle stripped of clinical content) confirms the model says "no clinical history on record" rather than inventing one.

**Lazy + injectable client.** `client._get_client()` builds the Anthropic SDK client on first use, not on import, so tests and CI never need `ANTHROPIC_API_KEY` set. `client.set_client(mock)` lets the entire 8-test summarize suite run with a `MagicMock` — zero real API spend during development.

**Trim bundles before sending.** Synthea bundles can be hundreds of KB (each patient has ~80 resources including every Observation). The client clips the serialized JSON at 50K chars before prompting. Truncation keeps the head of the bundle (Patient + early Encounters/Conditions) which is the most useful context for the chief-concern + diagnoses summary; trailing detail mostly duplicates earlier signal.

---

## License

[MIT](LICENSE)
