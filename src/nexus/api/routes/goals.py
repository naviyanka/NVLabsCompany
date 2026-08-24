"""Goal API endpoints - strategic goal management."""

import uuid
from datetime import timezone, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.task import Goal

router = APIRouter(tags=["goals"])


class GoalCreate(BaseModel):
    """Request body for creating a goal."""

    title: str
    description: str | None = None
    level: str = "company"
    parent_id: uuid.UUID | None = None
    owner_agent_id: uuid.UUID | None = None


class GoalUpdate(BaseModel):
    """Request body for updating a goal."""

    title: str | None = None
    description: str | None = None
    level: str | None = None
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
    created_at: datetime
    updated_at: datetime


@router.post(
    "/api/v1/companies/{company_id}/goals",
    status_code=status.HTTP_201_CREATED,
    response_model=GoalResponse,
)
async def create_goal(
    company_id: uuid.UUID, body: GoalCreate, db: DbSession
) -> Any:
    """Create a new strategic goal."""
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
    return goal


@router.get(
    "/api/v1/companies/{company_id}/goals",
    response_model=list[GoalResponse],
)
async def list_goals(
    company_id: uuid.UUID,
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


@router.get("/api/v1/goals/{goal_id}", response_model=GoalResponse)
async def get_goal(goal_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get a goal by ID."""
    stmt = select(Goal).where(Goal.id == goal_id, Goal.company_id == company_id)
    result = await db.execute(stmt)
    goal = result.scalar_one_or_none()
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal {goal_id} not found",
        )
    return goal


@router.put("/api/v1/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: uuid.UUID, body: GoalUpdate, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Update a goal."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    updates["updated_at"] = datetime.now(timezone.utc)
    stmt = update(Goal).where(Goal.id == goal_id, Goal.company_id == company_id).values(**updates)
    await db.execute(stmt)

    result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.company_id == company_id))
    goal = result.scalar_one_or_none()
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal {goal_id} not found",
        )
    return goal



@router.delete("/api/v1/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(goal_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete a goal with company_id check."""
    from sqlalchemy import delete as sa_delete

    stmt = sa_delete(Goal).where(Goal.id == goal_id, Goal.company_id == company_id)
    await db.execute(stmt)


@router.get("/api/v1/companies/{company_id}/goals/stats")
async def get_goal_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Goal statistics: total and by status."""
    from sqlalchemy import func

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


@router.post("/api/v1/goals/{goal_id}/execute")
async def execute_goal(
    goal_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Execute a goal using the GoalLoop orchestration module.

    Autonomously iterates: calls the assigned agent, evaluates progress
    against the goal using a heuristic judge, and repeats until the goal
    is achieved or safety limits are hit (max iterations, budget).
    """
    from nexus.models.agent import Agent
    from nexus.orchestration.goal_loop import GoalLoop, GoalResult, HeuristicGoalJudge
    from nexus.api.routes.chat import _build_system_prompt, _call_llm

    stmt = select(Goal).where(Goal.id == goal_id, Goal.company_id == company_id)
    result = await db.execute(stmt)
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    # Find the owner agent or any active agent
    agent = None
    if goal.owner_agent_id:
        a_stmt = select(Agent).where(Agent.id == goal.owner_agent_id, Agent.company_id == company_id)
        a_res = await db.execute(a_stmt)
        agent = a_res.scalar_one_or_none()

    if not agent:
        a_stmt = select(Agent).where(Agent.company_id == company_id, Agent.status.in_(["active", "ready"])).limit(1)
        a_res = await db.execute(a_stmt)
        agent = a_res.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=409, detail="No available agent to execute this goal")

    # Build execution function for the GoalLoop
    system_prompt = _build_system_prompt(agent)
    goal_description = f"{goal.title}\n{goal.description or ''}"

    async def execute_fn() -> tuple[str, int]:
        """Call the agent to work toward the goal."""
        response_text, _model, tokens = await _call_llm(
            agent, system_prompt, goal_description, []
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
    from sqlalchemy import update as sa_update
    new_status = "completed" if goal_result.success else "active"
    await db.execute(
        sa_update(Goal).where(Goal.id == goal_id).values(status=new_status, updated_at=datetime.now(timezone.utc))
    )
    await db.commit()

    return {
        "goal_id": str(goal_id),
        "success": goal_result.success,
        "iterations_used": goal_result.iterations_used,
        "total_cost_cents": goal_result.total_cost_cents,
        "stop_reason": goal_result.stop_reason,
        "final_output": str(goal_result.final_output)[:2000] if goal_result.final_output else None,
        "new_status": new_status,
    }
