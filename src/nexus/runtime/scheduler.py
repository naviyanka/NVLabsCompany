"""Background Scheduler — fires cron/schedule triggers at their appointed times.

Runs as a background asyncio task during the app lifespan. Every tick (default 60s),
queries the DB for active triggers whose `next_fire_at` is in the past, fires them
by calling the assigned agent's LLM adapter, records the execution, and calculates
the next fire time.

Supports trigger_type:
- "cron": config.cron_expression (e.g. "*/5 * * * *") — fires every match
- "on_schedule": config.scheduled_at (ISO datetime) — fires once

Usage:
    from nexus.runtime.scheduler import start_scheduler, stop_scheduler

    # In app lifespan:
    await start_scheduler(session_factory)
    yield
    await stop_scheduler()
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task[None] | None = None
_running = False
_instance_id = f"scheduler-{uuid.uuid4().hex[:8]}"

# Default tick interval in seconds
TICK_INTERVAL = 60


def _parse_cron_next_fire(cron_expression: str, after: datetime) -> datetime | None:
    """Calculate the next fire time from a simplified cron expression.

    Supports a subset of cron: "*/N * * * *" (every N minutes),
    "0 */N * * *" (every N hours), "0 0 * * *" (daily at midnight).
    Falls back to 1-hour intervals for unsupported expressions.
    """
    parts = cron_expression.strip().split()
    if len(parts) < 5:
        return after + timedelta(hours=1)

    minute_part = parts[0]
    hour_part = parts[1]

    # Every N minutes: */N * * * *
    if minute_part.startswith("*/"):
        try:
            interval = int(minute_part[2:])
            return after + timedelta(minutes=max(1, interval))
        except ValueError:
            pass

    # Every N hours: 0 */N * * *
    if hour_part.startswith("*/"):
        try:
            interval = int(hour_part[2:])
            return after + timedelta(hours=max(1, interval))
        except ValueError:
            pass

    # Daily: 0 0 * * *
    if minute_part == "0" and hour_part == "0":
        next_day = after.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return next_day

    # Default fallback: 1 hour
    return after + timedelta(hours=1)


async def _tick(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Single scheduler tick: find and fire due triggers."""
    from nexus.models.trigger import Trigger, TriggerExecution
    from nexus.models.agent import Agent
    from nexus.runtime.redis_utils import try_acquire_leader

    # Leader election: only the leader instance processes triggers
    if not await try_acquire_leader("scheduler", _instance_id):
        return

    now = datetime.now(timezone.utc)

    async with session_factory() as db:
        # Find active triggers that are due
        stmt = (
            select(Trigger)
            .where(
                Trigger.is_active == True,  # noqa: E712
                Trigger.trigger_type.in_(["cron", "on_schedule"]),
                Trigger.next_fire_at <= now,
            )
            .limit(20)  # Process up to 20 per tick to avoid long locks
        )
        result = await db.execute(stmt)
        due_triggers = list(result.scalars().all())

        if not due_triggers:
            return

        logger.info("Scheduler tick: %d triggers due", len(due_triggers))

        for trigger in due_triggers:
            try:
                await _fire_trigger(db, trigger, now)
            except Exception as e:
                logger.error("Trigger %s fire failed: %s", trigger.id, e)

        await db.commit()


async def _fire_trigger(db: AsyncSession, trigger: Any, now: datetime) -> None:
    """Fire a single trigger: call the agent and record execution."""
    from nexus.models.trigger import TriggerExecution
    from nexus.models.agent import Agent
    from nexus.api.routes.chat import _build_system_prompt, _call_llm

    # Load the assigned agent
    stmt = select(Agent).where(Agent.id == trigger.agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if not agent:
        logger.warning("Trigger %s: agent %s not found, deactivating", trigger.id, trigger.agent_id)
        trigger.is_active = False
        db.add(trigger)
        return

    # Build the prompt from trigger config
    config = trigger.config or {}
    prompt = config.get("prompt", config.get("message", f"Execute scheduled task: {trigger.name}"))

    # Call the agent
    system_prompt = _build_system_prompt(agent)
    response_text, model_used, tokens_used = await _call_llm(
        agent, system_prompt, prompt, []
    )

    # Record the execution
    execution = TriggerExecution(
        trigger_id=trigger.id,
        company_id=trigger.company_id,
        status="success",
        result_text=response_text[:5000] if hasattr(TriggerExecution, "result_text") else None,
    )
    db.add(execution)

    # Update trigger timing
    trigger.last_fired_at = now
    if trigger.trigger_type == "cron":
        cron_expr = config.get("cron_expression", "0 * * * *")
        trigger.next_fire_at = _parse_cron_next_fire(cron_expr, now)
    elif trigger.trigger_type == "on_schedule":
        # One-shot: deactivate after firing
        trigger.is_active = False
        trigger.next_fire_at = None

    db.add(trigger)
    logger.info(
        "Fired trigger '%s' → agent %s (%d tokens)",
        trigger.name, agent.name, tokens_used,
    )


async def _scheduler_loop(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Main scheduler loop — ticks every TICK_INTERVAL seconds."""
    global _running
    logger.info("Scheduler started (tick interval: %ds)", TICK_INTERVAL)
    while _running:
        try:
            await _tick(session_factory)
        except Exception as e:
            logger.error("Scheduler tick error: %s", e)
        await asyncio.sleep(TICK_INTERVAL)
    logger.info("Scheduler stopped")


async def start_scheduler(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Start the background scheduler task."""
    global _scheduler_task, _running
    if _scheduler_task is not None:
        return  # Already running
    _running = True
    _scheduler_task = asyncio.create_task(_scheduler_loop(session_factory))


async def stop_scheduler() -> None:
    """Stop the background scheduler task."""
    global _scheduler_task, _running
    _running = False
    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None
