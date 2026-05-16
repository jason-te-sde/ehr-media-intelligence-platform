"""Map a source Encounter dict to a FHIR R4 ``Encounter`` resource.

We carry over the original ``id``, ``status``, ``class``, ``type``, and
``period`` so DocumentReference / DiagnosticReport / Observation
references remain resolvable inside the assembled Bundle.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.period import Period
from fhir.resources.R4B.reference import Reference


def _coerce_iso(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return f"{value.isoformat()}T00:00:00Z"


def to_encounter(
    *,
    patient_id: str,
    encounter_id: str | None = None,
    status: str = "finished",
    class_code: str = "AMB",
    class_system: str = "http://terminology.hl7.org/CodeSystem/v3-ActCode",
    type_text: str | None = None,
    type_code: str | None = None,
    type_system: str = "http://snomed.info/sct",
    period_start: date | datetime | str | None = None,
    period_end: date | datetime | str | None = None,
) -> Encounter:
    """Build a valid FHIR R4 ``Encounter``.

    ``patient_id`` matches the bundle's ``Patient.id`` so the ``subject``
    reference resolves internally via ``urn:uuid:{patient_id}``.
    """
    coding = Coding(system=class_system, code=class_code)
    enc = Encounter(
        id=encounter_id or str(uuid.uuid4()),
        status=status,
        **{"class": coding},   # `class` is a Python keyword; pydantic accepts via kwargs
        subject=Reference(reference=f"urn:uuid:{patient_id}"),
    )
    if type_text or type_code:
        coding_list = []
        if type_code:
            coding_list.append(Coding(system=type_system, code=type_code, display=type_text))
        enc.type = [CodeableConcept(coding=coding_list or None, text=type_text)]
    start = _coerce_iso(period_start)
    end = _coerce_iso(period_end)
    if start or end:
        enc.period = Period(start=start, end=end)
    return enc


def from_source(raw: dict[str, Any], patient_id: str) -> Encounter:
    """Lift a Synthea-shaped Encounter dict into a fhir.resources Encounter."""
    cls = raw.get("class") or {}
    type0 = ((raw.get("type") or [{}])[0]) if raw.get("type") else {}
    coding0 = ((type0.get("coding") or [{}])[0]) if type0.get("coding") else {}
    period = raw.get("period") or {}
    return to_encounter(
        patient_id=patient_id,
        encounter_id=raw.get("id"),
        status=raw.get("status") or "finished",
        class_code=cls.get("code") or "AMB",
        class_system=cls.get("system") or "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        type_text=type0.get("text") or coding0.get("display"),
        type_code=coding0.get("code"),
        type_system=coding0.get("system") or "http://snomed.info/sct",
        period_start=period.get("start"),
        period_end=period.get("end"),
    )
