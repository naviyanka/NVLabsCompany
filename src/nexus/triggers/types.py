"""Trigger types - DTOs, mode and kind enumerations for the trigger system.

Defines the core type enumerations and gate logic for automatic
trigger execution based on mode and inbound kind, plus the
:class:`TriggerConfig` transfer object.

``TriggerConfig`` is a pure DTO. It carries trigger fields between layers and
holds no schedule state of its own -- the ``Trigger`` table is the only
registry, and ``nexus.runtime.scheduler`` is the only dispatcher (ADR 0001).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TriggerMode(str, Enum):
    """Trigger execution mode controlling which inbound messages are auto-processed.

    Attributes:
        strict: Only explicitly allowed triggers fire automatically.
        allow_all: All inbound messages are processed automatically.
        communication_only: Only communication-type messages are auto-processed.
    """

    strict = "strict"
    allow_all = "allow-all"
    communication_only = "communication-only"


class InboundKind(str, Enum):
    """Classification of an inbound message.

    Attributes:
        directive: An actionable instruction or command.
        communication: A question or informational exchange.
    """

    directive = "directive"
    communication = "communication"


DEFAULT_TRIGGER_MODE: TriggerMode = TriggerMode.strict


@dataclass
class TriggerConfig:
    """Data transfer object describing a scheduled trigger.

    Mirrors the ``triggers`` table columns so callers can pass a trigger
    around without an ORM instance. Persisting and scheduling belong to the
    ``Trigger`` model and ``nexus.runtime.scheduler`` respectively.

    Attributes:
        id: Unique trigger identifier.
        trigger_type: Type of trigger (cron, once, interval, on_schedule, webhook).
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

    @classmethod
    def from_model(cls, trigger: Any) -> "TriggerConfig":
        """Build a DTO from a ``Trigger`` row."""
        return cls(
            id=trigger.id,
            trigger_type=trigger.trigger_type,
            company_id=trigger.company_id,
            agent_id=trigger.agent_id,
            name=trigger.name,
            config=trigger.config or {},
            is_active=trigger.is_active,
            last_fired_at=trigger.last_fired_at,
            next_fire_at=trigger.next_fire_at,
        )


def is_auto_allowed(mode: TriggerMode, kind: InboundKind) -> bool:
    """Determine whether automatic processing is allowed for a given mode and kind.

    Gate function that decides if an inbound message should be
    automatically processed based on the current trigger mode.

    Args:
        mode: The current trigger mode.
        kind: The classification of the inbound message.

    Returns:
        True if the message should be auto-processed, False otherwise.
    """
    if mode == TriggerMode.allow_all:
        return True
    if mode == TriggerMode.communication_only:
        return kind == InboundKind.communication
    # strict mode: nothing is auto-allowed
    return False
