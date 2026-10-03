"""Goal API endpoints - strategic goal management.

Every route needs a goal permission (``read:goal`` or ``write:goal``) and is bound to the
caller's company. Company-in-the-URL routes use ``PathCompanyId``, so a foreign or made-up
company is the same 403 in every UUID spelling. Parents and owners are loaded by
``(company_id, id)`` (a foreign-key check would accept another tenant's row), and the status
lifecycle is validated here, never left to the client.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update

from nexus.api.deps import (
    CurrentCompanyId,
    CurrentPrincipal,
    DbSession,
    PathCompanyId,
    audit_actor,
    principal_kinds,
    require_permission,
)
from nexus.models._time import utcnow
from nexus.models.task import Goal, RunCompletionReason, Task
from nexus.services import work_service
from nexus.services.task_service import (
    CLOSED_GOAL_STATUSES,
    require_assignable_agent,
    require_goal,
)
from nexus.tools.governance_overlay import active_restrictions

router = APIRouter(tags=["goals"])

# GoalLoop reports its own vocabulary for why it stopped; map it onto the
# Phase 1.1 taxonomy so every terminal path speaks one language.
_LOOP_STOP_REASONS = {
    "judge_confirmed": RunCompletionReason.goal,
    "max_iterations": RunCompletionReason.max_iterations,
    "budget_exceeded": RunCompletionReason.budget_exhausted,
    "parse_failures": RunCompletionReason.doom_loop,
    "execution_error": RunCompletionReason.error,
}

GOAL_STATUSES = ("active", "in_progress", "blocked", "paused", *CLOSED_GOAL_STATUSES)

# Every non-GET goal route declares WRITE_GOAL: tests/test_goal_route_security walks the router
# and fails a route that does not. Run tokens and any principal kind added later are denied.
READ_GOAL = [require_permission("read", "goal")]
WRITE_GOAL = [require_permission("write", "goal"), principal_kinds("user", "service")]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class GoalCreate(BaseModel):
    """Request body for creating a goal. A new goal always starts ``active``."""

    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    level: str = Field(default="company", min_length=1, max_length=50)
    parent_id: uuid.UUID | None = None
    owner_agent_id: uuid.UUID | None = None


class GoalUpdate(BaseModel):
    """Request body for updating a goal."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    level: str | None = Field(default=None, min_length=1, max_length=50)
    status: str | None = None
    owner_agent_id: uuid.UUID | None = None


class GoalResponse(BaseModel):
    """Response model for a goal."""

    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    description: str | None = None
    level: str
    status: str
    parent_id: uuid.UUID | None = None
    owner_agent_id: uuid.UUID | None = None
    completion_reason: str | None = None
    created_at: datetime
    updated_at: datetime


async def _load_goal(db: Any, company_id: uuid.UUID, goal_id: uuid.UUID) -> Goal:
    goal = (
        await db.execute(select(Goal).where(Goal.id == goal_id, Goal.company_id == company_id))
    ).scalar_one_or_none()
    if goal is None:
        raise _error(status.HTTP_404_NOT_FOUND, "GOAL_NOT_FOUND", "Goal not found")
    return goal


async def _require_no_open_work(db: Any, company_id: uuid.UUID, goal_id: uuid.UUID) -> None:
    """A goal with live work orders is closed or driven by the work lifecycle, not from here."""
    open_orders = (
        await db.execute(
            select(func.count(Task.id)).where(
                Task.company_id == company_id,
                Task.goal_id == goal_id,
                work_service._work_order_clause(),
                Task.status.not_in((*work_service.CLOSED_STATUSES, "failed")),
            )
        )
    ).scalar() or 0
    if open_orders:
        raise _error(
            status.HTTP_409_CONFLICT,
            "GOAL_HAS_OPEN_WORK",
            "The goal has open work orders; finish or cancel them first",
        )


