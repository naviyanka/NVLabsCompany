"""Crash resumption for the orchestrator's unit of work.

`_execute_subtasks` used to take a task straight from `pending` to a terminal
status, so a process that died mid-LLM-call left the row looking untouched and
the next tick paid for the same call again. These tests cover the claim that
makes an interrupted task identifiable.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import chat
from nexus.models.agent import Agent
from nexus.models._time import utcnow
from nexus.models.company import Company
from nexus.models.task import Goal, RunCompletionReason, Task
from nexus.runtime import orchestrator


@pytest.fixture
async def company_db(tmp_path):
    """A company with one agent and a goal carrying one assigned subtask."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'orch.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    company = Company(name="Acme")
    agent = Agent(
        company_id=company.id,
        name="Worker",
        role="staff",
        model="m",
        budget_monthly_cents=10_000,
    )
    goal = Goal(company_id=company.id, title="Ship it", owner_agent_id=agent.id)
    task = Task(
        company_id=company.id,
        title="Do the work",
        goal_id=goal.id,
        assigned_agent_id=agent.id,
    )

    async with factory() as session:
        session.add_all([company, agent, goal, task])
        await session.commit()

    yield factory, company, agent, goal, task

    await engine.dispose()


async def reload(factory, task_id: uuid.UUID) -> Task:
    async with factory() as session:
        return (
            await session.execute(select(Task).where(Task.id == task_id))
        ).scalar_one()


class TestSubtaskClaim:
    """An in-flight subtask has to be distinguishable from a fresh one."""

    async def test_crash_mid_execution_leaves_the_task_claimed(
        self, company_db, monkeypatch
    ) -> None:
        factory, company, _agent, _goal, task = company_db

        async def boom(*_args, **_kwargs):
            raise KeyboardInterrupt("process killed mid-call")

        monkeypatch.setattr(chat, "_call_llm", boom)

        async with factory() as db:
            tasks = list((await db.execute(select(Task))).scalars())
            with pytest.raises(KeyboardInterrupt):
                await orchestrator._execute_subtasks(db, tasks, company.id)

        stored = await reload(factory, task.id)
        assert stored.status == "in_progress"
        assert stored.started_at is not None

    async def test_successful_execution_still_ends_terminal(
        self, company_db, monkeypatch
    ) -> None:
        factory, company, _agent, _goal, task = company_db

        async def ok(*_args, **_kwargs):
            return "work complete", "m", 10

        monkeypatch.setattr(chat, "_call_llm", ok)

        async with factory() as db:
            tasks = list((await db.execute(select(Task))).scalars())
            await orchestrator._execute_subtasks(db, tasks, company.id)
            await db.commit()

        stored = await reload(factory, task.id)
        assert stored.status == "completed"
        assert stored.completion_reason == RunCompletionReason.goal


class TestStaleClaimReaping:
    """A claim outliving its process must not pin the goal open forever."""

    async def test_stale_claim_is_failed_with_a_timeout_reason(
        self, company_db
    ) -> None:
        factory, _company, _agent, _goal, task = company_db

        async with factory() as session:
            stored = (
                await session.execute(select(Task).where(Task.id == task.id))
            ).scalar_one()
            stored.status = "in_progress"
            stored.started_at = utcnow() - timedelta(
                seconds=orchestrator.STALE_SUBTASK_SECONDS + 1
            )
            await session.commit()

        async with factory() as db:
            assert await orchestrator._reap_stale_subtasks(db) == 1
            await db.commit()

        reaped = await reload(factory, task.id)
        assert reaped.status == "failed"
        assert reaped.completion_reason == RunCompletionReason.timeout

    async def test_fresh_claim_is_left_alone(self, company_db) -> None:
        factory, _company, _agent, _goal, task = company_db

        async with factory() as session:
            stored = (
                await session.execute(select(Task).where(Task.id == task.id))
            ).scalar_one()
            stored.status = "in_progress"
            stored.started_at = utcnow()
            await session.commit()

        async with factory() as db:
            assert await orchestrator._reap_stale_subtasks(db) == 0
            await db.commit()

        assert (await reload(factory, task.id)).status == "in_progress"

    async def test_reaped_goal_can_advance_again(self, company_db) -> None:
        """The point of reaping: _drive_goal stops waiting on the dead claim."""
        factory, _company, _agent, goal, task = company_db

        async with factory() as session:
            stored = (
                await session.execute(select(Task).where(Task.id == task.id))
            ).scalar_one()
            stored.status = "in_progress"
            stored.started_at = utcnow() - timedelta(
                seconds=orchestrator.STALE_SUBTASK_SECONDS + 1
            )
            await session.commit()

        async with factory() as db:
            live_goal = (
                await db.execute(select(Goal).where(Goal.id == goal.id))
            ).scalar_one()

            # Before reaping, the claim counts as active and the goal waits.
            await orchestrator._drive_goal(db, live_goal)
            assert live_goal.status == "active"
            assert live_goal.completion_reason is None

            await orchestrator._reap_stale_subtasks(db)
            await orchestrator._drive_goal(db, live_goal)
            await db.commit()

        async with factory() as session:
            after = (
                await session.execute(select(Task).where(Task.id == task.id))
            ).scalar_one()
        assert after.status == "failed"


class TestStrandedGoalReclaim:
    """A goal handed to a workflow that died has to come back to the tick."""

    async def _park(self, factory, goal_id: uuid.UUID, age_seconds: int) -> None:
        async with factory() as session:
            goal = (
                await session.execute(select(Goal).where(Goal.id == goal_id))
            ).scalar_one()
            goal.status = "in_progress"
            goal.updated_at = utcnow() - timedelta(seconds=age_seconds)
            await session.commit()

    async def test_stranded_goal_returns_to_active(self, company_db) -> None:
        factory, _company, _agent, goal, _task = company_db
        await self._park(factory, goal.id, orchestrator.STRANDED_GOAL_SECONDS + 1)

        async with factory() as db:
            assert await orchestrator._reclaim_stranded_goals(db) == 1
            await db.commit()

        async with factory() as session:
            stored = (
                await session.execute(select(Goal).where(Goal.id == goal.id))
            ).scalar_one()
        assert stored.status == "active"

    async def test_recently_updated_goal_is_left_to_its_workflow(
        self, company_db
    ) -> None:
        factory, _company, _agent, goal, _task = company_db
        await self._park(factory, goal.id, 5)

        async with factory() as db:
            assert await orchestrator._reclaim_stranded_goals(db) == 0
            await db.commit()

        async with factory() as session:
            stored = (
                await session.execute(select(Goal).where(Goal.id == goal.id))
            ).scalar_one()
        assert stored.status == "in_progress"
