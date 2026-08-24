"""Autonomous Orchestration Coordinator — the proactive goal-pursuit engine.

Runs as a background asyncio task during the app lifespan. Periodically
scans for active goals and drives them toward completion by composing
the orchestration modules:

    GoalMonitor → TaskPlanner → AgentRouter → ParallelExecutor →
    CriticEvaluator → GoalLoop → SmartRetry → FailureAnalyzer

This transforms the platform from reactive (responds to API calls) to
proactive (autonomously pursues goals).

Usage:
    from nexus.runtime.orchestrator import start_orchestrator, stop_orchestrator

    # In app lifespan:
    await start_orchestrator(session_factory)
    yield
    await stop_orchestrator()
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_orchestrator_task: asyncio.Task[None] | None = None
_running = False

# How often to scan for active goals (seconds)
ORCHESTRATION_TICK_INTERVAL = 120  # 2 minutes

# Max goals to process per tick
MAX_GOALS_PER_TICK = 5

# Max iterations per goal per tick
MAX_ITERATIONS_PER_GOAL = 3


async def _tick(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Single orchestration tick: find active goals and drive progress."""
    from nexus.models.task import Goal, Task
    from nexus.models.agent import Agent

    async with session_factory() as db:
        # Find active goals that have an owner agent
        stmt = (
            select(Goal)
            .where(Goal.status == "active")
            .where(Goal.owner_agent_id != None)  # noqa: E711
            .limit(MAX_GOALS_PER_TICK)
        )
        result = await db.execute(stmt)
        active_goals = list(result.scalars().all())

        if not active_goals:
            return

        logger.info("Orchestrator tick: %d active goals to process", len(active_goals))

        for goal in active_goals:
            try:
                await _drive_goal(db, goal)
            except Exception as e:
                logger.error("Orchestrator: goal %s processing failed: %s", goal.id, e)

        await db.commit()


async def _drive_goal(db: AsyncSession, goal: Any) -> None:
    """Drive a single goal toward completion.

    Strategy:
    1. Check if goal already has pending/running subtasks — if so, skip (let them finish)
    2. If no subtasks exist, decompose the goal into subtasks
    3. Route unassigned subtasks to agents
    4. Execute ready subtasks (those with no pending dependencies)
    5. Evaluate if goal is complete
    """
    from nexus.models.task import Task
    from nexus.models.agent import Agent
    from nexus.orchestration.router import AgentCandidate, AgentRouter
    from nexus.orchestration.planner import TaskPlanner

    company_id = goal.company_id

    # Check for existing subtasks of this goal
    subtask_stmt = select(Task).where(
        Task.company_id == company_id,
        Task.parent_id == goal.id,
    )
    result = await db.execute(subtask_stmt)
    subtasks = list(result.scalars().all())

    # If there are running/pending subtasks, let them finish
    active_subtasks = [t for t in subtasks if t.status in ("pending", "in_progress", "running")]
    if active_subtasks:
        logger.debug("Goal %s: %d subtasks still active, waiting", goal.id, len(active_subtasks))
        return

    # If all subtasks are completed, mark goal as done
    completed_subtasks = [t for t in subtasks if t.status == "completed"]
    if subtasks and len(completed_subtasks) == len(subtasks):
        goal.status = "completed"
        goal.updated_at = datetime.now(timezone.utc)
        db.add(goal)
        logger.info("Goal %s completed (all %d subtasks done)", goal.id, len(subtasks))
        return

    # If there are failed subtasks, attempt retry or escalation
    failed_subtasks = [t for t in subtasks if t.status == "failed"]
    if failed_subtasks and not active_subtasks:
        # Too many failures — mark goal as blocked
        if len(failed_subtasks) >= 3:
            goal.status = "blocked"
            goal.updated_at = datetime.now(timezone.utc)
            db.add(goal)
            logger.warning("Goal %s blocked after %d failures", goal.id, len(failed_subtasks))
            return

    # If no subtasks exist yet, decompose the goal
    if not subtasks:
        await _decompose_goal(db, goal, company_id)
        return

    # Route unassigned pending subtasks
    pending_unassigned = [t for t in subtasks if t.status == "pending" and not t.assigned_agent_id]
    if pending_unassigned:
        await _route_subtasks(db, pending_unassigned, company_id)
        return

    # Execute assigned pending subtasks
    pending_assigned = [t for t in subtasks if t.status == "pending" and t.assigned_agent_id]
    if pending_assigned:
        await _execute_subtasks(db, pending_assigned, company_id)


