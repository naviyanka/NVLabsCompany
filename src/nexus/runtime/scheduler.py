"""Background Scheduler — fires cron/schedule triggers at their appointed times.

Runs as a background asyncio task during the app lifespan. Every tick (default 60s),
queries the DB for active triggers whose `next_fire_at` is in the past, fires them
by calling the assigned agent's LLM adapter, records the execution, and calculates
the next fire time.

This is the only trigger dispatcher (ADR 0001, arch_guard rule R2). The
``triggers`` table is the only registry, so a trigger created through the API
survives a restart.

Supports trigger_type:
- "cron": config.cron_expression (e.g. "*/5 * * * *"), or discrete
  config.minute / config.hour fields — fires every match
- "interval": config.seconds / config.minutes / config.hours — fires repeatedly
- "on_schedule" / "once": config.scheduled_at or config.fire_at (ISO datetime)
  — fires once, then deactivates
- "webhook": outbound POST to config.webhook_url — fires once per fire time

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


def _interval_seconds(config: dict[str, Any]) -> int:
    """Total interval length in seconds from `seconds`/`minutes`/`hours` config."""
    seconds = config.get("seconds", 0) or 0
    minutes = config.get("minutes", 0) or 0
    hours = config.get("hours", 0) or 0
    return int(seconds) + int(minutes) * 60 + int(hours) * 3600


def _next_cron_field_match(config: dict[str, Any], after: datetime) -> datetime:
    """Next fire time from discrete cron fields (`minute`, `hour`).

    Each field is either "*" (any) or an integer. Searches minute by minute up
    to 48 hours ahead, then falls back to one hour out.
    """
    minute = config.get("minute", "*")
    hour = config.get("hour", "*")

    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(48 * 60):
        try:
            minute_match = minute == "*" or candidate.minute == int(minute)
            hour_match = hour == "*" or candidate.hour == int(hour)
        except (TypeError, ValueError):
            break
        if minute_match and hour_match:
            return candidate
        candidate += timedelta(minutes=1)

    return after + timedelta(hours=1)


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO datetime from config into a naive UTC datetime."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def compute_next_fire(
    trigger_type: str, config: dict[str, Any] | None, after: datetime
) -> datetime | None:
    """Next fire time for a trigger, or None when it should not fire again.

    Args:
        trigger_type: cron, interval, once, on_schedule, or webhook.
        config: Type-specific configuration.
        after: Naive UTC datetime to compute from.

    Returns:
        The next naive UTC fire time, or None for one-shot triggers that have
        already fired.
    """
    config = config or {}

    if trigger_type == "cron":
        cron_expression = config.get("cron_expression")
        if cron_expression:
            return _parse_cron_next_fire(str(cron_expression), after)
        return _next_cron_field_match(config, after)

    if trigger_type == "interval":
        return after + timedelta(seconds=max(1, _interval_seconds(config)))

    if trigger_type in ("once", "on_schedule"):
        # Only the first schedule has a fire time; afterwards the trigger is done.
        scheduled = _parse_datetime(config.get("scheduled_at") or config.get("fire_at"))
        if scheduled and scheduled > after:
            return scheduled
        return None

    # webhook and event-driven types do not auto-repeat
    return None


async def _tick(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Single scheduler tick: find and fire due triggers."""
    from nexus.models.trigger import Trigger, TriggerExecution
    from nexus.models.agent import Agent
    from nexus.runtime.redis_utils import try_acquire_leader

    # Leader election: only the leader instance processes triggers
    if not await try_acquire_leader("scheduler", _instance_id):
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with session_factory() as db:
        # Find active triggers that are due
        stmt = (
            select(Trigger)
            .where(
                Trigger.is_active == True,  # noqa: E712
                Trigger.trigger_type.in_(
                    ["cron", "interval", "once", "on_schedule", "webhook"]
                ),
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
    """Fire a single trigger: call the agent, send webhook, or both."""
    from nexus.models.trigger import TriggerExecution
    from nexus.models.agent import Agent

    config = trigger.config or {}

    # Webhook triggers: make outbound HTTP POST
    if trigger.trigger_type == "webhook":
        webhook_url = config.get("webhook_url", "")
        if webhook_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30.0) as client:
                    payload = {
                        "trigger_id": str(trigger.id),
                        "trigger_name": trigger.name,
                        "company_id": str(trigger.company_id),
                        "fired_at": now.isoformat(),
                        "config": {k: v for k, v in config.items() if k != "webhook_url"},
                    }
                    response = await client.post(webhook_url, json=payload)
                    execution = TriggerExecution(
                        trigger_id=trigger.id,
                        company_id=trigger.company_id,
                        status="success" if response.status_code < 400 else "failed",
                    )
                    db.add(execution)
            except Exception as e:
                logger.warning("Webhook delivery failed for trigger %s: %s", trigger.id, e)
                execution = TriggerExecution(
                    trigger_id=trigger.id, company_id=trigger.company_id, status="failed",
                )
                db.add(execution)
        trigger.last_fired_at = now
        trigger.next_fire_at = compute_next_fire(trigger.trigger_type, config, now)
        db.add(trigger)
        return

    # Agent-based triggers: load agent and call LLM
    from nexus.api.routes.chat import _build_system_prompt, _call_llm

    stmt = select(Agent).where(Agent.id == trigger.agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if not agent:
        logger.warning("Trigger %s: agent %s not found, deactivating", trigger.id, trigger.agent_id)
        trigger.is_active = False
        db.add(trigger)
        return

    prompt = config.get("prompt", config.get("message", f"Execute scheduled task: {trigger.name}"))
    system_prompt = _build_system_prompt(agent)
    response_text, model_used, tokens_used = await _call_llm(agent, system_prompt, prompt, [])

    execution = TriggerExecution(
        trigger_id=trigger.id,
        company_id=trigger.company_id,
        status="success",
        result={"output": response_text[:5000], "model": model_used, "tokens": tokens_used},
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(execution)

    trigger.last_fired_at = now
    trigger.next_fire_at = compute_next_fire(trigger.trigger_type, config, now)
    if trigger.next_fire_at is None:
        trigger.is_active = False

    db.add(trigger)
    logger.info("Fired trigger '%s' → agent %s (%d tokens)", trigger.name, agent.name, tokens_used)


async def _scheduler_loop(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Main scheduler loop — ticks every TICK_INTERVAL seconds.

    With multiple replicas, only the lease leader fires triggers; followers
    keep looping cheaply so they can take over when the lease expires.
    """
    global _running
    from nexus.governance.leader_election import is_leader

    logger.info("Scheduler started (tick interval: %ds)", TICK_INTERVAL)
    while _running:
        try:
            if await is_leader("scheduler"):
                await _tick(session_factory)
        except Exception as e:
            logger.error("Scheduler tick error: %s", e)

        # The watchdog patrol rides this tick rather than running a loop of its
        # own, so there is one periodic driver in the process.
        try:
            from nexus.runtime.watchdog_service import patrol_once

            if await is_leader("watchdog"):
                await patrol_once(session_factory)
        except Exception as e:
            logger.error("Watchdog patrol error: %s", e)

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
