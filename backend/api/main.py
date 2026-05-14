"""FastAPI app: /health, /docs, plus /search (Task 4) and /patient/{id} (Task 5)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="EHR Media Intelligence Platform",
    version="0.1.0",
    description="AI-powered EHR pipeline: ingestion → FHIR R4 → Claude summaries → semantic search.",
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


from backend.api.routes.patient import router as patient_router
from backend.api.routes.search import router as search_router

app.include_router(search_router)
app.include_router(patient_router)


# Static frontend mount. The frontend/ directory is populated in Task 5;
# until then it's empty, and "/" returns the FastAPI default index.
_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if _FRONTEND_DIR.is_dir() and any(_FRONTEND_DIR.iterdir()):
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
