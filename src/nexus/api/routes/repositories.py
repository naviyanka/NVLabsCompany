"""Git repository CRUD endpoints.

Reading a repository needs ``read:repository``. Connecting, changing, syncing
or removing one needs ``write:repository``, which only administrators hold,
because a repository record points git at a directory on the server.

A clone's ``local_path`` must resolve inside ``settings.repository_roots``. The
path is checked when it is written (422) and again every time it is used
(409), so a row written before the roots existed is refused rather than
trusted. Nothing is moved or rewritten automatically.
"""

import uuid
from datetime import timezone, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession, PathCompanyId, require_permission
from nexus.config import settings
from nexus.governance.fs_roots import resolve_in_roots
from nexus.models.repository import Repository
from nexus.runtime.git_runner import GitError, GitRunner

router = APIRouter(tags=["repositories"])

READ = [require_permission("read", "repository")]
# No standard role grants write:repository, so only the admin wildcard passes.
WRITE = [require_permission("write", "repository")]


def _checked_local_path(raw: str, company_id: uuid.UUID) -> str:
    """Resolve a caller-supplied clone path, or 422 if it is outside the roots."""
    path = resolve_in_roots(raw, settings.repository_roots, company_id)
    if path is None:
        raise HTTPException(
            status_code=422,
            detail="local_path is outside the allowed repository roots",
        )
    return str(path)


def _clone_path(repo: Repository) -> Path | None:
    """Return the repository's clone directory, or None when none is configured.

    Raises 409 when the stored path is outside the roots: such a row predates
    the roots or was written around them, and git must not run there.
    """
    if not repo.local_path:
        return None
    path = resolve_in_roots(repo.local_path, settings.repository_roots, repo.company_id)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This repository's local_path is outside the allowed repository roots. "
                "Re-register the clone under a configured root."
            ),
        )
    return path


def _git_http_error(err: GitError) -> HTTPException | None:
    """Map a refused ref or a timeout to an HTTP error; other failures stay in-band."""
    if err.kind == "invalid_ref":
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
    if err.kind == "timeout":
        return HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="git timed out")
    return None


class RepoCreate(BaseModel):
    name: str
    url: str
    provider: str = "github"
    default_branch: str = "main"
    description: str | None = None
    language: str | None = None
    local_path: str | None = None


class RepoUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_branch: str | None = None
    is_active: bool | None = None
    local_path: str | None = None


class RepoResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    url: str
    provider: str
    default_branch: str
    description: str | None
    language: str | None
    local_path: str | None
    is_active: bool
    last_synced_at: datetime | None
    stats: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@router.get("/api/v1/companies/{company_id}/repos", response_model=list[RepoResponse], dependencies=READ)
async def list_repos(company_id: PathCompanyId, db: DbSession, limit: int = 50) -> Any:
    """List connected repositories."""
    stmt = select(Repository).where(Repository.company_id == company_id).order_by(Repository.updated_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/companies/{company_id}/repos",
    status_code=status.HTTP_201_CREATED,
    response_model=RepoResponse,
    dependencies=WRITE,
)
async def connect_repo(company_id: PathCompanyId, body: RepoCreate, db: DbSession) -> Any:
    """Connect a new repository."""
    local_path = _checked_local_path(body.local_path, company_id) if body.local_path else None
    repo = Repository(
        company_id=company_id,
        name=body.name,
        url=body.url,
        provider=body.provider,
        default_branch=body.default_branch,
        description=body.description,
        language=body.language,
        local_path=local_path,
    )
    db.add(repo)
    await db.flush()
    return repo


