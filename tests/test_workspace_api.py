"""The API surface the Agent Workspace UI is built on (P4).

The workspace only reads and mutates through these routes, so they are what
has to hold: an anonymous caller is 401, a role without the permission is 403,
another tenant's session is 404 whatever the route, and the realtime events
the UI refreshes from reach only the session's own tenant.

Requests go over HTTP through the real routers and dependencies. The only
stand-in is the principal, which a test middleware places where the auth
middleware would.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import adapters, mcp_bindings, sessions
from nexus.api.routes import agents as agent_routes
from nexus.api.routes.events import _event_generator, event_bus
from nexus.auth.middleware import rejection_for
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.company import Company
from nexus.services.session_service import SESSION_CHANNEL, publish_session_event


@pytest.fixture
async def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workspace.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)

    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        agent = Agent(
            company_id=acme.id, name="Ada", role="engineer", adapter_type="openai", model="gpt-x"
        )
        foreign = Agent(company_id=other.id, name="Foreign", role="engineer")
        db.add_all([agent, foreign])
        await db.flush()
        session = AgentSessionRecord(
            company_id=acme.id,
            agent_id=agent.id,
            status="active",
            adapter_type="openai",
            model="gpt-x",
        )
        db.add(session)
        await db.commit()

    principals = {
        "viewer": Principal(kind="user", company_id=acme.id, role="viewer", user_id=uuid.uuid4()),
        "manager": Principal(kind="user", company_id=acme.id, role="manager", user_id=uuid.uuid4()),
        "outsider": Principal(kind="user", company_id=other.id, role="admin", user_id=uuid.uuid4()),
        "admin": Principal(kind="user", company_id=acme.id, role="admin", user_id=uuid.uuid4()),
    }

    app = FastAPI()
    for router in (sessions.router, mcp_bindings.router, agent_routes.router, adapters.router):
        app.include_router(router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        who = request.headers.get("x-test-principal")
        if who:
            request.state.principal = principals[who]
        return await call_next(request)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield {
        "client": client,
        "factory": factory,
        "acme": acme.id,
        "other": other.id,
        "agent": agent.id,
        "foreign": foreign.id,
        "session": session.id,
    }
    await client.aclose()
    await engine.dispose()


def _reads(w) -> list[str]:
    s = w["session"]
    return [
        f"/api/v1/companies/{w['acme']}/sessions?agent_id={w['agent']}",
        f"/api/v1/sessions/{s}",
        f"/api/v1/sessions/{s}/timeline",
        f"/api/v1/sessions/{s}/usage",
        f"/api/v1/sessions/{s}/mcp-bindings",
        f"/api/v1/sessions/{s}/effective-tools",
    ]


def _writes(w) -> list[tuple[str, str, dict | None]]:
    s = w["session"]
    return [
        ("POST", f"/api/v1/agents/{w['agent']}/sessions", {}),
        ("PATCH", f"/api/v1/sessions/{s}", {"title": "renamed"}),
        ("POST", f"/api/v1/sessions/{s}/terminate", None),
        ("POST", f"/api/v1/sessions/{s}/messages", {"prompt": "hi"}),
    ]


async def _call(w, who, method, path, body=None):
    headers = {"x-test-principal": who} if who else {}
    return await w["client"].request(method, path, json=body, headers=headers)


async def _session_state(w):
    async with w["factory"]() as db:
        rows = (
            (
                await db.execute(
                    select(AgentSessionRecord).where(AgentSessionRecord.company_id == w["acme"])
                )
            )
            .scalars()
            .all()
        )
    return sorted((str(r.id), r.status, r.title) for r in rows)


async def test_anonymous_is_401(world) -> None:
    for path in _reads(world):
        assert (await _call(world, None, "GET", path)).status_code == 401, path
    for method, path, body in _writes(world):
        assert (await _call(world, None, method, path, body)).status_code == 401, path


async def test_member_reads_everything_the_workspace_shows(world) -> None:
    for path in _reads(world):
        response = await _call(world, "viewer", "GET", path)
        assert response.status_code == 200, (path, response.text)
    listed = (await _call(world, "viewer", "GET", _reads(world)[0])).json()["items"]
    assert [item["id"] for item in listed] == [str(world["session"])]
    agents = await _call(world, "viewer", "GET", f"/api/v1/companies/{world['acme']}/agents")
    assert [a["name"] for a in agents.json()] == ["Ada"]


async def test_viewer_cannot_mutate(world) -> None:
    before = await _session_state(world)
    for method, path, body in _writes(world):
        response = await _call(world, "viewer", method, path, body)
        assert response.status_code == 403, (path, response.text)
    assert await _session_state(world) == before


async def test_manager_mutates_through_the_api(world) -> None:
    created = await _call(world, "manager", "POST", f"/api/v1/agents/{world['agent']}/sessions", {})
    assert created.status_code == 201
    assert created.json()["agent_id"] == str(world["agent"])
    ended = await _call(
        world, "manager", "POST", f"/api/v1/sessions/{created.json()['id']}/terminate"
    )
    assert (ended.status_code, ended.json()["status"]) == (200, "terminated")


async def test_other_tenant_gets_404_on_every_session_route(world) -> None:
    before = await _session_state(world)
    for path in _reads(world)[1:]:
        response = await _call(world, "outsider", "GET", path)
        assert response.status_code == 404, (path, response.text)
    for method, path, body in _writes(world):
        response = await _call(world, "outsider", method, path, body)
        assert response.status_code == 404, (path, response.text)
    assert await _session_state(world) == before


async def test_other_tenant_cannot_list_across_companies(world) -> None:
    # Naming the other company in the path is refused outright.
    response = await _call(world, "outsider", "GET", _reads(world)[0])
    assert response.status_code == 403
    # Filtering its own list by a foreign agent finds nothing.
    own = await _call(
        world,
        "outsider",
        "GET",
        f"/api/v1/companies/{world['other']}/sessions?agent_id={world['agent']}",
    )
    assert (own.status_code, own.json()["items"]) == (200, [])


@pytest.mark.parametrize("resource", ["agents", "sessions"])
def test_middleware_refuses_foreign_company_paths(world, monkeypatch, resource) -> None:
    monkeypatch.setattr(settings, "auth_enabled", True)
    outsider = Principal(kind="user", company_id=world["other"], role="admin")
    response = rejection_for(f"/api/v1/companies/{world['acme']}/{resource}", outsider)
    assert response is not None and response.status_code == 403


async def test_session_events_carry_the_channel_and_tenant(world) -> None:
    queue: asyncio.Queue = asyncio.Queue()
    event_bus.subscribe("__all__", queue)
    try:
        created = await _call(
            world, "manager", "POST", f"/api/v1/agents/{world['agent']}/sessions", {}
        )
        event = queue.get_nowait()
    finally:
        event_bus.unsubscribe("__all__", queue)
    assert event.event_type == "session.created"
    assert event.channel == SESSION_CHANNEL
    assert event.company_id == world["acme"]
    assert event.payload["session_id"] == created.json()["id"]


async def test_session_stream_delivers_only_the_callers_tenant(world) -> None:
    calls = 0

    async def is_disconnected():
        nonlocal calls
        calls += 1
        return calls > 3

    request = AsyncMock()
    request.is_disconnected = is_disconnected

    async def publish():
        await asyncio.sleep(0.01)
        await publish_session_event("session.updated", world["other"], {"session_id": "theirs"})
        await publish_session_event("session.updated", world["acme"], {"session_id": "ours"})

    task = asyncio.create_task(publish())
    received = []
    async for chunk in _event_generator(request, None, SESSION_CHANNEL, world["acme"]):
        received.append(json.loads(chunk[len("data: ") : -2]))
        break
    await task
    assert [e["payload"]["session_id"] for e in received] == ["ours"]


async def test_session_events_are_published_only_after_commit(world, monkeypatch) -> None:
    """A listener that refetches on the event must already see the change.

    At publish time the spy reads the session over its own connection, which
    sees only committed rows. Publishing before the commit would show it the
    previous state (or no row at all for a create).
    """
    seen: list[tuple[str, tuple[str, str | None] | None]] = []

    async def spy(event_type, company_id, payload):
        async with world["factory"]() as db:
            row = await db.get(AgentSessionRecord, uuid.UUID(payload["session_id"]))
        seen.append((event_type, (row.status, row.title) if row else None))

    monkeypatch.setattr(sessions, "publish_session_event", spy)
    monkeypatch.setattr("nexus.services.session_service.publish_session_event", spy)

    created = await _call(world, "manager", "POST", f"/api/v1/agents/{world['agent']}/sessions", {})
    sid = created.json()["id"]
    await _call(world, "manager", "PATCH", f"/api/v1/sessions/{sid}", {"title": "renamed"})
    await _call(world, "manager", "POST", f"/api/v1/agents/{world['agent']}/sessions/{sid}/pause")
    await _call(world, "manager", "POST", f"/api/v1/sessions/{sid}/terminate")
    deleted = await _call(world, "admin", "DELETE", f"/api/v1/sessions/{sid}")

    assert deleted.status_code == 204
    assert seen == [
        ("session.created", ("active", None)),
        ("session.updated", ("active", "renamed")),
        ("session.updated", ("idle", "renamed")),
        ("session.terminated", ("terminated", "renamed")),
        ("session.deleted", None),
    ]
