# Task 4 — Semantic Search

> Embed FHIR document text and AI summaries into ChromaDB; expose `POST /search` via FastAPI returning top-5 ranked patient matches with filters and relevance scores.

GitHub workflow conventions are identical to [TASK1_PLAN.md](TASK1_PLAN.md) §2 and §5.

---

## 1. Context

**What the assessment asks** (Task 4 checklist):
- Embed all FHIR document text and AI summaries using a sentence-transformer model (e.g., `all-MiniLM-L6-v2`) or API embeddings
- Store embeddings in a lightweight vector store: `chromadb`, FAISS, or SQLite-vss
- Expose `POST /search` FastAPI endpoint that accepts a free-text query and returns the top-5 ranked patient record matches with relevance scores
- Support filtering by FHIR resource type and date range as query parameters
- Return results in under 2 seconds for 50 records

**Why this matters.** Keyword search misses paraphrase: a clinician searching "heart attack" should find records that say "myocardial infarction" or just "MI." Embeddings convert text to vectors that capture meaning, and cosine similarity surfaces conceptual matches. ChromaDB is the right scale — embedded (no separate server), persists to disk, fast enough for 100s–1000s of records. FastAPI gives us free OpenAPI docs for evaluators.

**Input.**
- FHIR Bundles from Task 2's `bundles` table
- `ClinicalSummary` objects from Task 3's `summaries` table

**Output.**
- ChromaDB collection persisted to `store/chroma/`
- Running FastAPI server at `localhost:8000` exposing `/search`, `/health`, `/docs`

---

## 2. Data Strategy

For each patient, we index **3 types of documents**:
1. The AI summary text (1 embedding per patient)
2. Each `DocumentReference.content` text (N embeddings per patient where N = number of notes)
3. Each `DiagnosticReport.conclusion` text (M embeddings per patient where M = number of reports)

