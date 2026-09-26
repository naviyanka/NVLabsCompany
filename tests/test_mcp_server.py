"""Tests for the inbound MCP server (src/nexus/tools/mcp_server.py, Phase 6.4, P3.1).

The plan's acceptance shape is "an external MCP client lists and calls a scoped
tool", so the end-to-end test drives the real client -- StdioMCPTransport, the
same code that talks to third-party servers -- against a subprocess running
this server. If both sides agree, the wire format is right.

The rest pins the authorization surface, which is where a mistake is expensive.
Every call goes through ``guarded_call`` against a real SQLite database:
tools/list must hide what tools/call would refuse, a write-risk tool must stay
denied under the read-only default, identity comes only from the credential,
and a missing credential must not start a server. The binding/RBAC/cross-tenant
matrix shared with the other paths lives in ``test_execution_context.py``.
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.api_key import ApiKey
from nexus.models.company import Company
from nexus.models.tool import ToolPolicy
from nexus.models.tool_invocation import ToolInvocation
from nexus.nodes.registry import NodeCategory, NodeRegistry
from nexus.tools.context import INBOUND_MCP, ExecutionContext
from nexus.tools.mcp_server import (
    MCPServer,
    authenticate,
    exposed_nodes,
    input_schema_for,
    risk_level_for,
)


def _write_tool() -> str:
    return next(i for i, n in exposed_nodes().items() if risk_level_for(n) == "write")


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mcp.db'}")
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
    """Companies Acme and Other, one agent each."""
    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        a = Agent(company_id=acme.id, name="A", role="engineer")
        o = Agent(company_id=other.id, name="O", role="engineer")
        db.add_all([a, o])
        await db.commit()
    return {"acme": acme.id, "other": other.id, "a": a.id, "o": o.id}


def _server(t, *, company="acme", agent="a") -> MCPServer:
    """A server for a run token of ``agent`` in ``company``, as authenticate builds it."""
    principal = Principal(
        kind="run", company_id=t[company], role="agent", run_id=uuid.uuid4(), agent_id=t[agent]
    )
    return MCPServer(ExecutionContext.for_principal(principal, source=INBOUND_MCP))


async def _policy(factory, company_id, effect, conditions, priority=0) -> None:
    async with factory() as db:
        db.add(ToolPolicy(company_id=company_id, name=f"{effect} {conditions}",
                          priority=priority, effect=effect, conditions=conditions))
        await db.commit()


# --- exposure ---------------------------------------------------------------


def test_only_executable_nodes_are_exposed():
    """A browse-only node would advertise a tool that cannot run."""
    catalog = NodeRegistry()
    exposed = exposed_nodes()

    assert exposed, "no tools exposed at all"
    assert len(exposed) < catalog.count, "expected browse-only nodes to be excluded"

    from nexus.nodes.executor import get_default_registry

    assert set(exposed) == set(get_default_registry().executable_node_ids)


def test_input_schema_marks_only_required_inputs_required():
    """MCP clients validate against inputSchema, so required must be accurate."""
    schema = input_schema_for(exposed_nodes()["http-request"])

    assert schema["type"] == "object"
    assert "url" in schema["required"]
    # headers is declared required=False on the node
    assert "headers" in schema["properties"]
    assert "headers" not in schema["required"]


def test_json_input_maps_to_object_not_string():
    """A 'json' node input is an object on the wire, not a JSON-encoded string."""
    schema = input_schema_for(exposed_nodes()["http-request"])
    assert schema["properties"]["headers"]["type"] == "object"


def test_write_categories_cover_the_outbound_node_kinds():
    """Guards the classifier against a new outbound category defaulting to read."""
    from nexus.tools.mcp_server import _WRITE_CATEGORIES

    for category in (
        NodeCategory.HTTP,
        NodeCategory.DATABASE,
        NodeCategory.MESSAGING,
        NodeCategory.EMAIL,
    ):
        assert category in _WRITE_CATEGORIES


# --- policy ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_default_hides_write_tools(t):
    """A company with no policies exposes read-risk tools only."""
    listed = {x["name"] for x in await _server(t).list_tools()}

    nodes = exposed_nodes()
    reads = {i for i, n in nodes.items() if risk_level_for(n) == "read"}
    writes = {i for i, n in nodes.items() if risk_level_for(n) == "write"}

    assert listed == reads
    assert writes, "no write-risk tool in the catalog, test proves nothing"


@pytest.mark.asyncio
async def test_denied_tool_is_refused_even_when_named_directly(t):
    """Hiding a tool from tools/list is not enough; the call must also refuse."""
    result = await _server(t).call_tool(_write_tool(), {})

    assert result["isError"] is True
    assert "Denied by access policy" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_deny_rule_beats_lower_priority_allow(factory, t):
    """Priority order decides, so a targeted deny overrides a broad allow."""
    await _policy(factory, t["acme"], "deny", {"tool_name": "http-request"}, priority=0)
    await _policy(factory, t["acme"], "allow", {}, priority=100)

    listed = {x["name"] for x in await _server(t).list_tools()}

    assert "http-request" not in listed
    assert "file-json-parse" in listed


@pytest.mark.asyncio
async def test_company_policies_replace_the_read_only_baseline(factory, t):
    """Once a company writes policies, the baseline no longer applies."""
    await _policy(factory, t["acme"], "deny", {})
    assert await _server(t).list_tools() == []


@pytest.mark.asyncio
async def test_policies_of_another_company_do_not_apply(factory, t):
    """Acme allows everything; Other's caller still gets the read-only default."""
    await _policy(factory, t["acme"], "allow", {})
    write_tool = _write_tool()

    permissive = _server(t)
    restrictive = _server(t, company="other", agent="o")

    assert write_tool in {x["name"] for x in await permissive.list_tools()}
    assert write_tool not in {x["name"] for x in await restrictive.list_tools()}
    assert (await restrictive.call_tool(write_tool, {}))["isError"] is True


