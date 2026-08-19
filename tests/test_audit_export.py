"""Tests for Audit Log Export and Retention."""

import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexus.governance.audit import AuditEntry, AuditLogger
from nexus.governance.audit_export import (
    AuditExporter,
    ExportFormat,
    RetentionPolicy,
)


@pytest.fixture
def logger() -> AuditLogger:
    """Create a fresh AuditLogger instance."""
    return AuditLogger()


@pytest.fixture
def exporter(logger: AuditLogger) -> AuditExporter:
    """Create an AuditExporter with an AuditLogger."""
    return AuditExporter(logger)


async def _add_entries(
    logger: AuditLogger, count: int, base_time: datetime | None = None
) -> list[AuditEntry]:
    """Add multiple entries to the logger for testing.

    Args:
        logger: The audit logger to add entries to.
        count: Number of entries to add.
        base_time: Starting timestamp (entries are spaced 1 hour apart).

    Returns:
        List of created entries.
    """
    if base_time is None:
        base_time = datetime.now(timezone.utc) - timedelta(hours=count)

    entries = []
    for i in range(count):
        entry = await logger.log(
            actor_type="agent",
            actor_id=f"agent-{i}",
            action=f"action-{i}",
            resource_type="task",
            resource_id=f"task-{i}",
            details={"index": i},
        )
        # Override timestamp for predictable ordering
        entry.timestamp = base_time + timedelta(hours=i)
        entries.append(entry)
    return entries


class TestRetentionPolicy:
    """Tests for RetentionPolicy dataclass."""

    def test_default_policy(self) -> None:
        """Test default retention policy values."""
        policy = RetentionPolicy()
        assert policy.max_age_days == 365
        assert policy.archive_after_days == 90

    def test_custom_policy(self) -> None:
        """Test custom retention policy values."""
        policy = RetentionPolicy(max_age_days=180, archive_after_days=30)
        assert policy.max_age_days == 180
        assert policy.archive_after_days == 30

    def test_invalid_archive_zero(self) -> None:
        """Test that archive_after_days of 0 raises ValueError."""
        with pytest.raises(ValueError, match="archive_after_days must be positive"):
            RetentionPolicy(archive_after_days=0)

    def test_invalid_max_age_zero(self) -> None:
        """Test that max_age_days of 0 raises ValueError."""
        with pytest.raises(ValueError, match="max_age_days must be positive"):
            RetentionPolicy(max_age_days=0, archive_after_days=1)

    def test_archive_must_be_less_than_max_age(self) -> None:
        """Test that archive_after_days must be less than max_age_days."""
        with pytest.raises(
            ValueError, match="archive_after_days must be less than"
        ):
            RetentionPolicy(max_age_days=30, archive_after_days=30)

    def test_archive_greater_than_max_age_raises(self) -> None:
        """Test archive_after_days > max_age_days raises ValueError."""
        with pytest.raises(
            ValueError, match="archive_after_days must be less than"
        ):
            RetentionPolicy(max_age_days=30, archive_after_days=60)


