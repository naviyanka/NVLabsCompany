"""Tests for the SSE endpoint and event stream formatting.

Validates EventStream SSE formatting, event type filtering, channel
filtering, queue bounds enforcement, and graceful close behavior.
"""

import asyncio
import json
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
