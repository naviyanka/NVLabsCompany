"""Typed event dataclasses for the real-time streaming subsystem.

Defines the core RealtimeEvent dataclass and event type constants used across
WebSocket, SSE, and pub/sub channels.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Event type constants
AGENT_STATUS_CHANGED = "agent_status_changed"
TASK_PROGRESS = "task_progress"
TASK_COMPLETED = "task_completed"
AGENT_MESSAGE = "agent_message"
SYSTEM_ALERT = "system_alert"


@dataclass
class RealtimeEvent:
    """A typed event for real-time streaming to connected clients.

    Represents a single event that can be published through the real-time
    event bus, delivered via WebSocket or SSE to subscribed clients.

    Attributes:
        id: Unique identifier for this event instance.
        event_type: Category of event (e.g., TASK_PROGRESS, AGENT_MESSAGE).
        channel: Optional channel name this event is scoped to.
        payload: Arbitrary event data as a dictionary.
        timestamp: UTC datetime when the event was created.
        source_agent_id: Optional UUID of the agent that produced this event.
        company_id: Optional tenant UUID for multi-tenant event scoping.
            When set, only clients authenticated for this company receive
            the event. When None, the event is delivered to all tenants.
    """

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    channel: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_agent_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event to a JSON-compatible dictionary.

        Returns:
            Dictionary representation suitable for JSON encoding.
        """
        return {
            "id": str(self.id),
            "event_type": self.event_type,
            "channel": self.channel,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "source_agent_id": str(self.source_agent_id) if self.source_agent_id else None,
            "company_id": str(self.company_id) if self.company_id else None,
        }
