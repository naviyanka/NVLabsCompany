"""Tests for the outward MCP server (src/nexus/tools/mcp_server.py, Phase 6.4).

The plan's acceptance shape is "an external MCP client lists and calls a scoped
tool", so the main test drives the real client -- StdioMCPTransport, the same
code that talks to third-party servers -- against a subprocess running this
server. If both sides agree, the wire format is right.

The rest pins the authorization surface, which is where a mistake is expensive:
tools/list must hide what tools/call would refuse, a write-risk tool must stay
denied under the read-only default, and a missing key must not start a server.
"""

import asyncio
import json
import sys
import textwrap
import uuid

import pytest

from nexus.nodes.registry import NodeCategory, NodeRegistry
from nexus.tools.mcp_server import (
    MCPServer,
    default_read_policy,
    exposed_nodes,
    input_schema_for,
    risk_level_for,
)
from nexus.tools.policy_engine import PolicyRule, ToolPolicyEngine

COMPANY_ID = uuid.uuid4()
PRINCIPAL_ID = uuid.uuid4()


def _engine(*rules: PolicyRule, default: str = "deny") -> ToolPolicyEngine:
    """A policy engine holding exactly the given rules."""
    engine = ToolPolicyEngine(default_effect=default)
    engine.load_policies(list(rules))
    return engine


def _server(engine: ToolPolicyEngine) -> MCPServer:
    """A server bound to the test company and the given policies."""
    return MCPServer(COMPANY_ID, PRINCIPAL_ID, engine)


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
    node = exposed_nodes()["http-request"]
    schema = input_schema_for(node)

    assert schema["type"] == "object"
    assert "url" in schema["required"]
    # headers is declared required=False on the node
    assert "headers" in schema["properties"]
    assert "headers" not in schema["required"]


def test_json_input_maps_to_object_not_string():
    """A 'json' node input is an object on the wire, not a JSON-encoded string."""
    schema = input_schema_for(exposed_nodes()["http-request"])
    assert schema["properties"]["headers"]["type"] == "object"


# --- policy ----------------------------------------------------------------


def test_read_only_default_hides_write_tools():
    """The baseline for a company with no policies must not expose writes."""
    server = _server(_engine(default_read_policy(COMPANY_ID)))
    listed = {t["name"] for t in server.list_tools()}

    nodes = exposed_nodes()
    reads = {i for i, n in nodes.items() if risk_level_for(n) == "read"}
    writes = {i for i, n in nodes.items() if risk_level_for(n) == "write"}

    assert listed == reads
    assert writes, "no write-risk tool in the catalog, test proves nothing"
    assert not (listed & writes)


@pytest.mark.asyncio
async def test_denied_tool_is_refused_even_when_named_directly():
    """Hiding a tool from tools/list is not enough; the call must also refuse."""
    server = _server(_engine(default_read_policy(COMPANY_ID)))
    write_tool = next(
        i for i, n in exposed_nodes().items() if risk_level_for(n) == "write"
    )

    result = await server.call_tool(write_tool, {})

    assert result["isError"] is True
    assert "Denied by policy" in result["content"][0]["text"]


def test_deny_rule_beats_lower_priority_allow():
    """Priority order decides, so a targeted deny overrides a broad allow."""
    server = _server(
        _engine(
            PolicyRule(
                name="deny http",
                priority=0,
                effect="deny",
                conditions={"tool_name": "http-request"},
            ),
            PolicyRule(
                name="allow everything",
                priority=100,
                effect="allow",
                conditions={},
            ),
        )
    )
    listed = {t["name"] for t in server.list_tools()}

    assert "http-request" not in listed
    assert "file-json-parse" in listed


def test_no_policies_at_all_exposes_nothing():
    """Default effect is deny: an empty policy set is a closed door."""
    assert _server(_engine()).list_tools() == []


@pytest.mark.asyncio
async def test_unknown_tool_is_an_error_result():
    server = _server(_engine(default_read_policy(COMPANY_ID)))
    result = await server.call_tool("no-such-tool", {})

    assert result["isError"] is True
    assert "Unknown tool" in result["content"][0]["text"]


# --- company scoping -------------------------------------------------------


@pytest.mark.asyncio
async def test_policies_of_another_company_do_not_apply():
    """Two servers, same tool, different company policies -- decisions differ."""
    permissive = MCPServer(
        COMPANY_ID,
        PRINCIPAL_ID,
        _engine(PolicyRule(name="allow all", priority=0, effect="allow", conditions={})),
    )
    restrictive = MCPServer(
        uuid.uuid4(),
        uuid.uuid4(),
        _engine(default_read_policy(COMPANY_ID)),
    )

    write_tool = next(
        i for i, n in exposed_nodes().items() if risk_level_for(n) == "write"
    )

    assert write_tool in {t["name"] for t in permissive.list_tools()}
    assert write_tool not in {t["name"] for t in restrictive.list_tools()}
    assert (await restrictive.call_tool(write_tool, {}))["isError"] is True


# --- JSON-RPC dispatch -----------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_reports_tools_capability():
    response = await _server(_engine()).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )

    assert response["id"] == 1
    assert "tools" in response["result"]["capabilities"]
    assert response["result"]["serverInfo"]["name"] == "nexus"


