"""Agent worktree records: creation, lookup, lifecycle and archive.

``WorktreeService`` is the only writer of ``agent_worktrees``. It works on
database rows and reads git; it never creates, merges or deletes a worktree or
branch on disk. That is a later layer, which runs only after the row exists.

Every call is made for one ``Principal``. The company comes from the
principal, never from a payload, and every linked repository, agent, session,
task and approval is loaded with that company in the WHERE clause, so a row in
another company reads as missing. This is the company-consistency check the
database does not make (see ``nexus.models.agent_worktree``).

Lifecycle::

    created -> active -> review -> approved -> merged -> archived
                 ^         |          |
                 +---------+----------+   (review/approved back to active)

Any non-archived status may also go straight to archived (failure or
abandonment). Archived is terminal. Archiving only changes the status: the
directory and branch are left in place, because an unmerged branch is work.

A worktree is a separate checkout on its own branch, not a sandbox: it gives
no filesystem or process isolation.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.governance.fs_roots import resolve_in_roots
from nexus.models.agent import Agent
from nexus.models.agent_session import ENDED_STATUSES, AgentSessionRecord
from nexus.models.agent_worktree import AgentWorktree
from nexus.models.governance import Approval
from nexus.models.repository import Repository
from nexus.models.task import Task
from nexus.runtime.git_runner import GitError, GitRunner

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "created": ("active", "archived"),
    "active": ("review", "archived"),
    "review": ("active", "approved", "archived"),
    "approved": ("active", "merged", "archived"),
    "merged": ("archived",),
    "archived": (),
}

BRANCH_PREFIX = "nexus/wt-"
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

WorktreeErrorReason = Literal[
    "forbidden",
    "not_found",
    "invalid_link",
    "invalid_repository",
    "unknown_ref",
    "git_unavailable",
    "invalid_path",
    "misconfigured",
    "conflict",
    "illegal_transition",
    "approval_required",
]

_STATUS_FOR: dict[str, int] = {
    "forbidden": status.HTTP_403_FORBIDDEN,
    "not_found": status.HTTP_404_NOT_FOUND,
    "invalid_link": 422,
    "invalid_repository": 422,
    "unknown_ref": status.HTTP_400_BAD_REQUEST,
    "git_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "invalid_path": 422,
    "misconfigured": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "conflict": status.HTTP_409_CONFLICT,
    "illegal_transition": status.HTTP_409_CONFLICT,
    "approval_required": status.HTTP_409_CONFLICT,
}


class WorktreeError(HTTPException):
    """A refused worktree operation. ``reason`` is stable for callers to branch on."""

    def __init__(self, reason: WorktreeErrorReason, detail: str) -> None:
        super().__init__(status_code=_STATUS_FOR[reason], detail=detail)
        self.reason = reason


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def worktree_root(company_id: uuid.UUID) -> Path:
    """The resolved directory ``company_id``'s worktrees live under."""
    template = settings.worktree_root
    if "{company_id}" not in template:
        raise WorktreeError("misconfigured", "worktree_root must contain {company_id}")
    return Path(template.replace("{company_id}", str(company_id))).expanduser().resolve()


def worktree_path(company_id: uuid.UUID, relative_path: str) -> Path:
    """Resolve a stored ``relative_path`` under the company's worktree root.

    Refuses absolute or drive-anchored paths, any ``..`` component, and any
    path that resolves outside the root or onto the root itself. ``resolve()``
    follows symlinks and junctions first, so a link under the root that points
    elsewhere is refused as well.
    """
    rel = PurePath(relative_path)
    if not relative_path or rel.anchor or ".." in rel.parts:
        raise WorktreeError("invalid_path", "Worktree path must be relative to the worktree root")
    root = worktree_root(company_id)
    path = (root / rel).resolve()
    if path == root or not path.is_relative_to(root):
        raise WorktreeError("invalid_path", "Worktree path is outside the worktree root")
    return path


