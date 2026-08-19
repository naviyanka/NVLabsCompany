"""Tests for WebhookDeliveryQueue - file-backed delivery queue with retry logic."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.communication.webhook_queue import WebhookDelivery, WebhookDeliveryQueue


def _make_delivery(
    id: str = "d1",
    url: str = "https://example.com/hook",
    payload: dict | None = None,
    headers: dict | None = None,
    created_at: datetime | None = None,
    retry_count: int = 0,
    next_retry_at: datetime | None = None,
    status: str = "pending",
    last_error: str | None = None,
) -> WebhookDelivery:
    """Helper to create a WebhookDelivery with sensible defaults."""
    return WebhookDelivery(
        id=id,
        url=url,
        payload=payload or {"event": "test"},
        headers=headers or {"Content-Type": "application/json"},
        created_at=created_at or datetime.now(UTC),
        retry_count=retry_count,
        next_retry_at=next_retry_at,
        status=status,
        last_error=last_error,
    )


class TestEnqueueDequeue:
    """Tests for basic enqueue/dequeue operations."""

    def test_enqueue_dequeue_cycle(self, tmp_path: Path) -> None:
        """Enqueue a delivery and dequeue it back."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        delivery = _make_delivery(id="d1")

        queue.enqueue(delivery)
        assert queue.get_pending_count() == 1

        result = queue.dequeue()
        assert result is not None
        assert result.id == "d1"
        assert queue.get_pending_count() == 0

    def test_dequeue_empty_returns_none(self, tmp_path: Path) -> None:
        """Dequeue on empty queue returns None."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        assert queue.dequeue() is None

    def test_dequeue_fifo_order(self, tmp_path: Path) -> None:
        """Dequeue returns deliveries in FIFO order."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        queue.enqueue(_make_delivery(id="first"))
        queue.enqueue(_make_delivery(id="second"))
        queue.enqueue(_make_delivery(id="third"))

        assert queue.dequeue().id == "first"
        assert queue.dequeue().id == "second"
        assert queue.dequeue().id == "third"

    def test_dequeue_respects_next_retry_at(self, tmp_path: Path) -> None:
        """Dequeue skips items whose next_retry_at is in the future."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")

        future = datetime.now(UTC) + timedelta(hours=1)
        queue.enqueue(_make_delivery(id="not_ready", next_retry_at=future))
        queue.enqueue(_make_delivery(id="ready", next_retry_at=None))

        result = queue.dequeue()
        assert result is not None
        assert result.id == "ready"

    def test_dequeue_returns_past_retry_at(self, tmp_path: Path) -> None:
        """Dequeue returns items whose next_retry_at is in the past."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")

        past = datetime.now(UTC) - timedelta(seconds=10)
        queue.enqueue(_make_delivery(id="past_due", next_retry_at=past))

        result = queue.dequeue()
        assert result is not None
        assert result.id == "past_due"

    def test_dequeue_skips_all_not_ready(self, tmp_path: Path) -> None:
        """Dequeue returns None when all items have future next_retry_at."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")

        future = datetime.now(UTC) + timedelta(hours=1)
        queue.enqueue(_make_delivery(id="d1", next_retry_at=future))
        queue.enqueue(_make_delivery(id="d2", next_retry_at=future))

        assert queue.dequeue() is None
        assert queue.get_pending_count() == 2


class TestAck:
    """Tests for the ack operation."""

    def test_ack_removes_delivery(self, tmp_path: Path) -> None:
        """Ack removes delivery from pending and returns True."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        queue.enqueue(_make_delivery(id="d1"))
        queue.enqueue(_make_delivery(id="d2"))

        assert queue.ack("d1") is True
        assert queue.get_pending_count() == 1

    def test_ack_missing_returns_false(self, tmp_path: Path) -> None:
        """Ack on non-existent delivery returns False."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        queue.enqueue(_make_delivery(id="d1"))

        assert queue.ack("nonexistent") is False
        assert queue.get_pending_count() == 1

    def test_ack_empty_queue_returns_false(self, tmp_path: Path) -> None:
        """Ack on empty queue returns False."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        assert queue.ack("anything") is False


