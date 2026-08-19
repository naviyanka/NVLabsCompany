"""Server-Sent Events (SSE) streaming support.

Provides the EventStream class that buffers RealtimeEvents in a bounded
asyncio.Queue and yields them as SSE-formatted strings for use with
FastAPI StreamingResponse.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

from nexus.realtime.events import RealtimeEvent

logger = logging.getLogger(__name__)

# Default maximum queue size for SSE buffering
DEFAULT_MAX_SIZE = 256


class EventStream:
    """Buffered event stream for Server-Sent Events delivery.

    Uses an asyncio.Queue with a configurable bound to buffer events
    between the publisher and the HTTP streaming response. Events are
    formatted as SSE data lines when consumed via the stream() generator.

    Attributes:
        _queue: Bounded asyncio queue holding RealtimeEvent instances.
        _closed: Flag indicating the stream has been terminated.
        maxsize: Maximum number of buffered events before drops occur.
    """

    def __init__(self, maxsize: int = DEFAULT_MAX_SIZE) -> None:
        """Initialize the event stream with a bounded queue.

        Args:
            maxsize: Maximum number of events to buffer. Defaults to 256.
        """
        self.maxsize = maxsize
        self._queue: asyncio.Queue[RealtimeEvent | None] = asyncio.Queue(
            maxsize=maxsize
        )
        self._closed: bool = False

    @property
    def closed(self) -> bool:
        """Return whether the stream has been closed."""
        return self._closed

    def push(self, event: RealtimeEvent) -> bool:
        """Push an event into the stream buffer.

        Uses put_nowait for non-blocking operation. If the queue is full,
        the event is dropped and False is returned.

        Args:
            event: The RealtimeEvent to buffer.

        Returns:
            True if the event was buffered, False if dropped (queue full or closed).
        """
        if self._closed:
            return False
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "EventStream queue full (maxsize=%d), dropping event %s",
                self.maxsize,
                event.event_type,
            )
            return False

    def close(self) -> None:
        """Signal the stream to terminate.

        Pushes a None sentinel to unblock any waiting consumer, and sets
        the closed flag to prevent further pushes.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    async def stream(self) -> AsyncGenerator[str, None]:
        """Async generator yielding SSE-formatted event strings.

        Blocks on the internal queue waiting for events. Each event is
        formatted as 'data: {json}\\n\\n' per the SSE specification.
        Terminates when the stream is closed (None sentinel received).

        Yields:
            SSE-formatted string for each buffered event.
        """
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield format_sse(event)

    @property
    def qsize(self) -> int:
        """Return the current number of buffered events."""
        return self._queue.qsize()


def format_sse(event: RealtimeEvent) -> str:
    """Format a RealtimeEvent as an SSE data line.

    Args:
        event: The event to format.

    Returns:
        SSE-formatted string: 'data: {json}\\n\\n'
    """
    return f"data: {json.dumps(event.to_dict())}\n\n"
