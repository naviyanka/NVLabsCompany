"""P6.5: agent worktrees backed by real git, and the session and CLI paths that use them.

Every test runs ``WorktreeService`` against real repositories created under a
temporary repository root, with worktrees under a temporary worktree root, on
a file SQLite database with foreign keys switched on. Nothing in the git layer
is stubbed except where a test injects one failure on purpose.

Groups: git lifecycle, head from git, approval, merge (including that the
clone's checkout is never touched), concurrency, failure consistency,
execution, security and session release.
"""

import asyncio
import inspect
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401  (registers every table)
from nexus.adapters.claude_code_adapter import ClaudeCodeAdapter
from nexus.adapters.cli_adapter import CLIAdapter
from nexus.api.routes import chat
from nexus.api.routes.sessions import terminate_session
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.agent_worktree import AgentWorktree
from nexus.models.company import Company
from nexus.models.governance import Approval, AuditLog
from nexus.models.repository import Repository
from nexus.runtime.executor import TaskExecutor
from nexus.runtime.git_runner import GitRunner
from nexus.services import worktree_service
from nexus.services.session_service import transition as end_session
from nexus.services.worktree_service import (
    GIT_AUTHOR,
    WORKTREE_APPROVAL_TYPE,
    WorktreeError,
    WorktreeService,
    release_session_worktree,
    session_workspace,
    worktree_path,
)

APPROVER = "approver@example.test"
SRC = Path(__file__).resolve().parents[1] / "src" / "nexus"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(cwd: Path, name: str, text: str, message: str = "change") -> str:
    (cwd / name).write_text(text)
    _git(cwd, "add", name)
    _git(cwd, "commit", "-q", "-m", message)
    return _git(cwd, "rev-parse", "HEAD")


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _commit(path, "shared.txt", "base\n", "init")
    _git(path, "tag", "-a", "v1", "-m", "release")
    return path


