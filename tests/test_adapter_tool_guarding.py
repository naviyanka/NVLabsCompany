"""Adapter tool loops must clear the same guardrails a ToolExecutor applies.

Both adapters dispatch tools by calling handlers directly, so they bypass
``ToolExecutor`` and everything it enforces. They now screen each call through
``guard_tool_call`` first. These tests go through each adapter's own entry point
rather than calling the guardrail chain directly, because the whole failure mode
being guarded against here is a correct check with no caller.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from nexus.adapters.hermes_adapter import HermesAdapter
from nexus.adapters.mcp_adapter import MCPAgentAdapter
from nexus.runtime.adapter import AgentSession
from nexus.tools.mcp_client import MCPResult

DANGEROUS = {"cmd": "rm -rf /"}
SAFE = {"cmd": "ls -la"}


def make_session() -> AgentSession:
    """A minimal session; neither adapter path needs a live backend."""
    return AgentSession(
        session_id=str(uuid.uuid4()),
        agent_id=uuid.uuid4(),
        adapter_type="test",
        config={},
    )


class TestHermesToolGuarding:
    """`HermesAdapter._execute_tool` is a real dispatch path."""

    async def test_dangerous_argument_is_refused(self) -> None:
        adapter = HermesAdapter()
        calls: list[dict[str, Any]] = []

        def handler(**kwargs: Any) -> str:
            calls.append(kwargs)
            return "should not run"

        adapter.register_tool("shell", handler)
        result = await adapter._execute_tool("shell", DANGEROUS)

        assert result["status"] == "guardrail_blocked"
        assert "guardrail" in result["error"].lower()
        assert calls == [], "handler ran despite a guardrail refusal"

    async def test_safe_argument_still_runs(self) -> None:
        adapter = HermesAdapter()
        calls: list[dict[str, Any]] = []

        def handler(**kwargs: Any) -> str:
            calls.append(kwargs)
            return "ok"

        adapter.register_tool("shell", handler)
        result = await adapter._execute_tool("shell", SAFE)

        assert result["status"] == "success"
        assert result["result"] == "ok"
        assert calls == [SAFE]

    async def test_unregistered_tool_behavior_is_unchanged(self) -> None:
        """The guardrail must not shadow the existing not-found response."""
        adapter = HermesAdapter()
        result = await adapter._execute_tool("nope", SAFE)

        assert result["status"] == "not_found"


class FakeMCPClient:
    """Stands in for a live MCP server; records what it was asked to run."""

    is_connected = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPResult:
        self.calls.append((tool_name, arguments))
        return MCPResult(content="ran", is_error=False, metadata={})


class TestMCPToolGuarding:
    """`MCPAdapter._do_execute` loops tool calls directly."""

    @pytest.fixture
    def adapter_with_client(self, monkeypatch: pytest.MonkeyPatch):
        adapter = MCPAgentAdapter()
        client = FakeMCPClient()
        return adapter, client

    async def test_dangerous_argument_is_refused(self, adapter_with_client) -> None:
        adapter, client = adapter_with_client
        session = make_session()
        adapter._logs = {session.session_id: []}
        adapter._clients = {session.session_id: client}

        result = await adapter._do_execute(
            session,
            uuid.uuid4(),
            {"tool_name": "shell", "arguments": DANGEROUS},
        )

        assert client.calls == [], "MCP tool ran despite a guardrail refusal"
        # The refusal reaches the model as an ordinary tool error, not an exception.
        assert result is not None

    async def test_safe_argument_reaches_the_server(self, adapter_with_client) -> None:
        adapter, client = adapter_with_client
        session = make_session()
        adapter._logs = {session.session_id: []}
        adapter._clients = {session.session_id: client}

        await adapter._do_execute(
            session,
            uuid.uuid4(),
            {"tool_name": "shell", "arguments": SAFE},
        )

        assert [name for name, _ in client.calls] == ["shell"]


class TestAutonomyGating:
    """With a known agent, the guard also resolves that agent's autonomy tier."""

    async def test_level_three_tool_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import nexus.tools.factory as factory

        class BlockingGate:
            async def check(self, **kwargs: Any) -> Any:
                class Decision:
                    allowed = False
                    reason = "Autonomy level 3 for 'delete_files' requires approval"
                    action_type = "delete_files"
                    correlation_id = uuid.uuid4()

                return Decision()

        monkeypatch.setattr(factory, "build_autonomy_gate", lambda db, **k: BlockingGate())

        refusal = await factory.guard_tool_call(
            "delete_file", {"path": "notes.txt"}, agent_id=uuid.uuid4()
        )

        assert refusal is not None
        assert refusal["status"] == "autonomy_blocked"
        assert "correlation_id" in refusal

    async def test_no_agent_id_skips_the_autonomy_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without an agent the tier cannot be resolved, so only guardrails run."""
        import nexus.tools.factory as factory

        def explode(*a: Any, **k: Any) -> Any:
            raise AssertionError("autonomy gate built without an agent_id")

        monkeypatch.setattr(factory, "build_autonomy_gate", explode)

        assert await factory.guard_tool_call("read_file", {"path": "notes.txt"}) is None

    async def test_guardrail_refusal_short_circuits_autonomy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A call the policy refuses outright is not sent for human approval."""
        import nexus.tools.factory as factory

        def explode(*a: Any, **k: Any) -> Any:
            raise AssertionError("autonomy gate consulted after a guardrail refusal")

        monkeypatch.setattr(factory, "build_autonomy_gate", explode)

        refusal = await factory.guard_tool_call("shell", DANGEROUS, agent_id=uuid.uuid4())
        assert refusal is not None
        assert refusal["status"] == "guardrail_blocked"

    async def test_allows_when_the_autonomy_check_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import nexus.tools.factory as factory

        def explode(*a: Any, **k: Any) -> Any:
            raise RuntimeError("no database")

        monkeypatch.setattr(factory, "build_autonomy_gate", explode)

        assert await factory.guard_tool_call("read_file", {}, agent_id=uuid.uuid4()) is None


class TestGuardHelper:
    """`guard_tool_call` is the shared screen both adapters use."""

    async def test_returns_none_for_a_safe_call(self) -> None:
        from nexus.tools.factory import guard_tool_call

        assert await guard_tool_call("shell", SAFE) is None

    async def test_returns_an_error_dict_for_a_blocked_call(self) -> None:
        from nexus.tools.factory import guard_tool_call

        refusal = await guard_tool_call("shell", DANGEROUS)
        assert refusal is not None
        assert refusal["status"] == "guardrail_blocked"

    async def test_allows_when_the_guardrail_itself_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bug inside a check must not take out legitimate work."""
        import nexus.tools.factory as factory

        class ExplodingChain:
            async def validate_tool_call(self, *a: Any, **k: Any) -> Any:
                raise RuntimeError("guardrail is broken")

        monkeypatch.setattr(factory, "build_guardrail_chain", lambda **k: ExplodingChain())

        assert await factory.guard_tool_call("shell", DANGEROUS) is None

    async def test_whitelist_refuses_an_unlisted_tool(self) -> None:
        from nexus.tools.factory import guard_tool_call

        refusal = await guard_tool_call("shell", SAFE, allowed_tools=["read_file"])
        assert refusal is not None
        assert refusal["status"] == "guardrail_blocked"
