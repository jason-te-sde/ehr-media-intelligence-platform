"""Offline extractive summarizer used when no AI summary is cached.

Parses the markdown-shaped headings Synthea emits ("# Chief Complaint",
"# History of Present Illness", "# Assessment", …) and surfaces the
most-recent values back as a ``ClinicalSummary``. This keeps the modal
useful when ``ANTHROPIC_API_KEY`` is unset; an AI summary, when
generated, always takes precedence.
"""

from __future__ import annotations

import re
from datetime import datetime

from .models import ClinicalSummary

EXTRACTIVE_MODEL_NAME = "extractive-v1"
EXTRACTIVE_DISCLAIMER = (
    "Extractive summary surfaced from the most recent note. "
    "Not AI-generated; not a clinical decision."
)

_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*-\s+(.+?)\s*$", re.MULTILINE)


def _split_sections(text: str) -> dict[str, str]:
    """Split a Synthea note into `{lowercased-heading: body}`."""
    sections: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[m.group(1).lower().strip()] = text[start:end].strip()
    return sections


_DATE_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}\s*$")


def _first_sentence(s: str, max_len: int = 180) -> str:
    s = s.strip()
    if not s:
        return ""
    # Stop at the first period/newline that isn't inside an abbreviation.
    cut = re.search(r"[.\n]", s)
    sentence = s[: cut.start()].strip() if cut else s
    if len(sentence) > max_len:
        sentence = sentence[: max_len - 1].rstrip() + "…"
    return sentence


def _extract_report_date(r: str) -> str | None:
    for line in r.splitlines():
        line = line.strip()
        if _DATE_LINE.match(line):
            return line
    return None


def _report_excerpt(r: str, max_len: int = 140) -> str:
    """Return a useful one-line description of a DiagnosticReport.

    Skips the leading date line and section headings; picks the first
    bullet or sentence of body text. Falls back to a generic label.
    """
    bullets = _BULLET_RE.findall(r)
    if bullets:
        text = bullets[0].strip()
    else:
        text = ""
        for line in r.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or _DATE_LINE.match(line):
                continue
            text = line
            break
    if not text:
        text = "Diagnostic report"
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def _bullets(section_body: str, limit: int) -> list[str]:
    items = [b.strip() for b in _BULLET_RE.findall(section_body)]
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _pick_latest_note(notes: list[str]) -> str | None:
    """Each note starts with an ISO date line; pick the largest."""
    best_date = ""
    best_note: str | None = None
    for n in notes:
        head = n.strip().split("\n", 1)[0].strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", head) and head >= best_date:
            best_date = head
            best_note = n
    return best_note or (notes[0] if notes else None)


def build_extractive_summary(
    notes: list[str],
    reports: list[str],
) -> ClinicalSummary | None:
    """Return an extractive summary from raw clinical text, or ``None`` if empty."""
    notes = [n for n in notes if n and n.strip()]
    reports = [r for r in reports if r and r.strip()]
    if not notes and not reports:
        return None

    chief = "Not recorded."
    diagnoses: list[str] = []
    anomalies: list[str] = []

    latest = _pick_latest_note(notes)
    if latest:
        sections = _split_sections(latest)
        cc = sections.get("chief complaint", "")
        if cc:
            bullets = _bullets(cc, limit=5)
            chief = "; ".join(bullets) if bullets else _first_sentence(cc)
        # SNOMED-style trailing tags Synthea injects, e.g. "stress (finding)".
        finding_re = re.compile(r"([A-Z][A-Za-z0-9 ,/'\-]{2,60})\s+\((finding|disorder|situation|procedure)\)")
        seen: set[str] = set()
        for body in sections.values():
            for m in finding_re.finditer(body):
                term = m.group(1).strip().rstrip(",")
                key = term.lower()
                if key in seen:
                    continue
                seen.add(key)
                diagnoses.append(term)
                if len(diagnoses) >= 5:
                    break
            if len(diagnoses) >= 5:
                break

    # Sort reports by their leading date, newest first.
    dated_reports = sorted(
        ((_extract_report_date(r) or "", r) for r in reports),
        key=lambda t: t[0],
        reverse=True,
    )
    recent_media: list[str] = []
    for d, r in dated_reports[:5]:
        excerpt = _report_excerpt(r)
        recent_media.append(f"{excerpt} ({d})" if d else excerpt)

    flag_terms = ("abnormal", "elevated", "critical", "positive", "out of range")
    for d, r in dated_reports:
        lowered = r.lower()
        if any(t in lowered for t in flag_terms):
            excerpt = _report_excerpt(r)
            anomalies.append(f"{excerpt} ({d})" if d else excerpt)
        if len(anomalies) >= 3:
            break

    word_count = sum(
        len(s.split())
        for s in [chief, *diagnoses, *recent_media, *anomalies, EXTRACTIVE_DISCLAIMER]
    )

    # Confidence: high if we found bullets in chief + diagnoses + media; medium
    # if some sections were inferred; low if mostly empty.
    filled = sum(1 for x in (diagnoses, recent_media, anomalies) if x)
    confidence: str = "high" if filled >= 2 and chief != "Not recorded." else (
        "medium" if filled >= 1 else "low"
    )
    return ClinicalSummary(
        chief_concern=chief or "Not recorded.",
        key_diagnoses=diagnoses,
        recent_media=recent_media,
        anomalies=anomalies,
        disclaimer=EXTRACTIVE_DISCLAIMER,
        confidence=confidence,
        word_count=word_count,
        model=EXTRACTIVE_MODEL_NAME,
        generated_at=datetime.utcnow(),
    )
