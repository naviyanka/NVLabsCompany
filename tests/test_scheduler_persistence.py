"""Tests for Phase 0.5 — one scheduler.

Covers:
- ``compute_next_fire`` for every trigger type the DB-backed scheduler dispatches.
- A cron trigger created through the API route fires after a "restart" (a fresh
  scheduler tick over the same database).
- ``TriggerExecutor`` writes ``trigger_executions`` rows, so execution history
  is queryable after a restart.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 — registers every table on SQLModel.metadata
from nexus.api.routes.triggers import TriggerCreate, create_trigger
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.trigger import Trigger, TriggerExecution
from nexus.runtime.scheduler import _tick, compute_next_fire
from nexus.triggers import TriggerConfig, TriggerExecutor


@pytest.fixture
async def session_factory(tmp_path):
    """A session factory over a file-backed SQLite DB with all tables created."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def company_and_agent(session_factory):
    """A persisted company and agent for triggers to reference."""
    company = Company(name="Acme")
    async with session_factory() as db:
        db.add(company)
        await db.flush()
        agent = Agent(company_id=company.id, name="Scout", role="analyst")
        db.add(agent)
        await db.commit()
    return company.id, agent.id


class TestComputeNextFire:
    """The single scheduler's next-fire computation."""

    NOW = datetime(2026, 1, 1, 10, 0)

    def test_cron_expression_every_n_minutes(self):
        """A */N cron expression advances by N minutes."""
        assert compute_next_fire(
            "cron", {"cron_expression": "*/5 * * * *"}, self.NOW
        ) == self.NOW + timedelta(minutes=5)

    def test_cron_discrete_fields(self):
        """Discrete minute/hour fields find the next matching wall-clock time."""
        assert compute_next_fire("cron", {"minute": "30", "hour": "*"}, self.NOW) == (
            datetime(2026, 1, 1, 10, 30)
        )

    def test_cron_no_config_falls_back(self):
        """A cron trigger with no schedule fields still gets a fire time."""
        assert compute_next_fire("cron", {}, self.NOW) is not None

    def test_interval_sums_units(self):
        """Interval config sums seconds, minutes, and hours."""
        assert compute_next_fire(
            "interval", {"hours": 1, "minutes": 2, "seconds": 3}, self.NOW
        ) == self.NOW + timedelta(hours=1, minutes=2, seconds=3)

    def test_interval_missing_config_is_at_least_one_second(self):
        """An interval trigger never returns a fire time in the past."""
        assert compute_next_fire("interval", {}, self.NOW) > self.NOW

    def test_once_in_the_future_uses_scheduled_time(self):
        """A future one-shot returns its scheduled datetime."""
        assert compute_next_fire(
            "once", {"fire_at": "2026-06-01T08:00:00"}, self.NOW
        ) == datetime(2026, 6, 1, 8, 0)

    def test_on_schedule_accepts_scheduled_at(self):
        """on_schedule reads scheduled_at as well as fire_at."""
        assert compute_next_fire(
            "on_schedule", {"scheduled_at": "2026-06-01T08:00:00"}, self.NOW
        ) == datetime(2026, 6, 1, 8, 0)

    def test_aware_scheduled_time_becomes_naive_utc(self):
        """A tz-aware schedule is normalised to naive UTC for the table."""
        result = compute_next_fire(
            "once", {"fire_at": "2026-06-01T08:00:00+02:00"}, self.NOW
        )
        assert result == datetime(2026, 6, 1, 6, 0)
        assert result.tzinfo is None

    def test_once_in_the_past_does_not_refire(self):
        """A one-shot whose time has passed returns None."""
        assert compute_next_fire("once", {"fire_at": "2020-01-01T00:00:00"}, self.NOW) is None

    def test_unparseable_schedule_does_not_refire(self):
        """A malformed datetime yields None rather than raising."""
        assert compute_next_fire("once", {"fire_at": "not-a-date"}, self.NOW) is None

    def test_webhook_does_not_auto_repeat(self):
        """Webhook triggers have no computed next fire time."""
        assert compute_next_fire("webhook", {}, self.NOW) is None

    def test_none_config_is_tolerated(self):
        """A trigger row with a NULL config does not raise."""
        assert compute_next_fire("interval", None, self.NOW) > self.NOW


