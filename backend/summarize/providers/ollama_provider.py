"""Ollama-backed LLM provider.

Talks to a local Ollama daemon (default ``http://127.0.0.1:11434``) over
HTTP. Uses the ``/api/chat`` endpoint with ``format=json`` so the model
is constrained to JSON output, then validates the result against
``ClinicalSummary``.

Env vars:
- ``OLLAMA_HOST``  (default ``http://127.0.0.1:11434``)
- ``OLLAMA_MODEL`` (default ``llama3.2:3b``)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

import httpx
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.patient import Patient

from ...fhir.mappers.document_reference import decode_attachment
from ..models import ClinicalSummary
from ..prompts import SYSTEM_PROMPT
from .base import LLMProvider, ProviderError, ProviderInfo

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2:3b"
REQUEST_TIMEOUT = 180.0
MAX_NOTES = 5
MAX_REPORTS = 5
MAX_NOTE_CHARS = 1500
MAX_TOTAL_CHARS = 15_000   # small local models lose coherence past ~16K input


def _patient_demographics(p: Patient) -> str:
    name = "Unknown"
    if p.name:
        n = p.name[0]
        given = (n.given or [""])[0]
        family = n.family or ""
        name = f"{given} {family}".strip() or "Unknown"
    bits = [name]
    if p.gender:
        bits.append(p.gender)
    if p.birthDate:
        bits.append(f"born {p.birthDate}")
    return ", ".join(bits)


def _resource_date(r) -> str:
    raw = getattr(r, "date", None) or getattr(r, "effectiveDateTime", None)
    return str(raw)[:10] if raw else ""


_ANOMALY_RE = re.compile(
    r"(?i)\b(abnormal|elevated|critically|critical|positive for|out of range|hyperglycemic|hypoglycemic|fracture|injury)\b"
)


def _extract_diagnoses(notes: list[str]) -> list[str]:
    """Pull SNOMED-style trailing tags like 'stress (finding)' from note text."""
    pat = re.compile(r"([A-Z][A-Za-z0-9 ,/'\-]{2,60})\s+\((finding|disorder|situation|procedure)\)")
    seen: set[str] = set()
    out: list[str] = []
    for n in notes:
        for m in pat.finditer(n):
            term = m.group(1).strip().rstrip(",")
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(term)
            if len(out) >= 8:
                return out
    return out


def _extract_imaging_lab_events(reports: list[DiagnosticReport]) -> list[str]:
    """Build a pre-curated 'imaging/lab events' list from DiagnosticReports.

    The 3B model is bad at picking studies out of prose; we hand it
    ``"<category> <YYYY-MM-DD>"`` rows directly.
    """
    out: list[str] = []
    seen: set[str] = set()
    for r in reports[:30]:
        cat_text = "Diagnostic report"
        if r.category and r.category[0].coding:
            cat_text = r.category[0].coding[0].display or r.category[0].text or cat_text
        elif r.category and r.category[0].text:
            cat_text = r.category[0].text
        d = _resource_date(r) or "(undated)"
        line = f"{cat_text} {d}".strip()
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
        if len(out) >= 10:
            break
    return out


def _extract_anomaly_lines(notes: list[str], reports: list[str]) -> list[str]:
    """Pull sentences mentioning anomaly indicators from notes + reports."""
    out: list[str] = []
    seen: set[str] = set()
    for body in notes + reports:
        for sentence in re.split(r"(?<=[.\n])", body):
            sentence = sentence.strip()
            if not sentence or len(sentence) < 12:
                continue
            if _ANOMALY_RE.search(sentence):
                key = sentence[:80].lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(sentence[:140].rstrip())
                if len(out) >= 6:
                    return out
    return out


def bundle_extract(bundle: Bundle) -> tuple[str, dict[str, list[str]]]:
    """Render the prompt text + return deterministic fallback lists.

    Sections injected into the prompt (so the model can copy verbatim):
      1. PATIENT demographics
      2. CANDIDATE DIAGNOSES — SNOMED tags scraped from notes
      3. IMAGING / LAB EVENTS — ``<category> <date>`` rows from DiagnosticReports
      4. POTENTIAL ANOMALY MENTIONS — sentences hitting the anomaly regex
      5. LATEST NOTES — for free-form chief-concern synthesis

    The fallback dict (``key_diagnoses`` / ``recent_media`` / ``anomalies``)
    is what we drop in if the model leaves a field empty — guarantees PDF's
    "Summary must include …" requirement holds even for a 3B-class model.
    """
    patient = next(
        (e.resource for e in bundle.entry if isinstance(e.resource, Patient)),
        None,
    )
    note_resources = [e.resource for e in bundle.entry if isinstance(e.resource, DocumentReference)]
    note_resources.sort(key=_resource_date, reverse=True)
    note_texts = [decode_attachment(dr).strip() for dr in note_resources]
    note_texts = [t for t in note_texts if t]

    report_resources = [e.resource for e in bundle.entry if isinstance(e.resource, DiagnosticReport)]
    report_resources.sort(key=_resource_date, reverse=True)
    report_texts = [(r.conclusion or "").strip() for r in report_resources]
    report_texts = [t for t in report_texts if t]

    diagnoses = _extract_diagnoses(note_texts)[:5]
    imaging = _extract_imaging_lab_events(report_resources)[:5]
    anomalies = _extract_anomaly_lines(note_texts, report_texts)[:3]

    parts: list[str] = []
    if patient is not None:
        parts.append(f"PATIENT: {_patient_demographics(patient)}")
    if diagnoses:
        parts.append("\nCANDIDATE DIAGNOSES (use as `key_diagnoses` source):\n- " +
                     "\n- ".join(diagnoses))
    if imaging:
        parts.append("\nIMAGING / LAB EVENTS (use as `recent_media` source):\n- " +
                     "\n- ".join(imaging))
    if anomalies:
        parts.append("\nPOTENTIAL ANOMALY MENTIONS (use as `anomalies` source):\n- " +
                     "\n- ".join(anomalies))
    if note_texts:
        parts.append("\n--- LATEST CLINICAL NOTES ---")
        for dr, text in zip(note_resources[:MAX_NOTES], note_texts[:MAX_NOTES], strict=False):
            d = _resource_date(dr) or "(undated)"
            if len(text) > MAX_NOTE_CHARS:
                text = text[:MAX_NOTE_CHARS] + " […]"
            parts.append(f"\nNote dated {d}:\n{text}")

    text = "\n".join(parts)
    if len(text) > MAX_TOTAL_CHARS:
        text = text[:MAX_TOTAL_CHARS] + "\n[…truncated]"
    return text, {
        "key_diagnoses": diagnoses,
        "recent_media": imaging,
        "anomalies": anomalies,
    }


def bundle_to_text(bundle: Bundle) -> str:
    """Backwards-compat alias that returns just the prompt text."""
    text, _ = bundle_extract(bundle)
    return text


_USER_PROMPT = (
    "Below is one patient's clinical record. Produce a single JSON object with "
    "EXACTLY these keys:\n"
    "  - chief_concern (string, one sentence summarizing the main clinical issue)\n"
    "  - key_diagnoses (array of strings, up to 5; copy from CANDIDATE DIAGNOSES verbatim)\n"
    "  - recent_media (array of strings, up to 5; copy from IMAGING / LAB EVENTS verbatim)\n"
    "  - anomalies (array of strings, up to 3; copy from POTENTIAL ANOMALY MENTIONS or [])\n"
    "  - disclaimer (string, non-empty)\n"
    "  - confidence (one of: \"low\", \"medium\", \"high\" — based on how rich the record is)\n"
    "  - word_count (integer)\n\n"
    "Rules: stick to ≤200 total words; never invent facts. If CANDIDATE DIAGNOSES "
    "or IMAGING / LAB EVENTS exists, your arrays MUST NOT be empty.\n\n"
    "PATIENT RECORD:\n"
    "------\n"
    "{record}\n"
    "------\n\n"
    "Return ONLY the JSON object, nothing else."
)


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
    ) -> None:
        self.host = (host or os.getenv("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL") or DEFAULT_MODEL
        self.info = ProviderInfo(
            id="ollama",
            name="Ollama (local)",
            model=self.model,
            needs_api_key=False,
            local=True,
        )

    def healthcheck(self) -> tuple[bool, str]:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=3.0)
            r.raise_for_status()
        except Exception as exc:
            return False, f"Ollama daemon unreachable at {self.host}: {exc}"
        tags = {m["name"] for m in r.json().get("models", [])}
        if self.model not in tags and f"{self.model}:latest" not in tags:
            return False, f"Model '{self.model}' not pulled. Run: ollama pull {self.model}"
        return True, f"Ollama up; model '{self.model}' ready."

    def summarize(self, bundle: Bundle) -> ClinicalSummary:
        record, fallbacks = bundle_extract(bundle)
        user_prompt = _USER_PROMPT.format(record=record)
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            r = httpx.post(f"{self.host}/api/chat", json=payload, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Ollama call failed: {exc}",
                hint=f"Verify the daemon is running ({self.host}) and the model is pulled.",
                status=502,
            ) from exc

        content = (r.json().get("message") or {}).get("content", "").strip()
        if not content:
            raise ProviderError("Ollama returned empty response.", status=502)
        try:
            payload_dict = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"Ollama did not return valid JSON: {exc}",
                hint="Try a larger model (e.g. llama3.1:8b) — small models occasionally drift.",
                status=502,
            ) from exc

        # Server fields: always overwrite — the model has no business setting these.
        payload_dict["model"] = f"ollama/{self.model}"
        payload_dict["generated_at"] = datetime.now(timezone.utc).isoformat()
        # Required schema fields: fill in defaults only if missing/empty.
        if not payload_dict.get("disclaimer"):
            payload_dict["disclaimer"] = "AI-generated summary; not a clinical decision."
        if not isinstance(payload_dict.get("word_count"), int):
            payload_dict["word_count"] = 0
        # Coerce arrays + cap at PDF limits (key_diagnoses ≤5, recent_media ≤5).
        for key, cap in (("key_diagnoses", 5), ("recent_media", 5), ("anomalies", 3)):
            v = payload_dict.get(key)
            if isinstance(v, list):
                payload_dict[key] = [str(x).strip() for x in v if x][:cap]
            else:
                payload_dict[key] = []
            # If the model left an array empty, fall back to the deterministic
            # extraction from the source bundle. Guarantees PDF spec's
            # "must include … key diagnoses … recent media records" never fails
            # silently for a patient with structured FHIR data.
            if not payload_dict[key] and fallbacks.get(key):
                payload_dict[key] = fallbacks[key][:cap]
        if not payload_dict.get("chief_concern"):
            payload_dict["chief_concern"] = "No clinical history on record"
        # Normalize confidence to the schema's Literal.
        conf = str(payload_dict.get("confidence", "")).strip().lower()
        if conf not in ("low", "medium", "high"):
            conf = "medium"
        payload_dict["confidence"] = conf
        try:
            return ClinicalSummary(**payload_dict)
        except Exception as exc:
            raise ProviderError(
                f"Ollama output failed schema validation: {exc}",
                hint=f"Raw payload keys: {list(payload_dict)}",
                status=502,
            ) from exc
