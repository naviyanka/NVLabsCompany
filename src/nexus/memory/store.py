"""3-Temperature Memory Store - hot (dict), warm (PostgreSQL), cold (JSON archive)."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.memory import MemoryRecord


@dataclass
class MemoryEntry:
    """In-memory representation of a memory record."""

    id: uuid.UUID
    scope: str
    scope_id: uuid.UUID | None
    content: str
    metadata: dict[str, Any] | None = None
    importance: float = 0.5
    access_count: int = 0
    tier: str = "hot"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class MemoryStore:
    """Three-temperature memory store implementing tiered storage.

    Architecture:
    - Hot tier: In-memory dict for frequently accessed memories (fastest).
    - Warm tier: PostgreSQL for moderately accessed memories (durable).
    - Cold tier: JSON file archive for rarely accessed memories (cheapest).

    Memories flow between tiers through promote/demote operations:
    - promote: cold -> warm -> hot
    - demote: hot -> warm -> cold
    - archive_old: bulk demote warm -> cold based on age threshold
    """

    def __init__(
        self,
        db: AsyncSession,
        cold_storage_path: Path | None = None,
    ) -> None:
        """Initialize the memory store.

        Args:
            db: Async database session for warm tier operations.
            cold_storage_path: Path for cold storage JSON files.
                Defaults to ./data/cold_memory/ if not specified.
        """
        self._db = db
        self._hot: dict[str, list[MemoryEntry]] = {}
        self._cold_path = cold_storage_path or Path("data/cold_memory")

    def _cache_key(self, scope: str, scope_id: uuid.UUID | None) -> str:
        """Generate a cache key for the hot tier."""
        return f"{scope}:{scope_id or 'global'}"

    async def store(
        self,
        scope: str,
        scope_id: uuid.UUID | None,
        content: str,
        metadata: dict[str, Any] | None = None,
        company_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        importance: float = 0.5,
    ) -> str:
        """Store a memory in the warm tier (PostgreSQL) and hot cache.

        Args:
            scope: Memory scope (agent, team, department, company).
            scope_id: The ID of the scope entity.
            content: The memory content text.
            metadata: Optional metadata dictionary.
            company_id: The company for tenant isolation.
            agent_id: The agent that owns this memory.
            importance: Importance score (0.0 to 1.0).

        Returns:
            The UUID string of the stored memory.
        """
        memory_id = uuid.uuid4()

        # Store in warm tier (database)
        record = MemoryRecord(
            id=memory_id,
            company_id=company_id or uuid.UUID(int=0),
            agent_id=agent_id,
            scope=scope,
            scope_id=scope_id,
            content=content,
            metadata=metadata,
            importance=importance,
            tier="warm",
        )
        self._db.add(record)
        await self._db.flush()

        # Also add to hot cache
        entry = MemoryEntry(
            id=memory_id,
            scope=scope,
            scope_id=scope_id,
            content=content,
            metadata=metadata,
            importance=importance,
            tier="hot",
        )
        key = self._cache_key(scope, scope_id)
        if key not in self._hot:
            self._hot[key] = []
        self._hot[key].append(entry)

        return str(memory_id)

    async def retrieve(
        self,
        scope: str,
        scope_id: uuid.UUID | None,
        query: str | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Retrieve memories from all tiers, starting with hot.

        Checks hot cache first, then falls back to warm (database).
        Cold tier is not searched directly; use promote() first.

        Args:
            scope: Memory scope to search.
            scope_id: The ID of the scope entity.
            query: Optional text query for filtering.
            limit: Maximum number of results.

        Returns:
            List of MemoryRecord instances.
        """
        results: list[MemoryRecord] = []

        # Check hot tier first
        key = self._cache_key(scope, scope_id)
        hot_entries = self._hot.get(key, [])
        if hot_entries:
            for entry in hot_entries[:limit]:
                record = MemoryRecord(
                    id=entry.id,
                    company_id=uuid.UUID(int=0),
                    scope=entry.scope,
                    scope_id=entry.scope_id,
                    content=entry.content,
                    metadata=entry.metadata,
                    importance=entry.importance,
                    access_count=entry.access_count,
                    tier="hot",
                    created_at=entry.created_at,
                )
                results.append(record)

        # If we need more, query warm tier
        if len(results) < limit:
            remaining = limit - len(results)
            hot_ids = {entry.id for entry in hot_entries}

            stmt = (
                select(MemoryRecord)
                .where(MemoryRecord.scope == scope)
                .where(MemoryRecord.tier == "warm")
            )
            if scope_id:
                stmt = stmt.where(MemoryRecord.scope_id == scope_id)

            stmt = stmt.order_by(MemoryRecord.importance.desc()).limit(remaining)
            result = await self._db.execute(stmt)
            warm_records = result.scalars().all()

            for record in warm_records:
                if record.id not in hot_ids:
                    results.append(record)

        return results[:limit]

    async def promote(self, memory_id: uuid.UUID) -> str:
        """Promote a memory to a hotter tier: cold -> warm -> hot.

        Args:
            memory_id: The memory to promote.

        Returns:
            The new tier name after promotion.
        """
        # Check if already in hot cache
        for entries in self._hot.values():
            for entry in entries:
                if entry.id == memory_id:
                    return "hot"  # Already at hottest tier

        # Check warm tier
        stmt = select(MemoryRecord).where(MemoryRecord.id == memory_id)
        result = await self._db.execute(stmt)
        record = result.scalar_one_or_none()

        if record is not None:
            if record.tier == "warm":
                # Promote warm -> hot
                entry = MemoryEntry(
                    id=record.id,
                    scope=record.scope,
                    scope_id=record.scope_id,
                    content=record.content,
                    metadata=record.metadata,
                    importance=record.importance,
                    access_count=record.access_count,
                    tier="hot",
                    created_at=record.created_at,
                )
                key = self._cache_key(record.scope, record.scope_id)
                if key not in self._hot:
                    self._hot[key] = []
                self._hot[key].append(entry)
                return "hot"
            elif record.tier == "cold":
                # Promote cold -> warm
                update_stmt = (
                    update(MemoryRecord)
                    .where(MemoryRecord.id == memory_id)
                    .values(tier="warm", updated_at=datetime.now(timezone.utc))
                )
                await self._db.execute(update_stmt)
                return "warm"

        # Try cold storage (JSON files)
        cold_record = await self._load_from_cold(memory_id)
        if cold_record:
            # Promote cold -> warm by inserting into database
            new_record = MemoryRecord(
                id=cold_record["id"],
                company_id=uuid.UUID(cold_record["company_id"]),
                scope=cold_record["scope"],
                scope_id=(
                    uuid.UUID(cold_record["scope_id"])
                    if cold_record.get("scope_id")
                    else None
                ),
                content=cold_record["content"],
                metadata=cold_record.get("metadata"),
                importance=cold_record.get("importance", 0.5),
                tier="warm",
            )
            self._db.add(new_record)
            await self._db.flush()
            return "warm"

        raise ValueError(f"Memory {memory_id} not found in any tier")

    async def demote(self, memory_id: uuid.UUID) -> str:
        """Demote a memory to a colder tier: hot -> warm -> cold.

        Args:
            memory_id: The memory to demote.

        Returns:
            The new tier name after demotion.
        """
        # Check hot tier
        for key, entries in self._hot.items():
            for i, entry in enumerate(entries):
                if entry.id == memory_id:
                    # Demote hot -> warm (remove from hot cache)
                    entries.pop(i)
                    if not entries:
                        del self._hot[key]
                    return "warm"

        # Check warm tier
        stmt = select(MemoryRecord).where(
            MemoryRecord.id == memory_id,
            MemoryRecord.tier == "warm",
        )
        result = await self._db.execute(stmt)
        record = result.scalar_one_or_none()

        if record is not None:
            # Demote warm -> cold (archive to JSON, update tier)
            await self._save_to_cold(record)
            update_stmt = (
                update(MemoryRecord)
                .where(MemoryRecord.id == memory_id)
                .values(tier="cold", updated_at=datetime.now(timezone.utc))
            )
            await self._db.execute(update_stmt)
            return "cold"

        raise ValueError(f"Memory {memory_id} not found or already at coldest tier")

    async def archive_old(self, threshold_days: int = 30) -> int:
        """Bulk demote old warm memories to cold tier.

        Args:
            threshold_days: Memories older than this many days get archived.

        Returns:
            Number of memories archived.
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)

        # Find old warm memories
        stmt = select(MemoryRecord).where(
            MemoryRecord.tier == "warm",
            MemoryRecord.created_at < cutoff,
        )
        result = await self._db.execute(stmt)
        old_records = result.scalars().all()

        archived_count = 0
        for record in old_records:
            await self._save_to_cold(record)
            archived_count += 1

        # Bulk update tier
        if old_records:
            update_stmt = (
                update(MemoryRecord)
                .where(
                    MemoryRecord.tier == "warm",
                    MemoryRecord.created_at < cutoff,
                )
                .values(tier="cold", updated_at=datetime.now(timezone.utc))
            )
            await self._db.execute(update_stmt)

        return archived_count

    async def _save_to_cold(self, record: MemoryRecord) -> None:
        """Save a memory record to cold JSON storage.

        Args:
            record: The MemoryRecord to archive.
        """
        self._cold_path.mkdir(parents=True, exist_ok=True)
        file_path = self._cold_path / f"{record.id}.json"

        data = {
            "id": str(record.id),
            "company_id": str(record.company_id),
            "agent_id": str(record.agent_id) if record.agent_id else None,
            "scope": record.scope,
            "scope_id": str(record.scope_id) if record.scope_id else None,
            "content": record.content,
            "metadata": record.metadata,
            "importance": record.importance,
            "access_count": record.access_count,
            "tier": "cold",
            "created_at": record.created_at.isoformat(),
        }
        file_path.write_text(json.dumps(data, indent=2))

    async def _load_from_cold(self, memory_id: uuid.UUID) -> dict[str, Any] | None:
        """Load a memory from cold JSON storage.

        Args:
            memory_id: The memory to load.

        Returns:
            Dictionary with memory data, or None if not found.
        """
        file_path = self._cold_path / f"{memory_id}.json"
        if file_path.exists():
            data = json.loads(file_path.read_text())
            data["id"] = uuid.UUID(data["id"])
            return data
        return None
