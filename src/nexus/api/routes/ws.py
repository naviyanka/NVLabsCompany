"""WebSocket endpoint for real-time client communication.

Provides a WebSocket connection endpoint at /ws/{client_id} that accepts
connections, registers them with the WebSocketManager, and processes
incoming JSON commands for channel subscriptions.

Authentication is handled via a query parameter (token) containing the
company UUID, since WebSocket handshakes do not reliably support custom
headers in all client implementations.
"""

import json
import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from nexus.realtime.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

# Shared WebSocket manager instance
manager = WebSocketManager()


async def _authenticate_websocket(
    websocket: WebSocket, company_id: str | None
) -> uuid.UUID | None:
    """Validate the company_id query parameter for WebSocket auth.

    Args:
        websocket: The WebSocket connection to close on failure.
        company_id: The company UUID string from query parameters.

    Returns:
        Parsed UUID if valid, None if authentication failed (socket closed).
    """
    if not company_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    try:
        return uuid.UUID(company_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str,
    company_id: str | None = Query(None, alias="company_id"),
) -> None:
    """Accept a WebSocket connection and handle real-time communication.

    Requires a company_id query parameter for authentication and tenant
    isolation. The company_id must be a valid UUID. If missing or invalid,
    the connection is closed with policy violation code (1008).

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
        company_id: Company UUID string for tenant isolation (query param).
    """
    # Authenticate via query parameter
    validated_company_id = await _authenticate_websocket(websocket, company_id)
    if validated_company_id is None:
        return

    await websocket.accept()
    await manager.connect(client_id, websocket, validated_company_id)

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
