"""External channel integration for routing messages to/from external platforms.

Provides a Protocol-based interface for channel implementations (Slack, Discord,
Webhooks) and a ChannelRouter that handles outbound message routing and inbound
message conversion.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from nexus.models.communication import Message


@runtime_checkable
class ChannelInterface(Protocol):
    """Protocol defining the interface for external communication channels.

    All channel implementations must provide async send and receive methods
    for bidirectional message exchange with external platforms.
    """

    async def send(self, message: Message) -> bool:
        """Send a message to the external channel.

        Args:
            message: The Message object to send.

        Returns:
            True if the message was successfully sent, False otherwise.
        """
        ...

    async def receive(self) -> Optional[Message]:
        """Receive a message from the external channel.

        Returns:
            A Message object if one is available, None otherwise.
        """
        ...


class SlackChannel:
    """Slack channel implementation for sending/receiving messages via Slack.

    This is a placeholder implementation that stores messages in memory
    for testing purposes. A production version would use the Slack API.

    Attributes:
        channel_name: The Slack channel name.
        webhook_url: The Slack webhook URL for posting messages.
        company_id: Company scope for tenant isolation.
    """

    def __init__(
        self,
        channel_name: str,
        webhook_url: str = "",
        company_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Initialize the Slack channel.

        Args:
            channel_name: The Slack channel name (e.g., #general).
            webhook_url: The Slack incoming webhook URL.
            company_id: Company scope for tenant isolation.
        """
        self.channel_name = channel_name
        self.webhook_url = webhook_url
        self.company_id = company_id
        self._sent: list[Message] = []
        self._inbox: list[Message] = []

    async def send(self, message: Message) -> bool:
        """Send a message to the Slack channel.

        Args:
            message: The Message object to send.

        Returns:
            True (placeholder always succeeds).
        """
        self._sent.append(message)
        return True

    async def receive(self) -> Optional[Message]:
        """Receive the next message from the Slack channel inbox.

        Returns:
            A Message object if available, None otherwise.
        """
        if self._inbox:
            return self._inbox.pop(0)
        return None


