"""Company work: the one lifecycle every route, tool and worker goes through.

A *work order* is a top-level ``Task`` stamped with :data:`WORK_ORDER` in its
``work_spec`` (no migration: the column already exists, and a real ``WorkSpec``
forbids the ``kind`` key, so the stamp cannot be forged through the task routes).
An ordinary top-level ``Task`` carries no stamp and never enters this lifecycle.
The CEO delegates it to a manager
(``delegated``); the manager assigns one child ``Task`` to a direct report with
a text ``WorkSpec``; the employee's attempt answers it; the attempt then waits
for a manager's review before anything counts as done::

    pending -> delegated -> in_progress -> (employee works) -> in_review
                                   verify -> completed        reject -> failed (retry within cap)

Rules this module enforces:

* Every transition is one conditional UPDATE, so a replay or a race has exactly
  one winner and the loser reads the winner's state.
* Submission is not completion. Only :func:`review` (verify) completes a text
  task, and the reviewer is never the executor.
* Audit rows hold ids, sizes and a digest, never the deliverable or a prompt.
* ``company_id`` always comes from the caller's server-side context.

The employee turn itself runs in :mod:`nexus.runtime.task_attempts`.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from nexus.models.agent import Agent
from nexus.models.task import Goal, Task
from nexus.models.task_attempt import (
    ACTIVE_ATTEMPT_STATUSES,
    LEASED_ATTEMPT_STATUSES,
    TaskAttempt,
)
from nexus.runtime import task_attempts
from nexus.runtime.task_attempts import (
    DEFAULT_MAX_ATTEMPTS,
    MAX_DELIVERABLE_CHARS,
    WORK_ORDER_KIND,
    WorkSpec,
    is_work_order_spec,
)
from nexus.services import manager_service as ms

NAMESPACE = uuid.UUID("5d0b8f3e-6c1a-4f53-9a57-3e1f0c2b7a90")  # shared with the CEO tools
CLOSED_STATUSES = ("completed", "cancelled")
SUMMARY_CHARS = 500
DIGEST_MAX_CHARS = 4000
OPEN_LIMIT = 25
CLOSED_LIMIT = 10
WORK_ORDER: dict[str, Any] = {"kind": WORK_ORDER_KIND}


def is_work_order(task: Task) -> bool:
    """A top-level task created by :func:`create_work_order` (not an ordinary task)."""
    return task.parent_task_id is None and is_work_order_spec(task.work_spec)


def _work_order_clause() -> Any:
    """SQL form of :func:`is_work_order`."""
    return and_(
        Task.parent_task_id.is_(None),
        Task.work_spec["kind"].as_string() == WORK_ORDER_KIND,
    )


def _kind_clause(task: Any) -> Any:
    """Any ``kind`` in ``work_spec``, known or not. Only the lifecycle writes one."""
    return task.work_spec["kind"].as_string().is_not(None)


async def is_work_owned(db: Any, company_id: uuid.UUID, task_id: uuid.UUID) -> bool:
    """True for a work order or a child of one: the work lifecycle owns its state.

    Fails closed: a task (or its parent) whose ``work_spec`` carries any ``kind`` is owned,
    even a kind this version does not know, so a malformed or future marker can never be
    reassigned through the generic routes. It is still not a work order
    (:func:`is_work_order`), so no lifecycle operation acts on it. A missing task, a foreign
    company's task, an ordinary task and one with unrelated ``work_spec`` data are ``False``.
    """
    root = aliased(Task)
    found = await db.execute(
        select(Task.id)
        .outerjoin(root, and_(root.id == Task.parent_task_id, root.company_id == Task.company_id))
        .where(
            Task.id == task_id,
            Task.company_id == company_id,
            or_(_kind_clause(Task), _kind_clause(root)),
        )
        .limit(1)
    )
    return found.first() is not None


def can_view_work_deliverable(principal: Any) -> bool:
    """Who may read a stored deliverable in full. Default deny.

    Allowed: a signed-in person (``kind == "user"`` with a ``user_id``; the middleware only
    builds one for an active user with a current membership) whose role may read tasks, and
    the keyless, unlabelled service principal that ``AUTH_ENABLED=false`` builds for the
    development operator. Everything else gets a bounded summary: API keys, run tokens
    (agents), labelled in-process services, a principal that names an agent, and any kind
    this function does not know.
    """
    kind = getattr(principal, "kind", None)
    if getattr(principal, "agent_id", None) is not None or getattr(principal, "run_id", None):
        return False
    if not principal.has_permission("read", "task"):
        return False
    if kind == "user":
        return getattr(principal, "user_id", None) is not None
    if kind == "service":
        return (
            getattr(principal, "api_key_id", None) is None
            and not getattr(principal, "label", "")
            and getattr(principal, "user_id", None) is None
        )
    return False


def refuse_if_work_owned(owned: bool) -> None:
    """The stable error the generic task routes answer with for work-owned tasks."""
    if owned:
        raise _error(
            409,
            "WORK_OWNED_BY_LIFECYCLE",
            "This task belongs to the company-work lifecycle; use the work routes",
        )


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return ms._error(status_code, code, message)


def _now() -> datetime:
    return task_attempts._now()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def max_attempts(spec: WorkSpec) -> int:
    return spec.max_attempts or DEFAULT_MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Create and delegate
# ---------------------------------------------------------------------------


async def create_work_order(
    db: Any,
    company_id: uuid.UUID,
    *,
    scope: str,
    actor: str,
    title: str,
    idempotency_key: str,
    description: str | None = None,
    goal_id: uuid.UUID | None = None,
    priority: int = 0,
    work_spec: dict[str, Any] | None = None,
    audit_action: str = "work.created",
    **audit_details: Any,
) -> tuple[Task, bool]:
    """Create one work order for ``(scope, idempotency_key)``. Returns ``(task, created)``.

    The id is derived from the company, the creator's scope and the key, so a
    replay finds the same row; a replay with another title is a 409. Commits.
    """
    new_id = uuid.uuid5(NAMESPACE, f"{company_id}:{scope}:work_order:{idempotency_key}")
    existing = (
        await db.execute(select(Task).where(Task.id == new_id, Task.company_id == company_id))
    ).scalar_one_or_none()
    if existing is not None:
        if existing.title != title:
            raise _error(
                409,
                "IDEMPOTENCY_KEY_REUSED",
                "This idempotency key was used for a different request",
            )
        return existing, False
    if goal_id is not None:
        goal = (
            await db.execute(select(Goal).where(Goal.id == goal_id, Goal.company_id == company_id))
        ).scalar_one_or_none()
        if goal is None:
            raise _error(404, "GOAL_NOT_FOUND", f"Goal {goal_id} not found")
    task = Task(
        id=new_id,
        company_id=company_id,
        title=title,
        description=description,
        priority=priority,
        goal_id=goal_id,
        work_spec=work_spec if work_spec is not None else dict(WORK_ORDER),
    )
    try:
        async with db.begin_nested():
            db.add(task)
    except IntegrityError:
        found = (
            await db.execute(select(Task).where(Task.id == new_id, Task.company_id == company_id))
        ).scalar_one_or_none()
        if found is None:
            raise _error(409, "WORK_CONFLICT", "A concurrent create conflicted; retry") from None
        return found, False
    await ms.audit(
        db,
        company_id,
        audit_action,
        actor,
        "task",
        new_id,
        idempotency_key=idempotency_key,
        **audit_details,
    )
    await db.commit()
    return task, True


async def _row(db: Any, company_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    """The task's current row, re-read past the session's identity map."""
    task = (
        await db.execute(
            select(Task)
            .where(Task.id == task_id, Task.company_id == company_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if task is None:
        raise _error(404, "TASK_NOT_FOUND", f"Task {task_id} not found")
    return task


async def require_work(db: Any, company_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    """The task if it is work (a work order or a work-spec task); else a plain 404.

    An ordinary task is not work, so the work routes answer as if it did not exist.
    """
    task = await _row(db, company_id, task_id)
    if not is_work_order(task) and not is_work_spec(task.work_spec):
        raise _error(404, "TASK_NOT_FOUND", f"Task {task_id} not found")
    return task


def is_work_spec(raw: Any) -> bool:
    """A stored ``work_spec`` that is a real ``WorkSpec`` (unrelated JSON is not work)."""
    try:
        task_attempts.parse_work_spec(raw)
    except HTTPException:
        return False
    return True


async def delegate_to_manager(
    db: Any,
    company_id: uuid.UUID,
    ceo_id: uuid.UUID,
    manager_id: uuid.UUID,
    task_id: uuid.UUID,
    actor: str,
) -> tuple[Task, bool]:
    """Hand a work order to one of the CEO's direct reports. Exactly one winner.

    The work order only records its owner; the manager decides who does the
    work. No attempt is created here (an attempt belongs to an employee).
    Returns ``(task, created)``; a replay to the same manager is ``created=False``.
    """
    await ms.require_report(db, company_id, ceo_id, manager_id)
    task = await _row(db, company_id, task_id)
    if task.work_spec and not is_work_order(task):
        raise _error(422, "TASK_HAS_WORK_SPEC", "Delegate a work-spec task as an attempt")
    if not is_work_order(task):
        # An ordinary task is not work: same answer as a task that does not exist.
        raise _error(404, "TASK_NOT_FOUND", f"Task {task_id} not found")
    res = await db.execute(
        update(Task)
        .where(
            Task.id == task_id,
            Task.company_id == company_id,
            Task.status == "pending",
            Task.assigned_agent_id.is_(None),
        )
        .values(assigned_agent_id=manager_id, status="delegated", updated_at=_now())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount == 1:
        await ms.audit(
            db,
            company_id,
            "work.delegated",
            actor,
            "task",
            task_id,
            ceo_id=ceo_id,
            manager_id=manager_id,
        )
        await db.commit()
        return await _row(db, company_id, task_id), True
    await db.rollback()
    task = await _row(db, company_id, task_id)
    if task.assigned_agent_id == manager_id:
        return task, False
    raise _error(409, "WORK_ALREADY_DELEGATED", "The work order is not open for delegation")


async def assign_task(
    db: Any,
    company_id: uuid.UUID,
    manager_id: uuid.UUID,
    work_order_id: uuid.UUID,
    employee_id: uuid.UUID,
    *,
    title: str,
    objective: str,
    idempotency_key: str,
    expected_deliverable: str | None = None,
    max_deliverable_chars: int | None = None,
    attempts_cap: int | None = None,
    principal: Any,
) -> tuple[Task, TaskAttempt, bool]:
    """The manager creates one task under its work order and assigns it to a report.

    Replaying the same key returns the same task and attempt; the same key with
    another employee or title is a 409. Returns ``(task, attempt, created)``.
    """
    actor = principal.display_name
    await ms.require_report(db, company_id, manager_id, employee_id)
    parent = await _row(db, company_id, work_order_id)
    if parent.assigned_agent_id != manager_id or not is_work_order(parent):
        # Not this manager's work order: indistinguishable from a missing one.
        raise _error(404, "TASK_NOT_FOUND", f"Task {work_order_id} not found")
    child_id = uuid.uuid5(NAMESPACE, f"{company_id}:{manager_id}:assigned:{idempotency_key}")
    child = (
        await db.execute(select(Task).where(Task.id == child_id, Task.company_id == company_id))
    ).scalar_one_or_none()
    created = child is None
    if child is not None:
        if (
            child.parent_task_id != parent.id
            or child.assigned_agent_id != employee_id
            or child.title != title
        ):
            raise _error(
                409,
                "IDEMPOTENCY_KEY_REUSED",
                "This idempotency key was used for a different request",
            )
    else:
        if parent.status in CLOSED_STATUSES or parent.status == "failed":
            raise _error(409, "WORK_CLOSED", f"The work order is {parent.status}")
        spec = WorkSpec(
            mode="text",
            objective=objective,
            expected_deliverable=expected_deliverable,
            max_deliverable_chars=max_deliverable_chars,
            max_attempts=attempts_cap,
        )
        child = Task(
            id=child_id,
            company_id=company_id,
            title=title,
            description=objective[:4000],
            priority=parent.priority,
            assigned_agent_id=employee_id,
            parent_task_id=parent.id,
            goal_id=parent.goal_id,
            work_spec=spec.model_dump(mode="json"),
        )
        try:
            async with db.begin_nested():
                db.add(child)
        except IntegrityError:
            created = False  # a concurrent identical assign won; carry on to the attempt
        else:
            await db.execute(
                update(Task)
                .where(
                    Task.id == parent.id, Task.company_id == company_id, Task.status == "delegated"
                )
                .values(
                    status="in_progress",
                    started_at=func.coalesce(Task.started_at, _now()),
                    updated_at=_now(),
                )
                .execution_options(synchronize_session=False)
            )
            await ms.audit(
                db,
                company_id,
                "work.assigned",
                actor,
                "task",
                child_id,
                manager_id=manager_id,
                employee_id=employee_id,
                work_order_id=parent.id,
                idempotency_key=idempotency_key,
            )
            await db.commit()
    # Always run: a crash between the task and its attempt is healed by the replay.
    attempt, queued = await ms.delegate(
        db, company_id, manager_id, employee_id, child_id, principal
    )
    return await _row(db, company_id, child_id), attempt, created or queued


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


async def _reply_text(attempt: TaskAttempt, turn: Any) -> str:
    from nexus.database import tenant_session
    from nexus.models.chat import ChatMessage

    if turn.response_message_id is None:
        return ""
    async with tenant_session(attempt.company_id) as db:
        reply = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.id == turn.response_message_id,
                    ChatMessage.company_id == attempt.company_id,
                )
            )
        ).scalar_one_or_none()
    return (reply.text or "") if reply else ""


async def submit_from_turn(attempt: TaskAttempt, worker_id: str, spec: WorkSpec, turn: Any) -> bool:
    """Turn the finished chat turn's reply into the attempt's deliverable.

    An empty reply is a failure, not a deliverable. The text is clipped to the
    spec's cap. Model text alone never completes the task.
    """
    text = (await _reply_text(attempt, turn)).strip()
    if not text:
        return await task_attempts._finish(
            attempt,
            worker_id,
            "failed",
            "error",
            error_code="EMPTY_DELIVERABLE",
            error="The employee returned no deliverable",
        )
    cap = min(spec.max_deliverable_chars or MAX_DELIVERABLE_CHARS, MAX_DELIVERABLE_CHARS)
    usage = {"model": turn.model_used, "tokens": (turn.result or {}).get("tokens_used")}
    return await submit_deliverable(attempt, worker_id, text, cap, usage)


async def submit_deliverable(
    attempt: TaskAttempt, worker_id: str, text: str, cap: int, usage: dict[str, Any] | None = None
) -> bool:
    """Store the deliverable and park the attempt for review. One conditional UPDATE.

    The attempt leaves the worker (``claimed_by`` and the lease are cleared), so
    the lease sweep leaves it alone: it waits durably for the manager. Returns
    False when the worker lost the attempt or a cancel won the race.
    """
    from nexus.database import tenant_session

    clipped = text[:cap]
    digest = hashlib.sha256(clipped.encode("utf-8")).hexdigest()
    record = {
        "state": "pending_review",
        "passed": None,
        "checks": [],
        "sha256": digest,
        "chars": len(clipped),
        "truncated": len(text) > cap,
    }
    now = _now()
    async with tenant_session(attempt.company_id) as db:
        res = await db.execute(
            update(TaskAttempt)
            .where(
                task_attempts._scoped(attempt.id, attempt.company_id),
                TaskAttempt.claimed_by == worker_id,
                TaskAttempt.status.in_(LEASED_ATTEMPT_STATUSES),
                TaskAttempt.cancel_requested_at.is_(None),
            )
            .values(
                status="verifying",
                claimed_by=None,
                lease_expires_at=None,
                output_summary=clipped,
                verification=record,
                usage=usage,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            await db.rollback()
            fresh = await task_attempts._get(db, attempt.company_id, attempt.id)
            lost_to_cancel = (
                fresh is not None
                and fresh.claimed_by == worker_id
                and fresh.cancel_requested_at is not None
            )
            if not lost_to_cancel:
                return False
        else:
            await db.execute(
                update(Task)
                .where(
                    Task.id == attempt.task_id,
                    Task.company_id == attempt.company_id,
                    Task.status.not_in(CLOSED_STATUSES),
                )
                .values(status="in_review", updated_at=now)
                .execution_options(synchronize_session=False)
            )
            await task_attempts._audit(
                db,
                attempt,
                "work.deliverable_submitted",
                actor_type="agent",
                actor=f"agent:{attempt.agent_id}",
                chars=record["chars"],
                sha256=digest,
                truncated=record["truncated"],
            )
            await db.commit()
            task_attempts.STATS["submitted"] += 1
            await task_attempts._publish(
                (await task_attempts.get_attempt(attempt.company_id, attempt.id)) or attempt
            )
            return True
    return await task_attempts._finish(
        attempt, worker_id, "cancelled", "cancelled", error_code="CANCELLED"
    )


# ---------------------------------------------------------------------------
# Review: verify or reject
# ---------------------------------------------------------------------------


def _reviewable(attempt: TaskAttempt) -> bool:
    return ms.awaiting_review(attempt)


async def review(
    db: Any,
    company_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    decision: str,
    reason: str | None,
    actor: str,
    reviewer_agent_id: uuid.UUID | None,
    retry: bool = False,
) -> tuple[TaskAttempt, bool]:
    """Verify or reject a submitted deliverable. Returns ``(attempt, changed)``.

    ``reviewer_agent_id`` is set for an agent reviewer: it must be the executor's
    manager and never the executor. A human reviewer passes None (the route has
    already required write permission). One conditional UPDATE decides; a loser
    gets 409, a repeat of the winning decision gets the stored result.
    ``retry`` on a reject starts the next attempt when the cap allows.
    """
    if decision not in ("verify", "reject"):
        raise _error(422, "INVALID_DECISION", "decision must be verify or reject")
    attempt = await task_attempts._get(db, company_id, attempt_id)
    if attempt is None:
        raise _error(404, "ATTEMPT_NOT_FOUND", f"Attempt {attempt_id} not found")
    spec = task_attempts.parse_work_spec((attempt.context_snapshot or {}).get("work_spec"))
    if spec.mode != "text":
        raise _error(422, "NOT_TEXT_WORK", "Only text work is reviewed here")
    if reviewer_agent_id is not None:
        if reviewer_agent_id == attempt.agent_id:
            raise _error(403, "SELF_REVIEW", "An employee cannot verify its own work")
        employee = await ms.get_agent(db, company_id, attempt.agent_id)
        if employee.manager_id != reviewer_agent_id:
            raise _error(404, "ATTEMPT_NOT_FOUND", f"Attempt {attempt_id} not found")
    outcome = "verified" if decision == "verify" else "rejected"
    record = attempt.verification or {}
    if not _reviewable(attempt):
        if record.get("state") == outcome and attempt.status in ("completed", "failed"):
            return attempt, False  # the same decision, replayed
        raise _error(
            409, "NOT_AWAITING_REVIEW", f"The attempt is {attempt.status}, not awaiting review"
        )
    reason = (reason or "").strip()[:1000] or None
    if decision == "reject" and not reason:
        raise _error(422, "REASON_REQUIRED", "A rejection needs a reason")
    now = _now()
    stamped = {**record, "state": outcome, "reviewed_by": actor, "reviewed_at": now.isoformat()}
    waiting = (TaskAttempt.status == "verifying", TaskAttempt.claimed_by.is_(None))
    if decision == "verify":
        stamped.update(
            passed=True, checks=[{"check": "manager_review", "passed": True, "detail": ""}]
        )
        done = await task_attempts._finish_in(
            db, attempt, "completed", "goal", None, *waiting, verification=stamped
        )
    else:
        stamped.update(
            passed=False,
            checks=[{"check": "manager_review", "passed": False, "detail": reason[:300]}],
        )
        done = await task_attempts._finish_in(
            db,
            attempt,
            "failed",
            "verification_failed",
            None,
            *waiting,
            verification=stamped,
            error_code="REJECTED_BY_MANAGER",
            error=reason,
        )
    if not done:  # lost the race; _finish_in rolled back
        fresh = await task_attempts._get(db, company_id, attempt_id)
        await db.refresh(fresh)
        if (fresh.verification or {}).get("state") == outcome:
            return fresh, False
        raise _error(409, "NOT_AWAITING_REVIEW", f"The attempt is already {fresh.status}")
    await task_attempts._audit(
        db,
        attempt,
        f"work.{outcome}",
        actor_type="agent" if reviewer_agent_id else "user",
        actor=actor,
        reviewer_agent_id=str(reviewer_agent_id) if reviewer_agent_id else None,
        reason_chars=len(reason or ""),
    )
    await db.commit()
    task_attempts.STATS[outcome] += 1
    await db.refresh(attempt)
    await task_attempts._publish(attempt)
    if decision == "reject" and retry and attempt.attempt_number < max_attempts(spec):
        await _retry(db, company_id, attempt, actor)
        await db.refresh(attempt)
    return attempt, True


async def _retry(db: Any, company_id: uuid.UUID, attempt: TaskAttempt, actor: str) -> None:
    """The one bounded retry after a rejection: task back to pending, next attempt queued."""
    await db.execute(
        update(Task)
        .where(Task.id == attempt.task_id, Task.company_id == company_id, Task.status == "failed")
        .values(status="pending", completion_reason=None, error=None, updated_at=_now())
        .execution_options(synchronize_session=False)
    )
    parent_id = (await _row(db, company_id, attempt.task_id)).parent_task_id
    if parent_id is not None:
        await db.execute(
            update(Task)
            .where(Task.id == parent_id, Task.company_id == company_id, Task.status == "failed")
            .values(status="in_progress", completion_reason=None, error=None, updated_at=_now())
            .execution_options(synchronize_session=False)
        )
    await db.commit()
    principal = _Actor(actor)
    await task_attempts.retry_attempt(
        db,
        company_id,
        attempt.task_id,
        attempt.id,
        principal,
        idempotency_key=f"review:{attempt.id}:retry",
    )


class _Actor:
    kind = "agent"

    def __init__(self, name: str) -> None:
        self.display_name = name


# ---------------------------------------------------------------------------
# Roll-up and cancel
# ---------------------------------------------------------------------------


async def after_terminal(db: Any, attempt: TaskAttempt) -> None:
    """Settle the parent work order after a text attempt ends. Called inside ``_finish_in``.

    All children completed completes the order; a child out of attempts fails
    it (fail fast). Conditional UPDATEs: replays are no-ops.
    """
    spec = (attempt.context_snapshot or {}).get("work_spec") or {}
    if spec.get("mode") != "text":
        return
    child = await _row(db, attempt.company_id, attempt.task_id)
    if child.parent_task_id is None:
        return
    now = _now()
    open_parent = Task.status.in_(("delegated", "in_progress", "in_review", "pending"))
    where = (Task.id == child.parent_task_id, Task.company_id == attempt.company_id, open_parent)
    if attempt.status == "completed":
        rows = (
            await db.execute(
                select(Task.status, Task.result).where(
                    Task.parent_task_id == child.parent_task_id,
                    Task.company_id == attempt.company_id,
                )
            )
        ).all()
        if rows and all(status == "completed" for status, _ in rows):
            result = "\n---\n".join((r or "")[: SUMMARY_CHARS * 4] for _, r in rows)[:4000]
            await db.execute(
                update(Task)
                .where(*where)
                .values(
                    status="completed",
                    completion_reason="goal",
                    completed_at=now,
                    result=result or None,
                    error=None,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
    elif attempt.status in ("failed", "blocked", "expired") and (
        attempt.attempt_number >= (spec.get("max_attempts") or DEFAULT_MAX_ATTEMPTS)
    ):
        await db.execute(
            update(Task)
            .where(*where)
            .values(
                status="failed",
                completion_reason=attempt.completion_reason,
                error=(attempt.error or attempt.error_code or "")[:4000] or None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )


async def cancel_work(
    db: Any, company_id: uuid.UUID, task_id: uuid.UUID, *, actor: str
) -> tuple[Task, bool]:
    """Cancel a work order or task and its open work. Completed work is never overwritten.

    Returns ``(task, changed)``; cancelling a cancelled task is a no-op.
    """
    task = await _row(db, company_id, task_id)
    if task.status == "completed":
        raise _error(409, "TASK_ALREADY_COMPLETED", "The task is already completed")
    if task.status == "cancelled":
        return task, False
    children = (
        (
            await db.execute(
                select(Task.id).where(Task.parent_task_id == task_id, Task.company_id == company_id)
            )
        )
        .scalars()
        .all()
    )
    now = _now()
    for target in [task_id, *children]:
        # Mark the task first so a worker finishing its cancelled attempt cannot reopen it.
        await db.execute(
            update(Task)
            .where(
                Task.id == target,
                Task.company_id == company_id,
                Task.status.not_in(CLOSED_STATUSES),
            )
            .values(
                status="cancelled", completion_reason="cancelled", completed_at=None, updated_at=now
            )
            .execution_options(synchronize_session=False)
        )
        active = await task_attempts._active(db, company_id, target)
        if active is None:
            continue
        if _reviewable(active):
            await task_attempts._finish_in(
                db,
                active,
                "cancelled",
                "cancelled",
                None,
                TaskAttempt.status == "verifying",
                TaskAttempt.claimed_by.is_(None),
                cancel_requested_at=now,
                cancelled_by=actor,
                error_code="CANCELLED",
            )
        else:
            await db.execute(
                update(TaskAttempt)
                .where(
                    task_attempts._scoped(active.id, company_id),
                    TaskAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
                    TaskAttempt.cancel_requested_at.is_(None),
                )
                .values(cancel_requested_at=now, cancelled_by=actor, updated_at=now)
                .execution_options(synchronize_session=False)
            )
    await ms.audit(
        db, company_id, "work.cancelled", actor, "task", task_id, open_children=len(children)
    )
    await db.commit()
    for target in [task_id, *children]:
        active = await task_attempts._active(db, company_id, target)
        if active is not None:
            # Queued attempts finish at once; a running one is finished by its worker.
            await task_attempts.cancel_attempt(db, company_id, target, active.id, _Actor(actor))
    task_attempts.get_worker().wake(company_id)
    return await _row(db, company_id, task_id), True


# ---------------------------------------------------------------------------
# Live status
# ---------------------------------------------------------------------------


def _clip(value: str | None, limit: int = SUMMARY_CHARS) -> str | None:
    return value[:limit] if value else None


def _attempt_state(
    attempt: TaskAttempt | None, now: datetime, with_deliverable: bool = False
) -> dict[str, Any] | None:
    if attempt is None:
        return None
    waiting = ms.awaiting_review(attempt)
    record = attempt.verification or {}
    return {
        # Only for a human reviewer's own reads; never in the CEO's prompt or tool output.
        **(
            {"deliverable": _clip(attempt.output_summary, MAX_DELIVERABLE_CHARS)}
            if with_deliverable and waiting
            else {}
        ),
        "attempt_id": str(attempt.id),
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "awaiting_review": waiting,
        "awaiting_review_seconds": (
            int((now - attempt.updated_at).total_seconds())
            if waiting and attempt.updated_at
            else None
        ),
        "verification": record.get("state")
        or (
            "passed"
            if record.get("passed")
            else "failed"
            if record.get("passed") is False
            else None
        ),
        "stale": ms._stale(attempt, now),
        "error_code": attempt.error_code,
        "updated_at": _iso(attempt.updated_at),
    }


async def status(
    db: Any,
    company_id: uuid.UUID,
    work_id: uuid.UUID | None = None,
    *,
    with_deliverable: bool = False,
) -> dict[str, Any]:
    """The company's work, read live from durable rows. No model call, no cache.

    Filtered to the company in SQL before any limit: every open work order
    (newest first, up to ``OPEN_LIMIT``) plus the most recent ``CLOSED_LIMIT``
    closed ones. Result text is the stored deliverable, clipped.
    """
    now = _now()
    base = select(Task).where(Task.company_id == company_id, _work_order_clause())
    if work_id is not None:
        roots = list((await db.execute(base.where(Task.id == work_id))).scalars())
        if not roots:
            raise _error(404, "TASK_NOT_FOUND", f"Task {work_id} not found")
    else:
        order = (Task.updated_at.desc(), Task.id)
        open_rows = (
            await db.execute(
                base.where(Task.status.not_in(CLOSED_STATUSES)).order_by(*order).limit(OPEN_LIMIT)
            )
        ).scalars()
        closed_rows = (
            await db.execute(
                base.where(Task.status.in_(CLOSED_STATUSES)).order_by(*order).limit(CLOSED_LIMIT)
            )
        ).scalars()
        roots = [*open_rows, *closed_rows]
    root_ids = [t.id for t in roots]
    children = (
        list(
            (
                await db.execute(
                    select(Task)
                    .where(Task.company_id == company_id, Task.parent_task_id.in_(root_ids))
                    .order_by(Task.created_at, Task.id)
                )
            ).scalars()
        )
        if root_ids
        else []
    )
    latest = await ms.latest_attempts(db, company_id, [*root_ids, *(c.id for c in children)])
    agent_ids = {a for t in (*roots, *children) for a in (t.assigned_agent_id,) if a}
    names = (
        dict(
            (
                await db.execute(
                    select(Agent.id, Agent.name).where(
                        Agent.company_id == company_id, Agent.id.in_(agent_ids)
                    )
                )
            ).all()
        )
        if agent_ids
        else {}
    )

    def view(task: Task) -> dict[str, Any]:
        attempt = latest.get(task.id)
        failed = task.status in ("failed", "blocked")
        return {
            "id": str(task.id),
            "title": task.title,
            "status": task.status,
            "assignee": (
                {"id": str(task.assigned_agent_id), "name": names.get(task.assigned_agent_id)}
                if task.assigned_agent_id
                else None
            ),
            "goal_id": str(task.goal_id) if task.goal_id else None,
            "attempt": _attempt_state(attempt, now, with_deliverable),
            "result": _clip(task.result) if task.status == "completed" else None,
            "failure": _clip(task.error) if failed else None,
            "updated_at": _iso(task.updated_at),
        }

    by_parent: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for child in children:
        by_parent.setdefault(child.parent_task_id, []).append(view(child))
    items = [{**view(t), "tasks": by_parent.get(t.id, [])} for t in roots]
    attempts = [a for i in items for a in (i["attempt"], *(c["attempt"] for c in i["tasks"])) if a]
    waiting = [a["awaiting_review_seconds"] for a in attempts if a["awaiting_review"]]
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "generated_at": now.isoformat(),
        "counts": counts,
        # Content-free: enough to see stuck work without reading any deliverable.
        "metrics": {
            "awaiting_review": len(waiting),
            "oldest_awaiting_review_seconds": max(waiting, default=None),
            "stale_attempts": sum(1 for a in attempts if a["stale"]),
        },
        "work": items,
    }


def digest(snapshot: dict[str, Any], limit: int = 8) -> str:
    """A short text view of :func:`status` for the CEO's prompt. Stored facts only."""
    lines = ["Live work (from the database, newest first):"]
    for item in snapshot["work"][:limit]:
        who = (item["assignee"] or {}).get("name") or "unassigned"
        line = f"- [{item['status']}] {item['title'][:120]} (owner: {who}, id {item['id']})"
        for task in item["tasks"][:3]:
            att = task["attempt"] or {}
            state = (
                "awaiting review"
                if att.get("awaiting_review")
                else att.get("status") or task["status"]
            )
            line += f"\n    task {task['title'][:80]}: {task['status']}, attempt {state}"
            if task["result"]:
                line += f", result: {task['result'][:200]}"
            if task["failure"]:
                line += f", failure: {task['failure'][:200]}"
        lines.append(line)
    if len(lines) == 1:
        lines.append("- no work yet")
    text = "\n".join(lines)
    return text if len(text) <= DIGEST_MAX_CHARS else text[: DIGEST_MAX_CHARS - 1] + "…"
