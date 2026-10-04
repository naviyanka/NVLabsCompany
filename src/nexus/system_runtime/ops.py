"""The catalogue of operations the system runtime may run.

This is an allow-list. Each operation has a stable name, an interval, a bounded batch size
and a timeout, and is a fixed function in this file: no operation takes a table, a function
or SQL from a caller, and none accepts a prompt or a tool request. An agent or a model
cannot invoke one, because nothing outside the system runtime process schedules them.

The rule every operation follows: the system role (``discovery``) is used only to find
*which* companies need work, with a bounded query. The work itself runs per company through
``tenant_session`` on the application role, so a tenant-bound code path does the writing and
one company's failure cannot reach another's rows.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

# Opens a cross-tenant read session. In production this is the system engine; tests pass an
# ordinary session factory so the same code runs against SQLite.
DiscoveryFactory = Callable[[], AbstractAsyncContextManager]

# Tenants handled between two yields to the event loop.
_CHUNK = 10


@dataclass
class OpResult:
    """What one run did. Counts only: nothing here carries company content."""

    seen: int = 0
    processed: int = 0
    failed: int = 0
    batches: int = 0
    outcome: Counter = field(default_factory=Counter)


@dataclass(frozen=True)
class Operation:
    name: str
    interval_seconds: float
    batch_size: int
    timeout_seconds: float
    run: Callable[[DiscoveryFactory, datetime], Awaitable[OpResult]]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _per_company(
    result: OpResult,
    company_ids: Iterable[uuid.UUID],
    work: Callable[[uuid.UUID], Awaitable[object]],
) -> None:
    """Run ``work`` for each company in bounded chunks, isolating failures.

    ``work`` is expected to use ``tenant_session``. A raising company is counted and
    skipped, and the next company still runs. The log line names the exception class only.
    """
    ids = list(company_ids)
    result.seen = len(ids)
    for start in range(0, len(ids), _CHUNK):
        result.batches += 1
        for company_id in ids[start : start + _CHUNK]:
            try:
                out = await work(company_id)
                if isinstance(out, Counter):
                    result.outcome.update(out)
                result.processed += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one tenant must not stop the rest
                result.failed += 1
                logger.warning("system runtime: a company pass failed (%s)", type(exc).__name__)
        await asyncio.sleep(0)


# -- budget_reservation_reap ---------------------------------------------------------


async def budget_reservation_reap(discovery: DiscoveryFactory, now: datetime) -> OpResult:
    """Release budget holds whose reservation expired, one company at a time."""
    from nexus.database import tenant_session
    from nexus.models.budget import CostEvent
    from nexus.services.budget_service import BudgetService

    async with discovery() as db:
        ids = (
            (
                await db.execute(
                    select(CostEvent.company_id)
                    .where(
                        CostEvent.status == "reserved",
                        CostEvent.expires_at.is_not(None),
                        CostEvent.expires_at <= now,
                    )
                    .distinct()
                    .limit(OPERATIONS["budget_reservation_reap"].batch_size)
                )
            )
            .scalars()
            .all()
        )

    async def work(company_id: uuid.UUID) -> None:
        async with tenant_session(company_id) as tdb:
            await BudgetService(tdb).reap_expired_reservations(company_id)

    result = OpResult()
    await _per_company(result, ids, work)
    return result


# -- task_recovery -------------------------------------------------------------------


async def task_recovery(discovery: DiscoveryFactory, now: datetime) -> OpResult:
    """Reap stale subtasks, hand stranded goals back and re-enqueue recoverable tasks."""
    from nexus.database import tenant_session
    from nexus.models.task import Goal, Task
    from nexus.runtime.orchestrator import (
        _reap_stale_subtasks,
        _reclaim_stranded_goals,
        reconcile_recovery,
    )

    limit = OPERATIONS["task_recovery"].batch_size
    async with discovery() as db:
        with_tasks = (
            (
                await db.execute(
                    select(Task.company_id)
                    .where(Task.status.in_(["in_progress", "needs_recovery"]))
                    .distinct()
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        with_goals = (
            (
                await db.execute(
                    select(Goal.company_id)
                    .where(Goal.status == "in_progress")
                    .distinct()
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    ids = sorted(set(with_tasks) | set(with_goals), key=str)[:limit]

    async def work(company_id: uuid.UUID) -> None:
        async with tenant_session(company_id) as tdb:
            changed = await _reap_stale_subtasks(tdb, company_id)
            changed += await _reclaim_stranded_goals(tdb, company_id)
            changed += await reconcile_recovery(tdb, company_id)
            if changed:
                await tdb.commit()

    result = OpResult()
    await _per_company(result, ids, work)
    return result


# -- goal_discovery ------------------------------------------------------------------


async def goal_discovery(discovery: DiscoveryFactory, now: datetime) -> OpResult:
    """Tell the orchestrator which companies have goals or tasks to drive.

    Publishes company ids only. The orchestrator reads the goals themselves inside each
    company's tenant session.
    """
    from nexus.models.task import Goal, Task
    from nexus.runtime import work_hints

    limit = OPERATIONS["goal_discovery"].batch_size
    async with discovery() as db:
        goal_companies = (
            (
                await db.execute(
                    select(Goal.company_id)
                    .where(Goal.status == "active", Goal.owner_agent_id.is_not(None))
                    .distinct()
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        task_companies = (
            (
                await db.execute(
                    select(Task.company_id)
                    .where(Task.status.in_(["in_progress", "needs_recovery"]))
                    .distinct()
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    ids = sorted(set(goal_companies) | set(task_companies), key=str)[:limit]
    result = OpResult(seen=len(ids), batches=1 if ids else 0)
    result.processed = await work_hints.publish("goals", ids)
    return result


# -- chat_turn_recovery --------------------------------------------------------------


async def chat_turn_recovery(discovery: DiscoveryFactory, now: datetime) -> OpResult:
    """Recover expired chat-turn leases and expire stale queued turns, per company.

    Also refreshes the queued/active gauges and hints the companies with queued turns to
    the chat workers.
    """
    from nexus.config import settings
    from nexus.models.chat_turn import ACTIVE_STATUSES, ChatTurn
    from nexus.observability.metrics import set_chat_turns
    from nexus.runtime import chat_turns, work_hints

    limit = OPERATIONS["chat_turn_recovery"].batch_size
    ttl = timedelta(seconds=settings.chat_turn_queue_ttl_seconds)
    async with discovery() as db:
        ids = (
            (
                await db.execute(
                    select(ChatTurn.company_id)
                    .where(
                        (ChatTurn.status.in_(ACTIVE_STATUSES) & (ChatTurn.lease_expires_at < now))
                        | ((ChatTurn.status == "queued") & (ChatTurn.queued_at < now - ttl))
                    )
                    .distinct()
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        by_status = dict(
            (
                await db.execute(
                    select(ChatTurn.status, func.count())
                    .where(ChatTurn.status.in_(("queued", *ACTIVE_STATUSES)))
                    .group_by(ChatTurn.status)
                )
            ).all()
        )
        waiting = (
            (
                await db.execute(
                    select(ChatTurn.company_id)
                    .where(ChatTurn.status == "queued")
                    .distinct()
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    set_chat_turns("queued", by_status.get("queued", 0))
    set_chat_turns("active", sum(by_status.get(s, 0) for s in ACTIVE_STATUSES))

    result = OpResult()
    await _per_company(result, ids, lambda cid: chat_turns.recover_company(cid, now))
    await work_hints.publish("chat_turns", waiting)
    return result


# -- task_attempt_recovery -----------------------------------------------------------


async def task_attempt_recovery(discovery: DiscoveryFactory, now: datetime) -> OpResult:
    """Recover expired task-attempt leases and expire stale queued attempts, per company."""
    from nexus.config import settings
    from nexus.models.task_attempt import LEASED_ATTEMPT_STATUSES, TaskAttempt
    from nexus.runtime import task_attempts, work_hints

    limit = OPERATIONS["task_attempt_recovery"].batch_size
    ttl = timedelta(seconds=settings.task_attempt_queue_ttl_seconds)
    async with discovery() as db:
        ids = (
            (
                await db.execute(
                    select(TaskAttempt.company_id)
                    .where(
                        (
                            TaskAttempt.status.in_(LEASED_ATTEMPT_STATUSES)
                            & (TaskAttempt.lease_expires_at < now)
                        )
                        | ((TaskAttempt.status == "queued") & (TaskAttempt.queued_at < now - ttl))
                    )
                    .distinct()
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        waiting = (
            (
                await db.execute(
                    select(TaskAttempt.company_id)
                    .where(TaskAttempt.status == "queued")
                    .distinct()
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    result = OpResult()
    await _per_company(result, ids, lambda cid: task_attempts.recover_company(cid, now))
    await work_hints.publish("task_attempts", waiting)
    return result


# -- watchdog_patrol -----------------------------------------------------------------


async def watchdog_patrol(discovery: DiscoveryFactory, now: datetime) -> OpResult:
    """Check agent health across tenants and file escalations through each tenant session."""
    from nexus.runtime.watchdog_service import discover_companies, patrol_company

    ids = await discover_companies(discovery, OPERATIONS["watchdog_patrol"].batch_size)
    result = OpResult()
    await _per_company(result, ids, patrol_company)
    return result


# -- org_snapshot_refresh ------------------------------------------------------------


async def org_snapshot_refresh(discovery: DiscoveryFactory, now: datetime) -> OpResult:
    """Regenerate debounced or reconciling organization snapshots, a bounded number per run."""
    from nexus.services import org_snapshot

    done = await org_snapshot.tick(now, discovery=discovery)
    return OpResult(seen=len(done), processed=len(done), batches=1 if done else 0)


OPERATIONS: dict[str, Operation] = {
    op.name: op
    for op in (
        Operation("budget_reservation_reap", 60, 50, 60, budget_reservation_reap),
        Operation("task_recovery", 120, 20, 120, task_recovery),
        Operation("goal_discovery", 60, 20, 30, goal_discovery),
        Operation("chat_turn_recovery", 15, 50, 60, chat_turn_recovery),
        Operation("task_attempt_recovery", 15, 50, 60, task_attempt_recovery),
        Operation("watchdog_patrol", 60, 20, 60, watchdog_patrol),
        Operation("org_snapshot_refresh", 60, 20, 120, org_snapshot_refresh),
    )
}
