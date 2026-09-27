"""P6.4: the AgentWorktree HTTP API.

Requests go over HTTP through the real router and its dependencies; a test
middleware places the principal where the auth middleware would. The database
is file SQLite with foreign keys on, and each company has a real git
repository under a temporary repository root. The routes only call
WorktreeService, so these tests check what the HTTP layer adds or must keep:
authentication, RBAC, tenant scoping, strict request bodies, the error
mapping, serialization and audit.
"""

import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401  (registers every table)
from nexus.api.routes import worktrees as api
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.agent_worktree import AgentWorktree
from nexus.models.company import Company
from nexus.models.governance import Approval, AuditLog
from nexus.models.repository import Repository
from nexus.models.task import Task
from nexus.services import worktree_service
from nexus.services.worktree_service import (
    WORKTREE_APPROVAL_TYPE,
    WorktreeError,
    WorktreeService,
    worktree_path,
)

HEAD = "1" * 40
NEW_HEAD = "2" * 40
APPROVER = "approver@example.test"
FIELDS = {
    "id",
    "company_id",
    "repository_id",
    "agent_id",
    "session_id",
    "task_id",
    "branch",
    "base_ref",
    "base_commit",
    "head_commit",
    "merged_commit",
    "relative_path",
    "status",
    "approval_id",
    "created_by",
    "created_at",
    "updated_at",
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
    return path


@pytest.fixture
async def w(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        # The sqlite3 driver opens no transaction before a SAVEPOINT, so releasing
        # the service's savepoint would commit the insert on its own. Emitting
        # BEGIN ourselves (SQLAlchemy's documented pysqlite recipe) gives the
        # transaction semantics Postgres has, which the rollback tests rely on.
        dbapi_conn.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    monkeypatch.setattr(settings, "repository_roots", str(tmp_path / "repos" / "{company_id}"))
    monkeypatch.setattr(settings, "worktree_root", str(tmp_path / "wt" / "{company_id}"))

    ids: dict = {"tmp": tmp_path, "factory": factory}
    async with factory() as db:
        for key in ("a", "b"):
            company = Company(name=f"co-{key}")
            db.add(company)
            await db.flush()
            clone = _make_repo(tmp_path / "repos" / str(company.id) / "r")
            repo = Repository(company_id=company.id, name="r", url="u", local_path=str(clone))
            agent = Agent(company_id=company.id, name="ag", role="dev")
            other_agent = Agent(company_id=company.id, name="ag2", role="dev")
            db.add_all([repo, agent, other_agent])
            await db.flush()
            session = AgentSessionRecord(company_id=company.id, agent_id=agent.id)
            task = Task(company_id=company.id, title="t")
            approval = Approval(company_id=company.id, type=WORKTREE_APPROVAL_TYPE)
            db.add_all([session, task, approval])
            await db.flush()
            ids[key] = {
                "company": company.id,
                "repo": repo.id,
                "clone": clone,
                "agent": agent.id,
                "other_agent": other_agent.id,
                "session": session.id,
                "task": task.id,
                "approval": approval.id,
            }
        await db.commit()

    a, b = ids["a"], ids["b"]
    run_id = uuid.uuid4()
    principals = {
        "viewer": Principal(kind="user", company_id=a["company"], role="viewer", email="v@a"),
        "manager": Principal(kind="user", company_id=a["company"], role="manager", email="m@a"),
        "admin": Principal(kind="user", company_id=a["company"], role="admin", email="ad@a"),
        "agent_role": Principal(kind="user", company_id=a["company"], role="agent", email="g@a"),
        "service": Principal(
            kind="service", company_id=a["company"], role="admin", api_key_id=uuid.uuid4()
        ),
        # A run token always carries role "agent" (auth middleware).
        "run": Principal(
            kind="run", company_id=a["company"], role="agent", run_id=run_id, agent_id=a["agent"]
        ),
        # Not issued today; shows the service's own-agent rule still holds if a
        # run ever held write:worktree.
        "run_writer": Principal(
            kind="run", company_id=a["company"], role="manager", run_id=run_id, agent_id=a["agent"]
        ),
        "outsider": Principal(kind="user", company_id=b["company"], role="admin", email="x@b"),
    }
    ids["principals"] = principals

    app = FastAPI()
    app.include_router(api.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        who = request.headers.get("x-test-principal")
        if who:
            request.state.principal = principals[who]
        return await call_next(request)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    ids["client"] = httpx.AsyncClient(transport=transport, base_url="http://test")
    yield ids
    await ids["client"].aclose()
    await engine.dispose()


async def _call(w, who, method, path, body=None, **kw):
    headers = {"x-test-principal": who} if who else {}
    return await w["client"].request(method, path, json=body, headers=headers, **kw)


def _body(ids, **extra) -> dict:
    return {"repository_id": str(ids["repo"]), "agent_id": str(ids["agent"]), **extra}


async def _create(w, who="manager", **extra) -> dict:
    r = await _call(w, who, "POST", "/api/v1/worktrees", _body(w["a"], **extra))
    assert r.status_code == 201, r.text
    return r.json()


async def _move(w, wt_id, to, who="manager", **extra):
    return await _call(
        w, who, "POST", f"/api/v1/worktrees/{wt_id}/transition", {"status": to, **extra}
    )


async def _row(w, wt_id) -> AgentWorktree | None:
    async with w["factory"]() as db:
        return await db.get(AgentWorktree, uuid.UUID(str(wt_id)))


async def _count(w) -> int:
    async with w["factory"]() as db:
        return len((await db.execute(select(AgentWorktree))).scalars().all())


async def _audits(w, action=None) -> list[AuditLog]:
    async with w["factory"]() as db:
        stmt = select(AuditLog).where(AuditLog.resource_type == "worktree")
        if action:
            stmt = stmt.where(AuditLog.action == action)
        return list((await db.execute(stmt.order_by(AuditLog.created_at))).scalars())


async def _set(w, wt_id, **values) -> None:
    async with w["factory"]() as db:
        row = await db.get(AgentWorktree, uuid.UUID(str(wt_id)))
        for key, value in values.items():
            setattr(row, key, value)
        await db.commit()


async def _approval(w, wt_id, *, head=HEAD, decided_by=APPROVER, expires_at=None) -> str:
    async with w["factory"]() as db:
        row = Approval(
            company_id=w["a"]["company"],
            type=WORKTREE_APPROVAL_TYPE,
            status="approved",
            payload={"worktree_id": str(wt_id), "head_commit": head},
            decided_by=decided_by,
            expires_at=expires_at,
        )
        db.add(row)
        await db.commit()
        return str(row.id)


async def _in_review(w, head=HEAD) -> dict:
    wt = await _create(w)
    await _set(w, wt["id"], status="review", head_commit=head)
    return wt


async def _reviewed_in_git(w) -> dict:
    """A worktree activated on disk, with one commit on its branch, moved to review."""
    wt = await _create(w)
    assert (await _move(w, wt["id"], "active")).status_code == 200
    path = worktree_path(w["a"]["company"], wt["relative_path"])
    (path / "work.txt").write_text("work\n")
    _git(path, "add", "work.txt")
    _git(path, "commit", "-q", "-m", "work")
    r = await _move(w, wt["id"], "review")
    assert r.status_code == 200, r.text
    return r.json()


def _routes() -> list[tuple[str, str]]:
    wt = uuid.uuid4()
    return [
        ("GET", "/api/v1/worktrees"),
        ("POST", "/api/v1/worktrees"),
        ("GET", f"/api/v1/worktrees/{wt}"),
        ("POST", f"/api/v1/worktrees/{wt}/transition"),
        ("POST", f"/api/v1/worktrees/{wt}/archive"),
    ]


# ── Authentication and RBAC ──────────────────────────────────────────────


def test_every_route_declares_a_permission():
    for route in api.router.routes:
        assert route.dependencies, f"{route.path} {route.methods} unguarded"


@pytest.mark.parametrize("method,path", _routes())
async def test_anonymous_is_401(w, method, path):
    body = {"status": "active"} if path.endswith("transition") else _body(w["a"])
    r = await _call(w, None, method, path, body if method == "POST" else None)
    assert r.status_code == 401


async def test_viewer_can_read(w):
    wt = await _create(w)
    r = await _call(w, "viewer", "GET", "/api/v1/worktrees")
    assert r.status_code == 200 and [x["id"] for x in r.json()] == [wt["id"]]
    r = await _call(w, "viewer", "GET", f"/api/v1/worktrees/{wt['id']}")
    assert r.status_code == 200 and r.json()["id"] == wt["id"]


async def test_viewer_cannot_write(w):
    wt = await _create(w)
    r = await _call(w, "viewer", "POST", "/api/v1/worktrees", _body(w["a"]))
    assert r.status_code == 403
    assert (await _move(w, wt["id"], "active", who="viewer")).status_code == 403
    r = await _call(w, "viewer", "POST", f"/api/v1/worktrees/{wt['id']}/archive")
    assert r.status_code == 403
    assert await _count(w) == 1
    assert (await _row(w, wt["id"])).status == "created"
    assert len(await _audits(w)) == 1  # only the manager's create


@pytest.mark.parametrize("who", ["manager", "admin", "service"])
async def test_writers_can_create_and_transition(w, who):
    wt = await _create(w, who=who)
    r = await _move(w, wt["id"], "active", who=who)
    assert r.status_code == 200 and r.json()["status"] == "active"
    r = await _call(w, who, "POST", f"/api/v1/worktrees/{wt['id']}/archive")
    assert r.status_code == 200 and r.json()["status"] == "archived"


@pytest.mark.parametrize("who", ["agent_role", "run"])
@pytest.mark.parametrize("method,path", _routes())
async def test_agent_role_and_run_tokens_have_no_worktree_access(w, who, method, path):
    body = {"status": "active"} if path.endswith("transition") else _body(w["a"])
    r = await _call(w, who, method, path, body if method == "POST" else None)
    assert r.status_code == 403
    assert await _count(w) == 0


async def test_run_may_only_create_for_its_own_agent(w):
    a = w["a"]
    body = _body(a, agent_id=str(a["other_agent"]))
    r = await _call(w, "run_writer", "POST", "/api/v1/worktrees", body)
    assert r.status_code == 403
    assert "own agent" in r.json()["detail"]
    assert await _count(w) == 0

    wt = await _create(w, who="run_writer")
    run = w["principals"]["run_writer"]
    assert (wt["agent_id"], wt["created_by"]) == (str(a["agent"]), run.display_name)


# ── Tenant isolation ─────────────────────────────────────────────────────


async def test_other_companys_worktree_is_404(w):
    wt = await _create(w)
    r = await _call(w, "outsider", "GET", f"/api/v1/worktrees/{wt['id']}")
    assert r.status_code == 404
    assert str(w["a"]["repo"]) not in r.text and wt["branch"] not in r.text


async def test_list_never_shows_another_company(w):
    mine = await _create(w)
    r = await _call(w, "outsider", "GET", "/api/v1/worktrees")
    assert r.status_code == 200 and r.json() == []
    # Filtering by the other tenant's ids finds nothing either.
    for key in ("repository_id", "agent_id", "session_id"):
        source = {"repository_id": "repo", "agent_id": "agent", "session_id": "session"}[key]
        r = await _call(
            w, "outsider", "GET", "/api/v1/worktrees", params={key: str(w["a"][source])}
        )
        assert r.json() == []
    r = await _call(w, "manager", "GET", "/api/v1/worktrees")
    assert [x["id"] for x in r.json()] == [mine["id"]]


@pytest.mark.parametrize(
    "field", ["repository_id", "agent_id", "session_id", "task_id", "approval_id"]
)
async def test_create_refuses_references_into_another_company(w, field):
    b = w["b"]
    source = {
        "repository_id": "repo",
        "agent_id": "agent",
        "session_id": "session",
        "task_id": "task",
        "approval_id": "approval",
    }[field]
    r = await _call(
        w, "manager", "POST", "/api/v1/worktrees", _body(w["a"], **{field: str(b[source])})
    )
    assert r.status_code == 404, r.text
    assert await _count(w) == 0
    assert await _audits(w) == []


async def test_transition_and_archive_of_another_companys_worktree_are_404(w):
    wt = await _create(w)
    assert (await _move(w, wt["id"], "active", who="outsider")).status_code == 404
    r = await _call(w, "outsider", "POST", f"/api/v1/worktrees/{wt['id']}/archive")
    assert r.status_code == 404
    assert (await _row(w, wt["id"])).status == "created"


async def test_spoofed_company_id_is_rejected_and_ignored(w):
    r = await _call(
        w,
        "manager",
        "POST",
        "/api/v1/worktrees",
        _body(w["a"], company_id=str(w["b"]["company"])),
    )
    assert r.status_code == 422
    assert await _count(w) == 0

    mine = await _create(w)
    assert mine["company_id"] == str(w["a"]["company"])
    # A query parameter naming another company does not change the scope.
    r = await _call(
        w, "manager", "GET", "/api/v1/worktrees", params={"company_id": str(w["b"]["company"])}
    )
    assert [x["id"] for x in r.json()] == [mine["id"]]


@pytest.mark.parametrize("spoof", [{"created_by": "someone@else"}, {"actor": "someone@else"}])
async def test_spoofed_creator_is_rejected(w, spoof):
    r = await _call(w, "manager", "POST", "/api/v1/worktrees", _body(w["a"], **spoof))
    assert r.status_code == 422
    assert await _count(w) == 0
    wt = await _create(w)
    assert wt["created_by"] == "m@a"


SERVER_FIELDS = {
    "id": str(uuid.uuid4()),
    "branch": "main",
    "relative_path": "../../escape",
    "base_commit": HEAD,
    "head_commit": HEAD,
    "merged_commit": HEAD,
    "status": "approved",
    "created_at": "2020-01-01T00:00:00",
}


@pytest.mark.parametrize("field", sorted(SERVER_FIELDS))
async def test_create_rejects_server_owned_fields(w, field):
    r = await _call(
        w, "manager", "POST", "/api/v1/worktrees", _body(w["a"], **{field: SERVER_FIELDS[field]})
    )
    assert r.status_code == 422
    assert await _count(w) == 0


@pytest.mark.parametrize(
    "spoof",
    [
        {"head_commit": HEAD},
        {"base_commit": HEAD},
        {"branch": "main"},
        {"relative_path": "../x"},
        {"company_id": str(uuid.uuid4())},
        {"created_by": "x"},
        {"approved": True},
    ],
)
async def test_transition_rejects_server_owned_fields(w, spoof):
    wt = await _in_review(w, head=None)
    r = await _move(w, wt["id"], "approved", **spoof)
    assert r.status_code == 422
    row = await _row(w, wt["id"])
    assert (row.status, row.head_commit, row.branch) == ("review", None, wt["branch"])


# ── Create, list, get ────────────────────────────────────────────────────


async def test_create_returns_the_server_generated_record(w):
    a = w["a"]
    wt = await _create(
        w, session_id=str(a["session"]), task_id=str(a["task"]), approval_id=str(a["approval"])
    )
    assert set(wt) == FIELDS
    assert wt["company_id"] == str(a["company"])
    assert wt["status"] == "created"
    assert wt["branch"] == f"nexus/wt-{wt['id']}"
    assert wt["relative_path"] == wt["id"]
    assert wt["base_ref"] == "HEAD"
    assert wt["base_commit"] == _git(a["clone"], "rev-parse", "HEAD")
    assert wt["head_commit"] is None and wt["merged_commit"] is None
    assert (wt["session_id"], wt["task_id"], wt["approval_id"]) == (
        str(a["session"]),
        str(a["task"]),
        str(a["approval"]),
    )
    assert wt["created_by"] == "m@a"


async def test_responses_carry_no_absolute_path(w):
    wt = await _create(w)
    root = str(w["tmp"])
    for r in (
        await _call(w, "manager", "GET", "/api/v1/worktrees"),
        await _call(w, "manager", "GET", f"/api/v1/worktrees/{wt['id']}"),
        await _move(w, wt["id"], "active"),
    ):
        assert root not in r.text and root.replace("\\", "/") not in r.text
        assert "\\\\" not in r.text
    assert not Path(wt["relative_path"]).is_absolute()


async def test_create_does_not_touch_the_filesystem(w):
    wt = await _create(w)
    path = worktree_path(w["a"]["company"], wt["relative_path"])
    assert not path.exists()
    assert wt["branch"] not in _git(w["a"]["clone"], "branch", "--list")


async def test_base_ref_is_resolved_server_side(w):
    a = w["a"]
    _git(a["clone"], "tag", "v1")
    wt = await _create(w, base_ref="v1")
    assert (wt["base_ref"], wt["base_commit"]) == (
        "v1",
        _git(a["clone"], "rev-parse", "v1^{commit}"),
    )


async def test_list_is_newest_first_and_filters(w):
    a = w["a"]
    first = await _create(w)
    second = await _create(w, agent_id=str(a["other_agent"]))
    await _move(w, first["id"], "active")

    r = await _call(w, "manager", "GET", "/api/v1/worktrees")
    assert [x["id"] for x in r.json()] == [second["id"], first["id"]]
    r = await _call(w, "manager", "GET", "/api/v1/worktrees", params={"status": "active"})
    assert [x["id"] for x in r.json()] == [first["id"]]
    r = await _call(
        w, "manager", "GET", "/api/v1/worktrees", params={"agent_id": str(a["other_agent"])}
    )
    assert [x["id"] for x in r.json()] == [second["id"]]
    r = await _call(w, "manager", "GET", "/api/v1/worktrees", params={"status": "bogus"})
    assert r.status_code == 422


async def test_get_unknown_worktree_is_404(w):
    r = await _call(w, "manager", "GET", f"/api/v1/worktrees/{uuid.uuid4()}")
    assert r.status_code == 404


# ── Malformed requests ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"agent_id": str(uuid.uuid4())},
        {"repository_id": str(uuid.uuid4())},
        {"repository_id": "not-a-uuid", "agent_id": str(uuid.uuid4())},
        {"repository_id": str(uuid.uuid4()), "agent_id": str(uuid.uuid4()), "base_ref": ""},
        {"repository_id": str(uuid.uuid4()), "agent_id": str(uuid.uuid4()), "base_ref": "x" * 257},
        {"repository_id": str(uuid.uuid4()), "agent_id": str(uuid.uuid4()), "base_ref": 7},
        [],
        "text",
    ],
)
async def test_malformed_create_is_422(w, body):
    r = await _call(w, "manager", "POST", "/api/v1/worktrees", body)
    assert r.status_code == 422
    assert await _count(w) == 0


async def test_non_json_body_is_422(w):
    r = await w["client"].post(
        "/api/v1/worktrees",
        content=b"{not json",
        headers={"x-test-principal": "manager", "content-type": "application/json"},
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "created"},
        {"status": "deleted"},
        {"status": "ACTIVE"},
        {"status": None},
        {"status": "active", "approval_id": str(uuid.uuid4())},
        {"status": "archived", "merged_commit": HEAD},
        {"status": "approved", "merged_commit": HEAD},
        {"status": "approved", "approval_id": "nope"},
        {"status": "merged", "merged_commit": "a" * 65},
    ],
)
async def test_malformed_transition_is_422(w, body):
    wt = await _create(w)
    r = await _call(w, "manager", "POST", f"/api/v1/worktrees/{wt['id']}/transition", body)
    assert r.status_code == 422
    assert (await _row(w, wt["id"])).status == "created"


