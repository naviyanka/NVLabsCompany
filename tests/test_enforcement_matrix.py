"""P3.2: the tool-binding enforcement matrix, in both modes.

Part 1 drives every access stage through :func:`nexus.tools.factory.guarded_call`
and pins the outcome, whether the tool ran, and the audit trail it left.
Part 2 drives an allowed, a soft-refused and a hard-refused call through each
dispatch path's own entry point, so no path can reach a tool around the check.

Expected, per mode:

============  ==============================  ==============================
case          audit                           enforce
============  ==============================  ==============================
allowed       allowed, executes               allowed, executes
soft          would_deny, executes            denied, does not execute
hard          denied, does not execute        denied, does not execute
============  ==============================  ==============================

Every call leaves one ``tool_invocations`` row for its company, and every
outcome other than ``allowed`` (and every refusal after access passed) an
``audit_log`` entry pointing at that row.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.adapters.hermes_adapter import HermesAdapter
from nexus.adapters.mcp_adapter import MCPAgentAdapter
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.mcp_binding import McpBinding
from nexus.models.tool import (
    ToolCatalogEntry,
    ToolConnection,
    ToolPolicy,
    ToolProfile,
    ToolProfileBinding,
)
from nexus.models.tool_invocation import ToolInvocation
from nexus.runtime.adapter import AgentSession
from nexus.tools.access import ALLOWED, BUILTIN_ENDPOINT, BUILTIN_TRANSPORT, DENIED, WOULD_DENY
from nexus.tools.context import INBOUND_MCP, ExecutionContext
from nexus.tools.factory import guarded_call
from nexus.tools.mcp_client import MCPResult

MODES = ["audit", "enforce"]
NODE = "file-json-parse"  # a read-risk builtin node, served by inbound MCP
REMOTE = "https://mcp.acme.test/rpc"
FOREIGN = "https://mcp.other.test/rpc"


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'matrix.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", maker)
    yield maker
    await engine.dispose()


@pytest.fixture
async def t(factory):
    """Acme: agents A and B with sessions S (A) and SB (B), the builtin
    connection BI (catalog: NODE) and remote R (catalog: search). Other: agent
    O and connection FC (catalog: search)."""
    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        a = Agent(company_id=acme.id, name="A", role="engineer")
        b = Agent(company_id=acme.id, name="B", role="engineer")
        o = Agent(company_id=other.id, name="O", role="engineer")
        db.add_all([a, b, o])
        await db.flush()
        s = AgentSessionRecord(company_id=acme.id, agent_id=a.id)
        sb = AgentSessionRecord(company_id=acme.id, agent_id=b.id)
        bi = ToolConnection(company_id=acme.id, name="nexus", transport_type=BUILTIN_TRANSPORT,
                            endpoint_url=BUILTIN_ENDPOINT)
        r = ToolConnection(company_id=acme.id, name="r", transport_type="mcp_remote",
                           endpoint_url=REMOTE)
        fc = ToolConnection(company_id=other.id, name="fc", transport_type="mcp_remote",
                            endpoint_url=FOREIGN)
        db.add_all([s, sb, bi, r, fc])
        await db.flush()
        db.add_all([
            ToolCatalogEntry(company_id=acme.id, connection_id=bi.id, tool_name=NODE,
                             risk_level="read"),
            ToolCatalogEntry(company_id=acme.id, connection_id=r.id, tool_name="search",
                             risk_level="read"),
            ToolCatalogEntry(company_id=other.id, connection_id=fc.id, tool_name="search",
                             risk_level="read"),
        ])
        await db.commit()
    return {"acme": acme.id, "other": other.id, "a": a.id, "b": b.id, "o": o.id,
            "s": s.id, "sb": sb.id, "bi": bi.id, "r": r.id, "fc": fc.id}


async def add(factory, *rows: Any) -> None:
    async with factory() as db:
        db.add_all(rows)
        await db.commit()


def binding(t, connection: str = "r", **fields: Any) -> McpBinding:
    return McpBinding(company_id=t["acme"], connection_id=t[connection], target_type="agent",
                      agent_id=t["a"], **fields)


def deny_all(t) -> ToolPolicy:
    return ToolPolicy(company_id=t["acme"], name="deny all", priority=0, effect="deny",
                      conditions={})


def agent_ctx(t, *, agent="a", session="s", role="agent", source="test") -> ExecutionContext:
    return ExecutionContext(
        company_id=t["acme"], principal_id=f"agent:{t[agent]}", principal_role=role,
        source=source, agent_id=t[agent], session_id=t[session] if session else None,
    )


def user(t, role: str) -> Principal:
    return Principal(kind="user", company_id=t["acme"], role=role, user_id=uuid.uuid4())


def run_principal(t) -> Principal:
    return Principal(kind="run", company_id=t["acme"], role="agent", run_id=uuid.uuid4(),
                     agent_id=t["a"])


async def rows(factory) -> list[ToolInvocation]:
    async with factory() as db:
        return list((await db.execute(select(ToolInvocation))).scalars())


async def audits(factory) -> list[AuditLog]:
    async with factory() as db:
        return list((await db.execute(select(AuditLog))).scalars())


def expected(kind: str, mode: str) -> tuple[str, bool]:
    """(authorization, executed) for a case kind under a mode."""
    if kind == "allowed":
        return ALLOWED, True
    if kind == "soft" and mode == "audit":
        return WOULD_DENY, True
    return DENIED, False


async def assert_recorded(factory, t, authorization: str, *, agentless: bool = False) -> None:
    """One row for Acme with the outcome, plus its audit entry when not allowed."""
    [row] = await rows(factory)
    assert row.company_id == t["acme"]
    assert row.authorization == authorization
    if agentless:
        assert row.agent_id is None
    assert row.authorization_detail["problems"] or authorization == ALLOWED
    entries = await audits(factory)
    if authorization == ALLOWED:
        assert entries == []
    else:
        [entry] = entries
        assert entry.action == f"tool.access_{authorization}"
        assert entry.resource_id == str(row.id) and entry.company_id == t["acme"]


# ---------------------------------------------------------------------------
# Part 1: every stage, through guarded_call
# ---------------------------------------------------------------------------


async def _catalog_off(factory, t) -> None:
    async with factory() as db:
        entry = (await db.execute(select(ToolCatalogEntry).where(
            ToolCatalogEntry.connection_id == t["r"]))).scalar_one()
        entry.is_active = False
        await db.commit()


async def _connection_off(factory, t) -> None:
    async with factory() as db:
        (await db.get(ToolConnection, t["r"])).is_active = False
        await db.commit()


async def _profile_deny(factory, t) -> None:
    profile = ToolProfile(company_id=t["acme"], name="locked", default_action="deny")
    await add(factory, profile)
    await add(factory, ToolProfileBinding(company_id=t["acme"], profile_id=profile.id,
                                          target_type="agent", target_id=t["a"]))


# name: (kind, expected stage, setup(factory, t), call overrides)
STAGES: dict[str, tuple[str, str | None, Any, dict[str, Any]]] = {
    "allowed": ("allowed", None, lambda f, t: add(f, binding(t)), {}),
    "missing_binding": ("soft", "binding", None, {}),
    "disabled_binding": ("soft", "binding",
                         lambda f, t: add(f, binding(t, status="disabled")), {}),
    "disabled_tool": ("soft", "binding",
                      lambda f, t: add(f, binding(t, disabled_tools=["search"])), {}),
    "catalog_disabled_tool": ("soft", "catalog", _catalog_off, {}),
    "inactive_connection": ("soft", "connection", _connection_off, {}),
    "unknown_tool": ("soft", "catalog", None, {"tool": "mystery"}),
    "agentless": ("soft", "agent", None, {"agent": None}),
    "rbac_denial": ("hard", "rbac", None, {"role": "viewer"}),
    "policy_denial": ("hard", "policy", lambda f, t: add(f, deny_all(t)), {}),
    "profile_denial": ("hard", "policy", _profile_deny, {}),
    "cross_company_resource": ("hard", "connection", None, {"connection": "fc"}),
    "wrong_agent": ("hard", "agent", None, {"agent": "o"}),
    "wrong_session": ("hard", "session", None, {"session": "sb"}),
}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("case", list(STAGES))
async def test_stage_matrix(factory, t, monkeypatch, mode, case) -> None:
    monkeypatch.setattr(settings, "tool_binding_enforcement", mode)
    kind, stage, setup, over = STAGES[case]
    # Every case but "allowed" keeps an active binding where it can, so the
    # stage under test is the only thing wrong with the call.
    if kind != "allowed" and case not in ("missing_binding", "disabled_binding", "disabled_tool"):
        await add(factory, binding(t))
    if setup is not None:
        await setup(factory, t)

    agent = over.get("agent", "a")
    session = over.get("session", "s") if agent else None
    if agent is None:
        ctx = ExecutionContext.for_principal(user(t, "admin"), source="test")
    else:
        ctx = agent_ctx(t, agent=agent, session=session, role=over.get("role", "agent"))

    executed: list[str] = []

    async def run() -> str:
        executed.append("ran")
        return "ok"

    out = await guarded_call(ctx, over.get("tool", "search"), {"q": "x"}, run, source="test",
                             connection_id=t[over.get("connection", "r")])

    authorization, runs = expected(kind, mode)
    assert (out["status"] == "success") is runs and bool(executed) is runs
    await assert_recorded(factory, t, authorization, agentless=agent is None)
    [row] = await rows(factory)
    assert row.status == ("success" if runs else "denied")
    detail = row.authorization_detail
    assert detail["enforcement"] == mode and detail["source"] == "test"
    if stage is not None:
        assert stage in {p["stage"] for p in detail["problems"]}
        assert all(p["hard"] is (kind == "hard") for p in detail["problems"]
                   if p["stage"] == stage)
    if case in ("allowed", "missing_binding", "rbac_denial"):
        assert row.agent_id == t["a"] and row.session_id == t["s"]
    if case == "wrong_session":
        assert detail["claimed_session_id"] == str(t["sb"])
    if case == "wrong_agent":
        assert detail["claimed_agent_id"] == str(t["o"])


@pytest.mark.parametrize("mode", MODES)
async def test_refusal_after_access_is_audited(factory, t, monkeypatch, mode) -> None:
    """A guardrail refusal of an allowed call is audited like an access refusal."""
    monkeypatch.setattr(settings, "tool_binding_enforcement", mode)
    await add(factory, binding(t))

    async def run() -> str:
        raise AssertionError("must not run")

    out = await guarded_call(agent_ctx(t), "search", {"cmd": "rm -rf /"}, run, source="test",
                             connection_id=t["r"])

    assert out["status"] == "guardrail_blocked"
    [row] = await rows(factory)
    assert (row.authorization, row.status) == (ALLOWED, "guardrail_blocked")
    [entry] = await audits(factory)
    assert entry.action == "tool.guardrail_blocked" and entry.resource_id == str(row.id)


# ---------------------------------------------------------------------------
# Part 2: every dispatch path, allowed / soft / hard
# ---------------------------------------------------------------------------


class FakeMCPClient:
    is_connected = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPResult:
        self.calls.append(tool_name)
        return MCPResult(content="ok", is_error=False, metadata={})


async def mcp_dispatch(session: AgentSession, executed: list[str]) -> Any:
    """Run ``search`` through the real MCP adapter, as the session's context."""
    adapter, client = MCPAgentAdapter(), FakeMCPClient()
    session.config = {**session.config, "server_url": REMOTE}
    adapter._logs = {session.session_id: []}
    adapter._clients = {session.session_id: client}
    result = await adapter._do_execute(
        session, uuid.uuid4(), {"tool_name": "search", "arguments": {}})
    executed.extend(client.calls)
    return result


