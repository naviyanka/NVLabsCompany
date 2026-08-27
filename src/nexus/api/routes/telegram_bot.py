"""Telegram remote control bot endpoint.

Receives Telegram Bot API webhook updates and provides operator commands:
  /status   — system operational state summary
  /agents   — list active agents
  /task <desc> — create a new task
  /help     — list available commands

Requires TELEGRAM_BOT_TOKEN env var. Set webhook via:
  curl https://api.telegram.org/bot<TOKEN>/setWebhook?url=<BASE_URL>/api/v1/channels/telegram/webhook
"""

import logging
import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["channels"])

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


async def _reply(chat_id: str, text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return
    url = _TELEGRAM_API.format(token=token)
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


async def _handle_status(chat_id: str) -> None:
    try:
        from nexus.api.routes.system import get_system_health
        health = await get_system_health()
        lines = [
            "*NEXUS Status*",
            f"State: `{health.get('status', 'unknown')}`",
            f"Agents: `{health.get('active_agents', '?')}`",
            f"Uptime: `{health.get('uptime', '?')}`",
        ]
        await _reply(chat_id, "\n".join(lines))
    except Exception as exc:
        await _reply(chat_id, f"Error fetching status: {exc}")


async def _telegram_company_id(db: Any) -> uuid.UUID:
    """The tenant the bot acts on.

    ``TELEGRAM_BOT_TOKEN`` names a bot, not a company, so the webhook has no
    tenant in its payload. Resolving it the same way first-run setup does keeps
    the bot in one company instead of reading across all of them — and replaces
    the hardcoded seeded-development UUID ``/task`` used to write, which points
    at a row that does not exist on a deployment that was never seeded.
    """
    from nexus.auth.users import pick_setup_company

    return (await pick_setup_company(db)).id


async def _handle_agents(chat_id: str) -> None:
    try:
        from nexus.database import async_session_factory
        from nexus.models.agent import Agent
        from sqlmodel import select

        async with async_session_factory() as db:
            company_id = await _telegram_company_id(db)
            result = await db.execute(
                select(Agent)
                .where(Agent.company_id == company_id, Agent.status == "active")
                .limit(20)
            )
            agents = result.scalars().all()

        if not agents:
            await _reply(chat_id, "No active agents.")
            return

        lines = ["*Active Agents*"]
        for a in agents:
            lines.append(f"• `{a.name}` — {a.role or 'agent'}")
        await _reply(chat_id, "\n".join(lines))
    except Exception as exc:
        await _reply(chat_id, f"Error: {exc}")


async def _handle_task(chat_id: str, description: str) -> None:
    if not description.strip():
        await _reply(chat_id, "Usage: /task <description>")
        return
    try:
        from nexus.database import async_session_factory
        from nexus.models.task import Task

        async with async_session_factory() as db:
            task = Task(
                company_id=await _telegram_company_id(db),
                title=description[:200],
                description=f"Created via Telegram remote control",
                status="pending",
                priority=1,
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
        await _reply(chat_id, f"Task created: `{task.id}`\n_{description[:100]}_")
    except Exception as exc:
        await _reply(chat_id, f"Failed to create task: {exc}")


_HELP_TEXT = """*NEXUS Telegram Remote Control*

/status — System operational state
/agents — List active agents
/task <desc> — Create a new task
/help — Show this message"""


@router.post("/api/v1/channels/telegram/webhook")
async def telegram_webhook(request: Request) -> Any:
    body = await request.json()

    message = body.get("message", {})
    text = message.get("text", "")
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if not chat_id or not text:
        return JSONResponse({"ok": True})

    command = text.strip().split()[0].lower()
    args = text.strip()[len(command):].strip()

    if command == "/status":
        await _handle_status(chat_id)
    elif command == "/agents":
        await _handle_agents(chat_id)
    elif command == "/task":
        await _handle_task(chat_id, args)
    elif command in ("/help", "/start"):
        await _reply(chat_id, _HELP_TEXT)
    else:
        await _reply(chat_id, f"Unknown command: `{command}`\nType /help for available commands.")

    return JSONResponse({"ok": True})