async def test_non_uuid_path_is_422(w):
    r = await _call(w, "manager", "GET", "/api/v1/worktrees/not-a-uuid")
    assert r.status_code == 422


# ── Service refusals over HTTP ───────────────────────────────────────────


@pytest.mark.parametrize("ref", ["no-such-branch", "--output=/tmp/x", "a b", "HEAD~99"])
async def test_unknown_or_unsafe_base_ref_is_400(w, ref):
    r = await _call(w, "manager", "POST", "/api/v1/worktrees", _body(w["a"], base_ref=ref))
    assert r.status_code == 400
    assert await _count(w) == 0


async def _set_local_path(w, value) -> None:
    async with w["factory"]() as db:
        repo = await db.get(Repository, w["a"]["repo"])
        repo.local_path = value
        await db.commit()


@pytest.mark.parametrize("where", ["none", "not_git", "outside_roots"])
async def test_invalid_repository_is_422(w, where):
    tmp = w["tmp"]
    if where == "none":
        await _set_local_path(w, None)
    elif where == "not_git":
        plain = tmp / "repos" / str(w["a"]["company"]) / "plain"
        plain.mkdir()
        await _set_local_path(w, str(plain))
    else:
        await _set_local_path(w, str(_make_repo(tmp / "elsewhere")))
    r = await _call(w, "manager", "POST", "/api/v1/worktrees", _body(w["a"]))
    assert r.status_code == 422
    assert await _count(w) == 0


