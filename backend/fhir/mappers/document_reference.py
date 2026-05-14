"""Map free-text clinical notes to FHIR ``DocumentReference`` resources."""

from __future__ import annotations

import base64
import uuid
from datetime import date, datetime

from fhir.resources.attachment import Attachment
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.documentreference import DocumentReference, DocumentReferenceContent
from fhir.resources.reference import Reference


def _as_iso_datetime(d: date | datetime | str | None) -> str | None:
    """Coerce a date/datetime/str into a FHIR ``instant`` string.

    FHIR ``DocumentReference.date`` is an ``instant`` (timestamp with timezone).
    We attach midnight UTC when only a calendar date is available.
    """
    if d is None:
        return None
    if isinstance(d, str):
        return d
    if isinstance(d, datetime):
        return d.isoformat()
    return f"{d.isoformat()}T00:00:00Z"


def to_document_reference(
    text: str,
    patient_id: str,
    doc_type: str = "Clinical Note",
    date: date | datetime | str | None = None,
    resource_id: str | None = None,
) -> DocumentReference:
    """Build a valid FHIR R4 ``DocumentReference`` carrying ``text`` as the attachment.

    ``patient_id`` matches the bundle's ``Patient.id`` / ``fullUrl`` so the
    ``subject`` reference resolves internally via ``urn:uuid:{patient_id}``.
    """
    return DocumentReference(
        id=resource_id or str(uuid.uuid4()),
        status="current",
        subject=Reference(reference=f"urn:uuid:{patient_id}"),
        date=_as_iso_datetime(date),
        type=CodeableConcept(text=doc_type),
        content=[DocumentReferenceContent(
            attachment=Attachment(
                contentType="text/plain",
                data=base64.b64encode(text.encode("utf-8")).decode("ascii"),
            ),
        )],
    )


def decode_attachment(dr: DocumentReference) -> str:
    """Recover the original UTF-8 text from a ``DocumentReference``.

    ``fhir.resources`` auto-decodes the base64 input on construction, so
    ``att.data`` is the raw bytes payload at runtime. When the resource is
    deserialized from JSON, ``att.data`` is the base64 string instead — we
    handle both shapes.
    """
    if not dr.content:
        return ""
    data = dr.content[0].attachment.data
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8")
    # str case (loaded from JSON) → still base64
    return base64.b64decode(data).decode("utf-8")
