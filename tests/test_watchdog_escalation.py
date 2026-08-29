"""The watchdog service is the module that makes the watchdog reachable.

`watchdog.py` is pure logic over dataclasses and has its own tests. This module
feeds it real rows and acts on its verdicts, and it had no test coverage at all —
which is how `needs_recovery` ended up written by startup reclaim and read by
nothing. These tests cover both escalation paths end to end.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import Decision
from nexus.runtime import watchdog_service
from nexus.runtime.heartbeat_persistent import NEEDS_RECOVERY


@pytest.fixture
async def company_db(tmp_path):
    """A company with one healthy agent and one awaiting recovery."""
    watchdog_service._reset_for_tests()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'watchdog.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    company = Company(name="Acme")
    healthy = Agent(company_id=company.id, name="Healthy", role="staff", model="m")
    stranded = Agent(
        company_id=company.id,
        name="Stranded",
        role="staff",
        model="m",
        status=NEEDS_RECOVERY,
    )

    async with factory() as session:
        session.add_all([company, healthy, stranded])
        await session.commit()

    yield factory, company, healthy, stranded

    watchdog_service._reset_for_tests()
    await engine.dispose()


async def open_decisions(factory) -> list[Decision]:
    """Every decision filed, oldest first."""
    async with factory() as session:
        result = await session.execute(select(Decision).order_by(Decision.created_at))
        return list(result.scalars())


class TestNeedsRecoveryEscalation:
    """An agent parked in needs_recovery has to reach a human."""

    async def test_patrol_files_a_decision(self, company_db) -> None:
        factory, _company, _healthy, stranded = company_db

        await watchdog_service.patrol_once(factory)

        decisions = await open_decisions(factory)
        assert len(decisions) == 1
        assert str(stranded.id) in decisions[0].title
        assert decisions[0].status == "open"

    async def test_healthy_agents_are_not_escalated(self, company_db) -> None:
        factory, _company, healthy, _stranded = company_db

        await watchdog_service.patrol_once(factory)

        decisions = await open_decisions(factory)
        assert all(str(healthy.id) not in d.title for d in decisions)

    async def test_repeated_patrols_file_one_decision(self, company_db) -> None:
        """A condition that persists must not file a decision per tick."""
        factory, *_ = company_db

        await watchdog_service.patrol_once(factory)
        await watchdog_service.patrol_once(factory)
        await watchdog_service.patrol_once(factory)

        assert len(await open_decisions(factory)) == 1

    async def test_decision_lands_on_the_escalation_queue(self, company_db) -> None:
        from nexus.governance.decision_queue_persistent import (
            PersistentDecisionQueueManager,
        )

        factory, _company, _healthy, stranded = company_db

        await watchdog_service.patrol_once(factory)

        manager = PersistentDecisionQueueManager(factory)
        items = await manager.get_pending(watchdog_service.ESCALATION_QUEUE)
        assert len(items) == 1
        assert items[0].source_id == stranded.id

    async def test_recovered_agent_stops_being_escalated(self, company_db) -> None:
        """Clearing the status is what takes an agent off the queue."""
        factory, _company, _healthy, stranded = company_db

        async with factory() as session:
            agent = await session.get(Agent, stranded.id)
            agent.status = "idle"
            await session.commit()

        await watchdog_service.patrol_once(factory)

        assert await open_decisions(factory) == []


class TestFailureHandling:
    """One bad escalation must not stop the rest of the patrol."""

    async def test_unknown_agent_is_skipped(self, company_db) -> None:
        factory, *_ = company_db

        # Must not raise.
        await watchdog_service._escalate_recovery(factory, uuid.uuid4())

        assert await open_decisions(factory) == []

    async def test_patrol_survives_an_escalation_failure(
        self, company_db, monkeypatch
    ) -> None:
        factory, *_ = company_db

        async def explode(*a: object, **k: object) -> None:
            raise RuntimeError("queue is down")

        monkeypatch.setattr(watchdog_service, "_escalate_recovery", explode)

        # Must not raise.
        await watchdog_service.patrol_once(factory)
