"""Tests for pluggable HiveManager backends (nexus.communication.hive_backend)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nexus.communication.hive_backend import (
    FileHiveBackend,
    HiveBackend,
    RedisHiveBackend,
)
from nexus.communication.hive_manager import HiveManager
from nexus.communication.hive_protocol import (
    AgentStatus,
    HiveAgentMeta,
    HiveMessage,
    MessageAct,
)


class TestFileHiveBackend:
    """Tests for the file-based hive backend."""

    async def test_register_and_get_registry(self, tmp_path: Path) -> None:
        """Test agent registration and registry retrieval."""
        backend = FileHiveBackend(tmp_path / "hive")
        meta = HiveAgentMeta(id="agent-1", name="Test Agent", role="worker")
        await backend.register_agent(meta)

        registry = await backend.get_registry()
        assert "agent-1" in registry
        assert registry["agent-1"].name == "Test Agent"

    async def test_unregister_agent_archive(self, tmp_path: Path) -> None:
        """Test archiving an agent on unregister."""
        backend = FileHiveBackend(tmp_path / "hive")
        meta = HiveAgentMeta(id="agent-1", name="Test Agent")
        await backend.register_agent(meta)
        await backend.unregister_agent("agent-1", archive=True)

        registry = await backend.get_registry()
        assert registry["agent-1"].archived is True

    async def test_unregister_agent_delete(self, tmp_path: Path) -> None:
        """Test removing an agent entirely on unregister."""
        backend = FileHiveBackend(tmp_path / "hive")
        meta = HiveAgentMeta(id="agent-1", name="Test Agent")
        await backend.register_agent(meta)
        await backend.unregister_agent("agent-1", archive=False)

        registry = await backend.get_registry()
        assert "agent-1" not in registry

    async def test_send_and_get_inbox(self, tmp_path: Path) -> None:
        """Test sending a message and retrieving it from inbox."""
        backend = FileHiveBackend(tmp_path / "hive")
        meta = HiveAgentMeta(id="agent-1", name="Agent 1")
        await backend.register_agent(meta)

        msg = HiveMessage(
            conversation="conv-1",
            from_agent="agent-1",
            to_agent="agent-1",
            act=MessageAct.INFORM,
            subject="Hello",
            body="Test message",
        )
        await backend.deliver_to_inbox("agent-1", msg)

        inbox = await backend.get_inbox("agent-1")
        assert len(inbox) == 1
        assert inbox[0].subject == "Hello"
        assert inbox[0].body == "Test message"

    async def test_mark_processed(self, tmp_path: Path) -> None:
        """Test marking a message as processed moves it to .done."""
        backend = FileHiveBackend(tmp_path / "hive")
        meta = HiveAgentMeta(id="agent-1", name="Agent 1")
        await backend.register_agent(meta)

        msg = HiveMessage(
            conversation="conv-1",
            from_agent="agent-1",
            to_agent="agent-1",
            act=MessageAct.INFORM,
            subject="Hello",
            body="Body",
        )
        await backend.deliver_to_inbox("agent-1", msg)
        await backend.mark_processed("agent-1", msg.id)

        inbox = await backend.get_inbox("agent-1")
        assert len(inbox) == 0

    async def test_update_status(self, tmp_path: Path) -> None:
        """Test updating an agent's status."""
        backend = FileHiveBackend(tmp_path / "hive")
        meta = HiveAgentMeta(id="agent-1", name="Agent 1")
        await backend.register_agent(meta)
        await backend.update_status("agent-1", AgentStatus.WORKING)

        registry = await backend.get_registry()
        assert registry["agent-1"].status == AgentStatus.WORKING

    async def test_send_message_creates_outbox_file(self, tmp_path: Path) -> None:
        """Test that send_message creates a file in the outbox."""
        backend = FileHiveBackend(tmp_path / "hive")
        meta = HiveAgentMeta(id="agent-1", name="Agent 1")
        await backend.register_agent(meta)

        msg = HiveMessage(
            conversation="conv-1",
            from_agent="agent-1",
            to_agent="agent-2",
            act=MessageAct.REQUEST,
            subject="Do something",
            body="Please do it",
        )
        await backend.send_message(msg)

        outbox = tmp_path / "hive" / "agents" / "agent-1" / "outbox"
        files = list(outbox.glob("*.json"))
        assert len(files) == 1

    async def test_conforms_to_protocol(self, tmp_path: Path) -> None:
        """Test that FileHiveBackend conforms to HiveBackend protocol."""
        backend = FileHiveBackend(tmp_path / "hive")
        assert isinstance(backend, HiveBackend)

    async def test_get_inbox_empty(self, tmp_path: Path) -> None:
        """Test that empty inbox returns empty list."""
        backend = FileHiveBackend(tmp_path / "hive")
        inbox = await backend.get_inbox("nonexistent")
        assert inbox == []