@pytest.mark.asyncio
async def test_unknown_tool_is_an_error_result(t):
    result = await _server(t).call_tool("no-such-tool", {})

    assert result["isError"] is True
    assert "Unknown tool" in result["content"][0]["text"]


# --- JSON-RPC dispatch -----------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_reports_tools_capability(t):
    response = await _server(t).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )

    assert response["id"] == 1
    assert "tools" in response["result"]["capabilities"]
    assert response["result"]["serverInfo"]["name"] == "nexus"


@pytest.mark.asyncio
async def test_notification_gets_no_response(t):
    """A JSON-RPC message without an id must not be answered."""
    response = await _server(t).handle(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert response is None


@pytest.mark.asyncio
async def test_unknown_method_is_method_not_found(t):
    response = await _server(t).handle({"jsonrpc": "2.0", "id": 7, "method": "resources/list"})
    assert response["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_tools_call_without_a_name_is_invalid_params(t):
    response = await _server(t).handle(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {}}
    )
    assert response["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_non_object_arguments_are_rejected(t):
    """execute_node expects a mapping; a list must not reach it."""
    response = await _server(t).handle(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "file-json-parse", "arguments": []},
        }
    )
    assert response["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_payload_identity_fields_are_ignored(factory, t):
    """A company or agent in the request is not authority; the credential's are used."""
    response = await _server(t).handle(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "file-json-parse",
                "arguments": {"text": "{}"},
                "company_id": str(t["other"]),
                "agent_id": str(t["o"]),
            },
        }
    )
    assert response["result"]["isError"] is False

    async with factory() as db:
        row = (await db.execute(select(ToolInvocation))).scalars().one()
    assert (row.company_id, row.agent_id) == (t["acme"], t["a"])


# --- execution -------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowed_tool_runs_and_is_recorded(factory, t):
    """The happy path: an allowed read tool executes and leaves an invocation row."""
    result = await _server(t).call_tool("file-json-parse", {"text": '{"a": 1}'})

    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["data"] == {"a": 1}

    async with factory() as db:
        row = (await db.execute(select(ToolInvocation))).scalars().one()
    assert row.tool_name == "file-json-parse"
    assert row.status == "success"
    assert row.authorization_detail["source"] == INBOUND_MCP
    assert row.authorization_detail["principal_role"] == "agent"


@pytest.mark.asyncio
async def test_execution_failure_comes_back_as_a_tool_error(t):
    """A node that fails must not become a JSON-RPC error."""
    response = await _server(t).handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "file-json-parse", "arguments": {"text": "not json"}},
        }
    )

    assert "error" not in response
    assert response["result"]["isError"] is True


@pytest.mark.asyncio
async def test_guardrail_blocks_a_dangerous_argument(factory, t):
    """guard_tool_call screens arguments before the node runs, even when policy allows."""
    await _policy(factory, t["acme"], "allow", {})

    result = await _server(t).call_tool(
        "db-sqlite-query", {"path": "/etc/passwd", "query": "SELECT 1"}
    )

    assert result["isError"] is True
    assert "guardrail" in result["content"][0]["text"].lower()


# --- serve loop ------------------------------------------------------------


async def _drive(server: MCPServer, lines: list[str]) -> list[dict]:
    """Run the serve loop over canned input, collecting written responses."""
    from nexus.tools.mcp_server import serve

    reader = asyncio.StreamReader()
    for line in lines:
        reader.feed_data(line.encode())
    reader.feed_eof()

    written: list[str] = []

    class _Sink:
        def write(self, text: str) -> None:
            written.append(text)

        def flush(self) -> None:
            pass

    await serve(server, reader, _Sink())
    return [json.loads(w) for w in written]


@pytest.mark.asyncio
async def test_serve_skips_malformed_lines_and_keeps_going(t):
    """One bad frame must not end an otherwise healthy session."""
    responses = await _drive(
        _server(t),
        [
            "not json at all\n",
            "\n",
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n",
        ],
    )

    assert len(responses) == 1
    assert responses[0]["id"] == 1


