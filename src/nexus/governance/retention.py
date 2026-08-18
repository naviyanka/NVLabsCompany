"""Retention Manager - Data lifecycle management.

Defines retention policies per data type, handles auto-archival and deletion,
legal holds, and storage usage tracking.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class DataCategory(str, Enum):
    """Categories of data subject to retention policies."""

    AUDIT_LOGS = "audit_logs"
    TASK_RESULTS = "task_results"
    MEMORY = "memory"
    COMMUNICATION = "communication"


@dataclass
class RetentionPolicy:
    """A retention policy for a specific data category.

    Attributes:
        category: The data category this policy applies to.
        retention_days: Total days to retain data before deletion.
        archive_after_days: Days after which data is archived to cold storage.
        grace_period_days: Extra days after expiration before actual deletion.
    """

    category: DataCategory
    retention_days: int = 365
    archive_after_days: int = 90
    grace_period_days: int = 30


@dataclass
class LegalHold:
    """A legal hold preventing deletion of data.

    Attributes:
        id: Unique hold identifier.
        category: Data category under hold.
        reason: Why the hold was placed.
        placed_by: Who placed the hold.
        placed_at: When the hold was placed.
        company_id: Tenant scope (None for system-wide holds).
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    category: DataCategory = DataCategory.AUDIT_LOGS
    reason: str = ""
    placed_by: str = ""
    placed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    company_id: uuid.UUID | None = None


@dataclass
class StorageUsage:
    """Storage usage metrics for a data category.

    Attributes:
        category: The data category.
        total_records: Number of records.
        active_records: Records in active storage.
        archived_records: Records in cold storage.
        expired_records: Records past retention but not yet deleted.
        estimated_size_bytes: Estimated storage in bytes.
    """

    category: DataCategory
    total_records: int = 0
    active_records: int = 0
    archived_records: int = 0
    expired_records: int = 0
    estimated_size_bytes: int = 0


