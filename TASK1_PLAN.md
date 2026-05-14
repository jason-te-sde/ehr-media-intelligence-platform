# Task 1 — Data Ingestion & Cleaning

> Complete execution plan for the foundation layer of the EHR Media Intelligence Platform.
> GitHub-driven workflow: one issue → one branch → one PR → one squash-merged commit on `main`.

---

## 1. Context

**The assessment.** Onye AI Full-stack internship code assessment. Task 1 is the foundation: ingest messy heterogeneous EHR records (JSON + CSV), clean and normalize them, and emit validated Pydantic v2 models with a per-record audit log. Everything downstream (FHIR mapping, AI summaries, semantic search, UI) depends on this layer.

**Deliverable.** Public GitHub repo with clean commit history, README with setup/run/test instructions, all tests runnable via `pytest`.

**Why GitHub-standard workflow.** The deliverable is a public repo; a clean issue/PR history demonstrates engineering maturity beyond just shipping code.

---

## 2. GitHub Workflow

### 2.1 Repository
- **Name**: `ehr-media-intelligence-platform`
- **Visibility**: public
- **Create command**:
  ```bash
  gh repo create ehr-media-intelligence-platform --public \
    --source=. --remote=origin \
    --description "EHR Media Intelligence Platform (Onye AI full-stack assessment)"
  ```
- **Default branch**: `main`
- **License**: MIT

### 2.2 Labels (created once, up front)

| Label | Color | Purpose |
|---|---|---|
| `task-1` … `task-5` | blue family | Maps each PR/issue to one of the 5 assessment tasks |
| `setup` | gray | Scaffolding, repo config |
| `feature` | green | New functionality |
| `tests` | yellow | Unit / integration tests |
| `docs` | purple | README / write-up |
| `infra` | orange | Data download, dependencies, build |

