"""Tool connection, MCP binding and effective-tools API (ws05).

Route functions are called directly against a real SQLite database, like
tests/test_agent_sessions.py; permissions are checked against the route table
and the RBAC roles.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import mcp_bindings as api
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.governance.rbac import role_allows
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.tool import ToolCatalogEntry, ToolPolicy
from nexus.tools.mcp_client import MCPTool

URL = "https://mcp.acme.test/rpc"


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bindings.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "tool_binding_enforcement", "audit")
    yield maker
    await engine.dispose()


@pytest.fixture
async def t(factory):
    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        a = Agent(company_id=acme.id, name="A", role="engineer")
        foreign = Agent(company_id=other.id, name="F", role="engineer")
        db.add_all([a, foreign])
        await db.flush()
        s1 = AgentSessionRecord(company_id=acme.id, agent_id=a.id)
        foreign_session = AgentSessionRecord(company_id=other.id, agent_id=foreign.id)
        db.add_all([s1, foreign_session])
        await db.commit()
    return {
        "acme": acme.id, "other": other.id, "a": a.id, "foreign": foreign.id,
        "s1": s1.id, "foreign_session": foreign_session.id,
    }


# Routes use the principal only as the audit actor; the company comes from the
# company_id argument, which is what the tests vary.
ADMIN = Principal(kind="user", company_id=uuid.uuid4(), role="admin", user_id=uuid.uuid4())


async def call(factory, fn, *args: Any) -> Any:
    extra = [ADMIN] if "principal" in inspect.signature(fn).parameters else []
    async with factory() as db:
        out = await fn(*args, db, *extra)
        await db.commit()
    return out


class FakeClient:
    async def connect(self, url: str) -> dict:
        return {}

    async def list_tools(self) -> list[MCPTool]:
        return [
            MCPTool(name="search", description="find", input_schema={}),
            MCPTool(name="delete_repo", description="rm", input_schema={}),
        ]

    async def disconnect(self) -> None:
        pass


async def connection_with_catalog(factory, t, monkeypatch) -> uuid.UUID:
    import nexus.tools.mcp_client as mcp_client

    monkeypatch.setattr(mcp_client, "MCPClient", FakeClient)
    conn = await call(factory, api.create_tool_connection,
                      api.ConnectionCreate(name="c", endpoint_url=URL, credential_ref="vault:x"),
                      t["acme"])
    entries = await call(factory, api.discover_connection_tools, conn.id, t["acme"])
    assert {e.tool_name: e.risk_level for e in entries} == {"search": "write",
                                                             "delete_repo": "write"}
    return conn.id


class TestPermissions:
    def test_every_route_is_guarded(self) -> None:
        for route in api.router.routes:
            admin_only = "RequireAdmin" in str(inspect.signature(route.endpoint))
            assert route.dependencies or admin_only, f"{route.path} {route.methods} unguarded"

    def test_roles(self) -> None:
        assert role_allows("viewer", "read", "mcp_binding")
        assert not role_allows("viewer", "write", "mcp_binding")
        assert not role_allows("agent", "write", "mcp_binding")
        assert role_allows("manager", "write", "mcp_binding")
        assert role_allows("admin", "write", "mcp_binding")


class TestConnections:
    async def test_create_discover_and_classify(self, factory, t, monkeypatch) -> None:
        conn_id = await connection_with_catalog(factory, t, monkeypatch)
        [listed] = await call(factory, api.list_tool_connections, t["acme"])
        assert listed.has_credential and not hasattr(listed, "credential_ref")
        assert await call(factory, api.list_tool_connections, t["other"]) == []

        entries = await call(factory, api.list_connection_tools, conn_id, t["acme"])
        search = next(e for e in entries if e.tool_name == "search")
        out = await call(factory, api.update_catalog_entry, conn_id, search.id,
                         api.CatalogEntryUpdate(risk_level="read"), t["acme"])
        assert out.risk_level == "read"

        # Rediscovery keeps the admin's classification.
        entries = await call(factory, api.discover_connection_tools, conn_id, t["acme"])
        assert next(e for e in entries if e.tool_name == "search").risk_level == "read"

    async def test_private_endpoint_rejected(self, factory, t) -> None:
        with pytest.raises(HTTPException) as exc:
            await call(factory, api.create_tool_connection,
                       api.ConnectionCreate(name="x", endpoint_url="https://10.0.0.5/rpc"),
                       t["acme"])
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException):
            await call(factory, api.create_tool_connection,
                       api.ConnectionCreate(name="x", endpoint_url="file:///etc/passwd"),
                       t["acme"])

    async def test_other_tenant_connection_is_404(self, factory, t, monkeypatch) -> None:
        conn_id = await connection_with_catalog(factory, t, monkeypatch)
        for fn, args in [
            (api.update_tool_connection, (conn_id, api.ConnectionUpdate(is_active=False))),
            (api.discover_connection_tools, (conn_id,)),
        ]:
            with pytest.raises(HTTPException) as exc:
                await call(factory, fn, *args, t["other"])
            assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            await call(factory, api.list_connection_tools, conn_id, t["other"])
        assert exc.value.status_code == 404


class TestBindings:
    async def test_crud_audit_and_effective_tools(self, factory, t, monkeypatch) -> None:
        conn_id = await connection_with_catalog(factory, t, monkeypatch)
        binding = await call(factory, api.create_agent_binding, t["a"],
                             api.BindingCreate(connection_id=conn_id), t["acme"])
        assert (binding.target_type, binding.version, binding.status) == ("agent", 1, "active")

        tools = await call(factory, api.agent_effective_tools, t["a"], t["acme"])
        assert {x.tool_name: x.outcome for x in tools} == {"search": "allowed",
                                                            "delete_repo": "allowed"}

        updated = await call(factory, api.update_binding, binding.id,
                             api.BindingUpdate(disabled_tools=["delete_repo"]), t["acme"])
        assert updated.version == 2
        tools = await call(factory, api.agent_effective_tools, t["a"], t["acme"])
        assert {x.tool_name: x.outcome for x in tools}["delete_repo"] == "would_deny"

        # A policy deny shows up as denied even though the binding grants the tool.
        async with factory() as db:
            db.add(ToolPolicy(company_id=t["acme"], name="no search", effect="deny",
                              conditions={"tool_name": ["search"]}))
            await db.commit()
        tools = await call(factory, api.agent_effective_tools, t["a"], t["acme"])
        assert {x.tool_name: x.outcome for x in tools}["search"] == "denied"

        await call(factory, api.delete_binding, binding.id, t["acme"])
        assert await call(factory, api.list_agent_bindings, t["a"], t["acme"]) == []

        async with factory() as db:
            actions = [a.action for a in (await db.execute(select(AuditLog))).scalars()]
        assert {"mcp_binding.create", "mcp_binding.update", "mcp_binding.delete",
                "tool_connection.create", "tool_connection.discover"} <= set(actions)

    async def test_session_binding_and_inheritance(self, factory, t, monkeypatch) -> None:
        conn_id = await connection_with_catalog(factory, t, monkeypatch)
        agent_b = await call(factory, api.create_agent_binding, t["a"],
                             api.BindingCreate(connection_id=conn_id), t["acme"])
        session_b = await call(factory, api.create_session_binding, t["s1"],
                               api.BindingCreate(connection_id=conn_id, status="disabled"),
                               t["acme"])
        listed = await call(factory, api.list_session_bindings, t["s1"], t["acme"])
        assert {b.id for b in listed} == {agent_b.id, session_b.id}

        # The session's disabled binding wins inside the session only.
        tools = await call(factory, api.session_effective_tools, t["s1"], t["acme"])
        assert {x.outcome for x in tools} == {"would_deny"}
        tools = await call(factory, api.agent_effective_tools, t["a"], t["acme"])
        assert {x.outcome for x in tools} == {"allowed"}

    async def test_duplicate_binding_is_409(self, factory, t, monkeypatch) -> None:
        conn_id = await connection_with_catalog(factory, t, monkeypatch)
        body = api.BindingCreate(connection_id=conn_id)
        await call(factory, api.create_agent_binding, t["a"], body, t["acme"])
        with pytest.raises(HTTPException) as exc:
            await call(factory, api.create_agent_binding, t["a"], body, t["acme"])
        assert exc.value.status_code == 409

    async def test_cross_tenant_targets_are_404(self, factory, t, monkeypatch) -> None:
        conn_id = await connection_with_catalog(factory, t, monkeypatch)
        body = api.BindingCreate(connection_id=conn_id)
        for fn, target in [
            (api.create_agent_binding, t["foreign"]),
            (api.create_session_binding, t["foreign_session"]),
        ]:
            with pytest.raises(HTTPException) as exc:
                await call(factory, fn, target, body, t["acme"])
            assert exc.value.status_code == 404

        # Acme's connection cannot be bound from Other, even to Other's own agent.
        with pytest.raises(HTTPException) as exc:
            await call(factory, api.create_agent_binding, t["foreign"], body, t["other"])
        assert exc.value.status_code == 404

        binding = await call(factory, api.create_agent_binding, t["a"], body, t["acme"])
        with pytest.raises(HTTPException) as exc:
            await call(factory, api.delete_binding, binding.id, t["other"])
        assert exc.value.status_code == 404
        for fn, target in [
            (api.agent_effective_tools, t["a"]),
            (api.session_effective_tools, t["s1"]),
        ]:
            with pytest.raises(HTTPException) as exc:
                await call(factory, fn, target, t["other"])
            assert exc.value.status_code == 404

    async def test_pending_approval_cannot_be_set_through_the_api(self) -> None:
        with pytest.raises(ValueError):
            api.BindingUpdate(status="pending_approval")

    async def test_catalog_entry_of_other_connection_is_404(
        self, factory, t, monkeypatch
    ) -> None:
        conn_id = await connection_with_catalog(factory, t, monkeypatch)
        async with factory() as db:
            entry = (await db.execute(select(ToolCatalogEntry))).scalars().first()
        with pytest.raises(HTTPException) as exc:
            await call(factory, api.update_catalog_entry, uuid.uuid4(), entry.id,
                       api.CatalogEntryUpdate(is_active=False), t["acme"])
        assert exc.value.status_code == 404
        assert conn_id
