# EHR Media Intelligence Platform

> Onye AI Full-stack internship code assessment — an AI-powered pipeline that ingests messy EHR records, normalizes them to HL7 FHIR R4, generates LLM-authored clinical summaries, exposes a semantic search API, and surfaces results through a clinician-facing web UI.

**Status:** Task 1 (ingestion & cleaning) complete. Tasks 2-5 to follow.

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

## Running the tests

```bash
pytest -v
```

Currently 10 tests: 3 model sanity checks + 6 cleaner edge cases + 1 bonus for unparseable DOB handling. All pass on Python 3.14 / pydantic 2.13.

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
└── tests/
    ├── test_models.py
    ├── test_cleaner.py
    └── data/edge_cases.json

scripts/
└── download_data.sh              # idempotent dataset fetch

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

## License

[MIT](LICENSE)
