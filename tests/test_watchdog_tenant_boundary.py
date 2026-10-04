"""The watchdog crosses tenants only to list company ids.

Reading a company's agents and runs, and filing its escalations, happen inside that
company's tenant session. These tests pin that with two companies, a failing tenant, a
bounded rotating discovery, and a process restart (which loses the in-memory state).
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 - registers every table
from nexus import database
from nexus.governance.decision_queue_model import DecisionQueueItemRecord
from nexus.governance.decision_queue_persistent import PersistentDecisionQueueManager
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import Decision
from nexus.models.heartbeat_run import HeartbeatRun
from nexus.runtime import watchdog_service
from nexus.runtime.heartbeat_persistent import NEEDS_RECOVERY, PersistentHeartbeatService
from nexus.runtime.watchdog import Watchdog
from nexus.system_runtime import ops


@pytest.fixture
async def world(tmp_path, monkeypatch):
    """Two companies, each with a stranded agent and a run that stalled with secret output."""
    watchdog_service._reset_for_tests()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wd.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", factory)

    log: list[str] = []

    class SpySession(AsyncSession):
        """Records what the discovery connection is asked to do."""

        async def execute(self, statement, *args, **kwargs):
            log.append(str(statement))
            return await super().execute(statement, *args, **kwargs)

        async def commit(self):
            log.append("COMMIT")
            await super().commit()

    discovery = async_sessionmaker(engine, class_=SpySession, expire_on_commit=False)

    opened: list[uuid.UUID] = []
    real_tenant_session = database.tenant_session

    @asynccontextmanager
    async def recording(company_id):
        opened.append(company_id)
        async with real_tenant_session(company_id) as session:
            yield session

    monkeypatch.setattr(database, "tenant_session", recording)

    world = _World(engine, factory, discovery, log, opened)
    yield world

    watchdog_service._reset_for_tests()
    await engine.dispose()


class _World:
    def __init__(self, engine, factory, discovery, log, opened):
        self.engine, self.factory, self.discovery = engine, factory, discovery
        self.log, self.opened = log, opened
        self.companies: dict[str, dict] = {}

    async def add_company(self, name: str, silent_hours: int = 5, pid: int | None = None) -> dict:
        secret = f"SECRET-{name}"
        async with self.factory() as session:
            company = Company(name=name)
            session.add(company)
            await session.flush()
            stranded = Agent(
                company_id=company.id, name="s", role="r", model="m", status=NEEDS_RECOVERY
            )
            working = Agent(company_id=company.id, name="w", role="r", model="m")
            session.add_all([stranded, working])
            await session.flush()
            run = HeartbeatRun(
                agent_id=working.id,
                process_pid=pid,
                started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=6),
                last_output_at=datetime.now(UTC).replace(tzinfo=None)
                - timedelta(hours=silent_hours),
                stdout_excerpt=secret,
                stderr_excerpt=secret,
                context_snapshot={"prompt": secret},
            )
            session.add(run)
            await session.commit()
        info = {
            "id": company.id,
            "secret": secret,
            "agents": {stranded.id, working.id},
            "stranded": stranded.id,
            "working": working.id,
            "run": run.id,
        }
        self.companies[name] = info
        return info

    async def run(self, run_id) -> HeartbeatRun:
        async with self.factory() as session:
            return await session.get(HeartbeatRun, run_id)

    async def agent(self, agent_id) -> Agent:
        async with self.factory() as session:
            return await session.get(Agent, agent_id)

    async def decisions(self, company_id) -> list[Decision]:
        async with self.factory() as session:
            rows = await session.execute(select(Decision).where(Decision.company_id == company_id))
            return list(rows.scalars())

    async def items(self, company_id) -> list[DecisionQueueItemRecord]:
        async with self.factory() as session:
            rows = await session.execute(
                select(DecisionQueueItemRecord).where(
                    DecisionQueueItemRecord.company_id == company_id
                )
            )
            return list(rows.scalars())

    async def patrol(self, times: int = 2):
        """The stall check needs a baseline patrol, so two passes reach an escalation."""
        result = None
        for _ in range(times):
            result = ops.OpResult()
            ids = await watchdog_service.discover_companies(self.discovery, 20)
            await ops._per_company(result, ids, watchdog_service.patrol_company)
        return result


async def test_the_only_cross_tenant_read_is_a_list_of_company_ids(world):
    await world.add_company("A")
    await world.add_company("B")

    await world.patrol()

    assert world.log, "discovery ran"
    assert all(s.startswith("SELECT DISTINCT agents.company_id") for s in world.log), world.log
    assert "COMMIT" not in world.log, "nothing is written through the privileged connection"


async def test_every_company_is_read_and_filed_inside_its_own_tenant_session(world):
    a, b = await world.add_company("A"), await world.add_company("B")

    result = await world.patrol()

    assert (result.processed, result.failed) == (2, 0)
    assert set(world.opened) == {a["id"], b["id"]}
    for company in (a, b):
        decisions = await world.decisions(company["id"])
        assert len(decisions) == 2  # the stranded agent and the stalled run
        assert {d.company_id for d in decisions} == {company["id"]}


async def test_agents_and_run_content_are_never_mixed_across_companies(world, monkeypatch):
    a, b = await world.add_company("A"), await world.add_company("B")
    seen: list[tuple[set, list]] = []
    real = Watchdog.patrol

    def spy(self, agents, runs=None):
        seen.append(({x.agent_id for x in agents}, [r.stdout_excerpt for r in runs or []]))
        return real(self, agents, runs)

    monkeypatch.setattr(Watchdog, "patrol", spy)
    await world.patrol(times=1)

    assert len(seen) == 2
    by_agents = {frozenset(agents): excerpts for agents, excerpts in seen}
    assert by_agents[frozenset(a["agents"])] == [a["secret"]]
    assert by_agents[frozenset(b["agents"])] == [b["secret"]]


async def test_no_run_content_is_retained_or_logged(world, caplog):
    await world.add_company("A")
    await world.add_company("B")
    caplog.set_level(logging.DEBUG)

    await world.patrol()

    retained = repr(watchdog_service._watchdog._stall_states)
    assert "SECRET" not in retained, "the watchdog keeps fingerprints, not output"
    assert "SECRET" not in caplog.text
    for company in world.companies.values():
        assert all("SECRET" not in d.body for d in await world.decisions(company["id"]))


async def test_one_company_failing_neither_stops_nor_exposes_another(world, caplog, monkeypatch):
    a, b = await world.add_company("A"), await world.add_company("B")
    real = database.tenant_session

    @asynccontextmanager
    async def a_is_down(company_id):
        if company_id == a["id"]:
            raise RuntimeError(a["secret"])
        async with real(company_id) as session:
            yield session

    monkeypatch.setattr(database, "tenant_session", a_is_down)
    caplog.set_level(logging.DEBUG)

    result = await world.patrol()

    assert (result.processed, result.failed) == (1, 1)
    assert await world.decisions(a["id"]) == []
    assert len(await world.decisions(b["id"])) == 2
    assert a["secret"] not in caplog.text and "RuntimeError" in caplog.text


async def test_each_company_escalates_to_its_own_queue(world):
    """Queues are found by name, so a shared name would file B's items under A."""
    a, b = await world.add_company("A"), await world.add_company("B")

    await world.patrol()

    manager = PersistentDecisionQueueManager(world.factory)
    for company in (a, b):
        pending = await manager.get_pending(watchdog_service.escalation_queue(company["id"]))
        assert {i.source_id for i in pending} == {company["stranded"], company["run"]}
        assert {i.company_id for i in pending} == {company["id"]}
    assert len(await world.items(a["id"])) == len(await world.items(b["id"])) == 2


