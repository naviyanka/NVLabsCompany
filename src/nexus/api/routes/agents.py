"""Agent API endpoints - CRUD and lifecycle operations."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import select, update

from nexus.api.deps import (
    CurrentCompanyId,
    CurrentPrincipal,
    DbSession,
    PathCompanyId,
    audit_actor,
    principal_kinds,
    require_permission,
)
from nexus.auth.principal import Principal
from nexus.models._time import utcnow
from nexus.models.agent import Agent
from nexus.realtime.publish import TOPOLOGY_CHANNEL, publish_event
from nexus.services import ceo_service
from nexus.services.governance_studio.errors import can_write
from nexus.services.task_service import TaskService
from nexus.tools.governance_overlay import active_restrictions

router = APIRouter(tags=["agents"])

# Statuses that must never be routed work: the employee exists but its
# execution backend is not usable yet.
CONFIGURATION_REQUIRED = "configuration_required"

# Fields that decide what an agent may do or spend. Only a human company administrator changes
# them, on every route that accepts an AgentUpdate. A new AgentUpdate field is authority unless
# it is listed in PROFILE_FIELDS (the guard test fails until it is in one of the two).
AUTHORITY_FIELDS = frozenset(
    {"role", "status", "adapter_type", "model", "capabilities",
     "budget_monthly_cents", "autonomy_policy"}
)
PROFILE_FIELDS = frozenset({"name", "title", "responsibilities", "objectives", "soul_description"})
# A role containing one of these words makes a create an administrator decision.
PRIVILEGED_ROLE_WORDS = ("ceo", "manager", "chief", "director", "head", "admin", "owner")
# The only adapter settings a clone carries: the rest may hold connection details or secrets.
CLONE_ADAPTER_KEYS = ("backend", "interactive", "use_worktree", "autonomy_mode", "extra_args")


def _forbidden(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": code, "message": message})


# Every non-GET agent route declares require_permission, and a principal-kind gate (or
# heartbeat_principal): tests/test_agent_route_security walks the router and fails a route
# that lacks either.
WRITE_AGENT = [require_permission("write", "agent"), principal_kinds("user", "service")]


def enforce_update_policy(principal: Principal, updates: dict[str, Any]) -> None:
    """The one field policy for every route that applies an AgentUpdate (default deny).

    A person writes agent profiles (the route already demands ``write:agent``); a run token,
    an agent and an API key never use the generic update. Authority fields need a human
    administrator of the caller's own company. Checked before any lookup, so the answer never
    depends on whether the agent exists.
    """
    if not ceo_service.is_human(principal):
        raise _forbidden("HUMAN_REQUIRED", "Only a person may edit an agent")
    locked = sorted(AUTHORITY_FIELDS & set(updates))
    if locked and not can_write(principal):
        raise _forbidden(
            "HUMAN_ADMIN_REQUIRED",
            f"Only a human administrator may change {', '.join(locked)}",
        )


def normalize_cli_employee(
    adapter_type: str,
    adapter_config: dict[str, Any] | None,
    model: str | None,
    allow_unavailable: bool = False,
) -> tuple[dict[str, Any], str | None]:
    """Validate a ``cli`` employee config; shared by every hiring path.

    Returns ``(canonical_adapter_config, status_override)``. The override is
    ``configuration_required`` when an unavailable backend was explicitly
    allowed, else None. Raises HTTP 422 ``{"code", "message"}`` on refusal.
    """
    from nexus.adapters.cli_registry import CLIConfigError, validate_employee_cli_config

    try:
        config, ready = validate_employee_cli_config(
            adapter_type, adapter_config, model, allow_unavailable=allow_unavailable
        )
    except CLIConfigError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return config, (None if ready else CONFIGURATION_REQUIRED)


class AgentCreate(BaseModel):
    """Request body for creating an agent."""

    name: str
    role: str
    title: str | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    adapter_type: str = "langchain"
    adapter_config: dict[str, Any] | None = None
    model: str | None = None
    capabilities: list[str] | None = None
    responsibilities: str | None = None
    objectives: str | None = None
    soul_description: str | None = None
    budget_monthly_cents: int = Field(default=0, ge=0)
    autonomy_policy: dict[str, Any] | None = None
    # Hire a CLI employee whose backend is not installed; it is stored as
    # ``configuration_required`` and receives no work until fixed.
    allow_unavailable_backend: bool = False


class AgentUpdate(BaseModel):
    """Request body for updating an agent.

    Identity and organisation (company, manager, CEO, department, team) are not fields: an
    unknown key is a 422, never silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    title: str | None = None
    role: str | None = None
    status: str | None = None
    adapter_type: str | None = None
    model: str | None = None
    capabilities: list[str] | None = None
    responsibilities: str | None = None
    objectives: str | None = None
    soul_description: str | None = None
    budget_monthly_cents: int | None = Field(default=None, ge=0)
    autonomy_policy: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    """Response model for an agent."""

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    title: str | None = None
    role: str
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    is_ceo: bool = False
    status: str
    adapter_type: str
    # Read only to derive cli_backend; other adapters may hold connection details.
    adapter_config: dict[str, Any] | None = Field(default=None, exclude=True)
    model: str | None = None
    capabilities: list[str] | None = None
    responsibilities: str | None = None
    objectives: str | None = None
    budget_monthly_cents: int
    spent_monthly_cents: int
    soul_description: str | None = None
    autonomy_policy: dict[str, Any] | None = None
    last_heartbeat_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cli_backend(self) -> str | None:
        """Canonical CLI backend this employee executes through, if any."""
        from nexus.adapters.uastl import ProviderResolutionError, resolve_provider

        try:
            key, config = resolve_provider(
                self.adapter_type, adapter_config=self.adapter_config
            )
        except ProviderResolutionError:
            return None
        return config.get("backend") if key == "cli" else None


