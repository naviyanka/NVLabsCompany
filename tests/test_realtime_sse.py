"""Tests for the SSE endpoint and event stream formatting.

Validates EventStream SSE formatting, event type filtering, channel
filtering, queue bounds enforcement, and graceful close behavior.
Also tests SSE endpoint auth enforcement and tenant isolation.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from nexus.realtime import (
    AGENT_MESSAGE,
    AGENT_STATUS_CHANGED,
    SYSTEM_ALERT,
    TASK_COMPLETED,
    TASK_PROGRESS,
    EventStream,
    RealtimeEvent,
    RealtimeEventBus,
)
from nexus.realtime.sse import format_sse


class TestSSEFormatting:
    """Tests for SSE event formatting."""

    def test_format_sse_basic(self):
        """format_sse produces correct SSE data line format."""
        event = RealtimeEvent(
            event_type=TASK_PROGRESS,
            payload={"progress": 75},
        )
        result = format_sse(event)
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        # Parse the JSON portion
        json_str = result[len("data: "):-2]
        data = json.loads(json_str)
        assert data["event_type"] == "task_progress"
        assert data["payload"] == {"progress": 75}

    def test_format_sse_contains_all_fields(self):
        """format_sse includes id, event_type, channel, payload, timestamp."""
        agent_id = uuid.uuid4()
        event = RealtimeEvent(
            event_type=AGENT_MESSAGE,
            payload={"content": "hello"},
            channel="general",
            source_agent_id=agent_id,
        )
        result = format_sse(event)
        json_str = result[len("data: "):-2]
        data = json.loads(json_str)
        assert data["id"] == str(event.id)
        assert data["event_type"] == "agent_message"
        assert data["channel"] == "general"
        assert data["payload"] == {"content": "hello"}
        assert data["source_agent_id"] == str(agent_id)
        assert "timestamp" in data

    def test_format_sse_null_fields(self):
        """format_sse handles None channel and source_agent_id."""
        event = RealtimeEvent(event_type=SYSTEM_ALERT, payload={"msg": "test"})
        result = format_sse(event)
        json_str = result[len("data: "):-2]
        data = json.loads(json_str)
        assert data["channel"] is None
        assert data["source_agent_id"] is None


class TestEventStreamSSE:
    """Tests for EventStream SSE delivery."""

    @pytest.mark.asyncio
    async def test_stream_yields_sse_format(self):
        """EventStream.stream() yields SSE-formatted strings."""
        es = EventStream(maxsize=10)
        event = RealtimeEvent(event_type=TASK_COMPLETED, payload={"task_id": "abc"})
        es.push(event)
        es.close()

        results = []
        async for data in es.stream():
            results.append(data)

        assert len(results) == 1
        assert results[0].startswith("data: ")
        parsed = json.loads(results[0][len("data: "):-2])
        assert parsed["event_type"] == "task_completed"
        assert parsed["payload"]["task_id"] == "abc"

    @pytest.mark.asyncio
    async def test_stream_multiple_events_in_order(self):
        """Events are yielded in FIFO order from the stream."""
        es = EventStream(maxsize=10)
        for i in range(5):
            es.push(RealtimeEvent(event_type=TASK_PROGRESS, payload={"i": i}))
        es.close()

        results = []
        async for data in es.stream():
            results.append(data)

        assert len(results) == 5
        for i, result in enumerate(results):
            parsed = json.loads(result[len("data: "):-2])
            assert parsed["payload"]["i"] == i

    @pytest.mark.asyncio
    async def test_stream_terminates_on_close(self):
        """Closing the stream causes the async generator to finish."""
        es = EventStream(maxsize=10)

        async def delayed_close():
            await asyncio.sleep(0.05)
            es.close()

        asyncio.get_event_loop().call_soon(
            asyncio.ensure_future, delayed_close()
        )

        # Use a task to handle the timing
        task = asyncio.create_task(delayed_close())
        results = []
        async for data in es.stream():
            results.append(data)
        await task
        assert results == []

    def test_queue_bounds_enforced(self):
        """EventStream respects maxsize and rejects excess events."""
        es = EventStream(maxsize=3)
        events = [
            RealtimeEvent(event_type=TASK_PROGRESS, payload={"n": i})
            for i in range(5)
        ]
        results = [es.push(e) for e in events]
        assert results == [True, True, True, False, False]
        assert es.qsize == 3

    @pytest.mark.asyncio
    async def test_closed_property(self):
        """closed property reflects stream state."""
        es = EventStream(maxsize=10)
        assert es.closed is False
        es.close()
        assert es.closed is True

    @pytest.mark.asyncio
    async def test_push_after_close_rejected(self):
        """Events pushed after close are rejected."""
        es = EventStream(maxsize=10)
        es.close()
        event = RealtimeEvent(event_type=TASK_PROGRESS, payload={})
        assert es.push(event) is False

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Calling close multiple times is safe."""
        es = EventStream(maxsize=10)
        es.close()
        es.close()  # Should not raise
        assert es.closed is True

    @pytest.mark.asyncio
    async def test_event_bus_to_stream_integration(self):
        """RealtimeEventBus can deliver events to an EventStream."""
        bus = RealtimeEventBus()
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=10)
        bus.subscribe(AGENT_STATUS_CHANGED, queue)

        event = RealtimeEvent(
            event_type=AGENT_STATUS_CHANGED,
            payload={"status": "idle"},
        )
        await bus.publish(AGENT_STATUS_CHANGED, event)

        # Verify the event arrived
        received = queue.get_nowait()
        assert received.event_type == AGENT_STATUS_CHANGED
        assert received.payload == {"status": "idle"}