async def test_a_restart_does_not_refile_escalations(world):
    """The in-memory set is lost on restart; the queue lookup is what prevents duplicates."""
    a, b = await world.add_company("A"), await world.add_company("B")
    await world.patrol(times=3)  # run escalated and closed, then both agents need recovery
    before = {n: len(await world.decisions(c["id"])) for n, c in world.companies.items()}
    assert before == {"A": 3, "B": 3}

    watchdog_service._reset_for_tests()  # a new process: no dedupe set, no stall state
    await world.patrol(times=3)

    after = {n: len(await world.decisions(c["id"])) for n, c in world.companies.items()}
    assert after == before
    assert len(await world.items(a["id"])) == len(await world.items(b["id"])) == 3


async def test_discovery_is_bounded_and_visits_every_company(world):
    ids = [(await world.add_company(f"C{i}"))["id"] for i in range(5)]

    rounds = [await watchdog_service.discover_companies(world.discovery, 2) for _ in range(3)]

    assert all(len(r) <= 2 for r in rounds)
    assert {i for r in rounds for i in r} == set(ids)


async def test_a_restart_only_changes_the_visiting_order(world):
    ids = {(await world.add_company(f"C{i}"))["id"] for i in range(3)}
    await watchdog_service.discover_companies(world.discovery, 2)

    watchdog_service._reset_for_tests()

    assert set(await watchdog_service.discover_companies(world.discovery, 10)) == ids


