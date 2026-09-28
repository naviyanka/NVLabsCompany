"""Task attempt API: start, read, cancel and retry an employee's work on a task.

Thin shells over :mod:`nexus.runtime.task_attempts`, which owns validation,
the one-active-attempt rule and every state change. Errors carry a stable
``code`` (409 for state conflicts, 422 for a task or employee that cannot run
work). Responses hold worktree-relative paths and evidence references only.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession, require_permission
from nexus.models.task_attempt import TaskAttempt
from nexus.runtime import task_attempts

router = APIRouter(tags=["task-attempts"])

READ = [require_permission("read", "task")]
WRITE = [require_permission("write", "task")]

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)]


class AttemptStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Must be the task's assigned employee; defaults to it.
    agent_id: uuid.UUID | None = None


async def _attempt(
    db: Any, company_id: uuid.UUID, task_id: uuid.UUID, attempt_id: uuid.UUID
) -> TaskAttempt:
    attempt = await task_attempts._get(db, company_id, attempt_id)
    if attempt is None or attempt.task_id != task_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "ATTEMPT_NOT_FOUND", "message": f"Attempt {attempt_id} not found"},
        )
    return attempt


@router.post("/api/v1/tasks/{task_id}/attempts", dependencies=WRITE)
async def start_attempt(
    task_id: uuid.UUID,
    response: Response,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    body: AttemptStart | None = None,
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    """Start work on the task, or return the attempt already running it."""
    attempt, created = await task_attempts.start_attempt(
        db,
        company_id,
        task_id,
        principal,
        agent_id=body.agent_id if body else None,
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {**task_attempts.attempt_view(attempt), "created": created}


@router.get("/api/v1/tasks/{task_id}/attempts", dependencies=READ)
async def list_attempts(
    task_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId
) -> list[dict[str, Any]]:
    """Every attempt on the task, newest first."""
    await task_attempts._load_task(db, company_id, task_id)
    rows = (
        await db.execute(
            select(TaskAttempt)
            .where(TaskAttempt.company_id == company_id, TaskAttempt.task_id == task_id)
            .order_by(TaskAttempt.attempt_number.desc())
        )
    ).scalars()
    return [task_attempts.attempt_view(a) for a in rows]


@router.get("/api/v1/tasks/{task_id}/attempts/{attempt_id}", dependencies=READ)
async def get_attempt(
    task_id: uuid.UUID, attempt_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId
) -> dict[str, Any]:
    """One attempt with its latest report."""
    return task_attempts.attempt_view(await _attempt(db, company_id, task_id, attempt_id))


@router.get("/api/v1/tasks/{task_id}/attempts/{attempt_id}/evidence", dependencies=READ)
async def get_evidence(
    task_id: uuid.UUID, attempt_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId
) -> dict[str, Any]:
    """The artifact manifest and the verification summary."""
    attempt = await _attempt(db, company_id, task_id, attempt_id)
    record = attempt.verification or {}
    return {
        "attempt_id": str(attempt.id),
        "status": attempt.status,
        "artifacts": attempt.artifacts or [],
        "verification": {
            "passed": record.get("passed"),
            "error_code": record.get("error_code"),
            "checks": record.get("checks", []),
            "commands": [
                {k: v for k, v in c.items() if k != "tail"} for c in record.get("commands", [])
            ],
            "criteria": record.get("criteria", []),
            "evaluator": record.get("evaluator"),
        }
        if record
        else None,
    }


@router.post("/api/v1/tasks/{task_id}/attempts/{attempt_id}/cancel", dependencies=WRITE)
async def cancel_attempt(
    task_id: uuid.UUID,
    attempt_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Cancel this attempt only."""
    attempt = await task_attempts.cancel_attempt(db, company_id, task_id, attempt_id, principal)
    return task_attempts.attempt_view(attempt)


@router.post("/api/v1/tasks/{task_id}/attempts/{attempt_id}/retry", dependencies=WRITE)
async def retry_attempt(
    task_id: uuid.UUID,
    attempt_id: uuid.UUID,
    response: Response,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    """Start the next attempt after a failed, blocked, cancelled or expired one."""
    attempt, created = await task_attempts.retry_attempt(
        db, company_id, task_id, attempt_id, principal, idempotency_key=idempotency_key
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {**task_attempts.attempt_view(attempt), "created": created}
