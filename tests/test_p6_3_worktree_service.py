"""P6.3: WorktreeService, the authoritative writer of agent_worktrees rows.

Runs on a file SQLite database with foreign keys switched on and against real
git repositories created under a temporary repository root. Nothing here
creates a worktree on disk; the service only records and transitions rows.
"""

import asyncio
import inspect
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401  (registers every table)
from nexus.api.routes.agents import delete_agent
from nexus.api.routes.repositories import disconnect_repo
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.agent_worktree import AgentWorktree
from nexus.models.company import Company
from nexus.models.governance import Approval
from nexus.models.repository import Repository
from nexus.models.task import Task
from nexus.runtime.git_runner import GitRunner
from nexus.services import worktree_service
from nexus.services.worktree_service import (
    WorktreeError,
    WorktreeService,
    worktree_path,
    worktree_root,
)

SHA = "b" * 40
STATUSES = ("created", "active", "review", "approved", "merged", "archived")
# Written out independently of worktree_service.TRANSITIONS on purpose.
ALLOWED = {
    ("created", "active"),
    ("created", "archived"),
    ("active", "review"),
    ("active", "archived"),
    ("review", "active"),
    ("review", "approved"),
    ("review", "archived"),
    ("approved", "active"),
    ("approved", "merged"),
    ("approved", "archived"),
    ("merged", "archived"),
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "commit", "-q", "--allow-empty", "-m", "init")
    _git(path, "tag", "-a", "v1", "-m", "release")
    return path


def _link_dir(link: Path, target: Path) -> None:
    """Symlink, or on Windows without symlink rights a junction; skip if neither works."""
    link.parent.mkdir(parents=True, exist_ok=True)
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
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'wt.db').as_posix()}")

    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def sessions(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "repository_roots", str(tmp_path / "repos" / "{company_id}"))
    monkeypatch.setattr(settings, "worktree_root", str(tmp_path / "wt" / "{company_id}"))
    return tmp_path


@pytest.fixture
async def world(sessions, roots):
    """Two companies, each with a git-backed repository, agent, session, task and approvals."""
    ids = {}
    async with sessions() as s:
        for key in ("a", "b"):
            company = Company(name=f"co-{key}")
            s.add(company)
            await s.flush()
            clone = _make_repo(roots / "repos" / str(company.id) / "r")
            repo = Repository(company_id=company.id, name="r", url="u", local_path=str(clone))
            agent = Agent(company_id=company.id, name="ag", role="dev")
            s.add_all([repo, agent])
            await s.flush()
            session = AgentSessionRecord(company_id=company.id, agent_id=agent.id)
            task = Task(company_id=company.id, title="t")
            approval = Approval(company_id=company.id, type="worktree_merge")
            approved = Approval(company_id=company.id, type="worktree_merge", status="approved")
            s.add_all([session, task, approval, approved])
            await s.flush()
            ids[key] = {
                "company": company.id,
                "repo": repo.id,
                "clone": clone,
                "agent": agent.id,
                "session": session.id,
                "task": task.id,
                "approval": approval.id,
                "approved": approved.id,
            }
        await s.commit()
    return ids


def _manager(company_id: uuid.UUID, **kw) -> Principal:
    return Principal(
        kind="user", company_id=company_id, role="manager", email="m@example.test", **kw
    )


async def _create(sessions, ids, principal=None, **kw) -> AgentWorktree:
    async with sessions() as s:
        svc = WorktreeService(s, principal or _manager(ids["company"]))
        wt = await svc.create(repository_id=ids["repo"], agent_id=ids["agent"], **kw)
        await s.commit()
        return wt


async def _set_status(sessions, wt_id, status: str) -> None:
    async with sessions() as s:
        row = await s.get(AgentWorktree, wt_id)
        row.status = status
        await s.commit()


async def _refused(coro, reason: str) -> WorktreeError:
    with pytest.raises(WorktreeError) as exc:
        await coro
    assert exc.value.reason == reason, exc.value.detail
    return exc.value


