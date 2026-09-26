"""P3.1: one server-side ExecutionContext, one boundary, on every tool path.

Pins the canonical invariant: a governed tool call runs only with a
server-validated company, principal, role, agent, session and connection, and
nothing a client, model or payload supplies can grant authority.

* RBAC: the role is the authenticated principal's (viewer, manager, admin,
  agent, service key), never a default.
* Inbound MCP: binding, disabled binding/tool, RBAC, policy and profile,
  cross-company identity, and the same invocation/audit record as outbound.
* CLI: a payload cannot give a CLI agent its own tools or switch its
  permission checks off, and its only route to NEXUS tools is refused like
  any other caller.
* Autonomy runs under the tenant the call was authorized for.
* The REST node route crosses the same boundary.

Enforcement stays ``audit`` globally; tests that need ``enforce`` set it.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
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
from nexus.tools.access import (
    ALLOWED,
    BUILTIN_ENDPOINT,
    BUILTIN_TRANSPORT,
    DENIED,
    WOULD_DENY,
    check_cli_args,
    check_tool_access,
)
from nexus.tools.context import INBOUND_MCP, ExecutionContext
from nexus.tools.mcp_server import MCPServer

TOOL = "file-json-parse"  # a read-risk builtin node
REMOTE = "https://mcp.acme.test/rpc"


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ctx.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", maker)
    monkeypatch.setattr(settings, "tool_binding_enforcement", "audit")
    yield maker
    await engine.dispose()


@pytest.fixture
async def t(factory):
    """Acme: agent A with session S, the builtin connection B (catalog: TOOL)
    and a remote connection R (catalog: search). Other: agent O."""
    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        a = Agent(company_id=acme.id, name="A", role="engineer")
        o = Agent(company_id=other.id, name="O", role="engineer")
        db.add_all([a, o])
        await db.flush()
        s = AgentSessionRecord(company_id=acme.id, agent_id=a.id)
        b = ToolConnection(company_id=acme.id, name="nexus", transport_type=BUILTIN_TRANSPORT,
                           endpoint_url=BUILTIN_ENDPOINT)
        r = ToolConnection(company_id=acme.id, name="r", transport_type="mcp_remote",
                           endpoint_url=REMOTE)
        db.add_all([s, b, r])
        await db.flush()
        db.add_all([
            ToolCatalogEntry(company_id=acme.id, connection_id=b.id, tool_name=TOOL,
                             risk_level="read"),
            ToolCatalogEntry(company_id=acme.id, connection_id=r.id, tool_name="search",
                             risk_level="read"),
        ])
        await db.commit()
    return {"acme": acme.id, "other": other.id, "a": a.id, "o": o.id, "s": s.id,
            "b": b.id, "r": r.id}


async def add(factory, *rows: Any) -> None:
    async with factory() as db:
        db.add_all(rows)
        await db.commit()


def bind(t, connection="b", **fields: Any) -> McpBinding:
    return McpBinding(company_id=t["acme"], connection_id=t[connection], target_type="agent",
                      agent_id=t["a"], **fields)


def run_ctx(t, *, company="acme", agent="a", session=None) -> ExecutionContext:
    """What a run token for ``agent`` in ``company`` authenticates to."""
    principal = Principal(kind="run", company_id=t[company], role="agent",
                          run_id=uuid.uuid4(), agent_id=t[agent])
    return ExecutionContext.for_principal(
        principal, source=INBOUND_MCP, session_id=t[session] if session else None
    )


async def invocations(factory) -> list[ToolInvocation]:
    async with factory() as db:
        return list((await db.execute(select(ToolInvocation))).scalars().all())


async def call(t, ctx=None) -> dict:
    return await MCPServer(ctx or run_ctx(t)).call_tool(TOOL, {"text": "{}"})


# --- RBAC: the principal's role ---------------------------------------------


@pytest.mark.parametrize(
    ("kind", "role", "allowed"),
    [
        ("user", "viewer", False),
        ("user", "manager", True),
        ("user", "admin", True),
        ("run", "agent", True),
        ("service", "viewer", False),
        ("service", "manager", True),
    ],
)
@pytest.mark.asyncio
async def test_role_comes_from_the_principal(factory, t, kind, role, allowed):
    """RBAC reads the principal's role; a viewer is refused even in audit mode."""
    principal = Principal(kind=kind, company_id=t["acme"], role=role, user_id=uuid.uuid4(),
                          api_key_id=uuid.uuid4(), run_id=uuid.uuid4(), agent_id=t["a"])
    ctx = ExecutionContext.for_principal(principal, source="chat", agent_id=t["a"])
    assert ctx.principal_role == role

    async with factory() as db:
        decision = await check_tool_access(db, ctx, tool_name="search", connection_id=t["r"])

    rbac = any(p["stage"] == "rbac" for p in decision.problems)
    assert rbac is not allowed
    if not allowed:
        assert decision.outcome == DENIED


