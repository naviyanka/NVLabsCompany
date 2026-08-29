"""Runs the watchdog against the database and escalates what it finds.

`watchdog.py` is deliberately free of database access: it takes agent state as
`AgentInfo` dataclasses and returns a `PatrolReport`. That keeps it testable, but
it also means something has to feed it real rows and act on its verdicts. This
module is that something, and it is what `main.py` starts.

Escalations become decision-queue items so a human sees them, deduped per run so
a stalled run does not refile every patrol.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.models.agent import Agent
from nexus.models.heartbeat_run import HeartbeatRun
from nexus.runtime.heartbeat_persistent import NEEDS_RECOVERY
from nexus.runtime.watchdog import AgentInfo, RecoveryAction, Watchdog, WatchdogConfig

logger = logging.getLogger(__name__)

ESCALATION_QUEUE = "watchdog-escalations"

_watchdog: Watchdog | None = None
# Run ids already escalated, so a stalled run files one decision, not one per
# patrol. Process-local: a restart may refile, which is the safe direction.
_escalated: set[uuid.UUID] = set()


async def _load_agents(session: AsyncSession) -> list[AgentInfo]:
    """Read current agent state into the dataclass the watchdog expects."""
    rows = (await session.execute(select(Agent))).scalars().all()
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


async def _load_active_runs(session: AsyncSession) -> list[HeartbeatRun]:
    """Read unfinished runs, which is what stall detection looks at."""
    stmt = select(HeartbeatRun).where(HeartbeatRun.finished_at.is_(None))
    return list((await session.execute(stmt)).scalars().all())


async def _file_decision(
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: uuid.UUID,
    source_id: uuid.UUID,
    title: str,
    body: str,
) -> None:
    """Put one open decision on the escalation queue for a human to answer.

    Deduped on ``source_id``, so a condition that persists across patrols files
    one decision rather than one per tick.

    Args:
        session_factory: Session factory for the decision and queue writes.
        agent_id: The agent the escalation is about; supplies the company.
        source_id: Dedupe key and queue-item source (a run id, or an agent id
            when the escalation is about the agent rather than a single run).
        title: Short summary shown in the queue.
        body: What the operator needs to know to decide.
    """
    from nexus.governance.decision_queue_persistent import (
        PersistentDecisionQueueManager,
    )
    from nexus.models.governance import Decision

    if source_id in _escalated:
        return

    # Neither the action dict nor HeartbeatRun carries a company, so it comes
    # from the owning agent.
    async with session_factory() as session:
        agent = (
            await session.execute(select(Agent).where(Agent.id == agent_id))
        ).scalars().first()
        if agent is None:
            logger.warning("Cannot escalate: unknown agent %s", agent_id)
            return
        company_id = agent.company_id

        decision = Decision(
            company_id=company_id, title=title, body=body, status="open"
        )
        session.add(decision)
        await session.commit()
        await session.refresh(decision)
        decision_id = decision.id

    manager = PersistentDecisionQueueManager(session_factory)
    try:
        await manager.create_queue(ESCALATION_QUEUE, company_id)
    except Exception:  # noqa: BLE001 - the queue usually already exists
        pass

    await manager.add_item(
        queue_name=ESCALATION_QUEUE,
        decision_id=decision_id,
        source_kind="system",
        source_id=source_id,
        priority=1,
    )
    _escalated.add(source_id)
    logger.warning("Escalated %s for human review: %s", source_id, title)


async def _escalate(
    session_factory: async_sessionmaker[AsyncSession],
    action: dict[str, object],
) -> None:
    """File one human decision for a stalled run.

    The watchdog never reassigns or cancels on its own -- a stall it cannot
    explain goes to a person.
    """
    raw_run_id = action.get("run_id")
    raw_agent_id = action.get("agent_id")
    if raw_run_id is None or raw_agent_id is None:
        return

    run_id = uuid.UUID(str(raw_run_id))
    await _file_decision(
        session_factory,
        agent_id=uuid.UUID(str(raw_agent_id)),
        source_id=run_id,
        title=f"Stalled agent run {run_id}",
        body=str(action.get("reason", "Run stopped producing output.")),
    )


async def _escalate_recovery(
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: uuid.UUID,
) -> None:
    """File a decision for an agent left in ``needs_recovery``.

    Startup reclaim moves an agent whose process died into ``needs_recovery``,
    but nothing moved it out again: no code read that status, so a reclaimed
    agent sat there indefinitely. Surfacing it as a decision is what makes the
    reclaim visible to someone who can act on it.
    """
    await _file_decision(
        session_factory,
        agent_id=agent_id,
        source_id=agent_id,
        title=f"Agent {agent_id} needs recovery",
        body=(
            "The agent's run process died and was reclaimed at startup. Decide "
            "whether to resume its work, reassign it, or leave it stopped."
        ),
    )


async def patrol_once(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """One patrol: load state, run the checks, act on escalations."""
    global _watchdog

    if _watchdog is None:
        _watchdog = Watchdog(config=WatchdogConfig())

    async with session_factory() as session:
        agents = await _load_agents(session)
        runs = await _load_active_runs(session)

    report = _watchdog.patrol(agents, runs)

    for action in report.actions_taken:
        if action.get("action") == RecoveryAction.ESCALATE_HUMAN.value:
            try:
                await _escalate(session_factory, action)
            except Exception as exc:  # noqa: BLE001 - one failure must not stop the patrol
                logger.warning("Could not escalate stalled run: %s", exc)

    # Agents parked in needs_recovery by startup reclaim. Nothing else reads
    # that status, so without this the reclaim is invisible.
    for agent in agents:
        if agent.status != NEEDS_RECOVERY:
            continue
        try:
            await _escalate_recovery(session_factory, agent.agent_id)
        except Exception as exc:  # noqa: BLE001 - one failure must not stop the patrol
            logger.warning("Could not escalate agent %s: %s", agent.agent_id, exc)

    if report.issues_found:
        logger.info(
            "Watchdog patrol: %d agent(s) checked, %d issue(s)",
            report.agents_checked,
            report.issues_found,
        )


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
    global _watchdog
    _watchdog = None
    _escalated.clear()