class TestExportJSON:
    """Tests for JSON export."""

    @pytest.mark.asyncio
    async def test_export_empty_range(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test exporting when no entries match the range."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=2)
        end = now - timedelta(hours=1)

        result = exporter.export_range(start, end, ExportFormat.JSON)
        parsed = json.loads(result)
        assert parsed == []

    @pytest.mark.asyncio
    async def test_export_entries_in_range(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test exporting entries within the specified range."""
        base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        entries = await _add_entries(logger, 5, base_time=base)

        # Export entries 1-3 (hours 1-3)
        start = base + timedelta(hours=1)
        end = base + timedelta(hours=3)
        result = exporter.export_range(start, end, ExportFormat.JSON)
        parsed = json.loads(result)

        assert len(parsed) == 3
        assert parsed[0]["actor_id"] == "agent-1"
        assert parsed[2]["actor_id"] == "agent-3"

    @pytest.mark.asyncio
    async def test_export_json_fields(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test that JSON export contains all expected fields."""
        now = datetime.now(timezone.utc)
        entry = await logger.log(
            actor_type="user",
            actor_id="user-42",
            action="login",
            resource_type="session",
            resource_id="sess-1",
            details={"ip": "10.0.0.1"},
            company_id=uuid.uuid4(),
        )
        entry.timestamp = now

        start = now - timedelta(seconds=1)
        end = now + timedelta(seconds=1)
        result = exporter.export_range(start, end, "json")
        parsed = json.loads(result)

        assert len(parsed) == 1
        record = parsed[0]
        assert record["actor_type"] == "user"
        assert record["actor_id"] == "user-42"
        assert record["action"] == "login"
        assert record["resource_type"] == "session"
        assert record["resource_id"] == "sess-1"
        assert "ip" in record["details"]
        assert record["id"] == str(entry.id)


class TestExportCSV:
    """Tests for CSV export."""

    @pytest.mark.asyncio
    async def test_export_csv_headers(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test that CSV export includes correct headers."""
        now = datetime.now(timezone.utc)
        await logger.log(
            actor_type="system",
            actor_id="system",
            action="startup",
        )
        # Set timestamp for the entry
        logger._entries[-1].timestamp = now

        start = now - timedelta(seconds=1)
        end = now + timedelta(seconds=1)
        result = exporter.export_range(start, end, ExportFormat.CSV)

        reader = csv.reader(io.StringIO(result))
        headers = next(reader)
        assert "id" in headers
        assert "actor_type" in headers
        assert "actor_id" in headers
        assert "action" in headers
        assert "timestamp" in headers

    @pytest.mark.asyncio
    async def test_export_csv_rows(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test that CSV export contains the correct number of rows."""
        base = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        await _add_entries(logger, 3, base_time=base)

        start = base
        end = base + timedelta(hours=3)
        result = exporter.export_range(start, end, ExportFormat.CSV)

        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        # 1 header + 3 data rows
        assert len(rows) == 4

    @pytest.mark.asyncio
    async def test_export_csv_empty(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test CSV export with no matching entries."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=2)
        end = now - timedelta(hours=1)

        result = exporter.export_range(start, end, ExportFormat.CSV)
        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        # Only header row
        assert len(rows) == 1


class TestExportValidation:
    """Tests for export validation."""

    def test_start_after_end_raises(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test that start > end raises ValueError."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="start must be before"):
            exporter.export_range(
                now, now - timedelta(hours=1), ExportFormat.JSON
            )


class TestApplyRetention:
    """Tests for retention policy application."""

    @pytest.mark.asyncio
    async def test_archive_old_entries(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test that entries older than archive_after_days are archived."""
        now = datetime.now(timezone.utc)

        # Add a recent entry
        recent = await logger.log(
            actor_type="agent", actor_id="a1", action="recent"
        )
        recent.timestamp = now - timedelta(days=5)

        # Add an old entry (should be archived)
        old = await logger.log(
            actor_type="agent", actor_id="a2", action="old"
        )
        old.timestamp = now - timedelta(days=100)

        policy = RetentionPolicy(max_age_days=365, archive_after_days=90)
        result = exporter.apply_retention(policy)

        assert result["archived"] == 1
        assert result["remaining"] == 1
        assert len(exporter.get_archive()) == 1
        assert exporter.get_archive()[0].action == "old"

    @pytest.mark.asyncio
    async def test_purge_ancient_entries(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test that entries older than max_age_days are purged."""
        now = datetime.now(timezone.utc)

        # Add an ancient entry (should be purged)
        ancient = await logger.log(
            actor_type="agent", actor_id="a1", action="ancient"
        )
        ancient.timestamp = now - timedelta(days=400)

        # Add a recent entry
        recent = await logger.log(
            actor_type="agent", actor_id="a2", action="recent"
        )
        recent.timestamp = now - timedelta(days=10)

        policy = RetentionPolicy(max_age_days=365, archive_after_days=90)
        result = exporter.apply_retention(policy)

        assert result["purged"] == 1
        assert result["remaining"] == 1
        assert len(exporter.get_archive()) == 0

    @pytest.mark.asyncio
    async def test_purge_from_archive(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test that archived entries past max_age are purged from archive."""
        now = datetime.now(timezone.utc)

        # Pre-populate archive with an ancient entry
        ancient_entry = AuditEntry(
            actor_type="agent",
            actor_id="a1",
            action="archived-ancient",
        )
        ancient_entry.timestamp = now - timedelta(days=400)
        exporter._archive.append(ancient_entry)

        policy = RetentionPolicy(max_age_days=365, archive_after_days=90)
        result = exporter.apply_retention(policy)

        assert result["purged"] == 1
        assert len(exporter.get_archive()) == 0

    @pytest.mark.asyncio
    async def test_retention_keeps_recent(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test that recent entries are not affected by retention."""
        now = datetime.now(timezone.utc)

        for i in range(5):
            entry = await logger.log(
                actor_type="agent", actor_id=f"a{i}", action=f"action-{i}"
            )
            entry.timestamp = now - timedelta(days=i)

        policy = RetentionPolicy(max_age_days=365, archive_after_days=90)
        result = exporter.apply_retention(policy)

        assert result["archived"] == 0
        assert result["purged"] == 0
        assert result["remaining"] == 5

    @pytest.mark.asyncio
    async def test_mixed_retention(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test retention with entries in all categories."""
        now = datetime.now(timezone.utc)

        # Recent (keep)
        e1 = await logger.log(
            actor_type="agent", actor_id="a1", action="recent"
        )
        e1.timestamp = now - timedelta(days=10)

        # Old (archive)
        e2 = await logger.log(
            actor_type="agent", actor_id="a2", action="old"
        )
        e2.timestamp = now - timedelta(days=100)

        # Ancient (purge)
        e3 = await logger.log(
            actor_type="agent", actor_id="a3", action="ancient"
        )
        e3.timestamp = now - timedelta(days=400)

        policy = RetentionPolicy(max_age_days=365, archive_after_days=90)
        result = exporter.apply_retention(policy)

        assert result["archived"] == 1
        assert result["purged"] == 1
        assert result["remaining"] == 1


class TestAtomicExport:
    """Tests for thread-safety of export operations."""

    @pytest.mark.asyncio
    async def test_export_is_consistent(
        self, logger: AuditLogger, exporter: AuditExporter
    ) -> None:
        """Test that export produces a consistent snapshot."""
        base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        await _add_entries(logger, 10, base_time=base)

        start = base
        end = base + timedelta(hours=10)

        # Multiple exports should give consistent results
        result1 = exporter.export_range(start, end, ExportFormat.JSON)
        result2 = exporter.export_range(start, end, ExportFormat.JSON)
        assert result1 == result2
