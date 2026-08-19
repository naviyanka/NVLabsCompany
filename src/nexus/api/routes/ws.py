"""WebSocket endpoint for real-time client communication.

Provides a WebSocket connection endpoint at /ws/{client_id} that accepts
connections, registers them with the WebSocketManager, and processes
incoming JSON commands for channel subscriptions.
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from nexus.realtime.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

# Shared WebSocket manager instance
manager = WebSocketManager()


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str) -> None:
    """Accept a WebSocket connection and handle real-time communication.

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
    await websocket.accept()
    await manager.connect(client_id, websocket)

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
