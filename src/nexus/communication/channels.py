"""External channel integration for routing messages to/from external platforms.

Provides a Protocol-based interface for channel implementations (Slack, Discord,
Webhooks) and a ChannelRouter that handles outbound message routing and inbound
message conversion. Outbound sends perform real HTTP calls; failed deliveries
are enqueued for retry via the file-backed WebhookDeliveryQueue. Inbound
messages arrive through the webhook server / trigger system, not receive().
"""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from nexus.models.communication import Message

logger = logging.getLogger(__name__)

_RETRY_QUEUE: Optional["WebhookDeliveryQueue"] = None


def _get_retry_queue():
    """Lazily construct the file-backed retry queue under the data dir."""
    global _RETRY_QUEUE
    if _RETRY_QUEUE is not None:
        return _RETRY_QUEUE
    try:
        from nexus.communication.webhook_queue import WebhookDeliveryQueue

        base = Path("./data")
        try:
            from nexus.config import settings

            base = Path(settings.data_dir)
        except Exception:
            pass
        _RETRY_QUEUE = WebhookDeliveryQueue(base / "channel_deliveries.json")
    except Exception as exc:
        logger.warning("Retry queue unavailable: %s", exc)
        return None
    return _RETRY_QUEUE


def _sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 signature (hex) of the exact bytes sent on the wire."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _message_payload(message: Message) -> dict[str, Any]:
    """Serialize a Message into a JSON-safe webhook payload."""
    return {
        "id": str(message.id),
        "sender_agent_id": str(message.sender_agent_id),
        "recipient_agent_id": (
            str(message.recipient_agent_id) if message.recipient_agent_id else None
        ),
        "message_type": message.message_type,
        "priority": message.priority,
        "content": message.content,
    }


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
    """Slack channel sending messages through a Slack incoming webhook URL.

    Inbound messages are not polled here — they arrive via the webhook server.
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
        """Post a message to Slack via the configured incoming webhook.

        Args:
            message: The Message object to send.

        Returns:
            True if Slack accepted the POST, False otherwise.
        """
        if not self.webhook_url:
            logger.warning("SlackChannel %s has no webhook_url configured", self.channel_name)
            return False
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.webhook_url,
                    json={"text": f"[{message.message_type}] {message.content}"},
                )
            if 200 <= response.status_code < 300:
                return True
            logger.warning(
                "Slack delivery to %s failed: HTTP %s", self.channel_name, response.status_code
            )
            return False
        except Exception as exc:
            logger.warning("Slack delivery failed: %s", exc)
            return False

    async def receive(self) -> Optional[Message]:
        """Receive the next message from the Slack channel inbox.

        Returns:
            A Message object if available, None otherwise.
        """
        if self._inbox:
            return self._inbox.pop(0)
        return None


class DiscordChannel:
    """Discord channel posting messages through the bot-token REST API.

    Outbound-only here: inbound events require the Gateway, which is handled
    separately (not part of the request path).
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
        """Post a message to the configured Discord channel via bot REST API.

        Args:
            message: The Message object to send.

        Returns:
            True if Discord accepted the POST, False otherwise.
        """
        if not self.bot_token or not self.channel_id:
            logger.warning("DiscordChannel missing bot_token or channel_id")
            return False
        try:
            import httpx

            url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    json={"content": message.content[:2000]},
                )
            if 200 <= response.status_code < 300:
                return True
            logger.warning("Discord delivery failed: HTTP %s", response.status_code)
            return False
        except Exception as exc:
            logger.warning("Discord delivery failed: %s", exc)
            return False

    async def receive(self) -> Optional[Message]:
        """Receive the next message from the Discord channel inbox.

        Returns:
            A Message object if available, None otherwise.
        """
        if self._inbox:
            return self._inbox.pop(0)
        return None


class WebhookChannel:
    """Generic outbound webhook channel with HMAC-SHA256 request signing.

    Deliveries are signed with X-Nexus-Signature over the exact body bytes and
    retried (with backoff, then dead-letter) via WebhookDeliveryQueue when the
    endpoint is unreachable or rejects the POST.
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
        """POST the message to the endpoint, signed when a secret is set.

        Args:
            message: The Message object to send.

        Returns:
            True on a 2xx response; False otherwise (failed deliveries are
            enqueued for retry).
        """
        if not self.endpoint_url:
            logger.warning("WebhookChannel has no endpoint_url configured")
            return False

        payload = _message_payload(message)
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["X-Nexus-Signature"] = _sign_payload(self.secret, body)

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.endpoint_url, content=body, headers=headers
                )
            if 200 <= response.status_code < 300:
                return True
            error = f"HTTP {response.status_code}"
        except Exception as exc:
            error = str(exc)
            logger.warning("Webhook delivery to %s failed: %s", self.endpoint_url, exc)

        queue = _get_retry_queue()
        if queue is not None:
            from nexus.communication.webhook_queue import WebhookDelivery

            queue.enqueue(
                WebhookDelivery(
                    id=f"{message.id}-{uuid.uuid4().hex[:8]}",
                    url=self.endpoint_url,
                    payload=payload,
                    headers=headers,
                    created_at=datetime.now(timezone.utc),
                    status="pending",
                    last_error=error,
                )
            )
        return False

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
        from nexus.observability.tracing import get_tracer

        tracer = get_tracer("nexus.channels")
        with tracer.start_as_current_span("route_outbound") as span:
            key = route_key or message.priority or message.message_type
            span.set_attribute("route_key", str(key))
            channel_name = self._routes.get(key)

            if channel_name is None:
                channel_name = self._routes.get(message.message_type)

            if channel_name is None:
                span.set_attribute("routed", False)
                return False

            channel = self._channels.get(channel_name)
            if channel is None:
                span.set_attribute("routed", False)
                return False

            span.set_attribute("channel", channel_name)
            result = await channel.send(message)
            span.set_attribute("delivered", result)
            return result

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
