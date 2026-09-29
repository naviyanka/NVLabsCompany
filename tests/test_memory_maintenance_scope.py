"""`_memory_maintenance` must touch only the company whose tick is running.

It used to run unfiltered once per company per tick, so every company's tick
decayed every other company's memories and promoted private agent memory into
shared scope.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.models.memory import MemoryRecord
from nexus.runtime import orchestrator

STALE = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'maint.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _stale_agent_memory(company_id: uuid.UUID) -> MemoryRecord:
    """Stale + high importance: eligible for both decay and the old promotion."""
    return MemoryRecord(
        company_id=company_id,
        agent_id=uuid.uuid4(),
        scope="agent",
        content="private agent note",
        importance=0.95,
        tier="warm",
        last_accessed_at=STALE,
    )


async def _seed(factory) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    a, b = uuid.uuid4(), uuid.uuid4()
    mem_a, mem_b = _stale_agent_memory(a), _stale_agent_memory(b)
    async with factory() as s:
        s.add_all([mem_a, mem_b])
        await s.commit()
    return a, b, mem_a.id, mem_b.id


async def _row(factory, memory_id: uuid.UUID) -> MemoryRecord:
    async with factory() as s:
        return (
            await s.execute(select(MemoryRecord).where(MemoryRecord.id == memory_id))
        ).scalar_one()


async def test_tick_for_one_company_cannot_mutate_another(factory):
    a, _b, id_a, id_b = await _seed(factory)

    async with factory() as s:
        await orchestrator._memory_maintenance(s, a)
        await s.commit()

    assert (await _row(factory, id_a)).importance == pytest.approx(0.95 * 0.95)
    assert (await _row(factory, id_b)).importance == 0.95


async def test_repeated_ticks_only_affect_the_intended_company(factory):
    a, _b, id_a, id_b = await _seed(factory)

    for _ in range(3):
        async with factory() as s:
            await orchestrator._memory_maintenance(s, a)
            await s.commit()

    assert (await _row(factory, id_a)).importance == pytest.approx(0.95**4)
    assert (await _row(factory, id_b)).importance == 0.95


async def test_private_agent_memory_is_never_promoted(factory):
    a, b, id_a, id_b = await _seed(factory)

    for company in (a, b):
        async with factory() as s:
            await orchestrator._memory_maintenance(s, company)
            await s.commit()

    for memory_id in (id_a, id_b):
        row = await _row(factory, memory_id)
        assert (row.scope, row.tier) == ("agent", "warm")


def test_tick_passes_the_company_being_processed():
    src = inspect.getsource(orchestrator._tick)
    assert "_memory_maintenance(db, company_id)" in src
