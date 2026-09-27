"""Agent worktrees: the records and the git worktrees behind them.

``WorktreeService`` is the only writer of ``agent_worktrees`` and the only code
that creates or merges an agent's worktree on disk. Every git call goes
through ``GitRunner`` in the repository's server-side clone.

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
directory, branch and commits are left in place, because an unmerged branch is
work.

What git backs:

* ``created -> active`` creates branch ``nexus/wt-{id}`` at the stored base
  commit and checks it out at ``worktree_path(company_id, relative_path)``.
  Both names were generated when the row was created; nothing from a request
  reaches git. It runs only for a ``created`` row that is already stored.
* ``head_commit`` is only ever read from git, from the repository's own list
  of worktrees, which also shows the worktree is registered and still on its
  own branch. The stored value is a cache of that read, never an input.
* ``-> review`` refuses a worktree with uncommitted changes: an approval
  names a commit and would not cover them.
* ``-> approved`` and ``-> merged`` refuse a worktree whose head in git is no
  longer the recorded head. ``refresh_head`` records the new head and sends
  review or approved work back to active, where it needs a new approval.
* ``-> merged`` merges the approved head into the base branch with
  ``GitRunner.merge_into``: a merge commit written without any checkout and
  published with a compare-and-swap on the branch, so a target that moved is
  refused, not overwritten. ``merged_commit`` is the commit git produced.
* A merge into the branch the clone has checked out first detaches the
  clone's HEAD at the commit its files are from, and records the branch in
  ``refs/nexus/HEAD``. The clone is never checked out: its files and index
  stay as they were and still match its HEAD, so nothing there can commit
  them over the merge. ``HEAD`` as a base ref keeps meaning that branch.

Git and the database do not share a transaction; nothing spans the two. Git
changes first, then the row, and the row write is conditional on the status
that was read, so of two racing callers one wins and the other gets a 409.
Each git step is safe to repeat, so a row write that fails after its git
change is repaired by retrying the same transition: activation reuses the
branch and worktree, and a merge whose commit already landed finds the head
contained in the target and records the target's head.

A worktree is a separate checkout on its own branch, not a sandbox: it gives
no filesystem or process isolation.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePath, PureWindowsPath
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.governance.fs_roots import is_link, pinned_directory, resolve_in_roots
from nexus.models.agent import Agent
from nexus.models.agent_session import ENDED_STATUSES, AgentSessionRecord
from nexus.models.agent_worktree import SESSION_HOLDING_STATUSES, AgentWorktree
from nexus.models.governance import Approval
from nexus.models.repository import Repository
from nexus.models.task import Task
from nexus.runtime.git_runner import GitError, GitRunner, WorktreeEntry

logger = logging.getLogger(__name__)

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "created": ("active", "archived"),
    "active": ("review", "archived"),
    "review": ("active", "approved", "archived"),
    "approved": ("active", "merged", "archived"),
    "merged": ("archived",),
    "archived": (),
}

BRANCH_PREFIX = "nexus/wt-"
# The branch the clone worked on before a merge detached its HEAD.
CLONE_BRANCH_REF = "refs/nexus/HEAD"
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

# Author and committer of the commits the server writes: session-end snapshots
# and merge commits.
GIT_AUTHOR = ("NEXUS", "nexus@localhost")

# Approval.type of a request to approve one worktree at one commit. Its payload
# is {"worktree_id": "<canonical uuid>", "head_commit": "<full commit id>"}.
WORKTREE_APPROVAL_TYPE = "worktree_approval"

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
    # PureWindowsPath also catches C:\x and \\srv\share on POSIX.
    if (
        not relative_path
        or rel.anchor
        or PureWindowsPath(relative_path).anchor
        or ".." in rel.parts
    ):
        raise WorktreeError("invalid_path", "Worktree path must be relative to the worktree root")
    root = worktree_root(company_id)
    path = (root / rel).resolve()
    if path == root or not path.is_relative_to(root):
        raise WorktreeError("invalid_path", "Worktree path is outside the worktree root")
    return path


def _check_not_linked(row: AgentWorktree, path: Path) -> None:
    """Refuse a worktree directory reached through a link.

    Neither the company's directory under the worktree root nor the worktree
    directory may be a symlink or junction, and the directory must still
    resolve to the path generated for the row.
    """
    company_dir = Path(settings.worktree_root.replace("{company_id}", str(row.company_id)))
    if (
        is_link(company_dir.expanduser().absolute())
        or is_link(path)
        or path.resolve() != worktree_root(row.company_id) / row.relative_path
    ):
        raise WorktreeError("invalid_path", "Worktree path passes through a link")


def _claim_directory(row: AgentWorktree, path: Path) -> None:
    """Create the empty directory git checks ``row``'s worktree out into.

    An empty real directory already there is accepted: a racing or an
    interrupted activation leaves one, and git refuses to check out into
    anything else. A file, a link or a directory with contents is refused.
    """
    _check_not_linked(row, path)
    worktree_root(row.company_id).mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError:
        if is_link(path) or not path.is_dir() or any(path.iterdir()):
            raise WorktreeError("invalid_path", "Worktree directory already exists") from None


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
# Git
# ---------------------------------------------------------------------------


@contextmanager
def _git_errors(what: str) -> Iterator[None]:
    """Report a git failure as a 503 without echoing git's output, which holds paths.

    A repository whose own config defines a filter or merge driver is refused
    as an invalid repository: retrying will not help, fixing its config will.
    """
    try:
        yield
    except GitError as exc:
        logger.warning("worktree git call failed (%s): %s %s", what, exc, exc.stderr.strip())
        if exc.kind == "unsafe_config":
            raise WorktreeError("invalid_repository", str(exc)) from exc
        raise WorktreeError("git_unavailable", f"Could not {what}") from exc


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


async def _repository_git(db: AsyncSession, row: AgentWorktree) -> GitRunner:
    """A runner in the clone of ``row``'s repository, loaded in ``row``'s company.

    Every git step starts here, so this is where a row whose branch or path is
    not the one generated from its id is refused: such a row was written
    around the service, and git must not act on the names it carries.
    """
    if row.branch != f"{BRANCH_PREFIX}{row.id}" or row.relative_path != str(row.id):
        raise WorktreeError("conflict", "Worktree record does not match its id")
    repo = (
        await db.execute(
            select(Repository).where(
                Repository.id == row.repository_id, Repository.company_id == row.company_id
            )
        )
    ).scalar_one_or_none()
    if repo is None:
        raise WorktreeError("not_found", f"Repository {row.repository_id} not found")
    with _git_errors("open the repository"):
        return GitRunner(repository_path(repo))


async def _registration(git: GitRunner, row: AgentWorktree) -> WorktreeEntry | None:
    """The repository's own record of a worktree at ``row``'s path, if it has one."""
    path = worktree_path(row.company_id, row.relative_path)
    for entry in await git.list_worktrees():
        if _same_path(entry.path, path):
            return entry
    return None


async def _read_head(git: GitRunner, row: AgentWorktree) -> str:
    """The worktree's head commit, as its repository records it.

    Refuses a worktree the repository does not list at ``row``'s path, one
    whose directory is gone, and one that is detached or on any branch but
    its own. The ``.git`` file inside the worktree is not consulted.
    """
    entry = await _registration(git, row)
    path = worktree_path(row.company_id, row.relative_path)
    if entry is None or entry.prunable or not path.is_dir():
        raise WorktreeError("conflict", "Worktree is missing on disk")
    if entry.branch != f"refs/heads/{row.branch}" or entry.head is None:
        raise WorktreeError("conflict", "Worktree is not on its own branch")
    return entry.head


async def _worktree_git(git: GitRunner, row: AgentWorktree) -> GitRunner:
    """A runner inside the worktree, once it is shown to belong to ``git``'s repository.

    The ``.git`` file in a worktree is writable by whatever works there.
    Before git runs in that directory, the repository it names must be this
    one, so a forged file cannot point git at another repository.
    """
    wt = GitRunner(worktree_path(row.company_id, row.relative_path))
    if not _same_path(await wt.common_dir(), git.path / ".git"):
        raise WorktreeError("conflict", "Worktree does not belong to its repository")
    return wt


async def _snapshot(
    db: AsyncSession, row: AgentWorktree, *, commit_changes: bool
) -> tuple[str, bool]:
    """Read the worktree's head, first committing uncommitted changes if asked.

    Returns the head and whether a commit was made. Without
    ``commit_changes`` a worktree with uncommitted changes is refused. A
    commit lands on the worktree's own branch only.
    """
    git = await _repository_git(db, row)
    with _git_errors("read the worktree"):
        head = await _read_head(git, row)
        wt = await _worktree_git(git, row)
        if not (await wt.status_porcelain()).strip():
            return head, False
    if not commit_changes:
        raise WorktreeError("conflict", "Worktree has uncommitted changes; commit them first")
    with _git_errors("commit the worktree's changes"):
        await wt.stage_all()
        await wt.commit(f"Work left in worktree {row.id} when its session ended", author=GIT_AUTHOR)
        return await _read_head(git, row), True


async def _cas(
    db: AsyncSession, row: AgentWorktree, expected: str, values: dict[str, Any], *conditions: Any
) -> None:
    """Write ``values`` only if the row is still ``expected`` (and meets ``conditions``).

    Of two racing writers exactly one matches; the other gets a 409. A write
    that would leave a session holding two worktrees is refused by the
    partial unique index.
    """
    try:
        async with db.begin_nested():
            result = await db.execute(
                update(AgentWorktree)
                .where(
                    AgentWorktree.id == row.id,
                    AgentWorktree.company_id == row.company_id,
                    AgentWorktree.status == expected,
                    *conditions,
                )
                .values(updated_at=_utcnow(), **values)
                .execution_options(synchronize_session=False)
            )
    except IntegrityError as exc:
        raise WorktreeError("conflict", "The session already holds an open worktree") from exc
    if result.rowcount != 1:  # type: ignore[union-attr]
        # Tell the loser what it lost to, when the status is what moved.
        now = await db.scalar(
            select(AgentWorktree.status).where(
                AgentWorktree.id == row.id, AgentWorktree.company_id == row.company_id
            )
        )
        if now is not None and now != expected:
            raise WorktreeError("conflict", f"Worktree is now {now}; reload and retry")
        raise WorktreeError("conflict", "Worktree changed concurrently; reload and retry")
    await db.refresh(row)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def check_worktree_approval(
    approval: Approval, worktree: AgentWorktree, now: datetime | None = None
) -> None:
    """Refuse unless ``approval`` approves exactly ``worktree`` at its current head.

    The approval must belong to the worktree's company, be decided
    ``approved``, be of :data:`WORKTREE_APPROVAL_TYPE`, and not have expired
    (``expires_at`` unset or later than ``now``, naive UTC). Its payload must
    be an object whose ``worktree_id`` is the worktree's id in canonical form
    and whose ``head_commit`` is the worktree's current ``head_commit``, a full
    commit id. Comparisons are exact: no case folding, no abbreviated ids, no
    braces or ``urn:`` forms, no values nested elsewhere in the payload. The
    payload is set when the approval is requested and nothing rewrites it, so
    what the approver approved is this worktree at this commit; once the head
    moves, the approval no longer matches.

    The approval must also have been decided by someone other than the
    principal who created the worktree. An approval records its requester
    only as an agent id supplied by the client, so the worktree's creator is
    the trustworthy stand-in for "who is asking".
    """
    if approval.company_id != worktree.company_id:
        # Callers load the approval company-scoped; this holds if one does not.
        raise WorktreeError("not_found", "Approval not found")
    if approval.status != "approved":
        raise WorktreeError("approval_required", f"Approval is {approval.status}")
    if approval.type != WORKTREE_APPROVAL_TYPE:
        raise WorktreeError("approval_required", "Approval is not a worktree approval")
    expires_at = approval.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone(UTC).replace(tzinfo=None)
        if expires_at <= (now or _utcnow()):
            raise WorktreeError("approval_required", "Approval has expired")
    payload = approval.payload
    if not isinstance(payload, dict):
        raise WorktreeError("approval_required", "Approval payload is not an object")
    named = payload.get("worktree_id")
    if not isinstance(named, str) or named != str(worktree.id):
        raise WorktreeError("approval_required", "Approval is for a different worktree")
    head = worktree.head_commit
    if head is None or not _SHA.fullmatch(head):
        raise WorktreeError("approval_required", "Worktree has no recorded head commit")
    approved_head = payload.get("head_commit")
    if not isinstance(approved_head, str) or approved_head != head:
        raise WorktreeError("approval_required", "Approval is for a different head commit")
    if not approval.decided_by or approval.decided_by == worktree.created_by:
        raise WorktreeError(
            "approval_required", "Approval must be decided by someone other than its requester"
        )


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
            git = GitRunner(repository_path(repo))
            ref = base_ref
            if base_ref == "HEAD":
                ref = await _clone_branch(git) or base_ref
            base_commit = await git.resolve_commit(ref)
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
        self, worktree_id: uuid.UUID, to: str, *, approval_id: uuid.UUID | None = None
    ) -> AgentWorktree:
        """Move a worktree to ``to`` if TRANSITIONS allows it.

        ``active`` from ``created`` creates the worktree on disk. ``review``
        reads the head from git and refuses uncommitted changes. ``approved``
        needs git's head to still be the recorded head and an approval of this
        company that passes :func:`check_worktree_approval` for it. ``merged``
        merges in git and records the commit git made. Every row write is
        conditional on the status read, so of two racing callers exactly one
        succeeds and the other gets a 409. Re-asserting the current status is
        a no-op.
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
        if current == "created" and to == "active":
            await self._activate(row)
        elif to == "review":
            head, _ = await _snapshot(self._db, row, commit_changes=False)
            await _cas(self._db, row, current, {"status": "review", "head_commit": head})
        elif to == "approved":
            await self._approve(row, approval_id or row.approval_id)
        elif to == "merged":
            await self._merge(row)
        else:
            await _cas(self._db, row, current, {"status": to})
        return row

    async def archive(self, worktree_id: uuid.UUID) -> AgentWorktree:
        """Archive a worktree. Only the status changes; nothing on disk is deleted."""
        return await self.transition(worktree_id, "archived")

    async def refresh_head(self, worktree_id: uuid.UUID) -> AgentWorktree:
        """Re-read the head from git and store it.

        Review or approved work whose head moved goes back to active: what was
        reviewed or approved is no longer what is there, and it needs a new
        approval. Other statuses have no live head and are returned unchanged.
        """
        self._require("write")
        row: AgentWorktree = await self._load(AgentWorktree, worktree_id, "Worktree")
        if row.status not in ("active", "review", "approved"):
            return row
        git = await _repository_git(self._db, row)
        with _git_errors("read the worktree"):
            head = await _read_head(git, row)
        if head == row.head_commit:
            return row
        values: dict[str, Any] = {"head_commit": head}
        if row.status != "active":
            values["status"] = "active"
        await _cas(self._db, row, row.status, values, AgentWorktree.head_commit == row.head_commit)
        return row

    async def _activate(self, row: AgentWorktree) -> None:
        """Create the branch and worktree of a stored ``created`` row, then mark it active.

        Repeatable: a branch still at the base commit and a worktree already
        registered at the row's path are reused, so a retry after a failed row
        write, or a second activation racing this one, finds them in place.
        The conditional row write decides which activation wins.
        """
        git = await _repository_git(self._db, row)
        path = worktree_path(row.company_id, row.relative_path)
        with _git_errors("create the worktree"):
            if await git.resolve_commit(row.base_commit) != row.base_commit:
                raise WorktreeError("conflict", "Base commit is not in the repository")
            await git.check_branch_name(row.branch)
            if await _registration(git, row) is None:
                branch_head = await _branch_head(git, row.branch)
                if branch_head is None:
                    try:
                        await git.create_branch(row.branch, row.base_commit)
                        branch_head = row.base_commit
                    except GitError:
                        # Another activation created it first, or it is taken.
                        branch_head = await _branch_head(git, row.branch)
                if branch_head != row.base_commit:
                    raise WorktreeError("conflict", "Worktree branch exists at another commit")
                _claim_directory(row, path)
                try:
                    # Held open so the checked path cannot be swapped for a
                    # link between the check and git writing into it.
                    with pinned_directory(path):
                        _check_not_linked(row, path)
                        await git.add_worktree(path, row.branch)
                except OSError as exc:
                    raise WorktreeError(
                        "invalid_path", "Worktree directory changed while it was being created"
                    ) from exc
                except GitError:
                    if await _registration(git, row) is None:
                        raise
            head = await _read_head(git, row)
        await _cas(self._db, row, "created", {"status": "active", "head_commit": head})

    async def _approve(self, row: AgentWorktree, link: uuid.UUID | None) -> None:
        if link is None:
            raise WorktreeError("approval_required", "Approving a worktree needs an approval")
        approval: Approval = await self._load(Approval, link, "Approval")
        check_worktree_approval(approval, row)
        git = await _repository_git(self._db, row)
        with _git_errors("read the worktree"):
            if await _read_head(git, row) != row.head_commit:
                raise WorktreeError("conflict", "Worktree head moved since review; refresh it")
        # The approval was checked against this head; a head that moved since
        # the read must not inherit it.
        await _cas(
            self._db,
            row,
            row.status,
            {"status": "approved", "approval_id": link},
            AgentWorktree.head_commit == row.head_commit,
        )

    async def _merge(self, row: AgentWorktree) -> None:
        """Merge the approved head into the base branch and record the commit git made.

        In order: the approval still passes for the recorded head; git's head
        is that recorded head; the target branch still contains the base
        commit. The merge commit is written without a checkout and published
        only if the target has not moved since it was read. A conflict or a
        moved target changes nothing and is a 409.
        """
        link = row.approval_id
        if link is None:
            raise WorktreeError("approval_required", "Worktree has no approval")
        approval: Approval = await self._load(Approval, link, "Approval")
        check_worktree_approval(approval, row)
        head = row.head_commit
        if head == row.base_commit:
            # Nothing to merge; recording "merged" would claim work that is not there.
            raise WorktreeError("conflict", "Worktree has no commits past its base; archive it")
        git = await _repository_git(self._db, row)
        with _git_errors("merge the worktree"):
            if await _read_head(git, row) != head:
                raise WorktreeError(
                    "conflict", "Worktree head moved since it was approved; refresh it"
                )
            target = await _merge_target(git, row)
            target_head = await git.resolve_commit(f"refs/heads/{target}")
            if not await git.is_ancestor(row.base_commit, target_head):
                raise WorktreeError("conflict", f"{target} no longer contains the worktree's base")
            message = (
                f"Merge worktree {row.id} into {target}\n\nBranch: {row.branch}\nApproval: {link}\n"
            )
            try:
                await _detach_clone(git, target, target_head)
                outcome = await git.merge_into(
                    target, head, target_head, message, author=GIT_AUTHOR
                )
            except GitError as exc:
                if exc.kind != "stale_ref":
                    raise
                raise WorktreeError("conflict", f"{target} moved during the merge; retry") from exc
        if outcome.status == "conflict" or outcome.commit is None:
            raise WorktreeError(
                "conflict", f"Merge into {target} conflicts in {len(outcome.conflicts)} path(s)"
            )
        # up_to_date: the head is already in the target, as on a retry after
        # the row write failed. No new commit is made; the target's head, which
        # contains the approved head, is recorded as the commit that holds it.
        merged = outcome.commit
        try:
            await _cas(
                self._db,
                row,
                "approved",
                {"status": "merged", "merged_commit": merged},
                AgentWorktree.head_commit == head,
                AgentWorktree.approval_id == link,
            )
        except WorktreeError as exc:
            logger.error(
                "worktree %s merged into %s as %s but its row was not updated",
                row.id,
                target,
                merged,
            )
            raise WorktreeError(
                "conflict",
                f"Merged into {target} as {merged}, but the worktree changed concurrently; "
                "reload it",
            ) from exc