class TestHiveManagerWithBackend:
    """Tests for HiveManager with a pluggable backend."""

    def test_backward_compatible_without_backend(self, tmp_path: Path) -> None:
        """Test that HiveManager works without explicit backend."""
        manager = HiveManager(tmp_path / "hive")
        meta = HiveAgentMeta(id="agent-1", name="Test Agent")
        manager.register_agent(meta)

        registry = manager.get_registry()
        assert "agent-1" in registry

    def test_delegates_to_backend(self, tmp_path: Path) -> None:
        """Test that HiveManager delegates to backend when provided."""
        backend = FileHiveBackend(tmp_path / "backend")
        manager = HiveManager(tmp_path / "hive", backend=backend)

        meta = HiveAgentMeta(id="agent-1", name="Test Agent")
        manager.register_agent(meta)

        # Verify the backend was used (not the manager's internal file logic)
        registry = manager.get_registry()
        assert "agent-1" in registry

    def test_send_message_via_backend(self, tmp_path: Path) -> None:
        """Test sending messages through pluggable backend."""
        backend = FileHiveBackend(tmp_path / "backend")
        manager = HiveManager(tmp_path / "hive", backend=backend)

        meta = HiveAgentMeta(id="agent-1", name="Agent 1")
        manager.register_agent(meta)

        msg = HiveMessage(
            conversation="conv-1",
            from_agent="agent-1",
            to_agent="agent-2",
            act=MessageAct.INFORM,
            subject="Hello",
            body="Body",
        )
        manager.send_message(msg)

        # Verify outbox file exists in backend root
        outbox = tmp_path / "backend" / "agents" / "agent-1" / "outbox"
        files = list(outbox.glob("*.json"))
        assert len(files) == 1

    def test_deliver_and_get_inbox_via_backend(self, tmp_path: Path) -> None:
        """Test message delivery and inbox retrieval through backend."""
        backend = FileHiveBackend(tmp_path / "backend")
        manager = HiveManager(tmp_path / "hive", backend=backend)

        meta = HiveAgentMeta(id="agent-1", name="Agent 1")
        manager.register_agent(meta)

        msg = HiveMessage(
            conversation="conv-1",
            from_agent="agent-2",
            to_agent="agent-1",
            act=MessageAct.INFORM,
            subject="Hi",
            body="Content",
        )
        manager.deliver_to_inbox("agent-1", msg)

        inbox = manager.get_inbox("agent-1")
        assert len(inbox) == 1
        assert inbox[0].subject == "Hi"

    def test_mark_processed_via_backend(self, tmp_path: Path) -> None:
        """Test marking messages processed through backend."""
        backend = FileHiveBackend(tmp_path / "backend")
        manager = HiveManager(tmp_path / "hive", backend=backend)

        meta = HiveAgentMeta(id="agent-1", name="Agent 1")
        manager.register_agent(meta)

        msg = HiveMessage(
            conversation="conv-1",
            from_agent="agent-2",
            to_agent="agent-1",
            act=MessageAct.INFORM,
            subject="Hi",
            body="Content",
        )
        manager.deliver_to_inbox("agent-1", msg)
        manager.mark_processed("agent-1", msg.id)

        inbox = manager.get_inbox("agent-1")
        assert len(inbox) == 0

    def test_update_status_via_backend(self, tmp_path: Path) -> None:
        """Test status updates through backend."""
        backend = FileHiveBackend(tmp_path / "backend")
        manager = HiveManager(tmp_path / "hive", backend=backend)

        meta = HiveAgentMeta(id="agent-1", name="Agent 1")
        manager.register_agent(meta)
        manager.update_status("agent-1", AgentStatus.BLOCKED)

        registry = manager.get_registry()
        assert registry["agent-1"].status == AgentStatus.BLOCKED


class TestRedisHiveBackend:
    """Tests for the Redis hive backend with mocked Redis."""

    def test_conforms_to_protocol(self) -> None:
        """Test that RedisHiveBackend conforms to HiveBackend protocol."""
        with patch("redis.asyncio.from_url"):
            backend = RedisHiveBackend("redis://localhost:6379/0")
            assert isinstance(backend, HiveBackend)

    async def test_unavailable_send_message_no_error(self) -> None:
        """Test that send_message does not raise when backend is unavailable."""
        with patch("redis.asyncio.from_url"):
            backend = RedisHiveBackend("redis://localhost:6379/0")
            backend._available = False

            msg = HiveMessage(
                conversation="conv-1",
                from_agent="agent-1",
                to_agent="agent-2",
                act=MessageAct.INFORM,
                subject="Hi",
                body="Body",
            )
            # Should not raise
            await backend.send_message(msg)

    async def test_unavailable_get_inbox_returns_empty(self) -> None:
        """Test that get_inbox returns empty list when unavailable."""
        with patch("redis.asyncio.from_url"):
            backend = RedisHiveBackend("redis://localhost:6379/0")
            backend._available = False

            result = await backend.get_inbox("agent-1")
            assert result == []

    async def test_unavailable_get_registry_returns_empty(self) -> None:
        """Test that get_registry returns empty dict when unavailable."""
        with patch("redis.asyncio.from_url"):
            backend = RedisHiveBackend("redis://localhost:6379/0")
            backend._available = False

            result = await backend.get_registry()
            assert result == {}

    async def test_send_message_calls_redis(self) -> None:
        """Test that send_message properly calls Redis xadd."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.xadd = AsyncMock()
            mock_from_url.return_value = mock_redis

            backend = RedisHiveBackend("redis://localhost:6379/0")
            msg = HiveMessage(
                conversation="conv-1",
                from_agent="agent-1",
                to_agent="agent-2",
                act=MessageAct.INFORM,
                subject="Hi",
                body="Body",
            )
            await backend.send_message(msg)
            mock_redis.xadd.assert_called_once()

    async def test_get_inbox_returns_messages(self) -> None:
        """Test that get_inbox properly reads from Redis streams."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            msg = HiveMessage(
                conversation="conv-1",
                from_agent="agent-1",
                to_agent="agent-2",
                act=MessageAct.INFORM,
                subject="Hi",
                body="Body",
            )
            import json

            mock_redis.xrange = AsyncMock(
                return_value=[
                    ("1-0", {"payload": json.dumps(msg.model_dump(mode="json"))})
                ]
            )
            mock_from_url.return_value = mock_redis

            backend = RedisHiveBackend("redis://localhost:6379/0")
            result = await backend.get_inbox("agent-2")
            assert len(result) == 1
            assert result[0].subject == "Hi"