async def test_misconfigured_worktree_root_is_500(w, monkeypatch):
    monkeypatch.setattr(settings, "worktree_root", str(w["tmp"] / "wt"))
    r = await _call(w, "manager", "POST", "/api/v1/worktrees", _body(w["a"]))
    assert r.status_code == 500
    assert r.json() == {"detail": "worktree_root must contain {company_id}"}
    assert await _count(w) == 0


async def test_session_of_another_agent_is_422(w):
    a = w["a"]
    body = _body(a, agent_id=str(a["other_agent"]), session_id=str(a["session"]))
    r = await _call(w, "manager", "POST", "/api/v1/worktrees", body)
    assert r.status_code == 422


async def test_second_open_worktree_for_a_session_is_409(w):
    await _create(w, session_id=str(w["a"]["session"]))
    r = await _call(
        w, "manager", "POST", "/api/v1/worktrees", _body(w["a"], session_id=str(w["a"]["session"]))
    )
    assert r.status_code == 409
    assert await _count(w) == 1


EXPECTED_STATUS = {
    "unknown_ref": 400,
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
    "illegal_transition": 409,
    "approval_required": 409,
    "invalid_link": 422,
    "invalid_repository": 422,
    "invalid_path": 422,
    "git_unavailable": 503,
    "misconfigured": 500,
}


