"""Tests for chat's durable memory wiring (PersistentLayeredMemory in chat.py).

Chat history is a bounded transcript, so anything an agent worked out beyond the
last few turns used to vanish. These tests cover the two halves of the fix: a
reply's facts land in ``memory_records`` through PersistentLayeredMemory, and a
later request -- including one served by a process that never saw the original
reply -- reads them back into the system prompt.

The "restart" is modelled by building a fresh store against the same database,
which is exactly what a new worker does: nothing in-process carries over.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 — registers every table on SQLModel.metadata
from nexus.api.routes import chat as chat_module
from nexus.memory.layered_persistent import L3_SCOPE, PersistentLayeredMemory
from nexus.memory.promotion import PromotionCriteria
from nexus.models.agent import Agent
from nexus.models.company import Company


@pytest.fixture
async def session_factory(tmp_path):
    """A session factory over a file-backed SQLite DB with all tables created."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chatmem.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def patched_db(session_factory, monkeypatch):
    """Point chat's module-level session factory at the test database.

    chat.py resolves ``async_session_factory`` from ``nexus.database`` at call
    time, so patching it there is what the production code actually picks up.
    """
    import nexus.database

    monkeypatch.setattr(nexus.database, "async_session_factory", session_factory)
    return session_factory


@pytest.fixture
async def company_and_agents(session_factory):
    """A company with two agents in it."""
    company = Company(name="Memory Corp")
    async with session_factory() as session:
        session.add(company)
        await session.commit()

    alpha = Agent(company_id=company.id, name="Alpha", role="engineer")
    beta = Agent(company_id=company.id, name="Beta", role="analyst")
    async with session_factory() as session:
        session.add(alpha)
        session.add(beta)
        await session.commit()
    return company.id, alpha, beta


class TestRememberResponse:
    """An agent's reply has to leave durable knowledge behind."""

    async def test_facts_from_reply_are_stored(self, patched_db, company_and_agents):
        """A reply stating something learned becomes an L2 fact."""
        _, alpha, _ = company_and_agents

        stored = await chat_module._remember_response(
            alpha, "I learned that the staging deploy needs the migration first."
        )
        assert stored == 1

        memory = PersistentLayeredMemory(
            session_factory=patched_db, company_id=alpha.company_id
        )
        facts = await memory.get_agent_facts(alpha.id)
        assert any("staging deploy" in f.content for f in facts)

    async def test_reply_without_facts_stores_nothing(
        self, patched_db, company_and_agents
    ):
        """Small talk is not knowledge; nothing is written."""
        _, alpha, _ = company_and_agents

        assert await chat_module._remember_response(alpha, "Sure, on it.") == 0

    async def test_repeated_reply_deduplicates(self, patched_db, company_and_agents):
        """Saying the same thing twice must not grow the store."""
        _, alpha, _ = company_and_agents
        text = "I learned that the cache key includes the tenant id."

        assert await chat_module._remember_response(alpha, text) == 1
        assert await chat_module._remember_response(alpha, text) == 0

    async def test_storage_failure_does_not_raise(
        self, company_and_agents, monkeypatch
    ):
        """A broken memory backend degrades chat, it does not break it."""
        import nexus.database

        _, alpha, _ = company_and_agents

        def _boom():
            raise RuntimeError("database gone")

        monkeypatch.setattr(nexus.database, "async_session_factory", _boom)
        assert await chat_module._remember_response(alpha, "I learned that X.") == 0


class TestContextSurvivesRestart:
    """A fresh process must see what an earlier one remembered."""

    async def test_facts_readable_after_restart(self, patched_db, company_and_agents):
        """Nothing in-process carries the fact; the database does."""
        _, alpha, _ = company_and_agents
        await chat_module._remember_response(
            alpha, "I learned that the rate limiter buckets per minute."
        )

        # A new store over the same database is what a restarted worker builds.
        restarted = PersistentLayeredMemory(
            session_factory=patched_db, company_id=alpha.company_id
        )
        context = await restarted.get_context_window(alpha.id)
        assert any("rate limiter" in line for line in context)

    async def test_shared_knowledge_reaches_the_prompt(
        self, patched_db, company_and_agents
    ):
        """A promoted fact from one agent shows up for another one's chat."""
        company_id, alpha, beta = company_and_agents

        memory = PersistentLayeredMemory(
            session_factory=patched_db, company_id=company_id
        )
        await memory.store_fact(alpha.id, "Deploys are frozen on Fridays.")
        # Promotion is what moves a fact from one agent's L2 to company-wide L3.
        promoted = await memory.run_promotion(
            PromotionCriteria(min_access_count=0, min_age_hours=0)
        )
        assert promoted

        shared = await chat_module._fetch_shared_knowledge(company_id)
        assert any("frozen on Fridays" in m["content"] for m in shared)
        assert all(m["scope"] == L3_SCOPE for m in shared)

    async def test_shared_knowledge_is_tenant_scoped(
        self, patched_db, company_and_agents
    ):
        """One company's shared knowledge must not leak into another's prompt."""
        company_id, alpha, _ = company_and_agents

        memory = PersistentLayeredMemory(
            session_factory=patched_db, company_id=company_id
        )
        await memory.store_fact(alpha.id, "Our API key rotates monthly.")
        await memory.run_promotion(
            PromotionCriteria(min_access_count=0, min_age_hours=0)
        )

        assert await chat_module._fetch_shared_knowledge(uuid.uuid4()) == []

    async def test_shared_lookup_failure_returns_empty(
        self, company_and_agents, monkeypatch
    ):
        """Losing shared context degrades the prompt, it does not fail the request."""
        import nexus.database

        company_id, _, _ = company_and_agents

        def _boom():
            raise RuntimeError("database gone")

        monkeypatch.setattr(nexus.database, "async_session_factory", _boom)
        assert await chat_module._fetch_shared_knowledge(company_id) == []