@router.post(
    "/api/v1/companies/{company_id}/agents",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentResponse,
    dependencies=WRITE_AGENT,
)
async def create_agent(
    company_id: PathCompanyId, body: AgentCreate, db: DbSession, principal: CurrentPrincipal
) -> Any:
    """Create a new agent in the caller's company.

    A CEO-, manager- or director-like role, any autonomy override and any budget are authority:
    a human administrator decides them. The manager is server-chosen.
    """
    role = body.role.lower()
    if (
        any(word in role for word in PRIVILEGED_ROLE_WORDS)
        or body.autonomy_policy
        or body.budget_monthly_cents
    ) and not can_write(principal):
        raise _forbidden(
            "HUMAN_ADMIN_REQUIRED",
            "Only a human administrator may create a manager or set autonomy or budget",
        )
    adapter_config, model = body.adapter_config, body.model
    status_override = None
    if body.adapter_type == "cli":
        adapter_config, status_override = normalize_cli_employee(
            body.adapter_type, adapter_config, model, body.allow_unavailable_backend
        )
        model = (model or "").strip()
    agent = Agent(
        company_id=company_id,
        name=body.name,
        role=body.role,
        title=body.title,
        department_id=body.department_id,
        team_id=body.team_id,
        adapter_type=body.adapter_type,
        adapter_config=adapter_config,
        model=model,
        capabilities=body.capabilities,
        responsibilities=body.responsibilities,
        objectives=body.objectives,
        soul_description=body.soul_description,
        budget_monthly_cents=body.budget_monthly_cents,
        autonomy_policy=body.autonomy_policy,
    )
    if status_override:
        agent.status = status_override
    agent.manager_id = await ceo_service.resolve_manager(db, company_id, None, None)
    db.add(agent)
    await db.flush()

    # Audit: agent created
    from nexus.governance.audit_service import record_audit
    await record_audit(
        company_id, "agent.created",
        **audit_actor(principal), resource_type="agent", resource_id=str(agent.id),
        details={
            "name": agent.name,
            "role": agent.role,
            "adapter_type": agent.adapter_type,
            "cli_backend": (adapter_config or {}).get("backend") if body.adapter_type == "cli" else None,
            "model": agent.model,
            "status": agent.status,
        },
        db=db,
    )

    return agent


