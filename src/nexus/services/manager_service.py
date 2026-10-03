"""Manager Core: a manager's direct reports, their work, and a roll-up.

The reporting line is ``Agent.manager_id`` (set, tenant-checked and
cycle-checked by ``PUT /api/v1/agents/{id}/manager``). An agent is a manager
when it has at least one direct report; there is no separate flag to drift.

Everything here is derived from persisted rows -- Agent, Task, TaskAttempt --
so an employee's status is never a second mutable record. Delegation queues
work through :func:`nexus.runtime.task_attempts.start_attempt`, the one path
that runs employee work, with a deterministic idempotency key so the same
delegation started twice yields one attempt.

Every lookup is scoped to one company, and every read or write about an
employee first proves that the employee reports directly to the manager.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from nexus.governance.audit_service import record_audit
from nexus.models.agent import Agent
from nexus.models.task import Task
from nexus.models.task_attempt import (
    ACTIVE_ATTEMPT_STATUSES,
    LEASED_ATTEMPT_STATUSES,
    TaskAttempt,
)
from nexus.runtime import task_attempts

# An active attempt with no progress for this long is reported as stale. The
# attempt worker recovers expired leases on its own; this only surfaces them.
STALE_AFTER = timedelta(minutes=30)
FAILED_STATUSES = ("failed", "blocked", "expired")
# ponytail: newest tasks per report only; page the roll-up if a team outgrows it.
MAX_TASKS = 200


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def agent_ref(agent: Agent) -> dict[str, Any]:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "title": agent.title,
        "role": agent.role,
        "status": agent.status,
    }


async def get_agent(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    """The agent in this company, or 404 (another tenant's agent is unseen)."""
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    ).scalar_one_or_none()
    if agent is None:
        raise _error(404, "AGENT_NOT_FOUND", f"Agent {agent_id} not found")
    return agent


async def direct_reports(db: Any, company_id: uuid.UUID, manager_id: uuid.UUID) -> list[Agent]:
    """The agents whose manager is ``manager_id``, in this company, by name."""
    rows = await db.execute(
        select(Agent)
        .where(Agent.company_id == company_id, Agent.manager_id == manager_id)
        .order_by(Agent.name, Agent.id)
    )
    return list(rows.scalars().all())


async def require_report(
    db: Any, company_id: uuid.UUID, manager_id: uuid.UUID, employee_id: uuid.UUID
) -> Agent:
    """The employee, when it reports directly to the manager; 404 or 403 otherwise."""
    await get_agent(db, company_id, manager_id)
    employee = await get_agent(db, company_id, employee_id)
    if employee.manager_id != manager_id:
        raise _error(403, "NOT_A_DIRECT_REPORT", "The agent does not report to this manager")
    return employee


async def audit(
    db: Any,
    company_id: uuid.UUID,
    action: str,
    actor: str,
    resource_type: str,
    resource_id: uuid.UUID,
    **details: Any,
) -> None:
    """One ``manager.*`` audit row, written in ``db``'s transaction; fails closed."""
    await record_audit(
        company_id,
        action,
        actor_type=(
            "agent" if actor.startswith(("agent:", "run:"))
            else "system" if actor.startswith("policy:")
            else "user"
        ),
        actor_id=actor,
        resource_type=resource_type,
        resource_id=str(resource_id),
        details={k: str(v) if isinstance(v, uuid.UUID) else v for k, v in details.items()},
        db=db,
        raise_on_error=True,
    )


async def delegate(
    db: Any,
    company_id: uuid.UUID,
    manager_id: uuid.UUID,
    employee_id: uuid.UUID,
    task_id: uuid.UUID,
    principal: Any,
) -> tuple[TaskAttempt, bool]:
    """Hand an existing task to a direct report and queue its attempt.

    The task is (re)assigned to the employee unless another employee's attempt
    is active, then :func:`task_attempts.start_attempt` queues the work under
    the key ``manager:<manager>:<employee>``: delegating the same task to the
    same employee again returns that attempt instead of creating another, and
    writes nothing. A later retry goes through the attempt retry route.

    Returns ``(attempt, created)``. Commits.
    """
    await require_report(db, company_id, manager_id, employee_id)
    task = await task_attempts._load_task(db, company_id, task_id)
    if task.assigned_agent_id != employee_id:
        active = await task_attempts._active(db, company_id, task_id)
        if active is not None:
            raise _error(409, "ATTEMPT_ACTIVE", "Cancel the active attempt before delegating")
        task.assigned_agent_id = employee_id
        task.updated_at = task_attempts._now()
    key = f"manager:{manager_id}:{employee_id}"
    # The delegation is recorded on the attempt's own ``task.attempt_queued``
    # row. A second audit write here would contend with the woken worker for
    # the SQLite audit chain lock while holding the write lock.
    attempt, created = await task_attempts.start_attempt(
        db, company_id, task_id, principal, agent_id=employee_id, idempotency_key=key,
        audit_details={"delegated_by": str(manager_id), "idempotency_key": key},
    )
    if not created:
        await db.commit()
    return attempt, created


