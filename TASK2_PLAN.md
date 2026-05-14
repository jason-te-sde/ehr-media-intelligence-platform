# Task 2 — FHIR R4 Normalization

> Map cleaned `CanonicalPatient` records into HL7 FHIR R4 `Bundle`s containing `Patient`, `DocumentReference`, and `DiagnosticReport` resources; validate each bundle; persist to SQLite.

GitHub workflow, labels, branch naming, commit convention, and per-issue execution cycle are identical to [TASK1_PLAN.md](TASK1_PLAN.md) §2 and §5 — not repeated here.

---

## 1. Context

**What the assessment asks** (Task 2 checklist):
- Map at minimum three resource types: `Patient`, `DocumentReference`, `DiagnosticReport`
- Use `fhir.resources` Python library for schema validation
- Generate a FHIR `Bundle` (JSON) per patient with correct cross-references (`subject`, `encounter`)
- Validate all bundles against FHIR R4 spec; surface errors in a report
- Store bundles in a local SQLite or file-based store

**Why this matters.** FHIR R4 is the lingua franca of modern EHR interoperability — Epic/Cerner/athena all speak FHIR. Committing to FHIR internally means every downstream consumer (summarization, search, future Epic integrations) gets a standard schema for free. Validation is the gatekeeper: an unvalidated bundle is a future production incident.

**Input.** `CanonicalPatient` objects loaded from `store/store.db` table `canonical_patients` (persisted by Task 1 pipeline — see [TASK1_PLAN.md §7.5](TASK1_PLAN.md)).

**Output.**
- `store.db` table `bundles(patient_id PK, bundle_json TEXT, created_at)` with one row per patient
- `validation_report.json` enumerating per-bundle pass/fail with FHIR error messages

---

## 2. Data Strategy

Reuses Task 1's data — no new downloads.

Synthea also publishes patient records as FHIR R4 bundles directly, which gives us a **reference target**: we can compare our generated bundle structure against Synthea's for the same patient. Synthea-FHIR is therefore both an input (via Task 1) and a sanity check (manual diff for a few patients during issue #5).

The `DocumentReference` and `DiagnosticReport` content comes from the raw records' free-text fields:
- Synthea CSV: `notes`, `imaging`, `observations` columns
- MIMIC demo: discharge note placeholder text, lab event text
- For records without document/report data, we still emit a minimal valid `Patient` resource — DocumentReference/DiagnosticReport are present only when the source has matching content

---

## 3. Issue Inventory (Task 2)

Six issues, ordered by dependency. Sequence begins after Task 1 is closed.

| # | Title | Labels | Depends on | Acceptance |
|---|---|---|---|---|
| **9** | `feat(fhir): Patient resource mapping` | `feature` `task-2` | Task 1 closed | `mappers/patient.py` exposes `canonical_to_patient(p) -> Patient`; `Patient.identifier` carries the MRN; gender/birthDate populated; `fhir.resources` validates the resource in isolation |
| **10** | `feat(fhir): DocumentReference + DiagnosticReport mapping` | `feature` `task-2` | #9 | `mappers/document_reference.py` and `mappers/diagnostic_report.py` produce valid resources from raw notes/labs; `subject` references constructed but not yet resolved |
| **11** | `feat(fhir): bundle assembly + validation` | `feature` `task-2` | #10 | `bundle.py` exposes `build_bundle(canonical, source_records) -> Bundle`; bundle type = `collection`; all `subject` references resolve internally via fullUrl; `validate_bundle(bundle)` returns list of errors |
| **12** | `feat(fhir): SQLite bundle store` | `feature` `task-2` | #11 | `store.py` exposes `save_bundle(bundle)` and `load_bundle(patient_id)`; SQLite schema initialized via `init_db()`; bundles serialize as JSON text |
| **13** | `feat(fhir): batch pipeline + validation report` | `feature` `task-2` | #12 | `scripts/build_bundles.py` iterates all `CanonicalPatient`s, builds bundles, validates, persists; emits `validation_report.json` with per-patient pass/fail and error details |
| **14** | `test(fhir): mapping + validation + store tests` | `tests` `task-2` | #11, #12 | `test_fhir_mappers.py`, `test_fhir_bundle.py`, `test_fhir_store.py`; at minimum 8 tests covering: patient identifier roundtrip, bundle reference resolution, validation error surfacing, store roundtrip |
| **15** | `docs: Task 2 README section + design notes` | `docs` `task-2` | #9–#14 | README updated with FHIR design choices (why `Bundle.type = "collection"`, how references work, validation strategy); 1-2 paragraphs added to write-up draft |

---

## 4. Module Design

