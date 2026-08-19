"""Server-Sent Events (SSE) endpoint for real-time event streaming.

Provides a GET /events/stream endpoint that returns a StreamingResponse
delivering events in SSE format. Supports optional filtering by event
type and channel.

Authentication is enforced via the standard CurrentCompanyId dependency
(X-Company-Id header), consistent with all other API routes.
"""

import asyncio
import logging
import uuid
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from nexus.api.deps import CurrentCompanyId
from nexus.realtime.event_bus import RealtimeEventBus
from nexus.realtime.events import RealtimeEvent
from nexus.realtime.sse import EventStream, format_sse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

# Shared event bus instance for SSE subscribers
event_bus = RealtimeEventBus()


async def _event_generator(
    request: Request,
    event_types: list[str] | None,
    channel: str | None,
    company_id: uuid.UUID | None = None,
) -> AsyncGenerator[str, None]:
    """Generate SSE events from the event bus with filtering.

    Creates a subscriber queue, subscribes to all or specific topics,
    and yields formatted events until the client disconnects.

    Events are filtered by tenant: only events whose company_id is None
    (global/broadcast events) or matches the authenticated company_id
    are delivered. This enforces multi-tenant isolation at the stream level.

    Args:
        request: The incoming HTTP request (used for disconnect detection).
        event_types: Optional list of event type filters.
        channel: Optional channel filter.
        company_id: Authenticated tenant UUID for tenant-scoped filtering.

    Yields:
        SSE-formatted event strings.
    """
    queue: asyncio.Queue[RealtimeEvent | None] = asyncio.Queue(maxsize=256)

    # Subscribe to specified topics or use a catch-all
    topics = event_types if event_types else ["__all__"]
    for topic in topics:
        event_bus.subscribe(topic, queue)

    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield ": keepalive\n\n"
                continue

            if event is None:
                break

            # Apply tenant isolation filter: only deliver events that are
            # global (company_id is None) or scoped to this tenant
            if company_id and event.company_id and event.company_id != company_id:
                continue

            # Apply channel filter
            if channel and event.channel != channel:
                continue

            yield format_sse(event)
    finally:
        for topic in topics:
            event_bus.unsubscribe(topic, queue)


@router.get("/events/stream")
async def stream_events(
    request: Request,
    company_id: CurrentCompanyId,
    event_types: Optional[str] = Query(
        None,
        description="Comma-separated list of event types to filter by",
    ),
    channel: Optional[str] = Query(
        None,
        description="Channel name to filter events by",
    ),
) -> StreamingResponse:
    """Stream real-time events using Server-Sent Events (SSE).

    Returns a streaming HTTP response with content-type text/event-stream.
    Events are delivered as they occur, formatted as SSE data lines.

    Requires authentication via X-Company-Id header for tenant isolation.

    Query Parameters:
        event_types: Optional comma-separated list of event types to filter.
                     If not provided, all events are streamed.
        channel: Optional channel name to filter events by.

    Returns:
        StreamingResponse with SSE-formatted event data.
    """
    types_list: list[str] | None = None
    if event_types:
        types_list = [t.strip() for t in event_types.split(",") if t.strip()]

    return StreamingResponse(
        _event_generator(request, types_list, channel, company_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