@pytest.mark.parametrize("reason", sorted(EXPECTED_STATUS))
async def test_service_error_mapping(w, monkeypatch, reason):
    async def refuse(self, **kw):
        raise WorktreeError(reason, f"refused: {reason}")

    monkeypatch.setattr(WorktreeService, "create", refuse)
    r = await _call(w, "manager", "POST", "/api/v1/worktrees", _body(w["a"]))
    assert r.status_code == EXPECTED_STATUS[reason]
    assert r.json() == {"detail": f"refused: {reason}"}
    assert await _audits(w) == []


def test_mapping_table_matches_the_service():
    assert EXPECTED_STATUS == worktree_service._STATUS_FOR


async def test_unexpected_error_is_a_bare_500(w, monkeypatch):
    async def explode(self, **kw):
        raise RuntimeError("secret internals: postgres://user:pw@db")

    monkeypatch.setattr(WorktreeService, "create", explode)
    r = await _call(w, "manager", "POST", "/api/v1/worktrees", _body(w["a"]))
    assert r.status_code == 500
    assert "secret internals" not in r.text and "Traceback" not in r.text


# ── Lifecycle ────────────────────────────────────────────────────────────


async def test_happy_path_to_merged(w):
    wt = await _reviewed_in_git(w)
    head = wt["head_commit"]
    assert head == _git(w["a"]["clone"], "rev-parse", wt["branch"])
    approval = await _approval(w, wt["id"], head=head)
    r = await _move(w, wt["id"], "approved", approval_id=approval)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["approval_id"], r.json()["head_commit"]) == (
        "approved",
        approval,
        head,
    )
    # A merged_commit in the body is accepted for compatibility and ignored.
    r = await _move(w, wt["id"], "merged", merged_commit="c" * 40)
    assert (r.status_code, r.json()["status"]) == (200, "merged"), r.text
    assert r.json()["merged_commit"] == _git(w["a"]["clone"], "rev-parse", "main")
    r = await _call(w, "manager", "POST", f"/api/v1/worktrees/{wt['id']}/archive")
    assert r.json()["status"] == "archived"


