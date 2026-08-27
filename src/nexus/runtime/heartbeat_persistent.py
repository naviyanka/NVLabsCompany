"""Persistent heartbeat service — DB-backed liveness with a Redis last-beat cache.

Phase 1.3. Replaces the in-memory ``HeartbeatMonitor``/``HeartbeatService``
dicts with rows in ``heartbeat_runs`` (``models/heartbeat_run.py``), a
state-backend cache for the hot last-beat read, wakeup coalescing so a burst
of wakeups produces one run, and orphan reclaim on startup so a run whose
process died is not left ``active`` forever.
"""

import asyncio
import logging
import os
import sys
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.models._time import utcnow
from nexus.models.agent import Agent
from nexus.models.heartbeat_run import HeartbeatRun, LivenessState

logger = logging.getLogger(__name__)

#: Agent status set on a run whose process no longer exists.
NEEDS_RECOVERY = "needs_recovery"


def process_alive(pid: int | None) -> bool:
    """Return whether a PID belongs to a live process.

    ``None`` counts as alive: a run with no recorded PID (in-process work)
    cannot be proven dead by a PID check, and reclaiming it would kill
    healthy runs. Anything other than a definite "no such process" also
    counts as alive, so an unreadable PID is never reclaimed by mistake.
    """
    if pid is None or pid <= 0:
        return True

    if sys.platform == "win32":
        # os.kill on Windows calls TerminateProcess for any signal, so a
        # signal-0 liveness probe would kill the process it is checking.
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_INVALID_PARAMETER = 87
        STILL_ACTIVE = 259

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return kernel32.GetLastError() != ERROR_INVALID_PARAMETER
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists but not ours, or unreadable
    return True


