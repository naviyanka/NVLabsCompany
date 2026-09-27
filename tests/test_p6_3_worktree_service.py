"""P6.3: WorktreeService, the authoritative writer of agent_worktrees rows.

Runs on a file SQLite database with foreign keys switched on and against real
git repositories created under a temporary repository root. Creation resolves
refs in those repositories for real. The git steps behind transitions
(creating the worktree, reading its head, merging) are replaced by
``_FakeGit`` here, so these tests cover the row rules alone: which moves are
legal, approval binding, company scoping and races. ``test_p6_5_git_worktrees``
runs the same transitions against real worktrees.
"""

import asyncio
import inspect
import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta, timezone
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
from nexus.runtime.git_runner import GitRunner, MergeOutcome
from nexus.services import worktree_service
from nexus.services.approval_service import ApprovalService
from nexus.services.worktree_service import (
    WORKTREE_APPROVAL_TYPE,
    WorktreeError,
    WorktreeService,
    check_worktree_approval,
    worktree_path,
    worktree_root,
)

SHA = "b" * 40
# Heads a worktree moves through; stand-ins for what the git layer records.
HEAD = "1" * 40
NEW_HEAD = "2" * 40
# The merge commit _FakeGit reports.
MERGED = "3" * 40
APPROVER = "approver@example.test"
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


class _FakeGit:
    """The repository's git as the transition steps see it, minus the disk."""

    async def resolve_commit(self, ref: str) -> str:
        return ref if len(ref) in (40, 64) else SHA

    async def check_branch_name(self, name: str) -> None:
        return None

    async def current_branch(self) -> str:
        return "refs/heads/main"

    async def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return True

    async def list_worktrees(self) -> list:
        return []

    async def merge_into(self, *args, **kwargs) -> MergeOutcome:
        return MergeOutcome(status="merged", commit=MERGED, conflicts=[])


@pytest.fixture(autouse=True)
def fake_git(monkeypatch):
    """Transition steps read the head the row records and merge as MERGED."""

    async def repository_git(db, row):
        return _FakeGit()

    async def registration(git, row):
        return object()

    async def read_head(git, row):
        return row.head_commit or HEAD

    async def snapshot(db, row, *, commit_changes):
        return row.head_commit or HEAD, False

    monkeypatch.setattr(worktree_service, "_repository_git", repository_git)
    monkeypatch.setattr(worktree_service, "_registration", registration)
    monkeypatch.setattr(worktree_service, "_read_head", read_head)
    monkeypatch.setattr(worktree_service, "_snapshot", snapshot)


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


async def _update(sessions, wt_id, **values) -> None:
    async with sessions() as s:
        row = await s.get(AgentWorktree, wt_id)
        for key, value in values.items():
            setattr(row, key, value)
        await s.commit()


async def _set_status(sessions, wt_id, status: str) -> None:
    await _update(sessions, wt_id, status=status)


async def _set_head(sessions, wt_id, head: str | None) -> None:
    await _update(sessions, wt_id, head_commit=head)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _approval(
    sessions,
    company_id: uuid.UUID,
    worktree_id,
    *,
    head: str = HEAD,
    status: str = "approved",
    type: str = WORKTREE_APPROVAL_TYPE,
    payload: dict | None = None,
    decided_by: str | None = APPROVER,
    expires_at: datetime | None = None,
) -> uuid.UUID:
    """An approval row naming ``worktree_id`` at ``head`` unless ``payload`` says otherwise."""
    if payload is None:
        payload = {"worktree_id": str(worktree_id), "head_commit": head}
    async with sessions() as s:
        row = Approval(
            company_id=company_id,
            type=type,
            status=status,
            payload=payload,
            decided_by=decided_by,
            expires_at=expires_at,
        )
        s.add(row)
        await s.commit()
        return row.id


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
    bound = await _approval(sessions, ids["company"], wt.id)
    # An approved row carries the approval that approved it; merging re-checks it.
    await _update(sessions, wt.id, status=src, head_commit=HEAD, approval_id=bound)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        call = svc.transition(wt.id, dst, approval_id=bound)
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
        await _refused(svc.transition(wt.id, dst), "illegal_transition")


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
    await _set_head(sessions, wt.id, HEAD)
    bound = await _approval(sessions, ids["company"], wt.id)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        for to in ("active", "review"):
            await svc.transition(wt.id, to)
        row = await svc.transition(wt.id, "approved", approval_id=bound)
        assert row.approval_id == bound
        row = await svc.transition(wt.id, "merged")
        assert row.merged_commit == MERGED  # what the merge produced
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


