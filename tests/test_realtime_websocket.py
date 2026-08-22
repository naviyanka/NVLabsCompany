"""Tests for the real-time WebSocket subsystem.

Validates WebSocketManager, RealtimeEvent, ChannelRegistry, EventStream,
and RealtimeEventBus using in-memory operation mode with AsyncMock for
WebSocket simulation.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.realtime import (
    AGENT_MESSAGE,
    AGENT_STATUS_CHANGED,
    SYSTEM_ALERT,
    TASK_COMPLETED,
    TASK_PROGRESS,
    ChannelRegistry,
    EventStream,
    RealtimeChannel,
    RealtimeEvent,
    RealtimeEventBus,
    WebSocketManager,
)
from nexus.api.routes.ws import _authenticate_websocket
from nexus.auth.principal import Principal


@pytest.fixture
def manager():
    """Provide a fresh WebSocketManager instance."""
    return WebSocketManager()


@pytest.fixture
def mock_websocket():
    """Provide a mock WebSocket instance."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture
def event_bus():
    """Provide a fresh RealtimeEventBus instance."""
    return RealtimeEventBus()


class TestWebSocketManager:
    """Tests for the WebSocketManager class."""

    @pytest.mark.asyncio
    async def test_connect_registers_client(self, manager, mock_websocket):
        """Connect registers a client in the active connections."""
        await manager.connect("client-1", mock_websocket)
        assert manager.connection_count == 1
        assert "client-1" in manager.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self, manager, mock_websocket):
        """Disconnect removes a client from active connections."""
        await manager.connect("client-1", mock_websocket)
        await manager.disconnect("client-1")
        assert manager.connection_count == 0
        assert "client-1" not in manager.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_cleans_channel_subscriptions(self, manager, mock_websocket):
        """Disconnect removes client from all channel subscriptions."""
        await manager.connect("client-1", mock_websocket)
        await manager.subscribe_channel("client-1", "updates")
        await manager.subscribe_channel("client-1", "alerts")
        await manager.disconnect("client-1")
        assert manager.get_channel_subscribers("updates") == set()
        assert manager.get_channel_subscribers("alerts") == set()

    @pytest.mark.asyncio
    async def test_send_personal_delivers_to_client(self, manager, mock_websocket):
        """send_personal sends JSON data to a specific connected client."""
        await manager.connect("client-1", mock_websocket)
        result = await manager.send_personal("client-1", {"msg": "hello"})
        assert result is True
        mock_websocket.send_json.assert_awaited_once_with({"msg": "hello"})

    @pytest.mark.asyncio
    async def test_send_personal_returns_false_for_unknown_client(self, manager):
        """send_personal returns False if client is not connected."""
        result = await manager.send_personal("unknown", {"msg": "hello"})
        assert result is False

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(self, manager):
        """broadcast sends data to all connected clients."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await manager.connect("client-1", ws1)
        await manager.connect("client-2", ws2)
        count = await manager.broadcast({"event": "test"})
        assert count == 2
        ws1.send_json.assert_awaited_once_with({"event": "test"})
        ws2.send_json.assert_awaited_once_with({"event": "test"})

    @pytest.mark.asyncio
    async def test_broadcast_handles_failed_sends(self, manager):
        """broadcast removes clients that fail to receive."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws2.send_json.side_effect = RuntimeError("connection closed")
        await manager.connect("client-1", ws1)
        await manager.connect("client-2", ws2)
        count = await manager.broadcast({"event": "test"})
        assert count == 1
        # client-2 should be disconnected
        assert manager.connection_count == 1

    @pytest.mark.asyncio
    async def test_subscribe_channel(self, manager, mock_websocket):
        """subscribe_channel adds client to the specified channel."""
        await manager.connect("client-1", mock_websocket)
        await manager.subscribe_channel("client-1", "tasks")
        assert "client-1" in manager.get_channel_subscribers("tasks")

    @pytest.mark.asyncio
    async def test_unsubscribe_channel(self, manager, mock_websocket):
        """unsubscribe_channel removes client from the channel."""
        await manager.connect("client-1", mock_websocket)
        await manager.subscribe_channel("client-1", "tasks")
        await manager.unsubscribe_channel("client-1", "tasks")
        assert "client-1" not in manager.get_channel_subscribers("tasks")

    @pytest.mark.asyncio
    async def test_broadcast_to_channel(self, manager):
        """broadcast_to_channel sends data only to channel subscribers."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()
        await manager.connect("client-1", ws1)
        await manager.connect("client-2", ws2)
        await manager.connect("client-3", ws3)
        await manager.subscribe_channel("client-1", "tasks")
        await manager.subscribe_channel("client-3", "tasks")
        count = await manager.broadcast_to_channel("tasks", {"task": "done"})
        assert count == 2
        ws1.send_json.assert_awaited_once_with({"task": "done"})
        ws3.send_json.assert_awaited_once_with({"task": "done"})
        ws2.send_json.assert_not_awaited()


class TestRealtimeEvent:
    """Tests for the RealtimeEvent dataclass."""

    def test_event_creation_with_defaults(self):
        """RealtimeEvent can be created with minimal arguments."""
        event = RealtimeEvent(event_type=TASK_PROGRESS, payload={"progress": 50})
        assert event.event_type == TASK_PROGRESS
        assert event.payload == {"progress": 50}
        assert event.id is not None
        assert event.channel is None
        assert event.source_agent_id is None
        assert isinstance(event.timestamp, datetime)

    def test_event_creation_with_all_fields(self):
        """RealtimeEvent can be created with all fields specified."""
        agent_id = uuid.uuid4()
        event = RealtimeEvent(
            event_type=AGENT_MESSAGE,
            payload={"content": "hello"},
            channel="general",
            source_agent_id=agent_id,
        )
        assert event.event_type == AGENT_MESSAGE
        assert event.channel == "general"
        assert event.source_agent_id == agent_id

    def test_event_to_dict_serialization(self):
        """to_dict produces a JSON-serializable dictionary."""
        event = RealtimeEvent(
            event_type=SYSTEM_ALERT,
            payload={"level": "critical"},
            channel="alerts",
        )
        data = event.to_dict()
        assert data["event_type"] == SYSTEM_ALERT
        assert data["channel"] == "alerts"
        assert data["payload"] == {"level": "critical"}
        assert data["id"] == str(event.id)
        assert "timestamp" in data

    def test_event_type_constants(self):
        """Event type constants are defined correctly."""
        assert AGENT_STATUS_CHANGED == "agent_status_changed"
        assert TASK_PROGRESS == "task_progress"
        assert TASK_COMPLETED == "task_completed"
        assert AGENT_MESSAGE == "agent_message"
        assert SYSTEM_ALERT == "system_alert"


class TestChannelRegistry:
    """Tests for the ChannelRegistry class."""

    def test_create_channel(self):
        """Creating a channel registers it in the registry."""
        registry = ChannelRegistry()
        channel = registry.create("tasks", "Task updates")
        assert channel.name == "tasks"
        assert channel.description == "Task updates"
        assert len(registry.list_channels()) == 1

    def test_create_duplicate_returns_existing(self):
        """Creating a channel with an existing name returns the same instance."""
        registry = ChannelRegistry()
        ch1 = registry.create("tasks")
        ch2 = registry.create("tasks")
        assert ch1 is ch2

    def test_delete_channel(self):
        """Deleting a channel removes it from the registry."""
        registry = ChannelRegistry()
        registry.create("tasks")
        result = registry.delete("tasks")
        assert result is True
        assert len(registry.list_channels()) == 0

    def test_delete_nonexistent_returns_false(self):
        """Deleting a non-existent channel returns False."""
        registry = ChannelRegistry()
        assert registry.delete("nothing") is False

    def test_get_channel(self):
        """get returns the channel by name or None if not found."""
        registry = ChannelRegistry()
        registry.create("alerts")
        assert registry.get("alerts") is not None
        assert registry.get("unknown") is None

    def test_get_subscribers(self):
        """get_subscribers returns subscriber set for a channel."""
        registry = ChannelRegistry()
        channel = registry.create("tasks")
        channel.add_subscriber("client-1")
        channel.add_subscriber("client-2")
        subs = registry.get_subscribers("tasks")
        assert subs == {"client-1", "client-2"}

    def test_get_subscribers_empty_for_unknown(self):
        """get_subscribers returns empty set for unknown channel."""
        registry = ChannelRegistry()
        assert registry.get_subscribers("nope") == set()


class TestEventStream:
    """Tests for the EventStream class."""

    @pytest.mark.asyncio
    async def test_push_and_stream(self):
        """Pushed events are yielded by stream()."""
        es = EventStream(maxsize=10)
        event = RealtimeEvent(event_type=TASK_PROGRESS, payload={"pct": 42})
        es.push(event)
        es.close()

        results = []
        async for data in es.stream():
            results.append(data)

        assert len(results) == 1
        assert '"task_progress"' in results[0]
        assert results[0].startswith("data: ")
        assert results[0].endswith("\n\n")

    @pytest.mark.asyncio
    async def test_close_terminates_stream(self):
        """Closing the stream causes the generator to terminate."""
        es = EventStream(maxsize=10)
        es.close()

        results = []
        async for data in es.stream():
            results.append(data)
        assert results == []

    def test_push_returns_false_when_closed(self):
        """push returns False after the stream is closed."""
        es = EventStream(maxsize=10)
        es.close()
        event = RealtimeEvent(event_type=TASK_PROGRESS, payload={})
        assert es.push(event) is False

    def test_push_returns_false_when_queue_full(self):
        """push returns False when the queue is at capacity."""
        es = EventStream(maxsize=2)
        e1 = RealtimeEvent(event_type=TASK_PROGRESS, payload={"n": 1})
        e2 = RealtimeEvent(event_type=TASK_PROGRESS, payload={"n": 2})
        e3 = RealtimeEvent(event_type=TASK_PROGRESS, payload={"n": 3})
        assert es.push(e1) is True
        assert es.push(e2) is True
        assert es.push(e3) is False

    @pytest.mark.asyncio
    async def test_qsize_property(self):
        """qsize reflects the current number of buffered events."""
        es = EventStream(maxsize=10)
        assert es.qsize == 0
        es.push(RealtimeEvent(event_type=TASK_PROGRESS, payload={}))
        assert es.qsize == 1


class TestRealtimeEventBus:
    """Tests for the RealtimeEventBus class."""

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, event_bus):
        """Published events are delivered to subscribed queues."""
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        event_bus.subscribe(TASK_PROGRESS, queue)
        event = RealtimeEvent(event_type=TASK_PROGRESS, payload={"pct": 100})
        delivered = await event_bus.publish(TASK_PROGRESS, event)
        assert delivered == 1
        received = queue.get_nowait()
        assert received.event_type == TASK_PROGRESS

    @pytest.mark.asyncio
    async def test_publish_fans_out_to_multiple_subscribers(self, event_bus):
        """Publishing fans out to all subscribers of a topic."""
        q1: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        q2: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        event_bus.subscribe(AGENT_MESSAGE, q1)
        event_bus.subscribe(AGENT_MESSAGE, q2)
        event = RealtimeEvent(event_type=AGENT_MESSAGE, payload={"text": "hi"})
        delivered = await event_bus.publish(AGENT_MESSAGE, event)
        assert delivered == 2
        assert not q1.empty()
        assert not q2.empty()

    @pytest.mark.asyncio
    async def test_publish_drops_when_queue_full(self, event_bus):
        """Publishing drops events for full subscriber queues."""
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=1)
        event_bus.subscribe(TASK_PROGRESS, queue)
        e1 = RealtimeEvent(event_type=TASK_PROGRESS, payload={"n": 1})
        e2 = RealtimeEvent(event_type=TASK_PROGRESS, payload={"n": 2})
        await event_bus.publish(TASK_PROGRESS, e1)
        delivered = await event_bus.publish(TASK_PROGRESS, e2)
        assert delivered == 0  # Queue was full, event dropped
        assert queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self, event_bus):
        """Unsubscribing removes the queue from the topic."""
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        event_bus.subscribe(TASK_PROGRESS, queue)
        result = event_bus.unsubscribe(TASK_PROGRESS, queue)
        assert result is True
        assert event_bus.subscriber_count(TASK_PROGRESS) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_returns_false_for_unknown(self, event_bus):
        """Unsubscribing a non-existent queue returns False."""
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        result = event_bus.unsubscribe("nonexistent", queue)
        assert result is False

    @pytest.mark.asyncio
    async def test_subscriber_count(self, event_bus):
        """subscriber_count returns correct count for a topic."""
        q1: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        q2: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        event_bus.subscribe(SYSTEM_ALERT, q1)
        event_bus.subscribe(SYSTEM_ALERT, q2)
        assert event_bus.subscriber_count(SYSTEM_ALERT) == 2

    @pytest.mark.asyncio
    async def test_topics_list(self, event_bus):
        """topics() returns all topics with active subscribers."""
        q: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        event_bus.subscribe(TASK_PROGRESS, q)
        event_bus.subscribe(AGENT_MESSAGE, q)
        topics = event_bus.topics()
        assert TASK_PROGRESS in topics
        assert AGENT_MESSAGE in topics

    @pytest.mark.asyncio
    async def test_publish_to_empty_topic_returns_zero(self, event_bus):
        """Publishing to a topic with no subscribers returns 0."""
        event = RealtimeEvent(event_type=TASK_PROGRESS, payload={})
        delivered = await event_bus.publish(TASK_PROGRESS, event)
        assert delivered == 0

    @pytest.mark.asyncio
    async def test_all_catch_all_receives_specific_topic_events(self, event_bus):
        """Subscribing to '__all__' receives events published to specific topics."""
        all_queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        event_bus.subscribe("__all__", all_queue)

        event = RealtimeEvent(event_type=TASK_PROGRESS, payload={"pct": 50})
        delivered = await event_bus.publish(TASK_PROGRESS, event)

        assert delivered == 1
        received = all_queue.get_nowait()
        assert received.event_type == TASK_PROGRESS
        assert received.payload == {"pct": 50}
        assert received is event

    @pytest.mark.asyncio
    async def test_all_catch_all_no_double_delivery(self, event_bus):
        """Publishing to '__all__' topic does not double-deliver to __all__ subscribers."""
        all_queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        event_bus.subscribe("__all__", all_queue)

        event = RealtimeEvent(event_type=SYSTEM_ALERT, payload={"msg": "test"})
        delivered = await event_bus.publish("__all__", event)

        assert delivered == 1
        assert all_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_all_catch_all_coexists_with_specific_subscriber(self, event_bus):
        """Both specific topic and __all__ subscribers receive the event."""
        specific_queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        all_queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        event_bus.subscribe(AGENT_MESSAGE, specific_queue)
        event_bus.subscribe("__all__", all_queue)

        event = RealtimeEvent(event_type=AGENT_MESSAGE, payload={"text": "hi"})
        delivered = await event_bus.publish(AGENT_MESSAGE, event)

        assert delivered == 2
        assert not specific_queue.empty()
        assert not all_queue.empty()
        assert specific_queue.get_nowait() is event
        assert all_queue.get_nowait() is event


class TestWebSocketAuth:
    """Tests for WebSocket authentication enforcement."""

    @staticmethod
    def _socket(principal=None):
        """A stand-in WebSocket whose scope carries the given principal."""
        ws = AsyncMock()
        ws.scope = {"type": "websocket", "state": {"principal": principal}}
        return ws

    @pytest.mark.asyncio
    async def test_authenticate_rejects_anonymous_handshake(self):
        """_authenticate_websocket closes with 1008 when no principal resolved."""
        ws = self._socket(None)
        result = await _authenticate_websocket(ws)
        assert result is None
        ws.close.assert_awaited_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_authenticate_rejects_scope_without_state(self):
        """A handshake that never reached the auth middleware is rejected."""
        ws = AsyncMock()
        ws.scope = {"type": "websocket"}
        result = await _authenticate_websocket(ws)
        assert result is None
        ws.close.assert_awaited_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_authenticate_ignores_company_id_query_param(self):
        """A company_id in the query string grants nothing on its own."""
        ws = self._socket(None)
        ws.scope["query_string"] = f"company_id={uuid.uuid4()}".encode()
        result = await _authenticate_websocket(ws)
        assert result is None
        ws.close.assert_awaited_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_authenticate_accepts_resolved_principal(self):
        """_authenticate_websocket returns the principal the middleware resolved."""
        principal = Principal(
            kind="user",
            company_id=uuid.uuid4(),
            role="admin",
            user_id=uuid.uuid4(),
            email="admin@example.com",
        )
        ws = self._socket(principal)
        result = await _authenticate_websocket(ws)
        assert result is principal
        assert result.company_id == principal.company_id
        ws.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manager_stores_company_id_on_connect(self):
        """WebSocketManager stores company_id when provided at connect time."""
        mgr = WebSocketManager()
        ws = AsyncMock()
        company = uuid.uuid4()
        await mgr.connect("client-1", ws, company)
        assert mgr.get_client_company("client-1") == company

    @pytest.mark.asyncio
    async def test_manager_broadcast_to_company(self):
        """broadcast_to_company sends only to connections with matching company_id."""
        mgr = WebSocketManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()
        company_a = uuid.uuid4()
        company_b = uuid.uuid4()
        await mgr.connect("client-1", ws1, company_a)
        await mgr.connect("client-2", ws2, company_b)
        await mgr.connect("client-3", ws3, company_a)

        count = await mgr.broadcast_to_company(company_a, {"event": "test"})
        assert count == 2
        ws1.send_json.assert_awaited_once_with({"event": "test"})
        ws3.send_json.assert_awaited_once_with({"event": "test"})
        ws2.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manager_disconnect_clears_company_id(self):
        """Disconnecting a client removes the company_id association."""
        mgr = WebSocketManager()
        ws = AsyncMock()
        company = uuid.uuid4()
        await mgr.connect("client-1", ws, company)
        await mgr.disconnect("client-1")
        assert mgr.get_client_company("client-1") is None
