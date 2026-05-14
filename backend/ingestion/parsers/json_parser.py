"""Parse JSON EHR exports into raw dicts that ``cleaner.clean_record`` can consume.

Two sub-formats are supported:

1. **FHIR Bundle** — Synthea's per-patient JSON: a single ``Bundle`` resource
   whose ``entry`` array contains one ``Patient`` resource (plus many others
   that this layer ignores).
2. **NDJSON / JSON array** — generic EHR exports where each line / element
   is a flat patient dict.

Both forms emit a uniform raw dict whose keys overlap with the field-alias
table in :mod:`backend.ingestion.cleaner`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

_MR_CODE = "MR"   # http://terminology.hl7.org/CodeSystem/v2-0203 — Medical Record Number


def _extract_mrn(patient: dict[str, Any]) -> str | None:
    """Return the Medical Record Number from a FHIR ``Patient.identifier`` array."""
    for ident in patient.get("identifier") or []:
        for coding in (ident.get("type") or {}).get("coding") or []:
            if coding.get("code") == _MR_CODE:
                return ident.get("value")
    # Fall back to the first identifier if no MR-typed one is present
    for ident in patient.get("identifier") or []:
        if ident.get("value"):
            return ident["value"]
    return None


def _patient_resource_to_raw(p: dict[str, Any]) -> dict[str, Any]:
    """Flatten a FHIR ``Patient`` resource into a raw dict for the cleaner."""
    name0 = (p.get("name") or [{}])[0]
    given_list = name0.get("given") or []
    return {
        "Id": p.get("id"),
        "mrn": _extract_mrn(p),
        "FIRST": given_list[0] if given_list else None,
        "LAST": name0.get("family"),
        "GENDER": p.get("gender"),
        "BIRTHDATE": p.get("birthDate"),
        "_fhir_patient": p,    # preserve original for downstream FHIR mapping
    }


def parse_fhir_bundle_file(path: str | Path) -> list[dict[str, Any]]:
    """Read one Synthea-style FHIR Bundle JSON and return its Patient resources as raw dicts."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("resourceType") != "Bundle":
        raise ValueError(f"{path}: expected a FHIR Bundle, got resourceType={data.get('resourceType')!r}")
    out: list[dict[str, Any]] = []
    for entry in data.get("entry") or []:
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "Patient":
            raw = _patient_resource_to_raw(resource)
            # Attach the full bundle so downstream FHIR mapping (Task 2) can pull
            # DocumentReference / DiagnosticReport content from the same source.
            raw["_fhir_bundle"] = data
            out.append(raw)
    return out


def parse_fhir_directory(directory: str | Path) -> list[dict[str, Any]]:
    """Read every ``*.json`` Bundle under ``directory`` and concat their patients."""
    out: list[dict[str, Any]] = []
    for p in sorted(Path(directory).glob("*.json")):
        out.extend(parse_fhir_bundle_file(p))
    return out


def parse_ndjson_file(path: str | Path) -> list[dict[str, Any]]:
    """Read a newline-delimited JSON file (one patient object per line)."""
    out: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def parse_json_array_file(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSON file containing a top-level array of patient objects."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a top-level JSON array")
    return data


def parse_json(path: str | Path) -> list[dict[str, Any]]:
    """Auto-detect FHIR Bundle / NDJSON / JSON array based on the first non-whitespace byte and resourceType."""
    p = Path(path)
    if p.is_dir():
        return parse_fhir_directory(p)
    text = p.read_text(encoding="utf-8").lstrip()
    if text.startswith("["):
        return parse_json_array_file(p)
    if text.startswith("{"):
        # could be a single object (FHIR Bundle) or one of many NDJSON lines
        first_line, _, rest = text.partition("\n")
        if rest.strip():
            return parse_ndjson_file(p)
        data = json.loads(first_line)
        if data.get("resourceType") == "Bundle":
            return parse_fhir_bundle_file(p)
        return [data]
    raise ValueError(f"{p}: unrecognized JSON content")