# ── Creation ─────────────────────────────────────────────────────────────


async def test_create_records_row_with_server_generated_fields(sessions, world):
    ids = world["a"]
    wt = await _create(
        sessions,
        ids,
        session_id=ids["session"],
        task_id=ids["task"],
        approval_id=ids["approval"],
    )
    assert wt.status == "created"
    assert wt.company_id == ids["company"]
    assert wt.branch == f"nexus/wt-{wt.id}"
    assert wt.relative_path == str(wt.id)
    assert not Path(wt.relative_path).is_absolute()
    assert wt.base_ref == "HEAD"
    assert wt.base_commit == _git(ids["clone"], "rev-parse", "HEAD")
    assert wt.created_by == "m@example.test"
    assert (wt.session_id, wt.task_id, wt.approval_id) == (
        ids["session"],
        ids["task"],
        ids["approval"],
    )
    async with sessions() as s:
        assert (await s.get(AgentWorktree, wt.id)) is not None


async def test_create_ignores_nothing_it_could_trust_from_the_caller(sessions, world):
    # There is no parameter for company, branch or path: they cannot be supplied.
    params = inspect.signature(WorktreeService.create).parameters
    assert not {"company_id", "branch", "relative_path", "base_commit", "status"} & set(params)


async def test_create_does_not_touch_the_filesystem(sessions, world, roots):
    wt = await _create(sessions, world["a"])
    assert not (roots / "wt").exists()
    branches = _git(world["a"]["clone"], "branch", "--list", wt.branch)
    assert branches == ""


async def test_base_ref_resolves_to_full_commit_id(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids, base_ref="v1")
    commit = _git(ids["clone"], "rev-parse", "v1^{commit}")
    assert wt.base_ref == "v1"
    assert wt.base_commit == commit
    assert len(wt.base_commit) in (40, 64)
    # An annotated tag's own object id is not a commit and is not stored.
    assert wt.base_commit != _git(ids["clone"], "rev-parse", "v1")


@pytest.mark.parametrize("ref", ["nope", "main~99", "-x", "a b"])
async def test_unknown_base_ref_is_refused(sessions, world, ref):
    err = await _refused(_create(sessions, world["a"], base_ref=ref), "unknown_ref")
    assert err.status_code == 400
    async with sessions() as s:
        assert (await s.execute(select(AgentWorktree))).first() is None


async def _set_local_path(sessions, repo_id, local_path) -> None:
    async with sessions() as s:
        repo = await s.get(Repository, repo_id)
        repo.local_path = local_path
        await s.commit()


async def test_repository_without_clone_is_invalid(sessions, world):
    await _set_local_path(sessions, world["a"]["repo"], None)
    await _refused(_create(sessions, world["a"]), "invalid_repository")


async def test_directory_that_is_not_a_repository_is_invalid_not_unknown_ref(
    sessions, world, roots
):
    # Inside the roots but not a git repository. git would otherwise search
    # upwards and could find an unrelated repository around the roots.
    plain = roots / "repos" / str(world["a"]["company"]) / "plain"
    plain.mkdir()
    await _set_local_path(sessions, world["a"]["repo"], str(plain))
    err = await _refused(_create(sessions, world["a"]), "invalid_repository")
    assert err.status_code == 422


async def test_repository_outside_roots_is_refused(sessions, world, roots):
    outside = _make_repo(roots / "elsewhere")
    await _set_local_path(sessions, world["a"]["repo"], str(outside))
    await _refused(_create(sessions, world["a"]), "invalid_repository")


async def test_repository_in_another_companys_root_is_refused(sessions, world):
    await _set_local_path(sessions, world["a"]["repo"], str(world["b"]["clone"]))
    await _refused(_create(sessions, world["a"]), "invalid_repository")


async def test_repository_link_escaping_roots_is_refused(sessions, world, roots):
    outside = _make_repo(roots / "elsewhere")
    link = roots / "repos" / str(world["a"]["company"]) / "link"
    _link_dir(link, outside)
    await _set_local_path(sessions, world["a"]["repo"], str(link))
    await _refused(_create(sessions, world["a"]), "invalid_repository")


