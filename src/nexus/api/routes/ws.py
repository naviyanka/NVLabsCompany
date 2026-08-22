"""WebSocket endpoint for real-time client communication.

Provides a WebSocket connection endpoint at /ws/{client_id} that accepts
connections, registers them with the WebSocketManager, and processes
incoming JSON commands for channel subscriptions.

Authentication comes from the same credentials as the REST API. Browsers cannot
set headers on a WebSocket handshake, but they *do* send cookies, so the session
cookie carries the identity; non-browser clients can still use an API key in the
``Authorization`` header. :class:`~nexus.auth.middleware.AuthenticationMiddleware`
resolves either one before the route runs and also rejects handshakes from an
origin outside the allowlist, which is what stops a third-party page from
opening a socket with the visitor's ambient cookie.

The company is taken from that principal and never from the query string. It
used to be a ``company_id`` query parameter, which meant anyone who could guess
a UUID could stream another tenant's events.
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from nexus.auth.middleware import get_principal_from_scope
from nexus.auth.principal import Principal
from nexus.realtime.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

# Shared WebSocket manager instance
manager = WebSocketManager()


async def _authenticate_websocket(websocket: WebSocket) -> Principal | None:
    """Return the handshake's principal, closing the socket if there is none.

    Closing with 1008 rather than accepting-then-closing keeps an unauthenticated
    client from ever reaching the receive loop. The client sees a failed handshake,
    which is the signal the dashboard uses to stop retrying and redirect to login.
    """
    principal = get_principal_from_scope(websocket.scope)
    if principal is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    return principal


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str,
) -> None:
    """Accept a WebSocket connection and handle real-time communication.

    The caller must present a session cookie or an API key; the connection is
    scoped to that credential's company. An unauthenticated handshake is closed
    with policy violation code (1008).

    Registers the client with the WebSocketManager, then enters a loop
    listening for JSON messages. Supports the following commands:

    - {"action": "subscribe", "channel": "<name>"} - Subscribe to a channel
    - {"action": "unsubscribe", "channel": "<name>"} - Unsubscribe from a channel
    - {"action": "broadcast", "data": {...}} - Broadcast data to all clients

    Any other message is echoed back to the sender as acknowledgement.
    Handles WebSocketDisconnect gracefully by cleaning up the connection.

    Args:
        websocket: The FastAPI WebSocket connection.
        client_id: UUID string identifying the connecting client.
    """
    principal = await _authenticate_websocket(websocket)
    if principal is None:
        return

    await websocket.accept()
    await manager.connect(client_id, websocket, principal.company_id)

    try:
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "invalid_json"})
                continue

            action = data.get("action")

            if action == "subscribe":
                channel = data.get("channel")
                if channel:
                    await manager.subscribe_channel(client_id, channel)
                    await websocket.send_json(
                        {"status": "subscribed", "channel": channel}
                    )
                else:
                    await websocket.send_json({"error": "missing_channel"})

            elif action == "unsubscribe":
                channel = data.get("channel")
                if channel:
                    await manager.unsubscribe_channel(client_id, channel)
                    await websocket.send_json(
                        {"status": "unsubscribed", "channel": channel}
                    )
                else:
                    await websocket.send_json({"error": "missing_channel"})

            elif action == "broadcast":
                broadcast_data = data.get("data", {})
                count = await manager.broadcast(broadcast_data)
                await websocket.send_json(
                    {"status": "broadcast_sent", "recipients": count}
                )

            else:
                # Echo back as acknowledgement
                await websocket.send_json({"status": "received", "data": data})

    except WebSocketDisconnect:
        await manager.disconnect(client_id)
        logger.info("Client %s disconnected", client_id)
