"""Best-effort, tenant-scoped fan-out of domain events onto the SSE bus.

Callers publish after their change is committed: a client that refetches on
the event must read the new state, never the old one.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Agent hierarchy and MCP binding changes: what the Canvas draws.
TOPOLOGY_CHANNEL = "topology"


async def publish_event(
    channel: str, event_type: str, company_id: uuid.UUID, payload: dict[str, Any]
) -> None:
    """Publish ``event_type`` on ``channel`` to ``company_id``'s subscribers only."""
    try:
        from nexus.api.routes.events import event_bus
        from nexus.realtime.events import RealtimeEvent

        await event_bus.publish(
            event_type,
            RealtimeEvent(
                event_type=event_type, payload=payload, channel=channel, company_id=company_id
            ),
        )
    except Exception as exc:  # noqa: BLE001 - realtime is best-effort
        logger.debug("%s event %s not published: %s", channel, event_type, exc)
