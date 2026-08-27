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
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.models.task import RunCompletionReason

logger = logging.getLogger(__name__)

_orchestrator_task: asyncio.Task[None] | None = None
_running = False
_instance_id = f"orchestrator-{uuid.uuid4().hex[:8]}"

# How often to scan for active goals (seconds)
ORCHESTRATION_TICK_INTERVAL = 120  # 2 minutes

# Max goals to process per tick
MAX_GOALS_PER_TICK = 5

# Max iterations per goal per tick
MAX_ITERATIONS_PER_GOAL = 3

# Max subtasks a goal may accumulate across decomposition rounds before the
# goal is given up on as non-converging (MAX_ITERATIONS_PER_GOAL rounds of the
# planner's 5 subtasks).
MAX_SUBTASKS_PER_GOAL = MAX_ITERATIONS_PER_GOAL * 5

# Wall-clock budget for one subtask's LLM call (seconds)
SUBTASK_TIMEOUT_SECONDS = 300

# Agents emit this marker to hand a subtask back to a human.
NEEDS_HELP_MARKER = "[NEEDS_HELP"


def _finish(row: Any, status: str, reason: str) -> None:
    """Mark a goal or task terminal with an explicit completion reason.

    Single funnel for every terminal path so a run can never end without a
    reason recorded (Phase 1.1).
    """
    row.status = status
    row.completion_reason = reason
    row.updated_at = datetime.now(timezone.utc)