def test_for_call_uses_the_principal_not_the_agent_role(t):
    """With a principal present there is no silent fallback to the agent role."""
    agent = Agent(id=t["a"], company_id=t["acme"], name="A", role="engineer")
    viewer = Principal(kind="user", company_id=t["acme"], role="viewer", user_id=uuid.uuid4())

    assert ExecutionContext.for_call(agent, viewer, source="chat").principal_role == "viewer"
    assert ExecutionContext.for_call(agent, None, source="scheduler").principal_role == "agent"


def test_run_principal_cannot_act_for_another_agent(t):
    principal = Principal(kind="run", company_id=t["acme"], role="agent",
                          run_id=uuid.uuid4(), agent_id=t["a"])
    with pytest.raises(PermissionError):
        ExecutionContext.for_principal(principal, source="chat", agent_id=uuid.uuid4())


# --- inbound MCP matrix -----------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_valid_binding_is_allowed(factory, t, monkeypatch):
    monkeypatch.setattr(settings, "tool_binding_enforcement", "enforce")
    await add(factory, bind(t))

    assert (await call(t))["isError"] is False
    [row] = await invocations(factory)
    assert row.authorization == ALLOWED
    assert (row.company_id, row.agent_id, row.connection_id) == (t["acme"], t["a"], t["b"])
    assert row.authorization_detail["binding_ids"]


@pytest.mark.asyncio
async def test_inbound_missing_binding(factory, t, monkeypatch):
    """Audit mode runs and records would_deny; enforce refuses."""
    assert (await call(t))["isError"] is False
    monkeypatch.setattr(settings, "tool_binding_enforcement", "enforce")
    refused = await call(t)

    assert refused["isError"] is True
    assert "no active binding" in refused["content"][0]["text"]
    audit, enforce = await invocations(factory)
    assert (audit.authorization, audit.status) == (WOULD_DENY, "success")
    assert (enforce.authorization, enforce.status) == (DENIED, "denied")


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param(lambda t: [bind(t, status="disabled")], id="binding-disabled"),
        pytest.param(lambda t: [bind(t, disabled_tools=[TOOL])], id="tool-disabled-by-binding"),
    ],
)
@pytest.mark.asyncio
async def test_inbound_disabled_binding_or_tool_is_refused(factory, t, monkeypatch, rows):
    monkeypatch.setattr(settings, "tool_binding_enforcement", "enforce")
    await add(factory, *rows(t))

    assert (await call(t))["isError"] is True
    [row] = await invocations(factory)
    assert row.authorization == DENIED


@pytest.mark.asyncio
async def test_inbound_catalog_disabled_tool_is_refused(factory, t, monkeypatch):
    monkeypatch.setattr(settings, "tool_binding_enforcement", "enforce")
    await add(factory, bind(t))
    async with factory() as db:
        entry = (await db.execute(select(ToolCatalogEntry).where(
            ToolCatalogEntry.tool_name == TOOL))).scalars().one()
        entry.is_active = False
        await db.commit()

    assert (await call(t))["isError"] is True


@pytest.mark.asyncio
async def test_inbound_rbac_refuses_a_viewer_key(factory, t):
    """A viewer API key is refused in audit mode too: RBAC is a hard stage."""
    await add(factory, bind(t))
    principal = Principal(kind="service", company_id=t["acme"], role="viewer",
                          api_key_id=uuid.uuid4())
    ctx = ExecutionContext.for_principal(principal, source=INBOUND_MCP)

    result = await call(t, ctx)

    assert result["isError"] is True
    assert "rbac" in result["content"][0]["text"]
    assert TOOL not in {x["name"] for x in await MCPServer(ctx).list_tools()}


