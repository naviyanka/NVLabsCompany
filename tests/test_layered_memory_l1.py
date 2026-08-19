"""Tests for L1 persistence in LayeredMemoryStore."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from nexus.memory.layered import LayeredMemoryConfig, LayeredMemoryStore


class TestL1Persistence:
    """Tests for L1 ring buffer persistence."""

    def test_l1_persists_on_add_session_summary(self, tmp_path: Path) -> None:
        """Test that adding a session summary persists L1 state."""
        persist_path = tmp_path / "memory.json"
        store = LayeredMemoryStore(persist_path=persist_path)

        task_id = uuid4()
        store.add_session_summary(task_id, "Test summary 1")

        # Check that the L1 file was created
        l1_path = tmp_path / "memory_l1.json"
        assert l1_path.exists()

        # Verify content
        data = json.loads(l1_path.read_text())
        assert "l1" in data
        assert len(data["l1"]) == 1
        assert data["l1"][0]["summary"] == "Test summary 1"
        assert data["l1"][0]["task_id"] == str(task_id)

    def test_l1_loads_on_init(self, tmp_path: Path) -> None:
        """Test that L1 state is restored when creating a new store."""
        persist_path = tmp_path / "memory.json"

        # Create store and add summaries
        store1 = LayeredMemoryStore(persist_path=persist_path)
        task_id = uuid4()
        store1.add_session_summary(task_id, "Summary A")
        store1.add_session_summary(task_id, "Summary B")

        # Create new store instance - should load persisted L1
        store2 = LayeredMemoryStore(persist_path=persist_path)
        summaries = store2.l1_summaries
        assert len(summaries) == 2
        assert summaries[0].summary == "Summary A"
        assert summaries[1].summary == "Summary B"

    def test_l1_ring_buffer_eviction_persists(self, tmp_path: Path) -> None:
        """Test that ring buffer eviction is reflected in persistence."""
        config = LayeredMemoryConfig(l1_ring_size=3)
        persist_path = tmp_path / "memory.json"
        store = LayeredMemoryStore(config=config, persist_path=persist_path)

        task_id = uuid4()
        for i in range(5):
            store.add_session_summary(task_id, f"Summary {i}")

        # Only last 3 should remain
        assert len(store.l1_summaries) == 3
        assert store.l1_summaries[0].summary == "Summary 2"
        assert store.l1_summaries[2].summary == "Summary 4"

        # Verify persistence matches
        store2 = LayeredMemoryStore(config=config, persist_path=persist_path)
        assert len(store2.l1_summaries) == 3
        assert store2.l1_summaries[0].summary == "Summary 2"

    def test_l1_no_persistence_without_persist_path(self) -> None:
        """Test that no file is created when persist_path is None."""
        store = LayeredMemoryStore()
        task_id = uuid4()
        store.add_session_summary(task_id, "Ephemeral summary")
        assert len(store.l1_summaries) == 1

    def test_l1_persist_path_derived_from_main_path(
        self, tmp_path: Path
    ) -> None:
        """Test that L1 path is derived from main persist path."""
        persist_path = tmp_path / "subdir" / "state.json"
        store = LayeredMemoryStore(persist_path=persist_path)

        task_id = uuid4()
        store.add_session_summary(task_id, "Test")

        expected_l1_path = tmp_path / "subdir" / "state_l1.json"
        assert expected_l1_path.exists()

    def test_l1_atomic_write_safety(self, tmp_path: Path) -> None:
        """Test that L1 uses atomic write (no partial writes)."""
        persist_path = tmp_path / "memory.json"
        store = LayeredMemoryStore(persist_path=persist_path)

        task_id = uuid4()
        store.add_session_summary(task_id, "First")
        store.add_session_summary(task_id, "Second")

        # Verify file is valid JSON (atomic write completed fully)
        l1_path = tmp_path / "memory_l1.json"
        data = json.loads(l1_path.read_text())
        assert len(data["l1"]) == 2

    def test_l1_preserves_l2_l3_persistence(self, tmp_path: Path) -> None:
        """Test that L1 persistence does not interfere with L2/L3."""
        persist_path = tmp_path / "memory.json"
        store = LayeredMemoryStore(persist_path=persist_path)

        # Add L2 data
        agent_id = uuid4()
        store.store_fact(agent_id, "A fact about something")

        # Add L1 data
        task_id = uuid4()
        store.add_session_summary(task_id, "Summary")

        # Verify both persisted independently
        assert persist_path.exists()  # L2/L3 file
        l1_path = tmp_path / "memory_l1.json"
        assert l1_path.exists()  # L1 file

        # Reload and verify both layers
        store2 = LayeredMemoryStore(persist_path=persist_path)
        assert len(store2.l1_summaries) == 1
        assert len(store2.get_agent_facts(agent_id)) == 1

    def test_l1_empty_on_fresh_init(self, tmp_path: Path) -> None:
        """Test that L1 is empty on fresh initialization."""
        persist_path = tmp_path / "memory.json"
        store = LayeredMemoryStore(persist_path=persist_path)
        assert store.l1_summaries == []

    def test_l1_multiple_task_ids(self, tmp_path: Path) -> None:
        """Test L1 persistence with different task IDs."""
        persist_path = tmp_path / "memory.json"
        store = LayeredMemoryStore(persist_path=persist_path)

        task_a = uuid4()
        task_b = uuid4()
        store.add_session_summary(task_a, "Task A summary")
        store.add_session_summary(task_b, "Task B summary")

        store2 = LayeredMemoryStore(persist_path=persist_path)
        summaries = store2.l1_summaries
        assert len(summaries) == 2
        assert summaries[0].task_id == task_a
        assert summaries[1].task_id == task_b