def mcp_session(ctx: ExecutionContext | None, agent_id: uuid.UUID) -> AgentSession:
    return AgentSession(session_id=str(uuid.uuid4()), agent_id=agent_id, adapter_type="mcp",
                        config={}, context=ctx)


class DispatchingAdapter:
    """An adapter whose task is one MCP tool call, made as its session's context."""

    def __init__(self, executed: list[str]) -> None:
        self.executed = executed

    async def create_session(self, agent_id, config):
        return mcp_session(None, agent_id)

    async def execute_task(self, session, task_id, payload):
        await mcp_dispatch(session, self.executed)
        return SimpleNamespace(success=True, output="", cost_cents=0, input_tokens=0,
                               output_tokens=0, error=None)

    async def terminate(self, session):
        pass


def dispatching_registry(executed: list[str]) -> Any:
    class Registry:
        def is_registered(self, name):
            return True

        def create_adapter(self, name, config):
            return DispatchingAdapter(executed)

    return Registry


async def spy_nodes(monkeypatch, executed: list[str]) -> None:
    import nexus.nodes.executor as node_executor
    import nexus.tools.mcp_server as mcp_server

    async def execute_node(name, arguments, **kw):
        executed.append(name)
        return SimpleNamespace(success=True, outputs={}, error=None)

    monkeypatch.setattr(mcp_server, "execute_node", execute_node)
    monkeypatch.setattr(node_executor, "execute_node", execute_node)