### 4.1 Final Task-2 Directory Layout

```
backend/fhir/
├── __init__.py
├── mappers/
│   ├── __init__.py
│   ├── patient.py              # issue #9
│   ├── document_reference.py   # issue #10
│   └── diagnostic_report.py    # issue #10
├── bundle.py                   # issue #11 — assembly + validation entry
└── store.py                    # issue #12 — SQLite persistence

scripts/build_bundles.py        # issue #13

backend/tests/
├── test_fhir_mappers.py        # issue #14
├── test_fhir_bundle.py         # issue #14
└── test_fhir_store.py          # issue #14
```

### 4.2 `mappers/patient.py`

```python
from fhir.resources.patient import Patient
from fhir.resources.identifier import Identifier
from fhir.resources.humanname import HumanName

def canonical_to_patient(c: CanonicalPatient) -> Patient:
    return Patient(
        id=c.record_id,
        identifier=[Identifier(system="urn:onye:mrn", value=c.mrn)],
        name=[HumanName(family=c.family_name, given=[c.given_name])],
        gender=c.gender if c.gender != "unknown" else None,
        birthDate=c.dob.isoformat() if c.dob else None,
    )
```

Gender mapping: Task 1's `"male"/"female"/"other"/"unknown"` aligns directly with FHIR's `AdministrativeGender` value set (we drop `"unknown"` to None since FHIR allows missing).

### 4.3 `mappers/document_reference.py`

For each free-text document/note in the raw record:

```python
def to_document_reference(
    text: str,
    patient_id: str,        # the same id used in Patient.id + bundle fullUrl
    doc_type: str,
    date: date,
) -> DocumentReference:
    return DocumentReference(
        status="current",
        subject=Reference(reference=f"urn:uuid:{patient_id}"),  # matches bundle fullUrl
        date=date.isoformat(),
        type=CodeableConcept(text=doc_type),  # e.g. "Discharge Summary"
        content=[DocumentReferenceContent(
            attachment=Attachment(
                contentType="text/plain",
                data=base64.b64encode(text.encode()).decode(),
            )
        )],
    )
```

### 4.4 `mappers/diagnostic_report.py`

```python
def to_diagnostic_report(
    conclusion: str,
    patient_id: str,
    category: str,         # "LAB" | "RAD" | "PAT"
    date: date,
) -> DiagnosticReport:
    return DiagnosticReport(
        status="final",
        subject=Reference(reference=f"urn:uuid:{patient_id}"),  # matches bundle fullUrl
        effectiveDateTime=date.isoformat(),
        category=[CodeableConcept(text=category)],
        code=CodeableConcept(text="Clinical Note"),
        conclusion=conclusion,
    )
```

### 4.5 `bundle.py`

```python
def extract_documents(raw: dict) -> list[dict]:
    """Normalize Synthea/MIMIC raw_record into a uniform list of {text, type, date}."""
    docs = []
    # Synthea CSV: 'notes' field
    if "NOTES" in raw and raw["NOTES"]:
        docs.append({"text": raw["NOTES"], "type": "Clinical Note", "date": raw.get("DATE")})
    # Synthea FHIR: walk bundle.entry for existing DocumentReference resources
    if "entry" in raw:
        for e in raw["entry"]:
            r = e.get("resource", {})
            if r.get("resourceType") == "DocumentReference":
                docs.append(_synthea_doc_to_dict(r))
    # MIMIC: noteevents text (if present) → one doc per row
    if "noteevents" in raw:
        for n in raw["noteevents"]:
            docs.append({"text": n["text"], "type": n.get("category", "Note"), "date": n.get("chartdate")})
    return docs

def extract_reports(raw: dict) -> list[dict]:
    """Normalize raw_record into a uniform list of {conclusion, category, date}."""
    # Similar logic: walk Synthea Observations + MIMIC labevents
    ...

def build_bundle(canonical: CanonicalPatient) -> Bundle:
    patient = canonical_to_patient(canonical)
    entries = [BundleEntry(
        fullUrl=f"urn:uuid:{patient.id}",
        resource=patient,
    )]
    
    for note in extract_documents(canonical.raw_record):
        dr = to_document_reference(note["text"], patient.id, note["type"], note["date"])
        entries.append(BundleEntry(fullUrl=f"urn:uuid:{dr.id}", resource=dr))
    
    for lab in extract_reports(canonical.raw_record):
        rep = to_diagnostic_report(lab["conclusion"], patient.id, lab["category"], lab["date"])
        entries.append(BundleEntry(fullUrl=f"urn:uuid:{rep.id}", resource=rep))
    
    return Bundle(type="collection", entry=entries)

def validate_bundle(bundle: Bundle) -> list[str]:
    """Returns list of validation error messages; empty = valid."""
    try:
        bundle.model_dump()       # triggers pydantic v2 validation
        return []
    except ValidationError as e:
        return [str(err) for err in e.errors()]
```

