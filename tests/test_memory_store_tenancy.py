"""MemoryStore requires a company and keeps tenants apart in every tier."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from nexus.memory.store import MemoryStore
from nexus.models.company import Company
from nexus.models.memory import MemoryRecord


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all, tables=[Company.__table__, MemoryRecord.__table__]
        )
    async with async_sessionmaker(engine, class_=AsyncSession)() as session:
        yield session
    await engine.dispose()


async def test_store_and_retrieve_fail_closed_without_a_company(db):
    store = MemoryStore(db)
    with pytest.raises(ValueError, match="company_id"):
        await store.store(scope="agent", scope_id=uuid.uuid4(), content="x")
    with pytest.raises(ValueError, match="company_id"):
        await store.retrieve(scope="agent", scope_id=uuid.uuid4())
    assert (await db.execute(MemoryRecord.__table__.select())).all() == []


async def test_one_store_never_serves_another_companys_memory(db):
    a, b = uuid.uuid4(), uuid.uuid4()
    for cid in (a, b):
        db.add(Company(id=cid, name=str(cid)))
    await db.flush()
    scope_id = uuid.uuid4()  # same scope entity id in both tenants
    store = MemoryStore(db)
    await store.store(scope="agent", scope_id=scope_id, content="A secret", company_id=a)
    await store.store(scope="agent", scope_id=scope_id, content="B secret", company_id=b)

    # Hot tier: the cache is keyed by company.
    got_a = await store.retrieve("agent", scope_id, company_id=a)
    assert [(r.content, r.company_id) for r in got_a] == [("A secret", a)]

    # Warm tier: a fresh store has no hot cache, so the query itself must filter.
    fresh = MemoryStore(db)
    got_b = await fresh.retrieve("agent", scope_id, company_id=b)
    assert [(r.content, r.company_id) for r in got_b] == [("B secret", b)]
    assert await fresh.retrieve("agent", scope_id, company_id=uuid.uuid4()) == []
