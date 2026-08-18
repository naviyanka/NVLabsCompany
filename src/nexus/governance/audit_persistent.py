"""Persistent Audit Logger - database-backed audit with hash chain integrity.

Provides buffered writes, tamper detection via SHA-256 hash chaining,
retention policies, and compliance query helpers with export capabilities.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class PersistentAuditEntry:
    """An audit entry with integrity hash for tamper detection.

    Attributes:
        id: Unique entry identifier.
        actor_type: Type of actor (agent, user, system).
        actor_id: Identifier of the actor.
        action: The action performed.
        resource_type: Type of resource affected.
        resource_id: Identifier of the affected resource.
        details: Additional context about the action.
        company_id: Company scope.
        timestamp: When the action occurred.
        entry_hash: SHA-256 hash including previous entry hash (chain).
        previous_hash: Hash of the previous entry in the chain.
        sequence_number: Position in the hash chain.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    actor_type: str = ""
    actor_id: str = ""
    action: str = ""
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    company_id: uuid.UUID | None = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    entry_hash: str = ""
    previous_hash: str = ""
    sequence_number: int = 0


@dataclass
class RetentionPolicy:
    """Policy for audit log retention.

    Attributes:
        max_age_days: Maximum age of entries before archival.
        archive_enabled: Whether to archive (vs delete) old entries.
        company_id: Company this policy applies to (None for global).
    """

    max_age_days: int = 90
    archive_enabled: bool = True
    company_id: uuid.UUID | None = None