async def test_the_operation_is_bounded_by_its_catalogue_batch_size():
    assert 1 < ops.OPERATIONS["watchdog_patrol"].batch_size <= 100


async def test_without_a_discovery_nothing_is_read_or_written():
    await watchdog_service.patrol_once()  # no factory: must not reach any database


async def test_nothing_is_filed_for_an_agent_whose_company_is_unknown(world):
    await watchdog_service._escalate_recovery(agent_id=uuid.uuid4())

    async with world.factory() as session:
        assert (await session.execute(select(func.count()).select_from(Decision))).scalar_one() == 0


# -- replacing the startup PID reclaim -----------------------------------------------------


async def test_a_run_stalled_past_the_critical_threshold_is_closed_and_its_agent_parked(world):
    a = await world.add_company("A")

    await world.patrol()

    run, agent = await world.run(a["run"]), await world.agent(a["working"])
    assert run.finished_at is not None and run.liveness_state == "confirmed_dead"
    assert agent.status == NEEDS_RECOVERY and str(run.id) in agent.error_reason


async def test_closing_a_stalled_run_is_idempotent(world):
    a = await world.add_company("A")
    await world.patrol()
    closed_at = (await world.run(a["run"])).finished_at
    decisions = len(await world.decisions(a["id"]))

    await world.patrol(times=3)

    assert (await world.run(a["run"])).finished_at == closed_at
    assert len(await world.decisions(a["id"])) == decisions + 1  # the working agent, once


async def test_a_dead_run_no_longer_swallows_wakeups_once_it_is_closed(world):
    """The failure the old reclaim prevented: an unfinished dead run coalesces every wakeup."""
    a = await world.add_company("A")
    heartbeat = PersistentHeartbeatService(world.factory)
    assert (await heartbeat.request_wakeup(a["working"])).id == a["run"]

    await world.patrol()

    assert (await heartbeat.request_wakeup(a["working"])).id != a["run"]


async def test_the_pid_is_not_the_evidence(world):
    """Another container's PIDs mean nothing here, so silence decides, whatever the PID says."""
    alive_pid = await world.add_company("A", silent_hours=5, pid=os.getpid())
    dead_pid_but_recent = await world.add_company("B", silent_hours=0, pid=2**22 + 12345)

    await world.patrol()

    assert (await world.run(alive_pid["run"])).finished_at is not None
    assert (await world.run(dead_pid_but_recent["run"])).finished_at is None
    assert (await world.agent(dead_pid_but_recent["working"])).status != NEEDS_RECOVERY


async def test_a_reclaim_never_touches_another_companys_run(world):
    a, b = await world.add_company("A"), await world.add_company("B")

    for agent in (a["working"], b["working"]):
        closed = await watchdog_service._reclaim_stalled_run(
            a["id"], b["run"], agent, session_factory=world.factory
        )
        assert closed is False

    assert (await world.run(b["run"])).finished_at is None
    assert (await world.agent(b["working"])).status != NEEDS_RECOVERY