# Each driver sets up its case and makes one call; the matrix asserts the rest.
# "Soft" is a missing binding unless the path's soft case is an agentless one.


async def via_inbound_mcp(factory, t, kind, executed, monkeypatch) -> None:
    from nexus.tools.mcp_server import MCPServer

    await spy_nodes(monkeypatch, executed)
    if kind != "soft":
        await add(factory, binding(t, "bi"))
    if kind == "hard":
        await add(factory, deny_all(t))
    ctx = ExecutionContext.for_principal(run_principal(t), source=INBOUND_MCP)
    await MCPServer(ctx).call_tool(NODE, {"text": "{}"})


async def via_cli(factory, t, kind, executed, monkeypatch) -> None:
    """A CLI agent reaches NEXUS tools only with its run token, over inbound MCP."""
    from nexus.auth.run_tokens import mint_run_token
    from nexus.tools.mcp_server import MCPServer, authenticate

    await spy_nodes(monkeypatch, executed)
    if kind != "soft":
        await add(factory, binding(t, "bi"))
    if kind == "hard":
        await add(factory, deny_all(t))
    ctx = await authenticate(run_token=mint_run_token(uuid.uuid4(), t["a"], t["acme"]))
    await MCPServer(ctx).call_tool(NODE, {"text": "{}"})


