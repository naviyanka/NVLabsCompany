"""The CEO knowledge seed writes through canonical ingest and is safe to rerun."""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401
from nexus import ceo_knowledge_seed as seed
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.memory import MemoryRecord


@pytest.fixture
async def factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    make = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with make() as s:
        s.add(Company(id=seed.COMPANY_ID, name="acme"))
        await s.flush()
        s.add(
            Agent(
                id=seed.CEO_AGENT_ID, company_id=seed.COMPANY_ID, name="ceo", role="ceo", model="m"
            )
        )
        await s.commit()

    @asynccontextmanager
    async def tenant_session(_company_id):
        async with make() as s:
            yield s

    monkeypatch.setattr("nexus.database.tenant_session", tenant_session)
    yield make
    await engine.dispose()


async def test_seed_writes_asserted_seed_rows_once(factory):
    await seed.seed_ceo_knowledge()
    await seed.seed_ceo_knowledge()  # a rerun adds nothing

    async with factory() as s:
        rows = (await s.execute(select(MemoryRecord))).scalars().all()
        assert len(rows) == len(seed.API_KNOWLEDGE)
        assert {r.source_type for r in rows} == {"seed"}
        assert len({r.source_id for r in rows}) == len(rows)
        assert {(r.status, r.trust_state) for r in rows} == {("active", "asserted")}
        assert all(r.content_hash and r.company_id == seed.COMPANY_ID for r in rows)
        assert (
            await s.execute(select(func.count()).select_from(MemoryRecord))
        ).scalar_one() == len(rows)
