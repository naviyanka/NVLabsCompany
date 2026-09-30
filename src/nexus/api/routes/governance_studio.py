"""Governance Studio API: what each agent may do, and the controls that change it.

The company is always the caller's own (never in the path), so another tenant's agent or
grant is a 404. Reads need a person; writes need a human administrator. Run tokens and API
keys are refused. The decisions themselves come from the real tool-access engine
(:mod:`nexus.services.governance_studio`).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlmodel import select

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.services.governance_studio import catalog as cat
from nexus.services.governance_studio import effective, grants, policies, runtime, simulate
from nexus.services.governance_studio.audit import actor_of
from nexus.services.governance_studio.errors import fail, require_admin_human, require_reader

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])

PAGE_MAX = 100


async def _agent(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    ).scalars().first()
    if agent is None:
        fail(404, "AGENT_NOT_FOUND", "No such agent")
    return agent


@router.get("/catalog")
async def get_catalog(principal: CurrentPrincipal) -> dict[str, Any]:
    require_reader(principal)
    return {
        "categories": list(cat.CATEGORIES),
        "capabilities": cat.build_catalog(),
        "gates": cat.gate_status(),
        "deferred": [
            "AI recommendations", "Automatic policy changes", "Compliance certification",
            "Policy scripting", "Voice permissions", "Full sandbox",
            "Verified memory (awaits its own release)",
        ],
    }


@router.get("/agents")
async def list_agents(
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    limit: int = Query(default=50, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    require_reader(principal)
    rows = (
        await db.execute(
            select(Agent)
            .where(Agent.company_id == company_id)
            .order_by(Agent.name, Agent.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(a.id), "name": a.name, "role": a.role, "title": a.title,
                "status": a.status, "is_ceo": a.is_ceo, "manager_id": str(a.manager_id)
                if a.manager_id else None,
                "adapter_type": a.adapter_type, "model": a.model,
                "autonomy_policy": a.autonomy_policy or {},
                "pause_reason": a.pause_reason,
            }
            for a in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/agents/{agent_id}/effective-access")
async def effective_access(
    agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    require_reader(principal)
    agent = await _agent(db, company_id, agent_id)
    return await effective.effective_access(db, company_id, agent)


@router.post("/grants", status_code=201)
async def create_grant(
    body: grants.GrantBody, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await grants.create(db, company_id, principal, body)
    await db.commit()
    return out


@router.get("/grants")
async def list_grants(
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    agent_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    require_reader(principal)
    return await grants.list_grants(
        db, company_id, agent_id=agent_id, status=status, limit=limit, offset=offset
    )


@router.post("/grants/{grant_id}/revoke")
async def revoke_grant(
    grant_id: uuid.UUID,
    body: grants.Revoke,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await grants.revoke(db, company_id, principal, grant_id, body)
    await db.commit()
    return out


@router.post("/grants/{grant_id}/approve")
async def approve_grant(
    grant_id: uuid.UUID,
    body: grants.Decision,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await grants.approve(db, company_id, principal, grant_id, body)
    await db.commit()
    return out


@router.post("/grants/{grant_id}/reject")
async def reject_grant(
    grant_id: uuid.UUID,
    body: grants.Decision,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await grants.reject(db, company_id, principal, grant_id, body)
    await db.commit()
    return out


@router.get("/approvals")
async def approval_inbox(
    db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Grants waiting for a decision, and whether the caller may decide them."""
    require_reader(principal)
    pending = await grants.list_grants(
        db, company_id, agent_id=None, status="pending_approval", limit=PAGE_MAX, offset=0
    )
    me = actor_of(principal)
    can_decide = principal.role == "admin"
    return {
        "items": [
            {**g, "can_decide": can_decide and g["requested_by"] != me}
            for g in pending["items"]
        ]
    }