@router.post(
    "/api/v1/companies/{company_id}/goals",
    status_code=status.HTTP_201_CREATED,
    response_model=GoalResponse,
    dependencies=WRITE_GOAL,
)
async def create_goal(
    company_id: PathCompanyId, body: GoalCreate, db: DbSession, principal: CurrentPrincipal
) -> Any:
    """Create a new strategic goal.

    The parent must be an open goal of this company and the owner an agent of this company that
    can take work; a foreign and a missing parent or owner are the same 404, and nothing is
    written when either check fails.
    """
    if body.parent_id is not None:
        await require_goal(db, company_id, body.parent_id)
    if body.owner_agent_id is not None:
        await require_assignable_agent(db, company_id, body.owner_agent_id)
    goal = Goal(
        company_id=company_id,
        title=body.title,
        description=body.description,
        level=body.level,
        parent_id=body.parent_id,
        owner_agent_id=body.owner_agent_id,
    )
    db.add(goal)
    await db.flush()

    from nexus.governance.audit_service import record_audit

    await record_audit(
        company_id, "goal.created",
        **audit_actor(principal), resource_type="goal", resource_id=str(goal.id),
        details={"level": goal.level}, db=db,
    )
    return goal


@router.get(
    "/api/v1/companies/{company_id}/goals",
    response_model=list[GoalResponse],
    dependencies=READ_GOAL,
)
async def list_goals(
    company_id: PathCompanyId,
    db: DbSession,
    level: str | None = None,
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List goals for a company."""
    stmt = select(Goal).where(Goal.company_id == company_id)
    if level:
        stmt = stmt.where(Goal.level == level)
    if status_filter:
        stmt = stmt.where(Goal.status == status_filter)
    stmt = stmt.offset(offset).limit(limit).order_by(Goal.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/api/v1/goals/{goal_id}", response_model=GoalResponse, dependencies=READ_GOAL)
async def get_goal(goal_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get a goal by ID."""
    return await _load_goal(db, company_id, goal_id)


@router.put("/api/v1/goals/{goal_id}", response_model=GoalResponse, dependencies=WRITE_GOAL)
async def update_goal(
    goal_id: uuid.UUID,
    body: GoalUpdate,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> Any:
    """Update a goal.

    ``status`` must be a known value. A closed goal is not reopened or edited: the only change
    allowed is archiving a completed or cancelled one. Completing a goal that still has open
    work orders is refused.
    """
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    if any(updates.get(k, 0) is None for k in ("title", "level", "status")):
        raise _error(422, "FIELD_NOT_NULLABLE", "That field cannot be cleared")
    new_status = updates.get("status")
    if new_status is not None and new_status not in GOAL_STATUSES:
        raise _error(422, "GOAL_STATUS_INVALID", "Unknown goal status")

    goal = await _load_goal(db, company_id, goal_id)
    if goal.status in CLOSED_GOAL_STATUSES and not (
        updates == {"status": "archived"} and goal.status != "archived"
    ):
        raise _error(status.HTTP_409_CONFLICT, "GOAL_CLOSED", "The goal is closed")
    if updates.get("owner_agent_id") is not None:
        await require_assignable_agent(db, company_id, updates["owner_agent_id"])
    if new_status == "completed" and goal.status != "completed":
        await _require_no_open_work(db, company_id, goal_id)

    fields = sorted(updates)
    updates["updated_at"] = utcnow()
    await db.execute(
        update(Goal).where(Goal.id == goal_id, Goal.company_id == company_id).values(**updates)
    )
    goal = (
        await db.execute(
            select(Goal)
            .where(Goal.id == goal_id, Goal.company_id == company_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    from nexus.governance.audit_service import record_audit

    await record_audit(
        company_id, "goal.updated",
        **audit_actor(principal), resource_type="goal", resource_id=str(goal_id),
        details={"fields": fields}, db=db,
    )
    return goal


@router.delete(
    "/api/v1/goals/{goal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=WRITE_GOAL,
)
async def delete_goal(
    goal_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> None:
    """Delete a goal of this company; a foreign and a missing goal are the same 404."""
    await _load_goal(db, company_id, goal_id)
    await db.execute(sa_delete(Goal).where(Goal.id == goal_id, Goal.company_id == company_id))

    from nexus.governance.audit_service import record_audit

    await record_audit(
        company_id, "goal.deleted",
        **audit_actor(principal), resource_type="goal", resource_id=str(goal_id), db=db,
    )


@router.get("/api/v1/companies/{company_id}/goals/stats", dependencies=READ_GOAL)
async def get_goal_stats(company_id: PathCompanyId, db: DbSession) -> dict[str, Any]:
    """Goal statistics: total and by status."""
    total_result = await db.execute(
        select(func.count(Goal.id)).where(Goal.company_id == company_id)
    )
    total = total_result.scalar() or 0

    status_result = await db.execute(
        select(Goal.status, func.count(Goal.id))
        .where(Goal.company_id == company_id)
        .group_by(Goal.status)
    )
    by_status = dict(status_result.all())

    return {"total": total, "by_status": by_status}


@router.post("/api/v1/goals/{goal_id}/execute", dependencies=WRITE_GOAL)
async def execute_goal(
    goal_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Execute a goal using the GoalLoop orchestration module.

    Autonomously iterates: calls the assigned agent, evaluates progress
    against the goal using a heuristic judge, and repeats until the goal
    is achieved or safety limits are hit (max iterations, budget).

    Only an open goal runs, only with an agent that can take work and is not isolated or under
    a company lockdown, and never while the goal has open work orders (the work lifecycle owns
    those). It creates no tasks.
    """
    from nexus.models.agent import Agent
    from nexus.orchestration.goal_loop import GoalLoop, GoalResult, HeuristicGoalJudge
    from nexus.api.routes.chat import _build_system_prompt, _call_llm

    goal = await require_goal(db, company_id, goal_id)
    await _require_no_open_work(db, company_id, goal_id)

    # Find the owner agent or any active agent
    agent = None
    if goal.owner_agent_id:
        agent = await require_assignable_agent(db, company_id, goal.owner_agent_id)

    if not agent:
        a_stmt = select(Agent).where(Agent.company_id == company_id, Agent.status.in_(["active", "ready"])).limit(1)
        a_res = await db.execute(a_stmt)
        agent = a_res.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=409, detail="No available agent to execute this goal")
    if await active_restrictions(db, company_id, agent.id):
        raise _error(
            status.HTTP_409_CONFLICT,
            "AGENT_RESTRICTED",
            "A Governance lockdown or isolation is active; release it first",
        )

    # Build execution function for the GoalLoop
    system_prompt = _build_system_prompt(agent)
    goal_description = f"{goal.title}\n{goal.description or ''}"

    async def execute_fn() -> tuple[str, int]:
        """Call the agent to work toward the goal."""
        response_text, _model, tokens = await _call_llm(
            agent, system_prompt, goal_description, [], principal=principal
        )
        # Cost in cents: ~1 cent per 500 tokens
        cost_cents = max(1, tokens // 500)
        return response_text, cost_cents

    # Run the goal loop with safety limits
    judge = HeuristicGoalJudge(
        completion_keywords=["complete", "done", "achieved", "finished", "accomplished"],
    )
    loop = GoalLoop(judge=judge, max_iterations=5, budget_limit_cents=2500)
    goal_result: GoalResult = await loop.run(
        task_id=goal.id,
        goal=goal_description,
        execute_fn=execute_fn,
    )

    # Update goal status based on result
    new_status = "completed" if goal_result.success else "active"
    reason = _LOOP_STOP_REASONS.get(
        goal_result.stopped_reason or "", RunCompletionReason.error
    ).value
    await db.execute(
        update(Goal)
        .where(Goal.id == goal_id, Goal.company_id == company_id)
        .values(
            status=new_status,
            completion_reason=reason,
            updated_at=utcnow(),
        )
    )

    from nexus.governance.audit_service import record_audit

    await record_audit(
        company_id, "goal.executed",
        **audit_actor(principal), resource_type="goal", resource_id=str(goal_id),
        details={"new_status": new_status, "completion_reason": reason}, db=db,
    )
    await db.commit()

    return {
        "goal_id": str(goal_id),
        "success": goal_result.success,
        "iterations_used": goal_result.iterations_used,
        "total_cost_cents": goal_result.total_cost_cents,
        "stop_reason": goal_result.stopped_reason,
        "completion_reason": reason,
        "judge_verdict": goal_result.judge_verdict,
        "final_output": str(goal_result.final_output)[:2000] if goal_result.final_output else None,
        "new_status": new_status,
    }
