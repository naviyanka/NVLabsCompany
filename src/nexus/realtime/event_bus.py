"""Real-time event bus for topic-based pub/sub with asyncio.Queue subscribers.

This module is separate from nexus.communication.event_bus which handles
domain-level event dispatch. This event bus is designed for real-time
streaming delivery to connected clients via WebSocket and SSE.
"""

import asyncio
import logging
from typing import Any

from nexus.realtime.events import RealtimeEvent

logger = logging.getLogger(__name__)

# Default subscriber queue size
DEFAULT_SUBSCRIBER_QUEUE_SIZE = 128


class RealtimeEventBus:
    """Async pub/sub event bus with topic-based routing and bounded queues.

    Subscribers register an asyncio.Queue for a specific topic. When events
    are published to a topic, they are fanned out to all subscriber queues
    using non-blocking put_nowait. If a subscriber queue is full, the event
    is silently dropped for that subscriber (backpressure).

    This is designed for real-time streaming to WebSocket/SSE clients,
    separate from the domain event bus in nexus.communication.

    Attributes:
        _subscriptions: Mapping of topic to list of subscriber queues.
    """

    def __init__(self) -> None:
        """Initialize the real-time event bus with empty subscriptions."""
        self._subscriptions: dict[str, list[asyncio.Queue[RealtimeEvent]]] = {}

    def subscribe(
        self, topic: str, queue: asyncio.Queue[RealtimeEvent]
    ) -> None:
        """Subscribe a queue to receive events for a topic.

        Args:
            topic: The topic/event_type to subscribe to.
            queue: An asyncio.Queue that will receive published events.
        """
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
        self._subscriptions[topic].append(queue)
        logger.debug("Subscriber added to topic '%s'", topic)

    def unsubscribe(
        self, topic: str, queue: asyncio.Queue[RealtimeEvent]
    ) -> bool:
        """Remove a queue subscription from a topic.

        Args:
            topic: The topic to unsubscribe from.
            queue: The queue to remove.

        Returns:
            True if the queue was found and removed, False otherwise.
        """
        subscribers = self._subscriptions.get(topic)
        if subscribers is None:
            return False
        try:
            subscribers.remove(queue)
            if not subscribers:
                del self._subscriptions[topic]
            return True
        except ValueError:
            return False

    async def publish(self, topic: str, event: RealtimeEvent) -> int:
        """Publish an event to all subscribers of a topic.

        Uses non-blocking put_nowait to fan out to subscriber queues.
        If a queue is full, the event is dropped for that subscriber.

        In addition to delivering to subscribers of the exact topic,
        events are also fanned out to subscribers of the special "__all__"
        catch-all topic. This allows clients to receive all events without
        subscribing to each topic individually.

        Args:
            topic: The topic to publish to.
            event: The RealtimeEvent to deliver.

        Returns:
            Number of subscribers that successfully received the event.
        """
        subscribers = self._subscriptions.get(topic, [])
        delivered = 0
        for queue in list(subscribers):
            try:
                queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                logger.debug(
                    "Subscriber queue full for topic '%s', dropping event",
                    topic,
                )

        # Fan out to "__all__" catch-all subscribers (skip if topic is already "__all__")
        if topic != "__all__":
            all_subscribers = self._subscriptions.get("__all__", [])
            for queue in list(all_subscribers):
                try:
                    queue.put_nowait(event)
                    delivered += 1
                except asyncio.QueueFull:
                    logger.debug(
                        "Subscriber queue full for '__all__' catch-all, dropping event",
                    )

        return delivered

    def subscriber_count(self, topic: str) -> int:
        """Get the number of subscribers for a topic.

        Args:
            topic: The topic to query.

        Returns:
            Number of subscribed queues.
        """
        return len(self._subscriptions.get(topic, []))

    def topics(self) -> list[str]:
        """List all topics with active subscribers.

        Returns:
            List of topic strings that have at least one subscriber.
        """
        return list(self._subscriptions.keys())