async def test_repository_traversal_is_refused(sessions, world, roots):
    _make_repo(roots / "elsewhere")
    raw = str(roots / "repos" / str(world["a"]["company"]) / ".." / ".." / "elsewhere")
    await _set_local_path(sessions, world["a"]["repo"], raw)
    await _refused(_create(sessions, world["a"]), "invalid_repository")


# ── Company consistency ──────────────────────────────────────────────────


@pytest.mark.parametrize("link", ["repo", "agent", "session", "task", "approval"])
async def test_other_companys_link_reads_as_missing(sessions, world, link):
    a, b = world["a"], world["b"]
    kw = {"repository_id": a["repo"], "agent_id": a["agent"]}
    field = {"repo": "repository_id", "agent": "agent_id"}.get(link, f"{link}_id")
    kw[field] = b[link]
    async with sessions() as s:
        svc = WorktreeService(s, _manager(a["company"]))
        err = await _refused(svc.create(**kw), "not_found")
    assert err.status_code == 404


async def test_company_comes_from_the_principal(sessions, world):
    # Company b's principal naming company a's rows finds nothing.
    a, b = world["a"], world["b"]
    async with sessions() as s:
        svc = WorktreeService(s, _manager(b["company"]))
        await _refused(svc.create(repository_id=a["repo"], agent_id=a["agent"]), "not_found")


async def test_session_of_another_agent_is_refused(sessions, world):
    ids = world["a"]
    async with sessions() as s:
        other = Agent(company_id=ids["company"], name="other", role="dev")
        s.add(other)
        await s.commit()
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        await _refused(
            svc.create(repository_id=ids["repo"], agent_id=other.id, session_id=ids["session"]),
            "invalid_link",
        )


async def test_ended_session_is_refused(sessions, world):
    ids = world["a"]
    async with sessions() as s:
        (await s.get(AgentSessionRecord, ids["session"])).status = "completed"
        await s.commit()
    await _refused(_create(sessions, ids, session_id=ids["session"]), "conflict")


# ── Authorization ────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["viewer", "agent"])
async def test_roles_without_write_worktree_cannot_create(sessions, world, role):
    ids = world["a"]
    p = Principal(kind="user", company_id=ids["company"], role=role, email="x@example.test")
    await _refused(_create(sessions, ids, principal=p), "forbidden")


async def test_run_principal_is_limited_to_its_own_agent(sessions, world):
    ids = world["a"]
    # Role admin so the agent check, not RBAC, is what refuses.
    p = Principal(
        kind="run", company_id=ids["company"], role="admin", run_id="r1", agent_id=uuid.uuid4()
    )
    await _refused(_create(sessions, ids, principal=p), "forbidden")