@router.get(
    "/api/v1/companies/{company_id}/agents",
    response_model=list[AgentResponse],
)
async def list_agents(
    company_id: uuid.UUID,
    db: DbSession,
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List agents for a company."""
    stmt = select(Agent).where(Agent.company_id == company_id)
    if status_filter:
        stmt = stmt.where(Agent.status == status_filter)
    stmt = stmt.offset(offset).limit(limit).order_by(Agent.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/api/v1/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get an agent by ID."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return agent


@router.get(
    "/api/v1/companies/{company_id}/agents/{agent_id}",
    response_model=AgentResponse,
)
async def get_agent_company_scoped(
    company_id: uuid.UUID, agent_id: uuid.UUID, db: DbSession
) -> Any:
    """Get an agent by ID (company-scoped path for dashboard compat)."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return agent


async def _guard_cli_update(
    db: Any, agent_id: uuid.UUID, company_id: uuid.UUID, updates: dict[str, Any]
) -> None:
    """Re-validate a CLI employee whose adapter, model or status is changing.

    Stops an update from producing an unvalidated ``cli`` agent, or from
    marking a ``configuration_required`` employee routable while its backend
    is still unusable.
    """
    if not {"adapter_type", "model", "status"} & set(updates):
        return
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    ).scalar_one_or_none()
    if agent is None:
        return  # the caller reports 404
    adapter_type = updates.get("adapter_type", agent.adapter_type)
    if adapter_type != "cli":
        return
    new_status = updates.get("status", agent.status)
    stored = (agent.adapter_config or {}) if agent.adapter_type == "cli" else {}
    # Only these keys reach the runtime; a legacy "cli" agent without a
    # backend always ran Claude Code.
    base = {
        k: stored[k]
        for k in ("backend", "interactive", "use_worktree", "autonomy_mode", "extra_args")
        if k in stored
    }
    if agent.adapter_type == "cli":
        base.setdefault("backend", "claude")
    config, status_override = normalize_cli_employee(
        adapter_type,
        base,
        updates.get("model", agent.model),
        allow_unavailable=new_status == CONFIGURATION_REQUIRED,
    )
    updates["adapter_config"] = config
    if status_override is None and new_status == CONFIGURATION_REQUIRED and "status" not in updates:
        updates["status"] = "idle"  # backend became usable


