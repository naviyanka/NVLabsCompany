"""Tests for Phase 1.3 — heartbeat that persists.

Covers PersistentHeartbeatService against a real SQLite database:
wakeup coalescing (three rapid wakeups produce one run), orphan reclaim on
restart (a killed process's run is reclaimed and its agent moves to
needs_recovery), last-beat reads surviving a restart, and stale detection.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 — registers every table on SQLModel.metadata
from nexus.models._time import utcnow
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.heartbeat_run import HeartbeatRun
from nexus.runtime.heartbeat_persistent import (
    NEEDS_RECOVERY,
    PersistentHeartbeatService,
    process_alive,
)


@pytest.fixture
async def session_factory(tmp_path):
    """A session factory over a file-backed SQLite DB with all tables created."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'heartbeat.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def agent_id(session_factory):
    """An agent row the heartbeat runs can point at."""
    company_id = uuid.uuid4()
    agent = Agent(company_id=company_id, name="Ada", role="engineer")
    async with session_factory() as session:
        session.add(Company(id=company_id, name="NVLabs"))
        session.add(agent)
        await session.commit()
    return agent.id


class TestWakeupCoalescing:
    """1.3.3 — collapse multiple pending wakeups for one agent into one."""

    async def test_three_rapid_wakeups_produce_one_run(self, session_factory, agent_id):
        """Three wakeups with none finished in between yield a single run."""
        svc = PersistentHeartbeatService(session_factory)

        first = await svc.request_wakeup(agent_id)
        second = await svc.request_wakeup(agent_id)
        third = await svc.request_wakeup(agent_id)

        assert first.id == second.id == third.id
        async with session_factory() as session:
            rows = (await session.execute(HeartbeatRun.__table__.select())).all()
        assert len(rows) == 1

    async def test_wakeup_after_finish_starts_a_new_run(self, session_factory, agent_id):
        """Once a run finishes, the next wakeup is not coalesced onto it."""
        svc = PersistentHeartbeatService(session_factory)

        first = await svc.request_wakeup(agent_id)
        await svc.finish_run(first.id, exit_code=0)
        second = await svc.request_wakeup(agent_id)

        assert second.id != first.id

    async def test_wakeups_for_different_agents_do_not_coalesce(
        self, session_factory, agent_id
    ):
        """Coalescing is per agent, not global."""
        other = Agent(company_id=uuid.uuid4(), name="Grace", role="engineer")
        async with session_factory() as session:
            session.add(Company(id=other.company_id, name="Other"))
            session.add(other)
            await session.commit()

        svc = PersistentHeartbeatService(session_factory)
        assert (await svc.request_wakeup(agent_id)).id != (
            await svc.request_wakeup(other.id)
        ).id


class TestPersistence:
    """1.3.1 — runs live in heartbeat_runs, not a process-local dict."""

    async def test_run_survives_restart(self, session_factory, agent_id):
        """A fresh service over the same DB sees the earlier run."""
        run = await PersistentHeartbeatService(session_factory).request_wakeup(agent_id)

        restarted = PersistentHeartbeatService(session_factory)
        active = await restarted.get_active_runs(agent_id)

        assert [r.id for r in active] == [run.id]

    async def test_last_heartbeat_falls_back_to_db(self, session_factory, agent_id):
        """1.3.2 — with no cache backend, the last beat comes from the DB."""
        svc = PersistentHeartbeatService(session_factory)
        await svc.request_wakeup(agent_id)
        await svc.register_heartbeat(agent_id)

        assert await PersistentHeartbeatService(session_factory).check_health(agent_id)

    async def test_check_health_false_for_unknown_agent(self, session_factory):
        """An agent that never beat is not healthy."""
        svc = PersistentHeartbeatService(session_factory)
        assert await svc.check_health(uuid.uuid4()) is False

    async def test_finish_run_with_bad_exit_marks_dead(self, session_factory, agent_id):
        """A non-zero exit code records confirmed_dead."""
        svc = PersistentHeartbeatService(session_factory)
        run = await svc.request_wakeup(agent_id)

        finished = await svc.finish_run(run.id, exit_code=1)

        assert finished.liveness_state == "confirmed_dead"
        assert finished.finished_at is not None

    async def test_detect_stale_finds_quiet_run(self, session_factory, agent_id):
        """A run with no output past the threshold is reported stale."""
        svc = PersistentHeartbeatService(session_factory)
        run = await svc.request_wakeup(agent_id)
        async with session_factory() as session:
            stored = await session.get(HeartbeatRun, run.id)
            stored.started_at = utcnow() - timedelta(seconds=600)
            await session.commit()

        stale = await svc.detect_stale(threshold_seconds=60)

        assert [r.id for r in stale] == [run.id]

    async def test_detect_stale_skips_recent_run(self, session_factory, agent_id):
        """A run that just beat is not stale."""
        svc = PersistentHeartbeatService(session_factory)
        await svc.request_wakeup(agent_id)
        assert await svc.detect_stale(threshold_seconds=60) == []


class TestOrphanReclaim:
    """1.3.4 — active runs with a dead PID move to needs_recovery."""

    async def test_dead_pid_run_is_reclaimed(self, session_factory, agent_id):
        """A killed process's run is reclaimed on restart."""
        svc = PersistentHeartbeatService(session_factory)
        run = await svc.request_wakeup(agent_id, process_pid=_dead_pid())

        reclaimed = await PersistentHeartbeatService(session_factory).reclaim_orphans()

        assert reclaimed == [run.id]
        async with session_factory() as session:
            stored = await session.get(HeartbeatRun, run.id)
            agent = await session.get(Agent, agent_id)
        assert stored.liveness_state == "confirmed_dead"
        assert stored.finished_at is not None
        assert agent.status == NEEDS_RECOVERY

    async def test_live_pid_run_is_left_alone(self, session_factory, agent_id):
        """A run whose process is still running is not reclaimed."""
        svc = PersistentHeartbeatService(session_factory)
        run = await svc.request_wakeup(agent_id, process_pid=os_getpid())

        assert await svc.reclaim_orphans() == []
        async with session_factory() as session:
            assert (await session.get(HeartbeatRun, run.id)).finished_at is None

    async def test_run_without_pid_is_left_alone(self, session_factory, agent_id):
        """A run with no PID cannot be proven dead, so it survives reclaim."""
        svc = PersistentHeartbeatService(session_factory)
        await svc.request_wakeup(agent_id)
        assert await svc.reclaim_orphans() == []

    async def test_finished_run_is_not_reclaimed(self, session_factory, agent_id):
        """Reclaim only looks at unfinished runs."""
        svc = PersistentHeartbeatService(session_factory)
        run = await svc.request_wakeup(agent_id, process_pid=_dead_pid())
        await svc.finish_run(run.id, exit_code=0)

        assert await svc.reclaim_orphans() == []


class TestProcessAlive:
    """process_alive treats an unknown PID as alive, a missing one as dead."""

    def test_none_pid_counts_as_alive(self) -> None:
        assert process_alive(None) is True

    def test_own_pid_is_alive(self) -> None:
        assert process_alive(os_getpid()) is True

    def test_missing_pid_is_dead(self) -> None:
        assert process_alive(_dead_pid()) is False


def os_getpid() -> int:
    """This process's PID."""
    import os

    return os.getpid()


def _dead_pid() -> int:
    """A PID no live process holds.

    Spawns a trivial child, waits for it, and reuses its PID: the only
    portable way to name a PID that is definitely gone.
    """
    import subprocess
    import sys

    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid
