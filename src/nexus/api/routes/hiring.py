"""Hiring API — batch team creation and manifest-based agent provisioning."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from nexus.api.deps import DbSession
from nexus.models.agent import Agent
from nexus.templates.archetypes import ArchetypeRegistry
from nexus.templates.hire_manifest import validate_hire_manifest

router = APIRouter(tags=["hiring"])

_archetype_registry = ArchetypeRegistry()


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class TeamAgentSpec(BaseModel):
    """Specification for a single agent within a team hire request."""

    name: str = Field(..., min_length=1, max_length=80)
    archetype: str | None = Field(
        None,
        description="Archetype name (e.g. 'Backend Engineer'). "
        "If provided, auto-fills capabilities, system_prompt, tools, and constraints.",
    )
    role: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=255)
    model: str | None = Field(None, max_length=80)
    adapter_type: str = "langchain"
    capabilities: list[str] | None = None
    responsibilities: str | None = None
    objectives: str | None = None
    soul_description: str | None = None
    budget_monthly_cents: int = 0


class HireTeamRequest(BaseModel):
    """Request body for batch-hiring a team of agents."""

    team_name: str = Field(..., min_length=1, max_length=100)
    department_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    agents: list[TeamAgentSpec] = Field(..., min_length=1, max_length=20)


class HireTeamResponse(BaseModel):
    """Response for a successful team hire."""

    team_name: str
    department_id: uuid.UUID | None = None
    agents_created: int
    agents: list[dict[str, Any]]


class HireFromManifestRequest(BaseModel):
    """Request body wrapping a hire manifest for agent creation."""

    manifest: dict[str, Any] = Field(
        ..., description="Raw HireManifest JSON object (spec: nexus/hire@1)"
    )
    name_override: str | None = Field(
        None,
        max_length=80,
        description="Override the manifest name for the created agent",
    )
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    budget_monthly_cents: int | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/agents/hire-team",
    status_code=status.HTTP_201_CREATED,
    response_model=HireTeamResponse,
)
async def hire_team(
    company_id: uuid.UUID,
    body: HireTeamRequest,
    db: DbSession,
) -> Any:
    """Batch-hire a team of agents in a single transaction.

    For each agent spec:
    - If `archetype` is provided, resolves it from the ArchetypeRegistry and
      auto-fills capabilities, soul_description (from system_prompt), and role.
    - Explicit fields in the spec override archetype defaults.
    - All agents are created with the same company_id, department_id, and
      optionally a shared manager_id.

    On any validation failure, no agents are created (atomic operation).
    """
    created_agents: list[dict[str, Any]] = []

    for spec in body.agents:
        # Resolve archetype defaults if specified
        archetype_caps: list[str] = []
        archetype_soul: str = ""
        archetype_role: str = ""

        if spec.archetype:
            archetype = _archetype_registry.get_archetype(spec.archetype)
            if archetype is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown archetype '{spec.archetype}'. "
                    f"Use GET /api/v1/agent-archetypes for available options.",
                )
            archetype_caps = archetype.capabilities
            archetype_soul = archetype.system_prompt
            archetype_role = archetype.role

        # Build agent with spec fields overriding archetype defaults
        agent = Agent(
            company_id=company_id,
            name=spec.name,
            role=spec.role or archetype_role or "specialist",
            title=spec.title,
            department_id=body.department_id,
            team_id=None,  # Team association can be done post-creation
            manager_id=body.manager_id,
            adapter_type=spec.adapter_type,
            model=spec.model,
            capabilities=spec.capabilities or archetype_caps or None,
            responsibilities=spec.responsibilities,
            objectives=spec.objectives,
            soul_description=spec.soul_description or archetype_soul or None,
            budget_monthly_cents=spec.budget_monthly_cents,
            status="idle",
        )
        db.add(agent)
        await db.flush()

        created_agents.append({
            "id": str(agent.id),
            "name": agent.name,
            "role": agent.role,
            "title": agent.title,
            "model": agent.model,
            "status": agent.status,
            "capabilities": agent.capabilities,
        })

    return HireTeamResponse(
        team_name=body.team_name,
        department_id=body.department_id,
        agents_created=len(created_agents),
        agents=created_agents,
    )


@router.post(
    "/api/v1/companies/{company_id}/agents/hire-from-manifest",
    status_code=status.HTTP_201_CREATED,
)
async def hire_from_manifest(
    company_id: uuid.UUID,
    body: HireFromManifestRequest,
    db: DbSession,
) -> dict[str, Any]:
    """Hire an agent from a portable HireManifest JSON spec.

    Validates the manifest against security rules (flag allowlist, model ID
    sanitization, provider validation), then creates an agent with the
    manifest's configuration mapped to the Agent model.

    Returns the created agent's ID and key fields.
    """
    # Validate manifest
    validation = validate_hire_manifest(body.manifest)
    if not validation.ok or validation.manifest is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Manifest validation failed",
                "errors": validation.errors,
            },
        )

    manifest = validation.manifest

    # Map manifest fields → Agent model
    agent_name = body.name_override or manifest.name
    adapter_type = manifest.provider or "langchain"

    agent = Agent(
        company_id=company_id,
        name=agent_name,
        role=manifest.name.lower().replace(" ", "-"),
        title=manifest.description or f"{manifest.name} Specialist",
        department_id=body.department_id,
        team_id=body.team_id,
        manager_id=body.manager_id,
        adapter_type=adapter_type,
        adapter_config={
            "command_flags": manifest.command_flags,
            "isolate": manifest.isolate,
        }
        if manifest.command_flags or manifest.isolate
        else None,
        model=manifest.model,
        capabilities=manifest.capabilities or None,
        responsibilities=manifest.goal,
        objectives=manifest.goal,
        soul_description=manifest.description,
        budget_monthly_cents=body.budget_monthly_cents
        or (manifest.token_cap // 100 if manifest.token_cap else 0),
        status="idle",
    )
    db.add(agent)
    await db.flush()

    return {
        "id": str(agent.id),
        "name": agent.name,
        "role": agent.role,
        "title": agent.title,
        "provider": manifest.provider,
        "model": agent.model,
        "capabilities": agent.capabilities,
        "status": agent.status,
        "manifest_spec": manifest.spec,
    }
