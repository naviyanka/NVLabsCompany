"""Tests for ControlRegistry restart survival (R-01 gap closure).

The registry must persist every operator control (pause, halt, gates, steers)
through restarts. The route module's singleton is wired to a JSON file under
the configured data dir; these tests exercise the same mechanism directly.
"""

from nexus.governance.control_registry import ControlRegistry


def test_state_survives_registry_recreation(tmp_path):
    persist = tmp_path / "control_registry.json"

    first = ControlRegistry(persist_path=persist)
    first.pause("agent-1", True)
    first.halt("agent-2")
    first.gate_tool("agent-1", "shell_exec", True)
    first.gate_tool("agent-1", "file_write", True)
    first.steer("agent-1", "focus on tests")
    first.steer("agent-1", "then docs")

    # Simulate a process restart: brand-new instance, same file.
    second = ControlRegistry(persist_path=persist)

    snap1 = second.snapshot("agent-1")
    assert snap1.paused is True
    assert snap1.gated_tools == ["file_write", "shell_exec"]
    assert snap1.pending_steers == 2

    snap2 = second.snapshot("agent-2")
    assert snap2.halted is True


def test_resume_clears_flags_but_keeps_gates_across_restart(tmp_path):
    persist = tmp_path / "control_registry.json"
    first = ControlRegistry(persist_path=persist)
    first.pause("a", True)
    first.halt("a")
    first.gate_tool("a", "deploy", True)
    first.resume("a")

    second = ControlRegistry(persist_path=persist)
    snap = second.snapshot("a")
    assert snap.paused is False
    assert snap.halted is False
    assert snap.gated_tools == ["deploy"]


def test_route_singleton_is_persistence_wired():
    from nexus.api.routes.control import _registry, _default_persist_path

    assert _registry._persist_path == _default_persist_path()
    assert _registry._persist_path is not None