async def via_node_rest(factory, t, kind, executed, monkeypatch) -> None:
    """Allowed needs an agent (a run token); a bare user is agentless (soft)."""
    from nexus.api.routes.nodes import NodeExecuteRequest, execute_node_endpoint

    await spy_nodes(monkeypatch, executed)
    await add(factory, binding(t, "bi"))
    principal = {"allowed": run_principal(t), "soft": user(t, "admin"),
                 "hard": user(t, "viewer")}[kind]
    try:
        await execute_node_endpoint(NODE, NodeExecuteRequest(params={"text": "{}"}),
                                    t["acme"], principal)
    except HTTPException as exc:
        assert exc.status_code == 403


async def via_mcp_adapter(factory, t, kind, executed, monkeypatch) -> None:
    if kind != "soft":
        await add(factory, binding(t))
    if kind == "hard":
        await add(factory, deny_all(t))
    await mcp_dispatch(mcp_session(agent_ctx(t, source="mcp"), t["a"]), executed)


async def via_hermes(factory, t, kind, executed, monkeypatch) -> None:
    """Hermes tools are local (no connection): soft is a session with no context."""
    adapter = HermesAdapter()
    adapter.register_tool("search", lambda **kw: executed.append("search") or "ok")
    if kind == "hard":
        await add(factory, deny_all(t))
    context = None if kind == "soft" else agent_ctx(t, source="hermes")
    await adapter._execute_tool("search", {}, agent_id=t["a"], context=context)