async def _branch_head(git: GitRunner, branch: str) -> str | None:
    try:
        return await git.resolve_commit(f"refs/heads/{branch}")
    except GitError as exc:
        if exc.kind != "invalid_ref":
            raise
        return None


async def _clone_branch(git: GitRunner) -> str | None:
    """The branch the clone works on, as a full ref, or None if there is none.

    That is the branch it has checked out or, once a merge detached the
    clone's HEAD, the branch recorded in ``CLONE_BRANCH_REF``.
    """
    return await git.current_branch() or await git.symbolic_ref(CLONE_BRANCH_REF)


async def _detach_clone(git: GitRunner, target: str, target_head: str) -> None:
    """Keep a merge into ``target`` from leaving a checkout behind its branch.

    ``merge_into`` moves the branch without touching any working tree. A
    checkout of that branch would be left with the old files and index under
    the new commit, and the next commit made there would undo the merge. So
    the clone, if it has ``target`` checked out, is detached at
    ``target_head``, the commit its files are from, and ``target`` is
    recorded in ``CLONE_BRANCH_REF``. Only HEAD moves. A worktree the service
    does not own with ``target`` checked out is not the service's to change,
    and the merge is refused.
    """
    ref = f"refs/heads/{target}"
    for entry in await git.list_worktrees():
        if entry.branch != ref:
            continue
        if not _same_path(entry.path, git.path):
            raise WorktreeError("conflict", f"{target} is checked out in another worktree")
        await git.set_symbolic_ref(CLONE_BRANCH_REF, target)
        await git.detach_head(target_head)


