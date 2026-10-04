"""Governance state must be loaded before a company's request is governed, and a company
whose state cannot be loaded is refused, never defaulted to allow.

The load is read-only and tenant-bound (``tenant_session``), so these tests also pin that a
failed load leaves no policy, budget or audit row behind and that one company's failure does
not touch another's.
"""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 - registers every table
from nexus.api import middleware as mw
from nexus.auth.principal import Principal
from nexus.governance import readiness
from nexus.models.company import Company
from nexus.models.policy import Policy


@pytest.fixture
async def engine(tmp_path, monkeypatch):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'gov.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    monkeypatch.setattr(
        "nexus.database.async_session_factory", async_sessionmaker(eng, expire_on_commit=False)
    )
    readiness.reset()
    yield eng
    readiness.reset()
    mw._policy_cache.clear()
    mw._budget_tracker._cache.clear()
    await eng.dispose()


async def _company(engine, name="Acme", budget=10_000, **policy_rules) -> uuid.UUID:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        company = Company(name=name, budget_monthly_cents=budget)
        db.add(company)
        await db.flush()
        if policy_rules:
            db.add(Policy(company_id=company.id, name="p", rules=policy_rules, enabled=True))
        await db.commit()
        return company.id


class _Downstream:
    """Stands in for any route: model call, tool call, spend or a plain read."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


async def _request(downstream, path, method="POST", company_id=None):
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    state = {}
    if company_id is not None:
        state["principal"] = Principal(kind="user", company_id=company_id, role="admin")
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "state": state,
        "query_string": b"",
    }
    await mw.GovernanceMiddleware(downstream)(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], (json.loads(body) if body else {})


async def _rows(engine) -> tuple[int, int]:
    async with async_sessionmaker(engine)() as db:
        policies = (await db.execute(select(func.count()).select_from(Policy))).scalar_one()
        companies = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
    return policies, companies


async def test_first_request_loads_state_and_is_served(engine):
    cid = await _company(engine, budget=500, deny_methods=["DELETE"])
    down = _Downstream()

    assert (await _request(down, "/api/v1/agents", "GET", cid))[0] == 200
    assert readiness.is_ready(cid)
    assert mw._budget_tracker.get_remaining(cid) == 500
    expected = [{"name": "p", "rules": {"deny_methods": ["DELETE"]}, "priority": 0}]
    assert mw._policy_cache[cid] == expected
    # The loaded policy is enforced, so state was really used rather than skipped.
    assert (await _request(down, "/api/v1/agents", "DELETE", cid))[0] == 403


async def test_concurrent_first_requests_share_one_load(engine, monkeypatch):
    cid = await _company(engine)
    loads = 0
    real = readiness._load

    async def counting(company_id):
        nonlocal loads
        loads += 1
        await asyncio.sleep(0.05)
        return await real(company_id)

    monkeypatch.setattr(readiness, "_load", counting)
    down = _Downstream()
    results = await asyncio.gather(
        *(_request(down, "/api/v1/agents", "GET", cid) for _ in range(5))
    )

    assert [s for s, _ in results] == [200] * 5
    assert loads == 1


async def test_initializer_failure_refuses_every_governed_request(engine, monkeypatch):
    cid = await _company(engine)

    async def broken(company_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(readiness, "_load", broken)
    down = _Downstream()
    status, body = await _request(down, "/api/v1/agents/x/chat", "POST", cid)

    assert (status, body["code"]) == (503, "GOVERNANCE_UNAVAILABLE")
    assert "db down" not in json.dumps(body)
    assert down.calls == 0
    assert not readiness.is_ready(cid)
    assert cid not in mw._policy_cache and mw._budget_tracker.get_remaining(cid) is None


async def test_partial_db_failure_leaves_no_state_and_writes_nothing(engine):
    cid = await _company(engine, deny_methods=["DELETE"])
    before = await _rows(engine)
    async with engine.begin() as conn:  # the company read succeeds, the policy read fails
        await conn.execute(text("ALTER TABLE policies RENAME TO policies_gone"))
    down = _Downstream()

    assert (await _request(down, "/api/v1/agents", "GET", cid))[0] == 503

    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE policies_gone RENAME TO policies"))
    assert await _rows(engine) == before
    assert down.calls == 0 and not readiness.is_ready(cid)
    assert cid not in mw._policy_cache and mw._budget_tracker.get_remaining(cid) is None


async def test_failure_while_applying_state_is_not_a_success(engine, monkeypatch):
    """The load finished but the caches could not be filled: still unready, still refused."""
    cid = await _company(engine)

    def boom(*_a, **_k):
        raise RuntimeError("cache write failed")

    monkeypatch.setattr(mw._budget_tracker, "set_budget", boom)
    down = _Downstream()

    assert (await _request(down, "/api/v1/agents", "GET", cid))[0] == 503
    assert not readiness.is_ready(cid) and down.calls == 0
    assert cid not in mw._policy_cache


async def test_unknown_company_is_refused_not_defaulted(engine):
    down = _Downstream()
    assert (await _request(down, "/api/v1/agents", "GET", uuid.uuid4()))[0] == 503
    assert down.calls == 0


async def test_backoff_suppresses_attempts_but_never_allows(engine, monkeypatch):
    cid = await _company(engine)
    real = readiness._load
    attempts = 0
    healthy = False

    async def flaky(company_id):
        nonlocal attempts
        attempts += 1
        if not healthy:
            raise RuntimeError("down")
        return await real(company_id)

    monkeypatch.setattr(readiness, "_load", flaky)
    down = _Downstream()
    assert (await _request(down, "/api/v1/agents", "GET", cid))[0] == 503
    assert attempts == 1

    healthy = True  # the database recovered, but the back-off window is still open
    for method, path in (("GET", "/api/v1/agents"), ("POST", "/api/v1/agents/x/chat")):
        assert (await _request(down, path, method, cid))[0] == 503
    assert attempts == 1 and down.calls == 0

    readiness._retry_at[cid] = 0.0  # window elapsed
    assert (await _request(down, "/api/v1/agents", "GET", cid))[0] == 200
    assert attempts == 2 and readiness.is_ready(cid)


async def test_one_company_failing_does_not_affect_another(engine, monkeypatch):
    a = await _company(engine, name="A")
    b = await _company(engine, name="B", budget=700)
    real = readiness._load

    async def only_a_fails(company_id):
        if company_id == a:
            raise RuntimeError("down")
        return await real(company_id)

    monkeypatch.setattr(readiness, "_load", only_a_fails)
    down = _Downstream()

    assert (await _request(down, "/api/v1/agents", "GET", a))[0] == 503
    assert (await _request(down, "/api/v1/agents", "GET", b))[0] == 200
    assert mw._budget_tracker.get_remaining(b) == 700
    assert mw._budget_tracker.get_remaining(a) is None
    assert (await _request(down, "/api/v1/agents", "GET", a))[0] == 503


@pytest.mark.parametrize("path", ["/health", "/health/ready", "/health/live"])
async def test_public_health_paths_do_not_need_governance_state(engine, monkeypatch, path):
    async def broken(company_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(readiness, "_load", broken)
    down = _Downstream()
    cid = uuid.uuid4()

    assert (await _request(down, path, "GET"))[0] == 200  # unauthenticated, as probes are
    assert (await _request(down, path, "GET", cid))[0] == 200
    assert down.calls == 2


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/agents/x/chat"),  # model execution
        ("POST", "/api/v1/tasks/x/execute"),  # autonomous work / tool calls
        ("POST", "/api/v1/decisions/x/approve"),  # approval-sensitive mutation
        ("PATCH", "/api/v1/agents/x"),  # ordinary mutation
        ("GET", "/api/v1/agents"),  # reads need policy state too (a policy may deny them)
    ],
)
async def test_model_tool_and_spend_paths_denied_while_unavailable(
    engine, monkeypatch, method, path
):
    cid = await _company(engine)

    async def broken(company_id):
        raise RuntimeError("down")

    monkeypatch.setattr(readiness, "_load", broken)
    down = _Downstream()

    assert (await _request(down, path, method, cid))[0] == 503
    assert down.calls == 0


def test_caches_themselves_default_to_deny_when_unloaded():
    cid = uuid.uuid4()
    assert mw._budget_tracker.check(cid, 1) is False
    request = type("R", (), {"scope": {"path": "/x", "method": "GET"}})()
    assert mw.GovernanceMiddleware(app=None)._evaluate_policy(request, cid)["allowed"] is False
