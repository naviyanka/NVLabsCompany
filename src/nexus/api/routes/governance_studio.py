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
from nexus.services.governance_studio import catalog as cat
from nexus.services.governance_studio import effective
from nexus.services.governance_studio.errors import fail, require_reader

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
