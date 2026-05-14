# EHR Media Intelligence Platform

> Onye AI Full-stack internship code assessment — an AI-powered pipeline that ingests messy EHR records, normalizes them to HL7 FHIR R4, generates LLM-authored clinical summaries, exposes a semantic search API, and surfaces results through a clinician-facing web UI.

**Status:** Task 1 in progress.

## Setup

Requires Python 3.11+.

```bash
git clone https://github.com/jason-te-sde/ehr-media-intelligence-platform.git
cd ehr-media-intelligence-platform

python3 -m venv .venv          # or python3.11 / python3.14
source .venv/bin/activate
pip install -r requirements.txt
```

## Running tests

```bash
pytest -v
```

## Downloading the datasets

The pipeline expects three public EHR datasets under `data/` (gitignored). Fetch them with:

```bash
bash scripts/download_data.sh
```

The script is idempotent — re-runs skip datasets that are already on disk. Datasets fetched:

| Dataset | Size | Role | Source |
|---|---|---|---|
| Synthea FHIR R4 sample | ~90 MB | Primary JSON input (FHIR Bundles) | [synthea-sample-data](https://github.com/synthetichealth/synthea-sample-data) |
| Synthea CSV sample | ~56 MB | Primary CSV input (multi-table) | same |
| MIMIC-IV demo | ~16 MB | Real-world deidentified CSV | [PhysioNet](https://physionet.org/content/mimic-iv-demo/2.2/) |

Synthea data is fully synthetic (no PHI). MIMIC-IV demo is deidentified under HIPAA Safe Harbor and freely redistributable.

## Running the pipeline

Detailed run instructions will be added per task as features land.

## Project layout

```
backend/
├── ingestion/      # Task 1 — raw → CanonicalPatient
│   ├── models.py
│   ├── cleaner.py
│   ├── parsers/
│   └── pipeline.py
└── tests/

scripts/            # download_data.sh and batch utilities
```

## License

[MIT](LICENSE)