class TestNack:
    """Tests for the nack operation with retry logic."""

    def test_nack_increments_retry_count(self, tmp_path: Path) -> None:
        """Nack increments retry_count and sets last_error."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        queue.enqueue(_make_delivery(id="d1"))

        queue.nack("d1", "connection timeout")

        # Item should still be pending with incremented retry
        assert queue.get_pending_count() == 1
        # Reload to check state
        queue2 = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        delivery = queue2._pending[0]
        assert delivery.retry_count == 1
        assert delivery.last_error == "connection timeout"
        assert delivery.next_retry_at is not None

    def test_nack_exponential_backoff_values(self, tmp_path: Path) -> None:
        """Nack computes correct exponential backoff: 1s, 2s, 4s, 8s, 16s."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        queue.enqueue(_make_delivery(id="d1"))

        expected_backoffs = [1, 2, 4, 8, 16]

        for i, expected_seconds in enumerate(expected_backoffs):
            now = datetime.now(UTC)
            with patch(
                "nexus.communication.webhook_queue.datetime"
            ) as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.fromisoformat = datetime.fromisoformat
                queue.nack("d1", f"error {i + 1}")

            delivery = queue._pending[0]
            assert delivery.retry_count == i + 1
            # Check that next_retry_at is approximately now + expected_seconds
            expected_time = now + timedelta(seconds=expected_seconds)
            delta = abs((delivery.next_retry_at - expected_time).total_seconds())
            assert delta < 1.0, (
                f"retry {i + 1}: expected ~{expected_seconds}s backoff, "
                f"got delta={delta}s"
            )

    def test_nack_beyond_max_retries_moves_to_dead_letters(
        self, tmp_path: Path
    ) -> None:
        """Nack beyond max_retries moves delivery to dead letters."""
        queue = WebhookDeliveryQueue(
            persist_path=tmp_path / "queue.json", max_retries=3
        )
        # Start with delivery already at max retries
        delivery = _make_delivery(id="d1", retry_count=3)
        queue.enqueue(delivery)

        queue.nack("d1", "final failure")

        assert queue.get_pending_count() == 0
        assert queue.get_dead_letter_count() == 1
        dead = queue.get_dead_letters()
        assert dead[0].id == "d1"
        assert dead[0].status == "dead"
        assert dead[0].retry_count == 4
        assert dead[0].last_error == "final failure"

    def test_nack_nonexistent_does_nothing(self, tmp_path: Path) -> None:
        """Nack on a nonexistent delivery does nothing."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        queue.enqueue(_make_delivery(id="d1"))

        queue.nack("nonexistent", "error")

        assert queue.get_pending_count() == 1
        assert queue.get_dead_letter_count() == 0


class TestDeadLetterCap:
    """Tests for dead letter cap enforcement."""

    def test_dead_letter_cap_drops_oldest(self, tmp_path: Path) -> None:
        """Dead letter cap enforced: oldest entry is dropped."""
        queue = WebhookDeliveryQueue(
            persist_path=tmp_path / "queue.json",
            max_retries=0,
            dead_letter_cap=3,
        )

        # Enqueue and nack 4 items (cap is 3)
        for i in range(4):
            delivery = _make_delivery(id=f"d{i}")
            queue.enqueue(delivery)
            queue.nack(f"d{i}", f"error {i}")

        assert queue.get_dead_letter_count() == 3
        dead_ids = [d.id for d in queue.get_dead_letters()]
        # Oldest (d0) should have been dropped
        assert "d0" not in dead_ids
        assert dead_ids == ["d1", "d2", "d3"]

    def test_dead_letter_cap_exact_limit(self, tmp_path: Path) -> None:
        """Dead letter count at exactly the cap stays at cap."""
        queue = WebhookDeliveryQueue(
            persist_path=tmp_path / "queue.json",
            max_retries=0,
            dead_letter_cap=2,
        )

        for i in range(2):
            queue.enqueue(_make_delivery(id=f"d{i}"))
            queue.nack(f"d{i}", "err")

        assert queue.get_dead_letter_count() == 2


class TestPersistence:
    """Tests for file-backed persistence."""

    def test_persistence_survives_restart(self, tmp_path: Path) -> None:
        """State persists across queue instances using the same file."""
        path = tmp_path / "queue.json"

        # Instance 1: enqueue items
        q1 = WebhookDeliveryQueue(persist_path=path)
        q1.enqueue(_make_delivery(id="d1", url="https://a.com"))
        q1.enqueue(_make_delivery(id="d2", url="https://b.com"))

        # Instance 2: read from same file
        q2 = WebhookDeliveryQueue(persist_path=path)
        assert q2.get_pending_count() == 2
        result = q2.dequeue()
        assert result.id == "d1"
        assert result.url == "https://a.com"

    def test_persistence_dead_letters_survive_restart(
        self, tmp_path: Path
    ) -> None:
        """Dead letters persist across queue instances."""
        path = tmp_path / "queue.json"

        q1 = WebhookDeliveryQueue(
            persist_path=path, max_retries=0
        )
        q1.enqueue(_make_delivery(id="dead1"))
        q1.nack("dead1", "permanent failure")

        q2 = WebhookDeliveryQueue(persist_path=path, max_retries=0)
        assert q2.get_dead_letter_count() == 1
        assert q2.get_dead_letters()[0].id == "dead1"

    def test_empty_file_on_init_creates_empty_state(
        self, tmp_path: Path
    ) -> None:
        """Non-existent file on init creates empty state."""
        path = tmp_path / "nonexistent" / "queue.json"
        queue = WebhookDeliveryQueue(persist_path=path)

        assert queue.get_pending_count() == 0
        assert queue.get_dead_letter_count() == 0

    def test_corrupt_file_on_init_creates_empty_state(
        self, tmp_path: Path
    ) -> None:
        """Corrupt/invalid JSON file on init creates empty state."""
        path = tmp_path / "queue.json"
        path.write_text("not valid json {{{", encoding="utf-8")

        queue = WebhookDeliveryQueue(persist_path=path)
        assert queue.get_pending_count() == 0
        assert queue.get_dead_letter_count() == 0

    def test_atomic_write_produces_valid_json(self, tmp_path: Path) -> None:
        """Atomic write produces a valid JSON file."""
        path = tmp_path / "queue.json"
        queue = WebhookDeliveryQueue(persist_path=path)
        queue.enqueue(_make_delivery(id="d1"))

        # Read file directly and parse
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert "pending" in data
        assert "dead_letters" in data
        assert len(data["pending"]) == 1
        assert data["pending"][0]["id"] == "d1"


class TestCounts:
    """Tests for count methods."""

    def test_get_pending_count(self, tmp_path: Path) -> None:
        """get_pending_count returns correct count."""
        queue = WebhookDeliveryQueue(persist_path=tmp_path / "queue.json")
        assert queue.get_pending_count() == 0

        queue.enqueue(_make_delivery(id="d1"))
        assert queue.get_pending_count() == 1

        queue.enqueue(_make_delivery(id="d2"))
        assert queue.get_pending_count() == 2

        queue.dequeue()
        assert queue.get_pending_count() == 1

    def test_get_dead_letter_count(self, tmp_path: Path) -> None:
        """get_dead_letter_count returns correct count."""
        queue = WebhookDeliveryQueue(
            persist_path=tmp_path / "queue.json", max_retries=0
        )
        assert queue.get_dead_letter_count() == 0

        queue.enqueue(_make_delivery(id="d1"))
        queue.nack("d1", "err")
        assert queue.get_dead_letter_count() == 1
