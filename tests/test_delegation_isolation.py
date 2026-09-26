"""Delegation creation is authorized, tenant-scoped and audited.

Both delegation routes are checked the same way: the caller needs task write
permission, the task and both agents must be in the caller's company, a caller
acting as an agent may only hand off its own work, and every accepted
delegation leaves an audit row. The request body (agent and task ids) is never
trusted on its own.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import agents as agent_routes
from nexus.api.routes import company_sim
from nexus.api.routes.events import event_bus
from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.task import Task
from nexus.realtime.publish import TOPOLOGY_CHANNEL


@pytest.fixture
async def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'delegation.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    monkeypatch.setattr(company_sim, "_delegation_store", {})

    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        ada = Agent(company_id=acme.id, name="Ada", role="engineer")
        lee = Agent(company_id=acme.id, name="Lee", role="lead")
        foreign = Agent(company_id=other.id, name="Foreign", role="engineer")
        db.add_all([ada, lee, foreign])
        await db.flush()
        task = Task(company_id=acme.id, title="Ship it")
        foreign_task = Task(company_id=other.id, title="Theirs")
        db.add_all([task, foreign_task])
        await db.commit()

    principals = {
        "viewer": Principal(kind="user", company_id=acme.id, role="viewer", user_id=uuid.uuid4()),
        "manager": Principal(kind="user", company_id=acme.id, role="manager", user_id=uuid.uuid4()),
        "outsider": Principal(kind="user", company_id=other.id, role="admin", user_id=uuid.uuid4()),
        # A run token minted for Ada: it may act only as Ada.
        "ada_run": Principal(
            kind="run", company_id=acme.id, role="agent", run_id=uuid.uuid4(), agent_id=ada.id
        ),
    }
    app = FastAPI()
    app.include_router(company_sim.router)
    app.include_router(agent_routes.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers["x-test-principal"]]
        return await call_next(request)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield {
        "client": client,
        "factory": factory,
        "acme": acme.id,
        "other": other.id,
        "ada": ada.id,
        "lee": lee.id,
        "foreign": foreign.id,
        "task": task.id,
        "foreign_task": foreign_task.id,
    }
    await client.aclose()
    await engine.dispose()


async def _call(w, who, method, path, body=None):
    return await w["client"].request(method, path, json=body, headers={"x-test-principal": who})


def _body(w, *, task=None, source=None, target=None) -> dict:
    return {
        "task_id": str(task or w["task"]),
        "from_agent_id": str(source or w["ada"]),
        "to_agent_id": str(target or w["lee"]),
        "reason": "load balancing",
    }


async def _delegate(w, who, company=None, **ids):
    return await _call(
        w, who, "POST", f"/api/v1/companies/{company or w['acme']}/delegations", _body(w, **ids)
    )


async def _audit_rows(w) -> list[tuple[uuid.UUID, str]]:
    async with w["factory"]() as db:
        rows = (
            await db.execute(select(AuditLog).where(AuditLog.action == "delegation.created"))
        ).scalars()
        return [(r.company_id, r.resource_id) for r in rows]


async def test_delegation_is_audited_committed_and_then_announced(world, monkeypatch) -> None:
    announced: list[tuple] = []

    async def spy(channel, event_type, company_id, payload):
        # At publish time the audit row is already visible to another connection.
        announced.append((channel, event_type, company_id, len(await _audit_rows(world))))

    monkeypatch.setattr(company_sim, "publish_event", spy)
    created = await _delegate(world, "manager")

    assert created.status_code == 201, created.text
    assert await _audit_rows(world) == [(world["acme"], str(world["task"]))]
    assert announced == [(TOPOLOGY_CHANNEL, "delegation.created", world["acme"], 1)]
    path = f"/api/v1/companies/{world['acme']}/delegations"
    listed = (await _call(world, "manager", "GET", path)).json()
    assert [d["id"] for d in listed] == [created.json()["id"]]


@pytest.mark.parametrize(
    ("who", "ids", "status", "detail"),
    [
        ("viewer", {}, 403, None),
        ("manager", {"source": "foreign"}, 404, "Source agent not found"),
        ("manager", {"target": "foreign"}, 404, "Target agent not found"),
        ("manager", {"task": "foreign_task"}, 404, "Task not found"),
        ("manager", {"target": "ada"}, 422, "An agent cannot delegate to itself"),
        (
            "ada_run",
            {"source": "lee", "target": "ada"},
            403,
            "An agent may only delegate its own work",
        ),
    ],
)
async def test_refused_delegations_leave_nothing_behind(world, who, ids, status, detail) -> None:
    refused = await _delegate(world, who, **{k: world[v] for k, v in ids.items()})
    assert refused.status_code == status, refused.text
    if detail:
        assert refused.json()["detail"] == detail
    assert await _audit_rows(world) == []
    assert company_sim._delegation_store == {}


async def test_another_company_cannot_delegate_or_read_across_tenants(world) -> None:
    across = await _delegate(world, "outsider")
    # Its own company, but naming Acme's agents and task in the body.
    smuggled = await _delegate(world, "outsider", company=world["other"])
    read = await _call(world, "outsider", "GET", f"/api/v1/companies/{world['acme']}/delegations")
    assert (across.status_code, smuggled.status_code, read.status_code) == (403, 404, 403)
    assert await _audit_rows(world) == []


async def test_a_run_may_delegate_its_own_work(world) -> None:
    created = await _delegate(world, "ada_run")
    assert created.status_code == 201, created.text
    async with world["factory"]() as db:
        row = (await db.execute(select(AuditLog))).scalar_one()
    assert (row.actor_type, row.actor_id) == ("agent", str(world["ada"]))


# --- The older per-agent route creates a task; it gets the same checks. -------


async def _agent_delegate(w, who, source=None, target=None):
    return await _call(
        w,
        who,
        "POST",
        f"/api/v1/agents/{source or w['ada']}/delegate",
        {"target_agent_id": str(target or w["lee"]), "title": "Review the release"},
    )


async def _tasks(w) -> list[str]:
    async with w["factory"]() as db:
        return sorted((await db.execute(select(Task.title))).scalars())


async def test_agent_delegate_route_is_audited(world) -> None:
    created = await _agent_delegate(world, "manager")
    assert created.status_code == 201, created.text
    assert await _audit_rows(world) == [(world["acme"], created.json()["task_id"])]


@pytest.mark.parametrize(
    ("who", "source", "target", "status"),
    [
        ("viewer", None, None, 403),
        ("manager", "foreign", None, 404),
        ("manager", None, "foreign", 404),
        ("outsider", None, None, 404),
        ("ada_run", "lee", "ada", 403),
    ],
)
async def test_agent_delegate_route_refusals(world, who, source, target, status) -> None:
    before = await _tasks(world)
    refused = await _agent_delegate(
        world, who, source=source and world[source], target=target and world[target]
    )
    assert refused.status_code == status, refused.text
    assert await _tasks(world) == before
    assert await _audit_rows(world) == []


async def test_refusals_publish_nothing(world) -> None:
    queue: asyncio.Queue = asyncio.Queue()
    event_bus.subscribe("__all__", queue)
    try:
        await _delegate(world, "viewer")
        await _delegate(world, "manager", target=world["foreign"])
    finally:
        event_bus.unsubscribe("__all__", queue)
    assert queue.empty()