@router.post("/simulate")
async def simulate_access(
    body: simulate.SimulateBody,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Decide one capability for one agent, optionally against proposed rules. Writes nothing."""
    require_reader(principal)
    agent = await _agent(db, company_id, body.agent_id)
    if body.session_id is not None:
        found = (
            await db.execute(
                select(AgentSessionRecord.id).where(
                    AgentSessionRecord.id == body.session_id,
                    AgentSessionRecord.company_id == company_id,
                    AgentSessionRecord.agent_id == agent.id,
                )
            )
        ).first()
        if found is None:
            fail(404, "SESSION_NOT_FOUND", "No such session for this agent")
    return await simulate.simulate(db, company_id, agent, body)


@router.get("/policy")
async def get_policy(
    db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    require_reader(principal)
    return await policies.overview(db, company_id)


@router.get("/drafts")
async def list_drafts(
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    require_reader(principal)
    return await policies.list_drafts(db, company_id, status=status, limit=limit, offset=offset)


@router.post("/drafts", status_code=201)
async def create_draft(
    body: policies.DraftBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await policies.create_draft(db, company_id, principal, body)
    await db.commit()
    return out


@router.get("/drafts/{draft_id}")
async def get_draft(
    draft_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    require_reader(principal)
    return await policies.get_draft(db, company_id, draft_id)


@router.put("/drafts/{draft_id}")
async def update_draft(
    draft_id: uuid.UUID, body: policies.DraftBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await policies.update_draft(db, company_id, principal, draft_id, body)
    await db.commit()
    return out


@router.post("/drafts/{draft_id}/discard")
async def discard_draft(
    draft_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await policies.discard_draft(db, company_id, principal, draft_id)
    await db.commit()
    return out


@router.post("/drafts/{draft_id}/publish")
async def publish_draft(
    draft_id: uuid.UUID, body: policies.PublishBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await policies.publish(db, company_id, principal, draft_id, body)
    await db.commit()
    return out


@router.get("/versions")
async def list_versions(
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    limit: int = Query(default=50, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    require_reader(principal)
    return await policies.list_versions(db, company_id, limit=limit, offset=offset)


@router.get("/versions/{number}")
async def get_version(
    number: int, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    require_reader(principal)
    return await policies.get_version(db, company_id, number)


@router.post("/versions/{number}/rollback")
async def rollback_version(
    number: int, body: policies.RollbackBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await policies.rollback(db, company_id, principal, number, body)
    await db.commit()
    return out


@router.get("/runtime")
async def active_work(
    db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal,
    agent_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    require_reader(principal)
    return await runtime.active_work(db, company_id, agent_id)


@router.post("/runtime/attempts/{attempt_id}/cancel")
async def cancel_attempt(
    attempt_id: uuid.UUID, body: runtime.CancelBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    return await runtime.cancel_attempt(db, company_id, principal, attempt_id, body)


@router.post("/runtime/turns/{turn_id}/cancel")
async def cancel_turn(
    turn_id: uuid.UUID, body: runtime.CancelBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    return await runtime.cancel_turn(db, company_id, principal, turn_id, body)


@router.post("/agents/{agent_id}/cancel")
async def cancel_agent_work(
    agent_id: uuid.UUID, body: runtime.CancelBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    return await runtime.cancel_agent(db, company_id, principal, agent_id, body)


@router.get("/restrictions")
async def get_restrictions(
    db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    require_reader(principal)
    return await runtime.restrictions(db, company_id)


@router.post("/lockdown", status_code=201)
async def start_lockdown(
    body: runtime.LockdownBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await runtime.lockdown(db, company_id, principal, body)
    await db.commit()
    return out


@router.post("/lockdown/release")
async def release_lockdown(
    body: runtime.LockdownBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await runtime.release_lockdown(db, company_id, principal, body)
    await db.commit()
    return out


@router.post("/agents/{agent_id}/isolate", status_code=201)
async def isolate_agent(
    agent_id: uuid.UUID, body: runtime.IsolateBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await runtime.isolate(db, company_id, principal, agent_id, body)
    await db.commit()
    return out


@router.post("/agents/{agent_id}/isolate/release")
async def release_agent_isolation(
    agent_id: uuid.UUID, body: runtime.IsolateBody, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    require_admin_human(principal)
    out = await runtime.release_isolation(db, company_id, principal, agent_id, body)
    await db.commit()
    return out


@router.get("/audit")
async def audit_timeline(
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    action: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    require_reader(principal)
    return await runtime.timeline(db, company_id, action=action, limit=limit, offset=offset)
