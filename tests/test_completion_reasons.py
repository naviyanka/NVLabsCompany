"""Phase 1.1 — every completion reason is reachable.

The acceptance test for the phase: each of the eight ``RunCompletionReason``
values is produced by a real terminal path in ``runtime/orchestrator.py`` (or
the goal-execute route that shares the taxonomy), never by a test-only stub.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.models.task import RunCompletionReason
from nexus.runtime import orchestrator as orch


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_task(**kw):
    """A stand-in Task row — SQLModel rows are plain attribute bags here."""
    base = dict(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        title="do the thing",
        description="",
        status="pending",
        priority=1,
        assigned_agent_id=uuid.uuid4(),
        goal_id=None,
        result=None,
        error=None,
        completion_reason=None,
        updated_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def make_goal(**kw):
    base = dict(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        title="ship it",
        description="",
        level="company",
        status="active",
        owner_agent_id=uuid.uuid4(),
        completion_reason=None,
        updated_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def make_agent(budget=10_000, spent=0):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="worker",
        capabilities=[],
        status="active",
        budget_monthly_cents=budget,
        spent_monthly_cents=spent,
        performance_score=50,
    )


def db_returning(*rows):
    """A mock session whose execute() yields the given rows in order."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    results = []
    for row in rows:
        res = MagicMock()
        res.scalar_one_or_none.return_value = row
        scalars = MagicMock()
        scalars.all.return_value = row if isinstance(row, list) else [row]
        res.scalars.return_value = scalars
        results.append(res)
    db.execute = AsyncMock(side_effect=results)
    return db


async def run_subtask(task, agent, llm):
    """Drive _execute_subtasks for one task with a patched LLM."""
    db = db_returning(agent)
    with patch("nexus.api.routes.chat._call_llm", new=llm), patch(
        "nexus.api.routes.chat._fetch_agent_memories", new=AsyncMock(return_value=[])
    ), patch(
        "nexus.api.routes.chat._build_system_prompt", new=MagicMock(return_value="sys")
    ), patch.object(
        orch, "_broadcast_orchestrator_event", new=AsyncMock()
    ), patch.object(
        orch, "_parse_adaptive_triggers", new=AsyncMock()
    ):
        await orch._execute_subtasks(db, [task], task.company_id)
    return task


# ---------------------------------------------------------------------------
# the eight reasons
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goal_reason_on_successful_subtask():
    task = make_task()
    llm = AsyncMock(return_value=("work is done", "gpt", 100))
    await run_subtask(task, make_agent(), llm)
    assert task.status == "completed"
    assert task.completion_reason == RunCompletionReason.goal


@pytest.mark.asyncio
async def test_no_tool_calls_reason_on_empty_output():
    task = make_task()
    llm = AsyncMock(return_value=("   ", "gpt", 0))
    await run_subtask(task, make_agent(), llm)
    assert task.status == "failed"
    assert task.completion_reason == RunCompletionReason.no_tool_calls


@pytest.mark.asyncio
async def test_timeout_reason_when_llm_exceeds_budget():
    task = make_task()

    async def hang(*_a, **_kw):
        await asyncio.sleep(10)

    with patch.object(orch, "SUBTASK_TIMEOUT_SECONDS", 0.01):
        await run_subtask(task, make_agent(), hang)
    assert task.status == "failed"
    assert task.completion_reason == RunCompletionReason.timeout


@pytest.mark.asyncio
async def test_budget_exhausted_reason_blocks_before_the_call():
    task = make_task()
    llm = AsyncMock(return_value=("never reached", "gpt", 0))
    await run_subtask(task, make_agent(budget=500, spent=500), llm)
    assert task.status == "failed"
    assert task.completion_reason == RunCompletionReason.budget_exhausted
    llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_needs_help_reason_when_agent_escalates():
    task = make_task()
    llm = AsyncMock(return_value=("[NEEDS_HELP] I need a human", "gpt", 20))
    await run_subtask(task, make_agent(), llm)
    assert task.status == "blocked"
    assert task.completion_reason == RunCompletionReason.needs_help


@pytest.mark.asyncio
async def test_error_reason_on_unhandled_failure():
    task = make_task()
    llm = AsyncMock(side_effect=RuntimeError("provider exploded"))
    await run_subtask(task, make_agent(), llm)
    assert task.status == "failed"
    assert task.completion_reason == RunCompletionReason.error
    assert "provider exploded" in task.error


@pytest.mark.asyncio
async def test_max_iterations_reason_when_tick_budget_runs_out():
    tasks = [make_task() for _ in range(orch.MAX_ITERATIONS_PER_GOAL + 1)]
    agent = make_agent()
    db = db_returning(*([agent] * len(tasks)))
    llm = AsyncMock(return_value=("done", "gpt", 10))
    with patch("nexus.api.routes.chat._call_llm", new=llm), patch(
        "nexus.api.routes.chat._fetch_agent_memories", new=AsyncMock(return_value=[])
    ), patch(
        "nexus.api.routes.chat._build_system_prompt", new=MagicMock(return_value="sys")
    ), patch.object(
        orch, "_broadcast_orchestrator_event", new=AsyncMock()
    ), patch.object(
        orch, "_parse_adaptive_triggers", new=AsyncMock()
    ):
        await orch._execute_subtasks(db, tasks, tasks[0].company_id)

    overflow = tasks[orch.MAX_ITERATIONS_PER_GOAL]
    assert overflow.status == "pending"
    assert overflow.completion_reason == RunCompletionReason.max_iterations
    assert tasks[0].completion_reason == RunCompletionReason.goal


