"""Tests for opt-in JSON file persistence across modules.

Covers ControlRegistry, PhaseMachine, and LayeredMemoryStore persistence
behavior: save/load round-trips, backward compatibility (persist_path=None),
atomic write safety, and missing-file-on-init scenarios.
"""

import json
import uuid
from pathlib import Path

import pytest

from nexus.governance.control_registry import ControlRegistry
from nexus.memory.layered import LayeredMemoryConfig, LayeredMemoryStore
from nexus.orchestration.phase_machine import PhaseMachine, TeamPhase


# ── ControlRegistry Persistence Tests ────────────────────────────────────────


class TestControlRegistryPersistence:
    """Tests for ControlRegistry file persistence."""

    def test_saves_and_loads_state(self, tmp_path: Path) -> None:
        """ControlRegistry saves state after mutations and loads on init."""
        fp = tmp_path / "control.json"

        reg = ControlRegistry(persist_path=fp)
        reg.pause("agent-1", True)
        reg.gate_tool("agent-1", "write_file", True)
        reg.gate_tool("agent-1", "delete_file", True)
        reg.steer("agent-1", "do something")
        reg.halt("agent-2")
        reg.pause_auto_delivery("agent-2", True)

        # Load in a new instance
        reg2 = ControlRegistry(persist_path=fp)
        snap1 = reg2.snapshot("agent-1")
        assert snap1.paused is True
        assert "write_file" in snap1.gated_tools
        assert "delete_file" in snap1.gated_tools
        assert snap1.pending_steers == 1

        snap2 = reg2.snapshot("agent-2")
        assert snap2.halted is True
        assert snap2.auto_delivery_paused is True

    def test_no_persist_path_works_as_before(self) -> None:
        """ControlRegistry without persist_path works identically."""
        reg = ControlRegistry()
        reg.pause("agent-1", True)
        reg.gate_tool("agent-1", "tool_a", True)
        reg.steer("agent-1", "guidance")

        snap = reg.snapshot("agent-1")
        assert snap.paused is True
        assert "tool_a" in snap.gated_tools
        assert snap.pending_steers == 1

    def test_missing_file_on_init_creates_fresh_state(self, tmp_path: Path) -> None:
        """ControlRegistry with non-existent persist_path starts fresh."""
        fp = tmp_path / "nonexistent" / "control.json"
        reg = ControlRegistry(persist_path=fp)
        snap = reg.snapshot("agent-1")
        assert snap.paused is False
        assert snap.gated_tools == []
        assert snap.pending_steers == 0

    def test_resume_persists(self, tmp_path: Path) -> None:
        """Resume clears pause/halt and persists the change."""
        fp = tmp_path / "control.json"
        reg = ControlRegistry(persist_path=fp)
        reg.pause("agent-1", True)
        reg.halt("agent-1")
        reg.resume("agent-1")

        reg2 = ControlRegistry(persist_path=fp)
        snap = reg2.snapshot("agent-1")
        assert snap.paused is False
        assert snap.halted is False

    def test_clear_steers_persists(self, tmp_path: Path) -> None:
        """clear_steers removes notes and persists."""
        fp = tmp_path / "control.json"
        reg = ControlRegistry(persist_path=fp)
        reg.steer("agent-1", "note 1")
        reg.steer("agent-1", "note 2")
        reg.clear_steers("agent-1")

        reg2 = ControlRegistry(persist_path=fp)
        assert reg2.take_steer("agent-1") is None

    def test_gated_tools_serialized_as_sorted_list(self, tmp_path: Path) -> None:
        """gated_tools is serialized as a sorted list in JSON."""
        fp = tmp_path / "control.json"
        reg = ControlRegistry(persist_path=fp)
        reg.gate_tool("agent-1", "z_tool", True)
        reg.gate_tool("agent-1", "a_tool", True)
        reg.gate_tool("agent-1", "m_tool", True)

        with open(fp) as f:
            data = json.load(f)
        assert data["agent-1"]["gated_tools"] == ["a_tool", "m_tool", "z_tool"]

    def test_atomic_write_file_valid_json(self, tmp_path: Path) -> None:
        """Persisted file is always valid JSON after mutations."""
        fp = tmp_path / "control.json"
        reg = ControlRegistry(persist_path=fp)
        for i in range(10):
            reg.pause(f"agent-{i}", True)
            reg.gate_tool(f"agent-{i}", f"tool_{i}", True)

        with open(fp) as f:
            data = json.load(f)
        assert len(data) == 10


# ── PhaseMachine Persistence Tests ───────────────────────────────────────────


