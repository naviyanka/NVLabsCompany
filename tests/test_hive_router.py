"""Tests for hive_router module - message routing from outbox to inbox."""

import json
import time
from pathlib import Path

from nexus.communication.hive_manager import HiveManager
from nexus.communication.hive_protocol import (
    HOP_CAP,
    AgentStatus,
    HiveAgentMeta,
    HiveMessage,
    MessageAct,
)
from nexus.communication.hive_router import HiveRouter


def _setup_hive(tmp_path: Path) -> tuple[HiveManager, HiveRouter]:
    """Create a HiveManager and HiveRouter pair."""
    manager = HiveManager(tmp_path / "hive")
    router = HiveRouter(manager)
    return manager, router


def _register_agents(manager: HiveManager, count: int = 3, god_id: str | None = None) -> None:
    """Register multiple test agents."""
    for i in range(1, count + 1):
        agent_id = f"agent-{i}"
        meta = HiveAgentMeta(
            id=agent_id,
            name=f"Agent {i}",
            role="worker",
            is_god=(agent_id == god_id),
        )
        manager.register_agent(meta)


def _make_message(
    from_agent: str = "agent-1",
    to_agent: str = "agent-2",
    msg_id: str = "msg-001",
    hops: int = 0,
) -> HiveMessage:
    """Create a test message."""
    return HiveMessage(
        id=msg_id,
        conversation="conv-1",
        from_agent=from_agent,
        to_agent=to_agent,
        act=MessageAct.INFORM,
        subject="test",
        body="hello",
        hops=hops,
    )


class TestHiveRouterDelivery:
    """Tests for basic message delivery."""

    def test_route_to_specific_agent(self, tmp_path: Path) -> None:
        """Message addressed to specific agent should be delivered to their inbox."""
        manager, router = _setup_hive(tmp_path)
        _register_agents(manager, 2)

        msg = _make_message(from_agent="agent-1", to_agent="agent-2")
        manager.send_message(msg)

        deliveries = router.route()
        assert len(deliveries) == 1
        assert deliveries[0][1] == ["agent-2"]

        # Verify message is in agent-2's inbox
        inbox = manager.get_inbox("agent-2")
        assert len(inbox) == 1
        assert inbox[0].id == "msg-001"

    def test_route_broadcast(self, tmp_path: Path) -> None:
        """Broadcast message should fan out to all active agents except sender."""
        manager, router = _setup_hive(tmp_path)
        _register_agents(manager, 3)

        msg = _make_message(from_agent="agent-1", to_agent="broadcast")
        manager.send_message(msg)

        deliveries = router.route()
        assert len(deliveries) == 1

        recipients = sorted(deliveries[0][1])
        assert recipients == ["agent-2", "agent-3"]

        # Verify messages in inboxes
        assert len(manager.get_inbox("agent-2")) == 1
        assert len(manager.get_inbox("agent-3")) == 1
        # Sender should NOT receive own broadcast
        assert len(manager.get_inbox("agent-1")) == 0

    def test_route_to_god(self, tmp_path: Path) -> None:
        """Message to 'god' should be delivered to the god agent."""
        manager, router = _setup_hive(tmp_path)
        _register_agents(manager, 3, god_id="agent-3")

        msg = _make_message(from_agent="agent-1", to_agent="god")
        manager.send_message(msg)

        deliveries = router.route()
        assert len(deliveries) == 1
        assert deliveries[0][1] == ["agent-3"]

        inbox = manager.get_inbox("agent-3")
        assert len(inbox) == 1

    def test_route_to_human(self, tmp_path: Path) -> None:
        """Message to 'human' should be delivered to god as proxy."""
        manager, router = _setup_hive(tmp_path)
        _register_agents(manager, 3, god_id="agent-3")

        msg = _make_message(from_agent="agent-1", to_agent="human")
        manager.send_message(msg)

        deliveries = router.route()
        assert len(deliveries) == 1
        assert deliveries[0][1] == ["agent-3"]

        inbox = manager.get_inbox("agent-3")
        assert len(inbox) == 1


class TestHiveRouterHopCap:
    """Tests for hop cap enforcement."""

    def test_hop_cap_prevents_delivery(self, tmp_path: Path) -> None:
        """Messages with hops >= HOP_CAP should NOT be delivered."""
        manager, router = _setup_hive(tmp_path)
        _register_agents(manager, 2)

        msg = _make_message(from_agent="agent-1", to_agent="agent-2", hops=HOP_CAP)
        manager.send_message(msg)

        deliveries = router.route()
        assert len(deliveries) == 0

        # Verify message NOT in agent-2's inbox
        inbox = manager.get_inbox("agent-2")
        assert len(inbox) == 0

        # Verify livelock warning logged
        logs = manager.get_log()
        assert len(logs) == 1
        assert logs[0]["event"] == "livelock_prevented"


class TestHiveRouterFileOps:
    """Tests for file operations during routing."""

    def test_route_moves_to_sent(self, tmp_path: Path) -> None:
        """Delivered messages should be moved from outbox/ to outbox/.sent/."""
        manager, router = _setup_hive(tmp_path)
        _register_agents(manager, 2)

        msg = _make_message(from_agent="agent-1", to_agent="agent-2")
        manager.send_message(msg)

        router.route()

        outbox = tmp_path / "hive" / "agents" / "agent-1" / "outbox"
        assert list(outbox.glob("*.json")) == []
        sent_dir = outbox / ".sent"
        sent_files = list(sent_dir.glob("*.json"))
        assert len(sent_files) == 1

    def test_route_logs_delivery(self, tmp_path: Path) -> None:
        """Routing should append delivery events to the log."""
        manager, router = _setup_hive(tmp_path)
        _register_agents(manager, 2)

        msg = _make_message(from_agent="agent-1", to_agent="agent-2")
        manager.send_message(msg)

        router.route()

        logs = manager.get_log()
        assert len(logs) == 1
        assert logs[0]["event"] == "message_delivered"
        assert logs[0]["message_id"] == "msg-001"
        assert logs[0]["recipients"] == ["agent-2"]

    def test_route_returns_delivery_tuples(self, tmp_path: Path) -> None:
        """route() should return correct (message, recipient_ids) tuples."""
        manager, router = _setup_hive(tmp_path)
        _register_agents(manager, 3)

        msg = _make_message(from_agent="agent-1", to_agent="broadcast")
        manager.send_message(msg)

        deliveries = router.route()
        assert len(deliveries) == 1
        delivered_msg, recipients = deliveries[0]
        assert delivered_msg.id == "msg-001"
        assert sorted(recipients) == ["agent-2", "agent-3"]


class TestHiveRouterArchived:
    """Tests for archived agent handling."""

    def test_route_skips_archived_agents_in_broadcast(self, tmp_path: Path) -> None:
        """Archived agents should be excluded from broadcast delivery."""
        manager, router = _setup_hive(tmp_path)
        _register_agents(manager, 3)

        # Archive agent-3
        manager.unregister_agent("agent-3")

        msg = _make_message(from_agent="agent-1", to_agent="broadcast")
        manager.send_message(msg)

        deliveries = router.route()
        assert len(deliveries) == 1
        assert deliveries[0][1] == ["agent-2"]

        # Verify agent-3 did not receive the message
        assert len(manager.get_inbox("agent-3")) == 0