@pytest.mark.parametrize(
    "src,dst",
    [
        ("created", "review"),
        ("created", "approved"),
        ("created", "merged"),
        ("active", "merged"),
        ("review", "merged"),
        ("merged", "active"),
        ("archived", "active"),
    ],
)
async def test_illegal_transition_is_409(w, src, dst):
    wt = await _create(w)
    await _set(w, wt["id"], status=src)
    extra = {"merged_commit": "c" * 40} if dst == "merged" else {}
    r = await _move(w, wt["id"], dst, **extra)
    assert r.status_code == 409
    assert (await _row(w, wt["id"])).status == src


async def test_archived_cannot_be_archived_into_anything_else(w):
    wt = await _create(w)
    await _call(w, "manager", "POST", f"/api/v1/worktrees/{wt['id']}/archive")
    for to in ("active", "review", "approved"):
        assert (await _move(w, wt["id"], to)).status_code == 409


async def test_approving_without_an_approval_is_409(w):
    wt = await _in_review(w)
    r = await _move(w, wt["id"], "approved")
    assert r.status_code == 409
    assert (await _row(w, wt["id"])).status == "review"


async def test_pending_approval_is_409(w):
    wt = await _in_review(w)
    r = await _move(w, wt["id"], "approved", approval_id=str(w["a"]["approval"]))
    assert r.status_code == 409


