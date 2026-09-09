"""LLM Connection API endpoints (WP-22b).

A Connection points NEXUS at any OpenAI- or Anthropic-compatible endpoint
(a self-hosted gateway, Ollama, vLLM, OpenRouter, ...). The example gateway
this abstraction was built for is one such endpoint the user may add; no
vendor name appears in this module (R9).

The API key is never returned. Create runs base_url through the SSRF guard,
with a per-deployment host allowlist for private/gateway hosts.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import DbSession, PathCompanyId, RequireAdmin
from nexus.config import settings
from nexus.governance.ssrf_protection import guard_url
from nexus.models.connection import WIRE_FORMATS, LLMConnection

router = APIRouter(tags=["connections"])


class ConnectionCreate(BaseModel):
    """Request body for creating an LLM connection."""

    name: str
    base_url: str
    wire_format: str
    api_key_ref: str | None = None
    mgmt_key_ref: str | None = None


class ConnectionResponse(BaseModel):
    """Response model. Never carries a key value — only presence flags."""

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    base_url: str
    wire_format: str
    has_api_key: bool
    has_mgmt_key: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


def _to_response(conn: LLMConnection) -> ConnectionResponse:
    return ConnectionResponse(
        id=conn.id,
        company_id=conn.company_id,
        name=conn.name,
        base_url=conn.base_url,
        wire_format=conn.wire_format,
        has_api_key=bool(conn.api_key_ref),
        has_mgmt_key=bool(conn.mgmt_key_ref),
        is_active=conn.is_active,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


def _host_allowlisted(url: str) -> bool:
    from urllib.parse import urlparse

    allow = {h.strip().lower() for h in settings.llm_connection_host_allowlist.split(",") if h.strip()}
    host = (urlparse(url).hostname or "").lower()
    return host in allow


@router.post(
    "/api/v1/companies/{company_id}/connections",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectionResponse,
)
async def create_connection(
    company_id: PathCompanyId,
    body: ConnectionCreate,
    db: DbSession,
    principal: RequireAdmin,
) -> Any:
    """Create an LLM connection. Rejects private hosts unless allowlisted."""
    if body.wire_format not in WIRE_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"wire_format must be one of {WIRE_FORMATS}",
        )
    if not _host_allowlisted(body.base_url):
        try:
            guard_url(body.base_url, field="base_url")
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    conn = LLMConnection(
        company_id=company_id,
        name=body.name,
        base_url=body.base_url,
        wire_format=body.wire_format,
        api_key_ref=body.api_key_ref,
        mgmt_key_ref=body.mgmt_key_ref,
    )
    db.add(conn)
    await db.flush()

    # Discover the gateway catalog so real context windows land in the
    # registry (WP-22c). Fail-open: discovery errors never fail create.
    if conn.wire_format == "openai":
        try:
            from nexus.models_router.catalog import discover_models

            await discover_models(conn.base_url)
        except Exception:
            pass

    return _to_response(conn)


@router.get(
    "/api/v1/companies/{company_id}/connections",
    response_model=list[ConnectionResponse],
)
async def list_connections(
    company_id: PathCompanyId,
    db: DbSession,
    principal: RequireAdmin,
) -> Any:
    """List connections for a company."""
    rows = await db.execute(
        select(LLMConnection).where(LLMConnection.company_id == company_id)
    )
    return [_to_response(c) for c in rows.scalars().all()]


@router.get(
    "/api/v1/companies/{company_id}/connections/{connection_id}",
    response_model=ConnectionResponse,
)
async def get_connection(
    company_id: PathCompanyId,
    connection_id: uuid.UUID,
    db: DbSession,
    principal: RequireAdmin,
) -> Any:
    """Get one connection by id."""
    conn = await db.get(LLMConnection, connection_id)
    if conn is None or conn.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _to_response(conn)
