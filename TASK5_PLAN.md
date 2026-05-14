# Task 5 — Frontend Search & Summary UI

> Clinician-facing single-page web app: search bar → ranked result cards → patient detail modal. Tailwind CSS + Vanilla JS, no build step. Responsive, accessible, with loading and empty states.

GitHub workflow conventions are identical to [TASK1_PLAN.md](TASK1_PLAN.md) §2 and §5.

---

## 1. Context

**What the assessment asks** (Task 5 checklist):
- Search bar that calls `POST /search` and renders ranked results in real time
- Result cards displaying: patient name/MRN, record date, resource type badge, relevance score, AI summary snippet
- Patient detail drawer/modal showing the full AI summary and a list of linked FHIR resources
- Filter controls: resource type dropdown, date range picker
- Responsive layout, loading states, empty-state messaging
- Accessible markup: ARIA labels, keyboard navigation for search and results

**Why this matters.** A search API is only useful if humans can drive it. The frontend is also the demo surface evaluators will look at first. Tailwind via CDN makes a professional layout cheap; vanilla JS keeps the bundle to zero. Accessibility isn't decorative — keyboard-only and screen-reader users are real clinical users, and ARIA correctness signals engineering maturity.

**Input.** A running FastAPI server from Task 4 with `POST /search`, plus a new `GET /patient/{id}` endpoint we add here.

**Output.** Static files (`frontend/index.html`, `frontend/app.js`) served by FastAPI at `localhost:8000/`. Optional `frontend/styles.css` for any small overrides.

---

## 2. Data Strategy

No data downloads — frontend talks only to the FastAPI server.

For development without backend: a `frontend/mock_search.json` stub can be loaded when `?mock=1` is in the URL. Allows working on UI before Task 4 is fully ready (defensive option, not the primary path).

---

## 3. Issue Inventory (Task 5)

Seven issues. Sequence begins after Task 4 closes.

| # | Title | Labels | Depends on | Acceptance |
|---|---|---|---|---|
| **29** | `feat(api): GET /patient/{id} detail endpoint` | `feature` `task-5` | Task 4 closed | Adds `patient_router` to `backend/api/main.py` (which Task 4 left as a placeholder); returns `PatientDetail` with full `ClinicalSummary` + list of linked FHIR resources (type, id, date, brief description); 404 on unknown ID |
| **30** | `feat(frontend): index.html scaffold + Tailwind CDN` | `feature` `task-5` | #29 | `frontend/index.html` loads Tailwind via CDN; sets viewport meta; has `<header>`, `<main>`, semantic landmarks; opens in browser via FastAPI static mount |
| **31** | `feat(frontend): search bar + result card list` | `feature` `task-5` | #30 | Typing in search bar triggers debounced (300ms) `fetch('/search')`; results render as cards with name/MRN, date, resource-type badge, relevance bar, snippet; clicking a card highlights it |
| **32** | `feat(frontend): filter controls (resource type + date range)` | `feature` `task-5` | #31 | Resource-type chips (multi-select) and two date inputs above the search bar; changes re-fire the query immediately; current filters reflected in URL hash |
| **33** | `feat(frontend): patient detail modal` | `feature` `task-5` | #31 | Clicking a card opens a modal showing full summary + linked resource list; Esc closes; focus trapped inside while open; clicking backdrop closes |
| **34** | `feat(frontend): a11y polish + loading + empty states` | `feature` `task-5` | #32, #33 | Skeleton loader during pending request; "No matches" empty state with help text; all interactive elements have ARIA labels; Lighthouse a11y score ≥ 90 |
| **35** | `docs: Task 5 README + screenshot` | `docs` `task-5` | #34 | README has Task 5 section with running instructions; one screenshot committed (`docs/screenshot.png`); a11y testing methodology documented |

---

## 4. Module Design

### 4.1 Final Task-5 Directory Layout