@pytest.mark.asyncio
async def test_doom_loop_reason_when_judge_keeps_rejecting():
    goal = make_goal()
    subtasks = [
        make_task(company_id=goal.company_id, goal_id=goal.id, status="completed")
        for _ in range(orch.MAX_SUBTASKS_PER_GOAL)
    ]
    db = db_returning(subtasks)

    verdict = SimpleNamespace(is_complete=False, reasoning="still nothing", confidence=0.1)
    judge = MagicMock()
    judge.evaluate = AsyncMock(return_value=verdict)
    with patch(
        "nexus.orchestration.goal_loop.HeuristicGoalJudge", return_value=judge
    ), patch.object(orch, "_decompose_goal", new=AsyncMock()) as decompose:
        await orch._drive_goal(db, goal)

    assert goal.status == "blocked"
    assert goal.completion_reason == RunCompletionReason.doom_loop
    decompose.assert_not_awaited()  # the point: it stopped re-decomposing


# ---------------------------------------------------------------------------
# goal-level rollups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goal_completes_with_goal_reason_when_judge_confirms():
    goal = make_goal()
    subtasks = [make_task(company_id=goal.company_id, goal_id=goal.id, status="completed")]
    db = db_returning(subtasks)

    verdict = SimpleNamespace(is_complete=True, reasoning="done", confidence=0.9)
    judge = MagicMock()
    judge.evaluate = AsyncMock(return_value=verdict)
    with patch("nexus.orchestration.goal_loop.HeuristicGoalJudge", return_value=judge), \
            patch.object(orch, "_broadcast_orchestrator_event", new=AsyncMock()):
        await orch._drive_goal(db, goal)

    assert goal.status == "completed"
    assert goal.completion_reason == RunCompletionReason.goal


@pytest.mark.asyncio
async def test_goal_inherits_needs_help_from_a_subtask():
    goal = make_goal()
    subtasks = [
        make_task(
            company_id=goal.company_id,
            goal_id=goal.id,
            status="blocked",
            completion_reason=RunCompletionReason.needs_help,
        )
    ]
    db = db_returning(subtasks)
    await orch._drive_goal(db, goal)
    assert goal.status == "blocked"
    assert goal.completion_reason == RunCompletionReason.needs_help


@pytest.mark.asyncio
async def test_goal_inherits_a_unanimous_failure_reason():
    goal = make_goal()
    subtasks = [
        make_task(
            company_id=goal.company_id,
            goal_id=goal.id,
            status="failed",
            completion_reason=RunCompletionReason.budget_exhausted,
        )
        for _ in range(3)
    ]
    db = db_returning(subtasks)
    await orch._drive_goal(db, goal)
    assert goal.status == "blocked"
    assert goal.completion_reason == RunCompletionReason.budget_exhausted


@pytest.mark.asyncio
async def test_mixed_failures_roll_up_to_error():
    goal = make_goal()
    reasons = [
        RunCompletionReason.timeout,
        RunCompletionReason.no_tool_calls,
        RunCompletionReason.error,
    ]
    subtasks = [
        make_task(company_id=goal.company_id, goal_id=goal.id, status="failed", completion_reason=r)
        for r in reasons
    ]
    db = db_returning(subtasks)
    await orch._drive_goal(db, goal)
    assert goal.completion_reason == RunCompletionReason.error


# ---------------------------------------------------------------------------
# taxonomy / API contract
# ---------------------------------------------------------------------------


def test_every_reason_is_covered_by_a_test():
    """Guard against a reason being added to the enum with no reachable path."""
    tested = {
        RunCompletionReason.goal,
        RunCompletionReason.no_tool_calls,
        RunCompletionReason.max_iterations,
        RunCompletionReason.timeout,
        RunCompletionReason.budget_exhausted,
        RunCompletionReason.doom_loop,
        RunCompletionReason.needs_help,
        RunCompletionReason.error,
    }
    assert set(RunCompletionReason) == tested


def test_goal_loop_stop_reasons_all_map_into_the_taxonomy():
    from nexus.api.routes.goals import _LOOP_STOP_REASONS

    # Every stopped_reason GoalLoop can emit has a mapping.
    emitted = {
        "judge_confirmed",
        "max_iterations",
        "budget_exceeded",
        "parse_failures",
        "execution_error",
    }
    assert emitted <= set(_LOOP_STOP_REASONS)
    assert set(_LOOP_STOP_REASONS.values()) <= set(RunCompletionReason)


def test_task_and_goal_rows_carry_the_column():
    from nexus.models.task import Goal, Task

    assert "completion_reason" in Task.model_fields
    assert "completion_reason" in Goal.model_fields


def test_frontend_taxonomy_matches_the_backend():
    """The dashboard hardcodes the list; drift would silently break filters."""
    from pathlib import Path
    import re

    src = Path(__file__).resolve().parents[1] / "dashboard" / "src" / "types" / "task.ts"
    text = src.read_text(encoding="utf-8")
    block = re.search(r"COMPLETION_REASONS\s*=\s*\[(.*?)\]", text, re.S)
    assert block, "COMPLETION_REASONS not found in dashboard/src/types/task.ts"
    listed = set(re.findall(r"'([a-z_]+)'", block.group(1)))
    assert listed == {r.value for r in RunCompletionReason}
