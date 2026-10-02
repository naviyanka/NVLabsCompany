"""3-Temperature Memory Store - hot (dict), warm (PostgreSQL), cold (JSON archive)."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.memory.ingest import (
    MemoryContext,
    MemoryInput,
    Origin,
    clean_user_metadata,
    ingest_memory,
)
from nexus.memory.safety import redact_text, sanitize_value
from nexus.models.memory import PROMPT_STATUSES, MemoryRecord


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

    def _cache_key(
        self, company_id: uuid.UUID, scope: str, scope_id: uuid.UUID | None
    ) -> str:
        """Generate a cache key for the hot tier; the company keeps tenants apart."""
        return f"{company_id}:{scope}:{scope_id or 'global'}"

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
            company_id: The company that owns the memory. Required.
            agent_id: The agent that owns this memory.
            importance: Importance score (0.0 to 1.0).

        Returns:
            The UUID string of the stored memory.

        Raises:
            ValueError: If ``company_id`` is missing or the scope is executive.
        """
        if company_id is None:
            raise ValueError("company_id is required to store a memory")
        if scope == "executive":
            # Executive memory is written only by nexus.services.ceo_service.
            raise ValueError("executive memory is recorded through the CEO service")
        memory_id = uuid.uuid4()

        # Warm tier goes through the canonical ingest path (redacted, hashed, sourced).
        result = await ingest_memory(
            self._db,
            MemoryContext(company_id, f"agent:{agent_id}" if agent_id else "system:memory-store"),
            MemoryInput(
                scope=scope,
                content=content,
                agent_id=agent_id,
                scope_id=scope_id,
                importance=importance,
                tier="warm",
                metadata=metadata,
                record_id=memory_id,
                extractor_version="memory-store-v1",
            ),
            Origin.SYSTEM,
        )
        content = result.record.content  # what was stored: redacted and normalized
        metadata = clean_user_metadata(result.record.record_metadata)
        memory_id = result.record.id

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
        key = self._cache_key(company_id, scope, scope_id)
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
        company_id: uuid.UUID | None = None,
    ) -> list[MemoryRecord]:
        """Retrieve memories from all tiers, starting with hot.

        Checks hot cache first, then falls back to warm (database).
        Cold tier is not searched directly; use promote() first.

        Args:
            scope: Memory scope to search.
            scope_id: The ID of the scope entity.
            query: Optional text query for filtering.
            limit: Maximum number of results.
            company_id: The company whose memories to read. Required.

        Returns:
            List of MemoryRecord instances.

        Raises:
            ValueError: If ``company_id`` is missing.
        """
        if company_id is None:
            raise ValueError("company_id is required to retrieve memories")
        results: list[MemoryRecord] = []

        # Check hot tier first
        key = self._cache_key(company_id, scope, scope_id)
        hot_entries = self._hot.get(key, [])
        if hot_entries:
            # The cache outlives lifecycle changes: keep only entries still active in this company.
            live = set(
                (await self._db.execute(
                    select(MemoryRecord.id).where(
                        MemoryRecord.company_id == company_id,
                        MemoryRecord.id.in_([e.id for e in hot_entries]),
                        MemoryRecord.status.in_(PROMPT_STATUSES),
                    )
                )).scalars().all()
            )
            hot_entries = [e for e in hot_entries if e.id in live]
        if hot_entries:
            for entry in hot_entries[:limit]:
                record = MemoryRecord(
                    id=entry.id,
                    company_id=company_id,
                    scope=entry.scope,
                    scope_id=entry.scope_id,
                    content=entry.content,
                    record_metadata=entry.metadata,
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
                .where(MemoryRecord.company_id == company_id)
                .where(MemoryRecord.scope == scope)
                .where(MemoryRecord.tier == "warm")
                .where(MemoryRecord.status.in_(PROMPT_STATUSES))
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

    @staticmethod
    def _require_company(company_id: uuid.UUID | None) -> uuid.UUID:
        if company_id is None:
            raise ValueError("company_id is required")
        return company_id if isinstance(company_id, uuid.UUID) else uuid.UUID(str(company_id))

    def _cold_file(self, company_id: uuid.UUID, memory_id: uuid.UUID) -> Path:
        """The cold file for a memory: ``<cold>/<company>/<memory>.json``.

        Both ids are parsed as UUIDs, so neither can carry a separator or ``..``; the
        resolved path is still checked to sit inside the company's own directory.
        """
        company_id = self._require_company(company_id)
        memory_id = memory_id if isinstance(memory_id, uuid.UUID) else uuid.UUID(str(memory_id))
        company_dir = (self._cold_path / str(company_id)).resolve()
        path = (company_dir / f"{memory_id}.json").resolve()
        if not path.is_relative_to(company_dir):
            raise ValueError("cold path escapes the company directory")
        return path

    async def _owned_record(
        self, company_id: uuid.UUID, memory_id: uuid.UUID, tier: str | None = None
    ) -> MemoryRecord | None:
        """The memory if it belongs to ``company_id``; another company's id reads as absent."""
        stmt = select(MemoryRecord).where(
            MemoryRecord.id == memory_id, MemoryRecord.company_id == company_id
        )
        if tier is not None:
            stmt = stmt.where(MemoryRecord.tier == tier)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def promote(self, memory_id: uuid.UUID, company_id: uuid.UUID | None = None) -> str:
        """Promote one of ``company_id``'s memories to a hotter tier: cold -> warm -> hot.

        Raises:
            ValueError: If ``company_id`` is missing, or the memory is not that company's.
        """
        company_id = self._require_company(company_id)
        prefix = f"{company_id}:"
        for key, entries in self._hot.items():
            if key.startswith(prefix) and any(e.id == memory_id for e in entries):
                return "hot"  # Already at hottest tier

        record = await self._owned_record(company_id, memory_id)
        if record is not None:
            if record.status not in PROMPT_STATUSES:
                # A closed or unreviewed row is never warmed or cached for recall.
                raise ValueError(f"Memory {memory_id} not found in any tier")
            if record.tier == "warm":
                entry = MemoryEntry(
                    id=record.id,
                    scope=record.scope,
                    scope_id=record.scope_id,
                    content=record.content,
                    metadata=record.record_metadata,
                    importance=record.importance,
                    access_count=record.access_count,
                    tier="hot",
                    created_at=record.created_at,
                )
                key = self._cache_key(company_id, record.scope, record.scope_id)
                self._hot.setdefault(key, []).append(entry)
                return "hot"
            if record.tier == "cold":
                await self._db.execute(
                    update(MemoryRecord)
                    .where(MemoryRecord.id == memory_id, MemoryRecord.company_id == company_id)
                    .values(tier="warm", updated_at=datetime.now(timezone.utc))
                )
                return "warm"
            raise ValueError(f"Memory {memory_id} not found in any tier")

        # A file exists only for a memory that was archived from this company's rows.
        cold_record = await self._load_from_cold(memory_id, company_id)
        if cold_record:
            await ingest_memory(
                self._db,
                MemoryContext(company_id, "system:cold-restore"),
                MemoryInput(
                    scope=cold_record["scope"],
                    content=cold_record["content"],
                    agent_id=(
                        uuid.UUID(cold_record["agent_id"]) if cold_record.get("agent_id") else None
                    ),
                    scope_id=(
                        uuid.UUID(cold_record["scope_id"]) if cold_record.get("scope_id") else None
                    ),
                    importance=cold_record.get("importance", 0.5),
                    tier="warm",
                    metadata=clean_user_metadata(cold_record.get("metadata")),
                    source_type="cold_archive",
                    source_id=str(cold_record["id"]),
                    extractor_version="cold-restore-v1",
                    record_id=cold_record["id"],
                ),
                Origin.SYSTEM,
            )
            return "warm"

        raise ValueError(f"Memory {memory_id} not found in any tier")

    async def demote(self, memory_id: uuid.UUID, company_id: uuid.UUID | None = None) -> str:
        """Demote one of ``company_id``'s memories to a colder tier: hot -> warm -> cold.

        Raises:
            ValueError: If ``company_id`` is missing, or the memory is not that company's.
        """
        company_id = self._require_company(company_id)
        prefix = f"{company_id}:"
        for key, entries in list(self._hot.items()):
            if not key.startswith(prefix):
                continue
            for i, entry in enumerate(entries):
                if entry.id == memory_id:
                    entries.pop(i)
                    if not entries:
                        del self._hot[key]
                    return "warm"

        record = await self._owned_record(company_id, memory_id, tier="warm")
        if record is None:
            raise ValueError(f"Memory {memory_id} not found or already at coldest tier")
        await self._save_to_cold(record)
        await self._db.execute(
            update(MemoryRecord)
            .where(MemoryRecord.id == memory_id, MemoryRecord.company_id == company_id)
            .values(tier="cold", updated_at=datetime.now(timezone.utc))
        )
        return "cold"

    async def archive_old(
        self, threshold_days: int = 30, company_id: uuid.UUID | None = None
    ) -> int:
        """Bulk demote ``company_id``'s old warm memories to cold. Returns how many.

        Raises:
            ValueError: If ``company_id`` is missing.
        """
        from datetime import timedelta

        company_id = self._require_company(company_id)
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)
        result = await self._db.execute(
            select(MemoryRecord).where(
                MemoryRecord.company_id == company_id,
                MemoryRecord.tier == "warm",
                MemoryRecord.created_at < cutoff,
            )
        )
        old_records = result.scalars().all()
        for record in old_records:
            await self._save_to_cold(record)
        if old_records:
            await self._db.execute(
                update(MemoryRecord)
                .where(
                    MemoryRecord.company_id == company_id,
                    MemoryRecord.id.in_([r.id for r in old_records]),
                )
                .values(tier="cold", updated_at=datetime.now(timezone.utc))
            )
        return len(old_records)

    async def _save_to_cold(self, record: MemoryRecord) -> None:
        """Write a memory to its company's cold directory, redacted first."""
        path = self._cold_file(record.company_id, record.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata, _ = sanitize_value(record.record_metadata or {})
        data = {
            "id": str(record.id),
            "company_id": str(record.company_id),
            "agent_id": str(record.agent_id) if record.agent_id else None,
            "scope": record.scope,
            "scope_id": str(record.scope_id) if record.scope_id else None,
            "content": redact_text(record.content)[0],
            "metadata": metadata,
            "importance": record.importance,
            "access_count": record.access_count,
            "tier": "cold",
            "created_at": record.created_at.isoformat(),
        }
        path.write_text(json.dumps(data, indent=2))

    async def _load_from_cold(
        self, memory_id: uuid.UUID, company_id: uuid.UUID | None = None
    ) -> dict[str, Any] | None:
        """Load a memory from ``company_id``'s cold directory, or None.

        A file whose recorded company differs from the directory it sits in is ignored.
        """
        company_id = self._require_company(company_id)
        path = self._cold_file(company_id, memory_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if data.get("company_id") != str(company_id):
            return None
        data["id"] = uuid.UUID(data["id"])
        return data
