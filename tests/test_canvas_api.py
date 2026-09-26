"""The API surface the Canvas mutates and reconciles through (P5).

The Canvas draws domain rows (agents, reporting lines, MCP bindings, tools)
and changes them only through these routes. What has to hold here is what the
Canvas relies on: a mutation is authorized, tenant-checked and audited on the
server, the next read returns the same state, a refused mutation leaves the
database untouched, tool authority comes from the server's access check alone,
and the ``topology`` events the Canvas refreshes from reach only the tenant
that owns the change.

Requests go over HTTP through the real routers and dependencies; a test
middleware places the principal where the auth middleware would.
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
from nexus.api.routes import agents as agent_routes
from nexus.api.routes import departments, mcp_bindings
from nexus.api.routes.events import _event_generator, event_bus
from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.company import Company, Department, Team
from nexus.models.governance import AuditLog
from nexus.models.mcp_binding import McpBinding
from nexus.models.tool import ToolCatalogEntry, ToolConnection
from nexus.realtime.publish import TOPOLOGY_CHANNEL, publish_event


@pytest.fixture
async def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'canvas.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)

    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        dept = Department(company_id=acme.id, name="Engineering")
        db.add(dept)
        await db.flush()
        team = Team(company_id=acme.id, department_id=dept.id, name="Platform")
        db.add(team)
        await db.flush()
        ceo = Agent(company_id=acme.id, name="Cy", role="ceo")
        db.add(ceo)
        await db.flush()
        lead = Agent(
            company_id=acme.id, name="Lee", role="lead", manager_id=ceo.id, department_id=dept.id
        )
        ada = Agent(company_id=acme.id, name="Ada", role="engineer", team_id=team.id)
        foreign = Agent(company_id=other.id, name="Foreign", role="engineer")
        db.add_all([lead, ada, foreign])
        conn = ToolConnection(company_id=acme.id, name="gh", transport_type="mcp_remote")
        foreign_conn = ToolConnection(
            company_id=other.id, name="theirs", transport_type="mcp_remote"
        )
        db.add_all([conn, foreign_conn])
        await db.flush()
        session = AgentSessionRecord(company_id=acme.id, agent_id=ada.id)
        db.add(session)
        db.add_all(
            [
                ToolCatalogEntry(
                    company_id=acme.id, connection_id=conn.id, tool_name="search", risk_level="read"
                ),
                ToolCatalogEntry(
                    company_id=acme.id,
                    connection_id=conn.id,
                    tool_name="open_pr",
                    risk_level="read",
                ),
            ]
        )
        await db.commit()

    principals = {
        "viewer": Principal(kind="user", company_id=acme.id, role="viewer", user_id=uuid.uuid4()),
        "manager": Principal(kind="user", company_id=acme.id, role="manager", user_id=uuid.uuid4()),
        "outsider": Principal(kind="user", company_id=other.id, role="admin", user_id=uuid.uuid4()),
    }

    app = FastAPI()
    for router in (agent_routes.router, mcp_bindings.router, departments.router):
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
        "ceo": ceo.id,
        "lead": lead.id,
        "ada": ada.id,
        "foreign": foreign.id,
        "conn": conn.id,
        "foreign_conn": foreign_conn.id,
        "session": session.id,
    }
    await client.aclose()
    await engine.dispose()


async def _call(w, who, method, path, body=None):
    headers = {"x-test-principal": who} if who else {}
    return await w["client"].request(method, path, json=body, headers=headers)


async def _set_manager(w, who, agent, manager):
    body = {"manager_id": manager and str(manager)}
    return await _call(w, who, "PUT", f"/api/v1/agents/{agent}/manager", body)


async def _managers(w) -> dict[str, str | None]:
    """The reporting lines as the database holds them."""
    async with w["factory"]() as db:
        rows = (await db.execute(select(Agent))).scalars().all()
    return {r.name: r.manager_id and str(r.manager_id) for r in rows}


async def _bindings(w) -> list[tuple]:
    async with w["factory"]() as db:
        rows = (await db.execute(select(McpBinding))).scalars().all()
    return sorted((str(r.agent_id), str(r.connection_id), r.status) for r in rows)


async def _effective(w, agent) -> dict[str, str]:
    response = await _call(w, "viewer", "GET", f"/api/v1/agents/{agent}/effective-tools")
    assert response.status_code == 200, response.text
    return {t["tool_name"]: t["outcome"] for t in response.json()}


def _drain(queue: asyncio.Queue) -> list:
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


# --- Reporting lines (Agent Network and Organization modes) -----------------


async def test_reporting_line_set_and_clear_round_trips(world) -> None:
    response = await _set_manager(world, "manager", world["ada"], world["lead"])
    assert (response.status_code, response.json()["manager_id"]) == (200, str(world["lead"]))

    # A reload reads the same line back, from both reads the Canvas uses.
    agents = (
        await _call(world, "viewer", "GET", f"/api/v1/companies/{world['acme']}/agents")
    ).json()
    assert {a["name"]: a["manager_id"] for a in agents}["Ada"] == str(world["lead"])
    one = await _call(world, "viewer", "GET", f"/api/v1/agents/{world['ada']}")
    assert one.json()["manager_id"] == str(world["lead"])

    cleared = await _set_manager(world, "manager", world["ada"], None)
    assert (cleared.status_code, cleared.json()["manager_id"]) == (200, None)
    assert (await _managers(world))["Ada"] is None

    async with world["factory"]() as db:
        audit = (
            (await db.execute(select(AuditLog).where(AuditLog.action == "agent.manager_changed")))
            .scalars()
            .all()
        )
    assert [(a.details["previous_manager_id"], a.details["manager_id"]) for a in audit] == [
        (None, str(world["lead"])),
        (str(world["lead"]), None),
    ]


async def test_reporting_line_needs_write_permission(world) -> None:
    before = await _managers(world)
    assert (await _set_manager(world, None, world["ada"], world["lead"])).status_code == 401
    assert (await _set_manager(world, "viewer", world["ada"], world["lead"])).status_code == 403
    assert await _managers(world) == before


async def test_reporting_line_cannot_cross_tenants(world) -> None:
    before = await _managers(world)
    # A foreign agent as manager, and a foreign caller on our agent: both unseen.
    assert (await _set_manager(world, "manager", world["ada"], world["foreign"])).status_code == 404
    assert (await _set_manager(world, "outsider", world["ada"], None)).status_code == 404
    assert (
        await _set_manager(world, "outsider", world["foreign"], world["ada"])
    ).status_code == 404
    assert await _managers(world) == before


async def test_reporting_line_rejects_self_and_cycles(world) -> None:
    before = await _managers(world)
    assert (await _set_manager(world, "manager", world["ada"], world["ada"])).status_code == 409
    # Lee reports to Cy, so Cy cannot report to Lee.
    assert (await _set_manager(world, "manager", world["ceo"], world["lead"])).status_code == 409
    assert await _managers(world) == before
    # Nor transitively: Ada under Lee under Cy, then Cy under Ada.
    assert (await _set_manager(world, "manager", world["ada"], world["lead"])).status_code == 200
    assert (await _set_manager(world, "manager", world["ceo"], world["ada"])).status_code == 409
    assert (await _managers(world))["Cy"] is None


async def test_org_reads_are_tenant_data(world) -> None:
    acme = world["acme"]
    depts = await _call(world, "viewer", "GET", f"/api/v1/companies/{acme}/departments")
    teams = await _call(world, "viewer", "GET", f"/api/v1/companies/{acme}/teams")
    assert [d["name"] for d in depts.json()] == ["Engineering"]
    assert [t["name"] for t in teams.json()] == ["Platform"]


# --- MCP bindings (Context/MCP mode) ----------------------------------------


async def test_binding_create_and_delete_round_trip(world) -> None:
    assert await _effective(world, world["ada"]) == {}

    created = await _call(
        world,
        "manager",
        "POST",
        f"/api/v1/agents/{world['ada']}/mcp-bindings",
        {"connection_id": str(world["conn"])},
    )
    assert created.status_code == 201, created.text
    listed = await _call(world, "viewer", "GET", f"/api/v1/agents/{world['ada']}/mcp-bindings")
    assert [b["id"] for b in listed.json()] == [created.json()["id"]]
    assert await _effective(world, world["ada"]) == {"search": "allowed", "open_pr": "allowed"}

    deleted = await _call(
        world, "manager", "DELETE", f"/api/v1/mcp-bindings/{created.json()['id']}"
    )
    assert deleted.status_code == 204
    assert await _bindings(world) == []
    assert await _effective(world, world["ada"]) == {}


async def test_disabled_binding_and_disabled_tool_are_not_allowed(world) -> None:
    created = await _call(
        world,
        "manager",
        "POST",
        f"/api/v1/agents/{world['ada']}/mcp-bindings",
        {"connection_id": str(world["conn"]), "disabled_tools": ["open_pr"]},
    )
    binding = created.json()["id"]
    tools = await _effective(world, world["ada"])
    assert tools["search"] == "allowed" and tools["open_pr"] != "allowed"

    disabled = await _call(
        world, "manager", "PATCH", f"/api/v1/mcp-bindings/{binding}", {"status": "disabled"}
    )
    assert (disabled.status_code, disabled.json()["status"]) == (200, "disabled")
    assert "allowed" not in (await _effective(world, world["ada"])).values()


async def test_binding_mutations_are_authorized_and_tenant_checked(world) -> None:
    body = {"connection_id": str(world["conn"])}
    path = f"/api/v1/agents/{world['ada']}/mcp-bindings"
    assert (await _call(world, None, "POST", path, body)).status_code == 401
    assert (await _call(world, "viewer", "POST", path, body)).status_code == 403
    assert (await _call(world, "outsider", "POST", path, body)).status_code == 404
    foreign_conn = {"connection_id": str(world["foreign_conn"])}
    assert (await _call(world, "manager", "POST", path, foreign_conn)).status_code == 404
    assert await _bindings(world) == []

    created = (await _call(world, "manager", "POST", path, body)).json()
    before = await _bindings(world)
    # A duplicate is refused rather than silently stacked.
    assert (await _call(world, "manager", "POST", path, body)).status_code == 409
    for who, expected in (("viewer", 403), ("outsider", 404)):
        gone = await _call(world, who, "DELETE", f"/api/v1/mcp-bindings/{created['id']}")
        patched = await _call(
            world, who, "PATCH", f"/api/v1/mcp-bindings/{created['id']}", {"status": "disabled"}
        )
        assert (gone.status_code, patched.status_code) == (expected, expected)
    assert await _bindings(world) == before


async def test_session_binding_create_is_authorized_and_tenant_checked(world) -> None:
    body = {"connection_id": str(world["conn"])}
    path = f"/api/v1/sessions/{world['session']}/mcp-bindings"
    for who, expected in ((None, 401), ("viewer", 403), ("outsider", 404)):
        assert (await _call(world, who, "POST", path, body)).status_code == expected
    foreign_conn = {"connection_id": str(world["foreign_conn"])}
    assert (await _call(world, "manager", "POST", path, foreign_conn)).status_code == 404
    assert await _bindings(world) == []

    created = await _call(world, "manager", "POST", path, body)
    assert created.status_code == 201, created.text
    assert (created.json()["target_type"], created.json()["session_id"]) == (
        "session",
        str(world["session"]),
    )


# --- Realtime ---------------------------------------------------------------


async def test_topology_events_follow_committed_changes(world) -> None:
    queue: asyncio.Queue = asyncio.Queue()
    event_bus.subscribe("__all__", queue)
    try:
        await _set_manager(world, "manager", world["ada"], world["lead"])
        created = (
            await _call(
                world,
                "manager",
                "POST",
                f"/api/v1/agents/{world['ada']}/mcp-bindings",
                {"connection_id": str(world["conn"])},
            )
        ).json()
        await _call(
            world,
            "manager",
            "PATCH",
            f"/api/v1/mcp-bindings/{created['id']}",
            {"status": "disabled"},
        )
        await _call(world, "manager", "DELETE", f"/api/v1/mcp-bindings/{created['id']}")
        # Refused mutations publish nothing.
        await _set_manager(world, "viewer", world["ada"], None)
        await _set_manager(world, "manager", world["ada"], world["ada"])
        events = _drain(queue)
    finally:
        event_bus.unsubscribe("__all__", queue)

    assert [e.event_type for e in events] == [
        "agent.manager_changed",
        "mcp_binding.created",
        "mcp_binding.updated",
        "mcp_binding.deleted",
    ]
    assert {e.channel for e in events} == {TOPOLOGY_CHANNEL}
    assert {e.company_id for e in events} == {world["acme"]}
    assert events[0].payload["manager_id"] == str(world["lead"])
    assert events[2].payload == {
        "binding_id": created["id"],
        "connection_id": str(world["conn"]),
        "agent_id": str(world["ada"]),
        "session_id": None,
        "status": "disabled",
    }


async def test_topology_stream_delivers_only_the_callers_tenant(world) -> None:
    calls = 0

    async def is_disconnected():
        nonlocal calls
        calls += 1
        return calls > 3

    request = AsyncMock()
    request.is_disconnected = is_disconnected

    async def publish():
        await asyncio.sleep(0.01)
        await publish_event(TOPOLOGY_CHANNEL, "agent.manager_changed", world["other"], {"n": 1})
        await publish_event(TOPOLOGY_CHANNEL, "agent.manager_changed", world["acme"], {"n": 2})

    task = asyncio.create_task(publish())
    received = []
    async for chunk in _event_generator(request, None, TOPOLOGY_CHANNEL, world["acme"]):
        received.append(json.loads(chunk[len("data: ") : -2]))
        break
    await task
    assert [e["payload"]["n"] for e in received] == [2]
