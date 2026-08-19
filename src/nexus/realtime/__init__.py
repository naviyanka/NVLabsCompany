"""Real-time streaming subsystem for WebSocket and Server-Sent Events.

This module provides the infrastructure for real-time event delivery to
connected clients via WebSocket connections and SSE streams. It includes:

- WebSocketManager: Connection management and channel-based messaging
- RealtimeEvent: Typed event dataclass for streaming payloads
- RealtimeChannel: Named channel for subscriber grouping
- ChannelRegistry: Registry for managing channel lifecycle
- EventStream: Bounded-queue SSE stream with async generator
- RealtimeEventBus: Topic-based pub/sub with non-blocking fan-out
"""

from nexus.realtime.channels import ChannelRegistry, RealtimeChannel
from nexus.realtime.event_bus import RealtimeEventBus
from nexus.realtime.events import (
    AGENT_MESSAGE,
    AGENT_STATUS_CHANGED,
    SYSTEM_ALERT,
    TASK_COMPLETED,
    TASK_PROGRESS,
    RealtimeEvent,
)
from nexus.realtime.sse import EventStream
from nexus.realtime.websocket_manager import WebSocketManager

__all__ = [
    "WebSocketManager",
    "RealtimeEvent",
    "RealtimeChannel",
    "ChannelRegistry",
    "EventStream",
    "RealtimeEventBus",
    "AGENT_STATUS_CHANGED",
    "TASK_PROGRESS",
    "TASK_COMPLETED",
    "AGENT_MESSAGE",
    "SYSTEM_ALERT",
]