def awaiting_review(attempt: TaskAttempt) -> bool:
    """A submitted deliverable no worker holds: only a manager's review moves it."""
    return attempt.status == "verifying" and attempt.claimed_by is None


def _stale(attempt: TaskAttempt, now: datetime) -> bool:
    if attempt.status not in ACTIVE_ATTEMPT_STATUSES:
        return False
    if awaiting_review(attempt):
        return False  # durable and waiting on a person, not on a worker
    if (
        attempt.status in LEASED_ATTEMPT_STATUSES
        and attempt.lease_expires_at is not None
        and attempt.lease_expires_at < now
    ):
        return True
    return attempt.updated_at is not None and now - attempt.updated_at > STALE_AFTER


def work_bucket(task: Task, attempt: TaskAttempt | None, now: datetime) -> str:
    """Where a task stands, from its newest attempt (or the task, before one).

    One of ``stale``, ``active``, ``completed``, ``failed``, ``blocked`` or
    ``queued``.
    """
    status = attempt.status if attempt is not None else task.status
    if attempt is not None and _stale(attempt, now):
        return "stale"
    if status in LEASED_ATTEMPT_STATUSES:
        return "active"
    if status == "completed" or task.status == "completed":
        return "completed"
    if status == "blocked" or task.status == "blocked":
        return "blocked"
    if status in FAILED_STATUSES or task.status == "failed":
        return "failed"
    return "queued"


async def latest_attempts(
    db: Any, company_id: uuid.UUID, task_ids: list[uuid.UUID] | None
) -> dict[uuid.UUID, TaskAttempt]:
    """Each task's newest attempt, in one query; ``None`` means every task."""
    if task_ids == []:
        return {}
    newest = select(TaskAttempt.task_id, func.max(TaskAttempt.attempt_number).label("n")).where(
        TaskAttempt.company_id == company_id
    )
    if task_ids is not None:
        newest = newest.where(TaskAttempt.task_id.in_(task_ids))
    newest = newest.group_by(TaskAttempt.task_id).subquery()
    rows = await db.execute(
        select(TaskAttempt).join(
            newest,
            (TaskAttempt.task_id == newest.c.task_id) & (TaskAttempt.attempt_number == newest.c.n),
        ).where(TaskAttempt.company_id == company_id)
    )
    return {a.task_id: a for a in rows.scalars().all()}


def _attempt_ref(
    attempt: TaskAttempt | None, titles: dict[uuid.UUID, str]
) -> dict[str, Any] | None:
    if attempt is None:
        return None
    return {
        "attempt_id": str(attempt.id),
        "task_id": str(attempt.task_id),
        "task_title": titles.get(attempt.task_id),
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "summary": task_attempts.bounded_summary(attempt.output_summary),
        "completion_reason": attempt.completion_reason,
        "error_code": attempt.error_code,
        "error": attempt.error,
        "started_at": _iso(attempt.started_at),
        "completed_at": _iso(attempt.completed_at),
        "updated_at": _iso(attempt.updated_at),
    }