async def test_viewer_can_read_but_agent_role_cannot(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    async with sessions() as s:
        viewer = Principal(kind="user", company_id=ids["company"], role="viewer", email="v@x")
        assert (await WorktreeService(s, viewer).get(wt.id)).id == wt.id
        agent = Principal(kind="user", company_id=ids["company"], role="agent", email="g@x")
        await _refused(WorktreeService(s, agent).get(wt.id), "forbidden")


# ── Paths ────────────────────────────────────────────────────────────────


def test_worktree_root_is_per_company(roots):
    a, b = uuid.uuid4(), uuid.uuid4()
    assert worktree_root(a) == (roots / "wt" / str(a)).resolve()
    assert worktree_root(a) != worktree_root(b)


def test_worktree_root_without_company_placeholder_is_refused(roots, monkeypatch):
    monkeypatch.setattr(settings, "worktree_root", str(roots / "wt"))
    with pytest.raises(WorktreeError) as exc:
        worktree_root(uuid.uuid4())
    assert exc.value.reason == "misconfigured"


def test_worktree_path_resolves_under_root(roots):
    cid, wid = uuid.uuid4(), str(uuid.uuid4())
    assert worktree_path(cid, wid) == worktree_root(cid) / wid


@pytest.mark.parametrize(
    "rel",
    [
        "",
        ".",
        "..",
        "../x",
        "a/../../x",
        "a/../..",
        "/etc/passwd",
        "\\\\srv\\share\\x",
        "C:\\x",
        "C:x",
    ],
)
def test_worktree_path_refuses_traversal_and_absolute(roots, rel):
    with pytest.raises(WorktreeError) as exc:
        worktree_path(uuid.uuid4(), rel)
    assert exc.value.reason == "invalid_path"


def test_worktree_path_refuses_link_escape(roots):
    cid = uuid.uuid4()
    outside = roots / "outside"
    outside.mkdir()
    _link_dir(worktree_root(cid) / "escape", outside)
    with pytest.raises(WorktreeError) as exc:
        worktree_path(cid, "escape")
    assert exc.value.reason == "invalid_path"


def test_worktree_path_refuses_link_into_another_company(roots):
    a, b = uuid.uuid4(), uuid.uuid4()
    target = worktree_root(b) / "x"
    target.mkdir(parents=True)
    _link_dir(worktree_root(a) / "x", target)
    with pytest.raises(WorktreeError):
        worktree_path(a, "x")


async def test_path_of_revalidates_stored_path(sessions, world, roots):
    ids = world["a"]
    wt = await _create(sessions, ids)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        assert svc.path_of(wt) == worktree_root(ids["company"]) / str(wt.id)
        wt.relative_path = "../escape"
        with pytest.raises(WorktreeError):
            svc.path_of(wt)


# ── Lifecycle ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("src", STATUSES)
@pytest.mark.parametrize("dst", STATUSES)
async def test_transition_matrix(sessions, world, src, dst):
    ids = world["a"]
    wt = await _create(sessions, ids)
    await _set_status(sessions, wt.id, src)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        call = svc.transition(wt.id, dst, approval_id=ids["approved"], merged_commit=SHA)
        if src == dst or (src, dst) in ALLOWED:
            row = await call
            await s.commit()
            assert row.status == dst
        else:
            err = await _refused(call, "illegal_transition")
            assert err.status_code == 409
    async with sessions() as s:
        expected = dst if (src == dst or (src, dst) in ALLOWED) else src
        assert (await s.get(AgentWorktree, wt.id)).status == expected


@pytest.mark.parametrize(
    "src,dst",
    [("archived", "active"), ("merged", "active"), ("created", "review"), ("active", "merged")],
)
async def test_named_illegal_transitions(sessions, world, src, dst):
    ids = world["a"]
    wt = await _create(sessions, ids)
    await _set_status(sessions, wt.id, src)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        await _refused(svc.transition(wt.id, dst, merged_commit=SHA), "illegal_transition")


@pytest.mark.parametrize("src", ["review", "approved"])
async def test_back_to_active_for_more_work(sessions, world, src):
    ids = world["a"]
    wt = await _create(sessions, ids)
    await _set_status(sessions, wt.id, src)
    async with sessions() as s:
        row = await WorktreeService(s, _manager(ids["company"])).transition(wt.id, "active")
        assert row.status == "active"


async def test_full_happy_path(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        for to in ("active", "review"):
            await svc.transition(wt.id, to)
        row = await svc.transition(wt.id, "approved", approval_id=ids["approved"])
        assert row.approval_id == ids["approved"]
        row = await svc.transition(wt.id, "merged", merged_commit=SHA)
        assert row.merged_commit == SHA
        row = await svc.archive(wt.id)
        assert row.status == "archived"


async def test_approving_needs_an_approved_approval(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    await _set_status(sessions, wt.id, "review")
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        await _refused(svc.transition(wt.id, "approved"), "approval_required")
        await _refused(
            svc.transition(wt.id, "approved", approval_id=ids["approval"]), "approval_required"
        )
        await _refused(
            svc.transition(wt.id, "approved", approval_id=world["b"]["approved"]), "not_found"
        )


@pytest.mark.parametrize("commit", [None, "abc", "HEAD", "B" * 40])
async def test_merging_needs_a_full_commit_id(sessions, world, commit):
    ids = world["a"]
    wt = await _create(sessions, ids)
    await _set_status(sessions, wt.id, "approved")
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        await _refused(svc.transition(wt.id, "merged", merged_commit=commit), "invalid_link")


async def test_transition_of_other_companys_worktree_reads_as_missing(sessions, world):
    wt = await _create(sessions, world["a"])
    async with sessions() as s:
        svc = WorktreeService(s, _manager(world["b"]["company"]))
        await _refused(svc.archive(wt.id), "not_found")


# ── Archive ──────────────────────────────────────────────────────────────


async def test_archive_deletes_nothing(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        # Stand-ins for what a later git layer will create.
        directory = svc.path_of(wt)
        directory.mkdir(parents=True)
        (directory / "work.txt").write_text("unmerged work")
        _git(ids["clone"], "branch", wt.branch)

        row = await svc.archive(wt.id)
        await s.commit()
    assert row.status == "archived"
    assert (directory / "work.txt").read_text() == "unmerged work"
    assert _git(ids["clone"], "branch", "--list", wt.branch).strip().endswith(wt.branch)
    async with sessions() as s:
        assert (await s.get(AgentWorktree, wt.id)).status == "archived"


async def test_archive_is_idempotent(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        await svc.archive(wt.id)
        assert (await svc.archive(wt.id)).status == "archived"


async def test_archive_frees_the_session(sessions, world):
    ids = world["a"]
    first = await _create(sessions, ids, session_id=ids["session"])
    async with sessions() as s:
        await WorktreeService(s, _manager(ids["company"])).archive(first.id)
        await s.commit()
    second = await _create(sessions, ids, session_id=ids["session"])
    assert second.id != first.id


# ── Concurrency and idempotency ──────────────────────────────────────────


async def test_second_open_worktree_for_a_session_conflicts(sessions, world):
    ids = world["a"]
    await _create(sessions, ids, session_id=ids["session"])
    err = await _refused(_create(sessions, ids, session_id=ids["session"]), "conflict")
    assert err.status_code == 409


async def test_concurrent_creates_for_one_session_yield_one_row(sessions, world):
    ids = world["a"]
    results = await asyncio.gather(
        *(_create(sessions, ids, session_id=ids["session"]) for _ in range(2)),
        return_exceptions=True,
    )
    ok = [r for r in results if isinstance(r, AgentWorktree)]
    refused = [r for r in results if isinstance(r, WorktreeError)]
    assert len(ok) == 1 and len(refused) == 1, results
    assert refused[0].reason == "conflict"
    async with sessions() as s:
        rows = (await s.execute(select(AgentWorktree))).scalars().all()
    assert [r.id for r in rows] == [ok[0].id]


async def test_branch_collision_conflicts_and_leaves_session_usable(sessions, world, monkeypatch):
    ids = world["a"]
    taken = uuid.uuid4()
    async with sessions() as s:
        s.add(
            AgentWorktree(
                company_id=ids["company"],
                repository_id=ids["repo"],
                agent_id=ids["agent"],
                branch=f"nexus/wt-{taken}",
                base_ref="HEAD",
                base_commit=SHA,
                relative_path="other",
                created_by="seed",
            )
        )
        await s.commit()
    monkeypatch.setattr(worktree_service.uuid, "uuid4", lambda: taken)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        await _refused(svc.create(repository_id=ids["repo"], agent_id=ids["agent"]), "conflict")
        # The failed insert was rolled back to its savepoint only.
        assert len(await svc.list_worktrees()) == 1


async def test_racing_transition_loses_with_409(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    await _set_status(sessions, wt.id, "review")
    async with sessions() as slow, sessions() as fast:
        slow_svc = WorktreeService(slow, _manager(ids["company"]))
        # Keep the reference: the identity map holds rows weakly, and a
        # collected row would simply be reloaded fresh.
        stale = await slow_svc.get(wt.id)
        assert stale.status == "review"
        await WorktreeService(fast, _manager(ids["company"])).transition(wt.id, "active")
        await fast.commit()
        # slow still believes "review"; its conditional write matches nothing.
        await _refused(slow_svc.transition(wt.id, "archived"), "conflict")
    async with sessions() as s:
        assert (await s.get(AgentWorktree, wt.id)).status == "active"


# ── Lookup and listing ───────────────────────────────────────────────────


async def test_listing_is_company_scoped_and_filterable(sessions, world):
    a, b = world["a"], world["b"]
    w1 = await _create(sessions, a, session_id=a["session"])
    w2 = await _create(sessions, a)
    wb = await _create(sessions, b)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(a["company"]))
        assert {w.id for w in await svc.list_worktrees()} == {w1.id, w2.id}
        assert [w.id for w in await svc.list_worktrees(session_id=a["session"])] == [w1.id]
        assert await svc.list_worktrees(repository_id=b["repo"]) == []
        await svc.archive(w2.id)
        assert [w.id for w in await svc.list_worktrees(status="archived")] == [w2.id]
        assert {w.id for w in await svc.list_worktrees(agent_id=a["agent"])} == {w1.id, w2.id}
        await _refused(svc.get(wb.id), "not_found")
        await _refused(svc.get(uuid.uuid4()), "not_found")


# ── Deletion paths ───────────────────────────────────────────────────────


async def test_repository_with_worktrees_cannot_be_deleted(sessions, world):
    from fastapi import HTTPException

    ids = world["a"]
    wt = await _create(sessions, ids)
    async with sessions() as s:
        await WorktreeService(s, _manager(ids["company"])).archive(wt.id)
        await s.commit()
    async with sessions() as s:
        with pytest.raises(HTTPException) as exc:
            await disconnect_repo(ids["repo"], s, ids["company"])
        assert exc.value.status_code == 409
    async with sessions() as s:
        assert await s.get(Repository, ids["repo"]) is not None
    # A repository without worktrees still deletes.
    async with sessions() as s:
        await disconnect_repo(world["b"]["repo"], s, world["b"]["company"])
        await s.commit()
        assert await s.get(Repository, world["b"]["repo"]) is None


async def test_agent_with_worktrees_cannot_be_deleted(sessions, world):
    from fastapi import HTTPException

    ids = world["a"]
    await _create(sessions, ids)
    async with sessions() as s:
        with pytest.raises(HTTPException) as exc:
            await delete_agent(ids["agent"], s, ids["company"])
        assert exc.value.status_code == 409
    async with sessions() as s:
        assert await s.get(Agent, ids["agent"]) is not None


# ── Git boundary ─────────────────────────────────────────────────────────


async def test_uses_git_runner_and_never_a_shell(sessions, world, monkeypatch):
    def _no_shell(*_a, **_k):
        raise AssertionError("shell execution attempted")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _no_shell)
    monkeypatch.setattr(subprocess, "run", _no_shell)
    monkeypatch.setattr(subprocess, "check_output", _no_shell)
    monkeypatch.setattr(os, "system", _no_shell)

    calls = []
    real = GitRunner.resolve_commit

    async def spy(self, ref):
        calls.append((self.path, ref))
        return await real(self, ref)

    monkeypatch.setattr(GitRunner, "resolve_commit", spy)
    ids = world["a"]
    async with sessions() as s:
        wt = await WorktreeService(s, _manager(ids["company"])).create(
            repository_id=ids["repo"], agent_id=ids["agent"], base_ref="main"
        )
    assert calls == [(ids["clone"].resolve(), "main")]
    assert len(wt.base_commit) == 40


def test_service_source_avoids_legacy_git_helpers():
    src = Path(worktree_service.__file__).read_text(encoding="utf-8")
    for banned in (
        "subprocess",
        "shell=True",
        "os.system",
        "nexus.runtime.worktree",
        "WorktreeManager",
    ):
        assert banned not in src, banned