**Reference style**: we use `urn:uuid:<id>` fullUrls so all references inside the bundle resolve internally — no external base URL needed, and bundles are self-contained when serialized.

**Source extraction**: `extract_documents` / `extract_reports` are the seam where Synthea vs MIMIC differences are normalized. Each branch handles one source shape and produces the same `{text, type, date}` dict.

### 4.6 `store.py`

```python
DDL = """
CREATE TABLE IF NOT EXISTS bundles (
    patient_id TEXT PRIMARY KEY,
    bundle_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def init_db(db_path: str = "store/store.db"): ...
def save_bundle(bundle: Bundle, db_path: str = "store/store.db"): ...
def load_bundle(patient_id: str, db_path: str = "store/store.db") -> Bundle: ...
def list_patient_ids(db_path: str = "store/store.db") -> list[str]: ...
```

### 4.7 `scripts/build_bundles.py`

```python
def main():
    init_db()                                 # creates `bundles` table in store/store.db
    canonicals = load_canonical_patients()    # from Task 1's `canonical_patients` table
    report = []
    for c in canonicals:
        bundle = build_bundle(c)
        errors = validate_bundle(bundle)
        if errors:
            report.append({"patient_id": c.record_id, "status": "invalid", "errors": errors})
            continue
        save_bundle(bundle)
        report.append({"patient_id": c.record_id, "status": "valid"})
    Path("validation_report.json").write_text(json.dumps(report, indent=2))
    summary = collections.Counter(r["status"] for r in report)
    print(f"Bundles built: {summary}")
```

---

## 5. Verification (Task 2 Overall Acceptance)

Milestone "Task 2: FHIR R4 Normalization" closes when **all** of these are true:

- [ ] All 6 issues closed and corresponding PRs merged into `main`
- [ ] `pytest backend/tests/test_fhir_*.py -v` passes (≥ 8 tests green)
- [ ] `python scripts/build_bundles.py` produces 100 bundles in `store.db`
- [ ] `validation_report.json` shows ≥ 95% valid (any failures investigated and either fixed or documented as known limitations)
- [ ] `sqlite3 store/store.db "SELECT COUNT(*) FROM bundles"` returns ~100
- [ ] One sample bundle manually inspected: matches Synthea's bundle structure for the same patient (rough diff)
- [ ] README has Task 2 section with design rationale
- [ ] Main shows 6 well-titled commits for Task 2

---

## 6. Time Estimate

| Issue | Estimate |
|---|---|
| #9 Patient mapper | 15 min |
| #10 DocumentRef + DiagnosticReport mappers | 20 min |
| #11 Bundle assembly + validation | 20 min |
| #12 SQLite store | 10 min |
| #13 Batch pipeline + report | 15 min |
| #14 Tests | 15 min |
| #15 Docs | 10 min |
| **Total** | **~105 min** |

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `fhir.resources` validation rejects our resources due to strict cardinality | Medium | Medium | Iterate per resource type; minimum-viable resources first, expand only when reviewer requests |
| Raw data has no document/report text → empty `DocumentReference` | High | Low | Skip emission when source field is empty; document this in README |
| Synthea raw FHIR bundles structurally differ from ours | Low | Low | We don't have to match Synthea byte-for-byte; we just need FHIR R4 compliance |
| Bundle JSON exceeds SQLite default row size | Low | Low | SQLite supports rows up to ~1 GB; not a concern at this scale |
| Cross-reference resolution (`subject` pointing at non-existent Patient) | Medium | High | All references use `urn:uuid:` fullUrls; bundle assembly ensures Patient entry is always first |

---

## 8. Open Questions (resolved)

- ✅ **Canonical patient persistence**: resolved — Task 1 issue #6 now persists to `store/store.db` table `canonical_patients` (see [TASK1_PLAN.md §7.5](TASK1_PLAN.md)).
- ✅ **`DocumentReference.content` source**: resolved via `extract_documents()` (TASK2 §4.5) — pulls from Synthea `NOTES`/embedded `DocumentReference` resources and MIMIC `noteevents`. If a patient has no source text, no `DocumentReference` is emitted.
- ❓ **`pydantic` version compatibility with `fhir.resources`**: `fhir.resources>=7.1.0` is Pydantic v2-native. Pin this version in `requirements.txt` (issue #1). If we end up with an older release, the code samples here use `.model_dump()` which won't work on v1 — adjust accordingly.
