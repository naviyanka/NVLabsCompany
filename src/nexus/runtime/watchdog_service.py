"""Runs the watchdog against the database and escalates what it finds.

`watchdog.py` is deliberately free of database access: it takes agent state as
`AgentInfo` dataclasses and returns a `PatrolReport`. That keeps it testable, but
it also means something has to feed it real rows and act on its verdicts. This
module is that something.

Tenant boundary. The system runtime's ``watchdog_patrol`` operation uses its
privileged discovery session for one thing only: listing company ids. Everything
that touches a company's rows, whether reading its agents and unfinished runs
(which carry output excerpts) or filing an escalation, runs inside that company's
``tenant_session`` on the application role. Run content is therefore loaded for one
company at a time and dropped before the next, and a failure in one company is
logged by class and never reaches another.

Escalations become decision-queue items so a human sees them. They are deduped per
source (a run, or an agent) by looking for an existing queue item in the company's
own tenant, so a stalled run files one decision across patrols and across restarts.
``_escalated`` is only a process-local fast path in front of that check.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.models.agent import Agent
from nexus.models.heartbeat_run import HeartbeatRun
from nexus.runtime.heartbeat_persistent import NEEDS_RECOVERY
from nexus.runtime.watchdog import AgentInfo, RecoveryAction, Watchdog, WatchdogConfig

logger = logging.getLogger(__name__)

ESCALATION_QUEUE = "watchdog-escalations"

DEFAULT_COMPANY_LIMIT = 20

_watchdog: Watchdog | None = None
# Fast path in front of the database dedupe. Process-local and lost on restart; the queue
# lookup in `_file_decision` is what actually prevents a refile.
_escalated: set[uuid.UUID] = set()
# Last company id visited, so a bounded discovery resumes where the previous patrol stopped
# instead of always starting with the same companies. Also process-local: a restart starts
# from the beginning, which only changes the visiting order.
_cursor: uuid.UUID | None = None


def escalation_queue(company_id: uuid.UUID) -> str:
    """The company's own escalation queue.

    Queues are looked up by name alone, so a shared name would put every company after the
    first into the first company's queue.
    """
    return f"{ESCALATION_QUEUE}:{company_id}"


def _agent_infos(rows: list[Agent]) -> list[AgentInfo]:
    """Convert agent rows into the dataclass the watchdog expects."""
    return [
        AgentInfo(
            agent_id=row.id,
            status=row.status,
            last_heartbeat_at=row.last_heartbeat_at,
            budget_monthly_cents=row.budget_monthly_cents or 0,
            spent_monthly_cents=row.spent_monthly_cents or 0,
        )
        for row in rows
    ]


async def _load_active_runs(
    session: AsyncSession, agent_ids: list[uuid.UUID]
) -> list[HeartbeatRun]:
    """Read the given agents' unfinished runs, which is what stall detection looks at."""
    if not agent_ids:
        return []
    stmt = select(HeartbeatRun).where(
        HeartbeatRun.finished_at.is_(None), HeartbeatRun.agent_id.in_(agent_ids)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _file_decision(
    agent_id: uuid.UUID,
    source_id: uuid.UUID,
    title: str,
    body: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    company_id: uuid.UUID | None = None,
) -> None:
    """Put one open decision on the company's escalation queue for a human to answer.

    Deduped on ``source_id`` against the company's queue items, so a condition that persists
    across patrols or restarts files one decision rather than one per tick.

    Args:
        agent_id: The agent the escalation is about.
        source_id: Dedupe key and queue-item source (a run id, or an agent id
            when the escalation is about the agent rather than a single run).
        title: Short summary shown in the queue.
        body: What the operator needs to know to decide.
        session_factory: Optional session factory override for tests.
        company_id: The agent's company, already known to the patrol. Production filing runs
            inside that company's ``tenant_session``. Without it, only a ``session_factory``
            can look the company up; otherwise nothing is filed, because the lookup would
            cross tenants.
    """
    from nexus.database import tenant_session_factory
    from nexus.governance.decision_queue_model import DecisionQueueItemRecord
    from nexus.governance.decision_queue_persistent import (
        PersistentDecisionQueueManager,
    )
    from nexus.models.governance import Decision

    if source_id in _escalated:
        return

    if company_id is None and session_factory is not None:
        async with session_factory() as session:
            company_id = (
                await session.execute(select(Agent.company_id).where(Agent.id == agent_id))
            ).scalars().first()
    if company_id is None:
        logger.warning("Cannot escalate agent %s: unknown agent or company", agent_id)
        return

    factory = session_factory or tenant_session_factory(company_id)
    queue = escalation_queue(company_id)

    async with factory() as session:
        already = (
            await session.execute(
                select(DecisionQueueItemRecord.id).where(
                    DecisionQueueItemRecord.company_id == company_id,
                    DecisionQueueItemRecord.source_kind == "system",
                    DecisionQueueItemRecord.source_id == source_id,
                )
            )
        ).scalars().first()
        if already is None:
            decision = Decision(company_id=company_id, title=title, body=body, status="open")
            session.add(decision)
            await session.commit()
            await session.refresh(decision)
            decision_id = decision.id

    if already is None:
        manager = PersistentDecisionQueueManager(factory)
        try:
            await manager.create_queue(queue, company_id)
        except Exception:  # noqa: BLE001 - the queue usually already exists
            pass
        await manager.add_item(
            queue_name=queue,
            decision_id=decision_id,
            source_kind="system",
            source_id=source_id,
            priority=1,
        )
        logger.warning("Escalated %s for human review: %s", source_id, title)

    _escalated.add(source_id)


async def _escalate(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    action: dict[str, object] | None = None,
    company_id: uuid.UUID | None = None,
) -> None:
    """File one human decision for a stalled run."""
    if action is None:
        return

    raw_run_id = action.get("run_id")
    raw_agent_id = action.get("agent_id")
    if raw_run_id is None or raw_agent_id is None:
        return

    run_id = uuid.UUID(str(raw_run_id))
    await _file_decision(
        agent_id=uuid.UUID(str(raw_agent_id)),
        company_id=company_id,
        source_id=run_id,
        title=f"Stalled agent run {run_id}",
        body=str(action.get("reason", "Run stopped producing output.")),
        session_factory=session_factory,
    )


async def _escalate_recovery(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    agent_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
) -> None:
    """File a decision for an agent left in ``needs_recovery``."""
    if agent_id is None:
        return

    await _file_decision(
        agent_id=agent_id,
        company_id=company_id,
        source_id=agent_id,
        title=f"Agent {agent_id} needs recovery",
        body=(
            "The agent's run process died and was reclaimed at startup. Decide "
            "whether to resume its work, reassign it, or leave it stopped."
        ),
        session_factory=session_factory,
    )


async def _reclaim_stalled_run(
    company_id: uuid.UUID,
    run_id: uuid.UUID,
    agent_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """Close a run the watchdog has confirmed dead and park its agent in ``needs_recovery``.

    This replaces the API's startup reclaim of runs whose process had died. That check asked
    the operating system whether a recorded PID existed, which is only meaningful from the
    process that started the run; the system runtime is a different container from the
    worker and would call every live run dead. Silence past the critical threshold with an
    unchanged stop-fingerprint is evidence any process can judge, and it is the same
    evidence the watchdog already uses to escalate.

    Without this a dead run stays unfinished forever, and ``request_wakeup`` keeps
    coalescing new wakeups onto it. Idempotent: a closed run is not loaded again, and the
    write is skipped if it was closed in the meantime or does not belong to ``company_id``.

    Returns:
        Whether a run was closed.
    """
    from nexus.database import tenant_session_factory
    from nexus.models._time import utcnow
    from nexus.models.heartbeat_run import LivenessState

    factory = session_factory or tenant_session_factory(company_id)
    async with factory() as session:
        run = await session.get(HeartbeatRun, run_id)
        agent = await session.get(Agent, agent_id)
        if (
            run is None
            or run.finished_at is not None
            or agent is None
            or run.agent_id != agent_id
            or agent.company_id != company_id
        ):
            return False
        run.liveness_state = LivenessState.confirmed_dead.value
        run.finished_at = utcnow()
        agent.status = NEEDS_RECOVERY
        agent.error_reason = f"heartbeat run {run.id} stalled with no output"
        await session.commit()
    if _watchdog is not None:
        _watchdog.forget_run(run_id)
    return True


async def discover_companies(
    discovery: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    limit: int = DEFAULT_COMPANY_LIMIT,
) -> list[uuid.UUID]:
    """Company ids that have agents: at most ``limit``, resuming after the last one visited.

    This is the only cross-tenant read the watchdog makes, and it returns ids alone.
    """
    global _cursor
    ids_stmt = select(Agent.company_id).distinct().order_by(Agent.company_id)
    async with discovery() as session:
        ahead = ids_stmt if _cursor is None else ids_stmt.where(Agent.company_id > _cursor)
        ids = list((await session.execute(ahead.limit(limit))).scalars().all())
        if _cursor is not None and len(ids) < limit:
            wrapped = ids_stmt.where(Agent.company_id <= _cursor).limit(limit - len(ids))
            ids += list((await session.execute(wrapped)).scalars().all())
    _cursor = ids[-1] if ids else None
    return ids


async def patrol_company(
    company_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Patrol one company: read its agents and runs, run the checks, file its escalations.

    Everything runs through ``tenant_session(company_id)`` unless a test supplies its own
    ``session_factory``. A read failure propagates so the caller can count the company as
    failed; an escalation failure is logged and does not stop the rest of the patrol.
    """
    from nexus.database import tenant_session_factory

    global _watchdog
    if _watchdog is None:
        _watchdog = Watchdog(config=WatchdogConfig())

    factory = session_factory or tenant_session_factory(company_id)
    async with factory() as session:
        rows = list(
            (await session.execute(select(Agent).where(Agent.company_id == company_id)))
            .scalars()
            .all()
        )
        agents = _agent_infos(rows)
        runs = await _load_active_runs(session, [row.id for row in rows])

    report = _watchdog.patrol(agents, runs)
    del runs  # run output excerpts are not kept past this company

    for action in report.actions_taken:
        if action.get("action") == RecoveryAction.ESCALATE_HUMAN.value:
            try:
                await _escalate(
                    session_factory=session_factory, action=action, company_id=company_id
                )
            except Exception as exc:  # noqa: BLE001 - one failure must not stop the patrol
                logger.warning("Could not escalate stalled run (%s)", type(exc).__name__)
            try:
                await _reclaim_stalled_run(
                    company_id,
                    uuid.UUID(str(action["run_id"])),
                    uuid.UUID(str(action["agent_id"])),
                    session_factory=session_factory,
                )
            except Exception as exc:  # noqa: BLE001 - one failure must not stop the patrol
                logger.warning("Could not close stalled run (%s)", type(exc).__name__)

    # Agents parked in needs_recovery by startup reclaim. Nothing else reads
    # that status, so without this the reclaim is invisible.
    for agent in agents:
        if agent.status != NEEDS_RECOVERY:
            continue
        try:
            await _escalate_recovery(
                session_factory=session_factory, agent_id=agent.agent_id, company_id=company_id
            )
        except Exception as exc:  # noqa: BLE001 - one failure must not stop the patrol
            logger.warning("Could not escalate an agent (%s)", type(exc).__name__)

    if report.issues_found:
        logger.info(
            "Watchdog patrol: %d agent(s) checked, %d issue(s)",
            report.agents_checked,
            report.issues_found,
        )


async def patrol_once(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    discovery: Callable[[], AbstractAsyncContextManager[AsyncSession]] | None = None,
    limit: int = DEFAULT_COMPANY_LIMIT,
) -> None:
    """One patrol over a bounded set of companies; a failing company does not stop the rest.

    The system runtime does not call this: it discovers with ``discover_companies`` and
    drives ``patrol_company`` through its own per-company loop so failures are counted.
    With neither argument there is no way to discover companies, and nothing happens.
    """
    factory = discovery or session_factory
    if factory is None:
        return
    for company_id in await discover_companies(factory, limit):
        try:
            await patrol_company(company_id, session_factory=session_factory)
        except Exception as exc:  # noqa: BLE001 - one company must not stop the rest
            logger.warning("Watchdog patrol of a company failed (%s)", type(exc).__name__)


async def stop_watchdog() -> None:
    """Release the watchdog's resources at shutdown.

    There is no loop to cancel: patrols ride the scheduler tick rather than a
    second polling loop of their own.
    """
    global _watchdog
    if _watchdog is not None:
        await _watchdog.stop()
        _watchdog = None


def _reset_for_tests() -> None:
    """Clear module state between tests."""
    global _watchdog, _cursor
    _watchdog = None
    _cursor = None
    _escalated.clear()