async def via_chat(factory, t, kind, executed, monkeypatch) -> None:
    if kind != "soft":
        await add(factory, binding(t))
    agent = SimpleNamespace(id=t["a"], company_id=t["acme"])
    principal = user(t, "viewer" if kind == "hard" else "admin")
    ctx = ExecutionContext.for_call(agent, principal, source="chat", session_id=t["s"])
    await mcp_dispatch(mcp_session(ctx, t["a"]), executed)


async def via_lifecycle(factory, t, kind, executed, monkeypatch) -> None:
    from nexus.runtime.lifecycle import AgentLifecycleManager

    if kind != "soft":
        await add(factory, binding(t))
    if kind == "hard":
        await add(factory, deny_all(t))
    async with factory() as db:
        adapter = DispatchingAdapter(executed)
        session = await AgentLifecycleManager(db, adapter).wake_agent(t["a"])
    await adapter.execute_task(session, uuid.uuid4(), {})


async def _activity(t, executed, monkeypatch, context: dict | None) -> None:
    import nexus.adapters.registry as registry_module
    from nexus.temporal.activities import ExecuteTaskInput, execute_task_activity

    monkeypatch.setattr(registry_module, "AdapterRegistry", dispatching_registry(executed))
    # config's company_id is not identity: only the started context is.
    await execute_task_activity(ExecuteTaskInput(
        task_id=str(uuid.uuid4()), agent_id=str(t["a"]), adapter_type="mcp",
        config={"company_id": str(t["other"])}, context=context))


async def via_temporal(factory, t, kind, executed, monkeypatch) -> None:
    if kind != "soft":
        await add(factory, binding(t))
    if kind == "hard":
        await add(factory, deny_all(t))
    agent = SimpleNamespace(id=t["a"], company_id=t["acme"])
    context = ExecutionContext.for_agent(agent, source="temporal").to_dict()
    await _activity(t, executed, monkeypatch, context)


async def via_task_flow(factory, t, kind, executed, monkeypatch) -> None:
    from nexus.workflows.task_flow import TaskFlow

    if kind != "soft":
        await add(factory, binding(t))
    principal = user(t, "viewer") if kind == "hard" else None
    context = TaskFlow(str(t["acme"]), principal=principal)._execution_context(t["a"], "mcp")
    await _activity(t, executed, monkeypatch, context)


async def via_company_flow(factory, t, kind, executed, monkeypatch) -> None:
    """Engineer sessions name no agent: only a run token gives them one."""
    from nexus.workflows.company_flow import CompanyWorkflow

    await add(factory, binding(t))
    principal = {"allowed": run_principal(t), "soft": None, "hard": user(t, "viewer")}[kind]
    flow = CompanyWorkflow(str(t["acme"]), adapter_registry=dispatching_registry(executed)(),
                           principal=principal)
    await flow._execute_engineer_task({"task_id": "t1", "description": "x"})


PATHS = {
    "inbound_mcp": (via_inbound_mcp, False),
    "cli": (via_cli, False),
    "node_rest": (via_node_rest, True),
    "mcp_adapter": (via_mcp_adapter, False),
    "hermes": (via_hermes, False),
    "chat": (via_chat, False),
    "lifecycle": (via_lifecycle, False),
    "temporal": (via_temporal, False),
    "task_flow": (via_task_flow, False),
    "company_flow": (via_company_flow, True),
}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind", ["allowed", "soft", "hard"])
@pytest.mark.parametrize("path", list(PATHS))
async def test_path_matrix(factory, t, monkeypatch, path, kind, mode) -> None:
    monkeypatch.setattr(settings, "tool_binding_enforcement", mode)
    driver, soft_is_agentless = PATHS[path]
    executed: list[str] = []

    await driver(factory, t, kind, executed, monkeypatch)

    authorization, runs = expected(kind, mode)
    assert bool(executed) is runs, executed
    await assert_recorded(factory, t, authorization,
                          agentless=soft_is_agentless and kind == "soft")
