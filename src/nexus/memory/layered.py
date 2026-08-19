"""4-Layer Memory System (L0-L3) for intelligent knowledge management.

Provides a higher-level memory abstraction alongside the existing 3-temperature
MemoryStore. Layers represent different scopes of knowledge:

- L0 (Ephemeral): Caller-managed working memory (not stored here).
- L1 (Session): Ring buffer of session summaries for recent context.
- L2 (Agent): Per-agent fact store with deduplication.
- L3 (Shared): Organizational knowledge promoted from L2.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import UUID


class MemoryLayer(Enum):
    """The four memory layers in the system.

    L0_EPHEMERAL: Working memory managed by the caller (not stored).
    L1_SESSION: Ring buffer of session summaries.
    L2_AGENT: Per-agent fact store with deduplication.
    L3_SHARED: Shared organizational knowledge (promoted from L2).
    """

    L0_EPHEMERAL = "l0_ephemeral"
    L1_SESSION = "l1_session"
    L2_AGENT = "l2_agent"
    L3_SHARED = "l3_shared"


@dataclass
class LayeredMemoryConfig:
    """Configuration for the layered memory system.

    Attributes:
        l1_ring_size: Maximum number of session summaries in L1 ring buffer.
        l2_max_facts: Maximum facts per agent in L2.
        l3_promotion_threshold: Number of accesses before auto-promotion.
        dedup_similarity: Jaccard similarity threshold for deduplication.
    """

    l1_ring_size: int = 50
    l2_max_facts: int = 500
    l3_promotion_threshold: int = 3
    dedup_similarity: float = 0.8


@dataclass
class Fact:
    """A discrete piece of knowledge stored in L2 or L3.

    Attributes:
        content: The textual content of the fact.
        source_agent_id: UUID of the agent that produced this fact, or None.
        created_at: Timestamp when the fact was created.
        access_count: Number of times this fact has been accessed.
        metadata: Optional dictionary of additional metadata.
    """

    content: str
    source_agent_id: UUID | None
    created_at: datetime
    access_count: int = 0
    metadata: dict | None = None


@dataclass
class L1Summary:
    """A session summary stored in the L1 ring buffer.

    Attributes:
        summary: The textual summary of the session.
        task_id: UUID of the task this summary is associated with.
        created_at: Timestamp when the summary was created.
    """

    summary: str
    task_id: UUID
    created_at: datetime


class LayeredMemoryStore:
    """4-layer memory store providing intelligent knowledge management.

    Architecture:
    - L0 (Ephemeral): Caller-managed working memory. Not stored by this class;
      exists only in the caller's context window. Documented for completeness.
    - L1 (Session): Ring buffer of session summaries with configurable max size.
      Oldest summaries are evicted when the buffer is full.
    - L2 (Agent): Per-agent fact store. Facts are deduplicated on insert using
      Jaccard similarity. Each agent has an independent fact list.
    - L3 (Shared): Organizational knowledge accessible by all agents. Facts are
      promoted from L2 based on access count or cross-agent validation.

    This system augments (not replaces) the existing 3-temperature MemoryStore.
    """

    def __init__(
        self,
        config: LayeredMemoryConfig | None = None,
        persist_path: Path | None = None,
    ) -> None:
        """Initialize the layered memory store.

        Args:
            config: Configuration for layer sizes and thresholds.
                Uses defaults if not specified.
            persist_path: Optional path to a JSON file for persisting L2/L3.
                When provided, L2 and L3 state is saved after mutations and
                loaded on init if the file exists. L1 is persisted to a
                separate file (<persist_path_stem>_l1.json) in the same
                directory. When None, no persistence occurs.
        """
        self._config = config or LayeredMemoryConfig()
        self._persist_path = persist_path
        self._l1: list[L1Summary] = []
        self._l2: dict[UUID, list[Fact]] = {}
        self._l3: list[Fact] = []
        self._load()

    @property
    def config(self) -> LayeredMemoryConfig:
        """Return the current configuration."""
        return self._config

    @property
    def l1_summaries(self) -> list[L1Summary]:
        """Return the current L1 session summaries (read-only view)."""
        return list(self._l1)

    @property
    def l2_facts(self) -> dict[UUID, list[Fact]]:
        """Return the current L2 per-agent facts (read-only view)."""
        return dict(self._l2)

    @property
    def l3_shared(self) -> list[Fact]:
        """Return the current L3 shared knowledge (read-only view)."""
        return list(self._l3)

    # ── Persistence ──────────────────────────────────────────────────────────

    @property
    def _l1_persist_path(self) -> Path | None:
        """Return the path for L1 persistence file, derived from persist_path."""
        if self._persist_path is None:
            return None
        return self._persist_path.parent / f"{self._persist_path.stem}_l1.json"

    def _serialize_l1_summary(self, summary: L1Summary) -> dict:
        """Serialize an L1Summary to a JSON-compatible dict."""
        return {
            "summary": summary.summary,
            "task_id": str(summary.task_id),
            "created_at": summary.created_at.isoformat(),
        }

    def _deserialize_l1_summary(self, data: dict) -> L1Summary:
        """Deserialize a dict back to an L1Summary instance."""
        return L1Summary(
            summary=data["summary"],
            task_id=UUID(data["task_id"]),
            created_at=datetime.fromisoformat(data["created_at"]),
        )

    def _persist_l1(self) -> None:
        """Atomically write L1 ring buffer state to the persist file."""
        l1_path = self._l1_persist_path
        if l1_path is None:
            return
        data = {
            "l1": [self._serialize_l1_summary(s) for s in self._l1],
        }
        l1_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=l1_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, l1_path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _load_l1(self) -> None:
        """Load L1 ring buffer state from the persist file if it exists."""
        l1_path = self._l1_persist_path
        if l1_path is None or not l1_path.exists():
            return
        with open(l1_path) as f:
            data = json.load(f)
        self._l1 = [
            self._deserialize_l1_summary(s) for s in data.get("l1", [])
        ]

    def _serialize_fact(self, fact: Fact) -> dict:
        """Serialize a Fact to a JSON-compatible dict."""
        return {
            "content": fact.content,
            "source_agent_id": str(fact.source_agent_id) if fact.source_agent_id else None,
            "created_at": fact.created_at.isoformat(),
            "access_count": fact.access_count,
            "metadata": fact.metadata,
        }

    def _deserialize_fact(self, data: dict) -> Fact:
        """Deserialize a dict back to a Fact instance."""
        return Fact(
            content=data["content"],
            source_agent_id=UUID(data["source_agent_id"]) if data["source_agent_id"] else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            access_count=data["access_count"],
            metadata=data.get("metadata"),
        )

    def _persist(self) -> None:
        """Atomically write L2 and L3 state to the persist file."""
        if self._persist_path is None:
            return
        data = {
            "l2": {
                str(agent_id): [self._serialize_fact(f) for f in facts]
                for agent_id, facts in self._l2.items()
            },
            "l3": [self._serialize_fact(f) for f in self._l3],
        }
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._persist_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._persist_path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _load(self) -> None:
        """Load L2 and L3 state from the persist file if it exists."""
        if self._persist_path is None or not self._persist_path.exists():
            self._load_l1()
            return
        with open(self._persist_path) as f:
            data = json.load(f)
        for agent_id_str, facts_data in data.get("l2", {}).items():
            self._l2[UUID(agent_id_str)] = [
                self._deserialize_fact(fd) for fd in facts_data
            ]
        self._l3 = [self._deserialize_fact(fd) for fd in data.get("l3", [])]
        self._load_l1()

    def add_session_summary(self, task_id: UUID, summary: str) -> None:
        """Add a session summary to the L1 ring buffer.

        If the ring buffer is full (at l1_ring_size capacity), the oldest
        summary is evicted before the new one is added. Persists L1 state
        after each addition.

        Args:
            task_id: UUID of the task this summary is associated with.
            summary: The textual summary of the session.
        """
        entry = L1Summary(
            summary=summary,
            task_id=task_id,
            created_at=datetime.now(timezone.utc),
        )
        if len(self._l1) >= self._config.l1_ring_size:
            self._l1.pop(0)  # Evict oldest
        self._l1.append(entry)
        self._persist_l1()

    def store_fact(
        self,
        agent_id: UUID,
        content: str,
        metadata: dict | None = None,
    ) -> bool:
        """Store a fact in L2 (per-agent) with deduplication check.

        Before storing, checks if a similar fact already exists for this
        agent using Jaccard similarity. If a duplicate is found (similarity
        >= dedup_similarity threshold), the fact is not stored.

        Args:
            agent_id: UUID of the agent this fact belongs to.
            content: The textual content of the fact.
            metadata: Optional metadata dictionary.

        Returns:
            True if the fact was stored, False if it was a duplicate.
        """
        from nexus.memory.dedup import is_duplicate

        if agent_id not in self._l2:
            self._l2[agent_id] = []

        existing = self._l2[agent_id]

        # Check for duplicates
        if is_duplicate(existing, content, self._config.dedup_similarity):
            return False

        # Enforce max facts per agent
        if len(existing) >= self._config.l2_max_facts:
            existing.pop(0)  # Evict oldest fact

        fact = Fact(
            content=content,
            source_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
            access_count=0,
            metadata=metadata,
        )
        existing.append(fact)
        self._persist()
        return True

    def get_agent_facts(self, agent_id: UUID, limit: int = 10) -> list[Fact]:
        """Retrieve facts for a specific agent from L2.

        Returns the most recent facts for the given agent, up to the
        specified limit. Increments access_count on each retrieved fact.

        Args:
            agent_id: UUID of the agent whose facts to retrieve.
            limit: Maximum number of facts to return.

        Returns:
            List of Fact instances (most recent first), up to limit.
        """
        facts = self._l2.get(agent_id, [])
        # Return most recent first
        result = facts[-limit:] if limit < len(facts) else facts[:]
        result.reverse()
        # Increment access counts
        for fact in result:
            fact.access_count += 1
        return result

    def get_shared_knowledge(self, limit: int = 10) -> list[Fact]:
        """Retrieve shared organizational knowledge from L3.

        Returns the most recent shared facts, up to the specified limit.

        Args:
            limit: Maximum number of facts to return.

        Returns:
            List of shared Fact instances (most recent first), up to limit.
        """
        result = self._l3[-limit:] if limit < len(self._l3) else self._l3[:]
        result.reverse()
        return result

    def promote_to_shared(self, agent_id: UUID, fact_content: str) -> bool:
        """Promote a fact from L2 to L3 (shared organizational knowledge).

        Finds the matching fact in the agent's L2 store and moves it to L3.
        The fact remains in L2 as well (copied, not moved) to maintain
        agent-level context.

        Args:
            agent_id: UUID of the agent whose fact to promote.
            fact_content: The content string of the fact to promote.

        Returns:
            True if the fact was found and promoted, False otherwise.
        """
        agent_facts = self._l2.get(agent_id, [])
        for fact in agent_facts:
            if fact.content == fact_content:
                # Create a copy for L3
                shared_fact = Fact(
                    content=fact.content,
                    source_agent_id=fact.source_agent_id,
                    created_at=fact.created_at,
                    access_count=fact.access_count,
                    metadata=fact.metadata,
                )
                self._l3.append(shared_fact)
                self._persist()
                return True
        return False

    def get_context_window(self, agent_id: UUID, limit: int = 20) -> list[str]:
        """Build a combined context window from L1 + L2 + L3.

        Combines session summaries (L1), agent facts (L2), and shared
        knowledge (L3) into a single ordered list of context strings.
        The allocation is roughly: L1 gets 1/4, L2 gets 1/2, L3 gets 1/4.

        Args:
            agent_id: UUID of the agent to build context for.
            limit: Maximum total number of context items to return.

        Returns:
            List of context strings combining all layers.
        """
        l1_limit = max(1, limit // 4)
        l3_limit = max(1, limit // 4)
        l2_limit = limit - l1_limit - l3_limit

        context: list[str] = []

        # L1: Recent session summaries
        recent_summaries = self._l1[-l1_limit:]
        for s in reversed(recent_summaries):
            context.append(f"[session] {s.summary}")

        # L2: Agent-specific facts
        agent_facts = self.get_agent_facts(agent_id, limit=l2_limit)
        for f in agent_facts:
            context.append(f"[agent] {f.content}")

        # L3: Shared organizational knowledge
        shared = self.get_shared_knowledge(limit=l3_limit)
        for f in shared:
            context.append(f"[shared] {f.content}")

        return context[:limit]
