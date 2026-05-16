"""GET /providers — list available LLM backends + their health status.

The frontend's provider-selector dropdown reads this and disables any
provider that fails its healthcheck (missing key, daemon down, model
not pulled, ...).
"""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from backend.summarize.providers import get_provider, list_providers
from backend.summarize.providers.factory import DEFAULT_PROVIDER

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderStatus(BaseModel):
    id: str
    name: str
    model: str
    local: bool
    needs_api_key: bool
    healthy: bool
    message: str
    active: bool


@router.get("", response_model=list[ProviderStatus])
def list_provider_status() -> list[ProviderStatus]:
    active_id = (os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    out: list[ProviderStatus] = []
    for pid in list_providers():
        try:
            prov = get_provider(pid)
            ok, msg = prov.healthcheck()
            out.append(ProviderStatus(
                id=prov.info.id,
                name=prov.info.name,
                model=prov.info.model,
                local=prov.info.local,
                needs_api_key=prov.info.needs_api_key,
                healthy=ok,
                message=msg,
                active=(prov.info.id == active_id),
            ))
        except Exception as exc:   # pragma: no cover — keep response stable on init errors
            out.append(ProviderStatus(
                id=pid,
                name=pid,
                model="?",
                local=False,
                needs_api_key=False,
                healthy=False,
                message=f"init failed: {exc}",
                active=(pid == active_id),
            ))
    return out
