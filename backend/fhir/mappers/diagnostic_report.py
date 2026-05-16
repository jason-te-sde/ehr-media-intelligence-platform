"""Map lab/imaging conclusions to FHIR ``DiagnosticReport`` resources."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.reference import Reference


def to_diagnostic_report(
    conclusion: str,
    patient_id: str,
    category: str = "LAB",
    date: date | datetime | str | None = None,
    resource_id: str | None = None,
    encounter_id: str | None = None,
) -> DiagnosticReport:
    """Build a valid FHIR R4 ``DiagnosticReport``.

    ``patient_id`` matches the bundle's ``Patient.id`` / ``fullUrl`` so the
    ``subject`` reference resolves internally via ``urn:uuid:{patient_id}``.

    ``category`` should be one of: ``LAB`` (laboratory), ``RAD`` (radiology),
    ``PAT`` (pathology), ``CG`` (cytogenetics), or any other v2-0074 code.
    """
    eff: str | None
    if date is None:
        eff = None
    elif isinstance(date, str):
        eff = date
    elif isinstance(date, datetime):
        eff = date.isoformat()
    else:
        eff = date.isoformat()

    dr = DiagnosticReport(
        id=resource_id or str(uuid.uuid4()),
        status="final",
        subject=Reference(reference=f"urn:uuid:{patient_id}"),
        effectiveDateTime=eff,
        category=[CodeableConcept(
            coding=[],
            text=category,
        )],
        code=CodeableConcept(text="Clinical Note"),
        conclusion=conclusion,
    )
    if encounter_id:
        dr.encounter = Reference(reference=f"urn:uuid:{encounter_id}")
    return dr