# ── Approval binding ─────────────────────────────────────────────────────


async def _in_review(sessions, ids, head: str | None = HEAD) -> AgentWorktree:
    wt = await _create(sessions, ids)
    await _set_status(sessions, wt.id, "review")
    await _set_head(sessions, wt.id, head)
    return wt


async def _approve(sessions, ids, wt, approval_id):
    async with sessions() as s:
        row = await WorktreeService(s, _manager(ids["company"])).transition(
            wt.id, "approved", approval_id=approval_id
        )
        await s.commit()
        return row


async def _status(sessions, wt) -> str:
    async with sessions() as s:
        return (await s.get(AgentWorktree, wt.id)).status


async def test_approval_naming_this_worktree_approves_it(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    bound = await _approval(sessions, ids["company"], wt.id)
    row = await _approve(sessions, ids, wt, bound)
    assert (row.status, row.approval_id) == ("approved", bound)
    assert await _status(sessions, wt) == "approved"


async def test_approval_for_another_worktree_is_refused(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    other = await _in_review(sessions, ids)
    for_other = await _approval(sessions, ids["company"], other.id)
    err = await _refused(_approve(sessions, ids, wt, for_other), "approval_required")
    assert err.status_code == 409
    assert await _status(sessions, wt) == "review"
    # The approval still approves the worktree it names.
    assert (await _approve(sessions, ids, other, for_other)).status == "approved"


@pytest.mark.parametrize("kind", ["worktree_merge", "deployment", "WORKTREE_APPROVAL", ""])
async def test_approval_of_the_wrong_type_is_refused(sessions, world, kind):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    wrong = await _approval(sessions, ids["company"], wt.id, type=kind)
    err = await _refused(_approve(sessions, ids, wt, wrong), "approval_required")
    assert err.status_code == 409
    assert await _status(sessions, wt) == "review"


@pytest.mark.parametrize("state", ["pending", "rejected", "denied", "expired", "APPROVED"])
async def test_undecided_or_rejected_approval_is_refused(sessions, world, state):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    undecided = await _approval(sessions, ids["company"], wt.id, status=state)
    err = await _refused(_approve(sessions, ids, wt, undecided), "approval_required")
    assert err.status_code == 409
    assert await _status(sessions, wt) == "review"


async def test_cross_company_approval_reads_as_missing(sessions, world):
    # Company b approves a worktree id that belongs to company a.
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    foreign = await _approval(sessions, world["b"]["company"], wt.id)
    err = await _refused(_approve(sessions, ids, wt, foreign), "not_found")
    assert err.status_code == 404
    assert await _status(sessions, wt) == "review"


def _spoofs(wt_id: uuid.UUID) -> list:
    wid = str(wt_id)
    return [
        None,
        {},
        {"worktree": wid},
        {"worktree_id": wid.upper()},
        {"worktree_id": "{" + wid + "}"},
        {"worktree_id": f"urn:uuid:{wid}"},
        {"worktree_id": wid.replace("-", "")},
        {"worktree_id": f" {wid}"},
        {"worktree_id": f"{wid}\n"},
        {"worktree_id": [wid]},
        {"worktree_id": {"id": wid}},
        {"worktree_id": f"{wid},{uuid.uuid4()}"},
        {"target": {"worktree_id": wid}},
        {"description": f"please approve {wid}"},
    ]


@pytest.mark.parametrize("case", range(14))
async def test_spoofed_worktree_reference_is_refused(sessions, world, case):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    payload = _spoofs(wt.id)[case]
    async with sessions() as s:
        row = Approval(
            company_id=ids["company"],
            type=WORKTREE_APPROVAL_TYPE,
            status="approved",
            payload=payload,
            decided_by=APPROVER,
        )
        s.add(row)
        await s.commit()
    await _refused(_approve(sessions, ids, wt, row.id), "approval_required")
    assert await _status(sessions, wt) == "review"


async def test_approval_linked_at_creation_cannot_approve(sessions, world):
    # A worktree created with an approval attached falls back to it when no
    # approval is passed. That approval cannot name the worktree, whose id did
    # not exist yet, so the fallback never approves.
    ids = world["a"]
    wt = await _create(sessions, ids, approval_id=ids["approved"])
    await _set_status(sessions, wt.id, "review")
    await _refused(_approve(sessions, ids, wt, None), "approval_required")
    assert await _status(sessions, wt) == "review"


def test_binding_check_refuses_an_approval_from_another_company(world):
    # Defense in depth for a caller that loads the approval without a company filter.
    wt = AgentWorktree(
        id=uuid.uuid4(),
        company_id=world["a"]["company"],
        repository_id=world["a"]["repo"],
        agent_id=world["a"]["agent"],
        branch="b",
        relative_path="p",
        base_ref="HEAD",
        base_commit=SHA,
        created_by="t",
    )
    foreign = Approval(
        company_id=world["b"]["company"],
        type=WORKTREE_APPROVAL_TYPE,
        status="approved",
        payload={"worktree_id": str(wt.id)},
    )
    with pytest.raises(WorktreeError) as exc:
        check_worktree_approval(foreign, wt)
    assert exc.value.reason == "not_found"


# ── Approval bound to the reviewed head ─────────────────────────────────


async def test_approval_for_the_current_head_approves(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    bound = await _approval(sessions, ids["company"], wt.id, head=HEAD)
    row = await _approve(sessions, ids, wt, bound)
    assert (row.status, row.head_commit) == ("approved", HEAD)


async def test_sha256_head_is_accepted(sessions, world):
    ids = world["a"]
    head = "c" * 64
    wt = await _in_review(sessions, ids, head=head)
    bound = await _approval(sessions, ids["company"], wt.id, head=head)
    assert (await _approve(sessions, ids, wt, bound)).status == "approved"


async def test_approval_for_an_old_head_is_refused(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids, head=NEW_HEAD)
    stale = await _approval(sessions, ids["company"], wt.id, head=HEAD)
    err = await _refused(_approve(sessions, ids, wt, stale), "approval_required")
    assert err.status_code == 409
    assert await _status(sessions, wt) == "review"


async def test_rework_invalidates_the_earlier_approval(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids, head=HEAD)
    first = await _approval(sessions, ids["company"], wt.id, head=HEAD)
    assert (await _approve(sessions, ids, wt, first)).status == "approved"

    # Back to work: new commits move the head, then review again.
    async with sessions() as s:
        await WorktreeService(s, _manager(ids["company"])).transition(wt.id, "active")
        await s.commit()
    await _set_head(sessions, wt.id, NEW_HEAD)
    async with sessions() as s:
        await WorktreeService(s, _manager(ids["company"])).transition(wt.id, "review")
        await s.commit()

    err = await _refused(_approve(sessions, ids, wt, first), "approval_required")
    assert err.status_code == 409
    assert await _status(sessions, wt) == "review"

    # A fresh approval of the new head does approve it.
    second = await _approval(sessions, ids["company"], wt.id, head=NEW_HEAD)
    row = await _approve(sessions, ids, wt, second)
    assert (row.status, row.approval_id, row.head_commit) == ("approved", second, NEW_HEAD)


async def test_approval_for_another_worktree_at_the_same_head_is_refused(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids, head=HEAD)
    other = await _in_review(sessions, ids, head=HEAD)
    for_other = await _approval(sessions, ids["company"], other.id, head=HEAD)
    err = await _refused(_approve(sessions, ids, wt, for_other), "approval_required")
    assert err.status_code == 409
    assert await _status(sessions, wt) == "review"


def _head_spoofs() -> list:
    return [
        {},
        {"head_commit": None},
        {"head_commit": ""},
        {"head_commit": HEAD[:7]},
        {"head_commit": HEAD[:39]},
        {"head_commit": HEAD + "1"},
        {"head_commit": HEAD + "0" * 24},
        {"head_commit": "A" * 40},
        {"head_commit": f" {HEAD}"},
        {"head_commit": f"{HEAD}\n"},
        {"head_commit": "HEAD"},
        {"head_commit": "refs/heads/main"},
        {"head_commit": [HEAD]},
        {"head_commit": {"sha": HEAD}},
        {"head_commit": int(HEAD)},
        {"head": HEAD},
        {"reviewed": {"head_commit": HEAD}},
        {"head_commit": NEW_HEAD},
    ]


@pytest.mark.parametrize("case", range(len(_head_spoofs())))
async def test_spoofed_or_malformed_head_is_refused(sessions, world, case):
    ids = world["a"]
    wt = await _in_review(sessions, ids, head=HEAD)
    payload = {"worktree_id": str(wt.id), **_head_spoofs()[case]}
    spoof = await _approval(sessions, ids["company"], wt.id, payload=payload)
    err = await _refused(_approve(sessions, ids, wt, spoof), "approval_required")
    assert err.status_code == 409
    assert await _status(sessions, wt) == "review"


@pytest.mark.parametrize("claimed", [None, "", "abc", HEAD])
async def test_worktree_without_a_recorded_head_cannot_be_approved(sessions, world, claimed):
    ids = world["a"]
    wt = await _in_review(sessions, ids, head=None)
    payload = {"worktree_id": str(wt.id), "head_commit": claimed}
    approval = await _approval(sessions, ids["company"], wt.id, payload=payload)
    await _refused(_approve(sessions, ids, wt, approval), "approval_required")
    assert await _status(sessions, wt) == "review"


@pytest.mark.parametrize("stored", ["abc", HEAD[:7], "A" * 40, "HEAD"])
async def test_malformed_recorded_head_cannot_be_approved_even_if_matched(sessions, world, stored):
    ids = world["a"]
    wt = await _in_review(sessions, ids, head=stored)
    matching = await _approval(sessions, ids["company"], wt.id, head=stored)
    await _refused(_approve(sessions, ids, wt, matching), "approval_required")
    assert await _status(sessions, wt) == "review"


async def test_head_moving_during_approval_loses_with_409(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids, head=HEAD)
    bound = await _approval(sessions, ids["company"], wt.id, head=HEAD)
    async with sessions() as slow:
        svc = WorktreeService(slow, _manager(ids["company"]))
        # Keep the reference so the identity map serves this stale row.
        stale = await svc.get(wt.id)
        assert stale.head_commit == HEAD
        await _set_head(sessions, wt.id, NEW_HEAD)
        # The check passes against the stale head; the conditional write does not.
        await _refused(svc.transition(wt.id, "approved", approval_id=bound), "conflict")
    assert await _status(sessions, wt) == "review"


# ── Approval expiry ──────────────────────────────────────────────────────


async def test_approval_without_expiry_is_accepted(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    bound = await _approval(sessions, ids["company"], wt.id, expires_at=None)
    assert (await _approve(sessions, ids, wt, bound)).status == "approved"


async def test_approval_expiring_in_the_future_is_accepted(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    later = _utcnow() + timedelta(hours=1)
    bound = await _approval(sessions, ids["company"], wt.id, expires_at=later)
    assert (await _approve(sessions, ids, wt, bound)).status == "approved"


@pytest.mark.parametrize("ago", [timedelta(seconds=1), timedelta(days=30)])
async def test_expired_approved_approval_cannot_approve(sessions, world, ago):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    expired = await _approval(
        sessions, ids["company"], wt.id, status="approved", expires_at=_utcnow() - ago
    )
    err = await _refused(_approve(sessions, ids, wt, expired), "approval_required")
    assert err.status_code == 409
    assert await _status(sessions, wt) == "review"


def _detached(world, **approval_fields) -> tuple[Approval, AgentWorktree]:
    """An unsaved worktree at HEAD and an approval of it, for boundary checks."""
    wt = AgentWorktree(
        id=uuid.uuid4(),
        company_id=world["a"]["company"],
        repository_id=world["a"]["repo"],
        agent_id=world["a"]["agent"],
        branch="b",
        relative_path="p",
        base_ref="HEAD",
        base_commit=SHA,
        head_commit=HEAD,
        created_by="m@example.test",
    )
    fields = {
        "company_id": world["a"]["company"],
        "type": WORKTREE_APPROVAL_TYPE,
        "status": "approved",
        "payload": {"worktree_id": str(wt.id), "head_commit": HEAD},
        "decided_by": APPROVER,
        **approval_fields,
    }
    return Approval(**fields), wt


def test_expiry_boundary_is_exclusive(world):
    moment = datetime(2026, 1, 1, 12, 0, 0)
    approval, wt = _detached(world, expires_at=moment)
    with pytest.raises(WorktreeError) as exc:
        check_worktree_approval(approval, wt, now=moment)
    assert exc.value.reason == "approval_required"
    check_worktree_approval(approval, wt, now=moment - timedelta(microseconds=1))


def test_timezone_aware_expiry_is_compared_in_utc(world):
    # 13:00 at UTC+2 is 11:00 UTC: past at 12:00 UTC, not yet at 10:59 UTC.
    approval, wt = _detached(
        world, expires_at=datetime(2026, 1, 1, 13, 0, tzinfo=timezone(timedelta(hours=2)))
    )
    with pytest.raises(WorktreeError):
        check_worktree_approval(approval, wt, now=datetime(2026, 1, 1, 12, 0))
    check_worktree_approval(approval, wt, now=datetime(2026, 1, 1, 10, 59))


# ── Self-approval ────────────────────────────────────────────────────────


async def _decided_through_service(sessions, ids, wt, decider: Principal) -> uuid.UUID:
    """Request and approve a worktree approval the way the approval routes do."""
    async with sessions() as s:
        service = ApprovalService(s)
        approval = await service.request_approval(
            ids["company"],
            WORKTREE_APPROVAL_TYPE,
            ids["agent"],
            payload={"worktree_id": str(wt.id), "head_commit": wt.head_commit},
        )
        await service.approve(approval.id, decider.display_name)
        await s.commit()
        return approval.id


async def test_worktree_creator_cannot_approve_their_own_worktree(sessions, world):
    ids = world["a"]
    creator = _manager(ids["company"])
    wt = await _in_review(sessions, ids)
    async with sessions() as s:
        wt = await s.get(AgentWorktree, wt.id)
    assert wt.created_by == creator.display_name
    own = await _decided_through_service(sessions, ids, wt, creator)
    err = await _refused(_approve(sessions, ids, wt, own), "approval_required")
    assert err.status_code == 409
    assert await _status(sessions, wt) == "review"


async def test_another_approver_can_approve_the_worktree(sessions, world):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    async with sessions() as s:
        wt = await s.get(AgentWorktree, wt.id)
    other = Principal(
        kind="user", company_id=ids["company"], role="manager", email="other@example.test"
    )
    theirs = await _decided_through_service(sessions, ids, wt, other)
    assert (await _approve(sessions, ids, wt, theirs)).status == "approved"


@pytest.mark.parametrize("decider", [None, ""])
async def test_approval_without_a_recorded_decider_is_refused(sessions, world, decider):
    ids = world["a"]
    wt = await _in_review(sessions, ids)
    anonymous = await _approval(sessions, ids["company"], wt.id, decided_by=decider)
    await _refused(_approve(sessions, ids, wt, anonymous), "approval_required")
    assert await _status(sessions, wt) == "review"


def test_transition_takes_no_commit_id_from_the_caller():
    # Heads and the merge commit are read from git; there is no way to pass one.
    params = inspect.signature(WorktreeService.transition).parameters
    assert not {"merged_commit", "head_commit", "base_commit"} & set(params)


async def test_merging_without_the_approval_that_approved_it_is_refused(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    await _update(sessions, wt.id, status="approved", head_commit=HEAD)
    async with sessions() as s:
        svc = WorktreeService(s, _manager(ids["company"]))
        await _refused(svc.transition(wt.id, "merged"), "approval_required")
    assert await _status(sessions, wt) == "approved"


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
