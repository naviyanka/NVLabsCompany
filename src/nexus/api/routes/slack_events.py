"""Slack Events API inbound endpoint + Email notification channel.

W-04 inbound: handles Slack's URL verification challenge and app_mention events
(creating tasks from mentions). Email channel sends via SMTP.
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["channels"])

logger = logging.getLogger(__name__)


@router.post("/api/v1/channels/slack/events")
async def slack_events(request: Request) -> Any:
    """Handle Slack Events API callbacks.

    Supports:
    - url_verification challenge (required by Slack on endpoint registration)
    - event_callback with app_mention type → creates a Task for the company
    """
    body = await request.json()
    event_type = body.get("type")

    if event_type == "url_verification":
        return JSONResponse({"challenge": body.get("challenge", "")})

    if event_type == "event_callback":
        event = body.get("event", {})
        if event.get("type") == "app_mention":
            text = event.get("text", "")
            user = event.get("user", "unknown")
            channel = event.get("channel", "")
            try:
                from nexus.database import async_session_factory
                from nexus.models.task import Task

                async with async_session_factory() as db:
                    task = Task(
                        company_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
                        title=f"Slack mention from {user}",
                        description=f"Channel: {channel}\n\n{text}",
                        status="pending",
                        priority=1,
                    )
                    db.add(task)
                    await db.commit()
                logger.info("Created task from Slack mention by %s in %s", user, channel)
            except Exception as exc:
                logger.warning("Failed to create task from Slack mention: %s", exc)

    return JSONResponse({"ok": True})