class TestSSEAuthEnforcement:
    """Tests for SSE endpoint authentication enforcement.

    The stream used to be gated on an ``X-Company-Id`` header, which any client
    could set to any value. It is now gated on the authenticated principal, so
    an anonymous request is a 401 and the company is never read off the wire.
    """

    def test_sse_endpoint_rejects_anonymous_request(self, monkeypatch):
        """GET /events/stream returns 401 without a session or API key."""
        from nexus.config import settings

        monkeypatch.setattr(settings, "auth_enabled", True)
        from nexus.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/events/stream")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_sse_endpoint_ignores_company_id_header(self, monkeypatch):
        """A self-asserted X-Company-Id header no longer authenticates anything."""
        from nexus.config import settings

        monkeypatch.setattr(settings, "auth_enabled", True)
        from nexus.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/events/stream",
            headers={"X-Company-Id": str(uuid.uuid4())},
        )
        assert response.status_code == 401

    def test_sse_endpoint_rejects_bogus_bearer_token(self, monkeypatch):
        """An unresolvable bearer token is anonymous, not an error."""
        from nexus.config import settings

        monkeypatch.setattr(settings, "auth_enabled", True)
        from nexus.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/events/stream",
            headers={"Authorization": "Bearer nvk_not_a_real_key"},
        )
        assert response.status_code == 401

    def test_sse_dependency_returns_principal_company(self):
        """get_current_company_id reads the company off the principal."""
        from nexus.api.deps import get_current_company_id
        from nexus.auth.principal import Principal

        company_id = uuid.uuid4()
        principal = Principal(
            kind="user",
            company_id=company_id,
            role="admin",
            user_id=uuid.uuid4(),
            email="admin@example.com",
        )
        assert get_current_company_id(principal) == company_id


class TestSSETenantIsolation:
    """Tests for SSE tenant-scoped event filtering."""

    @pytest.mark.asyncio
    async def test_event_generator_filters_other_company_events(self):
        """_event_generator skips events scoped to a different company."""
        from nexus.api.routes.events import _event_generator, event_bus

        company_a = uuid.uuid4()
        company_b = uuid.uuid4()

        # Mock request that disconnects after receiving all events
        request = AsyncMock()
        disconnect_after = 3  # Process 3 wait_for cycles then disconnect
        call_count = 0

        async def is_disconnected():
            nonlocal call_count
            call_count += 1
            return call_count > disconnect_after

        request.is_disconnected = is_disconnected

        # Publish events to the bus in a background task so the generator
        # can receive them. The generator subscribes to "__all__".
        event_for_a = RealtimeEvent(
            event_type=TASK_PROGRESS,
            payload={"for": "a"},
            company_id=company_a,
        )
        event_for_b = RealtimeEvent(
            event_type=TASK_PROGRESS,
            payload={"for": "b"},
            company_id=company_b,
        )
        event_global = RealtimeEvent(
            event_type=SYSTEM_ALERT,
            payload={"for": "all"},
            company_id=None,
        )

        async def publish_events():
            """Publish events after a brief delay to let generator subscribe."""
            await asyncio.sleep(0.01)
            await event_bus.publish(TASK_PROGRESS, event_for_a)
            await event_bus.publish(TASK_PROGRESS, event_for_b)
            await event_bus.publish(SYSTEM_ALERT, event_global)

        # Start publishing in background
        publish_task = asyncio.create_task(publish_events())

        # Collect results from a generator that filters for company_a
        results = []
        async for sse_data in _event_generator(request, None, None, company_a):
            results.append(sse_data)
            if len(results) >= 2:
                break

        await publish_task

        # Should have received event_for_a and event_global, but NOT event_for_b
        assert len(results) == 2
        # First result should be the event for company_a
        parsed_0 = json.loads(results[0][len("data: "):-2])
        assert parsed_0["payload"]["for"] == "a"
        # Second result should be the global event
        parsed_1 = json.loads(results[1][len("data: "):-2])
        assert parsed_1["payload"]["for"] == "all"
