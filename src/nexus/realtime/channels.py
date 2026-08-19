"""Channel management for real-time client subscriptions.

Provides the RealtimeChannel dataclass and ChannelRegistry for managing
named channels that clients can subscribe to for scoped event delivery.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class RealtimeChannel:
    """A named channel that clients can subscribe to for scoped event delivery.

    Channels group subscribers by topic so that events can be broadcast
    to a specific subset of connected clients rather than all of them.

    Attributes:
        name: Unique channel name (e.g., 'agent-updates', 'task-123').
        description: Human-readable description of the channel's purpose.
        created_at: UTC datetime when the channel was created.
        subscribers: Set of client_id strings currently subscribed.
    """

    name: str
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    subscribers: set[str] = field(default_factory=set)

    def add_subscriber(self, client_id: str) -> None:
        """Add a client to this channel's subscriber set.

        Args:
            client_id: The UUID string identifying the client.
        """
        self.subscribers.add(client_id)

    def remove_subscriber(self, client_id: str) -> None:
        """Remove a client from this channel's subscriber set.

        Args:
            client_id: The UUID string identifying the client.
        """
        self.subscribers.discard(client_id)

    @property
    def subscriber_count(self) -> int:
        """Return the number of active subscribers."""
        return len(self.subscribers)


class ChannelRegistry:
    """Registry of active real-time channels.

    Manages the lifecycle of channels: creation, deletion, listing,
    and subscriber tracking. Thread-safe for use in async contexts
    (single-threaded asyncio event loop).

    Attributes:
        _channels: Internal mapping of channel name to RealtimeChannel.
    """

    def __init__(self) -> None:
        """Initialize an empty channel registry."""
        self._channels: dict[str, RealtimeChannel] = {}

    def create(self, name: str, description: str = "") -> RealtimeChannel:
        """Create and register a new channel.

        If a channel with the given name already exists, returns the existing one.

        Args:
            name: Unique name for the channel.
            description: Optional human-readable description.

        Returns:
            The created or existing RealtimeChannel instance.
        """
        if name in self._channels:
            return self._channels[name]
        channel = RealtimeChannel(name=name, description=description)
        self._channels[name] = channel
        return channel

    def delete(self, name: str) -> bool:
        """Delete a channel by name.

        Args:
            name: The channel name to remove.

        Returns:
            True if the channel was found and removed, False otherwise.
        """
        if name in self._channels:
            del self._channels[name]
            return True
        return False

    def get(self, name: str) -> RealtimeChannel | None:
        """Retrieve a channel by name.

        Args:
            name: The channel name to look up.

        Returns:
            The RealtimeChannel instance if found, None otherwise.
        """
        return self._channels.get(name)

    def list_channels(self) -> list[RealtimeChannel]:
        """List all registered channels.

        Returns:
            List of all active RealtimeChannel instances.
        """
        return list(self._channels.values())

    def get_subscribers(self, name: str) -> set[str]:
        """Get the set of subscriber client_ids for a channel.

        Args:
            name: The channel name to query.

        Returns:
            Set of client_id strings, or empty set if channel not found.
        """
        channel = self._channels.get(name)
        if channel is None:
            return set()
        return channel.subscribers.copy()