@pytest.mark.asyncio
async def test_serve_writes_one_line_per_request(t):
    """Framing is newline-delimited; a client reads one response per readline."""
    responses = await _drive(
        _server(t),
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n",
        ],
    )

    assert [r["id"] for r in responses] == [1, 2]


# --- end-to-end: our own client against our own server ---------------------


# Stands in for main(): same server and database path, with the seeded SQLite
# file in place of the configured database and the context a run token gives.
_HARNESS = textwrap.dedent(
    """
    import asyncio, sys, uuid
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    import nexus.database as database
    from nexus.auth.principal import Principal
    from nexus.config import settings
    from nexus.tools.context import INBOUND_MCP, ExecutionContext
    from nexus.tools.mcp_server import MCPServer, StdinReader, serve

    async def main():
        db_path, company_id, agent_id = sys.argv[1:4]
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        database.async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
        settings.tool_binding_enforcement = "audit"
        principal = Principal(kind="run", company_id=uuid.UUID(company_id), role="agent",
                              run_id=uuid.uuid4(), agent_id=uuid.UUID(agent_id))
        server = MCPServer(ExecutionContext.for_principal(principal, source=INBOUND_MCP))
        await serve(server, StdinReader(), sys.stdout)

    asyncio.run(main())
    """
)


@pytest.mark.asyncio
async def test_real_mcp_client_lists_and_calls_a_scoped_tool(tmp_path, t):
    """Phase 6.4's acceptance test, driven by the real StdioMCPTransport."""
    from nexus.tools.mcp_stdio import StdioMCPTransport

    harness = tmp_path / "harness.py"
    harness.write_text(_HARNESS)

    transport = StdioMCPTransport(timeout_seconds=30.0)
    info = await transport.connect(
        sys.executable, [str(harness), str(tmp_path / "mcp.db"), str(t["acme"]), str(t["a"])]
    )
    try:
        assert info["name"] == "nexus"

        names = {x.name for x in await transport.list_tools()}
        assert "file-json-parse" in names
        # scoped: the read-only default withheld every write tool
        assert _write_tool() not in names

        result = await transport.call_tool("file-json-parse", {"text": '{"b": 2}'})
        assert result.is_error is False
        assert json.loads(result.content)["data"] == {"b": 2}
    finally:
        await transport.disconnect()


# --- startup and credentials -----------------------------------------------


@pytest.mark.asyncio
async def test_main_refuses_to_start_without_a_credential(monkeypatch, capsys):
    """No credential, no server: there is no unauthenticated mode."""
    from nexus.tools import mcp_server

    monkeypatch.delenv("NEXUS_RUN_TOKEN", raising=False)
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    assert await mcp_server.main() == 1
    assert "NEXUS_API_KEY is required" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_main_refuses_an_unknown_api_key(factory, monkeypatch, capsys):
    """An unresolvable key must fail closed, not fall back to a default scope."""
    from nexus.tools import mcp_server

    monkeypatch.delenv("NEXUS_RUN_TOKEN", raising=False)
    monkeypatch.setenv("NEXUS_API_KEY", "nv_not_a_real_key")

    assert await mcp_server.main() == 1
    assert "not a valid" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_run_token_fixes_company_agent_and_role(t):
    """The token's company and agent, with the agent role; nothing else can set them."""
    from nexus.auth.run_tokens import mint_run_token

    ctx = await authenticate(run_token=mint_run_token(uuid.uuid4(), t["a"], t["acme"]))

    assert (ctx.company_id, ctx.agent_id, ctx.principal_role) == (t["acme"], t["a"], "agent")
    assert ctx.source == INBOUND_MCP
    assert ctx.principal_id.startswith("run:")


@pytest.mark.asyncio
async def test_forged_run_token_is_refused():
    with pytest.raises(RuntimeError, match="NEXUS_RUN_TOKEN is not valid"):
        await authenticate(run_token="not.a.jwt")


@pytest.mark.asyncio
async def test_api_key_role_comes_from_the_key(factory, t):
    """A service principal: the key's company and role, and no agent."""
    plaintext = ApiKey.generate_key()
    async with factory() as db:
        db.add(ApiKey(company_id=t["acme"], name="k", key_prefix=ApiKey.get_prefix(plaintext),
                      key_hash=ApiKey.hash_key(plaintext), role="viewer"))
        await db.commit()

    ctx = await authenticate(api_key=plaintext)

    assert (ctx.company_id, ctx.principal_role, ctx.agent_id) == (t["acme"], "viewer", None)
    assert ctx.principal_id.startswith("service:")


@pytest.mark.asyncio
async def test_session_id_must_be_a_uuid(t):
    from nexus.auth.run_tokens import mint_run_token

    with pytest.raises(RuntimeError, match="NEXUS_SESSION_ID"):
        await authenticate(
            run_token=mint_run_token(uuid.uuid4(), t["a"], t["acme"]), session_id="nope"
        )
