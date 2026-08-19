"""Tests for hive_manager module - file-based agent coordination."""

import json
import time
from pathlib import Path

from nexus.communication.hive_manager import HiveManager
from nexus.communication.hive_protocol import (
    AgentStatus,
    HiveAgentMeta,
    HiveMessage,
    MessageAct,
)


def _make_agent(agent_id: str = "agent-1", name: str = "TestAgent") -> HiveAgentMeta:
    """Create a test agent meta."""
    return HiveAgentMeta(id=agent_id, name=name, role="worker")


def _make_message(
    from_agent: str = "agent-1",
    to_agent: str = "agent-2",
    msg_id: str = "msg-001",
) -> HiveMessage:
    """Create a test message."""
    return HiveMessage(
        id=msg_id,
        conversation="conv-1",
        from_agent=from_agent,
        to_agent=to_agent,
        act=MessageAct.INFORM,
        subject="test",
        body="hello world",
    )


class TestHiveManagerStructure:
    """Tests for directory structure creation."""

    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        """HiveManager should create registry.json, board.md, log.jsonl, agents/."""
        manager = HiveManager(tmp_path / "hive")
        root = tmp_path / "hive"

        assert root.exists()
        assert (root / "registry.json").exists()
        assert (root / "board.md").exists()
        assert (root / "log.jsonl").exists()
        assert (root / "agents").exists()

        # Verify registry.json content
        registry = json.loads((root / "registry.json").read_text())
        assert registry == {"agents": {}}

        # Verify board.md content
        assert (root / "board.md").read_text() == "# Shared Blackboard\n"


class TestHiveManagerAgents:
    """Tests for agent registration and management."""

    def test_register_agent(self, tmp_path: Path) -> None:
        """register_agent should create workspace dirs and files."""
        manager = HiveManager(tmp_path / "hive")
        meta = _make_agent()
        manager.register_agent(meta)

        agent_dir = tmp_path / "hive" / "agents" / "agent-1"
        assert agent_dir.exists()
        assert (agent_dir / "identity.md").exists()
        assert (agent_dir / "memory.md").exists()
        assert (agent_dir / "inbox").exists()
        assert (agent_dir / "inbox" / ".done").exists()
        assert (agent_dir / "outbox").exists()
        assert (agent_dir / "outbox" / ".sent").exists()
        assert (agent_dir / "cursor.json").exists()

    def test_get_registry(self, tmp_path: Path) -> None:
        """get_registry should return registered agents by id."""
        manager = HiveManager(tmp_path / "hive")
        meta1 = _make_agent("agent-1", "Agent One")
        meta2 = _make_agent("agent-2", "Agent Two")
        manager.register_agent(meta1)
        manager.register_agent(meta2)

        registry = manager.get_registry()
        assert "agent-1" in registry
        assert "agent-2" in registry
        assert registry["agent-1"].name == "Agent One"
        assert registry["agent-2"].name == "Agent Two"

    def test_get_agent(self, tmp_path: Path) -> None:
        """get_agent should return a single agent or None."""
        manager = HiveManager(tmp_path / "hive")
        meta = _make_agent()
        manager.register_agent(meta)

        agent = manager.get_agent("agent-1")
        assert agent is not None
        assert agent.name == "TestAgent"

        assert manager.get_agent("nonexistent") is None

    def test_unregister_agent(self, tmp_path: Path) -> None:
        """unregister_agent should mark agent as archived."""
        manager = HiveManager(tmp_path / "hive")
        meta = _make_agent()
        manager.register_agent(meta)

        manager.unregister_agent("agent-1")
        agent = manager.get_agent("agent-1")
        assert agent is not None
        assert agent.archived is True

    def test_update_status(self, tmp_path: Path) -> None:
        """update_status should change the agent's status."""
        manager = HiveManager(tmp_path / "hive")
        meta = _make_agent()
        manager.register_agent(meta)

        manager.update_status("agent-1", AgentStatus.WORKING)
        agent = manager.get_agent("agent-1")
        assert agent is not None
        assert agent.status == AgentStatus.WORKING


class TestHiveManagerMessages:
    """Tests for message sending and inbox management."""

    def test_send_message(self, tmp_path: Path) -> None:
        """send_message should write JSON to the sender's outbox."""
        manager = HiveManager(tmp_path / "hive")
        meta = _make_agent()
        manager.register_agent(meta)

        msg = _make_message()
        manager.send_message(msg)

        outbox = tmp_path / "hive" / "agents" / "agent-1" / "outbox"
        files = list(outbox.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["id"] == "msg-001"
        assert data["subject"] == "test"

    def test_get_inbox(self, tmp_path: Path) -> None:
        """get_inbox should read messages from an agent's inbox."""
        manager = HiveManager(tmp_path / "hive")
        meta = _make_agent("agent-2", "Receiver")
        manager.register_agent(meta)

        # Manually place a message in inbox
        msg = _make_message()
        manager.deliver_to_inbox("agent-2", msg)

        inbox_msgs = manager.get_inbox("agent-2")
        assert len(inbox_msgs) == 1
        assert inbox_msgs[0].id == "msg-001"

    def test_mark_processed(self, tmp_path: Path) -> None:
        """mark_processed should move message from inbox/ to inbox/.done/."""
        manager = HiveManager(tmp_path / "hive")
        meta = _make_agent("agent-2", "Receiver")
        manager.register_agent(meta)

        msg = _make_message()
        manager.deliver_to_inbox("agent-2", msg)

        manager.mark_processed("agent-2", "msg-001")

        inbox = tmp_path / "hive" / "agents" / "agent-2" / "inbox"
        assert list(inbox.glob("*.json")) == []
        done_dir = inbox / ".done"
        done_files = list(done_dir.glob("*.json"))
        assert len(done_files) == 1


class TestHiveManagerBlackboard:
    """Tests for blackboard read/write."""

    def test_blackboard_read_write(self, tmp_path: Path) -> None:
        """Read and update the shared blackboard."""
        manager = HiveManager(tmp_path / "hive")

        # Default content
        assert manager.get_blackboard() == "# Shared Blackboard\n"

        # Update
        manager.update_blackboard("# Updated\n\nNew content here.\n")
        assert manager.get_blackboard() == "# Updated\n\nNew content here.\n"


class TestHiveManagerLog:
    """Tests for append-only event log."""

    def test_log_append_and_read(self, tmp_path: Path) -> None:
        """Append events and read them back with limit."""
        manager = HiveManager(tmp_path / "hive")

        manager.append_log({"event": "test", "seq": 1})
        manager.append_log({"event": "test", "seq": 2})
        manager.append_log({"event": "test", "seq": 3})

        # Read all
        logs = manager.get_log()
        assert len(logs) == 3
        assert logs[0]["seq"] == 1
        assert logs[2]["seq"] == 3

        # Read with limit
        logs = manager.get_log(limit=2)
        assert len(logs) == 2
        assert logs[0]["seq"] == 2
        assert logs[1]["seq"] == 3
