"""Tests for Phase 2.3 — layered memory L2/L3 persisted to memory_records.

Covers: L2 facts surviving a restart, dedup running against the database,
per-agent capacity eviction, promotion writing L3 rows, and the acceptance
criterion — a promoted shared fact is visible to a second agent after restart.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 — registers every table on SQLModel.metadata
from nexus.memory.layered import LayeredMemoryConfig
from nexus.memory.layered_persistent import PersistentLayeredMemory
from nexus.memory.promotion import PromotionCriteria
from nexus.models.agent import Agent
from nexus.models.company import Company


@pytest.fixture
async def session_factory(tmp_path):
    """A session factory over a file-backed SQLite DB with all tables created."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def company_id(session_factory):
    """A company row the memory records can point at."""
    company = Company(name="Memory Corp")
    async with session_factory() as session:
        session.add(company)
        await session.commit()
    return company.id


@pytest.fixture
async def agents(session_factory, company_id):
    """Two agent rows in the same company."""
    alpha = Agent(company_id=company_id, name="Alpha", role="engineer")
    beta = Agent(company_id=company_id, name="Beta", role="analyst")
    async with session_factory() as session:
        session.add(alpha)
        session.add(beta)
        await session.commit()
    return alpha.id, beta.id


def _store(session_factory, company_id, **config) -> PersistentLayeredMemory:
    """Build a store, optionally overriding config fields."""
    return PersistentLayeredMemory(
        session_factory=session_factory,
        company_id=company_id,
        config=LayeredMemoryConfig(**config) if config else None,
    )


class TestL2Persistence:
    """2.3.1 — L2 facts are rows, not process state."""

    async def test_fact_survives_restart(self, session_factory, company_id, agents):
        """A fresh store over the same DB sees the earlier fact."""
        alpha, _ = agents
        await _store(session_factory, company_id).store_fact(
            alpha, "The deploy pipeline requires manual approval"
        )

        restarted = _store(session_factory, company_id)
        facts = await restarted.get_agent_facts(alpha)

        assert [f.content for f in facts] == [
            "The deploy pipeline requires manual approval"
        ]

    async def test_facts_are_scoped_per_agent(
        self, session_factory, company_id, agents
    ):
        """One agent's L2 does not leak into another's."""
        alpha, beta = agents
        store = _store(session_factory, company_id)
        await store.store_fact(alpha, "Alpha owns the billing service")

        assert await store.get_agent_facts(beta) == []

    async def test_access_count_persists(self, session_factory, company_id, agents):
        """Reading a fact bumps a counter that survives a restart."""
        alpha, _ = agents
        store = _store(session_factory, company_id)
        await store.store_fact(alpha, "Retries are capped at three attempts")

        await store.get_agent_facts(alpha)
        facts = await _store(session_factory, company_id).get_agent_facts(alpha)

        assert facts[0].access_count == 2  # one prior read, plus this one


class TestDedupAgainstDatabase:
    """2.3.3 — dedup compares against rows, not an in-process list."""

    async def test_duplicate_rejected_after_restart(
        self, session_factory, company_id, agents
    ):
        """A near-duplicate is refused by a store that never saw the original."""
        alpha, _ = agents
        content = "The staging cluster runs in the eu-west-1 region"
        assert await _store(session_factory, company_id).store_fact(alpha, content)

        restarted = _store(session_factory, company_id)
        assert await restarted.store_fact(alpha, content) is False
        assert len(await restarted.get_agent_facts(alpha)) == 1

    async def test_distinct_fact_still_stored(
        self, session_factory, company_id, agents
    ):
        """Dedup does not swallow an unrelated fact."""
        alpha, _ = agents
        store = _store(session_factory, company_id)
        await store.store_fact(alpha, "The staging cluster runs in eu-west-1")

        assert await store.store_fact(alpha, "Invoices are generated every Monday")
        assert len(await store.get_agent_facts(alpha)) == 2

    async def test_max_facts_evicts_oldest(self, session_factory, company_id, agents):
        """At capacity, the oldest row is dropped rather than the newest refused."""
        alpha, _ = agents
        store = _store(session_factory, company_id, l2_max_facts=2)
        await store.store_fact(alpha, "first unique observation about latency")
        await store.store_fact(alpha, "second unique observation about caching")
        await store.store_fact(alpha, "third unique observation about indexes")

        contents = {f.content for f in await store.get_agent_facts(alpha)}
        assert contents == {
            "second unique observation about caching",
            "third unique observation about indexes",
        }


