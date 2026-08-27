"""Persistent Audit Logger - database-backed audit with hash chain integrity.

Entries are written to the `audit_log` table (append-only, guarded by a DB
trigger). Tamper detection uses SHA-256 hash chaining ordered by
`sequence_number`; retention copies rows to `audit_log_archive` and marks the
source row archived rather than deleting from the verified chain.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlmodel import select

from nexus.models.governance import AuditLog, AuditLogArchive


def _utcnaive() -> datetime:
    """UTC now as a naive datetime (project-wide DB storage convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        timestamp: When the action occurred (naive UTC).
        entry_hash: SHA-256 hash including previous entry hash (chain).
        previous_hash: Hash of the previous entry in the chain.
        sequence_number: Position in the hash chain.
        archived_at: Set when retention copied the row to the archive.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    actor_type: str = ""
    actor_id: str = ""
    action: str = ""
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    company_id: uuid.UUID | None = None
    timestamp: datetime = field(default_factory=_utcnaive)
    entry_hash: str = ""
    previous_hash: str = ""
    sequence_number: int = 0
    archived_at: datetime | None = None

    @classmethod
    def from_row(cls, row: AuditLog) -> "PersistentAuditEntry":
        """Build an entry from an `audit_log` row."""
        return cls(
            id=row.id,
            actor_type=row.actor_type,
            actor_id=row.actor_id or "",
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            details=row.details or {},
            company_id=row.company_id,
            timestamp=row.created_at,
            entry_hash=row.entry_hash or "",
            previous_hash=row.previous_hash or "",
            sequence_number=row.sequence_number or 0,
            archived_at=row.archived_at,
        )

    def to_row(self) -> AuditLog:
        """Build an `audit_log` row from this entry."""
        return AuditLog(
            id=self.id,
            company_id=self.company_id,
            actor_type=self.actor_type,
            actor_id=self.actor_id or None,
            action=self.action,
            resource_type=self.resource_type,
            resource_id=self.resource_id,
            details=self.details or None,
            created_at=self.timestamp,
            sequence_number=self.sequence_number,
            entry_hash=self.entry_hash,
            previous_hash=self.previous_hash,
        )


def compute_entry_hash(entry: PersistentAuditEntry, previous_hash: str) -> str:
    """Compute SHA-256 hash for an entry including the previous hash.

    This creates a hash chain where tampering with any entry invalidates all
    subsequent hashes. Module-level so every writer of `audit_log` (the
    buffered logger and `audit_service.record_audit`) hashes identically.

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


@dataclass
class RetentionPolicy:
    """Policy for audit log retention.

    Attributes:
        max_age_days: Maximum age of entries before archival.
        archive_enabled: Whether to archive old entries.
        company_id: Company this policy applies to (None for global).
    """

    max_age_days: int = 90
    archive_enabled: bool = True
    company_id: uuid.UUID | None = None


class PersistentAuditLogger:
    """Database-backed audit logger with hash chain integrity.

    Buffers entries in memory and batch-inserts them into `audit_log`. Each
    entry is linked to the previous via SHA-256 hash chain for tamper
    detection. Call `resume()` once after construction to continue the chain
    from whatever is already in the database.
    """

    def __init__(
        self,
        buffer_size: int = 100,
        last_hash: str | None = None,
        session_factory: Any | None = None,
    ) -> None:
        """Initialize the persistent audit logger.

        Args:
            buffer_size: Maximum entries to buffer before flush.
            last_hash: Optional hash to resume the chain from. If provided,
                new entries will chain from this hash instead of "genesis".
            session_factory: Async session factory to use. Defaults to the
                application factory from `nexus.database`.
        """
        self._buffer: list[PersistentAuditEntry] = []
        self._buffer_size = buffer_size
        self._last_hash: str = last_hash if last_hash is not None else "genesis"
        self._sequence: int = 0
        self._retention_policies: dict[uuid.UUID | None, RetentionPolicy] = {}
        self._session_factory = session_factory

    def _sessions(self) -> Any:
        """Return the async session factory, resolved lazily."""
        if self._session_factory is None:
            from nexus.database import async_session_factory

            self._session_factory = async_session_factory
        return self._session_factory

    async def resume(self) -> int:
        """Load the chain tail from the database so logging can continue.

        Returns:
            The sequence number of the last persisted entry (0 if empty).
        """
        async with self._sessions()() as session:
            result = await session.execute(
                select(AuditLog)
                .where(AuditLog.sequence_number.is_not(None))
                .order_by(AuditLog.sequence_number.desc())
                .limit(1)
            )
            row = result.scalars().first()

        if row is not None:
            self._sequence = row.sequence_number or 0
            self._last_hash = row.entry_hash or "genesis"
        return self._sequence

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
        return compute_entry_hash(entry, previous_hash)

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
        entries are inserted into `audit_log` as a batch.

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
        """Flush the buffer, performing a batch INSERT into `audit_log`.

        Returns:
            Number of entries flushed.
        """
        if not self._buffer:
            return 0

        pending = self._buffer
        async with self._sessions()() as session:
            for entry in pending:
                session.add(entry.to_row())
            await session.commit()

        self._buffer = []
        return len(pending)

    async def verify_chain_integrity(self) -> bool:
        """Verify the integrity of the persisted hash chain.

        Reads `audit_log` ordered by `sequence_number`, recomputes each hash,
        and checks it matches. Detects any tampering with the audit log.
        Unflushed buffer entries are verified after the persisted tail.

        Returns:
            True if the chain is valid, False if tampered.
        """
        async with self._sessions()() as session:
            result = await session.execute(
                select(AuditLog)
                .where(AuditLog.sequence_number.is_not(None))
                .order_by(AuditLog.sequence_number)
            )
            rows = result.scalars().all()

        stored = [PersistentAuditEntry.from_row(row) for row in rows]
        all_entries = stored + self._buffer
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

    async def _fetch_all(self) -> list[PersistentAuditEntry]:
        """Read every persisted entry in chain order, then buffered entries."""
        async with self._sessions()() as session:
            result = await session.execute(
                select(AuditLog).order_by(
                    AuditLog.sequence_number, AuditLog.created_at
                )
            )
            rows = result.scalars().all()
        return [PersistentAuditEntry.from_row(row) for row in rows] + list(
            self._buffer
        )

    async def query_by_actor(
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
        statement = select(AuditLog).where(AuditLog.actor_id == actor_id)
        if actor_type:
            statement = statement.where(AuditLog.actor_type == actor_type)
        statement = statement.order_by(AuditLog.sequence_number.desc()).limit(limit)

        async with self._sessions()() as session:
            result = await session.execute(statement)
            rows = result.scalars().all()

        results = [PersistentAuditEntry.from_row(row) for row in rows]
        # Include buffered (not yet flushed) entries, newest first.
        for entry in reversed(self._buffer):
            if len(results) >= limit:
                break
            if entry.actor_id != actor_id:
                continue
            if actor_type and entry.actor_type != actor_type:
                continue
            results.insert(0, entry)
        return results[:limit]

    async def query_by_time_range(
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
        start_naive = start.replace(tzinfo=None) if start.tzinfo else start
        end_naive = end.replace(tzinfo=None) if end.tzinfo else end

        results: list[PersistentAuditEntry] = []
        for entry in await self._fetch_all():
            if entry.timestamp < start_naive or entry.timestamp > end_naive:
                continue
            if company_id and entry.company_id != company_id:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    async def export_json(
        self,
        entries: list[PersistentAuditEntry] | None = None,
    ) -> str:
        """Export audit entries as JSON.

        Args:
            entries: Specific entries to export. If None, exports all.

        Returns:
            JSON string of audit entries.
        """
        target = entries if entries is not None else await self._fetch_all()
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

    async def export_csv(
        self,
        entries: list[PersistentAuditEntry] | None = None,
    ) -> str:
        """Export audit entries as CSV.

        Args:
            entries: Specific entries to export. If None, exports all.

        Returns:
            CSV string of audit entries.
        """
        target = entries if entries is not None else await self._fetch_all()
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
            max_age_days: Maximum age before archival.
            archive_enabled: Whether to copy old entries to the archive.
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
        """Enforce retention policies by archiving old entries.

        Rows are copied into `audit_log_archive` and stamped with
        `archived_at` in place. Nothing is ever deleted from `audit_log`, so
        the hash chain stays verifiable.

        Returns:
            Number of entries archived.
        """
        now = _utcnaive()
        processed = 0

        async with self._sessions()() as session:
            result = await session.execute(
                select(AuditLog).where(AuditLog.archived_at.is_(None))
            )
            rows = result.scalars().all()

            for row in rows:
                policy = self._retention_policies.get(
                    row.company_id,
                    self._retention_policies.get(None),
                )
                if policy is None or not policy.archive_enabled:
                    continue

                if now - row.created_at <= timedelta(days=policy.max_age_days):
                    continue

                session.add(
                    AuditLogArchive(
                        id=row.id,
                        company_id=row.company_id,
                        actor_type=row.actor_type,
                        actor_id=row.actor_id,
                        action=row.action,
                        resource_type=row.resource_type,
                        resource_id=row.resource_id,
                        details=row.details,
                        ip_address=row.ip_address,
                        created_at=row.created_at,
                        sequence_number=row.sequence_number,
                        entry_hash=row.entry_hash,
                        previous_hash=row.previous_hash,
                        archived_at=now,
                    )
                )
                row.archived_at = now
                session.add(row)
                processed += 1

            await session.commit()

        return processed

    async def get_archived_entries(self) -> list[PersistentAuditEntry]:
        """Get entries that have been archived.

        Returns:
            List of archived entries.
        """
        async with self._sessions()() as session:
            result = await session.execute(
                select(AuditLogArchive).order_by(AuditLogArchive.sequence_number)
            )
            rows = result.scalars().all()

        return [
            PersistentAuditEntry(
                id=row.id,
                actor_type=row.actor_type,
                actor_id=row.actor_id or "",
                action=row.action,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                details=row.details or {},
                company_id=row.company_id,
                timestamp=row.created_at,
                entry_hash=row.entry_hash or "",
                previous_hash=row.previous_hash or "",
                sequence_number=row.sequence_number or 0,
                archived_at=row.archived_at,
            )
            for row in rows
        ]

    @property
    def buffer_count(self) -> int:
        """Get current number of entries in the buffer."""
        return len(self._buffer)

    async def total_entries(self) -> int:
        """Count persisted entries in `audit_log` (excluding the buffer)."""
        async with self._sessions()() as session:
            result = await session.execute(select(func.count()).select_from(AuditLog))
            return int(result.scalar() or 0)

    async def active_entries(self) -> int:
        """Count persisted entries that have not been archived."""
        async with self._sessions()() as session:
            result = await session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.archived_at.is_(None))
            )
            return int(result.scalar() or 0)
