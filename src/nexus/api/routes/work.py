"""Work API: the human operator's view of company work and its lifecycle actions.

Thin shells over :mod:`nexus.services.work_service`, which owns every state change.
The company always comes from the authenticated context, never the path or body. A
work order that is not in the caller's company is a plain 404, exactly like one that
does not exist. Agents (run tokens) use the governed manager and CEO tools instead.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession, require_permission
from nexus.runtime.task_attempts import attempt_view
from nexus.services import ceo_service, work_service

router = APIRouter(tags=["work"])

READ = [require_permission("read", "task")]
WRITE = [require_permission("write", "task")]

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)]


class WorkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    goal_id: uuid.UUID | None = None
    priority: int = Field(default=0, ge=0, le=10)


class WorkDelegate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manager_id: uuid.UUID


class WorkReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["verify", "reject"]
    reason: str | None = Field(default=None, max_length=1000)
    retry: bool = False


def _human(principal: Any) -> str:
    """Only a person (or a service key) acts here; a run token is an agent."""
    if principal.kind == "run":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "AGENT_USES_TOOLS", "message": "Agents act through governed tools"},
        )
    return principal.display_name


def _not_found(work_id: uuid.UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "TASK_NOT_FOUND", "message": f"Work {work_id} not found"},
    )


@router.post("/api/v1/work", status_code=status.HTTP_201_CREATED, dependencies=WRITE)
async def create_work(
    body: WorkCreate,
    response: Response,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    """Create a work order. The same Idempotency-Key returns the same one."""
    actor = _human(principal)
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Send an Idempotency-Key"},
        )
    task, created = await work_service.create_work_order(
        db,
        company_id,
        scope=f"human:{actor}",
        actor=actor,
        title=body.title,
        idempotency_key=idempotency_key,
        description=body.description,
        goal_id=body.goal_id,
        priority=body.priority,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {"id": str(task.id), "status": task.status, "created": created}


@router.get("/api/v1/work", dependencies=READ)
async def list_work(db: DbSession, company_id: CurrentCompanyId) -> dict[str, Any]:
    """Live work: open first, then the most recent closed. Read from stored state."""
    return await work_service.status(db, company_id, with_deliverable=True)


@router.get("/api/v1/work/{work_id}", dependencies=READ)
async def get_work(
    work_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId
) -> dict[str, Any]:
    snapshot = await work_service.status(db, company_id, work_id, with_deliverable=True)
    if not snapshot["work"]:
        raise _not_found(work_id)
    return snapshot["work"][0]


@router.post("/api/v1/work/{work_id}/delegate", dependencies=WRITE)
async def delegate_work(
    work_id: uuid.UUID,
    body: WorkDelegate,
    response: Response,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Hand the work order to the CEO's manager. Repeating it changes nothing."""
    actor = _human(principal)
    ceo = await ceo_service.current_ceo(db, company_id)
    if ceo is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "NO_CEO", "message": "The company has no CEO"},
        )
    task, created = await work_service.delegate_to_manager(
        db, company_id, ceo.id, body.manager_id, work_id, actor
    )
    response.status_code = status.HTTP_200_OK
    return {"id": str(task.id), "status": task.status, "created": created}


@router.post("/api/v1/work/attempts/{attempt_id}/review", dependencies=WRITE)
async def review_work(
    attempt_id: uuid.UUID,
    body: WorkReview,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Verify or reject a submitted deliverable. One decision wins; a replay is a no-op."""
    attempt, changed = await work_service.review(
        db,
        company_id,
        attempt_id,
        decision=body.decision,
        reason=body.reason,
        actor=_human(principal),
        reviewer_agent_id=None,
        retry=body.retry,
    )
    return {"changed": changed, "attempt": attempt_view(attempt)}


@router.post("/api/v1/work/{work_id}/cancel", dependencies=WRITE)
async def cancel_work(
    work_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    task, changed = await work_service.cancel_work(db, company_id, work_id, actor=_human(principal))
    return {"id": str(task.id), "status": task.status, "changed": changed}