class PersistentHeartbeatService:
    """Database-backed heartbeat runs with a state-backend last-beat cache.

    Usage::

        svc = PersistentHeartbeatService(async_session_factory, state_backend)
        await svc.reclaim_orphans()                 # on startup
        run = await svc.request_wakeup(agent_id)    # coalesced
        await svc.register_heartbeat(agent_id)
        await svc.finish_run(run.id, exit_code=0)
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        state_backend: object | None = None,
        default_threshold_seconds: int = 60,
    ) -> None:
        """Initialize with a session factory and an optional state backend.

        Args:
            session_factory: SQLAlchemy async session factory.
            state_backend: Optional :class:`StateBackend` (Redis or file) used
                to cache last-beat timestamps. ``None`` means DB-only.
            default_threshold_seconds: Staleness threshold for health checks.
        """
        self._session_factory = session_factory
        self._backend = state_backend
        self._default_threshold = default_threshold_seconds
        self._wakeup_lock = asyncio.Lock()

    # -- last beat -------------------------------------------------------

    async def register_heartbeat(self, agent_id: uuid.UUID) -> None:
        """Record a beat for an agent in the cache and on its active run."""
        now = utcnow()
        if self._backend is not None:
            try:
                await self._backend.set(f"heartbeat:{agent_id}", now.isoformat())
            except Exception as exc:  # cache is best-effort, DB is the truth
                logger.warning("Heartbeat cache write failed: %s", exc)

        async with self._session_factory() as session:
            for run in await self._active_runs(session, agent_id):
                run.last_output_at = now
            await session.commit()

    async def get_last_heartbeat(self, agent_id: uuid.UUID):
        """Return the last beat for an agent, cache first then DB."""
        from datetime import datetime

        if self._backend is not None:
            try:
                raw = await self._backend.get(f"heartbeat:{agent_id}")
                if raw:
                    return datetime.fromisoformat(raw)
            except Exception as exc:
                logger.warning("Heartbeat cache read failed: %s", exc)

        async with self._session_factory() as session:
            stmt = (
                select(HeartbeatRun)
                .where(HeartbeatRun.agent_id == agent_id)
                .order_by(HeartbeatRun.started_at.desc())
                .limit(1)
            )
            run = (await session.execute(stmt)).scalar_one_or_none()
        if run is None:
            return None
        return run.last_output_at or run.started_at

    async def check_health(
        self, agent_id: uuid.UUID, threshold_seconds: int | None = None
    ) -> bool:
        """Return whether an agent beat within the threshold window."""
        last = await self.get_last_heartbeat(agent_id)
        if last is None:
            return False
        threshold = threshold_seconds or self._default_threshold
        return (utcnow() - last).total_seconds() <= threshold

    # -- runs ------------------------------------------------------------

    async def request_wakeup(
        self,
        agent_id: uuid.UUID,
        process_pid: int | None = None,
        invocation_source: str = "heartbeat",
        session_id_before: str | None = None,
        context_snapshot: dict | None = None,
    ) -> HeartbeatRun:
        """Start a run for an agent, coalescing onto one already in flight.

        Three rapid wakeups produce one run: the second and third find the
        first still unfinished and return it instead of starting another.
        """
        async with self._wakeup_lock:
            async with self._session_factory() as session:
                existing = await self._active_runs(session, agent_id)
                if existing:
                    logger.debug("Coalesced wakeup for agent %s", agent_id)
                    return existing[0]

                run = HeartbeatRun(
                    agent_id=agent_id,
                    process_pid=process_pid,
                    invocation_source=invocation_source,
                    session_id_before=session_id_before,
                    context_snapshot=context_snapshot,
                )
                session.add(run)
                await session.commit()
                await session.refresh(run)
                return run

    async def finish_run(
        self,
        run_id: uuid.UUID,
        exit_code: int | None = None,
        signal: str | None = None,
        session_id_after: str | None = None,
    ) -> HeartbeatRun | None:
        """Mark a run finished; a bad exit or signal means confirmed dead."""
        async with self._session_factory() as session:
            run = await session.get(HeartbeatRun, run_id)
            if run is None:
                return None
            run.exit_code = exit_code
            run.signal = signal
            run.session_id_after = session_id_after
            run.finished_at = utcnow()
            if (exit_code is not None and exit_code != 0) or signal is not None:
                run.liveness_state = LivenessState.confirmed_dead.value
            await session.commit()
            await session.refresh(run)
            return run

    async def get_active_runs(self, agent_id: uuid.UUID) -> list[HeartbeatRun]:
        """Return unfinished runs for an agent."""
        async with self._session_factory() as session:
            return await self._active_runs(session, agent_id)

    async def detect_stale(self, threshold_seconds: int = 60) -> list[HeartbeatRun]:
        """Return unfinished runs with no activity inside the threshold."""
        cutoff = utcnow() - timedelta(seconds=threshold_seconds)
        async with self._session_factory() as session:
            stmt = select(HeartbeatRun).where(HeartbeatRun.finished_at.is_(None))
            runs = list((await session.execute(stmt)).scalars().all())
        return [
            run
            for run in runs
            if (run.last_output_at or run.started_at) < cutoff
        ]

    # -- orphan reclaim --------------------------------------------------

    async def reclaim_orphans(self) -> list[uuid.UUID]:
        """Reclaim active runs whose process is gone. Call on startup.

        Marks each such run ``confirmed_dead`` and moves its agent to
        ``needs_recovery`` so a human or the watchdog decides what happens
        next, rather than leaving a dead run counted as active forever.

        Returns:
            The ids of the reclaimed runs.
        """
        reclaimed: list[uuid.UUID] = []
        async with self._session_factory() as session:
            stmt = select(HeartbeatRun).where(HeartbeatRun.finished_at.is_(None))
            for run in (await session.execute(stmt)).scalars().all():
                if process_alive(run.process_pid):
                    continue
                run.liveness_state = LivenessState.confirmed_dead.value
                run.finished_at = utcnow()
                agent = await session.get(Agent, run.agent_id)
                if agent is not None:
                    agent.status = NEEDS_RECOVERY
                    agent.error_reason = (
                        f"process {run.process_pid} died during heartbeat run {run.id}"
                    )
                reclaimed.append(run.id)
            await session.commit()

        if reclaimed:
            logger.warning("Reclaimed %d orphaned heartbeat run(s)", len(reclaimed))
        return reclaimed

    # -- internals -------------------------------------------------------

    @staticmethod
    async def _active_runs(
        session: AsyncSession, agent_id: uuid.UUID
    ) -> list[HeartbeatRun]:
        stmt = (
            select(HeartbeatRun)
            .where(
                HeartbeatRun.agent_id == agent_id,
                HeartbeatRun.finished_at.is_(None),
            )
            .order_by(HeartbeatRun.started_at)
        )
        return list((await session.execute(stmt)).scalars().all())