@pytest.mark.asyncio
async def test_inbound_policy_deny_beats_a_binding(factory, t):
    """A binding grants the connection; it never overrides a policy deny."""
    await add(factory, bind(t),
              ToolPolicy(company_id=t["acme"], name="no json", priority=0, effect="deny",
                         conditions={"tool_name": TOOL}))

    result = await call(t)

    assert result["isError"] is True
    assert "policy" in result["content"][0]["text"]
    [row] = await invocations(factory)
    assert row.authorization == DENIED


@pytest.mark.asyncio
async def test_profile_default_deny_applies(factory, t):
    """A ToolProfile bound to the agent sets the default effect when no policy matches."""
    profile = ToolProfile(company_id=t["acme"], name="locked", default_action="deny")
    await add(factory, profile)
    await add(factory, ToolProfileBinding(company_id=t["acme"], profile_id=profile.id,
                                          target_type="agent", target_id=t["a"]),
              ToolPolicy(company_id=t["acme"], name="other tool", priority=0, effect="allow",
                         conditions={"tool_name": "something-else"}))

    assert (await call(t))["isError"] is True


@pytest.mark.asyncio
async def test_inbound_cross_company_identity_is_refused(factory, t):
    """A token naming Other's company with Acme's agent (or session) cannot run."""
    await add(factory, bind(t))

    foreign_agent = await call(t, run_ctx(t, company="other", agent="a"))
    foreign_session = await call(t, run_ctx(t, agent="o", company="acme", session="s"))

    assert foreign_agent["isError"] is True
    assert "agent not found in this company" in foreign_agent["content"][0]["text"]
    assert foreign_session["isError"] is True


@pytest.mark.asyncio
async def test_inbound_records_what_outbound_records(factory, t):
    """Same boundary, same row: inbound and outbound would_deny produce matching
    tool_invocations detail and an audit_log entry each."""
    from nexus.tools.factory import guarded_call

    assert (await call(t))["isError"] is False  # no binding: would_deny

    outbound_ctx = ExecutionContext.for_agent(
        Agent(id=t["a"], company_id=t["acme"], name="A", role="engineer"), source="mcp"
    )

    async def run():
        return "ok"

    out = await guarded_call(outbound_ctx, "search", {}, run, source="mcp", endpoint_url=REMOTE)
    assert out["status"] == "success"

    inbound, outbound = await invocations(factory)
    assert inbound.authorization == outbound.authorization == WOULD_DENY
    assert set(inbound.authorization_detail) == set(outbound.authorization_detail)
    assert inbound.authorization_detail["source"] == INBOUND_MCP
    async with factory() as db:
        audits = (await db.execute(select(AuditLog))).scalars().all()
    assert sorted(a.action for a in audits) == ["tool.access_would_deny"] * 2


# --- CLI / out-of-process ---------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["--mcp-config", "evil.json"],
        ["--dangerously-skip-permissions"],
        ["--permission-mode=bypassPermissions"],
        ["--allowedTools", "Bash"],
        "--yolo",
    ],
)
def test_cli_payload_cannot_grant_tools_or_disable_permissions(args):
    assert check_cli_args(args)


def test_cli_payload_plain_args_pass():
    assert check_cli_args(["--verbose"]) is None
    assert check_cli_args(None) is None


@pytest.mark.parametrize("adapter_path", ["claude_code_adapter.ClaudeCodeAdapter",
                                          "cli_adapter.CLIAdapter"])
@pytest.mark.asyncio
async def test_cli_adapters_refuse_before_spawning(monkeypatch, adapter_path):
    import asyncio
    import importlib

    module, cls = adapter_path.split(".")
    adapter = getattr(importlib.import_module(f"nexus.adapters.{module}"), cls)()

    async def no_spawn(*a, **kw):
        raise AssertionError("subprocess spawned")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_spawn)
    session = AgentSession(session_id="s", agent_id=uuid.uuid4(), adapter_type="cli")

    result = await adapter._do_execute(
        session, uuid.uuid4(), {"prompt": "x", "args": ["--mcp-config", "x.json"]}
    )

    assert result.success is False


