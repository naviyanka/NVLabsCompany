"""Organization snapshot API: read the latest precomputed snapshot, its history, or refresh it.

Thin shells over :mod:`nexus.services.org_snapshot`. The company is the
caller's own (no company in the path), so another tenant's snapshot is never
addressable. Company operators (users, and service keys) read the whole
organization and may refresh it. An agent (a run token) reads only what
:func:`~nexus.services.org_snapshot.agent_scope` allows it: a manager its
team's projection, an explicitly authorized agent the organization, anyone
else nothing. Reads never aggregate: they return the stored version.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession, require_permission
from nexus.services import manager_service, org_snapshot

router = APIRouter(prefix="/api/v1/organization/snapshot", tags=["organization"])

READ = [require_permission("read", "task")]
WRITE = [require_permission("write", "task")]


def _operator(principal: Any) -> None:
    if principal.kind == "run":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SNAPSHOT_FORBIDDEN", "message": "Agents may only read their scope"},
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
