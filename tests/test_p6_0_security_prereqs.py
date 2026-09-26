"""P6.0: security prerequisites on the repository and approval routes.

Repository routes are tenant-scoped through the authenticated principal,
need read:/write:repository, and only run git inside a clone that resolves
under ``settings.repository_roots``. ``/tree`` cannot be walked out of the
clone and ``/diff`` cannot be fed git options: the demonstrated
``base=--output=<path>`` request used to make git write a file of the
caller's choosing on the server.

Approving or rejecting needs approve:approval, and the decision is recorded
against the authenticated principal whatever the request body claims.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import approvals, repositories
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.company import Company
from nexus.models.governance import Approval
from nexus.models.repository import Repository

HAS_GIT = shutil.which("git") is not None


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture
async def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p6_0.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    monkeypatch.setattr(settings, "repository_roots", str(tmp_path / "repos" / "{company_id}"))

    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.commit()

    root = tmp_path / "repos" / str(acme.id)
    clone = root / "demo"
    clone.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("host file")

    if HAS_GIT:
        _git(clone, "init", "-q")
        (clone / "a.txt").write_text("one\n")
        _git(clone, "add", "a.txt")
        _git(clone, "commit", "-q", "-m", "first")
        (clone / "a.txt").write_text("two\n")
        _git(clone, "commit", "-q", "-am", "second")

    async with factory() as db:
        inside = Repository(company_id=acme.id, name="demo", url="u", local_path=str(clone.resolve()))
        # A row written before the roots existed, pointing outside every root.
        legacy = Repository(company_id=acme.id, name="legacy", url="u", local_path=str(outside))
        pending = [Approval(company_id=acme.id, type="deploy") for _ in range(3)]
        foreign = Approval(company_id=other.id, type="deploy")
        db.add_all([inside, legacy, *pending, foreign])
        await db.commit()

    principals = {
        "admin": Principal(kind="user", company_id=acme.id, role="admin", user_id=uuid.uuid4()),
        "manager": Principal(kind="user", company_id=acme.id, role="manager", user_id=uuid.uuid4(),
                             email="manager@acme.test"),
        "viewer": Principal(kind="user", company_id=acme.id, role="viewer", user_id=uuid.uuid4()),
        "agent": Principal(kind="run", company_id=acme.id, role="agent", run_id=uuid.uuid4(),
                           agent_id=uuid.uuid4()),
        "outsider": Principal(kind="user", company_id=other.id, role="admin", user_id=uuid.uuid4()),
    }
    app = FastAPI()
    app.include_router(repositories.router)
    app.include_router(approvals.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers["x-test-principal"]]
        return await call_next(request)

    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield SimpleNamespace(
        http=http, factory=factory, acme=acme.id, other=other.id, tmp=tmp_path, root=root,
        clone=clone, outside=outside, repo=inside.id, legacy=legacy.id,
        pending=[a.id for a in pending], foreign=foreign.id, principals=principals,
    )
    await http.aclose()
    await engine.dispose()


def call(w, who, method, url, **kwargs):
    return w.http.request(method, url, headers={"x-test-principal": who}, **kwargs)


# ---------------------------------------------------------------- repositories


async def test_company_path_is_scoped_to_the_principal(world):
    w = world
    for method, url in (
        ("GET", f"/api/v1/companies/{w.acme}/repos"),
        ("GET", f"/api/v1/companies/{w.acme}/repos/stats"),
        ("POST", f"/api/v1/companies/{w.acme}/repos"),
    ):
        r = await call(w, "outsider", method, url, json={"name": "x", "url": "u"})
        assert r.status_code == 403, (method, url, r.text)
    r = await call(w, "admin", "GET", f"/api/v1/companies/{w.acme}/repos")
    assert r.status_code == 200 and len(r.json()) == 2


async def test_only_admin_can_connect_or_change_a_repository(world):
    w = world
    body = {"name": "new", "url": "u", "local_path": str(w.root / "new")}
    for who in ("viewer", "manager", "agent"):
        r = await call(w, who, "POST", f"/api/v1/companies/{w.acme}/repos", json=body)
        assert r.status_code == 403, who
        r = await call(w, who, "PUT", f"/api/v1/repos/{w.repo}", json={"name": "renamed"})
        assert r.status_code == 403, who
        r = await call(w, who, "DELETE", f"/api/v1/repos/{w.repo}")
        assert r.status_code == 403, who
        r = await call(w, who, "POST", f"/api/v1/repos/{w.repo}/sync")
        assert r.status_code == 403, who
    r = await call(w, "admin", "POST", f"/api/v1/companies/{w.acme}/repos", json=body)
    assert r.status_code == 201
    assert r.json()["local_path"] == str((w.root / "new").resolve())


async def test_viewer_and_manager_can_read(world):
    w = world
    for who in ("viewer", "manager"):
        r = await call(w, who, "GET", f"/api/v1/repos/{w.repo}")
        assert r.status_code == 200, who
    r = await call(w, "agent", "GET", f"/api/v1/repos/{w.repo}")
    assert r.status_code == 403


async def test_local_path_outside_roots_is_refused_on_write(world):
    w = world
    for bad in (str(w.outside), str(w.root / ".." / ".." / "outside"), str(w.tmp / "repos" / str(w.other))):
        r = await call(w, "admin", "POST", f"/api/v1/companies/{w.acme}/repos",
                       json={"name": "x", "url": "u", "local_path": bad})
        assert r.status_code == 422, bad
        r = await call(w, "admin", "PUT", f"/api/v1/repos/{w.repo}", json={"local_path": bad})
        assert r.status_code == 422, bad


async def test_existing_row_outside_roots_is_refused_on_use(world):
    w = world
    for method, suffix in (("POST", "sync"), ("GET", "commits"), ("GET", "tree"), ("GET", "diff")):
        r = await call(w, "admin", method, f"/api/v1/repos/{w.legacy}/{suffix}")
        assert r.status_code == 409, (suffix, r.text)


@pytest.mark.parametrize("path", ["..", "../..", "../../outside", "sub/../../.."])
async def test_tree_refuses_parent_traversal(world, path):
    r = await call(world, "viewer", "GET", f"/api/v1/repos/{world.repo}/tree", params={"path": path})
    assert r.status_code == 400


async def test_tree_refuses_absolute_paths(world):
    w = world
    for path in (str(w.outside), "/etc", "\\Windows", "C:\\Windows", "C:Windows"):
        r = await call(w, "viewer", "GET", f"/api/v1/repos/{w.repo}/tree", params={"path": path})
        if os.name != "nt" and path.startswith(("\\", "C:")):
            # Backslash and drive letters are ordinary name characters on POSIX.
            assert r.status_code in (200, 400)
            assert "secret.txt" not in r.text
            continue
        assert r.status_code == 400, path


def _link_dir(link, target) -> bool:
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False


def _junction(link, target) -> bool:
    if os.name != "nt":
        return False
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    return done.returncode == 0


@pytest.mark.parametrize("make", [_link_dir, _junction], ids=["symlink", "junction"])
async def test_tree_does_not_follow_links_out_of_the_clone(world, make):
    w = world
    link = w.clone / "escape"
    if not make(link, w.outside):
        pytest.skip("cannot create this kind of link here")
    r = await call(w, "viewer", "GET", f"/api/v1/repos/{w.repo}/tree", params={"path": "escape"})
    assert r.status_code == 400
    r = await call(w, "viewer", "GET", f"/api/v1/repos/{w.repo}/tree")
    assert r.status_code == 200
    entry = next(e for e in r.json()["entries"] if e["name"] == "escape")
    assert entry["type"] == "symlink" and "children" not in entry
    assert "secret.txt" not in r.text


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
@pytest.mark.parametrize("field", ["base", "target"])
async def test_diff_output_option_injection_is_blocked(world, field):
    """The recon exploit: git read ``--output=<path>..HEAD`` as an option."""
    w = world
    pwned = w.tmp / "pwned"
    for value in (f"--output={pwned}", f"--output={pwned}..HEAD", "-p", "--no-index"):
        r = await call(w, "viewer", "GET", f"/api/v1/repos/{w.repo}/diff", params={field: value})
        assert r.status_code == 400, (value, r.text)
    assert not any(p.name.startswith("pwned") for p in w.tmp.rglob("pwned*"))


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
@pytest.mark.parametrize("ref", ["HEAD HEAD", "HEAD\n", "no-such-ref", "x" * 300, "HEAD\x00"])
async def test_diff_refuses_malformed_or_unknown_refs(world, ref):
    r = await call(world, "viewer", "GET", f"/api/v1/repos/{world.repo}/diff", params={"base": ref})
    assert r.status_code == 400


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
async def test_diff_between_real_commits_still_works(world):
    r = await call(world, "viewer", "GET", f"/api/v1/repos/{world.repo}/diff")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base"] == "HEAD~1" and body["target"] == "HEAD"
    assert "-one" in body["diff"] and "+two" in body["diff"]
    assert "a.txt" in body["stat"]


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
async def test_commits_read_the_confined_clone(world):
    r = await call(world, "viewer", "GET", f"/api/v1/repos/{world.repo}/commits")
    assert r.status_code == 200
    assert [c["message"] for c in r.json()] == ["second", "first"]


# ------------------------------------------------------------------ approvals


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_viewer_and_agent_cannot_decide(world, action):
    w = world
    for who in ("viewer", "agent"):
        r = await call(w, who, "POST", f"/api/v1/approvals/{w.pending[0]}/{action}",
                       json={"decided_by": "admin@acme.test"})
        assert r.status_code == 403, who
    async with w.factory() as db:
        assert (await db.get(Approval, w.pending[0])).status == "pending"


@pytest.mark.parametrize("action,status", [("approve", "approved"), ("reject", "rejected")])
async def test_decision_is_recorded_against_the_principal(world, action, status):
    w = world
    r = await call(w, "manager", "POST", f"/api/v1/approvals/{w.pending[1]}/{action}",
                   json={"decided_by": "spoofed-ceo", "decision_note": "ok"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == status
    assert r.json()["decided_by"] == "manager@acme.test"
    async with w.factory() as db:
        stored = await db.get(Approval, w.pending[1])
        assert stored.decided_by == "manager@acme.test" and stored.decision_note == "ok"


async def test_body_without_decided_by_is_accepted(world):
    w = world
    r = await call(w, "admin", "POST", f"/api/v1/approvals/{w.pending[2]}/approve", json={})
    assert r.status_code == 200
    assert r.json()["decided_by"] == w.principals["admin"].display_name


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_cannot_decide_another_companys_approval(world, action):
    w = world
    r = await call(w, "admin", "POST", f"/api/v1/approvals/{w.foreign}/{action}", json={})
    assert r.status_code == 404
    async with w.factory() as db:
        assert (await db.get(Approval, w.foreign)).status == "pending"


async def test_approval_company_paths_are_scoped(world):
    w = world
    r = await call(w, "outsider", "GET", f"/api/v1/companies/{w.acme}/approvals/pending")
    assert r.status_code == 403
    r = await call(w, "outsider", "POST", f"/api/v1/companies/{w.acme}/approvals",
                   json={"type": "deploy", "requested_by_agent_id": str(uuid.uuid4())})
    assert r.status_code == 403
    r = await call(w, "viewer", "GET", f"/api/v1/companies/{w.acme}/approvals/pending")
    assert r.status_code == 200 and len(r.json()) == 3