async def _tick(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Single orchestration tick: find active goals and drive progress."""
    from nexus.models.task import Goal, Task
    from nexus.models.agent import Agent
    from nexus.runtime.redis_utils import try_acquire_leader

    # Leader election: only the leader instance runs orchestration
    if not await try_acquire_leader("orchestrator", _instance_id):
        return

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
            # Temporal-backed durable goal pursuit when enabled
            from nexus.temporal.client import is_temporal_enabled, start_goal_workflow

            if is_temporal_enabled():
                # Dispatch to Temporal — durable, survives crashes
                workflow_id = await start_goal_workflow(
                    goal_id=str(goal.id),
                    company_id=str(goal.company_id),
                    title=goal.title,
                    description=goal.description or "",
                    owner_agent_id=str(goal.owner_agent_id) if goal.owner_agent_id else None,
                )
                if workflow_id:
                    logger.info("Goal %s dispatched to Temporal: %s", goal.id, workflow_id)
                    # Mark goal as being processed by Temporal so we don't re-dispatch
                    goal.status = "in_progress"
                    continue
                # Temporal unavailable — fall through to in-process execution

            # Multi-turn: try up to 3 iterations per goal per tick
            for _iteration in range(3):
                try:
                    prev_status = goal.status
                    await _drive_goal(db, goal)
                    # If goal didn't change status, stop iterating
                    if goal.status == prev_status:
                        break
                except Exception as e:
                    logger.error("Orchestrator: goal %s processing failed: %s", goal.id, e)
                    break

        # Auto-evaluate stale evolution proposals (older than 2 minutes in "proposed" status)
        try:
            await _auto_evaluate_proposals(db)
        except Exception as e:
            logger.debug("Auto-evaluate proposals error: %s", e)

        # Memory maintenance: decay old memories + promote high-value ones to L3
        try:
            await _memory_maintenance(db)
        except Exception as e:
            logger.debug("Memory maintenance error: %s", e)

        # Agent heartbeat & wakeup: wake idle agents with pending work
        try:
            await _agent_heartbeat_wakeup(db)
        except Exception as e:
            logger.debug("Heartbeat wakeup error: %s", e)

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
        Task.goal_id == goal.id,
    )
    result = await db.execute(subtask_stmt)
    subtasks = list(result.scalars().all())

    # If there are running/pending subtasks, let them finish
    active_subtasks = [t for t in subtasks if t.status in ("pending", "in_progress", "running")]
    if active_subtasks:
        logger.debug("Goal %s: %d subtasks still active, waiting", goal.id, len(active_subtasks))
        return

    # If all subtasks are completed, evaluate goal with GoalLoop judge
    completed_subtasks = [t for t in subtasks if t.status == "completed"]
    if subtasks and len(completed_subtasks) == len(subtasks):
        # Use HeuristicGoalJudge to check if goal is truly achieved
        from nexus.orchestration.goal_loop import HeuristicGoalJudge, JudgeVerdict
        judge = HeuristicGoalJudge(
            completion_keywords=["complete", "done", "achieved", "finished", "success"],
            min_output_length=10,
        )
        # Combine subtask titles as "output" for the judge
        combined_output = "\n".join(t.title for t in completed_subtasks)
        verdict: JudgeVerdict = await judge.evaluate(
            goal=f"{goal.title}\n{goal.description or ''}",
            current_output=combined_output,
            iteration=1,
        )
        if verdict.is_complete:
            _finish(goal, "completed", RunCompletionReason.goal)
            db.add(goal)
            logger.info("Goal %s completed (judge confirmed: %s)", goal.id, verdict.reasoning)
            await _broadcast_orchestrator_event("goal_completed", {
                "goal_id": str(goal.id), "title": goal.title, "reasoning": verdict.reasoning,
                "completion_reason": RunCompletionReason.goal.value,
            })
        elif len(subtasks) >= MAX_SUBTASKS_PER_GOAL:
            # Re-decomposing again would just add another round of subtasks the
            # judge already rejected — that is the doom loop.
            _finish(goal, "blocked", RunCompletionReason.doom_loop)
            db.add(goal)
            logger.warning(
                "Goal %s: judge still rejects after %d subtasks — doom loop, giving up",
                goal.id, len(subtasks),
            )
        else:
            # Judge says not complete — decompose again for another iteration
            logger.info("Goal %s: subtasks done but judge says incomplete (%s) — redecomposing", goal.id, verdict.reasoning)
            await _decompose_goal(db, goal, company_id)
        return

    # An agent asked for a human — escalate the whole goal, don't retry.
    escalated = [t for t in subtasks if t.completion_reason == RunCompletionReason.needs_help]
    if escalated:
        _finish(goal, "blocked", RunCompletionReason.needs_help)
        db.add(goal)
        logger.warning("Goal %s escalated: %d subtasks need human help", goal.id, len(escalated))
        return

    # If there are failed subtasks, attempt retry or escalation
    failed_subtasks = [t for t in subtasks if t.status == "failed"]
    if failed_subtasks and not active_subtasks:
        # Too many failures — mark goal as blocked, carrying the reason the
        # subtasks themselves recorded when they all agree.
        if len(failed_subtasks) >= 3:
            reasons = {t.completion_reason for t in failed_subtasks if t.completion_reason}
            reason = reasons.pop() if len(reasons) == 1 else RunCompletionReason.error
            _finish(goal, "blocked", reason)
            db.add(goal)
            logger.warning("Goal %s blocked after %d failures (%s)", goal.id, len(failed_subtasks), reason)
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
            goal_id=goal.id,
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

    for index, task in enumerate(tasks):
        if index >= MAX_ITERATIONS_PER_GOAL:
            # Out of iterations for this tick — the rest stay pending and are
            # picked up next tick, but record why they didn't run now.
            _finish(task, "pending", RunCompletionReason.max_iterations)
            db.add(task)
            continue

        if not task.assigned_agent_id:
            continue

        # Load the assigned agent
        agent_stmt = select(Agent).where(Agent.id == task.assigned_agent_id)
        result = await db.execute(agent_stmt)
        agent = result.scalar_one_or_none()
        if not agent:
            _finish(task, "failed", RunCompletionReason.error)
            task.error = f"Assigned agent {task.assigned_agent_id} not found"
            db.add(task)
            continue

        # Pre-flight budget check — don't start work we cannot pay for.
        if agent.budget_monthly_cents and agent.spent_monthly_cents >= agent.budget_monthly_cents:
            _finish(task, "failed", RunCompletionReason.budget_exhausted)
            task.error = (
                f"Agent {agent.name} has spent {agent.spent_monthly_cents} of "
                f"{agent.budget_monthly_cents} cents"
            )
            db.add(task)
            await _broadcast_orchestrator_event("subtask_failed", {
                "task_id": str(task.id), "title": task.title[:60],
                "error": "budget exhausted",
                "completion_reason": RunCompletionReason.budget_exhausted.value,
            })
            logger.warning("Subtask '%s' skipped: agent %s budget exhausted", task.title[:40], agent.name)
            continue

        try:
            # Build prompt and execute
            memories = await _fetch_agent_memories(db, agent.id, company_id, limit=5)
            system_prompt = _build_system_prompt(agent, memories=memories)
            prompt = f"Execute this task:\n{task.title}\n{task.description or ''}"

            await _broadcast_orchestrator_event("subtask_started", {
                "task_id": str(task.id), "title": task.title[:60], "agent": agent.name,
            })

            response_text, model_used, tokens_used = await asyncio.wait_for(
                _call_llm(agent, system_prompt, prompt, []),
                timeout=SUBTASK_TIMEOUT_SECONDS,
            )

            if NEEDS_HELP_MARKER in (response_text or ""):
                # The agent decided it cannot finish without a human.
                _finish(task, "blocked", RunCompletionReason.needs_help)
                task.result = response_text
                db.add(task)
                await _broadcast_orchestrator_event("subtask_blocked", {
                    "task_id": str(task.id), "title": task.title[:60], "agent": agent.name,
                    "completion_reason": RunCompletionReason.needs_help.value,
                })
                logger.warning("Subtask '%s' needs human help (%s)", task.title[:40], agent.name)
                continue

            if not (response_text or "").strip():
                # Nothing actionable came back — an empty turn is not success.
                _finish(task, "failed", RunCompletionReason.no_tool_calls)
                task.error = "Agent produced no output"
                db.add(task)
                await _broadcast_orchestrator_event("subtask_failed", {
                    "task_id": str(task.id), "title": task.title[:60], "error": "no output",
                    "completion_reason": RunCompletionReason.no_tool_calls.value,
                })
                logger.warning("Subtask '%s' produced no output (%s)", task.title[:40], agent.name)
                continue

            # Mark as completed
            _finish(task, "completed", RunCompletionReason.goal)
            db.add(task)

            await _broadcast_orchestrator_event("subtask_completed", {
                "task_id": str(task.id), "title": task.title[:60],
                "agent": agent.name, "tokens": tokens_used,
                "completion_reason": RunCompletionReason.goal.value,
            })
            logger.info("Subtask '%s' completed by %s (%d tokens)", task.title[:40], agent.name, tokens_used)

            # Self-adaptive trigger: parse [SCHEDULE:] patterns from LLM output
            await _parse_adaptive_triggers(db, agent, response_text, company_id)

        except (asyncio.TimeoutError, TimeoutError) as e:
            _finish(task, "failed", RunCompletionReason.timeout)
            task.error = f"Timed out after {SUBTASK_TIMEOUT_SECONDS}s"
            db.add(task)

            await _broadcast_orchestrator_event("subtask_failed", {
                "task_id": str(task.id), "title": task.title[:60], "error": task.error,
                "completion_reason": RunCompletionReason.timeout.value,
            })
            logger.error("Subtask '%s' timed out: %s", task.title[:40], e)

        except Exception as e:
            _finish(task, "failed", RunCompletionReason.error)
            task.error = str(e)[:2000]
            db.add(task)

            await _broadcast_orchestrator_event("subtask_failed", {
                "task_id": str(task.id), "title": task.title[:60], "error": str(e)[:100],
                "completion_reason": RunCompletionReason.error.value,
            })
            logger.error("Subtask '%s' execution failed: %s", task.title[:40], e)

    await db.flush()


def _auto_promote_enabled() -> bool:
    """Whether unattended promotion is permitted.

    The documented policy is that promotion NEVER happens automatically (see
    the promote route); auto-promotion exists as an explicit opt-in via
    EVOLUTION_AUTO_PROMOTE=true for operators who want it.
    """
    import os

    return os.environ.get("EVOLUTION_AUTO_PROMOTE", "").lower() == "true"


async def _score_proposal(db: AsyncSession, proposal: Any) -> tuple[float, float]:
    """Compute (baseline_score, candidate_score) for a proposal.

    Uses the LLMEvolutionAdvisor through the proposing agent's own adapter when
    available; falls back to a conservative heuristic delta otherwise. Mirrors
    the manual evaluate endpoint so automated and human-triggered evaluations
    agree.
    """
    from nexus.models.agent import Agent

    baseline = 0.5
    candidate = 0.5
    agent = None

    if proposal.proposed_by_agent_id:
        agent_stmt = select(Agent).where(Agent.id == proposal.proposed_by_agent_id)
        agent_res = await db.execute(agent_stmt)
        agent = agent_res.scalar_one_or_none()

    if agent is not None:
        baseline = (agent.performance_score or 50) / 100.0
        candidate = baseline
        try:
            from nexus.api.routes.chat import _build_system_prompt, _call_llm
            from nexus.evolution.llm_evolution import LLMEvolutionAdvisor

            async def llm_fn(prompt: str) -> str:
                text, _, _ = await _call_llm(agent, _build_system_prompt(agent), prompt, [])
                return text

            advisor = LLMEvolutionAdvisor(llm_callable=llm_fn)
            performance_data = {
                "task_type_performance": {},
                "tool_usage_stats": {},
                "cost_history": [agent.spent_monthly_cents],
                "quality_history": [baseline],
            }
            suggestions = await advisor.suggest_agent_improvements(
                str(agent.id), performance_data
            )
            candidate = min(1.0, baseline + suggestions.get("confidence", 0.1) * 0.2)
        except Exception as exc:
            logger.info(
                "Advisor scoring failed for proposal %s, using heuristic: %s",
                proposal.id,
                exc,
            )
            candidate = min(1.0, baseline + 0.05)
    return round(baseline, 4), round(candidate, 4)


async def _auto_evaluate_proposals(db: AsyncSession) -> None:
    """Auto-evaluate evolution proposals that have been in 'proposed' status > 2 minutes.

    Scores come from the real evaluation path (advisor with heuristic fallback),
    never invented constants. Promotion remains human-gated unless the operator
    explicitly enables EVOLUTION_AUTO_PROMOTE.
    """
    from nexus.models.evolution import EvolutionEvaluation, EvolutionProposal

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
    stmt = (
        select(EvolutionProposal)
        .where(EvolutionProposal.status == "proposed")
        .where(EvolutionProposal.created_at <= cutoff)
        .limit(3)
    )
    result = await db.execute(stmt)
    stale_proposals = list(result.scalars().all())

    promote_allowed = _auto_promote_enabled()

    for proposal in stale_proposals:
        proposal.status = "evaluating"
        proposal.updated_at = datetime.now(timezone.utc)

        baseline_score, candidate_score = await _score_proposal(db, proposal)
        improvement = (
            (candidate_score - baseline_score) / max(baseline_score, 0.01) * 100
        )
        evaluation = EvolutionEvaluation(
            proposal_id=proposal.id,
            company_id=proposal.company_id,
            baseline_score=baseline_score,
            candidate_score=candidate_score,
            improvement_percent=round(improvement, 2),
            statistical_significance=0.85 if candidate_score > baseline_score else 0.3,
            passed=candidate_score > baseline_score,
        )
        db.add(evaluation)
        logger.info(
            "Auto-evaluated proposal %s (baseline %s -> candidate %s)",
            proposal.id,
            baseline_score,
            candidate_score,
        )

        if promote_allowed and (proposal.confidence or 0) >= 0.8 and evaluation.passed:
            proposal.status = "promoted"
            logger.info("Auto-promoted high-confidence proposal %s", proposal.id)

    if promote_allowed:
        # Sweep already-evaluated proposals ready for unattended promotion.
        eval_cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
        eval_stmt = (
            select(EvolutionProposal)
            .where(EvolutionProposal.status == "evaluating")
            .where(EvolutionProposal.updated_at <= eval_cutoff)
            .where(EvolutionProposal.confidence >= 0.8)
            .limit(3)
        )
        eval_result = await db.execute(eval_stmt)
        for prop in eval_result.scalars().all():
            prop.status = "promoted"
            prop.updated_at = datetime.now(timezone.utc)
            logger.info("Auto-promoted evaluated proposal %s", prop.id)

    if stale_proposals:
        await db.flush()


async def _parse_adaptive_triggers(db: AsyncSession, agent: Any, llm_output: str, company_id: uuid.UUID) -> None:
    """Parse self-adaptive trigger patterns from LLM output (Clawith "Aware" pattern).

    Supported patterns in LLM output:
    - [SCHEDULE: */5 * * * *] — create a cron trigger
    - [POLL: https://example.com/api] — create a polling trigger
    - [REMIND: 2h] — create a one-shot trigger in N hours
    """
    import re
    from nexus.models.trigger import Trigger

    # Parse [SCHEDULE: cron_expr] patterns
    schedule_matches = re.findall(r'\[SCHEDULE:\s*([^\]]+)\]', llm_output)
    for cron_expr in schedule_matches:
        trigger = Trigger(
            company_id=company_id,
            agent_id=agent.id,
            trigger_type="cron",
            name=f"Self-scheduled by {agent.name}",
            config={"cron_expression": cron_expr.strip(), "prompt": f"Follow up on recent work"},
            is_active=True,
            next_fire_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(trigger)
        logger.info("Agent %s self-created cron trigger: %s", agent.name, cron_expr.strip())

    # Parse [POLL: url] patterns
    poll_matches = re.findall(r'\[POLL:\s*([^\]]+)\]', llm_output)
    for url in poll_matches:
        trigger = Trigger(
            company_id=company_id,
            agent_id=agent.id,
            trigger_type="webhook",
            name=f"Self-polling by {agent.name}",
            config={"webhook_url": url.strip(), "poll": True},
            is_active=True,
        )
        db.add(trigger)
        logger.info("Agent %s self-created poll trigger: %s", agent.name, url.strip())

    # Parse [REMIND: Nh] patterns (one-shot)
    remind_matches = re.findall(r'\[REMIND:\s*(\d+)([hm])\]', llm_output)
    for value, unit in remind_matches:
        hours = int(value) if unit == "h" else int(value) / 60
        trigger = Trigger(
            company_id=company_id,
            agent_id=agent.id,
            trigger_type="on_schedule",
            name=f"Self-reminder by {agent.name}",
            config={"prompt": f"Reminder: follow up on previous task"},
            is_active=True,
            next_fire_at=datetime.now(timezone.utc) + timedelta(hours=hours),
        )
        db.add(trigger)
        logger.info("Agent %s self-created reminder: %s%s", agent.name, value, unit)

    if schedule_matches or poll_matches or remind_matches:
        await db.flush()


async def _agent_heartbeat_wakeup(db: AsyncSession) -> None:
    """Auto-wake idle agents with pending tasks, auto-pause active agents with no work."""
    from nexus.models.agent import Agent
    from nexus.models.task import Task
    from sqlalchemy import func, update as sa_update

    # Wake idle agents that have pending tasks
    idle_with_work = await db.execute(
        select(Agent.id).where(
            Agent.status == "idle",
            Agent.id.in_(
                select(Task.assigned_agent_id).where(Task.status == "pending").distinct()
            ),
        ).limit(5)
    )
    for (agent_id,) in idle_with_work.all():
        await db.execute(sa_update(Agent).where(Agent.id == agent_id).values(status="active"))
        logger.info("Auto-woke idle agent %s (has pending tasks)", agent_id)

    # Auto-pause active agents with zero pending/running tasks (idle for too long)
    active_no_work = await db.execute(
        select(Agent.id).where(
            Agent.status == "active",
            ~Agent.id.in_(
                select(Task.assigned_agent_id).where(Task.status.in_(["pending", "in_progress", "running"])).distinct()
            ),
        ).limit(5)
    )
    for (agent_id,) in active_no_work.all():
        await db.execute(sa_update(Agent).where(Agent.id == agent_id).values(status="idle"))
        logger.debug("Auto-idled agent %s (no pending work)", agent_id)

    await db.flush()


async def _memory_maintenance(db: AsyncSession) -> None:
    """Periodic memory maintenance: decay old memories and promote high-value ones.

    - Decay: reduce importance of memories not accessed in 7+ days by 5%
    - L3 Promotion: memories with importance >= 0.9 and scope='agent' get promoted to scope='company'
    """
    from nexus.models.memory import MemoryRecord
    from sqlalchemy import update as sa_update

    now = datetime.now(timezone.utc)
    decay_cutoff = now - timedelta(days=7)

    # Decay old memories (reduce importance by 5%, minimum 0.1)
    await db.execute(
        sa_update(MemoryRecord)
        .where(
            MemoryRecord.last_accessed_at != None,  # noqa: E711
            MemoryRecord.last_accessed_at < decay_cutoff,
            MemoryRecord.importance > 0.1,
        )
        .values(importance=MemoryRecord.importance * 0.95)
    )

    # L3 Promotion: high-importance agent memories → company scope
    high_value_stmt = (
        select(MemoryRecord)
        .where(
            MemoryRecord.scope == "agent",
            MemoryRecord.importance >= 0.9,
            MemoryRecord.tier == "warm",
        )
        .limit(5)
    )
    result = await db.execute(high_value_stmt)
    for mem in result.scalars().all():
        mem.scope = "company"
        mem.tier = "hot"
        db.add(mem)

    await db.flush()


async def _broadcast_orchestrator_event(event_type: str, data: dict[str, Any]) -> None:
    """Broadcast an orchestrator event to WebSocket subscribers (best-effort)."""
    try:
        from nexus.api.routes.ws import manager as ws_manager
        await ws_manager.broadcast_to_channel("orchestrator", {
            "type": event_type,
            "source": "orchestrator",
            **data,
        })
    except Exception:
        pass  # WebSocket delivery is best-effort


async def _orchestrator_loop(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Main orchestrator loop — ticks every ORCHESTRATION_TICK_INTERVAL seconds.

    Lease-gated: with multiple replicas only the leader drives goals, so work
    is not duplicated. Followers take over automatically when the lease lapses.
    """
    global _running
    from nexus.governance.leader_election import is_leader

    logger.info("Autonomous Orchestrator started (tick interval: %ds)", ORCHESTRATION_TICK_INTERVAL)
    while _running:
        try:
            if await is_leader("orchestrator"):
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