class TestTriggerConfigDto:
    """TriggerConfig survives as a DTO with no scheduling behaviour."""

    def test_defaults(self):
        """The DTO defaults match the table's defaults."""
        dto = TriggerConfig()
        assert dto.trigger_type == "interval"
        assert dto.is_active is True
        assert dto.config == {}

    def test_from_model_copies_fields(self):
        """from_model carries every scheduling field across."""
        trigger = Trigger(
            company_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            trigger_type="cron",
            name="nightly",
            config={"cron_expression": "0 0 * * *"},
            next_fire_at=datetime(2026, 1, 2, 0, 0),
        )
        dto = TriggerConfig.from_model(trigger)

        assert dto.id == trigger.id
        assert dto.trigger_type == "cron"
        assert dto.name == "nightly"
        assert dto.config == {"cron_expression": "0 0 * * *"}
        assert dto.next_fire_at == datetime(2026, 1, 2, 0, 0)

    def test_no_registry_module_remains(self):
        """The second, in-memory scheduler is gone."""
        with pytest.raises(ModuleNotFoundError):
            __import__("nexus.triggers.scheduler")


class TestCronTriggerSurvivesRestart:
    """Accept criterion: a cron trigger created via API fires after a restart."""

    async def test_created_trigger_gets_a_next_fire_time(
        self, session_factory, company_and_agent
    ):
        """The create route seeds next_fire_at so the row alone is schedulable."""
        company_id, agent_id = company_and_agent

        async with session_factory() as db:
            trigger = await create_trigger(
                company_id,
                TriggerCreate(
                    agent_id=agent_id,
                    trigger_type="cron",
                    name="every-5",
                    config={"cron_expression": "*/5 * * * *"},
                ),
                db,
            )
            await db.commit()

        assert trigger.next_fire_at is not None

    async def test_caller_supplied_fire_time_is_kept(
        self, session_factory, company_and_agent
    ):
        """An explicit next_fire_at is not overwritten by the computation."""
        company_id, agent_id = company_and_agent
        pinned = datetime(2026, 3, 1, 12, 0)

        async with session_factory() as db:
            trigger = await create_trigger(
                company_id,
                TriggerCreate(
                    agent_id=agent_id,
                    trigger_type="cron",
                    name="pinned",
                    config={"cron_expression": "*/5 * * * *"},
                    next_fire_at=pinned,
                ),
                db,
            )
            await db.commit()

        assert trigger.next_fire_at == pinned

    async def test_due_trigger_fires_on_a_fresh_scheduler_tick(
        self, session_factory, company_and_agent
    ):
        """A cron trigger persisted before a restart fires on the next tick.

        The tick runs against the same database with no in-process registry,
        which is what a restart looks like to the scheduler.
        """
        company_id, agent_id = company_and_agent

        async with session_factory() as db:
            trigger = await create_trigger(
                company_id,
                TriggerCreate(
                    agent_id=agent_id,
                    trigger_type="cron",
                    name="every-5",
                    config={"cron_expression": "*/5 * * * *", "prompt": "check inbox"},
                ),
                db,
            )
            # Backdate so the trigger is due when the scheduler next ticks.
            trigger.next_fire_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            ) - timedelta(minutes=1)
            db.add(trigger)
            await db.commit()
            trigger_id = trigger.id
            first_fire_at = trigger.next_fire_at

        with (
            patch(
                "nexus.runtime.redis_utils.try_acquire_leader",
                AsyncMock(return_value=True),
            ),
            patch(
                "nexus.api.routes.chat._call_llm",
                AsyncMock(return_value=("done", "gpt-test", 12)),
            ),
            patch("nexus.api.routes.chat._build_system_prompt", lambda agent: "sys"),
        ):
            await _tick(session_factory)

        async with session_factory() as db:
            fired = await db.get(Trigger, trigger_id)
            executions = list(
                (
                    await db.execute(
                        select(TriggerExecution).where(
                            TriggerExecution.trigger_id == trigger_id
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert fired.last_fired_at is not None
        assert fired.is_active is True
        assert fired.next_fire_at > first_fire_at
        assert len(executions) == 1
        assert executions[0].status == "success"

    async def test_one_shot_trigger_deactivates_after_firing(
        self, session_factory, company_and_agent
    ):
        """An on_schedule trigger fires once, then goes inactive."""
        company_id, agent_id = company_and_agent
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        async with session_factory() as db:
            trigger = Trigger(
                company_id=company_id,
                agent_id=agent_id,
                trigger_type="on_schedule",
                name="one-shot",
                config={"scheduled_at": (now - timedelta(minutes=1)).isoformat()},
                next_fire_at=now - timedelta(minutes=1),
            )
            db.add(trigger)
            await db.commit()
            trigger_id = trigger.id

        with (
            patch(
                "nexus.runtime.redis_utils.try_acquire_leader",
                AsyncMock(return_value=True),
            ),
            patch(
                "nexus.api.routes.chat._call_llm",
                AsyncMock(return_value=("done", "gpt-test", 3)),
            ),
            patch("nexus.api.routes.chat._build_system_prompt", lambda agent: "sys"),
        ):
            await _tick(session_factory)

        async with session_factory() as db:
            fired = await db.get(Trigger, trigger_id)

        assert fired.is_active is False
        assert fired.next_fire_at is None

    async def test_non_leader_tick_does_not_fire(
        self, session_factory, company_and_agent
    ):
        """Only the lease leader dispatches, so a trigger cannot fire twice."""
        company_id, agent_id = company_and_agent
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        async with session_factory() as db:
            trigger = Trigger(
                company_id=company_id,
                agent_id=agent_id,
                trigger_type="interval",
                name="follower",
                config={"minutes": 5},
                next_fire_at=now - timedelta(minutes=1),
            )
            db.add(trigger)
            await db.commit()
            trigger_id = trigger.id

        with patch(
            "nexus.runtime.redis_utils.try_acquire_leader",
            AsyncMock(return_value=False),
        ):
            await _tick(session_factory)

        async with session_factory() as db:
            trigger = await db.get(Trigger, trigger_id)

        assert trigger.last_fired_at is None


class TestExecutorWritesRows:
    """Accept criterion: execution history is queryable."""

    async def test_successful_execution_is_persisted(self, session_factory):
        """A completed execution leaves a row behind."""
        executor = TriggerExecutor(session_factory)
        executor.register_action("ping", AsyncMock(return_value={"ok": True}))
        trigger_id, company_id = uuid.uuid4(), uuid.uuid4()

        record = await executor.fire_trigger(
            trigger_id=trigger_id,
            agent_id=uuid.uuid4(),
            action_type="ping",
            action_config={},
            company_id=company_id,
        )

        assert record.status == "completed"

        async with session_factory() as db:
            row = await db.get(TriggerExecution, record.id)

        assert row is not None
        assert row.status == "completed"
        assert row.result == {"ok": True}
        assert row.completed_at is not None

    async def test_failed_execution_records_the_error(self, session_factory):
        """A handler exception is recorded on the row, not swallowed."""
        executor = TriggerExecutor(session_factory)
        executor.register_action("boom", AsyncMock(side_effect=RuntimeError("nope")))

        record = await executor.fire_trigger(
            trigger_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            action_type="boom",
            action_config={},
            company_id=uuid.uuid4(),
        )

        async with session_factory() as db:
            row = await db.get(TriggerExecution, record.id)

        assert row.status == "failed"
        assert row.error == "nope"

    async def test_missing_handler_is_persisted_as_failed(self, session_factory):
        """An unregistered action type still leaves an auditable row."""
        executor = TriggerExecutor(session_factory)

        record = await executor.fire_trigger(
            trigger_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            action_type="unknown",
            action_config={},
            company_id=uuid.uuid4(),
        )

        async with session_factory() as db:
            row = await db.get(TriggerExecution, record.id)

        assert row.status == "failed"
        assert "unknown" in row.error

    async def test_history_survives_restart(self, session_factory):
        """A fresh executor over the same DB reads the earlier executions."""
        company_id, trigger_id = uuid.uuid4(), uuid.uuid4()
        executor = TriggerExecutor(session_factory)
        executor.register_action("ping", AsyncMock(return_value={"ok": True}))
        await executor.fire_trigger(
            trigger_id=trigger_id,
            agent_id=uuid.uuid4(),
            action_type="ping",
            action_config={},
            company_id=company_id,
        )

        restarted = TriggerExecutor(session_factory)
        history = await restarted.get_executions(trigger_id=trigger_id)

        assert len(history) == 1
        assert history[0].trigger_id == trigger_id
        assert history[0].status == "completed"

    async def test_get_executions_filters(self, session_factory):
        """Filters narrow by trigger, company, and status."""
        executor = TriggerExecutor(session_factory)
        executor.register_action("ping", AsyncMock(return_value={"ok": True}))
        executor.register_action("boom", AsyncMock(side_effect=RuntimeError("nope")))
        company_id, other_company = uuid.uuid4(), uuid.uuid4()
        trigger_id = uuid.uuid4()

        await executor.fire_trigger(
            trigger_id=trigger_id,
            agent_id=uuid.uuid4(),
            action_type="ping",
            action_config={},
            company_id=company_id,
        )
        await executor.fire_trigger(
            trigger_id=trigger_id,
            agent_id=uuid.uuid4(),
            action_type="boom",
            action_config={},
            company_id=company_id,
        )
        await executor.fire_trigger(
            trigger_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            action_type="ping",
            action_config={},
            company_id=other_company,
        )

        assert len(await executor.get_executions(company_id=company_id)) == 2
        assert len(await executor.get_executions(trigger_id=trigger_id)) == 2
        assert len(await executor.get_executions(status="failed")) == 1
        assert len(await executor.get_executions(limit=1)) == 1