@pytest.mark.asyncio
async def test_denied_tool_cannot_run_through_the_cli_route(factory, t, monkeypatch):
    """A CLI agent's run token reaches NEXUS tools only via inbound MCP, where a
    policy-denied tool is refused and the node never executes."""
    import nexus.tools.mcp_server as mcp_server

    executed: list[str] = []

    async def spy(name, arguments, **kw):
        executed.append(name)

    monkeypatch.setattr(mcp_server, "execute_node", spy)
    await add(factory, bind(t),
              ToolPolicy(company_id=t["acme"], name="deny all", priority=0, effect="deny",
                         conditions={}))

    assert (await call(t))["isError"] is True
    assert executed == []


# --- autonomy under the tenant ------------------------------------------------


@pytest.mark.asyncio
async def test_autonomy_runs_under_the_authorized_company(factory, t, monkeypatch):
    import contextlib

    import nexus.database as database
    import nexus.tools.factory as tool_factory

    tenants: list[uuid.UUID] = []
    real = database.tenant_session

    @contextlib.asynccontextmanager
    async def spy_session(company_id):
        tenants.append(company_id)
        async with real(company_id) as db:
            yield db

    seen: dict[str, Any] = {}

    class Gate:
        async def check(self, **kw):
            seen.update(kw)
            return type("D", (), {"allowed": False, "reason": "needs approval",
                                  "action_type": "x", "correlation_id": uuid.uuid4()})()

    monkeypatch.setattr(database, "tenant_session", spy_session)
    monkeypatch.setattr(tool_factory, "build_autonomy_gate", lambda db: Gate())
    await add(factory, bind(t))

    result = await call(t)

    assert result["isError"] is True
    assert seen["company_id"] == t["acme"] and seen["agent_id"] == t["a"]
    assert tenants and set(tenants) == {t["acme"]}
    [row] = await invocations(factory)
    assert row.status == "autonomy_blocked"


@pytest.mark.skipif(settings.database_url.startswith("sqlite"), reason="needs PostgreSQL RLS")
@pytest.mark.asyncio
async def test_access_session_sets_the_rls_tenant():
    from sqlalchemy import text

    from nexus.tools.factory import _access_session

    company_id = uuid.uuid4()
    async with _access_session(company_id) as db:
        value = (await db.execute(text("SELECT current_setting('nexus.company_id')"))).scalar()
    assert value == str(company_id)


# --- REST node route ------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_route_crosses_the_same_boundary(factory, t, monkeypatch):
    from nexus.api.routes.nodes import NodeExecuteRequest, execute_node_endpoint

    body = NodeExecuteRequest(params={"text": "{}"})
    viewer = Principal(kind="user", company_id=t["acme"], role="viewer", user_id=uuid.uuid4())
    admin = Principal(kind="user", company_id=t["acme"], role="admin", user_id=uuid.uuid4())

    with pytest.raises(HTTPException) as refused:
        await execute_node_endpoint(TOOL, body, t["acme"], viewer)
    assert refused.value.status_code == 403

    # No agent behind a direct user call: audit mode records it as would_deny...
    assert (await execute_node_endpoint(TOOL, body, t["acme"], admin)).success is True
    # ...and enforce refuses it.
    monkeypatch.setattr(settings, "tool_binding_enforcement", "enforce")
    with pytest.raises(HTTPException):
        await execute_node_endpoint(TOOL, body, t["acme"], admin)

    rows = await invocations(factory)
    assert [r.authorization for r in rows] == [DENIED, WOULD_DENY, DENIED]
    assert all(r.agent_id is None and r.company_id == t["acme"] for r in rows)
    assert {r.authorization_detail["source"] for r in rows} == {"node_api"}


# --- Each path builds its context on the server -----------------------------
#
# Chat, lifecycle, the Temporal activity, task_flow and company_flow each put
# an ExecutionContext on the adapter session, and the adapter hands it to
# guarded_call (covered in test_tool_access). These pin what each path builds.