class TestPromotion:
    """2.3.3 — promotion writes L3 rows and dedups against them."""

    async def test_explicit_promotion_writes_l3(
        self, session_factory, company_id, agents
    ):
        """promote_to_shared copies an L2 fact and leaves the original."""
        alpha, _ = agents
        store = _store(session_factory, company_id)
        content = "Customer data must never leave the EU"
        await store.store_fact(alpha, content)

        assert await store.promote_to_shared(alpha, content)
        assert [f.content for f in await store.get_shared_knowledge()] == [content]
        assert len(await store.get_agent_facts(alpha)) == 1

    async def test_promoting_unknown_fact_returns_false(
        self, session_factory, company_id, agents
    ):
        """A fact the agent does not hold cannot be promoted."""
        alpha, _ = agents
        store = _store(session_factory, company_id)

        assert await store.promote_to_shared(alpha, "never stored") is False

    async def test_promotion_is_idempotent(self, session_factory, company_id, agents):
        """Promoting twice does not duplicate the shared row."""
        alpha, _ = agents
        store = _store(session_factory, company_id)
        content = "All secrets are rotated every ninety days"
        await store.store_fact(alpha, content)

        assert await store.promote_to_shared(alpha, content)
        assert await store.promote_to_shared(alpha, content) is False
        assert len(await store.get_shared_knowledge()) == 1

    async def test_run_promotion_uses_access_count(
        self, session_factory, company_id, agents
    ):
        """A frequently read fact is promoted by the engine's criteria."""
        alpha, _ = agents
        store = _store(session_factory, company_id)
        content = "The nightly export job finishes before 04:00 UTC"
        await store.store_fact(alpha, content)
        for _ in range(3):
            await store.get_agent_facts(alpha)

        promoted = await store.run_promotion(PromotionCriteria(min_access_count=3))

        assert [f.content for f in promoted] == [content]
        assert [f.content for f in await store.get_shared_knowledge()] == [content]

    async def test_run_promotion_skips_cold_facts(
        self, session_factory, company_id, agents
    ):
        """An unread single-agent fact stays in L2."""
        alpha, _ = agents
        store = _store(session_factory, company_id)
        await store.store_fact(alpha, "A one-off note nobody has read yet")

        promoted = await store.run_promotion(
            PromotionCriteria(min_access_count=3, min_agents_referenced=2)
        )

        assert promoted == []
        assert await store.get_shared_knowledge() == []


class TestAcceptance:
    """2.3 accept — a promoted shared fact reaches a second agent after restart."""

    async def test_shared_fact_visible_to_second_agent_after_restart(
        self, session_factory, company_id, agents
    ):
        """Alpha promotes; a new process serving Beta sees it in L3 and context."""
        alpha, beta = agents
        content = "Production migrations run only during the Friday window"

        writer = _store(session_factory, company_id)
        await writer.store_fact(alpha, content)
        assert await writer.promote_to_shared(alpha, content)

        # A different process, a different agent.
        reader = _store(session_factory, company_id)
        assert [f.content for f in await reader.get_shared_knowledge()] == [content]

        context = await reader.get_context_window(beta, limit=8)
        assert f"[shared] {content}" in context
        assert not any(line.startswith("[agent]") for line in context)

    async def test_l3_is_scoped_per_company(self, session_factory, company_id, agents):
        """Another tenant's store does not see this company's shared knowledge."""
        alpha, _ = agents
        store = _store(session_factory, company_id)
        content = "Internal rate limits are five hundred requests per minute"
        await store.store_fact(alpha, content)
        await store.promote_to_shared(alpha, content)

        other = _store(session_factory, uuid.uuid4())
        assert await other.get_shared_knowledge() == []


class TestL1RemainsEphemeral:
    """2.3.2 — L1 stays an in-memory ring buffer by design."""

    async def test_l1_does_not_survive_restart(
        self, session_factory, company_id, agents
    ):
        """Session summaries are process-local; a new store starts empty."""
        _, beta = agents
        store = _store(session_factory, company_id)
        store.add_session_summary(uuid.uuid4(), "Investigated the latency spike")

        assert len(store.l1_summaries) == 1
        assert _store(session_factory, company_id).l1_summaries == []

    async def test_l1_ring_buffer_evicts_oldest(self, session_factory, company_id):
        """The buffer is bounded by l1_ring_size."""
        store = _store(session_factory, company_id, l1_ring_size=2)
        task_id = uuid.uuid4()
        for label in ("first", "second", "third"):
            store.add_session_summary(task_id, label)

        assert [s.summary for s in store.l1_summaries] == ["second", "third"]

    async def test_context_window_includes_all_layers(
        self, session_factory, company_id, agents
    ):
        """L1 + L2 + L3 are tagged and combined within the limit."""
        alpha, _ = agents
        store = _store(session_factory, company_id)
        store.add_session_summary(uuid.uuid4(), "Reviewed the incident timeline")
        await store.store_fact(alpha, "Alpha maintains the ingestion worker")
        await store.store_fact(alpha, "Backfills are throttled to ten per second")
        await store.promote_to_shared(alpha, "Alpha maintains the ingestion worker")

        context = await store.get_context_window(alpha, limit=8)

        assert len(context) <= 8
        assert any(line.startswith("[session]") for line in context)
        assert any(line.startswith("[agent]") for line in context)
        assert any(line.startswith("[shared]") for line in context)