class DiscordChannel:
    """Discord channel implementation for sending/receiving messages via Discord.

    This is a placeholder implementation that stores messages in memory
    for testing purposes. A production version would use the Discord API.

    Attributes:
        guild_id: The Discord guild (server) identifier.
        channel_id: The Discord channel identifier.
        bot_token: The Discord bot token for authentication.
        company_id: Company scope for tenant isolation.
    """

    def __init__(
        self,
        guild_id: str,
        channel_id: str,
        bot_token: str = "",
        company_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Initialize the Discord channel.

        Args:
            guild_id: The Discord guild (server) ID.
            channel_id: The Discord channel ID.
            bot_token: The Discord bot token.
            company_id: Company scope for tenant isolation.
        """
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.bot_token = bot_token
        self.company_id = company_id
        self._sent: list[Message] = []
        self._inbox: list[Message] = []

    async def send(self, message: Message) -> bool:
        """Send a message to the Discord channel.

        Args:
            message: The Message object to send.

        Returns:
            True (placeholder always succeeds).
        """
        self._sent.append(message)
        return True

    async def receive(self) -> Optional[Message]:
        """Receive the next message from the Discord channel inbox.

        Returns:
            A Message object if available, None otherwise.
        """
        if self._inbox:
            return self._inbox.pop(0)
        return None


class WebhookChannel:
    """Webhook channel for sending/receiving messages via HTTP webhooks.

    This is a placeholder implementation that stores messages in memory
    for testing purposes. A production version would make HTTP calls
    to configured endpoint URLs.

    Attributes:
        endpoint_url: The webhook endpoint URL.
        secret: Optional webhook secret for request signing.
        company_id: Company scope for tenant isolation.
    """

    def __init__(
        self,
        endpoint_url: str,
        secret: str = "",
        company_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Initialize the Webhook channel.

        Args:
            endpoint_url: The webhook endpoint URL.
            secret: Optional secret for HMAC signing of payloads.
            company_id: Company scope for tenant isolation.
        """
        self.endpoint_url = endpoint_url
        self.secret = secret
        self.company_id = company_id
        self._sent: list[Message] = []
        self._inbox: list[Message] = []

    async def send(self, message: Message) -> bool:
        """Send a message via the webhook endpoint.

        Args:
            message: The Message object to send.

        Returns:
            True (placeholder always succeeds).
        """
        self._sent.append(message)
        return True

    async def receive(self) -> Optional[Message]:
        """Receive the next message from the webhook inbox.

        Returns:
            A Message object if available, None otherwise.
        """
        if self._inbox:
            return self._inbox.pop(0)
        return None


class ChannelRouter:
    """Routes outbound messages to appropriate external channels and handles inbound.

    Manages a registry of named channels and routes messages based on
    configuration. Supports converting inbound external messages into
    internal Message objects.

    Attributes:
        db: Optional async database session for persistence.
    """

    def __init__(self, db: Optional[Any] = None) -> None:
        """Initialize the ChannelRouter.

        Args:
            db: Optional AsyncSession for database persistence.
        """
        self.db = db
        self._channels: dict[str, ChannelInterface] = {}
        # Routing rules: message_type or keyword -> channel name
        self._routes: dict[str, str] = {}

    def register_channel(self, name: str, channel: ChannelInterface) -> None:
        """Register an external channel with a unique name.

        Args:
            name: Unique identifier for the channel.
            channel: Channel implementation conforming to ChannelInterface.
        """
        self._channels[name] = channel

    def add_route(self, key: str, channel_name: str) -> None:
        """Add a routing rule mapping a key to a channel.

        Keys can be message types, priority levels, or arbitrary route names.

        Args:
            key: The routing key (e.g., 'urgent', 'slack', 'notification').
            channel_name: Name of the registered channel to route to.
        """
        self._routes[key] = channel_name

    async def route_outbound(self, message: Message, route_key: Optional[str] = None) -> bool:
        """Route an outbound message to the appropriate external channel.

        Determines the target channel using the route_key (falling back to
        message priority, then message type). Returns False if no matching
        route or channel is found.

        Args:
            message: The Message to route externally.
            route_key: Optional explicit routing key override.

        Returns:
            True if the message was successfully routed, False otherwise.
        """
        # Determine which channel to use
        key = route_key or message.priority or message.message_type
        channel_name = self._routes.get(key)

        if channel_name is None:
            # Try message type as fallback
            channel_name = self._routes.get(message.message_type)

        if channel_name is None:
            return False

        channel = self._channels.get(channel_name)
        if channel is None:
            return False

        return await channel.send(message)

    async def handle_inbound(
        self,
        channel_name: str,
        company_id: uuid.UUID,
        sender_agent_id: uuid.UUID,
        content: str,
        message_type: str = "notification",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[Message]:
        """Handle an inbound message from an external channel.

        Converts an external message into an internal Message object
        and optionally persists it.

        Args:
            channel_name: Name of the channel the message came from.
            company_id: Company scope for the inbound message.
            sender_agent_id: Agent ID to attribute the message to.
            content: Message content from the external channel.
            message_type: Type of the internal message. Defaults to 'notification'.
            metadata: Optional additional metadata.

        Returns:
            The created internal Message, or None if the channel is not registered.
        """
        if channel_name not in self._channels:
            return None

        channel_meta = metadata or {}
        channel_meta["source_channel"] = channel_name

        msg = Message(
            id=uuid.uuid4(),
            company_id=company_id,
            sender_agent_id=sender_agent_id,
            recipient_agent_id=None,
            group_id=None,
            message_type=message_type,
            priority="normal",
            content=content,
            msg_metadata=channel_meta,
            correlation_id=str(uuid.uuid4()),
            delivered=True,
            delivery_route="direct",
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )

        if self.db is not None:
            self.db.add(msg)
            await self.db.commit()

        return msg

    def get_channel(self, name: str) -> Optional[ChannelInterface]:
        """Retrieve a registered channel by name.

        Args:
            name: The channel name.

        Returns:
            The channel implementation, or None if not found.
        """
        return self._channels.get(name)

    def list_channels(self) -> list[str]:
        """List all registered channel names.

        Returns:
            List of registered channel names.
        """
        return list(self._channels.keys())