async def test_expired_approval_is_409(w):
    wt = await _in_review(w)
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    approval = await _approval(w, wt["id"], expires_at=past)
    r = await _move(w, wt["id"], "approved", approval_id=approval)
    assert r.status_code == 409
    assert (await _row(w, wt["id"])).status == "review"


async def test_approval_is_bound_to_the_head_the_server_recorded(w):
    wt = await _in_review(w, head=NEW_HEAD)
    stale = await _approval(w, wt["id"], head=HEAD)
    r = await _move(w, wt["id"], "approved", approval_id=stale)
    assert r.status_code == 409
    # The client cannot claim the head it wants either.
    r = await _move(w, wt["id"], "approved", approval_id=stale, head_commit=HEAD)
    assert r.status_code == 422
    row = await _row(w, wt["id"])
    assert (row.status, row.head_commit) == ("review", NEW_HEAD)


async def test_worktree_without_a_recorded_head_cannot_be_approved(w):
    wt = await _in_review(w, head=None)
    approval = await _approval(w, wt["id"])
    assert (await _move(w, wt["id"], "approved", approval_id=approval)).status_code == 409


async def test_creator_cannot_approve_their_own_worktree(w):
    wt = await _in_review(w)
    own = await _approval(w, wt["id"], decided_by="m@a")
    assert (await _move(w, wt["id"], "approved", approval_id=own)).status_code == 409