async def apply_agent_update(
    db: Any, principal: Principal, company_id: uuid.UUID, agent_id: uuid.UUID, body: AgentUpdate
) -> Agent:
    """The one implementation behind PUT, PATCH and the company-scoped PATCH.

    Policy first (the answer does not depend on whether the agent exists), then a lookup by
    ``(company_id, id)``: a foreign and a missing agent are the same 404. Only the validated
    AgentUpdate fields are written, so company, manager and CEO never change here.
    """
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    if any(
        updates.get(k, 0) is None for k in ("role", "status", "adapter_type", "budget_monthly_cents")
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": "FIELD_NOT_NULLABLE", "message": "That field cannot be cleared"},
        )
    enforce_update_policy(principal, updates)
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    fields = sorted(updates)
    await _guard_cli_update(db, agent_id, company_id, updates)
    updates["updated_at"] = utcnow()
    await db.execute(
        update(Agent).where(Agent.id == agent_id, Agent.company_id == company_id).values(**updates)
    )
    agent = (
        await db.execute(
            select(Agent)
            .where(Agent.id == agent_id, Agent.company_id == company_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    from nexus.governance.audit_service import record_audit

    await record_audit(
        company_id, "agent.updated",
        **audit_actor(principal), resource_type="agent", resource_id=str(agent_id),
        details={"fields": fields}, db=db,
    )
    return agent


@router.put(
    "/api/v1/agents/{agent_id}",
    response_model=AgentResponse,
    dependencies=WRITE_AGENT,
)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> Any:
    """Update an agent."""
    return await apply_agent_update(db, principal, company_id, agent_id, body)


@router.patch(
    "/api/v1/agents/{agent_id}",
    response_model=AgentResponse,
    dependencies=WRITE_AGENT,
)
async def patch_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> Any:
    """Partial update an agent (PATCH semantics, same logic as PUT)."""
    return await apply_agent_update(db, principal, company_id, agent_id, body)


@router.patch(
    "/api/v1/companies/{company_id}/agents/{agent_id}",
    response_model=AgentResponse,
    dependencies=WRITE_AGENT,
)
async def patch_agent_company_scoped(
    company_id: PathCompanyId,
    agent_id: uuid.UUID,
    body: AgentUpdate,
    db: DbSession,
    principal: CurrentPrincipal,
) -> Any:
    """Partial update via company-scoped path (dashboard compat)."""
    return await apply_agent_update(db, principal, company_id, agent_id, body)


async def _lifecycle_agent(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return agent


async def _reload(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    return (
        await db.execute(
            select(Agent)
            .where(Agent.id == agent_id, Agent.company_id == company_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


@router.post(
    "/api/v1/agents/{agent_id}/wake",
    response_model=AgentResponse,
    dependencies=WRITE_AGENT,
)
async def wake_agent(
    agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> Any:
    """Wake an agent (transition to ready state).

    Refused while a Governance lockdown or the agent's isolation is active: releasing those is
    a governance decision, never a side effect of waking.
    """
    agent = await _lifecycle_agent(db, company_id, agent_id)
    if await active_restrictions(db, company_id, agent_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "AGENT_RESTRICTED",
                "message": "A Governance lockdown or isolation is active; release it first",
            },
        )
    if agent.status not in ("idle", "paused"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent cannot be woken from status '{agent.status}'",
        )
    update_stmt = (
        update(Agent)
        .where(Agent.id == agent_id, Agent.company_id == company_id)
        .values(status="ready", updated_at=utcnow())
    )
    await db.execute(update_stmt)
    agent = await _reload(db, company_id, agent_id)

    # Audit: agent woken
    from nexus.governance.audit_service import record_audit
    await record_audit(
        company_id, "agent.woken",
        **audit_actor(principal), resource_type="agent", resource_id=str(agent_id),
        details={"name": agent.name, "new_status": "ready"},
        db=db,
    )

    return agent


@router.post(
    "/api/v1/agents/{agent_id}/pause",
    response_model=AgentResponse,
    dependencies=WRITE_AGENT,
)
async def pause_agent(
    agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> Any:
    """Pause an agent. Allowed under isolation or lockdown too: it only removes capability."""
    agent = await _lifecycle_agent(db, company_id, agent_id)
    if agent.status == "terminated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot pause a terminated agent",
        )
    previous = agent.status
    update_stmt = (
        update(Agent)
        .where(Agent.id == agent_id, Agent.company_id == company_id)
        .values(
            status="paused",
            paused_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    await db.execute(update_stmt)
    agent = await _reload(db, company_id, agent_id)

    from nexus.governance.audit_service import record_audit
    await record_audit(
        company_id, "agent.paused",
        **audit_actor(principal), resource_type="agent", resource_id=str(agent_id),
        details={"name": agent.name, "previous_status": previous, "new_status": "paused"},
        db=db,
    )
    return agent


def heartbeat_principal(principal: CurrentPrincipal, agent_id: uuid.UUID) -> Principal:
    """Who may record a heartbeat for ``agent_id`` (default deny).

    An agent's own run token (bound to this exact agent), or a person or API key whose role
    holds ``write:agent``. Any other kind, and a run token for a different agent, is refused.
    """
    if principal.kind == "run" and principal.agent_id == agent_id:
        return principal
    if principal.kind in ("user", "service") and principal.has_permission("write", "agent"):
        return principal
    raise _forbidden("HEARTBEAT_FORBIDDEN", "Not allowed to record a heartbeat for this agent")


@router.post("/api/v1/agents/{agent_id}/heartbeat", dependencies=[Depends(heartbeat_principal)])
async def agent_heartbeat(
    agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId
) -> dict[str, Any]:
    """Record a heartbeat. Writes ``last_heartbeat_at`` only and carries no body."""
    now = utcnow()
    stmt = (
        update(Agent)
        .where(Agent.id == agent_id, Agent.company_id == company_id)
        .values(last_heartbeat_at=now)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return {"agent_id": str(agent_id), "heartbeat_at": now.isoformat()}


@router.delete(
    "/api/v1/agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=WRITE_AGENT,
)
async def delete_agent(agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete an agent that owns no open work, or refuse with a stable 409.

    Every query is scoped to the caller's company. 409 AGENT_OWNS_ACTIVE_WORK when the agent
    holds a task that is not completed, failed or cancelled (ordinary, work order or work
    child, including one in review) or a live attempt; that ownership is never nulled.
    Retention: a terminal task of this company only loses its owner; recorded attempts (and
    any other row that references the agent) are history that pins it (409 AGENT_HAS_HISTORY).
    """
    from sqlalchemy import delete as sa_delete, update as sa_update
    from sqlalchemy.exc import IntegrityError
    from nexus.models.task import Task, Goal
    from nexus.models.agent_worktree import AgentWorktree
    from nexus.services import task_service

    known = await db.scalar(
        select(Agent.id).where(Agent.id == agent_id, Agent.company_id == company_id)
    )
    if known is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # Worktree records are history and pin their agent (RESTRICT), so refuse
    # before touching anything rather than surface a raw FK error.
    held = await db.scalar(
        select(AgentWorktree.id)
        .where(AgentWorktree.agent_id == agent_id, AgentWorktree.company_id == company_id)
        .limit(1)
    )
    if held is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent {agent_id} has agent worktrees and cannot be deleted",
        )

    await task_service.refuse_if_agent_owns_work(db, company_id, agent_id)

    try:
        # Reports move to the CEO; terminal tasks and goals of this company lose this owner.
        await ceo_service.release_reports(db, company_id, agent_id)
        await db.execute(
            sa_update(Task)
            .where(
                Task.company_id == company_id,
                Task.assigned_agent_id == agent_id,
                Task.status.in_(task_service.CLOSED_TASK_STATUSES),
            )
            .values(assigned_agent_id=None)
        )
        await db.execute(
            sa_update(Goal)
            .where(Goal.company_id == company_id, Goal.owner_agent_id == agent_id)
            .values(owner_agent_id=None)
        )
        stmt = sa_delete(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
        result = await db.execute(stmt)
    except IntegrityError:
        # Another row still references the agent, or work arrived meanwhile.
        await db.rollback()
        raise task_service.agent_history_error() from None
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )


@router.post(
    "/api/v1/agents/{agent_id}/clone",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentResponse,
    dependencies=WRITE_AGENT,
)
async def clone_agent(
    agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> Any:
    """Clone an agent for a human administrator: profile, role, model and budget.

    The copy is a plain employee: not the CEO, status idle, the manager chosen by the server.
    Autonomy, permissions, tools, the LLM connection, runtime configuration, memory and
    heartbeat are never copied, and only the allow-listed adapter settings are.
    """
    if not can_write(principal):
        raise _forbidden("HUMAN_ADMIN_REQUIRED", "Only a human administrator may clone an agent")
    source = await _lifecycle_agent(db, company_id, agent_id)
    clone = Agent(
        company_id=company_id,
        name=f"{source.name}-clone",
        role=source.role,
        title=source.title,
        department_id=source.department_id,
        team_id=source.team_id,
        adapter_type=source.adapter_type,
        adapter_config={
            k: v for k, v in (source.adapter_config or {}).items() if k in CLONE_ADAPTER_KEYS
        } or None,
        model=source.model,
        capabilities=list(source.capabilities) if source.capabilities else None,
        responsibilities=source.responsibilities,
        objectives=source.objectives,
        soul_description=source.soul_description,
        budget_monthly_cents=source.budget_monthly_cents,
    )
    clone.manager_id = await ceo_service.resolve_manager(db, company_id, None, None)
    db.add(clone)
    await db.flush()

    from nexus.governance.audit_service import record_audit
    await record_audit(
        company_id, "agent.cloned",
        **audit_actor(principal), resource_type="agent", resource_id=str(clone.id),
        details={"source_agent_id": str(agent_id)}, db=db,
    )
    return clone


class ManagerUpdate(BaseModel):
    """Request body for setting who an agent reports to.

    ``null`` means the CEO while the company has one (it is then the only
    root), otherwise no manager.
    """

    manager_id: uuid.UUID | None = None


@router.put(
    "/api/v1/agents/{agent_id}/manager",
    response_model=AgentResponse,
    dependencies=WRITE_AGENT,
)
async def set_agent_manager(
    agent_id: uuid.UUID,
    body: ManagerUpdate,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> Any:
    """Set or clear the agent's manager (the reporting line the org chart draws).

    Validated by :func:`ceo_service.resolve_manager`: both agents in the
    caller's company, no line back to the agent itself, the CEO reports to no
    one, and ``null`` is the CEO while there is one.
    """
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found"
        )
    target = await ceo_service.resolve_manager(db, company_id, agent_id, body.manager_id)
    previous = agent.manager_id
    if previous == target:
        return agent
    agent.manager_id = target
    agent.updated_at = utcnow()
    await db.flush()

    from nexus.governance.audit_service import record_audit

    change = {
        "agent_id": str(agent_id),
        "previous_manager_id": previous and str(previous),
        "manager_id": target and str(target),
    }
    await record_audit(
        company_id, "agent.manager_changed",
        actor_type="user", actor_id=principal.user_id and str(principal.user_id),
        resource_type="agent", resource_id=str(agent_id), details=change, db=db,
    )
    await db.commit()
    await publish_event(TOPOLOGY_CHANNEL, "agent.manager_changed", company_id, change)
    return agent


class DelegateTaskRequest(BaseModel):
    """Request body for delegating a task to another agent."""

    target_agent_id: uuid.UUID
    title: str
    description: str | None = None
    priority: int = 1


@router.post(
    "/api/v1/agents/{agent_id}/delegate",
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("write", "task"), principal_kinds("user", "service", "run")],
)
async def delegate_task(
    agent_id: uuid.UUID,
    body: DelegateTaskRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Delegate a task from one agent to another.

    Creates a task assigned to the target agent and sends a notification
    via the communication inbox. The source agent is recorded as the requestor.
    Both agents must be in the caller's company, and a caller acting as an
    agent may only delegate as itself.
    """
    from nexus.governance.audit_service import record_audit
    from nexus.models.communication import Message

    if principal.agent_id is not None and agent_id != principal.agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="An agent may only delegate its own work"
        )

    # Verify both agents exist
    source = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    source_agent = source.scalar_one_or_none()
    if not source_agent:
        raise HTTPException(status_code=404, detail="Source agent not found")

    target = await db.execute(select(Agent).where(Agent.id == body.target_agent_id, Agent.company_id == company_id))
    target_agent = target.scalar_one_or_none()
    if not target_agent:
        raise HTTPException(status_code=404, detail="Target agent not found")

    # Create the delegated task
    task = await TaskService(db).create_task(
        company_id,
        body.title,
        body.description or f"Delegated from {source_agent.name}",
        body.priority,
        assigned_agent_id=body.target_agent_id,
    )

    # Send delegation message to target agent's inbox
    msg = Message(
        company_id=company_id,
        sender_agent_id=agent_id,
        recipient_agent_id=body.target_agent_id,
        message_type="delegation",
        content=f"Task delegated: {body.title}",
        priority="normal",
        delivery_route="direct",
    )
    db.add(msg)
    await db.flush()

    result = {
        "task_id": str(task.id),
        "delegated_by": str(agent_id),
        "delegated_to": str(body.target_agent_id),
        "title": body.title,
        "status": "pending",
    }
    await record_audit(
        company_id, "delegation.created",
        actor_type="agent" if principal.agent_id else principal.kind,
        actor_id=str(principal.agent_id or principal.user_id or principal.api_key_id or ""),
        resource_type="task", resource_id=str(task.id), details=result,
        db=db, raise_on_error=True,
    )
    return result
