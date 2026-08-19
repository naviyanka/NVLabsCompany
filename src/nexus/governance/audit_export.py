"""Audit Log Export and Retention - supports JSON/CSV export and retention policies.

Provides atomic export of audit entries within a date range and retention
management that archives old entries and purges ancient ones.
"""

from __future__ import annotations

import csv
import io
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nexus.governance.audit import AuditEntry, AuditLogger


class ExportFormat(str, Enum):
    """Supported export formats.

    Values:
        JSON: JSON array of audit entries.
        CSV: Comma-separated values with headers.
    """

    JSON = "json"
    CSV = "csv"


@dataclass
class RetentionPolicy:
    """Retention policy for audit log entries.

    Attributes:
        max_age_days: Entries older than this are purged entirely.
        archive_after_days: Entries older than this are moved to archive.
    """

    max_age_days: int = 365
    archive_after_days: int = 90

    def __post_init__(self) -> None:
        """Validate retention policy values."""
        if self.archive_after_days <= 0:
            raise ValueError("archive_after_days must be positive")
        if self.max_age_days <= 0:
            raise ValueError("max_age_days must be positive")
        if self.archive_after_days >= self.max_age_days:
            raise ValueError(
                "archive_after_days must be less than max_age_days"
            )


def _entry_to_dict(entry: AuditEntry) -> dict[str, Any]:
    """Convert an AuditEntry to a serializable dictionary.

    Args:
        entry: The audit entry to convert.

    Returns:
        Dictionary representation of the entry.
    """
    return {
        "id": str(entry.id),
        "actor_type": entry.actor_type,
        "actor_id": entry.actor_id,
        "action": entry.action,
        "resource_type": entry.resource_type or "",
        "resource_id": entry.resource_id or "",
        "details": json.dumps(entry.details) if entry.details else "{}",
        "company_id": str(entry.company_id) if entry.company_id else "",
        "timestamp": entry.timestamp.isoformat(),
    }


class AuditExporter:
    """Export and retention management for audit log entries.

    Provides thread-safe export of audit entries in JSON or CSV format,
    and applies retention policies to archive and purge old entries.

    Example:
        logger = AuditLogger()
        exporter = AuditExporter(logger)
        data = exporter.export_range(start, end, ExportFormat.JSON)
        exporter.apply_retention(RetentionPolicy(max_age_days=365, archive_after_days=90))
    """

    def __init__(self, audit_logger: AuditLogger) -> None:
        """Initialize the audit exporter.

        Args:
            audit_logger: The AuditLogger instance to export from.
        """
        self._logger = audit_logger
        self._lock = threading.Lock()
        self._archive: list[AuditEntry] = []

    def export_range(
        self,
        start: datetime,
        end: datetime,
        fmt: ExportFormat | str = ExportFormat.JSON,
    ) -> str:
        """Export audit entries within a date range.

        Uses a threading lock to ensure atomic reads and prevent
        partial data from concurrent modifications.

        Args:
            start: Start of the export range (inclusive).
            end: End of the export range (inclusive).
            fmt: Export format (json or csv).

        Returns:
            Formatted string containing the exported entries.

        Raises:
            ValueError: If start is after end or format is unsupported.
        """
        if isinstance(fmt, str):
            fmt = ExportFormat(fmt.lower())

        if start > end:
            raise ValueError("start must be before or equal to end")

        with self._lock:
            entries = [
                entry for entry in self._logger._entries
                if start <= entry.timestamp <= end
            ]

        if fmt == ExportFormat.JSON:
            return self._export_json(entries)
        elif fmt == ExportFormat.CSV:
            return self._export_csv(entries)
        else:
            raise ValueError(f"Unsupported format: {fmt}")

    def _export_json(self, entries: list[AuditEntry]) -> str:
        """Export entries as a JSON array.

        Args:
            entries: List of audit entries to export.

        Returns:
            JSON string.
        """
        records = [_entry_to_dict(entry) for entry in entries]
        return json.dumps(records, indent=2)

    def _export_csv(self, entries: list[AuditEntry]) -> str:
        """Export entries as CSV with headers.

        Args:
            entries: List of audit entries to export.

        Returns:
            CSV formatted string.
        """
        output = io.StringIO()
        fieldnames = [
            "id", "actor_type", "actor_id", "action",
            "resource_type", "resource_id", "details",
            "company_id", "timestamp",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for entry in entries:
            writer.writerow(_entry_to_dict(entry))

        return output.getvalue()

    def apply_retention(self, policy: RetentionPolicy) -> dict[str, int]:
        """Apply a retention policy to the audit log.

        Entries older than archive_after_days are moved to the archive.
        Entries older than max_age_days are purged entirely (from both
        active log and archive).

        Args:
            policy: The retention policy to apply.

        Returns:
            Dictionary with counts: archived, purged, remaining.
        """
        now = datetime.now(timezone.utc)
        archived_count = 0
        purged_count = 0

        with self._lock:
            remaining_entries: list[AuditEntry] = []

            for entry in self._logger._entries:
                age_days = (now - entry.timestamp).days

                if age_days >= policy.max_age_days:
                    purged_count += 1
                elif age_days >= policy.archive_after_days:
                    self._archive.append(entry)
                    archived_count += 1
                else:
                    remaining_entries.append(entry)

            self._logger._entries = remaining_entries

            # Also purge ancient entries from the archive
            archive_remaining: list[AuditEntry] = []
            for entry in self._archive:
                age_days = (now - entry.timestamp).days
                if age_days >= policy.max_age_days:
                    purged_count += 1
                else:
                    archive_remaining.append(entry)
            self._archive = archive_remaining

        return {
            "archived": archived_count,
            "purged": purged_count,
            "remaining": len(self._logger._entries),
        }

    def get_archive(self) -> list[AuditEntry]:
        """Return the archived entries.

        Returns:
            List of archived AuditEntry objects.
        """
        with self._lock:
            return list(self._archive)
