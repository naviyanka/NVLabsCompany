"""WebSocket connection manager for real-time client communication.

Manages active WebSocket connections keyed by client_id, supports personal
messaging, broadcasting, and channel-based subscriptions.
"""

import json
import logging
import uuid
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and channel subscriptions.

    Tracks active connections by client_id (UUID string), provides methods
    for sending personal messages, broadcasting to all connections, and
    channel-based pub/sub for scoped delivery. Supports tenant isolation
    via company_id association per connection.

    All methods are async to support non-blocking I/O.

    Attributes:
        _connections: Mapping of client_id to active WebSocket connection.
        _channels: Mapping of channel name to set of subscribed client_ids.
        _company_ids: Mapping of client_id to associated company UUID.
    """

    def __init__(self) -> None:
        """Initialize the WebSocket manager with empty connection tracking."""
        self._connections: dict[str, WebSocket] = {}
        self._channels: dict[str, set[str]] = {}
        self._company_ids: dict[str, uuid.UUID] = {}

    @property
    def active_connections(self) -> dict[str, WebSocket]:
        """Return the current active connections mapping."""
        return self._connections.copy()

    @property
    def connection_count(self) -> int:
        """Return the number of active connections."""
        return len(self._connections)

    async def connect(
        self, client_id: str, websocket: WebSocket, company_id: uuid.UUID | None = None
    ) -> None:
        """Register a new WebSocket connection for a client.

        If the client already has an active connection, it is replaced.

        Args:
            client_id: UUID string identifying the client.
            websocket: The FastAPI WebSocket instance.
            company_id: Optional company UUID for tenant isolation.
        """
        self._connections[client_id] = websocket
        if company_id is not None:
            self._company_ids[client_id] = company_id
        logger.info("WebSocket connected: client_id=%s", client_id)

    async def disconnect(self, client_id: str) -> None:
        """Remove a client connection and clean up channel subscriptions.

        If the underlying WebSocket connection is still open, it is closed
        gracefully before removing tracking state. This handles the proactive
        disconnect case (e.g., auth revocation, eviction) where the server
        initiates the disconnection.

        Args:
            client_id: UUID string identifying the client to disconnect.
        """
        websocket = self._connections.pop(client_id, None)
        self._company_ids.pop(client_id, None)
        if websocket is not None:
            try:
                await websocket.close()
            except Exception:
                # Connection may already be closed by the client
                pass
        # Remove from all channels
        for subscribers in self._channels.values():
            subscribers.discard(client_id)
        logger.info("WebSocket disconnected: client_id=%s", client_id)

    async def send_personal(self, client_id: str, data: dict[str, Any]) -> bool:
        """Send a JSON message to a specific client.

        Args:
            client_id: Target client UUID string.
            data: Dictionary payload to send as JSON.

        Returns:
            True if the message was sent, False if client not connected.
        """
        websocket = self._connections.get(client_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(data)
            return True
        except Exception:
            logger.warning("Failed to send to client_id=%s, removing", client_id)
            await self.disconnect(client_id)
            return False

    async def broadcast(self, data: dict[str, Any]) -> int:
        """Broadcast a JSON message to all connected clients.

        Args:
            data: Dictionary payload to send as JSON.

        Returns:
            Number of clients the message was successfully sent to.
        """
        sent_count = 0
        disconnected: list[str] = []
        for client_id, websocket in list(self._connections.items()):
            try:
                await websocket.send_json(data)
                sent_count += 1
            except Exception:
                disconnected.append(client_id)
        for client_id in disconnected:
            await self.disconnect(client_id)
        return sent_count

    async def subscribe_channel(self, client_id: str, channel: str) -> None:
        """Subscribe a client to a named channel.

        Args:
            client_id: UUID string of the subscribing client.
            channel: Channel name to subscribe to.
        """
        if channel not in self._channels:
            self._channels[channel] = set()
        self._channels[channel].add(client_id)
        logger.debug("Client %s subscribed to channel %s", client_id, channel)

    async def unsubscribe_channel(self, client_id: str, channel: str) -> None:
        """Unsubscribe a client from a named channel.

        Args:
            client_id: UUID string of the client.
            channel: Channel name to unsubscribe from.
        """
        subscribers = self._channels.get(channel)
        if subscribers:
            subscribers.discard(client_id)
            if not subscribers:
                del self._channels[channel]
        logger.debug("Client %s unsubscribed from channel %s", client_id, channel)

    async def broadcast_to_channel(self, channel: str, data: dict[str, Any]) -> int:
        """Broadcast a JSON message to all clients subscribed to a channel.

        Args:
            channel: Target channel name.
            data: Dictionary payload to send as JSON.

        Returns:
            Number of clients the message was successfully sent to.
        """
        subscribers = self._channels.get(channel, set())
        sent_count = 0
        disconnected: list[str] = []
        for client_id in list(subscribers):
            websocket = self._connections.get(client_id)
            if websocket is None:
                continue
            try:
                await websocket.send_json(data)
                sent_count += 1
            except Exception:
                disconnected.append(client_id)
        for client_id in disconnected:
            await self.disconnect(client_id)
        return sent_count

    def get_channel_subscribers(self, channel: str) -> set[str]:
        """Get the set of client_ids subscribed to a channel.

        Args:
            channel: Channel name to query.

        Returns:
            Set of client_id strings subscribed to the channel.
        """
        return self._channels.get(channel, set()).copy()

    async def broadcast_to_company(
        self, company_id: uuid.UUID, data: dict[str, Any]
    ) -> int:
        """Broadcast a JSON message to all clients belonging to a company.

        Only sends to connections that were registered with the matching
        company_id, enforcing tenant isolation at the WebSocket layer.

        Args:
            company_id: Target company UUID for tenant-scoped delivery.
            data: Dictionary payload to send as JSON.

        Returns:
            Number of clients the message was successfully sent to.
        """
        sent_count = 0
        disconnected: list[str] = []
        for client_id, cid in list(self._company_ids.items()):
            if cid != company_id:
                continue
            websocket = self._connections.get(client_id)
            if websocket is None:
                continue
            try:
                await websocket.send_json(data)
                sent_count += 1
            except Exception:
                disconnected.append(client_id)
        for client_id in disconnected:
            await self.disconnect(client_id)
        return sent_count

    def get_client_company(self, client_id: str) -> uuid.UUID | None:
        """Get the company UUID associated with a client connection.

        Args:
            client_id: UUID string of the client.

        Returns:
            The company UUID if set, None otherwise.
        """
        return self._company_ids.get(client_id)