### 2.3 Milestones
- `Task 1: Ingestion & Cleaning` (current focus, closes when issues #1–#8 merge)
- Reserved (not created yet): `Task 2: FHIR R4`, `Task 3: AI Summarization`, `Task 4: Semantic Search`, `Task 5: Frontend UI`

### 2.4 Branch Naming
`<type>/<issue-number>-<short-slug>` — examples:
- `chore/1-scaffolding`
- `infra/2-data-fetch`
- `feat/3-canonical-models`
- `feat/4-cleaner`
- `feat/5-parsers`
- `feat/6-pipeline`
- `test/7-edge-cases`
- `docs/8-readme`

### 2.5 Commit Convention (Conventional Commits)
`<type>(<scope>): <subject>` — examples:
- `feat(ingestion): add CanonicalPatient pydantic model`
- `fix(cleaner): handle empty MRN field`
- `test(cleaner): add 6 edge-case fixtures`
- `docs(readme): document download_data.sh usage`

### 2.6 Pull Request Workflow
1. Open PR with title mirroring the issue title
2. Body includes `Closes #N` (auto-closes the issue on merge)
3. Apply the same labels + milestone as the issue
4. **Squash-merge** to main so each PR becomes exactly one commit on `main`
5. Delete the merged branch (`--delete-branch`)

**Why squash-merge.** The assessment asks for "one commit per major task" — squashing each PR keeps history dense and readable. Task 1 will land on `main` as ~8 well-titled commits.

---

## 3. Data Strategy

We use industry-standard public datasets, not hand-crafted toy samples. This shows judgment about real-world clinical data and naturally exercises the cleaner's edge cases.

| Dataset | Role | Format | Source | Privacy |
|---|---|---|---|---|
| **Synthea 100-pt sample** | Primary input (JSON + CSV) | FHIR R4 JSON + multi-table CSV | [synthetichealth.github.io/synthea-sample-data](https://synthetichealth.github.io/synthea-sample-data) | Fully synthetic, no PHI |
| **MIMIC-IV demo** | Secondary CSV (real-world dirty) | CSV | [physionet.org/content/mimic-iv-demo](https://physionet.org/content/mimic-iv-demo) | Real ICU patients, deidentified per HIPAA Safe Harbor; demo subset is openly downloadable |
| **`edge_cases.json`** | Unit-test fixture (~10 rows) | hand-crafted JSON | local | Synthetic by hand |

Why this combination:
- **Synthea** gives us the same patients in both required formats (JSON + CSV), and it's already FHIR R4 — feeds directly into Task 2
- **MIMIC** introduces real-world inconsistencies (column-name variants, mixed date formats) that Synthea is too clean to provide
- **edge_cases.json** deliberately hits every cleaner branch in unit tests — the real datasets are too clean to cover every corner

Download URLs will be verified via `WebFetch` before issue #2 runs.

---

## 4. Issue Inventory

Eight issues, ordered by dependency. Each PR maps 1:1 to one issue.

| # | Title | Labels | Depends on | Acceptance |
|---|---|---|---|---|
| **1** | `chore: project scaffolding` | `setup` | — | `requirements.txt`, `.gitignore`, `pyproject.toml`, `backend/` skeleton, `README.md` skeleton, `pip install -r requirements.txt` succeeds on Python 3.11 |
| **2** | `infra: data fetch script` | `infra` `task-1` | #1 | `scripts/download_data.sh` idempotently fetches Synthea 100-pt FHIR + CSV and MIMIC-IV demo; `data/` is gitignored; README documents usage |
| **3** | `feat(ingestion): canonical Pydantic schema` | `feature` `task-1` | #1 | `backend/ingestion/models.py` exports `CanonicalPatient` + `AuditEntry`; minimal construction test in `test_models.py` passes |
| **4** | `feat(ingestion): record cleaner + dedup` | `feature` `task-1` | #3 | `cleaner.py` exports `normalize_dob`, `normalize_gender`, `normalize_mrn`, `clean_record`, `deduplicate`; every mutation writes to `audit_log` |
| **5** | `feat(ingestion): JSON & CSV parsers` | `feature` `task-1` | #3 | `parsers/json_parser.py` supports FHIR Bundle and NDJSON; `parsers/csv_parser.py` handles Synthea + MIMIC headers; alias map covers `DOB`/`birthDate`/`date_of_birth`/`dob` |
| **6** | `feat(ingestion): pipeline orchestrator + audit report + SQLite persistence` | `feature` `task-1` | #4, #5 | `pipeline.py` exposes `run_pipeline(path)` + CLI; writes `audit_report.json`; **persists `CanonicalPatient[]` to `store/store.db` table `canonical_patients`** (so Task 2 can load them); running on Synthea FHIR dir produces ~100 records in DB |
| **7** | `test(cleaner): 6 edge-case unit tests` | `tests` `task-1` | #4 | `backend/tests/data/edge_cases.json` fixture; `test_cleaner.py` covers: multi-format dates, missing DOB, duplicates, gender codes, MRN formats, missing names; `pytest -v` 6/6 pass |
| **8** | `docs: Task 1 README + design notes` | `docs` `task-1` | #2–#7 | README covers setup + run + test; design tradeoffs section (why Synthea, why dateutil fallback, audit-log design); write-up draft for the 1-page deliverable |
| ~~9~~ | ~~`ci: GitHub Actions pytest on PR`~~ | — | — | **Skipped** per user choice |

**Rationale for granularity** (vs. one-file-per-issue):
- Splitting `cleaner.py` into four issues creates rebase chains that hurt review velocity
- Issue #4 in a single PR shows the complete cleaning strategy at once
- Issue #5 groups JSON + CSV because they share the same "raw dict in → alias-mapped dict out" pattern

---

## 5. Per-Issue Execution Cycle (Standard 7 Steps)

Every issue follows this loop:

```bash
# 1. Sync main
git checkout main && git pull

# 2. Create branch
git checkout -b feat/3-canonical-models

# 3. Write code + run tests locally
pytest backend/tests/ -v

# 4. Commit (Conventional Commits)
git add backend/ingestion/models.py backend/tests/test_models.py
git commit -m "feat(ingestion): add CanonicalPatient pydantic schema"

# 5. Push to remote
git push -u origin feat/3-canonical-models

# 6. Open PR (linked to issue)
gh pr create \
  --title "feat(ingestion): canonical Pydantic schema" \
  --body "Closes #3

## What
- Adds CanonicalPatient + AuditEntry pydantic v2 models
- ...

## How to verify
\`\`\`bash
pytest backend/tests/test_models.py -v
\`\`\`" \
  --label "feature,task-1" \
  --milestone "Task 1: Ingestion & Cleaning"

# 7. Merge + cleanup
gh pr merge --squash --delete-branch
```

Eight issues = eight loops.

---

## 6. Final Directory Structure

```
ehr-media-intelligence-platform/
├── backend/
│   ├── __init__.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── models.py              # issue #3 — CanonicalPatient, AuditEntry
│   │   ├── cleaner.py             # issue #4 — normalizers + dedup
│   │   ├── parsers/
│   │   │   ├── __init__.py
│   │   │   ├── json_parser.py     # issue #5 — FHIR Bundle + NDJSON
│   │   │   └── csv_parser.py      # issue #5 — Synthea + MIMIC schemas
│   │   └── pipeline.py            # issue #6 — orchestrator + CLI
│   └── tests/
│       ├── __init__.py
│       ├── test_models.py         # issue #3
│       ├── test_cleaner.py        # issue #7 — 6 edge cases
│       └── data/
│           └── edge_cases.json    # issue #7 — hand-crafted fixture
├── data/                          # gitignored, populated by scripts
│   ├── synthea/
│   │   ├── fhir/                  # FHIR Bundle JSONs
│   │   └── csv/                   # patients.csv, encounters.csv, …
│   └── mimic_iv_demo/             # MIMIC-IV demo CSVs
├── store/                         # gitignored, SQLite DB + (later) ChromaDB
│   └── store.db                   # canonical_patients table created by Task 1; bundles + summaries added in Tasks 2-3
├── scripts/
│   └── download_data.sh           # issue #2 — idempotent fetch
├── requirements.txt               # issue #1
├── pyproject.toml                 # issue #1
├── .gitignore                     # issue #1 — ignores .venv/, data/, __pycache__/, audit_report.json
├── LICENSE                        # issue #1 — MIT
├── README.md                      # issue #1 skeleton, finalized in #8
└── TASK1_PLAN.md                  # this file
```

---

## 7. Module Design Details

### 7.1 `models.py` — Canonical Schema

```python
class AuditEntry(BaseModel):
    field: str
    original: str | None
    normalized: str | None
    reason: str

class CanonicalPatient(BaseModel):
    record_id: str           # uuid4, stable dedup key
    mrn: str                 # "MRN-XXXXXXXX" (8 zero-padded digits)
    given_name: str
    family_name: str
    dob: date | None         # ISO 8601; None if unparseable
    gender: Literal["male", "female", "other", "unknown"]
    source_format: Literal["json", "csv"]
    raw_record: dict         # original record preserved verbatim
    audit_log: list[AuditEntry]
```

### 7.2 `cleaner.py` — Normalization Functions

| Function | Handles |
|---|---|
| `normalize_dob(v)` | `MM/DD/YYYY`, `YYYY-MM-DD`, `DD-Mon-YYYY`, Unix timestamps → `date` (via `dateutil.parser`) |
| `normalize_gender(v)` | `M`, `F`, `1`, `2`, `Male`, `Female`, `MALE` → `"male"`/`"female"`/`"other"`/`"unknown"` |
| `normalize_mrn(v)` | Strip spaces/dashes, extract digits, zero-pad to 8, prepend `"MRN-"` |
| `clean_record(raw, fmt)` | Compose a `CanonicalPatient`, attach `audit_log` for every change |
| `deduplicate(records)` | Fingerprint `(family_name.lower(), dob, mrn)`; keep the record with the fewest audit entries (most complete); log drops |

Every cleaner appends to `audit_log` **only when it actually changes a value**, so the log is a true delta of what was modified.

### 7.3 `parsers/json_parser.py`

Two JSON sub-formats supported:
- **FHIR Bundle** (Synthea): extract `bundle["entry"][*]["resource"]` where `resourceType == "Patient"`, flatten to a dict
- **NDJSON / plain JSON array** (generic EHR exports): parse line-by-line or element-by-element

Field-alias map: `patient_dob` / `DOB` / `birthDate` / `date_of_birth` → `dob`, etc.

### 7.4 `parsers/csv_parser.py`

- Uses `csv.DictReader`
- Header normalization: lowercase + spaces → underscores
- Handles two schemas:
  - **Synthea `patients.csv`**: `Id, BIRTHDATE, FIRST, LAST, GENDER, …`
  - **MIMIC `patients.csv`**: `subject_id, gender, anchor_age, anchor_year, dod`

### 7.5 `pipeline.py` — Orchestrator

```python
def run_pipeline(path: str | Path, db_path: str = "store/store.db") -> list[CanonicalPatient]:
    records = parse_auto(path)              # auto-pick parser by extension / dir structure
    cleaned = [clean_record(r, fmt) for r in records]
    unique  = deduplicate(cleaned)
    write_audit_report(unique, "audit_report.json")
    save_canonical_patients(unique, db_path) # persists for downstream tasks
    return unique
```

Persistence schema:
```sql
CREATE TABLE IF NOT EXISTS canonical_patients (
    record_id TEXT PRIMARY KEY,
    mrn TEXT NOT NULL,
    patient_json TEXT NOT NULL,         -- full CanonicalPatient.model_dump_json()
    source_format TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Helpers in `pipeline.py`:
- `save_canonical_patients(patients, db_path)` — upsert by `record_id`
- `load_canonical_patients(db_path)` — Task 2 entry point

CLI entry: `python -m backend.ingestion.pipeline <path>`

### 7.6 `tests/data/edge_cases.json` — Unit-Test Fixture (~10 rows)

Each row deliberately triggers one cleaning rule:
- Three rows with the same DOB in different formats (`"01/15/1990"`, `"1990-01-15"`, `"15-Jan-1990"`)
- One row with empty DOB
- Two rows with identical `(family_name, dob, mrn)` for the dedup test
- Five gender variants: `"M"`, `"1"`, `"MALE"`, empty string, garbage
- One row missing `family_name`
- One row with unparseable DOB (`"not a date"`)

### 7.7 `tests/test_cleaner.py` — Six Edge-Case Tests

| # | Test | Asserts |
|---|---|---|
| 1 | Multi-format dates | All three formats normalize to `date(1990, 1, 15)` |
| 2 | Missing DOB | `dob` is `None`; audit entry recorded |
| 3 | Duplicate records | Two identical fingerprints → 1 record; drop logged in audit |
| 4 | Gender codes | `M`/`1`/`MALE` → `"male"`; junk → `"unknown"` |
| 5 | MRN formats | `12345`/`MRN-00012345`/`  012345  ` → all `MRN-00012345` |
| 6 | Missing family_name | Becomes `"UNKNOWN"`; audit logged; no crash |

---

## 8. Verification (Task 1 Overall Acceptance)

Milestone "Task 1: Ingestion & Cleaning" closes when **all** of these are true:

- [ ] All 8 issues closed and corresponding PRs merged into `main`
- [ ] `pytest backend/tests/ -v` passes (≥ 6 tests green)
- [ ] `python -m backend.ingestion.pipeline data/synthea/fhir/` outputs ~100 `CanonicalPatient` records to stdout/file
- [ ] `python -m backend.ingestion.pipeline data/mimic_iv_demo/...` runs without crashing
- [ ] `sqlite3 store/store.db "SELECT COUNT(*) FROM canonical_patients"` returns ~100
- [ ] `audit_report.json` contains real cleaning actions (date reformats, gender code mappings, occasional dedups)
- [ ] README documents setup + run + test commands; design notes section present
- [ ] `main` shows ~8 well-titled, conventional-commit-style commits for Task 1

---

## 9. Time Estimate

| Phase | Estimate |
|---|---|
| Phase 0: GitHub repo + labels + milestone | 5 min |
| Issue #1: scaffolding | 5 min |
| Issue #2: data fetch | 10 min (incl. URL verification) |
| Issue #3: models | 10 min |
| Issue #4: cleaner | 15 min |
| Issue #5: parsers | 15 min |
| Issue #6: pipeline | 10 min |
| Issue #7: tests | 15 min |
| Issue #8: README + write-up | 15 min |
| **Total** | **~100 min** |

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Synthea or PhysioNet download URL changes | Verify with `WebFetch` before issue #2; have a backup mirror noted |
| MIMIC schema differs from Synthea more than expected | Field-alias map in parsers is extensible; add MIMIC-specific aliases in issue #5 |
| FHIR Bundle nesting trips up parser | `json_parser.py` has a dedicated FHIR path that only walks `entry[*].resource` |
| `pytest` discovery issues with `backend/` layout | `pyproject.toml` sets `tool.pytest.ini_options.testpaths = ["backend/tests"]` in issue #1 |
| `gh pr merge --squash` rejected by branch protection | Disable required reviews for solo dev (`gh api -X PATCH repos/{owner}/{repo}/branches/main/protection`), or use `--admin` flag |

---

## 11. Open Items (Confirmed)

- ✅ `gh` CLI logged in
- ✅ Repo name: `ehr-media-intelligence-platform`, public
- ✅ CI (issue #9): **skipped**
- ✅ Language: English for all artifacts
- ✅ `CanonicalPatient` persistence: SQLite `canonical_patients` table (issue #6)
