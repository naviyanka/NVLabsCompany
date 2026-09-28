"""Organization snapshot API: read the latest precomputed snapshot, its history, or refresh it.

Thin shells over :mod:`nexus.services.org_snapshot`. The company is the
caller's own (no company in the path), so another tenant's snapshot is never
addressable. Users read the whole organization and may refresh it; a service
key needs the admin permission on ``organization_snapshot`` (only the
auth-disabled development principal is exempt). An agent (a run token) reads only what
:func:`~nexus.services.org_snapshot.agent_scope` allows it: a manager its
team's projection, an explicitly authorized agent the organization, anyone
else nothing. Reads never aggregate: they return the stored version.

``/api/v1/organization/ceo`` shows and changes who the CEO is (a human
administrator only) and reads or records its executive memory
(:mod:`nexus.services.ceo_service`).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession, require_permission
from nexus.services import ceo_service, manager_service, org_snapshot

router = APIRouter(prefix="/api/v1/organization/snapshot", tags=["organization"])
ceo_router = APIRouter(prefix="/api/v1/organization/ceo", tags=["organization"])

READ = [require_permission("read", "task")]
WRITE = [require_permission("write", "task")]


def _operator(principal: Any) -> None:
    """Whole-organization access: a user, or a service key granted it explicitly.

    A service key is not an operator by default: it needs the admin grant on
    ``organization_snapshot`` (no non-admin role has it). The auth-disabled
    development principal is the one exception.
    """
    if principal.kind == "run":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SNAPSHOT_FORBIDDEN", "message": "Agents may only read their scope"},
        )
    if principal.kind == "service" and not (
        ceo_service.dev_fallback(principal)
        or principal.has_permission("admin", "organization_snapshot")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SNAPSHOT_FORBIDDEN",
                    "message": "This API key may not read or refresh the organization snapshot"},
        )


@router.get("", dependencies=READ)
async def latest(
    db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    """The latest stored snapshot, even when stale, with its freshness and last refresh error."""
    if principal.kind == "run":
        return await org_snapshot.read_as_agent(
            db, company_id, principal.agent_id, principal.display_name
        )
    _operator(principal)
    return await org_snapshot.read(db, company_id)


@router.get("/history", dependencies=READ)
async def history(
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    limit: int = Query(default=10, ge=1, le=org_snapshot.HISTORY_MAX),
) -> list[dict[str, Any]]:
    """Newest versions first, metadata only."""
    _operator(principal)
    return await org_snapshot.history(db, company_id, limit)


@router.post("/refresh", dependencies=WRITE)
async def refresh(
    db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Regenerate now. A failure keeps the previous snapshot and is reported, not raised."""
    _operator(principal)
    # The generation opens its own short transactions; release this one first.
    await db.commit()
    outcome = await org_snapshot.generate(company_id)
    await manager_service.audit(
        db, company_id, "organization.snapshot_refreshed", principal.display_name,
        "organization_snapshot", company_id, **outcome,
    )
    await db.commit()
    return {**await org_snapshot.read(db, company_id), "refresh": outcome}


# --- CEO ------------------------------------------------------------------------


class AppointCEO(BaseModel):
    agent_id: uuid.UUID


@ceo_router.get("", dependencies=READ)
async def ceo_status(
    db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    """The CEO, its backend and tool availability, snapshot freshness, memory, approvals."""
    _operator(principal)
    return await ceo_service.status(db, company_id)


@ceo_router.put("")
async def appoint_ceo(
    body: AppointCEO, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Appoint the CEO, or replace the current one. A human administrator only."""
    return await ceo_service.appoint(db, company_id, body.agent_id, principal)


@ceo_router.delete("")
async def remove_ceo(
    db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Remove the CEO designation. A human administrator only."""
    return await ceo_service.remove(db, company_id, principal)


@ceo_router.get("/memory", dependencies=READ)
async def executive_memory(
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    query: str | None = Query(default=None, max_length=200),
    type: str | None = None,
    include_closed: bool = False,
    limit: int = Query(default=ceo_service.SEARCH_MAX, ge=1, le=ceo_service.SEARCH_MAX),
) -> list[dict[str, Any]]:
    """Executive memory, newest first."""
    _operator(principal)
    rows = await ceo_service.recall(
        db, company_id, query=query, type=type, include_closed=include_closed, limit=limit
    )
    return [ceo_service.entry_view(r) for r in rows]


@ceo_router.post("/memory", status_code=status.HTTP_201_CREATED, dependencies=WRITE)
async def record_executive_memory(
    body: ceo_service.MemoryEntry,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Record a human directive or decision for the CEO. People only."""
    if not ceo_service.is_human(principal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "HUMAN_DECISION_REQUIRED",
                    "message": "Only a person records executive memory here"},
        )
    record = await ceo_service.remember(
        db, company_id, body, recorded_by=principal.display_name, origin="human",
    )
    await db.commit()
    return ceo_service.entry_view(record)