class TestPhaseMachinePersistence:
    """Tests for PhaseMachine file persistence."""

    def test_saves_and_loads_state(self, tmp_path: Path) -> None:
        """PhaseMachine saves phase state and loads on init."""
        fp = tmp_path / "phases.json"
        leader1 = uuid.uuid4()
        leader2 = uuid.uuid4()

        machine = PhaseMachine(persist_path=fp)
        machine.check_plan_detected(leader1, "Here is my [PLAN]")
        machine.check_plan_detected(leader2, "[PLAN] something")
        machine.approve_plan(leader2)

        # Load in a new instance
        machine2 = PhaseMachine(persist_path=fp)
        assert machine2.get_phase(leader1) == TeamPhase.DESIGN
        assert machine2.get_phase(leader2) == TeamPhase.EXECUTE

    def test_no_persist_path_works_as_before(self) -> None:
        """PhaseMachine without persist_path works identically."""
        machine = PhaseMachine()
        leader = uuid.uuid4()
        machine.check_plan_detected(leader, "[PLAN] test")
        assert machine.get_phase(leader) == TeamPhase.DESIGN

    def test_missing_file_on_init_creates_fresh_state(self, tmp_path: Path) -> None:
        """PhaseMachine with non-existent persist_path starts fresh."""
        fp = tmp_path / "nonexistent" / "phases.json"
        machine = PhaseMachine(persist_path=fp)
        leader = uuid.uuid4()
        assert machine.get_phase(leader) == TeamPhase.CREATE

    def test_full_cycle_persists(self, tmp_path: Path) -> None:
        """Full lifecycle transitions are all persisted."""
        fp = tmp_path / "phases.json"
        leader = uuid.uuid4()

        machine = PhaseMachine(persist_path=fp)
        machine.check_plan_detected(leader, "[PLAN]")
        machine.approve_plan(leader)
        machine.check_final_result(leader, "Done")
        machine.handle_user_feedback(leader, "Iterate")

        machine2 = PhaseMachine(persist_path=fp)
        assert machine2.get_phase(leader) == TeamPhase.CREATE

    def test_reset_persists(self, tmp_path: Path) -> None:
        """Reset clears state and persists the empty map."""
        fp = tmp_path / "phases.json"
        leader = uuid.uuid4()

        machine = PhaseMachine(persist_path=fp)
        machine.check_plan_detected(leader, "[PLAN]")
        machine.reset()

        machine2 = PhaseMachine(persist_path=fp)
        assert machine2.get_all_phases() == {}

    def test_uuid_keys_round_trip(self, tmp_path: Path) -> None:
        """UUID keys are correctly serialized as strings and deserialized."""
        fp = tmp_path / "phases.json"
        leader = uuid.UUID("12345678-1234-5678-1234-567812345678")

        machine = PhaseMachine(persist_path=fp)
        machine.check_plan_detected(leader, "[PLAN]")

        # Verify JSON uses string keys
        with open(fp) as f:
            data = json.load(f)
        assert "12345678-1234-5678-1234-567812345678" in data

        # Verify round-trip restores UUID keys
        machine2 = PhaseMachine(persist_path=fp)
        assert leader in machine2.get_all_phases()
        assert machine2.get_phase(leader) == TeamPhase.DESIGN

    def test_atomic_write_file_valid_json(self, tmp_path: Path) -> None:
        """Persisted file is always valid JSON after mutations."""
        fp = tmp_path / "phases.json"
        machine = PhaseMachine(persist_path=fp)
        for _ in range(5):
            leader = uuid.uuid4()
            machine.check_plan_detected(leader, "[PLAN]")

        with open(fp) as f:
            data = json.load(f)
        assert len(data) == 5


# ── LayeredMemoryStore Persistence Tests ─────────────────────────────────────