async def _latest(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID, statuses: tuple) -> Any:
    return (
        await db.execute(
            select(TaskAttempt)
            .where(
                TaskAttempt.company_id == company_id,
                TaskAttempt.agent_id == agent_id,
                TaskAttempt.status.in_(statuses),
            )
            .order_by(TaskAttempt.updated_at.desc(), TaskAttempt.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def employee_status(db: Any, employee: Agent, now: datetime | None = None) -> dict[str, Any]:
    """Structured status of one employee, derived from its attempts."""
    now = now or task_attempts._now()
    company_id = employee.company_id
    active = await _latest(db, company_id, employee.id, ACTIVE_ATTEMPT_STATUSES)
    success = await _latest(db, company_id, employee.id, ("completed",))
    failure = await _latest(db, company_id, employee.id, FAILED_STATUSES)
    known = [a for a in (active, success, failure) if a is not None]
    task_ids = {a.task_id for a in known}
    titles = (
        dict(
            (
                await db.execute(
                    select(Task.id, Task.title).where(
                        Task.company_id == company_id, Task.id.in_(task_ids)
                    )
                )
            ).all()
        )
        if task_ids
        else {}
    )

    if active is not None:
        state = "stale" if _stale(active, now) else (
            "queued" if active.status == "queued" else "working"
        )
    elif employee.status == "paused":
        state = "paused"
    else:
        finished = [a for a in (success, failure) if a is not None]
        last = max(finished, key=lambda a: a.updated_at) if finished else None
        state = "idle" if last is None or last.status == "completed" else last.status

    newest = max(known, key=lambda a: a.updated_at) if known else None
    evidence_from = next(
        (
            a
            for a in sorted(known, key=lambda a: a.updated_at, reverse=True)
            if a.artifacts or a.verification
        ),
        None,
    )
    usage = (newest.usage or {}) if newest is not None else {}
    stamps = [employee.updated_at] + [a.updated_at for a in known]
    return {
        "employee": agent_ref(employee),
        "state": state,
        "active": _attempt_ref(active, titles),
        "progress": (
            {"report": active.report, "report_seq": active.report_seq}
            if active is not None and active.report
            else None
        ),
        "latest_evidence": (
            {
                "attempt_id": str(evidence_from.id),
                "task_id": str(evidence_from.task_id),
                "artifacts": evidence_from.artifacts or [],
                "verification": evidence_from.verification,
            }
            if evidence_from is not None
            else None
        ),
        "last_success": _attempt_ref(success, titles),
        "latest_failure": _attempt_ref(failure, titles),
        "backend": (employee.adapter_config or {}).get("backend") or usage.get("backend"),
        "updated_at": _iso(max(s for s in stamps if s is not None)),
    }


async def rollup(db: Any, company_id: uuid.UUID, manager_id: uuid.UUID) -> dict[str, Any]:
    """The manager's direct-report snapshot. Deterministic; no model call."""
    now = task_attempts._now()
    manager = await get_agent(db, company_id, manager_id)
    reports = await direct_reports(db, company_id, manager_id)
    names = {r.id: r.name for r in reports}
    statuses = [await employee_status(db, r, now) for r in reports]

    tasks = (
        (
            await db.execute(
                select(Task)
                .where(Task.company_id == company_id, Task.assigned_agent_id.in_(list(names)))
                .order_by(Task.updated_at.desc(), Task.id)
                .limit(MAX_TASKS)
            )
        ).scalars().all()
        if names
        else []
    )
    latest = await latest_attempts(db, company_id, [t.id for t in tasks])

    work: dict[str, list[dict[str, Any]]] = {
        "active": [], "queued": [], "completed": [], "failed_blocked": [], "stale": []
    }
    for task in tasks:
        attempt = latest.get(task.id)
        bucket = work_bucket(task, attempt, now)
        if bucket in ("failed", "blocked"):
            bucket = "failed_blocked"
        work[bucket].append(
            {
                "task_id": str(task.id),
                "title": task.title,
                "employee_id": str(task.assigned_agent_id),
                "employee_name": names.get(task.assigned_agent_id),
                "task_status": task.status,
                "attempt_id": str(attempt.id) if attempt is not None else None,
                "attempt_status": attempt.status if attempt is not None else None,
                "error_code": attempt.error_code if attempt is not None else None,
                "summary": task_attempts.bounded_summary(attempt.output_summary)
                if attempt is not None
                else None,
                "updated_at": _iso(attempt.updated_at if attempt is not None else task.updated_at),
            }
        )

    counts = {k: len(v) for k, v in work.items()}
    blockers = [f"{w['employee_name']}: {w['title']}" for w in work["failed_blocked"]]
    summary = (
        f"{manager.name} has {len(reports)} direct report(s): "
        f"{counts['active']} active, {counts['queued']} queued, {counts['completed']} completed, "
        f"{counts['failed_blocked']} failed/blocked, {counts['stale']} stale."
    )
    if blockers:
        summary += " Needs attention: " + "; ".join(blockers[:5]) + "."
    stamps = [s["updated_at"] for s in statuses]
    stamps += [w["updated_at"] for v in work.values() for w in v]
    return {
        "manager": agent_ref(manager),
        "direct_reports": statuses,
        "work": work,
        "counts": counts,
        "summary": summary,
        "generated_at": _iso(now),
        "data_as_of": max((s for s in stamps if s), default=None),
    }


async def task_evidence(
    db: Any, company_id: uuid.UUID, manager_id: uuid.UUID, task_id: uuid.UUID
) -> dict[str, Any]:
    """Results and evidence of a task held by one of the manager's reports."""
    task = await task_attempts._load_task(db, company_id, task_id)
    if task.assigned_agent_id is None:
        raise _error(403, "NOT_A_DIRECT_REPORT", "The task is not assigned to a direct report")
    await require_report(db, company_id, manager_id, task.assigned_agent_id)
    attempts = (
        await db.execute(
            select(TaskAttempt)
            .where(TaskAttempt.company_id == company_id, TaskAttempt.task_id == task_id)
            .order_by(TaskAttempt.attempt_number.desc())
        )
    ).scalars().all()
    return {
        "task": {
            "id": str(task.id),
            "title": task.title,
            "status": task.status,
            "assigned_agent_id": str(task.assigned_agent_id),
        },
        "attempts": [task_attempts.attempt_view(a) for a in attempts],
    }