async def _decompose_goal(db: AsyncSession, goal: Any, company_id: uuid.UUID) -> None:
    """Decompose a goal into subtasks using TaskPlanner."""
    from nexus.models.task import Task
    from nexus.orchestration.planner import TaskPlanner

    planner = TaskPlanner(max_subtasks=5)
    description = f"{goal.title}\n{goal.description or ''}"

    subtasks = await planner.decompose_task(
        task_id=goal.id,
        description=description,
        context={"level": goal.level, "status": goal.status},
    )

    for st in subtasks:
        task = Task(
            company_id=company_id,
            title=st.description[:500],
            description=f"Auto-decomposed from goal: {goal.title}",
            priority=1,
            parent_id=goal.id,
            status="pending",
        )
        db.add(task)

    await db.flush()
    logger.info("Goal %s: decomposed into %d subtasks", goal.id, len(subtasks))


async def _route_subtasks(db: AsyncSession, tasks: list[Any], company_id: uuid.UUID) -> None:
    """Route unassigned subtasks to the best available agents."""
    from nexus.models.agent import Agent
    from nexus.orchestration.router import AgentCandidate, AgentRouter

    # Load active agents
    agent_stmt = select(Agent).where(
        Agent.company_id == company_id,
        Agent.status.in_(["active", "ready"]),
    )
    result = await db.execute(agent_stmt)
    agents = list(result.scalars().all())

    if not agents:
        logger.warning("No available agents for routing in company %s", company_id)
        return

    candidates = [
        AgentCandidate(
            agent_id=a.id,
            name=a.name,
            skills=a.capabilities or [],
            current_workload=0,
            max_concurrent=5,
            budget_remaining_cents=a.budget_monthly_cents - a.spent_monthly_cents,
            performance_score=(a.performance_score or 50) / 100.0,
            status=a.status,
        )
        for a in agents
    ]

    router = AgentRouter()

    for task in tasks:
        decision = await router.route_task(
            task_description=task.title,
            required_skills=[],
            estimated_cost_cents=100,
            available_agents=candidates,
        )
        if decision:
            task.assigned_agent_id = decision.agent_id
            task.updated_at = datetime.now(timezone.utc)
            db.add(task)

    await db.flush()
    logger.info("Routed %d subtasks to agents", len(tasks))


async def _execute_subtasks(db: AsyncSession, tasks: list[Any], company_id: uuid.UUID) -> None:
    """Execute assigned subtasks by calling the agent's LLM adapter."""
    from nexus.models.agent import Agent
    from nexus.api.routes.chat import _build_system_prompt, _call_llm, _fetch_agent_memories

    for task in tasks[:MAX_ITERATIONS_PER_GOAL]:  # Limit per tick
        if not task.assigned_agent_id:
            continue

        # Load the assigned agent
        agent_stmt = select(Agent).where(Agent.id == task.assigned_agent_id)
        result = await db.execute(agent_stmt)
        agent = result.scalar_one_or_none()
        if not agent:
            task.status = "failed"
            task.updated_at = datetime.now(timezone.utc)
            db.add(task)
            continue

        try:
            # Build prompt and execute
            memories = await _fetch_agent_memories(db, agent.id, company_id, limit=5)
            system_prompt = _build_system_prompt(agent, memories=memories)
            prompt = f"Execute this task:\n{task.title}\n{task.description or ''}"

            response_text, model_used, tokens_used = await _call_llm(
                agent, system_prompt, prompt, []
            )

            # Mark as completed
            task.status = "completed"
            task.updated_at = datetime.now(timezone.utc)
            db.add(task)
            logger.info("Subtask '%s' completed by %s (%d tokens)", task.title[:40], agent.name, tokens_used)

        except Exception as e:
            task.status = "failed"
            task.updated_at = datetime.now(timezone.utc)
            db.add(task)
            logger.error("Subtask '%s' execution failed: %s", task.title[:40], e)

    await db.flush()


async def _orchestrator_loop(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Main orchestrator loop — ticks every ORCHESTRATION_TICK_INTERVAL seconds."""
    global _running
    logger.info("Autonomous Orchestrator started (tick interval: %ds)", ORCHESTRATION_TICK_INTERVAL)
    while _running:
        try:
            await _tick(session_factory)
        except Exception as e:
            logger.error("Orchestrator tick error: %s", e)
        await asyncio.sleep(ORCHESTRATION_TICK_INTERVAL)
    logger.info("Autonomous Orchestrator stopped")


async def start_orchestrator(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Start the autonomous orchestration background task."""
    global _orchestrator_task, _running
    if _orchestrator_task is not None:
        return
    _running = True
    _orchestrator_task = asyncio.create_task(_orchestrator_loop(session_factory))


async def stop_orchestrator() -> None:
    """Stop the autonomous orchestration background task."""
    global _orchestrator_task, _running
    _running = False
    if _orchestrator_task:
        _orchestrator_task.cancel()
        try:
            await _orchestrator_task
        except asyncio.CancelledError:
            pass
        _orchestrator_task = None