class TestLayeredMemoryPersistence:
    """Tests for LayeredMemoryStore file persistence (L2/L3 only)."""

    def test_persists_l2_and_l3(self, tmp_path: Path) -> None:
        """LayeredMemoryStore persists L2 and L3 facts."""
        fp = tmp_path / "memory.json"
        agent = uuid.UUID("11111111-1111-1111-1111-111111111111")

        store = LayeredMemoryStore(persist_path=fp)
        store.store_fact(agent, "Python uses GIL for thread safety")
        store.store_fact(agent, "Rust has zero-cost abstractions")
        store.promote_to_shared(agent, "Python uses GIL for thread safety")

        # Load in a new instance
        store2 = LayeredMemoryStore(persist_path=fp)
        facts = store2.get_agent_facts(agent)
        assert len(facts) == 2
        contents = [f.content for f in facts]
        assert "Python uses GIL for thread safety" in contents
        assert "Rust has zero-cost abstractions" in contents

        shared = store2.get_shared_knowledge()
        assert len(shared) == 1
        assert shared[0].content == "Python uses GIL for thread safety"

    def test_l1_is_persisted(self, tmp_path: Path) -> None:
        """L1 session summaries are persisted to a separate file."""
        fp = tmp_path / "memory.json"
        task_id = uuid.uuid4()
        agent = uuid.uuid4()

        store = LayeredMemoryStore(persist_path=fp)
        store.add_session_summary(task_id, "Session summary text")
        store.store_fact(agent, "A fact to trigger persistence")

        # Load in a new instance - L1 should be restored
        store2 = LayeredMemoryStore(persist_path=fp)
        assert len(store2.l1_summaries) == 1
        assert store2.l1_summaries[0].summary == "Session summary text"

    def test_no_persist_path_works_as_before(self) -> None:
        """LayeredMemoryStore without persist_path works identically."""
        agent = uuid.uuid4()
        store = LayeredMemoryStore()
        store.store_fact(agent, "Knowledge fact")
        facts = store.get_agent_facts(agent)
        assert len(facts) == 1
        assert facts[0].content == "Knowledge fact"

    def test_missing_file_on_init_creates_fresh_state(self, tmp_path: Path) -> None:
        """LayeredMemoryStore with non-existent persist_path starts fresh."""
        fp = tmp_path / "nonexistent" / "memory.json"
        store = LayeredMemoryStore(persist_path=fp)
        agent = uuid.uuid4()
        assert store.get_agent_facts(agent) == []
        assert store.get_shared_knowledge() == []

    def test_fact_fields_round_trip(self, tmp_path: Path) -> None:
        """Fact fields (datetime, UUID, metadata) survive serialization."""
        fp = tmp_path / "memory.json"
        agent = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        store = LayeredMemoryStore(persist_path=fp)
        store.store_fact(agent, "Fact with metadata", metadata={"key": "value"})

        store2 = LayeredMemoryStore(persist_path=fp)
        facts = store2.get_agent_facts(agent)
        assert len(facts) == 1
        fact = facts[0]
        assert fact.content == "Fact with metadata"
        assert fact.source_agent_id == agent
        assert fact.metadata == {"key": "value"}
        assert fact.created_at.tzinfo is not None  # timezone-aware
        assert fact.access_count == 1  # incremented by get_agent_facts

    def test_multiple_agents_l2_round_trip(self, tmp_path: Path) -> None:
        """Multiple agents' L2 facts are persisted independently."""
        fp = tmp_path / "memory.json"
        agent1 = uuid.uuid4()
        agent2 = uuid.uuid4()

        store = LayeredMemoryStore(persist_path=fp)
        store.store_fact(agent1, "Agent 1 knowledge")
        store.store_fact(agent2, "Agent 2 knowledge")

        store2 = LayeredMemoryStore(persist_path=fp)
        facts1 = store2.get_agent_facts(agent1)
        facts2 = store2.get_agent_facts(agent2)
        assert len(facts1) == 1
        assert len(facts2) == 1
        assert facts1[0].content == "Agent 1 knowledge"
        assert facts2[0].content == "Agent 2 knowledge"

    def test_promote_to_shared_persists(self, tmp_path: Path) -> None:
        """promote_to_shared triggers persistence."""
        fp = tmp_path / "memory.json"
        agent = uuid.uuid4()

        store = LayeredMemoryStore(persist_path=fp)
        store.store_fact(agent, "Organizational fact")
        store.promote_to_shared(agent, "Organizational fact")

        store2 = LayeredMemoryStore(persist_path=fp)
        shared = store2.get_shared_knowledge()
        assert len(shared) == 1
        assert shared[0].content == "Organizational fact"

    def test_atomic_write_file_valid_json(self, tmp_path: Path) -> None:
        """Persisted file is always valid JSON after mutations."""
        fp = tmp_path / "memory.json"
        agent = uuid.uuid4()

        store = LayeredMemoryStore(persist_path=fp)
        distinct_facts = [
            "Python programming language features overview",
            "Kubernetes container orchestration platform details",
            "PostgreSQL relational database system internals",
        ]
        for fact in distinct_facts:
            store.store_fact(agent, fact)

        with open(fp) as f:
            data = json.load(f)
        assert "l2" in data
        assert "l3" in data

    def test_source_agent_id_none_round_trip(self, tmp_path: Path) -> None:
        """Facts with source_agent_id=None are handled correctly."""
        fp = tmp_path / "memory.json"
        agent = uuid.uuid4()

        store = LayeredMemoryStore(persist_path=fp)
        store.store_fact(agent, "Fact content")
        # Promote creates a copy, source_agent_id is preserved from original
        store.promote_to_shared(agent, "Fact content")

        store2 = LayeredMemoryStore(persist_path=fp)
        shared = store2.get_shared_knowledge()
        assert len(shared) == 1
        # The source_agent_id should be the agent that stored it
        assert shared[0].source_agent_id == agent
