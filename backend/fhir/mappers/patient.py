"""Map a ``CanonicalPatient`` to a FHIR R4 ``Patient`` resource.

The MRN is carried on ``Patient.identifier`` with a type coding of
``MR`` (terminology.hl7.org/v2-0203 — Medical Record Number). ``Patient.id``
is reused across the bundle so internal ``urn:uuid:{id}`` references resolve.
"""

from __future__ import annotations

from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.humanname import HumanName
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.patient import Patient

from backend.ingestion.models import CanonicalPatient

MR_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"
ONYE_MRN_SYSTEM = "urn:onye:mrn"


def _mrn_identifier(mrn: str) -> Identifier:
    return Identifier(
        type=CodeableConcept(
            coding=[Coding(system=MR_SYSTEM, code="MR", display="Medical Record Number")],
            text="Medical Record Number",
        ),
        system=ONYE_MRN_SYSTEM,
        value=mrn,
    )


def canonical_to_patient(c: CanonicalPatient) -> Patient:
    """Build a FHIR R4 ``Patient`` from a cleaned ``CanonicalPatient``."""
    return Patient(
        id=c.record_id,
        identifier=[_mrn_identifier(c.mrn)],
        name=[HumanName(family=c.family_name, given=[c.given_name])],
        # FHIR `gender` valueset matches our canonical literal exactly.
        # Drop "unknown" to None so the field is simply absent rather than
        # using an unknown code (FHIR also accepts "unknown" but null is cleaner).
        gender=c.gender if c.gender != "unknown" else None,
        birthDate=c.dob.isoformat() if c.dob else None,
    )


def extract_mrn(patient: Patient) -> str | None:
    """Inverse of ``_mrn_identifier``: pull the MR-typed identifier value from a Patient."""
    for ident in patient.identifier or []:
        coding = (ident.type.coding if ident.type else None) or []
        if any(c.code == "MR" for c in coding):
            return ident.value
    return None