Metadata stored alongside each embedding:
- `patient_id` (Patient resource ID)
- `mrn` (for display)
- `resource_type`: `"Summary"` | `"DocumentReference"` | `"DiagnosticReport"`
- `resource_date` (ISO date string, for display)
- `resource_timestamp` (Unix epoch int — **used for date range filtering** because ChromaDB's `$gte`/`$lte` only accepts numeric metadata)
- `display_name` (patient name for result card)
- `snippet` (first 200 chars of the embedded text)

Total embeddings for 100 Synthea patients ≈ 100 summaries + ~200 docs + ~150 reports = **~450 vectors**.

---

## 3. Issue Inventory (Task 4)

Seven issues. Sequence begins after Task 3 closes.

| # | Title | Labels | Depends on | Acceptance |
|---|---|---|---|---|
| **22** | `feat(search): embedding wrapper with all-MiniLM-L6-v2` | `feature` `task-4` | Task 3 closed | `embed.py` exposes `embed(text: str) -> list[float]` and `embed_batch(texts) -> list[list[float]]`; model loaded once at import; 384-dim output verified |
| **23** | `feat(search): ChromaDB collection + persistence` | `feature` `task-4` | #22 | `index.py` exposes `get_or_create_collection()`, `add_documents(docs)`, `query(text, filters, top_k)`; persists to `store/chroma/`; collection name `ehr_records` |
| **24** | `feat(search): build_index batch script` | `feature` `task-4` | #23 | `scripts/build_index.py` reads all bundles + summaries, extracts 3 doc types, embeds, upserts to ChromaDB; idempotent (re-run skips already-indexed by ID) |
| **25** | `feat(api): FastAPI scaffold + health + static mount` | `feature` `task-4` | #1 (scaffolding) | `api/main.py` creates `FastAPI()`; `GET /health` returns `{status: ok}`; `/docs` works; static files from `frontend/` mounted at `/` |
| **26** | `feat(api): POST /search with filters + scoring` | `feature` `task-4` | #23, #25 | `api/routes/search.py` exposes `POST /search` accepting `SearchRequest`, returning `SearchResponse`; filters by resource_type + date range; relevance score normalized 0-1 |
| **27** | `test(search): retrieval + filter + timing tests` | `tests` `task-4` | #26 | Tests cover: known query returns expected patient in top-5; resource_type filter excludes other types; date range filter excludes out-of-range; 50-record p95 latency < 2s |
| **28** | `docs: Task 4 README + API reference` | `docs` `task-4` | #22–#27 | README documents how to run the server, how to build the index, the `POST /search` contract with example curl; OpenAPI URL noted |

---

## 4. Module Design

### 4.1 Final Task-4 Directory Layout

```
backend/
├── search/
│   ├── __init__.py
│   ├── embed.py            # issue #22 — sentence-transformers wrapper
│   └── index.py            # issue #23 — ChromaDB persistence + query
└── api/
    ├── __init__.py
    ├── main.py             # issue #25 — FastAPI app
    ├── models.py           # SearchRequest, SearchResponse, SearchHit
    └── routes/
        ├── __init__.py
        └── search.py       # issue #26 — POST /search

scripts/build_index.py      # issue #24

backend/tests/
├── test_search_embed.py    # issue #27
├── test_search_index.py    # issue #27
└── test_api_search.py      # issue #27 — uses FastAPI TestClient
```

### 4.2 `embed.py`

```python
from sentence_transformers import SentenceTransformer

_model = SentenceTransformer("all-MiniLM-L6-v2")    # loaded once

def embed(text: str) -> list[float]:
    return _model.encode(text, normalize_embeddings=True).tolist()

def embed_batch(texts: list[str]) -> list[list[float]]:
    return _model.encode(texts, normalize_embeddings=True, batch_size=32).tolist()
```

Normalizing embeddings makes cosine similarity = dot product → cheaper queries.

### 4.3 `index.py`

```python
import chromadb

def get_or_create_collection(path: str = "store/chroma"):
    client = chromadb.PersistentClient(path=path)
    return client.get_or_create_collection(
        name="ehr_records",
        metadata={"hnsw:space": "cosine"},
    )

def add_documents(docs: list[IndexedDoc]):
    collection = get_or_create_collection()
    collection.upsert(
        ids=[d.id for d in docs],
        embeddings=[d.embedding for d in docs],
        metadatas=[d.metadata for d in docs],
        documents=[d.snippet for d in docs],
    )

def query(text: str, filters: dict, top_k: int = 5) -> list[QueryHit]:
    collection = get_or_create_collection()
    embedding = embed(text)
    where = build_where_clause(filters)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        where=where,
    )
    return parse_results(results)
```

ChromaDB's `where` clause syntax maps directly to our filters:
- Resource type: `{"resource_type": {"$in": ["DocumentReference", "DiagnosticReport"]}}`
- Date range: `{"resource_timestamp": {"$gte": 1704067200}}` (Unix epoch, **not ISO string** — ChromaDB only supports numeric comparisons)
- Combined filters use `{"$and": [...]}`

`build_where_clause(filters)` converts `SearchRequest.date_from`/`date_to` (Python `date`) → Unix int before building the clause.

### 4.4 `scripts/build_index.py`

```python
def main():
    docs = []
    for pid in list_patient_ids():
        bundle = load_bundle(pid)
        patient = bundle.entry[0].resource    # Patient is first
        display_name = format_name(patient)
        mrn = patient.identifier[0].value
        
        # 1) Summary
        summary = load_summary(pid)
        if summary:
            docs.append(make_doc(
                id=f"{pid}::summary",
                text=summary_to_text(summary),
                resource_type="Summary",
                resource_date=summary.generated_at.date(),
                patient_id=pid, mrn=mrn, display_name=display_name,
            ))
        
        # 2) DocumentReferences
        for dr in iter_resources(bundle, "DocumentReference"):
            docs.append(make_doc(id=f"{pid}::doc::{dr.id}", text=decode_attachment(dr), ...))
        
        # 3) DiagnosticReports
        for rep in iter_resources(bundle, "DiagnosticReport"):
            docs.append(make_doc(id=f"{pid}::report::{rep.id}", text=rep.conclusion, ...))
    
    # Batch-embed all at once for speed
    texts = [d.text for d in docs]
    embeddings = embed_batch(texts)
    for d, e in zip(docs, embeddings):
        d.embedding = e
    
    add_documents(docs)
    print(f"Indexed {len(docs)} documents")
```

### 4.5 `api/models.py`

```python
class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    resource_types: list[Literal["Summary", "DocumentReference", "DiagnosticReport"]] | None = None
    date_from: date | None = None
    date_to: date | None = None
    top_k: int = Field(default=5, ge=1, le=20)

class SearchHit(BaseModel):
    patient_id: str
    mrn: str
    display_name: str
    resource_type: str
    resource_date: date | None
    relevance_score: float       # 0.0–1.0
    snippet: str

class SearchResponse(BaseModel):
    hits: list[SearchHit]
    query_time_ms: int
```

### 4.6 `api/main.py`

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="EHR Media Intelligence Platform", version="0.1.0")

app.include_router(search_router, prefix="/search")
# Note: patient_router (GET /patient/{id}) is added in Task 5 issue #29.

@app.get("/health")
def health():
    return {"status": "ok"}

