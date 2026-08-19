"""Comprehensive tests for the ControlRegistry module."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.governance.control_registry import (
    MAX_STEER_BYTES,
    AgentControlSnapshot,
    ControlRegistry,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_registry() -> ControlRegistry:
    """Create a fresh ControlRegistry for testing."""
    return ControlRegistry()


# ── Test: Pause Denies All Tools ─────────────────────────────────────────────


class TestPause:
    """Tests for the pause functionality."""

    def test_pause_denies_all_tools(self):
        """A paused agent should have all tool calls denied."""
        reg = _make_registry()
        reg.pause("agent-1", True)

        deny, reason = reg.tool_decision("agent-1", "read_file")
        assert deny is True
        assert reason is not None
        assert "Paused" in reason

        deny2, reason2 = reg.tool_decision("agent-1", "write_file")
        assert deny2 is True
        assert reason2 is not None

    def test_unpause_allows_tools(self):
        """Unpausing an agent should allow tool calls again."""
        reg = _make_registry()
        reg.pause("agent-1", True)
        reg.pause("agent-1", False)

        deny, reason = reg.tool_decision("agent-1", "read_file")
        assert deny is False
        assert reason is None

    def test_pause_on_false_unpauses(self):
        """Calling pause with on=False should clear the paused state."""
        reg = _make_registry()
        reg.pause("agent-1", True)
        reg.pause("agent-1", False)

        snap = reg.snapshot("agent-1")
        assert snap.paused is False


# ── Test: Gate Denies Specific Tool ──────────────────────────────────────────


class TestGateTool:
    """Tests for tool gating functionality."""

    def test_gate_denies_specific_tool(self):
        """A gated tool should be denied for the agent."""
        reg = _make_registry()
        reg.gate_tool("agent-1", "dangerous_tool", True)

        deny, reason = reg.tool_decision("agent-1", "dangerous_tool")
        assert deny is True
        assert reason is not None
        assert "gated" in reason

    def test_gate_allows_other_tools(self):
        """Non-gated tools should still be allowed."""
        reg = _make_registry()
        reg.gate_tool("agent-1", "dangerous_tool", True)

        deny, reason = reg.tool_decision("agent-1", "safe_tool")
        assert deny is False
        assert reason is None

    def test_ungate_tool(self):
        """Ungating a tool should allow it again."""
        reg = _make_registry()
        reg.gate_tool("agent-1", "dangerous_tool", True)
        reg.gate_tool("agent-1", "dangerous_tool", False)

        deny, reason = reg.tool_decision("agent-1", "dangerous_tool")
        assert deny is False
        assert reason is None

    def test_multiple_gated_tools(self):
        """Multiple tools can be gated independently."""
        reg = _make_registry()
        reg.gate_tool("agent-1", "tool_a", True)
        reg.gate_tool("agent-1", "tool_b", True)

        deny_a, _ = reg.tool_decision("agent-1", "tool_a")
        deny_b, _ = reg.tool_decision("agent-1", "tool_b")
        deny_c, _ = reg.tool_decision("agent-1", "tool_c")

        assert deny_a is True
        assert deny_b is True
        assert deny_c is False


# ── Test: Steer FIFO Queue ───────────────────────────────────────────────────


class TestSteer:
    """Tests for the steer guidance queue."""

    def test_steer_enqueues_and_take_dequeues_fifo(self):
        """Steer entries are dequeued in FIFO order."""
        reg = _make_registry()
        reg.steer("agent-1", "first guidance")
        reg.steer("agent-1", "second guidance")
        reg.steer("agent-1", "third guidance")

        assert reg.take_steer("agent-1") == "first guidance"
        assert reg.take_steer("agent-1") == "second guidance"
        assert reg.take_steer("agent-1") == "third guidance"
        assert reg.take_steer("agent-1") is None

    def test_steer_max_10kb_truncation(self):
        """Steer entries longer than 10KB are truncated."""
        reg = _make_registry()
        long_text = "x" * 20_000
        reg.steer("agent-1", long_text)

        result = reg.take_steer("agent-1")
        assert result is not None
        assert len(result) == MAX_STEER_BYTES

    def test_steer_trims_whitespace(self):
        """Steer entries are trimmed of leading/trailing whitespace."""
        reg = _make_registry()
        reg.steer("agent-1", "  guidance with spaces  ")

        result = reg.take_steer("agent-1")
        assert result == "guidance with spaces"

    def test_steer_empty_text_ignored(self):
        """Empty or whitespace-only steer text is not enqueued."""
        reg = _make_registry()
        reg.steer("agent-1", "")
        reg.steer("agent-1", "   ")

        assert reg.take_steer("agent-1") is None

    def test_take_steer_unknown_agent_returns_none(self):
        """take_steer for an unknown agent returns None."""
        reg = _make_registry()
        assert reg.take_steer("unknown-agent") is None

    def test_clear_steers(self):
        """clear_steers removes all pending steer notes."""
        reg = _make_registry()
        reg.steer("agent-1", "note 1")
        reg.steer("agent-1", "note 2")
        reg.clear_steers("agent-1")

        assert reg.take_steer("agent-1") is None

    def test_clear_steers_unknown_agent_noop(self):
        """clear_steers on an unknown agent does not raise."""
        reg = _make_registry()
        reg.clear_steers("unknown-agent")  # Should not raise


# ── Test: Halt ───────────────────────────────────────────────────────────────


class TestHalt:
    """Tests for the halt functionality."""

    def test_halt_sets_flag(self):
        """Halting an agent sets the halt flag."""
        reg = _make_registry()
        reg.halt("agent-1")

        assert reg.should_halt("agent-1") is True

    def test_should_halt_unknown_agent_returns_false(self):
        """should_halt for an unknown agent returns False."""
        reg = _make_registry()
        assert reg.should_halt("unknown-agent") is False


# ── Test: Resume ─────────────────────────────────────────────────────────────


class TestResume:
    """Tests for the resume functionality."""

    def test_resume_clears_pause_and_halt(self):
        """Resume clears both pause and halt flags."""
        reg = _make_registry()
        reg.pause("agent-1", True)
        reg.halt("agent-1")
        reg.resume("agent-1")

        snap = reg.snapshot("agent-1")
        assert snap.paused is False
        assert snap.halted is False

    def test_resume_keeps_gates(self):
        """Resume preserves gated tools."""
        reg = _make_registry()
        reg.gate_tool("agent-1", "tool_a", True)
        reg.gate_tool("agent-1", "tool_b", True)
        reg.pause("agent-1", True)
        reg.halt("agent-1")
        reg.resume("agent-1")

        snap = reg.snapshot("agent-1")
        assert "tool_a" in snap.gated_tools
        assert "tool_b" in snap.gated_tools

        deny, _ = reg.tool_decision("agent-1", "tool_a")
        assert deny is True


# ── Test: Snapshot ───────────────────────────────────────────────────────────


class TestSnapshot:
    """Tests for the snapshot functionality."""

    def test_snapshot_returns_correct_state(self):
        """Snapshot reflects the current control state."""
        reg = _make_registry()
        reg.pause("agent-1", True)
        reg.gate_tool("agent-1", "tool_a", True)
        reg.steer("agent-1", "guidance 1")
        reg.steer("agent-1", "guidance 2")

        snap = reg.snapshot("agent-1")
        assert snap.paused is True
        assert snap.halted is False
        assert snap.auto_delivery_paused is False
        assert "tool_a" in snap.gated_tools
        assert snap.pending_steers == 2

    def test_snapshot_unknown_agent_returns_defaults(self):
        """Snapshot for an unknown agent returns all-false defaults."""
        reg = _make_registry()
        snap = reg.snapshot("unknown-agent")

        assert snap.paused is False
        assert snap.halted is False
        assert snap.auto_delivery_paused is False
        assert snap.gated_tools == []
        assert snap.pending_steers == 0

    def test_snapshot_is_agentcontrolsnapshot(self):
        """Snapshot returns an AgentControlSnapshot instance."""
        reg = _make_registry()
        snap = reg.snapshot("agent-1")
        assert isinstance(snap, AgentControlSnapshot)


# ── Test: Auto Delivery Paused ───────────────────────────────────────────────


class TestAutoDeliveryPaused:
    """Tests for auto-delivery pause functionality."""

    def test_pause_auto_delivery(self):
        """pause_auto_delivery sets the flag correctly."""
        reg = _make_registry()
        reg.pause_auto_delivery("agent-1", True)

        assert reg.is_auto_delivery_paused("agent-1") is True

    def test_unpause_auto_delivery(self):
        """pause_auto_delivery with on=False clears the flag."""
        reg = _make_registry()
        reg.pause_auto_delivery("agent-1", True)
        reg.pause_auto_delivery("agent-1", False)

        assert reg.is_auto_delivery_paused("agent-1") is False

    def test_is_auto_delivery_paused_unknown_agent(self):
        """is_auto_delivery_paused for unknown agent returns False."""
        reg = _make_registry()
        assert reg.is_auto_delivery_paused("unknown") is False


# ── Test: Tool Decision for Unknown Agent ────────────────────────────────────


class TestToolDecisionUnknown:
    """Tests for tool_decision with unknown agents."""

    def test_unknown_agent_returns_deny_false(self):
        """tool_decision for an unknown agent returns deny=False."""
        reg = _make_registry()
        deny, reason = reg.tool_decision("unknown-agent", "any_tool")

        assert deny is False
        assert reason is None


# ── Test: Combined Scenarios ─────────────────────────────────────────────────


class TestCombinedScenarios:
    """Tests for combined control scenarios."""

    def test_pause_plus_gate(self):
        """Pause takes priority over gate in denial reason."""
        reg = _make_registry()
        reg.pause("agent-1", True)
        reg.gate_tool("agent-1", "tool_a", True)

        deny, reason = reg.tool_decision("agent-1", "tool_a")
        assert deny is True
        assert "Paused" in reason  # Pause reason takes priority

    def test_halt_plus_steer(self):
        """Halt and steer can coexist independently."""
        reg = _make_registry()
        reg.halt("agent-1")
        reg.steer("agent-1", "do this thing")

        assert reg.should_halt("agent-1") is True
        assert reg.take_steer("agent-1") == "do this thing"

    def test_multiple_agents_independent(self):
        """Control state for different agents is independent."""
        reg = _make_registry()
        reg.pause("agent-1", True)
        reg.gate_tool("agent-2", "tool_a", True)

        deny1, _ = reg.tool_decision("agent-1", "tool_a")
        deny2, _ = reg.tool_decision("agent-2", "tool_a")
        deny3, _ = reg.tool_decision("agent-2", "tool_b")

        assert deny1 is True  # agent-1 is paused
        assert deny2 is True  # agent-2 has tool_a gated
        assert deny3 is False  # agent-2 tool_b not gated

    def test_full_lifecycle(self):
        """Test a full lifecycle: pause -> steer -> halt -> resume."""
        reg = _make_registry()

        # Start clean
        snap = reg.snapshot("agent-1")
        assert snap.paused is False
        assert snap.halted is False

        # Pause
        reg.pause("agent-1", True)
        deny, _ = reg.tool_decision("agent-1", "any")
        assert deny is True

        # Steer while paused
        reg.steer("agent-1", "guidance")
        snap = reg.snapshot("agent-1")
        assert snap.pending_steers == 1

        # Halt
        reg.halt("agent-1")
        assert reg.should_halt("agent-1") is True

        # Resume clears pause + halt
        reg.resume("agent-1")
        deny, _ = reg.tool_decision("agent-1", "any")
        assert deny is False
        assert reg.should_halt("agent-1") is False

        # Steer still available after resume
        assert reg.take_steer("agent-1") == "guidance"


# ── Test: REST API Endpoints ─────────────────────────────────────────────────


class TestControlAPI:
    """Tests for the control REST API endpoints."""

    @pytest.fixture()
    def client(self):
        """Create a test client with the control router."""
        from nexus.api.routes.control import _registry, router

        app = FastAPI()
        app.include_router(router)

        # Reset registry state between tests
        _registry._map.clear()

        return TestClient(app)

    def test_pause_endpoint(self, client: TestClient):
        """POST /control/{agent_id}/pause sets pause state."""
        resp = client.post("/control/agent-1/pause", json={"on": True})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify via snapshot
        snap_resp = client.get("/control/agent-1/snapshot")
        assert snap_resp.json()["paused"] is True

    def test_gate_tool_endpoint(self, client: TestClient):
        """POST /control/{agent_id}/gate-tool gates a tool."""
        resp = client.post("/control/agent-1/gate-tool", json={"tool": "write_file", "on": True})
        assert resp.status_code == 200

        snap_resp = client.get("/control/agent-1/snapshot")
        assert "write_file" in snap_resp.json()["gated_tools"]

    def test_steer_endpoint(self, client: TestClient):
        """POST /control/{agent_id}/steer adds a steer note."""
        resp = client.post("/control/agent-1/steer", json={"text": "do X"})
        assert resp.status_code == 200

        snap_resp = client.get("/control/agent-1/snapshot")
        assert snap_resp.json()["pending_steers"] == 1

    def test_halt_endpoint(self, client: TestClient):
        """POST /control/{agent_id}/halt sets halt flag."""
        resp = client.post("/control/agent-1/halt")
        assert resp.status_code == 200

        snap_resp = client.get("/control/agent-1/snapshot")
        assert snap_resp.json()["halted"] is True

    def test_resume_endpoint(self, client: TestClient):
        """POST /control/{agent_id}/resume clears pause and halt."""
        client.post("/control/agent-1/pause", json={"on": True})
        client.post("/control/agent-1/halt")

        resp = client.post("/control/agent-1/resume")
        assert resp.status_code == 200

        snap_resp = client.get("/control/agent-1/snapshot")
        data = snap_resp.json()
        assert data["paused"] is False
        assert data["halted"] is False

    def test_snapshot_endpoint_unknown_agent(self, client: TestClient):
        """GET /control/{agent_id}/snapshot for unknown agent returns defaults."""
        resp = client.get("/control/unknown-agent/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["paused"] is False
        assert data["halted"] is False
        assert data["auto_delivery_paused"] is False
        assert data["gated_tools"] == []
        assert data["pending_steers"] == 0