def repository_path(repo: Repository) -> Path:
    """The repository's clone directory, only if it is a git repository inside the roots.

    The clone must have its own ``.git`` directory. Without that check git
    would search parent directories and could run against an unrelated
    repository that happens to contain the roots.
    """
    if not repo.local_path:
        raise WorktreeError("invalid_repository", "Repository has no local clone")
    path = resolve_in_roots(repo.local_path, settings.repository_roots, repo.company_id)
    if path is None:
        raise WorktreeError("invalid_repository", "Repository path is outside the allowed roots")
    if not (path / ".git").is_dir():
        raise WorktreeError("invalid_repository", "Repository path is not a git repository")
    return path


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WorktreeService:
    """Creates, reads and transitions ``AgentWorktree`` rows for one principal.

    Methods flush but do not commit; the caller owns the transaction.
    """

    def __init__(self, db: AsyncSession, principal: Principal) -> None:
        self._db = db
        self._principal = principal
        self._company_id = principal.company_id

    def _require(self, action: str) -> None:
        if not self._principal.has_permission(action, "worktree"):
            raise WorktreeError("forbidden", f"Not allowed to {action} worktrees")

    async def _load(self, model: Any, row_id: uuid.UUID, label: str) -> Any:
        row = (
            await self._db.execute(
                select(model).where(model.id == row_id, model.company_id == self._company_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise WorktreeError("not_found", f"{label} {row_id} not found")
        return row

    # -- create ----------------------------------------------------------------

    async def create(
        self,
        *,
        repository_id: uuid.UUID,
        agent_id: uuid.UUID,
        base_ref: str = "HEAD",
        session_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        approval_id: uuid.UUID | None = None,
    ) -> AgentWorktree:
        """Record a new worktree in ``created`` status.

        The branch name, id and path are generated here. ``base_ref`` is
        resolved to a full commit id before anything is written; the ref text
        itself is kept only as a label.
        """
        self._require("write")
        principal = self._principal
        if principal.kind == "run" and principal.agent_id != agent_id:
            raise WorktreeError("forbidden", "A run may only create worktrees for its own agent")

        repo: Repository = await self._load(Repository, repository_id, "Repository")
        await self._load(Agent, agent_id, "Agent")
        if session_id is not None:
            session: AgentSessionRecord = await self._load(
                AgentSessionRecord, session_id, "Session"
            )
            if session.agent_id != agent_id:
                raise WorktreeError("invalid_link", "Session belongs to a different agent")
            if session.status in ENDED_STATUSES:
                raise WorktreeError("conflict", f"Session is {session.status}")
        if task_id is not None:
            await self._load(Task, task_id, "Task")
        if approval_id is not None:
            await self._load(Approval, approval_id, "Approval")

        try:
            base_commit = await GitRunner(repository_path(repo)).resolve_commit(base_ref)
        except GitError as exc:
            if exc.kind == "invalid_ref":
                raise WorktreeError("unknown_ref", f"Unknown base ref: {base_ref!r}") from exc
            raise WorktreeError("git_unavailable", "Could not read the repository") from exc

        worktree_id = uuid.uuid4()
        relative_path = str(worktree_id)
        worktree_path(self._company_id, relative_path)  # refuse a root that resolves oddly

        row = AgentWorktree(
            id=worktree_id,
            company_id=self._company_id,
            repository_id=repo.id,
            agent_id=agent_id,
            session_id=session_id,
            task_id=task_id,
            approval_id=approval_id,
            branch=f"{BRANCH_PREFIX}{worktree_id}",
            base_ref=base_ref,
            base_commit=base_commit,
            relative_path=relative_path,
            status="created",
            created_by=principal.display_name,
        )
        # The unique constraints decide races between concurrent creators:
        # one branch per repository, one open worktree per session.
        try:
            async with self._db.begin_nested():
                self._db.add(row)
        except IntegrityError as exc:
            raise WorktreeError(
                "conflict", "Conflicts with an existing worktree (branch or open session worktree)"
            ) from exc
        return row

    # -- read ------------------------------------------------------------------

    async def get(self, worktree_id: uuid.UUID) -> AgentWorktree:
        self._require("read")
        return await self._load(AgentWorktree, worktree_id, "Worktree")

    async def list_worktrees(
        self,
        *,
        repository_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[AgentWorktree]:
        """This company's worktrees, newest first, optionally filtered."""
        self._require("read")
        stmt = select(AgentWorktree).where(AgentWorktree.company_id == self._company_id)
        if repository_id is not None:
            stmt = stmt.where(AgentWorktree.repository_id == repository_id)
        if agent_id is not None:
            stmt = stmt.where(AgentWorktree.agent_id == agent_id)
        if session_id is not None:
            stmt = stmt.where(AgentWorktree.session_id == session_id)
        if status is not None:
            stmt = stmt.where(AgentWorktree.status == status)
        stmt = stmt.order_by(AgentWorktree.created_at.desc())
        return list((await self._db.execute(stmt)).scalars())

    def path_of(self, worktree: AgentWorktree) -> Path:
        """Absolute directory of ``worktree``, re-validated under the root."""
        return worktree_path(worktree.company_id, worktree.relative_path)

    # -- lifecycle -------------------------------------------------------------

    async def transition(
        self,
        worktree_id: uuid.UUID,
        to: str,
        *,
        approval_id: uuid.UUID | None = None,
        merged_commit: str | None = None,
    ) -> AgentWorktree:
        """Move a worktree to ``to`` if TRANSITIONS allows it.

        ``approved`` needs a linked approval of this company whose status is
        approved. ``merged`` needs the full id of the merge commit. The write
        is conditional on the status read, so of two racing callers exactly
        one succeeds and the other gets a 409. Re-asserting the current status
        is a no-op.
        """
        self._require("write")
        row: AgentWorktree = await self._load(AgentWorktree, worktree_id, "Worktree")
        current = row.status
        if to == current:
            return row
        if to not in TRANSITIONS.get(current, ()):
            raise WorktreeError(
                "illegal_transition", f"Worktree is {current}; it cannot become {to}"
            )

        values: dict[str, Any] = {"status": to, "updated_at": _utcnow()}
        if to == "approved":
            link = approval_id or row.approval_id
            if link is None:
                raise WorktreeError("approval_required", "Approving a worktree needs an approval")
            approval: Approval = await self._load(Approval, link, "Approval")
            if approval.status != "approved":
                raise WorktreeError("approval_required", f"Approval is {approval.status}")
            values["approval_id"] = link
        if to == "merged":
            if merged_commit is None or not _SHA.fullmatch(merged_commit):
                raise WorktreeError("invalid_link", "merged_commit must be a full commit id")
            values["merged_commit"] = merged_commit

        result = await self._db.execute(
            update(AgentWorktree)
            .where(
                AgentWorktree.id == worktree_id,
                AgentWorktree.company_id == self._company_id,
                AgentWorktree.status == current,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:  # type: ignore[union-attr]
            raise WorktreeError("conflict", "Worktree changed concurrently; reload and retry")
        await self._db.refresh(row)
        return row

    async def archive(self, worktree_id: uuid.UUID) -> AgentWorktree:
        """Archive a worktree. Only the status changes; nothing on disk is deleted."""
        return await self.transition(worktree_id, "archived")