# Static frontend mounted last so it doesn't shadow API routes
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
```

The `frontend/` directory will be empty until Task 5 issue #30. Mounting it now is harmless — `index.html` simply doesn't exist yet, and `/` returns 404, which is fine.

### 4.7 `api/routes/search.py`

```python
@router.post("", response_model=SearchResponse)
def search(req: SearchRequest):
    t0 = time.time()
    filters = build_filters(req)
    raw_hits = index.query(req.query, filters, top_k=req.top_k)
    hits = [SearchHit(
        patient_id=h.metadata["patient_id"],
        mrn=h.metadata["mrn"],
        display_name=h.metadata["display_name"],
        resource_type=h.metadata["resource_type"],
        resource_date=parse_date(h.metadata.get("resource_date")),
        relevance_score=1.0 - h.distance,    # cosine distance → similarity
        snippet=h.document,
    ) for h in raw_hits]
    return SearchResponse(hits=hits, query_time_ms=int((time.time() - t0) * 1000))
```

---

## 5. Performance Strategy

**Target**: p95 latency < 2 seconds for 50 records (assessment requirement).
**Actual expected**: ~100ms total (assessment target gives lots of headroom).

Breakdown:
- Query embedding: ~30 ms (one short sentence on CPU)
- ChromaDB HNSW lookup over ~450 vectors: <10 ms
- Metadata filter + result assembly: <10 ms
- JSON serialization + HTTP overhead: ~20 ms

**Test plan**: `test_api_search.py` includes a timing assertion: 20 sequential queries on a 50-record index, p95 < 2000 ms.

---

## 6. Verification (Task 4 Overall Acceptance)

Milestone "Task 4: Semantic Search" closes when **all** of these are true:

- [ ] All 7 issues closed and corresponding PRs merged into `main`
- [ ] `pytest backend/tests/test_search*.py backend/tests/test_api_search.py -v` passes (≥ 6 tests)
- [ ] `python scripts/build_index.py` indexes ~450 documents across 100 patients
- [ ] `uvicorn backend.api.main:app` starts cleanly; `/health` returns 200; `/docs` renders OpenAPI page
- [ ] `curl -X POST localhost:8000/search -H "Content-Type: application/json" -d '{"query":"chest pain"}'` returns 5 hits with descending scores
- [ ] Filter test: `{"resource_types":["DiagnosticReport"]}` excludes Summary and DocumentReference hits
- [ ] Date range test: `{"date_from":"2024-01-01","date_to":"2024-12-31"}` excludes out-of-range records
- [ ] p95 latency < 500 ms on 50-record index (well under 2s requirement)
- [ ] README documents how to run the server + curl example + OpenAPI URL
- [ ] Main shows 7 well-titled commits for Task 4

---

## 7. Time Estimate

| Issue | Estimate |
|---|---|
| #22 Embed wrapper | 15 min |
| #23 ChromaDB index module | 20 min |
| #24 Batch index script | 20 min |
| #25 FastAPI scaffold | 15 min |
| #26 /search endpoint | 25 min |
| #27 Tests | 20 min |
| #28 Docs | 10 min |
| **Total** | **~125 min** |

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `all-MiniLM-L6-v2` model download fails on first run | Low | Medium | Pre-download in `scripts/build_index.py` startup; document in README that first run pulls ~80 MB |
| ChromaDB persistence corrupted by Ctrl-C mid-write | Low | Medium | Use `upsert` (idempotent); `store/chroma/` is gitignored and recreated easily |
| Embeddings too generic for clinical text | Medium | Medium | Test with known clinical synonyms (MI/heart attack, HTN/hypertension); fall back to a clinical-domain model (`pubmedbert`) if quality is poor |
| Filter clauses fail silently when metadata is missing | Medium | Low | Default `resource_date` to `"1970-01-01"` when source has no date; type-coerce in `build_filters` |
| FastAPI startup blocks on model loading (~3s) | Medium | Low | Acceptable for dev; document in README that first request after startup is fast (model already loaded) |
| 50-record latency exceeds 2s on slow CI/dev box | Low | High | Pre-load model at startup, not per-request; cache embedded queries (optional) |

---

## 9. Open Questions

- ❓ **Snippet length for result cards?** 200 chars matches a typical card design. Adjustable in `build_index.py` (single constant).
- ❓ **Should we expose `top_k` configurable per query?** Yes — defaults to 5 but client can request up to 20.
- ❓ **What if a patient has no summary yet?** Indexing skips them silently; they're still searchable via their DocumentReference/DiagnosticReport content.
- ❓ **CORS?** The frontend is served from the same FastAPI origin, so no CORS issues for the assessment scope. Add `CORSMiddleware` only if we host frontend separately later.
