"""Webhook Persistent Delivery Queue - file-backed queue with retry and dead letter storage.

Provides a durable outbound webhook delivery queue that persists state to a JSON file.
Supports exponential backoff retries and dead letter storage for permanently failed
deliveries. All file writes are atomic (tempfile + os.replace) to prevent corruption.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass
class WebhookDelivery:
    """A single outbound webhook delivery attempt."""

    id: str
    url: str
    payload: dict[str, Any]
    headers: dict[str, str]
    created_at: datetime
    retry_count: int = 0
    next_retry_at: datetime | None = None
    status: str = "pending"
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "url": self.url,
            "payload": self.payload,
            "headers": self.headers,
            "created_at": self.created_at.isoformat(),
            "retry_count": self.retry_count,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "status": self.status,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookDelivery:
        """Deserialize from a dictionary."""
        return cls(
            id=data["id"],
            url=data["url"],
            payload=data["payload"],
            headers=data["headers"],
            created_at=datetime.fromisoformat(data["created_at"]),
            retry_count=data.get("retry_count", 0),
            next_retry_at=(
                datetime.fromisoformat(data["next_retry_at"])
                if data.get("next_retry_at")
                else None
            ),
            status=data.get("status", "pending"),
            last_error=data.get("last_error"),
        )


@dataclass
class WebhookDeliveryQueue:
    """File-backed delivery queue with retry logic and dead letter storage.

    Persists pending deliveries and dead letters to a JSON file. All writes are
    atomic using tempfile in the same directory followed by os.replace to prevent
    corruption on crash.

    Exponential backoff formula: min(2^(retry_count - 1), 16) seconds from now.
    """

    persist_path: Path
    max_retries: int = 5
    dead_letter_cap: int = 100
    _pending: list[WebhookDelivery] = field(default_factory=list, init=False, repr=False)
    _dead_letters: list[WebhookDelivery] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Load persisted state on initialization."""
        self._load()

    def _load(self) -> None:
        """Load state from the persistence file.

        If the file does not exist or is invalid, starts with empty state.
        """
        if not self.persist_path.exists():
            self._pending = []
            self._dead_letters = []
            return

        try:
            raw = self.persist_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            self._pending = [
                WebhookDelivery.from_dict(d) for d in data.get("pending", [])
            ]
            self._dead_letters = [
                WebhookDelivery.from_dict(d) for d in data.get("dead_letters", [])
            ]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._pending = []
            self._dead_letters = []

    def _save(self) -> None:
        """Persist current state to file atomically.

        Writes to a temporary file in the same directory, then uses os.replace
        for an atomic swap. This prevents corruption if the process dies mid-write.
        """
        data = {
            "pending": [d.to_dict() for d in self._pending],
            "dead_letters": [d.to_dict() for d in self._dead_letters],
        }
        content = json.dumps(data, indent=2)

        # Ensure parent directory exists
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file in same dir + os.replace
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.persist_path.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            fd.write(content)
            fd.flush()
            os.fsync(fd.fileno())
            fd.close()
            os.replace(fd.name, self.persist_path)
        except BaseException:
            fd.close()
            # Clean up temp file on failure
            try:
                os.unlink(fd.name)
            except OSError:
                pass
            raise

    def enqueue(self, delivery: WebhookDelivery) -> None:
        """Add a delivery to the pending queue.

        Args:
            delivery: The webhook delivery to enqueue.
        """
        self._pending.append(delivery)
        self._save()

    def dequeue(self) -> WebhookDelivery | None:
        """Remove and return the next ready delivery from the queue.

        A delivery is ready if its next_retry_at is None or <= now (UTC).

        Returns:
            The next ready WebhookDelivery, or None if no deliveries are ready.
        """
        now = datetime.now(UTC)
        for i, delivery in enumerate(self._pending):
            if delivery.next_retry_at is None or delivery.next_retry_at <= now:
                self._pending.pop(i)
                self._save()
                return delivery
        return None

    def ack(self, delivery_id: str) -> bool:
        """Acknowledge successful delivery, removing it from the queue.

        Args:
            delivery_id: The ID of the delivery to acknowledge.

        Returns:
            True if the delivery was found and removed, False otherwise.
        """
        for i, delivery in enumerate(self._pending):
            if delivery.id == delivery_id:
                self._pending.pop(i)
                self._save()
                return True
        return False

    def nack(self, delivery_id: str, error: str) -> None:
        """Report a delivery failure, applying retry logic or dead-lettering.

        Increments the retry count and computes the next retry time using
        exponential backoff: min(2^(retry_count - 1), 16) seconds.

        If retry_count exceeds max_retries, the delivery is moved to the dead
        letter queue. The dead letter queue is capped; the oldest entry is
        dropped when the cap is exceeded.

        Args:
            delivery_id: The ID of the failed delivery.
            error: Description of the failure.
        """
        for i, delivery in enumerate(self._pending):
            if delivery.id == delivery_id:
                delivery.retry_count += 1
                delivery.last_error = error

                if delivery.retry_count > self.max_retries:
                    # Move to dead letters
                    delivery.status = "dead"
                    self._pending.pop(i)
                    self._dead_letters.append(delivery)

                    # Enforce dead letter cap - drop oldest
                    while len(self._dead_letters) > self.dead_letter_cap:
                        self._dead_letters.pop(0)
                else:
                    # Compute exponential backoff
                    backoff_seconds = min(2 ** (delivery.retry_count - 1), 16)
                    delivery.next_retry_at = (
                        datetime.now(UTC) + timedelta(seconds=backoff_seconds)
                    )

                self._save()
                return

    def get_dead_letters(self) -> list[WebhookDelivery]:
        """Return the list of dead-lettered deliveries.

        Returns:
            List of deliveries that exceeded the maximum retry count.
        """
        return list(self._dead_letters)

    def get_pending_count(self) -> int:
        """Return the number of pending deliveries.

        Returns:
            Count of deliveries in the pending queue.
        """
        return len(self._pending)

    def get_dead_letter_count(self) -> int:
        """Return the number of dead-lettered deliveries.

        Returns:
            Count of deliveries in the dead letter queue.
        """
        return len(self._dead_letters)