async def _merge_target(git: GitRunner, row: AgentWorktree) -> str:
    """The branch a worktree merges into: the branch its ``base_ref`` names.

    ``HEAD`` means the branch the clone works on (see ``_clone_branch``). A tag, a commit
    id or another worktree's branch is refused: there is no branch to merge
    into, or not one to merge into.
    """
    name = row.base_ref
    if name == "HEAD":
        ref = await _clone_branch(git)
        if ref is None:
            raise WorktreeError("conflict", "Repository HEAD is not on a branch")
        name = ref
    name = name.removeprefix("refs/heads/")
    try:
        await git.check_branch_name(name)
    except GitError as exc:
        if exc.kind != "invalid_ref":
            raise
        raise WorktreeError("conflict", "Worktree base is not a branch") from exc
    if name.startswith(BRANCH_PREFIX):
        raise WorktreeError("conflict", "Worktree base is another worktree's branch")
    if await _branch_head(git, name) is None:
        raise WorktreeError("conflict", "Worktree base is not a branch")
    return name


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


async def held_worktree(
    db: AsyncSession, company_id: uuid.UUID, session_id: uuid.UUID
) -> AgentWorktree | None:
    """The ``created`` or ``active`` worktree the session holds, if any."""
    return (
        await db.execute(
            select(AgentWorktree).where(
                AgentWorktree.company_id == company_id,
                AgentWorktree.session_id == session_id,
                AgentWorktree.status.in_(SESSION_HOLDING_STATUSES),
            )
        )
    ).scalar_one_or_none()