```
frontend/
├── index.html             # issue #30 — page skeleton
├── app.js                 # issues #31, #32, #33, #34 — all interactivity
├── styles.css             # optional, minimal overrides
└── mock_search.json       # dev-only stub

backend/api/routes/
└── patient.py             # issue #29 — GET /patient/{id}

docs/
└── screenshot.png         # issue #35

backend/tests/
└── test_api_patient.py    # issue #29
```

### 4.2 `backend/api/routes/patient.py`

```python
class LinkedResource(BaseModel):
    resource_type: str          # "DocumentReference" | "DiagnosticReport"
    resource_id: str
    date: date | None
    title: str                  # short label, e.g. "Discharge Summary"

class PatientDetail(BaseModel):
    patient_id: str
    mrn: str
    display_name: str
    dob: date | None
    gender: str
    summary: ClinicalSummary | None
    linked_resources: list[LinkedResource]

@router.get("/{patient_id}", response_model=PatientDetail)
def get_patient(patient_id: str):
    bundle = load_bundle(patient_id)
    if bundle is None:
        raise HTTPException(404, "patient not found")
    summary = load_summary_for_patient(patient_id)
    return assemble_detail(bundle, summary)
```

### 4.3 `frontend/index.html` — Layout Skeleton

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EHR Media Intelligence</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-900">
  <header class="bg-white border-b shadow-sm sticky top-0 z-10">
    <div class="max-w-5xl mx-auto px-4 py-3">
      <h1 class="text-xl font-semibold">EHR Media Intelligence</h1>
      <!-- Filters: resource-type chips + date range inputs -->
      <div id="filters" role="region" aria-label="Search filters" class="mt-2"></div>
      <!-- Search bar -->
      <input id="search" type="search" role="search" aria-label="Search patient records"
             placeholder="Search clinical notes, labs, summaries..."
             class="mt-2 w-full px-4 py-2 border rounded">
    </div>
  </header>
  <main class="max-w-5xl mx-auto px-4 py-6">
    <div id="status" aria-live="polite" class="sr-only"></div>
    <ul id="results" role="list" class="space-y-3"></ul>
    <div id="empty" hidden class="text-center text-slate-500 py-12">
      <p>No matches. Try a different query or relax filters.</p>
    </div>
  </main>
  <div id="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" hidden
       class="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-20">
    <div class="bg-white rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto p-6">
      <!-- Content rendered by app.js -->
    </div>
  </div>
  <script type="module" src="/app.js"></script>
</body>
</html>
```

### 4.4 `frontend/app.js` — State + Handlers

```javascript
const state = {
  query: "",
  filters: { resource_types: [], date_from: null, date_to: null },
  results: [],
  loading: false,
  selectedPatient: null,
};

const searchDebounced = debounce(runSearch, 300);

document.getElementById("search").addEventListener("input", e => {
  state.query = e.target.value;
  searchDebounced();
});

async function runSearch() {
  if (!state.query) return clearResults();
  state.loading = true;
  renderLoading();
  const res = await fetch("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: state.query,
      resource_types: state.filters.resource_types.length ? state.filters.resource_types : null,
      date_from: state.filters.date_from,
      date_to: state.filters.date_to,
      top_k: 5,
    }),
  });
  state.results = (await res.json()).hits;
  state.loading = false;
  renderResults();
}

async function openDetail(patientId) {
  const res = await fetch(`/patient/${patientId}`);
  const detail = await res.json();
  state.selectedPatient = detail;
  renderModal();
  trapFocus(document.getElementById("modal"));
}

