"""Trigger types - mode and kind enumerations for the trigger system.

Defines the core type enumerations and gate logic for automatic
trigger execution based on mode and inbound kind.
"""

from enum import Enum


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