async def session_workspace(
    db: AsyncSession, company_id: uuid.UUID, agent_id: uuid.UUID, session_id: uuid.UUID
) -> Path | None:
    """The directory work in this session must run in, or None if it holds no worktree.

    Called by the execution path after the session and agent were
    authorized; it grants nothing. A worktree still ``created`` is refused
    until it is activated, and one git does not show registered on its own
    branch in its repository is refused, so work never falls back to some
    other directory.
    """
    row = await held_worktree(db, company_id, session_id)
    if row is None:
        return None
    if row.agent_id != agent_id:
        raise WorktreeError("forbidden", "The session's worktree belongs to another agent")
    if row.status != "active":
        raise WorktreeError("conflict", "Activate the session's worktree before running work")
    git = await _repository_git(db, row)
    with _git_errors("read the worktree"):
        await _read_head(git, row)
        await _worktree_git(git, row)
    return worktree_path(row.company_id, row.relative_path)


async def release_session_worktree(db: AsyncSession, record: AgentSessionRecord) -> None:
    """Let go of the worktree a session held, when that session ends.

    A ``created`` worktree never had work in it and is archived. An
    ``active`` one has its uncommitted changes committed to its own branch
    and its head read from git: with commits past its base it goes to review,
    otherwise it is archived. Either way the session stops holding it. If git
    fails the worktree stays active and unheld for a person to look at;
    ending the session is never blocked by it. Nothing is merged or deleted.

    Runs because an authorized caller ended the session, and is audited as a
    system action in the session's company. Flushes; the caller commits.
    """
    from nexus.governance.audit_service import record_audit

    if record.status not in ENDED_STATUSES:
        return
    row = await held_worktree(db, record.company_id, record.id)
    if row is None:
        return
    before = row.status
    values: dict[str, Any] = {"session_id": None}
    committed = False
    error: str | None = None
    if before == "created":
        values["status"] = "archived"
    else:
        from nexus.adapters.cli_adapter import recover_instruction_files

        # An instruction file a killed CLI run left behind is not work.
        recover_instruction_files(worktree_path(row.company_id, row.relative_path))
        try:
            head, committed = await _snapshot(db, row, commit_changes=True)
        except WorktreeError as exc:
            error = str(exc.detail)
            logger.warning("worktree %s left active at session end: %s", row.id, error)
        else:
            values["head_commit"] = head
            values["status"] = "review" if head != row.base_commit else "archived"
    try:
        await _cas(db, row, before, values)
    except WorktreeError as exc:
        logger.warning("worktree %s changed while its session ended; left as is", row.id)
        if not committed:
            return
        # The session-end commit is on the worktree's branch; keep it on record.
        await db.refresh(row)
        error = str(exc.detail)
    await record_audit(
        record.company_id,
        "worktree.released",
        actor_type="system",
        resource_type="worktree",
        resource_id=str(row.id),
        details={
            "session_id": str(record.id),
            "previous_status": before,
            "status": row.status,
            "head_commit": values.get("head_commit", row.head_commit),
            "committed_changes": committed,
            "error": error,
        },
        db=db,
    )
