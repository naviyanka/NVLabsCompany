"""Git repository CRUD endpoints."""

import uuid
from datetime import timezone, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.repository import Repository

router = APIRouter(tags=["repositories"])


class RepoCreate(BaseModel):
    name: str
    url: str
    provider: str = "github"
    default_branch: str = "main"
    description: str | None = None
    language: str | None = None


class RepoUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_branch: str | None = None
    is_active: bool | None = None


class RepoResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    url: str
    provider: str
    default_branch: str
    description: str | None
    language: str | None
    is_active: bool
    last_synced_at: datetime | None
    stats: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@router.get("/api/v1/companies/{company_id}/repos", response_model=list[RepoResponse])
async def list_repos(company_id: uuid.UUID, db: DbSession, limit: int = 50) -> Any:
    """List connected repositories."""
    stmt = select(Repository).where(Repository.company_id == company_id).order_by(Repository.updated_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/api/v1/companies/{company_id}/repos", status_code=status.HTTP_201_CREATED, response_model=RepoResponse)
async def connect_repo(company_id: uuid.UUID, body: RepoCreate, db: DbSession) -> Any:
    """Connect a new repository."""
    repo = Repository(
        company_id=company_id,
        name=body.name,
        url=body.url,
        provider=body.provider,
        default_branch=body.default_branch,
        description=body.description,
        language=body.language,
    )
    db.add(repo)
    await db.flush()
    return repo


@router.get("/api/v1/repos/{repo_id}", response_model=RepoResponse)
async def get_repo(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get repository detail."""
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.put("/api/v1/repos/{repo_id}", response_model=RepoResponse)
async def update_repo(repo_id: uuid.UUID, body: RepoUpdate, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Update repository settings."""
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    updates = body.model_dump(exclude_unset=True)
    updates["updated_at"] = datetime.now(timezone.utc)
    for k, v in updates.items():
        setattr(repo, k, v)
    await db.flush()
    return repo


@router.delete("/api/v1/repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_repo(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Disconnect (delete) a repository."""
    from sqlalchemy import delete as sa_delete
    stmt = sa_delete(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    await db.execute(stmt)


@router.post("/api/v1/repos/{repo_id}/sync")
async def sync_repo(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict:
    """Trigger a repository sync (fetch latest commits/PRs)."""
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    repo.last_synced_at = datetime.now(timezone.utc)
    await db.flush()
    return {"repo_id": str(repo_id), "synced_at": repo.last_synced_at.isoformat()}



# ---------------------------------------------------------------------------
# Repository Stats and Placeholder Data Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/v1/companies/{company_id}/repos/stats")
async def get_repo_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
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


@router.get("/api/v1/repos/{repo_id}/commits")
async def get_repo_commits(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> list[dict[str, Any]]:
    """Return placeholder commit list for a repository."""
    import hashlib

    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Generate deterministic sample commits based on repo name
    seed = repo.name
    commits = []
    messages = [
        "Initial project setup",
        "Add authentication module",
        "Fix database connection pooling",
        "Update dependencies to latest versions",
        "Refactor API handlers for clarity",
        "Add unit tests for core service",
        "Implement caching layer",
        "Fix race condition in worker queue",
        "Update README with deployment guide",
        "Performance optimization for search queries",
    ]
    authors = ["alice", "bob", "charlie", "diana", "eve"]

    for i in range(10):
        sha_input = f"{seed}-{i}".encode()
        sha = hashlib.sha256(sha_input).hexdigest()[:7]
        commits.append({
            "sha": sha,
            "message": messages[i],
            "author": authors[i % len(authors)],
            "date": (datetime.now(timezone.utc) - timedelta(days=10 - i)).isoformat(),
        })

    return commits


@router.get("/api/v1/repos/{repo_id}/pull-requests")
async def get_repo_pull_requests(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> list[dict[str, Any]]:
    """Return placeholder PR list for a repository."""
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    prs = [
        {"id": 1, "title": "Add input validation layer", "status": "open", "author": "alice", "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
        {"id": 2, "title": "Refactor database models", "status": "merged", "author": "bob", "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()},
        {"id": 3, "title": "Fix memory leak in worker", "status": "open", "author": "charlie", "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()},
        {"id": 4, "title": "Update CI/CD pipeline config", "status": "closed", "author": "diana", "created_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()},
        {"id": 5, "title": "Implement rate limiting middleware", "status": "merged", "author": "eve", "created_at": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()},
    ]
    return prs


@router.get("/api/v1/repos/{repo_id}/contributors")
async def get_repo_contributors(repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> list[dict[str, Any]]:
    """Return placeholder contributors list for a repository."""
    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    contributors = [
        {"name": "Alice Chen", "commits_count": 142, "avatar_url": "https://api.dicebear.com/7.x/initials/svg?seed=AC"},
        {"name": "Bob Martinez", "commits_count": 98, "avatar_url": "https://api.dicebear.com/7.x/initials/svg?seed=BM"},
        {"name": "Charlie Kim", "commits_count": 76, "avatar_url": "https://api.dicebear.com/7.x/initials/svg?seed=CK"},
        {"name": "Diana Patel", "commits_count": 54, "avatar_url": "https://api.dicebear.com/7.x/initials/svg?seed=DP"},
        {"name": "Eve Johnson", "commits_count": 31, "avatar_url": "https://api.dicebear.com/7.x/initials/svg?seed=EJ"},
    ]
    return contributors



@router.get("/api/v1/repos/{repo_id}/tree")
async def get_repo_file_tree(
    repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId,
    path: str = "", depth: int = 3
) -> dict[str, Any]:
    """Get the file tree of a repository for the file explorer.

    Reads the actual filesystem at the repo's local_path and returns
    a nested tree structure up to the specified depth.
    """
    from nexus.models.repository import Repository
    from pathlib import Path as FsPath

    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    base_path = FsPath(repo.local_path) if hasattr(repo, "local_path") and repo.local_path else FsPath(".")
    target = base_path / path if path else base_path

    if not target.exists():
        return {"path": path, "entries": [], "error": "Path not found"}

    def _scan_dir(dir_path: FsPath, current_depth: int) -> list[dict[str, Any]]:
        if current_depth > depth:
            return []
        entries = []
        try:
            for item in sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if item.name.startswith(".") and item.name not in (".github", ".kiro"):
                    continue
                if item.name in ("node_modules", "__pycache__", ".git", "venv", ".venv", "dist"):
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


@router.get("/api/v1/repos/{repo_id}/diff")
async def get_repo_diff(
    repo_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId,
    base: str = "HEAD~1", target: str = "HEAD"
) -> dict[str, Any]:
    """Get git diff between two refs for the diff viewer.

    Runs `git diff base..target` on the repository's local path.
    """
    import asyncio
    from nexus.models.repository import Repository
    from pathlib import Path as FsPath

    stmt = select(Repository).where(Repository.id == repo_id, Repository.company_id == company_id)
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = repo.local_path if hasattr(repo, "local_path") and repo.local_path else "."

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", f"{base}..{target}", "--stat",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        # Also get the full diff (limited to 50KB)
        proc_full = await asyncio.create_subprocess_exec(
            "git", "diff", f"{base}..{target}",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        full_stdout, _ = await proc_full.communicate()

        return {
            "repo_id": str(repo_id),
            "base": base,
            "target": target,
            "stat": stdout.decode("utf-8", errors="replace")[:5000],
            "diff": full_stdout.decode("utf-8", errors="replace")[:50000],
            "truncated": len(full_stdout) > 50000,
        }
    except FileNotFoundError:
        return {"error": "git not found on PATH", "base": base, "target": target}
    except Exception as e:
        return {"error": str(e), "base": base, "target": target}