@pytest.mark.asyncio
async def test_notification_gets_no_response():
    """A JSON-RPC message without an id must not be answered."""
    response = await _server(_engine()).handle(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert response is None


@pytest.mark.asyncio
async def test_unknown_method_is_method_not_found():
    response = await _server(_engine()).handle(
        {"jsonrpc": "2.0", "id": 7, "method": "resources/list"}
    )
    assert response["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_tools_call_without_a_name_is_invalid_params():
    response = await _server(_engine()).handle(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {}}
    )
    assert response["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_non_object_arguments_are_rejected():
    """execute_node expects a mapping; a list must not reach it."""
    response = await _server(_engine()).handle(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "file-json-parse", "arguments": []},
        }
    )
    assert response["error"]["code"] == -32602


# --- execution -------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowed_tool_runs_and_returns_its_outputs():
    """The happy path: an allowed read tool executes through execute_node."""
    server = _server(_engine(default_read_policy(COMPANY_ID)))

    result = await server.call_tool("file-json-parse", {"text": '{"a": 1}'})

    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["data"] == {"a": 1}


@pytest.mark.asyncio
async def test_execution_failure_comes_back_as_a_tool_error():
    """A node that raises must not become a JSON-RPC error."""
    server = _server(_engine(default_read_policy(COMPANY_ID)))

    response = await server.handle(
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
async def test_guardrail_blocks_a_dangerous_argument():
    """guard_tool_call screens arguments before the node runs."""
    server = _server(
        _engine(PolicyRule(name="allow all", priority=0, effect="allow", conditions={}))
    )

    result = await server.call_tool(
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
async def test_serve_skips_malformed_lines_and_keeps_going():
    """One bad frame must not end an otherwise healthy session."""
    responses = await _drive(
        _server(_engine()),
        [
            "not json at all\n",
            "\n",
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n",
        ],
    )

    assert len(responses) == 1
    assert responses[0]["id"] == 1


@pytest.mark.asyncio
async def test_serve_writes_one_line_per_request():
    """Framing is newline-delimited; a client reads one response per readline."""
    responses = await _drive(
        _server(_engine()),
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n",
        ],
    )

    assert [r["id"] for r in responses] == [1, 2]


# --- end-to-end: our own client against our own server ---------------------


# Stands in for main(): same server, fixed policies, no DB or API key needed.
_HARNESS = textwrap.dedent(
    """
    import asyncio, sys, uuid
    from nexus.tools.mcp_server import MCPServer, StdinReader, serve
    from nexus.tools.policy_engine import PolicyRule, ToolPolicyEngine

    async def main():
        engine = ToolPolicyEngine(default_effect="deny")
        engine.load_policies([
            PolicyRule(name="allow reads", priority=0, effect="allow",
                       conditions={"risk_level": ["read"]}),
        ])
        server = MCPServer(uuid.uuid4(), uuid.uuid4(), engine)
        await serve(server, StdinReader(), sys.stdout)

    asyncio.run(main())
    """
)


@pytest.mark.asyncio
async def test_real_mcp_client_lists_and_calls_a_scoped_tool(tmp_path):
    """Phase 6.4's acceptance test, driven by the real StdioMCPTransport."""
    from nexus.tools.mcp_stdio import StdioMCPTransport

    harness = tmp_path / "harness.py"
    harness.write_text(_HARNESS)

    transport = StdioMCPTransport(timeout_seconds=30.0)
    info = await transport.connect(sys.executable, [str(harness)])
    try:
        assert info["name"] == "nexus"

        tools = await transport.list_tools()
        names = {t.name for t in tools}
        assert "file-json-parse" in names
        # scoped: the read-only policy withheld every write tool
        writes = {i for i, n in exposed_nodes().items() if risk_level_for(n) == "write"}
        assert not (names & writes)

        result = await transport.call_tool("file-json-parse", {"text": '{"b": 2}'})
        assert result.is_error is False
        assert json.loads(result.content)["data"] == {"b": 2}
    finally:
        await transport.disconnect()


# --- startup ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_refuses_to_start_without_an_api_key(monkeypatch, capsys):
    """No key, no server: there is no unauthenticated mode."""
    from nexus.tools import mcp_server

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    assert await mcp_server.main() == 1
    assert "NEXUS_API_KEY is required" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_main_refuses_an_unknown_api_key(monkeypatch, capsys):
    """An unresolvable key must fail closed, not fall back to a default scope."""
    from nexus.tools import mcp_server

    monkeypatch.setenv("NEXUS_API_KEY", "nv_not_a_real_key")

    async def _reject(credential):
        raise RuntimeError("NEXUS_API_KEY is not a valid, active API key")

    monkeypatch.setattr(mcp_server, "authenticate", _reject)

    assert await mcp_server.main() == 1
    assert "not a valid" in capsys.readouterr().err


def test_default_read_policy_denies_writes_by_omission():
    """The baseline allows read risk only; write falls through to default deny."""
    engine = _engine(default_read_policy(COMPANY_ID))

    assert engine.evaluate(PRINCIPAL_ID, "file-json-parse", "read").allowed
    assert not engine.evaluate(PRINCIPAL_ID, "msg-slack-send", "write").allowed


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