@router.get("/api/v1/repos/{repo_id}", response_model=RepoResponse, dependencies=READ)
async def get_repo(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get repository detail."""
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.put("/api/v1/repos/{repo_id}", response_model=RepoResponse, dependencies=WRITE)
async def update_repo(repo_id: uuid.UUID, body: RepoUpdate, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Update repository settings."""
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    updates = body.model_dump(exclude_unset=True)
    if updates.get("local_path"):
        updates["local_path"] = _checked_local_path(updates["local_path"], company_id)
    updates["updated_at"] = datetime.now(timezone.utc)
    for k, v in updates.items():
        setattr(repo, k, v)
    await db.flush()
    return repo


@router.delete("/api/v1/repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=WRITE)
async def disconnect_repo(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Disconnect (delete) a repository.

    Refused with 409 while agent worktrees reference it: worktree records are
    kept as history (archived ones included), so they pin their repository.
    """
    from sqlalchemy import delete as sa_delete

    from nexus.models.agent_worktree import AgentWorktree

    held = await db.scalar(
        select(AgentWorktree.id)
        .where(AgentWorktree.repository_id == repo_id, AgentWorktree.company_id == company_id)
        .limit(1)
    )
    if held is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository has agent worktrees and cannot be deleted",
        )
    stmt = sa_delete(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    await db.execute(stmt)


@router.post("/api/v1/repos/{repo_id}/sync", dependencies=WRITE)
async def sync_repo(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict:
    """Trigger a repository sync (fetch latest commits/PRs).

    A local clone path is required: sync validates the directory exists and is
    a git repository, then records the sync time. Without a clone there is no
    truthful data source to refresh.
    """
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    clone = _clone_path(repo)
    if clone is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No local clone configured. Set local_path on this repository before syncing.",
        )
    if not clone.exists() or not (clone / ".git").exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"local_path '{repo.local_path}' is not an available git clone",
        )

    repo.last_synced_at = datetime.now(timezone.utc)
    await db.flush()
    return {"repo_id": str(repo_id), "synced_at": repo.last_synced_at.isoformat()}



# ---------------------------------------------------------------------------
# Repository Stats and History Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/v1/companies/{company_id}/repos/stats", dependencies=READ)
async def get_repo_stats(company_id: PathCompanyId, db: DbSession) -> dict[str, Any]:
    """Repository statistics for a company."""
    from sqlalchemy import func

    # Total repos
    total_result = await db.execute(
        select(func.count(Repository.id)).where(Repository.company_id == company_id)
    )
    total_repos = total_result.scalar() or 0

    # Active repos
    active_result = await db.execute(
        select(func.count(Repository.id)).where(
            Repository.company_id == company_id, Repository.is_active == True
        )
    )
    active_repos = active_result.scalar() or 0

    # Last sync
    last_sync_result = await db.execute(
        select(func.max(Repository.last_synced_at)).where(Repository.company_id == company_id)
    )
    last_sync = last_sync_result.scalar()

    # Total syncs (count of repos that have been synced at least once)
    synced_result = await db.execute(
        select(func.count(Repository.id)).where(
            Repository.company_id == company_id, Repository.last_synced_at.isnot(None)
        )
    )
    total_syncs = synced_result.scalar() or 0

    return {
        "total_repos": total_repos,
        "active_repos": active_repos,
        "last_sync": last_sync.isoformat() if last_sync else None,
        "total_syncs": total_syncs,
    }


@router.get("/api/v1/repos/{repo_id}/commits", dependencies=READ)
async def get_repo_commits(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> list[dict[str, Any]]:
    """List commits for a repository.

    Returns real git-history data when a local clone path is available on the
    repository record, otherwise an empty list. Fabricated sample data is
    deliberately NOT returned here — clients should render an empty state and
    prompt the user to sync a clone.
    """
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    clone = _clone_path(repo)
    if clone is None or not clone.exists():
        return []

    try:
        stdout = await GitRunner(clone).log(50, "%H%x1f%an%x1f%aI%x1f%s")
    except GitError as err:
        if http := _git_http_error(err):
            raise http from None
        return []

    commits: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            sha, author, date, message = parts
            commits.append({"sha": sha[:12], "message": message, "author": author, "date": date})
    return commits


@router.get("/api/v1/repos/{repo_id}/pull-requests", dependencies=READ)
async def get_repo_pull_requests(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> list[dict[str, Any]]:
    """List pull requests for a repository.

    No forge (GitHub/GitLab) integration exists yet, so there is no truthful
    data source for PRs — an empty list is returned rather than fabricated
    samples.
    """
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    return []


@router.get("/api/v1/repos/{repo_id}/contributors", dependencies=READ)
async def get_repo_contributors(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> list[dict[str, Any]]:
    """List contributors for a repository.

    Derived from real git history when a local clone is available; otherwise an
    empty list. Never returns synthetic authors.
    """
    commits = await get_repo_commits(repo_id, db, company_id)
    counts: dict[str, int] = {}
    for commit in commits:
        counts[commit["author"]] = counts.get(commit["author"], 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"name": name, "commits_count": count}
        for name, count in ranked
    ]



@router.get("/api/v1/repos/{repo_id}/tree", dependencies=READ)
async def get_repo_file_tree(
    repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId,
    path: str = "", depth: int = 3
) -> dict[str, Any]:
    """Get the file tree of a repository for the file explorer.

    Reads the actual filesystem at the repo's local_path and returns
    a nested tree structure up to the specified depth. ``path`` is relative to
    the clone: an absolute path, a ``..`` climb, or a symlink or junction that
    resolves outside the clone is refused with 400. Links met while listing
    are reported as ``symlink`` entries and never followed.
    """
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    base_path = _clone_path(repo)
    if base_path is None:
        return {"path": path, "entries": [], "error": "No local clone configured for this repository"}
    if not base_path.exists():
        return {"path": path, "entries": [], "error": f"Local clone not found at {repo.local_path}"}

    if Path(path).anchor:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="path must be relative to the repository")
    target = (base_path / path).resolve() if path else base_path
    if not target.is_relative_to(base_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="path is outside the repository")

    if not target.exists():
        return {"path": path, "entries": [], "error": "Path not found"}

    def _scan_dir(dir_path: Path, current_depth: int) -> list[dict[str, Any]]:
        if current_depth > depth:
            return []
        entries = []
        try:
            for item in sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if item.name.startswith(".") and item.name not in (".github", ".kiro"):
                    continue
                if item.name in ("node_modules", "__pycache__", ".git", "venv", ".venv", "dist"):
                    continue
                # is_dir(), is_file() and stat() follow links, so a link is
                # classified first and then left alone.
                if item.is_symlink() or item.is_junction():
                    entries.append({
                        "name": item.name,
                        "type": "symlink",
                        "path": str(item.relative_to(base_path)),
                    })
                    continue
                entry: dict[str, Any] = {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "path": str(item.relative_to(base_path)),
                }
                if item.is_file():
                    entry["size"] = item.stat().st_size
                    entry["extension"] = item.suffix
                elif item.is_dir() and current_depth < depth:
                    entry["children"] = _scan_dir(item, current_depth + 1)
                entries.append(entry)
        except PermissionError:
            pass
        return entries

    tree = _scan_dir(target, 1)
    return {"path": path, "repo_id": str(repo_id), "entries": tree}


@router.get("/api/v1/repos/{repo_id}/diff", dependencies=READ)
async def get_repo_diff(
    repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId,
    base: str = "HEAD~1", target: str = "HEAD"
) -> dict[str, Any]:
    """Get git diff between two refs for the diff viewer.

    Both refs are resolved to commit SHAs first (400 if either is malformed or
    unknown), and only the SHAs reach ``git diff``. External diff drivers and
    textconv filters from the repository's config are disabled, since they run
    commands.
    """
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = _clone_path(repo)
    if repo_path is None:
        return {
            "error": "No local clone configured for this repository",
            "base": base,
            "target": target,
        }

    try:
        runner = GitRunner(repo_path)
        stat = await runner.diff(base, target, stat=True)
        # Also get the full diff (limited to 50KB)
        full = await runner.diff(base, target)
    except GitError as err:
        if http := _git_http_error(err):
            raise http from None
        if err.kind == "unavailable":
            return {"error": "git not found on PATH", "base": base, "target": target}
        return {"error": str(err), "base": base, "target": target}
    return {
        "repo_id": str(repo_id),
        "base": base,
        "target": target,
        "stat": stat[:5000],
        "diff": full[:50000],
        "truncated": len(full) > 50000,
    }
