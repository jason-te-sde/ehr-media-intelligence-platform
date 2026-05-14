"""Normalize raw EHR records into ``CanonicalPatient`` instances.

Every cleaning function appends to ``audit_log`` only when it actually
changes a value, so the audit log is a true delta of what was modified.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from dateutil import parser as dateutil_parser

from .models import AuditEntry, CanonicalPatient, Gender, SourceFormat

# ---------------------------------------------------------------------------
# Field aliases — Synthea / MIMIC / generic EHR sources name fields differently.
# The parsers map source dicts to a uniform shape; cleaner.py then reads from
# this canonical key set first, falling back through the aliases.
# ---------------------------------------------------------------------------

_DOB_KEYS = ("dob", "DOB", "date_of_birth", "birthDate", "BIRTHDATE")
_GENDER_KEYS = ("gender", "Gender", "GENDER", "sex")
_MRN_KEYS = ("mrn", "MRN", "patient_id", "Id", "id", "subject_id")
_GIVEN_KEYS = ("given_name", "first_name", "FIRST", "given", "first")
_FAMILY_KEYS = ("family_name", "last_name", "LAST", "family", "last")

_GENDER_MAP: dict[str, Gender] = {
    "m": "male", "male": "male", "1": "male",
    "f": "female", "female": "female", "2": "female",
    "o": "other", "other": "other",
    "u": "unknown", "unknown": "unknown", "": "unknown",
}

_MRN_DIGITS_RE = re.compile(r"\d+")


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> tuple[str | None, Any]:
    """Return (matching_key, value) of the first key found in ``raw``, else (None, None)."""
    for k in keys:
        if k in raw and raw[k] not in (None, ""):
            return k, raw[k]
    return None, None


# ---------------------------------------------------------------------------
# Field-level normalizers
# ---------------------------------------------------------------------------

def normalize_dob(value: Any) -> tuple[date | None, str | None]:
    """Parse a DOB into a ``date``. Returns ``(date | None, error_reason | None)``."""
    if value is None or str(value).strip() == "":
        return None, "missing DOB"
    raw = str(value).strip()
    try:
        parsed = dateutil_parser.parse(raw, dayfirst=False)
        return parsed.date(), None
    except (ValueError, TypeError, OverflowError):
        return None, f"unparseable date: {raw!r}"


def normalize_gender(value: Any) -> Gender:
    """Map common gender encodings to the canonical Literal."""
    key = str(value).strip().lower() if value is not None else ""
    return _GENDER_MAP.get(key, "unknown")


def normalize_mrn(value: Any) -> str:
    """Strip non-digits, zero-pad to 8, prepend ``MRN-``.

    Inputs without any digits become ``MRN-00000000`` so the field is always
    well-formed (the audit log will flag this case).
    """
    raw = str(value).strip() if value is not None else ""
    digits = "".join(_MRN_DIGITS_RE.findall(raw))
    if not digits:
        digits = "0"
    return f"MRN-{digits.zfill(8)}"


# ---------------------------------------------------------------------------
# Record-level cleaning
# ---------------------------------------------------------------------------

def clean_record(raw: dict[str, Any], source_format: SourceFormat) -> CanonicalPatient:
    """Compose a ``CanonicalPatient`` from a raw source dict.

    Each normalization step appends to ``audit_log`` only if it actually
    changes a value, so the log is a true delta of what was modified.
    """
    audit: list[AuditEntry] = []

    def log(field: str, original: Any, normalized: Any, reason: str) -> None:
        audit.append(AuditEntry(
            field=field,
            original=None if original is None else str(original),
            normalized=None if normalized is None else str(normalized),
            reason=reason,
        ))

    # --- DOB ---
    _, raw_dob = _first_present(raw, _DOB_KEYS)
    parsed_dob, dob_err = normalize_dob(raw_dob)
    if dob_err:
        log("dob", raw_dob, None, dob_err)
    elif parsed_dob is not None and str(raw_dob).strip() != parsed_dob.isoformat():
        log("dob", raw_dob, parsed_dob.isoformat(), "normalized date format")

    # --- gender ---
    _, raw_gender = _first_present(raw, _GENDER_KEYS)
    norm_gender = normalize_gender(raw_gender)
    if raw_gender is None or str(raw_gender).strip().lower() != norm_gender:
        log("gender", raw_gender, norm_gender, "normalized gender code")

    # --- MRN ---
    _, raw_mrn = _first_present(raw, _MRN_KEYS)
    norm_mrn = normalize_mrn(raw_mrn)
    if raw_mrn is None or str(raw_mrn).strip() != norm_mrn:
        log("mrn", raw_mrn, norm_mrn, "normalized MRN format")

    # --- names ---
    _, raw_given = _first_present(raw, _GIVEN_KEYS)
    given = str(raw_given).strip() if raw_given else ""
    if not given:
        log("given_name", raw_given, "UNKNOWN", "missing given name")
        given = "UNKNOWN"

    _, raw_family = _first_present(raw, _FAMILY_KEYS)
    family = str(raw_family).strip() if raw_family else ""
    if not family:
        log("family_name", raw_family, "UNKNOWN", "missing family name")
        family = "UNKNOWN"

    return CanonicalPatient(
        mrn=norm_mrn,
        given_name=given,
        family_name=family,
        dob=parsed_dob,
        gender=norm_gender,
        source_format=source_format,
        raw_record=raw,
        audit_log=audit,
    )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _fingerprint(p: CanonicalPatient) -> tuple[str, str, str]:
    return (p.family_name.lower(), str(p.dob), p.mrn)


def deduplicate(records: list[CanonicalPatient]) -> list[CanonicalPatient]:
    """Collapse duplicate records by ``(family_name, dob, mrn)``.

    The record with the fewest audit entries (= most complete original data)
    wins. The discarded record's ``record_id`` is logged on the survivor.
    """
    seen: dict[tuple, CanonicalPatient] = {}
    for rec in records:
        key = _fingerprint(rec)
        if key not in seen:
            seen[key] = rec
            continue

        existing = seen[key]
        winner, loser = (rec, existing) if len(rec.audit_log) < len(existing.audit_log) else (existing, rec)
        winner.audit_log.append(AuditEntry(
            field="record_id",
            original=loser.record_id,
            normalized=winner.record_id,
            reason="duplicate dropped (kept record with fewer audit entries)",
        ))
        seen[key] = winner

    return list(seen.values())