def _user(t, role: str) -> Principal:
    return Principal(kind="user", company_id=t["acme"], role=role, user_id=uuid.uuid4())


def test_task_flow_context_is_the_agent_or_the_principal(t):
    from nexus.workflows.task_flow import TaskFlow

    ctx = ExecutionContext.from_dict(TaskFlow(str(t["acme"]))._execution_context(t["a"], "mcp"))
    assert (ctx.company_id, ctx.agent_id, ctx.principal_id, ctx.principal_role, ctx.source) == (
        t["acme"], t["a"], f"agent:{t['a']}", "agent", "task_flow")

    viewer = TaskFlow(str(t["acme"]), principal=_user(t, "viewer"))
    assert viewer._execution_context(t["a"], "mcp")["principal_role"] == "viewer"

    run = Principal(kind="run", company_id=t["acme"], role="agent", run_id=uuid.uuid4(),
                    agent_id=t["a"])
    assert TaskFlow(str(t["acme"]), principal=run)._execution_context(t["o"], "mcp") is None
    assert TaskFlow("not-a-uuid")._execution_context(t["a"], "mcp") is None


def test_company_flow_context_names_no_agent(t):
    from nexus.workflows.company_flow import CompanyWorkflow

    ctx = CompanyWorkflow(str(t["acme"]))._execution_context("mcp")
    assert (ctx.company_id, ctx.agent_id, ctx.principal_role, ctx.source) == (
        t["acme"], None, "agent", "company_flow")
    manager = CompanyWorkflow(str(t["acme"]), principal=_user(t, "manager"))
    assert manager._execution_context("mcp").principal_role == "manager"
    assert CompanyWorkflow("not-a-uuid")._execution_context("mcp") is None


async def test_lifecycle_session_acts_as_the_agent_in_its_company(factory, t):
    from nexus.runtime.lifecycle import AgentLifecycleManager

    class Adapter:
        async def create_session(self, agent_id, config):
            return AgentSession(session_id="s", agent_id=agent_id, adapter_type="fake")

    async with factory() as db:
        session = await AgentLifecycleManager(db, Adapter()).wake_agent(t["a"])
    ctx = session.context
    assert (ctx.company_id, ctx.agent_id, ctx.principal_id, ctx.principal_role, ctx.source) == (
        t["acme"], t["a"], f"agent:{t['a']}", "agent", "lifecycle")


async def test_temporal_activity_puts_the_started_context_on_the_session(t, monkeypatch):
    from types import SimpleNamespace

    import nexus.adapters.registry as registry_module
    from nexus.temporal.activities import ExecuteTaskInput, execute_task_activity

    seen: list[Any] = []

    class Adapter:
        async def create_session(self, agent_id, config):
            return AgentSession(session_id="s", agent_id=agent_id, adapter_type="fake")

        async def execute_task(self, session, task_id, payload):
            seen.append(session.context)
            return SimpleNamespace(success=True, output="", cost_cents=0, input_tokens=0,
                                   output_tokens=0, error=None)

        async def terminate(self, session):
            pass

    class Registry:
        def is_registered(self, name):
            return True

        def create_adapter(self, name, config):
            return Adapter()

    monkeypatch.setattr(registry_module, "AdapterRegistry", Registry)
    started = ExecutionContext.for_agent(
        SimpleNamespace(id=t["a"], company_id=t["acme"]), source="task_flow")
    out = await execute_task_activity(ExecuteTaskInput(
        task_id=str(uuid.uuid4()), agent_id=str(t["a"]), adapter_type="fake",
        config={"company_id": str(t["other"])}, context=started.to_dict()))
    assert out.success
    assert seen == [started]  # config's company_id is not identity


def test_chat_context_is_the_principal_else_the_agent(t):
    from types import SimpleNamespace

    agent = SimpleNamespace(id=t["a"], company_id=t["acme"])
    ctx = ExecutionContext.for_call(agent, _user(t, "viewer"), source="chat")
    assert (ctx.principal_role, ctx.agent_id, ctx.source) == ("viewer", t["a"], "chat")
    ctx = ExecutionContext.for_call(agent, None, source="background")
    assert (ctx.principal_id, ctx.principal_role) == (f"agent:{t['a']}", "agent")
