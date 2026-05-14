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
