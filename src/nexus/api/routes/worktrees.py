"""Agent worktree API: list, create, read, transition, refresh and archive worktrees.

Every route is a thin shell over :class:`nexus.services.worktree_service.WorktreeService`,
which is built for the authenticated principal and owns all validation: the
company comes from the principal, linked rows are loaded within that company
(another tenant's row is a 404), the branch, path and base commit are
generated server-side, and lifecycle moves follow ``TRANSITIONS`` with the
approval and head-commit checks. Refusals are ``WorktreeError``, an
``HTTPException`` carrying the status for its reason.

Request bodies forbid unknown fields, so a client cannot send ``company_id``,
``branch``, ``relative_path``, ``status``, ``head_commit`` or ``created_by`` and
have it silently dropped. Responses carry the stored relative path only, never
the absolute directory.

The service does the git work: activating creates the worktree on disk, review
and refresh read its head from git, and merging merges in git. Nothing here
deletes a worktree or branch; archiving changes the status alone. Mutations are
audited with the principal as actor before the commit, and an audit write that
fails rolls the row change back. Git and the database share no transaction: if
the row change cannot be saved after git changed, the response is a 500 that
says so, and retrying the same request reconciles the row with git.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nexus.api.deps import CurrentPrincipal, DbSession, require_permission
from nexus.auth.principal import Principal
from nexus.models.agent_worktree import AgentWorktree
from nexus.services.worktree_service import WorktreeService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["worktrees"])

READ = [require_permission("read", "worktree")]
WRITE = [require_permission("write", "worktree")]

WorktreeStatus = Literal["created", "active", "review", "approved", "merged", "archived"]


class WorktreeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_id: uuid.UUID
    agent_id: uuid.UUID
    session_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    approval_id: uuid.UUID | None = None
    # A label resolved to a commit by the service; the resolved id is what is stored.
    base_ref: str = Field(default="HEAD", min_length=1, max_length=256)


class WorktreeTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "created" is only ever the initial status.
    status: Literal["active", "review", "approved", "merged", "archived"]
    approval_id: uuid.UUID | None = None
    # Accepted for compatibility and ignored: the merge commit is the one git
    # produces when the server merges, never a value from the request.
    merged_commit: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _fields_match_target(self) -> WorktreeTransition:
        # The service ignores these for other targets; refuse rather than drop them.
        if self.approval_id is not None and self.status != "approved":
            raise ValueError("approval_id is only accepted when approving")
        if self.merged_commit is not None and self.status != "merged":
            raise ValueError("merged_commit is only accepted when merging")
        return self


class WorktreeOut(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    repository_id: uuid.UUID
    agent_id: uuid.UUID
    session_id: uuid.UUID | None
    task_id: uuid.UUID | None
    branch: str
    base_ref: str
    base_commit: str
    head_commit: str | None
    merged_commit: str | None
    relative_path: str
    status: str
    approval_id: uuid.UUID | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime


def _out(row: AgentWorktree) -> WorktreeOut:
    return WorktreeOut.model_validate(row, from_attributes=True)


async def _audit(
    db: Any, principal: Principal, action: str, row: AgentWorktree, **details: Any
) -> None:
    from nexus.governance.audit_service import record_audit

    await record_audit(
        principal.company_id,
        action,
        actor_type="agent" if principal.kind == "run" else principal.kind,
        actor_id=principal.display_name,
        resource_type="worktree",
        resource_id=str(row.id),
        details={
            "repository_id": str(row.repository_id),
            "agent_id": str(row.agent_id),
            "approval_id": row.approval_id and str(row.approval_id),
            "status": row.status,
            **details,
        },
        db=db,
        raise_on_error=True,
    )


@router.get("/api/v1/worktrees", response_model=list[WorktreeOut], dependencies=READ)
async def list_worktrees(
    principal: CurrentPrincipal,
    db: DbSession,
    repository_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    status_filter: WorktreeStatus | None = Query(default=None, alias="status"),
) -> Any:
    """The caller's company's worktrees, newest first."""
    rows = await WorktreeService(db, principal).list_worktrees(
        repository_id=repository_id,
        agent_id=agent_id,
        session_id=session_id,
        status=status_filter,
    )
    return [_out(r) for r in rows]


@router.post(
    "/api/v1/worktrees",
    status_code=status.HTTP_201_CREATED,
    response_model=WorktreeOut,
    dependencies=WRITE,
)
async def create_worktree(body: WorktreeCreate, principal: CurrentPrincipal, db: DbSession) -> Any:
    """Record a worktree in ``created`` status. Nothing is created on disk."""
    row = await WorktreeService(db, principal).create(**body.model_dump())
    await _audit(
        db, principal, "worktree.created", row, base_commit=row.base_commit, branch=row.branch
    )
    await db.commit()
    return _out(row)


@router.get("/api/v1/worktrees/{worktree_id}", response_model=WorktreeOut, dependencies=READ)
async def get_worktree(worktree_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> Any:
    return _out(await WorktreeService(db, principal).get(worktree_id))


async def _change(
    db: Any,
    principal: Principal,
    worktree_id: uuid.UUID,
    change: Callable[[WorktreeService], Awaitable[AgentWorktree]],
    **details: Any,
) -> AgentWorktree:
    """Apply a lifecycle change, then audit and commit it if the status or head moved.

    By the time the row is saved git may already have changed (a worktree
    created, a branch merged). If saving fails, say so instead of reporting a
    plain error: retrying the same request reconciles the row with git.
    """
    service = WorktreeService(db, principal)
    old = await service.get(worktree_id)
    before, before_head = old.status, old.head_commit
    row = await change(service)
    if (row.status, row.head_commit) == (before, before_head):
        return row  # nothing changed
    if row.status == "archived":
        action = "worktree.archived"
    elif row.status == before:
        action = "worktree.refreshed"
    else:
        action = "worktree.transitioned"
    extra = {k: str(v) for k, v in details.items() if v is not None}
    try:
        await _audit(
            db,
            principal,
            action,
            row,
            previous_status=before,
            previous_head=before_head,
            head_commit=row.head_commit,
            merged_commit=row.merged_commit,
            **extra,
        )
        await db.commit()
    except Exception as exc:
        logger.error(
            "worktree %s: %s -> %s done in git but not saved (merged_commit=%s)",
            worktree_id,
            before,
            row.status,
            row.merged_commit,
            exc_info=True,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Git may already reflect this change, but the worktree record was not saved; "
            "retry the same request to reconcile it",
        ) from exc
    return row


@router.post(
    "/api/v1/worktrees/{worktree_id}/transition",
    response_model=WorktreeOut,
    dependencies=WRITE,
)
async def transition_worktree(
    worktree_id: uuid.UUID, body: WorktreeTransition, principal: CurrentPrincipal, db: DbSession
) -> Any:
    """Move a worktree along its lifecycle. The service decides whether the move is allowed.

    ``merged_commit`` in the body is ignored; the stored value comes from git.
    """
    row = await _change(
        db,
        principal,
        worktree_id,
        lambda s: s.transition(worktree_id, body.status, approval_id=body.approval_id),
        approval_id=body.approval_id,
    )
    return _out(row)


@router.post(
    "/api/v1/worktrees/{worktree_id}/refresh",
    response_model=WorktreeOut,
    dependencies=WRITE,
)
async def refresh_worktree(
    worktree_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> Any:
    """Re-read the head from git. Review or approved work whose head moved returns to active."""
    return _out(await _change(db, principal, worktree_id, lambda s: s.refresh_head(worktree_id)))


@router.post(
    "/api/v1/worktrees/{worktree_id}/archive",
    response_model=WorktreeOut,
    dependencies=WRITE,
)
async def archive_worktree(
    worktree_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> Any:
    """Archive a worktree. Only the status changes; its directory and branch stay."""
    return _out(await _change(db, principal, worktree_id, lambda s: s.archive(worktree_id)))
