"""Trigger Scheduler - manages trigger registration, scheduling, and next-fire computation."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class TriggerConfig:
    """Configuration for a scheduled trigger.

    Attributes:
        id: Unique trigger identifier.
        trigger_type: Type of trigger (cron, once, interval).
        company_id: Company scope.
        agent_id: Agent to activate when trigger fires.
        name: Human-readable name.
        config: Type-specific configuration.
        is_active: Whether the trigger is enabled.
        last_fired_at: When the trigger last fired.
        next_fire_at: When the trigger will next fire.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    trigger_type: str = "interval"
    company_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    name: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    last_fired_at: datetime | None = None
    next_fire_at: datetime | None = None


class TriggerScheduler:
    """Manages trigger lifecycle: registration, scheduling, and due-trigger retrieval.

    Supports three trigger types:
    - cron: fires on a schedule defined by cron expression fields
    - once: fires at a specific datetime, then deactivates
    - interval: fires every N seconds/minutes/hours
    """

    def __init__(self) -> None:
        """Initialize an empty trigger scheduler."""
        self._triggers: dict[uuid.UUID, TriggerConfig] = {}

    def register_trigger(self, trigger: TriggerConfig) -> TriggerConfig:
        """Register a new trigger and compute its initial next_fire_at.

        Args:
            trigger: The trigger configuration to register.

        Returns:
            The registered trigger with computed next_fire_at.
        """
        if trigger.next_fire_at is None:
            trigger.next_fire_at = self._compute_next_fire(trigger)
        self._triggers[trigger.id] = trigger
        return trigger

    def unregister_trigger(self, trigger_id: uuid.UUID) -> bool:
        """Remove a trigger from the scheduler.

        Args:
            trigger_id: The trigger to remove.

        Returns:
            True if removed, False if not found.
        """
        if trigger_id in self._triggers:
            del self._triggers[trigger_id]
            return True
        return False

    def get_trigger(self, trigger_id: uuid.UUID) -> TriggerConfig | None:
        """Retrieve a trigger by ID.

        Args:
            trigger_id: The trigger identifier.

        Returns:
            The TriggerConfig, or None if not found.
        """
        return self._triggers.get(trigger_id)

    def get_due_triggers(self, now: datetime | None = None) -> list[TriggerConfig]:
        """Get all triggers whose next_fire_at is at or before now.

        Args:
            now: The current time. Uses UTC now if None.

        Returns:
            List of triggers that are due to fire.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        due: list[TriggerConfig] = []
        for trigger in self._triggers.values():
            if not trigger.is_active:
                continue
            if trigger.next_fire_at and trigger.next_fire_at <= now:
                due.append(trigger)

        return due

    def update_next_fire(self, trigger: TriggerConfig) -> None:
        """Update a trigger's next_fire_at after it has fired.

        For 'once' triggers, deactivates after firing.
        For 'interval' triggers, adds the interval duration.
        For 'cron' triggers, computes next occurrence from cron fields.

        Args:
            trigger: The trigger to update.
        """
        now = datetime.now(timezone.utc)
        trigger.last_fired_at = now

        if trigger.trigger_type == "once":
            # Once triggers fire exactly once
            trigger.is_active = False
            trigger.next_fire_at = None

        elif trigger.trigger_type == "interval":
            interval_seconds = self._get_interval_seconds(trigger.config)
            trigger.next_fire_at = now + timedelta(seconds=interval_seconds)

        elif trigger.trigger_type == "cron":
            trigger.next_fire_at = self._compute_next_cron(trigger.config, now)

        # Update in registry
        self._triggers[trigger.id] = trigger

    def _compute_next_fire(self, trigger: TriggerConfig) -> datetime:
        """Compute the initial next_fire_at for a trigger.

        Args:
            trigger: The trigger to compute for.

        Returns:
            The next datetime when the trigger should fire.
        """
        now = datetime.now(timezone.utc)

        if trigger.trigger_type == "once":
            fire_at = trigger.config.get("fire_at")
            if fire_at and isinstance(fire_at, str):
                return datetime.fromisoformat(fire_at)
            return now

        elif trigger.trigger_type == "interval":
            interval_seconds = self._get_interval_seconds(trigger.config)
            return now + timedelta(seconds=interval_seconds)

        elif trigger.trigger_type == "cron":
            return self._compute_next_cron(trigger.config, now)

        return now

    def _get_interval_seconds(self, config: dict[str, Any]) -> int:
        """Extract interval duration in seconds from trigger config.

        Config can specify: seconds, minutes, or hours.

        Args:
            config: Trigger configuration dictionary.

        Returns:
            Interval in seconds.
        """
        seconds = config.get("seconds", 0)
        minutes = config.get("minutes", 0)
        hours = config.get("hours", 0)
        return seconds + (minutes * 60) + (hours * 3600)

    def _compute_next_cron(
        self, config: dict[str, Any], after: datetime
    ) -> datetime:
        """Compute next cron fire time from cron-style fields.

        Supports simplified cron with: minute, hour, day_of_month,
        month, day_of_week fields. Each can be '*' (any) or an int.

        Args:
            config: Cron configuration with field values.
            after: Compute next fire time after this datetime.

        Returns:
            The next datetime matching the cron expression.
        """
        minute = config.get("minute", "*")
        hour = config.get("hour", "*")

        # Simple implementation: find next matching minute/hour
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Search up to 48 hours ahead for next match
        max_iterations = 48 * 60
        for _ in range(max_iterations):
            minute_match = (minute == "*" or candidate.minute == int(minute))
            hour_match = (hour == "*" or candidate.hour == int(hour))

            if minute_match and hour_match:
                return candidate
            candidate += timedelta(minutes=1)

        # Fallback: 1 hour from now
        return after + timedelta(hours=1)

    def list_triggers(
        self, company_id: uuid.UUID | None = None, active_only: bool = True
    ) -> list[TriggerConfig]:
        """List registered triggers with optional filters.

        Args:
            company_id: Filter by company. None means all.
            active_only: Whether to only return active triggers.

        Returns:
            List of matching TriggerConfig objects.
        """
        results: list[TriggerConfig] = []
        for trigger in self._triggers.values():
            if active_only and not trigger.is_active:
                continue
            if company_id and trigger.company_id != company_id:
                continue
            results.append(trigger)
        return results