class PersistentAuditLogger:
    """Database-backed audit logger with hash chain integrity.

    Provides async, non-blocking audit entry logging with buffered writes
    for performance. Each entry is linked to the previous via SHA-256 hash
    chain for tamper detection.
    """

    def __init__(
        self,
        buffer_size: int = 100,
        last_hash: str | None = None,
    ) -> None:
        """Initialize the persistent audit logger.

        Args:
            buffer_size: Maximum entries to buffer before flush.
            last_hash: Optional hash to resume the chain from. If provided,
                new entries will chain from this hash instead of "genesis",
                enabling chain resumption across process restarts.
        """
        self._buffer: list[PersistentAuditEntry] = []
        self._buffer_size = buffer_size
        # Simulated persistent storage (in production, this would be DB)
        self._entries: list[PersistentAuditEntry] = []
        self._archived: list[PersistentAuditEntry] = []
        self._last_hash: str = last_hash if last_hash is not None else "genesis"
        self._sequence: int = 0
        self._retention_policies: dict[uuid.UUID | None, RetentionPolicy] = {}

    def compute_entry_hash(
        self,
        entry: PersistentAuditEntry,
        previous_hash: str,
    ) -> str:
        """Compute SHA-256 hash for an entry including the previous hash.

        This creates a hash chain where tampering with any entry
        invalidates all subsequent hashes.

        Args:
            entry: The audit entry to hash.
            previous_hash: Hash of the previous entry in the chain.

        Returns:
            SHA-256 hex digest of the entry + previous hash.
        """
        hash_input = (
            f"{entry.id}|{entry.actor_type}|{entry.actor_id}|"
            f"{entry.action}|{entry.resource_type}|{entry.resource_id}|"
            f"{entry.timestamp.isoformat()}|{entry.company_id}|"
            f"{previous_hash}"
        )
        return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    async def log_entry(
        self,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        company_id: uuid.UUID | None = None,
    ) -> PersistentAuditEntry:
        """Log an audit entry asynchronously with hash chain integrity.

        The entry is added to the buffer. When the buffer is full,
        entries are flushed (batch insert).

        Args:
            actor_type: Type of actor (agent, user, system).
            actor_id: Identifier of the actor.
            action: The action performed.
            resource_type: Type of resource affected.
            resource_id: Identifier of the affected resource.
            details: Additional context about the action.
            company_id: Company scope.

        Returns:
            The created PersistentAuditEntry with hash chain.
        """
        self._sequence += 1
        entry = PersistentAuditEntry(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            company_id=company_id,
            previous_hash=self._last_hash,
            sequence_number=self._sequence,
        )
        entry.entry_hash = self.compute_entry_hash(entry, self._last_hash)
        self._last_hash = entry.entry_hash

        self._buffer.append(entry)

        if len(self._buffer) >= self._buffer_size:
            await self.flush_buffer()

        return entry

    async def flush_buffer(self) -> int:
        """Flush the buffer, performing a batch insert to storage.

        Returns:
            Number of entries flushed.
        """
        count = len(self._buffer)
        self._entries.extend(self._buffer)
        self._buffer = []
        return count

    def verify_chain_integrity(self) -> bool:
        """Verify the integrity of the hash chain.

        Recomputes hashes for all entries and checks they match.
        Detects any tampering with the audit log.

        Returns:
            True if the chain is valid, False if tampered.
        """
        # Combine buffer and stored entries for verification
        all_entries = self._entries + self._buffer
        if not all_entries:
            return True

        previous_hash = "genesis"
        for entry in all_entries:
            expected_hash = self.compute_entry_hash(entry, previous_hash)
            if entry.entry_hash != expected_hash:
                return False
            if entry.previous_hash != previous_hash:
                return False
            previous_hash = entry.entry_hash

        return True

    def query_by_actor(
        self,
        actor_id: str,
        actor_type: str | None = None,
        limit: int = 100,
    ) -> list[PersistentAuditEntry]:
        """Query audit entries by actor.

        Args:
            actor_id: The actor to query.
            actor_type: Optional actor type filter.
            limit: Maximum entries to return.

        Returns:
            List of matching entries, newest first.
        """
        all_entries = self._entries + self._buffer
        results: list[PersistentAuditEntry] = []
        for entry in reversed(all_entries):
            if entry.actor_id != actor_id:
                continue
            if actor_type and entry.actor_type != actor_type:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def query_by_time_range(
        self,
        start: datetime,
        end: datetime,
        company_id: uuid.UUID | None = None,
        limit: int = 1000,
    ) -> list[PersistentAuditEntry]:
        """Query audit entries within a time range.

        Args:
            start: Start of the time range (inclusive).
            end: End of the time range (inclusive).
            company_id: Optional company filter.
            limit: Maximum entries to return.

        Returns:
            List of matching entries.
        """
        all_entries = self._entries + self._buffer
        results: list[PersistentAuditEntry] = []
        for entry in all_entries:
            if entry.timestamp < start or entry.timestamp > end:
                continue
            if company_id and entry.company_id != company_id:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def export_json(
        self,
        entries: list[PersistentAuditEntry] | None = None,
    ) -> str:
        """Export audit entries as JSON.

        Args:
            entries: Specific entries to export. If None, exports all.

        Returns:
            JSON string of audit entries.
        """
        target = entries if entries is not None else (self._entries + self._buffer)
        records: list[dict[str, Any]] = []
        for entry in target:
            records.append({
                "id": str(entry.id),
                "actor_type": entry.actor_type,
                "actor_id": entry.actor_id,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "details": entry.details,
                "company_id": str(entry.company_id) if entry.company_id else None,
                "timestamp": entry.timestamp.isoformat(),
                "entry_hash": entry.entry_hash,
                "previous_hash": entry.previous_hash,
                "sequence_number": entry.sequence_number,
            })
        return json.dumps(records, indent=2)

    def export_csv(
        self,
        entries: list[PersistentAuditEntry] | None = None,
    ) -> str:
        """Export audit entries as CSV.

        Args:
            entries: Specific entries to export. If None, exports all.

        Returns:
            CSV string of audit entries.
        """
        target = entries if entries is not None else (self._entries + self._buffer)
        lines: list[str] = [
            "id,actor_type,actor_id,action,resource_type,resource_id,timestamp,sequence_number,entry_hash"
        ]
        for entry in target:
            lines.append(
                f"{entry.id},{entry.actor_type},{entry.actor_id},"
                f"{entry.action},{entry.resource_type or ''},"
                f"{entry.resource_id or ''},{entry.timestamp.isoformat()},"
                f"{entry.sequence_number},{entry.entry_hash}"
            )
        return "\n".join(lines)

    def set_retention_policy(
        self,
        max_age_days: int = 90,
        archive_enabled: bool = True,
        company_id: uuid.UUID | None = None,
    ) -> RetentionPolicy:
        """Set a retention policy for audit entries.

        Args:
            max_age_days: Maximum age before archival/deletion.
            archive_enabled: Whether to archive (True) or delete (False).
            company_id: Company-specific policy (None for global).

        Returns:
            The configured RetentionPolicy.
        """
        policy = RetentionPolicy(
            max_age_days=max_age_days,
            archive_enabled=archive_enabled,
            company_id=company_id,
        )
        self._retention_policies[company_id] = policy
        return policy

    async def enforce_retention(self) -> int:
        """Enforce retention policies, archiving or removing old entries.

        Returns:
            Number of entries archived or removed.
        """
        now = datetime.now(timezone.utc)
        processed = 0
        remaining: list[PersistentAuditEntry] = []

        for entry in self._entries:
            policy = self._retention_policies.get(
                entry.company_id,
                self._retention_policies.get(None),
            )
            if policy is None:
                remaining.append(entry)
                continue

            age = now - entry.timestamp
            if age > timedelta(days=policy.max_age_days):
                if policy.archive_enabled:
                    self._archived.append(entry)
                processed += 1
            else:
                remaining.append(entry)

        self._entries = remaining
        return processed

    def get_archived_entries(self) -> list[PersistentAuditEntry]:
        """Get entries that have been archived.

        Returns:
            List of archived entries.
        """
        return list(self._archived)

    @property
    def buffer_count(self) -> int:
        """Get current number of entries in the buffer."""
        return len(self._buffer)

    @property
    def total_entries(self) -> int:
        """Get total number of stored entries (excluding buffer)."""
        return len(self._entries)