@dataclass
class DataRecord:
    """Represents a data record subject to retention policies.

    Attributes:
        id: Unique record identifier.
        category: Data category.
        created_at: When the record was created.
        archived: Whether the record has been archived.
        archived_at: When it was archived.
        company_id: Tenant scope.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    category: DataCategory = DataCategory.AUDIT_LOGS
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    archived: bool = False
    archived_at: datetime | None = None
    company_id: uuid.UUID | None = None


class RetentionManager:
    """Manages data lifecycle including archival, deletion, and legal holds.

    Provides:
    - Retention policy definition per data category
    - Auto-archive of old data
    - Auto-delete of expired data (with grace period)
    - Legal hold support (prevents deletion during investigations)
    - Storage usage tracking and projections
    """

    def __init__(self) -> None:
        """Initialize the retention manager."""
        self._policies: dict[DataCategory, RetentionPolicy] = {}
        self._legal_holds: dict[uuid.UUID, LegalHold] = {}
        self._records: list[DataRecord] = []

    def set_policy(self, policy: RetentionPolicy) -> RetentionPolicy:
        """Set or update a retention policy for a data category.

        Args:
            policy: The retention policy to set.

        Returns:
            The set policy.
        """
        self._policies[policy.category] = policy
        return policy

    def get_policy(self, category: DataCategory) -> RetentionPolicy | None:
        """Get the retention policy for a data category.

        Args:
            category: The data category.

        Returns:
            The RetentionPolicy, or None if not configured.
        """
        return self._policies.get(category)

    def add_record(self, record: DataRecord) -> DataRecord:
        """Add a data record for retention tracking.

        Args:
            record: The data record to track.

        Returns:
            The added record.
        """
        self._records.append(record)
        return record

    def check_expiration(
        self, category: DataCategory, reference_time: datetime | None = None
    ) -> list[DataRecord]:
        """Check which records in a category have expired.

        A record is expired if it has exceeded the retention_days + grace_period_days
        defined in the policy.

        Args:
            category: The data category to check.
            reference_time: Time to check against (defaults to now).

        Returns:
            List of expired DataRecords.
        """
        policy = self._policies.get(category)
        if policy is None:
            return []

        now = reference_time or datetime.now(timezone.utc)
        total_retention = policy.retention_days + policy.grace_period_days
        cutoff = now - timedelta(days=total_retention)

        expired: list[DataRecord] = []
        for record in self._records:
            if record.category == category and record.created_at < cutoff:
                expired.append(record)

        return expired

    def archive_old_data(
        self, category: DataCategory, reference_time: datetime | None = None
    ) -> list[DataRecord]:
        """Archive records that have exceeded the archive threshold.

        Moves records older than archive_after_days to archived state.

        Args:
            category: The data category to archive.
            reference_time: Time to check against (defaults to now).

        Returns:
            List of newly archived records.
        """
        policy = self._policies.get(category)
        if policy is None:
            return []

        now = reference_time or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=policy.archive_after_days)

        archived: list[DataRecord] = []
        for record in self._records:
            if (
                record.category == category
                and not record.archived
                and record.created_at < cutoff
            ):
                record.archived = True
                record.archived_at = now
                archived.append(record)

        return archived

    def delete_expired_data(
        self, category: DataCategory, reference_time: datetime | None = None
    ) -> list[DataRecord]:
        """Delete records that have expired past the grace period.

        Will NOT delete records under legal hold.

        Args:
            category: The data category to clean.
            reference_time: Time to check against (defaults to now).

        Returns:
            List of deleted DataRecords.
        """
        # Check for legal holds
        if self._has_legal_hold(category):
            return []

        expired = self.check_expiration(category, reference_time)
        deleted: list[DataRecord] = []

        for record in expired:
            self._records.remove(record)
            deleted.append(record)

        return deleted

    def set_legal_hold(
        self,
        category: DataCategory,
        reason: str,
        placed_by: str = "system",
        company_id: uuid.UUID | None = None,
    ) -> LegalHold:
        """Place a legal hold on a data category preventing deletion.

        Args:
            category: The data category to hold.
            reason: Why the hold is being placed.
            placed_by: Who is placing the hold.
            company_id: Tenant scope (None for system-wide).

        Returns:
            The created LegalHold.
        """
        hold = LegalHold(
            category=category,
            reason=reason,
            placed_by=placed_by,
            company_id=company_id,
        )
        self._legal_holds[hold.id] = hold
        return hold

    def remove_legal_hold(self, hold_id: uuid.UUID) -> bool:
        """Remove a legal hold.

        Args:
            hold_id: The hold to remove.

        Returns:
            True if the hold was found and removed.
        """
        if hold_id in self._legal_holds:
            del self._legal_holds[hold_id]
            return True
        return False

    def get_legal_holds(
        self, category: DataCategory | None = None
    ) -> list[LegalHold]:
        """Get active legal holds.

        Args:
            category: If provided, filter to holds on this category.

        Returns:
            List of active LegalHold objects.
        """
        if category is None:
            return list(self._legal_holds.values())
        return [h for h in self._legal_holds.values() if h.category == category]

    def get_storage_usage(self, category: DataCategory) -> StorageUsage:
        """Get storage usage metrics for a data category.

        Args:
            category: The data category to check.

        Returns:
            StorageUsage metrics.
        """
        records = [r for r in self._records if r.category == category]
        active = [r for r in records if not r.archived]
        archived = [r for r in records if r.archived]

        policy = self._policies.get(category)
        expired_count = 0
        if policy:
            now = datetime.now(timezone.utc)
            total_retention = policy.retention_days + policy.grace_period_days
            cutoff = now - timedelta(days=total_retention)
            expired_count = sum(1 for r in records if r.created_at < cutoff)

        # Estimate 1KB per record for sizing
        estimated_size = len(records) * 1024

        return StorageUsage(
            category=category,
            total_records=len(records),
            active_records=len(active),
            archived_records=len(archived),
            expired_records=expired_count,
            estimated_size_bytes=estimated_size,
        )

    def project_storage(
        self, category: DataCategory, days_ahead: int = 30
    ) -> dict[str, Any]:
        """Project future storage usage based on current growth rate.

        Args:
            category: The data category to project.
            days_ahead: Number of days to project forward.

        Returns:
            Dict with projection data including estimated_records and estimated_bytes.
        """
        current_usage = self.get_storage_usage(category)
        records = [r for r in self._records if r.category == category]

        if len(records) < 2:
            daily_growth = 1.0
        else:
            sorted_records = sorted(records, key=lambda r: r.created_at)
            first = sorted_records[0].created_at
            last = sorted_records[-1].created_at
            span_days = max((last - first).days, 1)
            daily_growth = len(records) / span_days

        projected_records = current_usage.total_records + int(daily_growth * days_ahead)
        projected_bytes = projected_records * 1024

        return {
            "current_records": current_usage.total_records,
            "daily_growth_rate": daily_growth,
            "projected_records": projected_records,
            "projected_bytes": projected_bytes,
            "days_ahead": days_ahead,
        }

    def _has_legal_hold(self, category: DataCategory) -> bool:
        """Check if a category has an active legal hold.

        Args:
            category: The category to check.

        Returns:
            True if there is an active legal hold.
        """
        return any(h.category == category for h in self._legal_holds.values())
