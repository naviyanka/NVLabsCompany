"""Database-backed L2/L3 for the layered memory system (Phase 2.3).

``LayeredMemoryStore`` keeps every layer in process memory (optionally mirrored
to a JSON file). This module backs the two layers that must outlive a process
with ``memory_records`` rows, so a fact promoted to L3 by one agent is visible
to a different agent after a restart.

Layer durability, and why it is split this way:

- **L0 (ephemeral)** is the caller's working set for a single turn. It is the
  live context window; persisting it would store a copy of data the caller
  already holds and is about to discard. Not stored here, by design.
- **L1 (session)** is a ring buffer of session summaries, bounded by
  ``l1_ring_size``. It is a *recency* cache: entries are evicted by age and are
  worthless once the session they summarise is over, so a DB round trip per
  turn buys nothing. Kept in memory by design; use
  ``LayeredMemoryStore(persist_path=...)`` if a session must survive a crash.
- **L2 (agent)** and **L3 (shared)** are durable knowledge. Both live in
  ``memory_records``, distinguished by ``scope`` (``l2_agent`` / ``l3_shared``),
  which keeps them disjoint from the 3-temperature ``MemoryStore`` rows that
  use scope values like ``agent`` and ``company`` in the same table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.memory.dedup import is_duplicate
from nexus.memory.layered import Fact, L1Summary, LayeredMemoryConfig, MemoryLayer
from nexus.memory.promotion import PromotionCriteria, PromotionEngine
from nexus.models.memory import MemoryRecord

L2_SCOPE = MemoryLayer.L2_AGENT.value
L3_SCOPE = MemoryLayer.L3_SHARED.value


def _to_fact(record: MemoryRecord) -> Fact:
    """Convert a ``memory_records`` row into a :class:`Fact`."""
    return Fact(
        content=record.content,
        source_agent_id=record.agent_id,
        created_at=record.created_at.replace(tzinfo=UTC),
        access_count=record.access_count,
        metadata=record.record_metadata,
    )


@dataclass
class PersistentLayeredMemory:
    """Layered memory with L2/L3 in the database and L1 in a ring buffer.

    Args:
        session_factory: Async session factory for ``memory_records`` access.
        company_id: Tenant the facts belong to. All reads and writes are
            scoped to it, so two companies never see each other's L3.
        config: Layer sizes and the dedup threshold. Defaults apply.
    """

    session_factory: async_sessionmaker[AsyncSession]
    company_id: uuid.UUID
    config: LayeredMemoryConfig | None = None

    def __post_init__(self) -> None:
        self.config = self.config or LayeredMemoryConfig()
        self._l1: list[L1Summary] = []

    # ── L1: in-memory ring buffer (see module docstring) ─────────────────────

    @property
    def l1_summaries(self) -> list[L1Summary]:
        """Return the current L1 session summaries (read-only view)."""
        return list(self._l1)

    def add_session_summary(self, task_id: uuid.UUID, summary: str) -> None:
        """Append a session summary, evicting the oldest when full."""
        if len(self._l1) >= self.config.l1_ring_size:
            self._l1.pop(0)
        self._l1.append(
            L1Summary(
                summary=summary,
                task_id=task_id,
                created_at=datetime.now(UTC),
            )
        )

    # ── L2: per-agent facts ──────────────────────────────────────────────────

    async def store_fact(
        self,
        agent_id: uuid.UUID,
        content: str,
        metadata: dict | None = None,
    ) -> bool:
        """Store an L2 fact for an agent, skipping near-duplicates.

        Dedup runs against the agent's rows in the database (2.3.3), not a
        process-local list, so a restarted process still recognises a
        duplicate. When the agent is at ``l2_max_facts``, the oldest row is
        deleted to make room.

        Returns:
            True if a row was written, False if it deduplicated away.
        """
        async with self.session_factory() as session:
            existing = list(
                (await session.execute(self._l2_query(agent_id))).scalars().all()
            )
            if is_duplicate(
                [_to_fact(r) for r in existing],
                content,
                self.config.dedup_similarity,
            ):
                return False

            overflow = len(existing) + 1 - self.config.l2_max_facts
            if overflow > 0:
                # Oldest first: the query is newest-first, so evict from the tail.
                for record in existing[-overflow:]:
                    await session.execute(
                        delete(MemoryRecord).where(MemoryRecord.id == record.id)
                    )

            session.add(
                MemoryRecord(
                    company_id=self.company_id,
                    agent_id=agent_id,
                    scope=L2_SCOPE,
                    scope_id=agent_id,
                    content=content,
                    record_metadata=metadata,
                )
            )
            await session.commit()
        return True

    async def get_agent_facts(
        self, agent_id: uuid.UUID, limit: int = 10
    ) -> list[Fact]:
        """Return an agent's most recent L2 facts, bumping their access count."""
        async with self.session_factory() as session:
            records = list(
                (
                    await session.execute(self._l2_query(agent_id).limit(limit))
                )
                .scalars()
                .all()
            )
            # Convert before the UPDATE: it synchronises the loaded objects,
            # so reading them afterwards would double-count this access.
            facts = [_to_fact(r) for r in records]
            if records:
                await session.execute(
                    update(MemoryRecord)
                    .where(MemoryRecord.id.in_([r.id for r in records]))
                    .values(
                        access_count=MemoryRecord.access_count + 1,
                        last_accessed_at=datetime.now(UTC).replace(
                            tzinfo=None
                        ),
                    )
                )
                await session.commit()

        for fact in facts:
            fact.access_count += 1
        return facts

    async def all_agent_facts(self) -> dict[uuid.UUID, list[Fact]]:
        """Return every agent's L2 facts, keyed by agent, for promotion scans."""
        async with self.session_factory() as session:
            records = (
                (
                    await session.execute(
                        select(MemoryRecord)
                        .where(MemoryRecord.company_id == self.company_id)
                        .where(MemoryRecord.scope == L2_SCOPE)
                        .order_by(MemoryRecord.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )

        grouped: dict[uuid.UUID, list[Fact]] = {}
        for record in records:
            if record.agent_id is None:
                continue
            grouped.setdefault(record.agent_id, []).append(_to_fact(record))
        return grouped

    # ── L3: shared knowledge ─────────────────────────────────────────────────

    async def get_shared_knowledge(self, limit: int = 10) -> list[Fact]:
        """Return the most recent shared (L3) facts for the company."""
        async with self.session_factory() as session:
            records = (
                (
                    await session.execute(
                        select(MemoryRecord)
                        .where(MemoryRecord.company_id == self.company_id)
                        .where(MemoryRecord.scope == L3_SCOPE)
                        .order_by(MemoryRecord.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [_to_fact(r) for r in records]

    async def promote_to_shared(self, agent_id: uuid.UUID, content: str) -> bool:
        """Copy one of an agent's L2 facts into L3.

        The L2 row is left in place so the agent keeps its own context. A fact
        already in L3 (by dedup similarity) is not written twice.

        Returns:
            True if a shared row was written, False if the agent has no such
            fact or L3 already holds an equivalent one.
        """
        async with self.session_factory() as session:
            source = (
                await session.execute(
                    self._l2_query(agent_id).where(MemoryRecord.content == content)
                )
            ).scalar_one_or_none()
            if source is None:
                return False

            if await self._l3_has(session, content):
                return False

            session.add(
                MemoryRecord(
                    company_id=self.company_id,
                    agent_id=source.agent_id,
                    scope=L3_SCOPE,
                    content=source.content,
                    record_metadata=source.record_metadata,
                    importance=source.importance,
                    access_count=source.access_count,
                )
            )
            await session.commit()
        return True

    async def run_promotion(
        self, criteria: PromotionCriteria | None = None
    ) -> list[Fact]:
        """Promote every eligible L2 fact to L3 and return what was written.

        Eligibility is :class:`PromotionEngine`'s (access count or cross-agent
        validation) evaluated over the facts in the database; each winner is
        deduplicated against existing L3 rows before insert (2.3.3).
        """
        criteria = criteria or PromotionCriteria()
        eligible = PromotionEngine().promote_eligible(
            await self.all_agent_facts(), criteria
        )

        promoted: list[Fact] = []
        async with self.session_factory() as session:
            for fact in eligible:
                if await self._l3_has(session, fact.content):
                    continue
                session.add(
                    MemoryRecord(
                        company_id=self.company_id,
                        agent_id=fact.source_agent_id,
                        scope=L3_SCOPE,
                        content=fact.content,
                        record_metadata=fact.metadata,
                        access_count=fact.access_count,
                    )
                )
                # Commit per fact so the next dedup check sees this one.
                await session.commit()
                promoted.append(fact)
        return promoted

    # ── Combined context ─────────────────────────────────────────────────────

    async def get_context_window(
        self, agent_id: uuid.UUID, limit: int = 20
    ) -> list[str]:
        """Build a context window from L1 + L2 + L3 (roughly 1/4, 1/2, 1/4)."""
        l1_limit = max(1, limit // 4)
        l3_limit = max(1, limit // 4)
        l2_limit = limit - l1_limit - l3_limit

        context = [
            f"[session] {s.summary}" for s in reversed(self._l1[-l1_limit:])
        ]
        context += [
            f"[agent] {f.content}"
            for f in await self.get_agent_facts(agent_id, limit=l2_limit)
        ]
        context += [
            f"[shared] {f.content}"
            for f in await self.get_shared_knowledge(limit=l3_limit)
        ]
        return context[:limit]

    # ── Internals ────────────────────────────────────────────────────────────

    def _l2_query(self, agent_id: uuid.UUID):
        """Newest-first select of one agent's L2 rows in this company."""
        return (
            select(MemoryRecord)
            .where(MemoryRecord.company_id == self.company_id)
            .where(MemoryRecord.scope == L2_SCOPE)
            .where(MemoryRecord.agent_id == agent_id)
            .order_by(MemoryRecord.created_at.desc())
        )

    async def _l3_has(self, session: AsyncSession, content: str) -> bool:
        """True when L3 already holds a fact similar enough to ``content``."""
        records = (
            (
                await session.execute(
                    select(MemoryRecord)
                    .where(MemoryRecord.company_id == self.company_id)
                    .where(MemoryRecord.scope == L3_SCOPE)
                )
            )
            .scalars()
            .all()
        )
        return is_duplicate(
            [_to_fact(r) for r in records], content, self.config.dedup_similarity
        )