async def test_approval_of_another_company_is_404(w):
    wt = await _in_review(w)
    r = await _move(w, wt["id"], "approved", approval_id=str(w["b"]["approval"]))
    assert r.status_code == 404


@pytest.mark.parametrize("merge", [None, "abc", "C" * 40, "c" * 40])
async def test_merge_commit_in_the_body_is_never_recorded(w, merge):
    # Without the approval that approved it the merge is refused, whatever
    # commit the body names, and nothing is written.
    wt = await _create(w)
    await _set(w, wt["id"], status="approved", head_commit=HEAD)
    r = await _move(w, wt["id"], "merged", merged_commit=merge)
    assert r.status_code == 409
    row = await _row(w, wt["id"])
    assert (row.status, row.merged_commit) == ("approved", None)


async def test_reasserting_the_current_status_is_a_quiet_no_op(w):
    wt = await _create(w)
    r = await _move(w, wt["id"], "created")
    assert r.status_code == 422  # "created" is never a target
    await _move(w, wt["id"], "active")
    before = len(await _audits(w))
    r = await _move(w, wt["id"], "active")
    assert (r.status_code, r.json()["status"]) == (200, "active")
    assert len(await _audits(w)) == before


# ── Archive ──────────────────────────────────────────────────────────────


async def test_archive_leaves_directory_and_branch(w, monkeypatch):
    from nexus.runtime.git_runner import GitRunner
    from nexus.runtime.worktree import WorktreeManager

    def forbidden(*a, **kw):
        raise AssertionError("archive must not remove anything")

    monkeypatch.setattr(WorktreeManager, "remove_worktree", forbidden)
    monkeypatch.setattr(GitRunner, "remove_worktree", forbidden)

    a = w["a"]
    wt = await _create(w)
    path = worktree_path(a["company"], wt["relative_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(a["clone"], "worktree", "add", "-q", "-b", wt["branch"], str(path), wt["base_commit"])
    (path / "work.txt").write_text("unmerged work")

    r = await _call(w, "manager", "POST", f"/api/v1/worktrees/{wt['id']}/archive")
    assert (r.status_code, r.json()["status"]) == (200, "archived")
    assert (path / "work.txt").read_text() == "unmerged work"
    assert wt["branch"] in _git(a["clone"], "branch", "--list", wt["branch"])
    assert str(path.resolve()).replace("\\", "/") in _git(a["clone"], "worktree", "list").replace(
        "\\", "/"
    )


async def test_archive_of_unknown_worktree_is_404(w):
    r = await _call(w, "manager", "POST", f"/api/v1/worktrees/{uuid.uuid4()}/archive")
    assert r.status_code == 404


async def test_archive_takes_no_body(w):
    wt = await _create(w)
    r = await _call(
        w, "manager", "POST", f"/api/v1/worktrees/{wt['id']}/archive", {"status": "merged"}
    )
    assert (r.status_code, r.json()["status"]) == (200, "archived")
    assert (await _row(w, wt["id"])).merged_commit is None


# ── Audit ────────────────────────────────────────────────────────────────


async def test_mutations_are_audited_with_the_principal_as_actor(w):
    wt = await _reviewed_in_git(w)
    approval = await _approval(w, wt["id"], head=wt["head_commit"])
    await _move(w, wt["id"], "approved", approval_id=approval)
    await _move(w, wt["id"], "merged", merged_commit="c" * 40)
    await _call(w, "manager", "POST", f"/api/v1/worktrees/{wt['id']}/archive")

    logs = await _audits(w)
    assert [e.action for e in logs] == [
        "worktree.created",
        "worktree.transitioned",
        "worktree.transitioned",
        "worktree.transitioned",
        "worktree.transitioned",
        "worktree.archived",
    ]
    assert {(e.actor_type, e.actor_id, e.resource_id) for e in logs} == {("user", "m@a", wt["id"])}
    assert {e.company_id for e in logs} == {w["a"]["company"]}
    created, activated, reviewed, approved, merged, archived = logs
    assert activated.details["head_commit"] == wt["base_commit"]
    assert (reviewed.details["previous_head"], reviewed.details["head_commit"]) == (
        wt["base_commit"],
        wt["head_commit"],
    )
    assert created.details["branch"] == wt["branch"]
    assert created.details["base_commit"] == wt["base_commit"]
    assert (approved.details["previous_status"], approved.details["status"]) == (
        "review",
        "approved",
    )
    assert approved.details["approval_id"] == approval
    assert merged.details["merged_commit"] == _git(w["a"]["clone"], "rev-parse", "main")
    assert (archived.details["previous_status"], archived.details["status"]) == (
        "merged",
        "archived",
    )


async def test_run_actor_is_recorded_as_the_agent(w):
    wt = await _create(w, who="run_writer")
    [entry] = await _audits(w)
    run = w["principals"]["run_writer"]
    assert (entry.actor_type, entry.actor_id, entry.resource_id) == (
        "agent",
        run.display_name,
        wt["id"],
    )


async def test_reads_and_refusals_are_not_audited(w):
    wt = await _create(w)
    await _call(w, "manager", "GET", "/api/v1/worktrees")
    await _call(w, "manager", "GET", f"/api/v1/worktrees/{wt['id']}")
    await _move(w, wt["id"], "merged", merged_commit="c" * 40)  # illegal
    await _move(w, wt["id"], "active", who="viewer")  # forbidden
    assert [e.action for e in await _audits(w)] == ["worktree.created"]


async def test_failed_audit_write_rolls_the_mutation_back(w, monkeypatch):
    from nexus.governance import audit_service

    wt = await _create(w)
    working = audit_service._chain_in_savepoint

    async def broken(*a, **kw):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit_service, "_chain_in_savepoint", broken)
    r = await _call(w, "manager", "POST", "/api/v1/worktrees", _body(w["a"]))
    assert r.status_code == 500 and "audit store down" not in r.text
    assert await _count(w) == 1
    r = await _move(w, wt["id"], "active")
    assert r.status_code == 500
    assert "retry the same request" in r.json()["detail"]
    assert (await _row(w, wt["id"])).status == "created"
    # The worktree was created on disk before the save failed; retrying reuses it.
    monkeypatch.setattr(audit_service, "_chain_in_savepoint", working)
    r = await _move(w, wt["id"], "active")
    assert r.status_code == 200, r.text
    assert r.json()["head_commit"] == wt["base_commit"]
    listed = _git(w["a"]["clone"], "worktree", "list", "--porcelain")
    assert listed.count("worktree ") == 2  # the clone and this one worktree