document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !document.getElementById("modal").hidden) closeModal();
});
```

### 4.5 Accessibility Specifics

| Element | A11y treatment |
|---|---|
| Search input | `role="search"`, `aria-label`, autocomplete off |
| Filter chips | `<button aria-pressed="…">` with visible toggle state |
| Result list | `<ul role="list">`, each `<li>` contains `<article tabindex="0">` so cards are keyboard-focusable |
| Card | Enter/Space opens modal; `aria-label` summarizes the card's content |
| Modal | `role="dialog"`, `aria-modal="true"`, focus trap, Esc to close, backdrop click to close |
| Loading | `<div aria-live="polite">` announces "Loading results" |
| Empty state | Plain `<p>` with help text; no `aria-live` to avoid double announcement |
| Score bar | `<div role="meter" aria-valuemin="0" aria-valuemax="1" aria-valuenow="0.87">` |

### 4.6 Responsive Strategy

Tailwind responsive utilities only:
- `sm:` breakpoint at 640px: filter row stacks vertically below this
- `md:` breakpoint at 768px: result cards stay 1-column always (clinical use case is more like a list than a grid)
- Touch targets: all interactive elements ≥ 44×44 px (Tailwind `min-h-11 min-w-11`)

### 4.7 Loading & Empty States

| State | What renders | Example |
|---|---|---|
| Initial (no query) | Empty results area with "Start typing to search" hint | grayed-out illustration |
| Loading | 3 skeleton cards animated with `animate-pulse` | placeholder bars |
| Has results | List of `SearchHit` cards | filled |
| No results | "No matches" message with suggestions | "Try removing a filter or using different terms" |
| Error | Toast at top: "Search failed — please try again" | error styling |

---

## 5. Verification (Task 5 Overall Acceptance)

Milestone "Task 5: Frontend UI" closes when **all** of these are true:

- [ ] All 7 issues closed and corresponding PRs merged into `main`
- [ ] `pytest backend/tests/test_api_patient.py -v` passes
- [ ] Browse to `http://localhost:8000/` — UI loads with no console errors
- [ ] Typing "chest pain" (or similar) returns ranked result cards within 1s
- [ ] Clicking a card opens modal with full summary + linked resource list
- [ ] Filter changes immediately re-query
- [ ] Keyboard-only navigation: Tab to search, type query, Tab to first card, Enter opens modal, Esc closes
- [ ] Resize browser to iPhone-width: layout remains usable, no horizontal scroll
- [ ] Lighthouse a11y audit ≥ 90 (run on a result-laden page)
- [ ] Screenshot committed to `docs/screenshot.png`
- [ ] README has Task 5 section with running + testing instructions
- [ ] Main shows 7 well-titled commits for Task 5

---

## 6. Time Estimate

| Issue | Estimate |
|---|---|
| #29 GET /patient/{id} | 15 min |
| #30 HTML scaffold + Tailwind | 10 min |
| #31 Search bar + result cards | 25 min |
| #32 Filter controls | 15 min |
| #33 Detail modal | 20 min |
| #34 A11y + loading + empty | 20 min |
| #35 Docs + screenshot | 10 min |
| **Total** | **~115 min** |

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Tailwind CDN unreachable during grading | Low | Medium | Document fallback: download `tailwind.min.css` into `frontend/` and switch the `<script>` tag |
| Search request races (older response overwrites newer) | Medium | Medium | Track a request ID; ignore responses whose ID isn't the latest |
| Modal focus trap leaks (Tab escapes the modal) | Medium | Medium | Use a small focus-trap utility (~20 lines); test with keyboard-only walkthrough |
| Date inputs vary by browser (Safari is finicky) | Medium | Low | Use plain `<input type="date">` and accept browser native UI; document this in README |
| Mobile viewport tests skipped due to time | Medium | Low | DevTools device-mode quick check before submission |
| Lighthouse a11y < 90 | Medium | Medium | Issue #34 budgets time for fixes; common offenders: missing `<label>`, low contrast — both easy to fix |

---

## 8. Open Questions

- ❓ **Drawer vs modal for patient detail?** Modal is simpler for keyboard/focus management and matches assessment phrasing ("drawer/modal"). Default to modal.
- ❓ **Should filters be persisted in URL?** Yes — issue #32 reflects current filter state in `location.hash` so refresh/back-button preserves state.
- ❓ **Score visualization?** A horizontal bar (Tailwind: `<div class="h-2 bg-blue-500" style="width:{score*100}%">`) — visually scannable, no chart library needed.
- ❓ **Dark mode?** Out of scope. Keep light theme only; assessment doesn't require it.
