"""Trigger history - ledger of trigger activations and their outcomes.

Maintains a capped history of trigger events for auditing and replay purposes.
"""

from dataclasses import dataclass, field

from nexus.triggers.types import InboundKind

TRIGGER_HISTORY_LIMIT: int = 500


@dataclass
class TriggerHistoryEntry:
    """A single entry in the trigger history ledger.

    Attributes:
        id: Unique entry identifier.
        source: Origin system of the trigger.
        source_id: Identifier within the source system.
        source_name: Human-readable source name.
        direction: Direction of the message (inbound/outbound).
        peer: The remote peer involved.
        title: Optional title for the entry.
        body: The message body.
        kind: Classification of the inbound message.
        decision: The decision made (auto-allowed, queued, etc.).
        correlation_id: Correlation identifier for tracing.
        task_id: Associated task identifier.
        at: Unix timestamp when the entry was recorded.
    """

    id: str
    source: str
    source_id: str
    source_name: str
    direction: str
    peer: str
    title: str = ""
    body: str = ""
    kind: InboundKind = InboundKind.communication
    decision: str = ""
    correlation_id: str = ""
    task_id: str = ""
    at: float = 0.0


class TriggerHistoryLedger:
    """Capped ledger of trigger history entries.

    Maintains at most TRIGGER_HISTORY_LIMIT entries, dropping the oldest
    when the limit is exceeded.
    """

    def __init__(self) -> None:
        """Initialize an empty ledger."""
        self._entries: list[TriggerHistoryEntry] = []

    def add(self, entry: TriggerHistoryEntry) -> None:
        """Add an entry to the ledger, dropping the oldest if at capacity.

        Args:
            entry: The trigger history entry to record.
        """
        self._entries.append(entry)
        if len(self._entries) > TRIGGER_HISTORY_LIMIT:
            self._entries = self._entries[-TRIGGER_HISTORY_LIMIT:]

    def list(self, limit: int | None = None) -> list[TriggerHistoryEntry]:
        """Retrieve entries from the ledger.

        Args:
            limit: Maximum number of entries to return. Returns all if None.

        Returns:
            List of TriggerHistoryEntry objects, most recent last.
        """
        if limit is None:
            return list(self._entries)
        return self._entries[-limit:]
