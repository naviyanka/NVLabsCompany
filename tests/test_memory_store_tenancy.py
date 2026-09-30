"""MemoryStore requires a company and keeps tenants apart in every tier."""

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401
from nexus.memory.store import MemoryStore
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.memory import MemoryRecord


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
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
    agent = Agent(company_id=a, name="a", role="engineer", model="m")
    db.add(agent)
    await db.flush()
    scope_id = agent.id  # company B holds a row that names the same scope entity id
    store = MemoryStore(db)
    await store.store(scope="agent", scope_id=scope_id, content="A secret", company_id=a)
    db.add(MemoryRecord(company_id=b, scope="agent", scope_id=scope_id, content="B secret", tier="warm"))
    await db.flush()

    # Hot tier: the cache is keyed by company.
    got_a = await store.retrieve("agent", scope_id, company_id=a)
    assert [(r.content, r.company_id) for r in got_a] == [("A secret", a)]

    # Warm tier: a fresh store has no hot cache, so the query itself must filter.
    fresh = MemoryStore(db)
    got_b = await fresh.retrieve("agent", scope_id, company_id=b)
    assert [(r.content, r.company_id) for r in got_b] == [("B secret", b)]
    assert await fresh.retrieve("agent", scope_id, company_id=uuid.uuid4()) == []


# --- promote / demote / archive_old / cold storage -------------------------------------------

SECRET = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 3


@pytest.fixture
async def two(db):
    a, b = uuid.uuid4(), uuid.uuid4()
    for cid in (a, b):
        db.add(Company(id=cid, name=str(cid)))
    await db.flush()
    return a, b


async def _warm(db, company_id, content="note", **kw):
    """A warm row that is not in any store's hot cache."""
    record = MemoryRecord(
        id=uuid.uuid4(), company_id=company_id, scope="agent", scope_id=uuid.uuid4(),
        content=content, tier="warm", **kw,
    )
    db.add(record)
    await db.flush()
    return record


async def _tier(db, memory_id):
    row = (await db.execute(MemoryRecord.__table__.select().where(
        MemoryRecord.__table__.c.id == memory_id))).one()
    return row.tier


@pytest.mark.parametrize("method", ["promote", "demote"])
async def test_tier_moves_fail_closed_without_a_company(db, tmp_path, method):
    store = MemoryStore(db, cold_storage_path=tmp_path)
    with pytest.raises(ValueError, match="company_id"):
        await getattr(store, method)(uuid.uuid4())
    with pytest.raises(ValueError, match="company_id"):
        await store.archive_old(0)
    with pytest.raises(ValueError, match="company_id"):
        await store._load_from_cold(uuid.uuid4())
    assert list(tmp_path.iterdir()) == []


async def test_company_cannot_move_another_companys_memory_by_uuid(db, tmp_path, two):
    a, b = two
    theirs = await _warm(db, b, "B only")
    store = MemoryStore(db, cold_storage_path=tmp_path)

    # A guessed foreign id reads exactly like an id that does not exist.
    for call in (store.promote(theirs.id, a), store.demote(theirs.id, a)):
        with pytest.raises(ValueError, match="not found"):
            await call
    with pytest.raises(ValueError, match="not found"):
        await store.promote(uuid.uuid4(), a)
    assert await store.archive_old(0, a) == 0
    assert await _tier(db, theirs.id) == "warm"
    assert list(tmp_path.iterdir()) == []


async def test_archive_and_promote_round_trip_stay_inside_their_company(db, tmp_path, two):
    a, b = two
    mine, theirs = await _warm(db, a, "A note"), await _warm(db, b, "B note")
    store = MemoryStore(db, cold_storage_path=tmp_path)

    assert await store.demote(mine.id, a) == "cold"
    assert (tmp_path / str(a) / f"{mine.id}.json").is_file()
    assert await _tier(db, mine.id) == "cold"
    assert await _tier(db, theirs.id) == "warm"
    with pytest.raises(ValueError, match="not found"):
        await store.promote(mine.id, b)  # B cannot pull A's cold memory back
    assert await store.promote(mine.id, a) == "warm"

    assert await store.archive_old(0, b) == 1
    assert await _tier(db, theirs.id) == "cold" and await _tier(db, mine.id) == "warm"
    assert not (tmp_path / str(b) / f"{mine.id}.json").exists()


async def test_hot_cache_moves_are_company_scoped(db, tmp_path, two):
    a, b = two
    store = MemoryStore(db, cold_storage_path=tmp_path)
    agent = Agent(company_id=a, name="a", role="engineer", model="m")
    db.add(agent)
    await db.flush()
    memory_id = uuid.UUID(await store.store("agent", agent.id, "mine", company_id=a))
    with pytest.raises(ValueError, match="not found"):
        await store.demote(memory_id, b)
    assert await store.promote(memory_id, a) == "hot"
    assert await store.demote(memory_id, a) == "warm"


async def test_cold_files_cannot_escape_or_cross_companies(db, tmp_path, two):
    a, b = two
    store = MemoryStore(db, cold_storage_path=tmp_path / "cold")
    memory_id = uuid.uuid4()
    with pytest.raises(ValueError):
        store._cold_file("../../evil", memory_id)
    with pytest.raises(ValueError):
        store._cold_file(a, "../../evil")
    inside = store._cold_file(a, memory_id)
    assert inside.parent == (tmp_path / "cold" / str(a)).resolve()

    # A file planted in B's directory that claims to be A's is not served to B.
    planted = store._cold_file(b, memory_id)
    planted.parent.mkdir(parents=True)
    planted.write_text(json.dumps({"id": str(memory_id), "company_id": str(a),
                                   "scope": "agent", "content": "x"}))
    assert await store._load_from_cold(memory_id, b) is None
    with pytest.raises(ValueError, match="not found"):
        await store.promote(memory_id, b)


async def test_cold_file_never_holds_an_unredacted_secret(db, tmp_path, two):
    a, _ = two
    record = await _warm(db, a, f"key is {SECRET}", record_metadata={"note": f"also {SECRET}"})
    store = MemoryStore(db, cold_storage_path=tmp_path)
    await store.demote(record.id, a)
    text = (tmp_path / str(a) / f"{record.id}.json").read_text()
    assert SECRET not in text and "sk-ant-api03" not in text