def _link_dir(link: Path, target: Path) -> None:
    """Symlink, or on Windows without symlink rights a junction; skip if neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, OSError):
        pytest.skip("neither symlinks nor junctions can be created here")


@pytest.fixture
async def sessions(tmp_path, monkeypatch):
    eng = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'wt.db').as_posix()}")

    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    monkeypatch.setattr(settings, "repository_roots", str(tmp_path / "repos" / "{company_id}"))
    monkeypatch.setattr(settings, "worktree_root", str(tmp_path / "wt" / "{company_id}"))
    yield async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
async def world(sessions, tmp_path):
    """Two companies, each with a git clone, an agent, a second agent and an open session."""
    ids = {}
    async with sessions() as s:
        for key in ("a", "b"):
            company = Company(name=f"co-{key}")
            s.add(company)
            await s.flush()
            clone = _make_repo(tmp_path / "repos" / str(company.id) / "r")
            repo = Repository(company_id=company.id, name="r", url="u", local_path=str(clone))
            agent = Agent(company_id=company.id, name="ag", role="dev")
            other = Agent(company_id=company.id, name="ag2", role="dev")
            s.add_all([repo, agent, other])
            await s.flush()
            session = AgentSessionRecord(company_id=company.id, agent_id=agent.id)
            s.add(session)
            await s.flush()
            ids[key] = {
                "company": company.id,
                "repo": repo.id,
                "clone": clone,
                "agent": agent.id,
                "other_agent": other.id,
                "session": session.id,
                "base": _git(clone, "rev-parse", "HEAD"),
            }
        await s.commit()
    return ids


def _manager(company_id: uuid.UUID) -> Principal:
    return Principal(kind="user", company_id=company_id, role="manager", email="m@example.test")


async def _create(sessions, ids, **kw) -> AgentWorktree:
    async with sessions() as s:
        wt = await WorktreeService(s, _manager(ids["company"])).create(
            repository_id=ids["repo"], agent_id=ids["agent"], **kw
        )
        await s.commit()
        return wt


async def _move(sessions, ids, wt_id, to, **kw) -> AgentWorktree:
    async with sessions() as s:
        row = await WorktreeService(s, _manager(ids["company"])).transition(wt_id, to, **kw)
        await s.commit()
        return row


async def _refresh(sessions, ids, wt_id) -> AgentWorktree:
    async with sessions() as s:
        row = await WorktreeService(s, _manager(ids["company"])).refresh_head(wt_id)
        await s.commit()
        return row


async def _refused(awaitable, *reasons) -> WorktreeError:
    with pytest.raises(WorktreeError) as exc:
        await awaitable
    assert exc.value.reason in reasons, exc.value.detail
    return exc.value


async def _row(sessions, wt_id) -> AgentWorktree:
    async with sessions() as s:
        return await s.get(AgentWorktree, wt_id)


async def _update(sessions, wt_id, **values) -> None:
    async with sessions() as s:
        row = await s.get(AgentWorktree, wt_id)
        for key, value in values.items():
            setattr(row, key, value)
        await s.commit()


async def _approval(sessions, ids, wt_id, head: str) -> uuid.UUID:
    async with sessions() as s:
        row = Approval(
            company_id=ids["company"],
            type=WORKTREE_APPROVAL_TYPE,
            status="approved",
            payload={"worktree_id": str(wt_id), "head_commit": head},
            decided_by=APPROVER,
        )
        s.add(row)
        await s.commit()
        return row.id


def _path(ids, wt: AgentWorktree) -> Path:
    return worktree_path(ids["company"], wt.relative_path)


async def _active(sessions, ids, **kw) -> tuple[AgentWorktree, Path]:
    wt = await _create(sessions, ids, **kw)
    wt = await _move(sessions, ids, wt.id, "active")
    return wt, _path(ids, wt)


async def _reviewed(sessions, ids, name="work.txt", text="work\n", **kw):
    wt, path = await _active(sessions, ids, **kw)
    _commit(path, name, text, "agent work")
    return await _move(sessions, ids, wt.id, "review"), path


async def _approved(sessions, ids, **kw):
    wt, path = await _reviewed(sessions, ids, **kw)
    approval = await _approval(sessions, ids, wt.id, wt.head_commit)
    return await _move(sessions, ids, wt.id, "approved", approval_id=approval), path


def _worktrees(clone: Path) -> list[str]:
    listed = _git(clone, "worktree", "list", "--porcelain")
    return [line for line in listed.splitlines() if line.startswith("worktree ")]


# ── Git lifecycle ────────────────────────────────────────────────────────


async def test_activation_creates_the_branch_and_worktree_from_the_stored_base(sessions, world):
    ids = world["a"]
    clone = ids["clone"]
    wt = await _create(sessions, ids)
    assert not _path(ids, wt).exists()  # created is a record only
    # main moves after the worktree was recorded; activation still uses the base.
    _commit(clone, "later.txt", "later\n")
    wt = await _move(sessions, ids, wt.id, "active")
    path = _path(ids, wt)

    assert wt.branch == f"nexus/wt-{wt.id}"
    assert (
        path
        == (
            Path(settings.worktree_root.replace("{company_id}", str(ids["company"]))) / str(wt.id)
        ).resolve()
    )
    assert _git(clone, "rev-parse", f"refs/heads/{wt.branch}") == ids["base"]
    assert wt.head_commit == ids["base"] == _git(path, "rev-parse", "HEAD")
    assert _git(path, "symbolic-ref", "HEAD") == f"refs/heads/{wt.branch}"
    assert not (path / "later.txt").exists()
    # The clone's own checkout is left alone.
    assert _git(clone, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert _git(clone, "status", "--porcelain") == ""
    assert len(_worktrees(clone)) == 2


async def test_activation_refuses_a_branch_already_at_another_commit(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    other = _commit(ids["clone"], "x.txt", "x\n")
    _git(ids["clone"], "branch", wt.branch, other)
    await _refused(_move(sessions, ids, wt.id, "active"), "conflict")
    assert (await _row(sessions, wt.id)).status == "created"
    assert not _path(ids, wt).exists()


async def test_activation_refuses_an_existing_directory(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    path = _path(ids, wt)
    path.mkdir(parents=True)
    (path / "planted.txt").write_text("x")
    await _refused(_move(sessions, ids, wt.id, "active"), "invalid_path")
    assert (await _row(sessions, wt.id)).status == "created"
    assert len(_worktrees(ids["clone"])) == 1


async def test_archive_deletes_nothing(sessions, world):
    ids = world["a"]
    wt, path = await _reviewed(sessions, ids)
    wt = await _move(sessions, ids, wt.id, "archived")
    assert wt.status == "archived"
    assert (path / "work.txt").exists()
    assert _git(ids["clone"], "rev-parse", f"refs/heads/{wt.branch}") == wt.head_commit
    assert len(_worktrees(ids["clone"])) == 2


# ── Head from git ────────────────────────────────────────────────────────


async def test_review_records_the_head_git_reports(sessions, world):
    ids = world["a"]
    wt, path = await _reviewed(sessions, ids)
    assert wt.status == "review"
    assert wt.head_commit == _git(path, "rev-parse", "HEAD") != ids["base"]


async def test_review_refuses_uncommitted_changes(sessions, world):
    ids = world["a"]
    wt, path = await _active(sessions, ids)
    (path / "loose.txt").write_text("not committed\n")
    await _refused(_move(sessions, ids, wt.id, "review"), "conflict")
    row = await _row(sessions, wt.id)
    assert row.status == "active" and row.head_commit == ids["base"]


async def test_a_head_forged_in_the_database_is_never_approved(sessions, world):
    ids = world["a"]
    wt, path = await _reviewed(sessions, ids)
    real = wt.head_commit
    forged = _commit(ids["clone"], "main-only.txt", "x\n")  # a real commit, just not this head
    await _update(sessions, wt.id, head_commit=forged)
    approval = await _approval(sessions, ids, wt.id, forged)
    err = await _refused(_move(sessions, ids, wt.id, "approved", approval_id=approval), "conflict")
    assert "moved since review" in err.detail
    # Refreshing puts git's head back and sends the work back to active.
    row = await _refresh(sessions, ids, wt.id)
    assert (row.status, row.head_commit) == ("active", real)


async def test_callers_cannot_supply_head_base_or_merge_commits():
    params = set(inspect.signature(WorktreeService.transition).parameters)
    params |= set(inspect.signature(WorktreeService.create).parameters)
    params |= set(inspect.signature(WorktreeService.refresh_head).parameters)
    assert not params & {"head_commit", "base_commit", "merged_commit", "branch", "relative_path"}


async def test_refresh_demotes_approved_work_whose_head_moved(sessions, world):
    ids = world["a"]
    wt, path = await _approved(sessions, ids)
    old_head, old_approval = wt.head_commit, wt.approval_id
    new_head = _commit(path, "more.txt", "more\n")
    row = await _refresh(sessions, ids, wt.id)
    assert (row.status, row.head_commit) == ("active", new_head)
    # The old approval named the old head; it cannot approve the new one.
    await _move(sessions, ids, wt.id, "review")
    await _refused(
        _move(sessions, ids, wt.id, "approved", approval_id=old_approval), "approval_required"
    )
    assert old_head != new_head


async def test_approve_refuses_a_head_that_moved_without_a_refresh(sessions, world):
    ids = world["a"]
    wt, path = await _reviewed(sessions, ids)
    approval = await _approval(sessions, ids, wt.id, wt.head_commit)
    _commit(path, "sneaky.txt", "x\n")
    await _refused(_move(sessions, ids, wt.id, "approved", approval_id=approval), "conflict")
    assert (await _row(sessions, wt.id)).status == "review"


async def test_merge_refuses_a_head_that_moved_after_approval(sessions, world):
    ids = world["a"]
    wt, path = await _approved(sessions, ids)
    main_before = _git(ids["clone"], "rev-parse", "main")
    _commit(path, "late.txt", "x\n")
    err = await _refused(_move(sessions, ids, wt.id, "merged"), "conflict")
    assert "moved since it was approved" in err.detail
    assert _git(ids["clone"], "rev-parse", "main") == main_before
    assert (await _row(sessions, wt.id)).status == "approved"


# ── Merge ────────────────────────────────────────────────────────────────


async def test_merge_writes_a_merge_commit_without_touching_any_checkout(sessions, world):
    ids = world["a"]
    clone = ids["clone"]
    wt, path = await _approved(sessions, ids)
    old_main = _git(clone, "rev-parse", "main")
    row = await _move(sessions, ids, wt.id, "merged")

    main = _git(clone, "rev-parse", "main")
    assert row.status == "merged" and row.merged_commit == main
    assert _git(clone, "rev-list", "--parents", "-n", "1", "main").split()[1:] == [
        old_main,
        wt.head_commit,
    ]
    assert _git(clone, "show", "main:work.txt") == "work"
    assert _git(clone, "log", "-1", "--format=%an <%ae>", "main") == "{} <{}>".format(*GIT_AUTHOR)
    # No checkout happened: the clone's files are what they were, and its
    # HEAD is detached at the commit they match (see test_p6_5_hardening).
    assert not (clone / "work.txt").exists()
    assert _git(clone, "rev-parse", "HEAD") == old_main
    assert _git(clone, "status", "--porcelain") == ""
    # The worktree and its branch remain.
    assert (path / "work.txt").exists()
    assert _git(clone, "rev-parse", f"refs/heads/{wt.branch}") == wt.head_commit


async def test_merge_into_a_target_that_moved_cleanly(sessions, world):
    ids = world["a"]
    clone = ids["clone"]
    wt, _ = await _approved(sessions, ids)
    moved = _commit(clone, "other.txt", "other\n")
    row = await _move(sessions, ids, wt.id, "merged")
    parents = _git(clone, "rev-list", "--parents", "-n", "1", "main").split()[1:]
    assert parents == [moved, wt.head_commit]
    assert row.merged_commit == _git(clone, "rev-parse", "main")


async def test_conflicting_merge_changes_nothing(sessions, world):
    ids = world["a"]
    clone = ids["clone"]
    wt, _ = await _approved(sessions, ids, name="shared.txt", text="agent\n")
    main_before = _commit(clone, "shared.txt", "human\n")
    err = await _refused(_move(sessions, ids, wt.id, "merged"), "conflict")
    assert "conflicts" in err.detail
    assert _git(clone, "rev-parse", "main") == main_before
    row = await _row(sessions, wt.id)
    assert row.status == "approved" and row.merged_commit is None


async def test_a_target_that_moves_during_the_merge_is_not_overwritten(
    sessions, world, monkeypatch
):
    ids = world["a"]
    clone = ids["clone"]
    wt, _ = await _approved(sessions, ids)
    real = GitRunner.merge_into
    moved: list[str] = []

    async def racing(self, branch, source, expected_head, message, **kw):
        # Someone else pushes to main after the service read it.
        tree = f"{expected_head}^{{tree}}"
        racer = _git(clone, "commit-tree", tree, "-p", expected_head, "-m", "racer")
        _git(clone, "update-ref", "refs/heads/main", racer)
        moved.append(racer)
        return await real(self, branch, source, expected_head, message, **kw)

    monkeypatch.setattr(GitRunner, "merge_into", racing)
    err = await _refused(_move(sessions, ids, wt.id, "merged"), "conflict")
    assert "moved during the merge" in err.detail
    assert _git(clone, "rev-parse", "main") == moved[0]
    assert _git(clone, "rev-list", "--merges", "--count", "main") == "0"
    assert (await _row(sessions, wt.id)).status == "approved"


async def test_merge_refuses_a_target_rewritten_without_the_base(sessions, world):
    ids = world["a"]
    clone = ids["clone"]
    wt, _ = await _approved(sessions, ids)
    tree = _git(clone, "rev-parse", "main^{tree}")
    orphan = _git(clone, "commit-tree", tree, "-m", "rewritten")
    _git(clone, "update-ref", "refs/heads/main", orphan)
    err = await _refused(_move(sessions, ids, wt.id, "merged"), "conflict")
    assert "no longer contains" in err.detail
    assert _git(clone, "rev-parse", "main") == orphan


@pytest.mark.parametrize("kind", ["tag", "commit", "worktree_branch"])
async def test_merge_needs_a_base_that_is_an_ordinary_branch(sessions, world, kind):
    ids = world["a"]
    if kind == "tag":
        base_ref = "v1"
    elif kind == "commit":
        base_ref = ids["base"]
    else:
        other, _ = await _active(sessions, ids)
        base_ref = other.branch
    wt, _ = await _approved(sessions, ids, base_ref=base_ref)
    main_before = _git(ids["clone"], "rev-parse", "main")
    await _refused(_move(sessions, ids, wt.id, "merged"), "conflict")
    assert _git(ids["clone"], "rev-parse", "main") == main_before
    assert (await _row(sessions, wt.id)).status == "approved"


async def test_merge_into_a_named_branch(sessions, world):
    ids = world["a"]
    clone = ids["clone"]
    _git(clone, "branch", "release")
    wt, _ = await _approved(sessions, ids, base_ref="release")
    main_before = _git(clone, "rev-parse", "main")
    row = await _move(sessions, ids, wt.id, "merged")
    assert row.merged_commit == _git(clone, "rev-parse", "release")
    assert _git(clone, "rev-parse", "main") == main_before


# ── Concurrency ──────────────────────────────────────────────────────────


@pytest.fixture
def serialised_writes(monkeypatch):
    """Commit each row write as it lands, one at a time.

    SQLite locks the whole file for a write until the transaction ends, so two
    open write transactions deadlock where Postgres would make the second wait
    on the row. Committing each conditional write under a lock gives the
    Postgres outcome: the git steps still race freely, and the second write
    sees the first one's status.
    """
    real = worktree_service._cas
    lock = asyncio.Lock()

    async def cas(db, *args, **kw):
        async with lock:
            await real(db, *args, **kw)
            await db.commit()

    monkeypatch.setattr(worktree_service, "_cas", cas)


async def _race(sessions, ids, call):
    """Load the row in two sessions first, then run ``call`` in both at once."""

    async def one(s, svc):
        row = await call(svc)
        await s.commit()
        return row

    async with sessions() as s1, sessions() as s2:
        svcs = [WorktreeService(s, _manager(ids["company"])) for s in (s1, s2)]
        return await asyncio.gather(one(s1, svcs[0]), one(s2, svcs[1]), return_exceptions=True)


def _split(results):
    ok = [r for r in results if isinstance(r, AgentWorktree)]
    lost = [r for r in results if isinstance(r, WorktreeError)]
    assert len(ok) + len(lost) == len(results), results
    return ok, lost


async def test_two_creators_for_one_session_make_one_worktree(sessions, world):
    ids = world["a"]
    results = await asyncio.gather(
        *(_create(sessions, ids, session_id=ids["session"]) for _ in range(2)),
        return_exceptions=True,
    )
    ok, lost = _split(results)
    assert len(ok) == 1 and [e.reason for e in lost] == ["conflict"]


async def test_two_activations_make_one_worktree(sessions, world, serialised_writes):
    ids = world["a"]
    wt = await _create(sessions, ids)
    ok, lost = _split(await _race(sessions, ids, lambda svc: svc.transition(wt.id, "active")))
    assert len(ok) == 1 and len(lost) == 1
    row = await _row(sessions, wt.id)
    assert row.status == "active" and row.head_commit == ids["base"]
    assert len(_worktrees(ids["clone"])) == 2


async def test_two_reviews_one_wins(sessions, world, serialised_writes):
    ids = world["a"]
    wt, path = await _active(sessions, ids)
    head = _commit(path, "work.txt", "work\n")
    ok, lost = _split(await _race(sessions, ids, lambda svc: svc.transition(wt.id, "review")))
    assert len(ok) == 1 and [e.reason for e in lost] == ["conflict"]
    assert (await _row(sessions, wt.id)).head_commit == head


async def test_two_refreshes_one_wins(sessions, world, serialised_writes):
    ids = world["a"]
    wt, path = await _reviewed(sessions, ids)
    head = _commit(path, "more.txt", "more\n")
    ok, lost = _split(await _race(sessions, ids, lambda svc: svc.refresh_head(wt.id)))
    assert len(ok) == 1 and [e.reason for e in lost] == ["conflict"]
    row = await _row(sessions, wt.id)
    assert (row.status, row.head_commit) == ("active", head)


async def test_two_merges_merge_once(sessions, world, serialised_writes):
    ids = world["a"]
    clone = ids["clone"]
    wt, _ = await _approved(sessions, ids)
    ok, lost = _split(await _race(sessions, ids, lambda svc: svc.transition(wt.id, "merged")))
    assert len(ok) == 1 and [e.reason for e in lost] == ["conflict"]
    assert _git(clone, "rev-list", "--merges", "--count", "main") == "1"
    assert (await _row(sessions, wt.id)).merged_commit == _git(clone, "rev-parse", "main")


async def test_a_stale_row_cannot_overwrite_a_newer_one(sessions, world):
    ids = world["a"]
    wt, path = await _reviewed(sessions, ids)
    async with sessions() as slow:
        svc = WorktreeService(slow, _manager(ids["company"]))
        stale = await svc.get(wt.id)  # keep a reference so the identity map holds it
        assert stale.status == "review"
        new_head = _commit(path, "more.txt", "more\n")
        await _refresh(sessions, ids, wt.id)
        # slow still believes "review" at the old head; its write matches nothing.
        await _refused(svc.transition(wt.id, "archived"), "conflict")
    row = await _row(sessions, wt.id)
    assert (row.status, row.head_commit) == ("active", new_head)


# ── Failure consistency ──────────────────────────────────────────────────


def _fail_first_cas(monkeypatch):
    real = worktree_service._cas
    calls = []

    async def cas(*args, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database went away")
        return await real(*args, **kw)

    monkeypatch.setattr(worktree_service, "_cas", cas)


async def test_activation_saved_after_a_failed_row_write_reuses_git_state(
    sessions, world, monkeypatch
):
    ids = world["a"]
    wt = await _create(sessions, ids)
    _fail_first_cas(monkeypatch)
    with pytest.raises(RuntimeError):
        await _move(sessions, ids, wt.id, "active")
    # Git changed; the row did not.
    assert (await _row(sessions, wt.id)).status == "created"
    assert len(_worktrees(ids["clone"])) == 2
    row = await _move(sessions, ids, wt.id, "active")
    assert (row.status, row.head_commit) == ("active", ids["base"])
    assert len(_worktrees(ids["clone"])) == 2


async def test_merge_saved_after_a_failed_row_write_is_not_merged_twice(
    sessions, world, monkeypatch
):
    ids = world["a"]
    clone = ids["clone"]
    wt, _ = await _approved(sessions, ids)
    _fail_first_cas(monkeypatch)
    with pytest.raises(RuntimeError):
        await _move(sessions, ids, wt.id, "merged")
    merge = _git(clone, "rev-parse", "main")
    assert (await _row(sessions, wt.id)).status == "approved"
    row = await _move(sessions, ids, wt.id, "merged")
    assert (row.status, row.merged_commit) == ("merged", merge)
    assert _git(clone, "rev-list", "--merges", "--count", "main") == "1"


async def test_git_failure_changes_no_row(sessions, world, monkeypatch):
    ids = world["a"]
    wt = await _create(sessions, ids)

    async def broken(self, *a, **kw):
        from nexus.runtime.git_runner import GitError

        raise GitError("unavailable", "git is gone")

    monkeypatch.setattr(GitRunner, "add_worktree", broken)
    await _refused(_move(sessions, ids, wt.id, "active"), "git_unavailable")
    assert (await _row(sessions, wt.id)).status == "created"


# ── Execution ────────────────────────────────────────────────────────────


async def _workspace(sessions, ids, company=None, agent=None, session=None):
    async with sessions() as s:
        return await session_workspace(
            s, company or ids["company"], agent or ids["agent"], session or ids["session"]
        )


async def test_session_workspace_is_the_active_worktree(sessions, world):
    ids = world["a"]
    assert await _workspace(sessions, ids) is None  # no worktree held
    wt = await _create(sessions, ids, session_id=ids["session"])
    await _refused(_workspace(sessions, ids), "conflict")  # created: not on disk yet
    await _move(sessions, ids, wt.id, "active")
    assert await _workspace(sessions, ids) == _path(ids, wt)
    await _refused(_workspace(sessions, ids, agent=ids["other_agent"]), "forbidden")
    # Another company's view of the same session holds nothing.
    assert await _workspace(sessions, ids, company=world["b"]["company"]) is None


async def test_session_workspace_refuses_a_missing_directory(sessions, world):
    ids = world["a"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    shutil.rmtree(path)
    await _refused(_workspace(sessions, ids), "conflict")


async def test_session_workspace_refuses_a_switched_branch(sessions, world):
    ids = world["a"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    _git(path, "checkout", "-q", "-b", "elsewhere")
    await _refused(_workspace(sessions, ids), "conflict")


async def test_session_workspace_refuses_a_git_file_pointing_at_another_repository(sessions, world):
    ids = world["a"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    foreign = world["b"]["clone"] / ".git"
    (path / ".git").unlink()  # Windows will not overwrite a hidden file in place
    (path / ".git").write_text(f"gitdir: {foreign.as_posix()}\n")
    await _refused(_workspace(sessions, ids), "conflict", "git_unavailable")


def _fake_process():
    process = AsyncMock()
    process.communicate = AsyncMock(return_value=(b"done\n", b""))
    process.returncode = 0
    return process


async def test_cli_work_runs_in_the_worktree_and_never_in_the_clone(
    sessions, world, tmp_path, monkeypatch
):
    ids = world["a"]
    clone = ids["clone"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    # What chat._call_llm does for a session that holds a worktree. Resolved
    # before the patch below, which would also catch git's own processes.
    workspace = str(await _workspace(sessions, ids))
    seen = {}

    async def spawn(*cmd, cwd=None, **kw):
        seen["cwd"] = cwd
        seen["cmd"] = cmd
        Path(cwd, "agent.txt").write_text("written by the agent\n")
        return _fake_process()

    real_spawn = asyncio.create_subprocess_exec
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    adapter = CLIAdapter()
    legacy = tmp_path / "legacy-workspace"
    session = await adapter.create_session(
        ids["agent"], {"backend": "claude", "workspace": str(legacy)}
    )
    session.worktree_path = workspace
    result = await adapter.execute_task(session, uuid.uuid4(), {"prompt": "go"})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", real_spawn)

    assert result.success, result.error
    assert Path(seen["cwd"]) == path
    assert (path / "agent.txt").exists()
    assert not (clone / "agent.txt").exists() and not (legacy / "agent.txt").exists()
    assert _git(clone, "status", "--porcelain") == ""
    assert _git(clone, "rev-parse", "main") == ids["base"]
    # Ending the session keeps the agent's work for review; nothing merges it.
    await _end(sessions, ids)
    row = await _row(sessions, wt.id)
    assert row.status == "review"
    assert _git(clone, "show", f"{row.head_commit}:agent.txt") == "written by the agent"
    assert _git(clone, "rev-parse", "main") == ids["base"]


@pytest.mark.parametrize("option", ["use_worktree", "auto_merge"])
async def test_cli_adapter_refuses_its_old_worktree_options(option):
    with pytest.raises(ValueError, match=option):
        await CLIAdapter().create_session(uuid.uuid4(), {"backend": "claude", option: True})


@pytest.mark.parametrize(
    "payload",
    [
        {"args": ["--add-dir", "/"]},
        {"args": ["--add-dir=/"]},
        {"args": ["-w", "x"]},
        {"args": ["--worktree=x"]},
        {"worktree": "x"},
    ],
)
async def test_claude_code_cannot_leave_its_worktree(tmp_path, monkeypatch, payload):
    async def spawn(*a, **kw):
        raise AssertionError("no process may start")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    adapter = ClaudeCodeAdapter()
    session = await adapter.create_session(uuid.uuid4(), {"workspace": str(tmp_path / "ws")})
    session.worktree_path = str(tmp_path)
    result = await adapter.execute_task(session, uuid.uuid4(), {"prompt": "go", **payload})
    assert not result.success


async def test_executor_refuses_the_old_isolate_payload():
    executor = TaskExecutor(AsyncMock(), AsyncMock())
    session = AsyncMock()
    with pytest.raises(ValueError, match="isolate"):
        await executor.execute(AsyncMock(), session, {"isolate": True})


def test_no_execution_path_creates_merges_or_removes_worktrees_itself():
    for path in [*(SRC / "adapters").glob("*.py"), SRC / "runtime" / "executor.py"]:
        text = path.read_text(encoding="utf-8")
        for name in ("WorktreeManager", "merge_worktree", "remove_worktree", "create_worktree"):
            assert name not in text, f"{path.name} uses {name}"


def test_chat_runs_sessions_in_their_checked_worktree():
    source = inspect.getsource(chat._call_llm)
    assert "session_workspace(" in source
    assert "session.worktree_path = " in source


# ── Security ─────────────────────────────────────────────────────────────


async def test_a_worktree_replaced_by_a_link_is_refused(sessions, world, tmp_path):
    ids = world["a"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    _commit(path, "work.txt", "work\n")
    outside = tmp_path / "outside"
    shutil.move(str(path), str(outside))
    _link_dir(path, outside)
    await _refused(_workspace(sessions, ids), "invalid_path")
    await _refused(_move(sessions, ids, wt.id, "review"), "invalid_path")
    await _refused(_refresh(sessions, ids, wt.id), "invalid_path")


async def test_another_company_cannot_touch_the_worktree(sessions, world):
    a, b = world["a"], world["b"]
    wt, _ = await _reviewed(sessions, a)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(b["company"]))
        await _refused(svc.transition(wt.id, "active"), "not_found")
        await _refused(svc.refresh_head(wt.id), "not_found")
        await _refused(svc.archive(wt.id), "not_found")
    assert (await _row(sessions, wt.id)).status == "review"


@pytest.mark.parametrize(
    "base_ref",
    [
        "main; touch pwned",
        "$(touch pwned)",
        "`touch pwned`",
        "main && touch pwned",
        "--output=pwned",
        "-c core.pager=touch",
        "main\ntouch pwned",
        "../../etc/passwd",
        "refs/heads/../../x",
    ],
)
async def test_hostile_base_refs_are_unknown_and_run_nothing(sessions, world, base_ref):
    ids = world["a"]
    await _refused(_create(sessions, ids, base_ref=base_ref), "unknown_ref")
    assert not (ids["clone"] / "pwned").exists() and not Path("pwned").exists()
    async with sessions() as s:
        assert (await s.execute(select(AgentWorktree))).scalars().all() == []


@pytest.mark.parametrize(
    "forged",
    [
        {"branch": "main"},
        {"branch": "nexus/wt-other"},
        {"relative_path": "../escape"},
        {"relative_path": "somewhere-else"},
    ],
)
async def test_a_branch_or_path_altered_in_the_database_is_refused(sessions, world, forged):
    ids = world["a"]
    clone = ids["clone"]
    wt = await _create(sessions, ids, session_id=ids["session"])
    await _update(sessions, wt.id, **forged)
    await _refused(_move(sessions, ids, wt.id, "active"), "conflict")
    assert len(_worktrees(clone)) == 1
    assert _git(clone, "symbolic-ref", "HEAD") == "refs/heads/main"
    # An active row altered afterwards is refused too, by every git path.
    await _update(sessions, wt.id, branch=wt.branch, relative_path=wt.relative_path)
    await _move(sessions, ids, wt.id, "active")
    await _update(sessions, wt.id, **forged)
    await _refused(_workspace(sessions, ids), "conflict")
    await _refused(_refresh(sessions, ids, wt.id), "conflict")
    await _refused(_move(sessions, ids, wt.id, "review"), "conflict")


# ── Session release ──────────────────────────────────────────────────────


async def _end(sessions, ids, status="terminated"):
    async with sessions() as s:
        record = await s.get(AgentSessionRecord, ids["session"])
        end_session(record, status)
        await release_session_worktree(s, record)
        await s.commit()


async def _released_audits(sessions) -> list[AuditLog]:
    async with sessions() as s:
        stmt = select(AuditLog).where(AuditLog.action == "worktree.released")
        return list((await s.execute(stmt)).scalars())


async def test_ending_a_session_commits_left_work_and_sends_it_to_review(sessions, world):
    ids = world["a"]
    clone = ids["clone"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    (path / "unsaved.txt").write_text("left behind\n")
    await _end(sessions, ids)

    row = await _row(sessions, wt.id)
    assert row.status == "review" and row.session_id is None
    assert row.head_commit == _git(path, "rev-parse", "HEAD") != ids["base"]
    assert _git(path, "status", "--porcelain") == ""
    assert _git(path, "log", "-1", "--format=%an", row.head_commit) == GIT_AUTHOR[0]
    assert _git(clone, "rev-parse", "main") == ids["base"]  # nothing merged
    assert path.is_dir()
    [audit] = await _released_audits(sessions)
    assert audit.actor_type == "system"
    assert audit.details["committed_changes"] is True
    assert audit.details["status"] == "review"


async def test_ending_a_session_with_commits_sends_them_to_review(sessions, world):
    ids = world["a"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    head = _commit(path, "work.txt", "work\n")
    await _end(sessions, ids, "completed")
    row = await _row(sessions, wt.id)
    assert (row.status, row.head_commit, row.session_id) == ("review", head, None)


async def test_ending_a_session_without_work_archives_the_worktree(sessions, world):
    ids = world["a"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    await _end(sessions, ids, "failed")
    row = await _row(sessions, wt.id)
    assert (row.status, row.session_id) == ("archived", None)
    assert path.is_dir()
    assert _git(ids["clone"], "rev-parse", f"refs/heads/{wt.branch}") == ids["base"]


async def test_ending_a_session_archives_a_worktree_never_activated(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids, session_id=ids["session"])
    await _end(sessions, ids)
    row = await _row(sessions, wt.id)
    assert (row.status, row.session_id) == ("archived", None)


async def test_a_session_that_has_not_ended_keeps_its_worktree(sessions, world):
    ids = world["a"]
    wt, _ = await _active(sessions, ids, session_id=ids["session"])
    async with sessions() as s:
        record = await s.get(AgentSessionRecord, ids["session"])
        end_session(record, "idle")
        await release_session_worktree(s, record)
        await s.commit()
    row = await _row(sessions, wt.id)
    assert (row.status, row.session_id) == ("active", ids["session"])
    assert await _released_audits(sessions) == []


async def test_git_failure_at_session_end_leaves_the_worktree_active_and_unheld(
    sessions, world, monkeypatch
):
    ids = world["a"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    (path / "unsaved.txt").write_text("x\n")

    async def broken(*a, **kw):
        raise WorktreeError("git_unavailable", "Could not read the worktree")

    monkeypatch.setattr(worktree_service, "_snapshot", broken)
    await _end(sessions, ids)
    row = await _row(sessions, wt.id)
    assert (row.status, row.session_id) == ("active", None)
    assert (path / "unsaved.txt").exists()
    [audit] = await _released_audits(sessions)
    assert audit.details["error"] == "Could not read the worktree"
    async with sessions() as s:
        assert (await s.get(AgentSessionRecord, ids["session"])).status == "terminated"


async def test_terminate_route_releases_the_worktree(sessions, world):
    ids = world["a"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    head = _commit(path, "work.txt", "work\n")
    async with sessions() as s:
        out = await terminate_session(ids["session"], ids["company"], s)
    assert out.status == "terminated"
    row = await _row(sessions, wt.id)
    assert (row.status, row.head_commit, row.session_id) == ("review", head, None)


async def test_terminate_route_in_another_company_releases_nothing(sessions, world):
    from fastapi import HTTPException

    ids = world["a"]
    wt, _ = await _active(sessions, ids, session_id=ids["session"])
    async with sessions() as s:
        with pytest.raises(HTTPException) as exc:
            await terminate_session(ids["session"], world["b"]["company"], s)
    assert exc.value.status_code == 404
    row = await _row(sessions, wt.id)
    assert (row.status, row.session_id) == ("active", ids["session"])
