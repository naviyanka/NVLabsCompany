"""Memory ingest and lifecycle are atomic with the caller's transaction on SQLite.

SQLite's driver opens its transaction at the first write, not at the first statement, so
a SAVEPOINT that runs first becomes the outermost transaction and releasing it commits.
``begin_write`` takes the write lock up front. These tests use SQLite's default rollback
journal (no WAL) and fail if the helper is removed.
"""
# ruff: noqa: F811 -- pytest fixtures imported from test_memory_ingest

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from sqlalchemy import func, select

from nexus.memory.ingest import Origin, begin_write, ingest_memory
from nexus.memory.lifecycle import archive_memory, reject_memory, supersede_memory
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.memory import MemoryRecord
from nexus.services import manager_service
from tests.test_memory_ingest import _count, _ctx, _item, env  # noqa: F401 -- fixture and helpers


async def _audits(s, action=None) -> int:
    q = select(func.count()).select_from(AuditLog)
    if action:
        q = q.where(AuditLog.action == action)
    return (await s.execute(q)).scalar_one()


async def _seed(factory, ids, origin=Origin.API, content="Deploys go out on Tuesdays"):
    """One committed row, and the audit rows its creation left behind."""
    async with factory() as s:
        record = (await ingest_memory(s, _ctx(ids), _item(ids, content=content), origin)).record
        await s.commit()
        return record.id


def _other_connection_sees(factory, table: str) -> int:
    """Rows a different connection can read right now: only committed data is visible."""
    path = factory.kw["bind"].url.database
    conn = sqlite3.connect(path, timeout=0)
    try:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# --- ingest ---------------------------------------------------------------------------


async def test_ingest_rollback_leaves_no_row_and_no_audit(env):
    factory, ids = env
    async with factory() as s:
        assert await _count(s) == 0
        result = await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)
        assert result.created and await _count(s) == 1  # visible inside the transaction
        assert await _audits(s, "memory.recorded") == 1
        # Uncommitted: no other connection can see it (the savepoint did not commit).
        assert _other_connection_sees(factory, "memory_records") == 0
        await s.rollback()
    async with factory() as fresh:
        assert await _count(fresh) == 0
        assert await _audits(fresh, "memory.recorded") == 0


def _keyed(ids):
    """A source identity makes the write idempotent (a bare API write has none)."""
    return _item(ids, source_type="chat_reply", source_id="turn-1", item_key="fact:0")


async def test_ingest_commit_persists_record_and_audit_together(env):
    factory, ids = env
    async with factory() as s:
        first = await ingest_memory(s, _ctx(ids), _keyed(ids), Origin.CHAT_EXTRACTION)
        await s.commit()
    async with factory() as fresh:
        assert await _count(fresh) == 1
        assert await _audits(fresh, "memory.recorded") == 1
        replay = await ingest_memory(fresh, _ctx(ids), _keyed(ids), Origin.CHAT_EXTRACTION)
        await fresh.commit()
        assert not replay.created and replay.record.id == first.record.id
        assert await _count(fresh) == 1
        assert await _audits(fresh, "memory.recorded") == 1


# --- lifecycle ------------------------------------------------------------------------


async def test_archive_rollback_restores_the_status(env):
    factory, ids = env
    memory_id = await _seed(factory, ids)
    async with factory() as s:
        row = await archive_memory(s, _ctx(ids), memory_id)
        assert row.status == "archived"
        assert await _audits(s, "memory.archived") == 1
        await s.rollback()
    async with factory() as fresh:
        assert (await fresh.get(MemoryRecord, memory_id)).status == "active"
        assert await _audits(fresh, "memory.archived") == 0


async def test_reject_rollback_restores_the_status(env):
    factory, ids = env
    memory_id = await _seed(factory, ids, origin=Origin.CHAT_EXTRACTION)
    async with factory() as s:
        row = await reject_memory(s, _ctx(ids), memory_id)
        assert row.status == "rejected"
        await s.rollback()
    async with factory() as fresh:
        assert (await fresh.get(MemoryRecord, memory_id)).status == "candidate"
        assert await _audits(fresh, "memory.rejected") == 0


async def test_supersede_rollback_leaves_neither_successor_nor_link(env):
    factory, ids = env
    old_id = await _seed(factory, ids)
    async with factory() as s:
        res = await supersede_memory(
            s, _ctx(ids), old_id, _item(ids, content="Deploys go out on Wednesdays"), Origin.API
        )
        assert res.created and await _count(s) == 2
        assert (await s.get(MemoryRecord, old_id)).status == "superseded"
        assert _other_connection_sees(factory, "memory_records") == 1
        await s.rollback()
    async with factory() as fresh:
        assert await _count(fresh) == 1
        old = await fresh.get(MemoryRecord, old_id)
        assert old.status == "active" and "superseded_by" not in (old.record_metadata or {})
        assert await _count(fresh, supersedes_id=old_id) == 0
        assert await _audits(fresh, "memory.superseded") == 0
        assert await _audits(fresh, "memory.recorded") == 1  # only the seed's


async def test_supersede_commit_persists_all_of_it_at_once(env):
    factory, ids = env
    old_id = await _seed(factory, ids)
    async with factory() as s:
        await supersede_memory(
            s, _ctx(ids), old_id, _item(ids, content="Deploys go out on Wednesdays"), Origin.API
        )
        await s.commit()
    async with factory() as fresh:
        assert await _count(fresh) == 2
        assert (await fresh.get(MemoryRecord, old_id)).status == "superseded"
        assert await _audits(fresh, "memory.superseded") == 1


# --- the caller's transaction ---------------------------------------------------------


async def test_helper_does_not_commit_or_replace_the_callers_work(env):
    factory, ids = env
    async with factory() as s:
        s.add(Company(name="pending"))
        await s.flush()
        await begin_write(s)
        assert s.in_transaction()
        await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)
        await s.rollback()
    async with factory() as fresh:
        # The caller's unrelated flush was still part of its transaction.
        names = (await fresh.execute(select(Company.name))).scalars().all()
        assert "pending" not in names
        assert await _count(fresh) == 0


async def test_explicit_outer_transaction_commits_once(env):
    factory, ids = env
    old_id = await _seed(factory, ids)
    async with factory() as s, s.begin():
        await ingest_memory(s, _ctx(ids), _item(ids, content="Standups are at nine"), Origin.API)
        await archive_memory(s, _ctx(ids), old_id)
        await supersede_memory(
            s,
            _ctx(ids),
            (await _live_id(s, "Standups are at nine")),
            _item(ids, content="Standups are at ten"),
            Origin.API,
        )
    async with factory() as fresh:
        assert await _count(fresh) == 3
        assert (await fresh.get(MemoryRecord, old_id)).status == "archived"


async def test_explicit_outer_transaction_rolls_back_everything(env):
    factory, ids = env
    old_id = await _seed(factory, ids)
    with pytest.raises(RuntimeError, match="abort"):
        async with factory() as s, s.begin():
            await ingest_memory(
                s, _ctx(ids), _item(ids, content="Standups are at nine"), Origin.API
            )
            await archive_memory(s, _ctx(ids), old_id)
            raise RuntimeError("abort")
    async with factory() as fresh:
        assert await _count(fresh) == 1
        assert (await fresh.get(MemoryRecord, old_id)).status == "active"
        assert await _audits(fresh, "memory.archived") == 0


async def _live_id(s, content):
    return (
        await s.execute(select(MemoryRecord.id).where(MemoryRecord.content == content))
    ).scalar_one()


async def test_repeated_calls_in_one_transaction_are_safe(env):
    factory, ids = env
    async with factory() as s:
        for _ in range(3):
            await begin_write(s)
        for n in range(3):
            await ingest_memory(s, _ctx(ids), _item(ids, content=f"fact number {n}"), Origin.API)
        first = await _live_id(s, "fact number 0")
        # supersede -> ingest_memory -> begin_write again, inside its own savepoint.
        await supersede_memory(s, _ctx(ids), first, _item(ids, content="fact zero"), Origin.API)
        await begin_write(s)
        assert _other_connection_sees(factory, "memory_records") == 0  # no savepoint committed
        await s.commit()
    async with factory() as fresh:
        assert await _count(fresh) == 4


async def test_helper_is_a_no_op_for_an_unbound_session():
    await begin_write(object())  # nothing to start, nothing raised


# --- contention -----------------------------------------------------------------------


async def test_the_write_lock_is_held_from_the_first_statement(env, monkeypatch):
    """A second writer cannot get in between the memory row and its audit row."""
    factory, ids = env
    path = factory.kw["bind"].url.database
    real_audit, probed = manager_service.audit, []

    async def probing_audit(*args, **kw):
        probe = sqlite3.connect(path, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                probe.execute("BEGIN IMMEDIATE")
            probed.append(True)
        finally:
            probe.close()
        return await real_audit(*args, **kw)

    monkeypatch.setattr(manager_service, "audit", probing_audit)
    async with factory() as s:
        await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)
        await s.commit()
    assert probed == [True]


async def test_a_background_writer_waits_instead_of_failing_the_audit(env, monkeypatch):
    """The CEO delegation shape: a second session writes while ingest is mid-flight."""
    factory, ids = env
    real_audit, background = manager_service.audit, []

    async def audit_then_release_the_writer(*args, **kw):
        async def write():
            async with factory() as bg:
                bg.add(Company(name=f"bg-{len(background)}"))
                await bg.commit()

        background.append(asyncio.ensure_future(write()))
        await asyncio.sleep(0)  # let the writer reach the database, and be made to wait
        return await real_audit(*args, **kw)

    monkeypatch.setattr(manager_service, "audit", audit_then_release_the_writer)
    for n in range(12):
        async with factory() as s:
            await ingest_memory(s, _ctx(ids), _item(ids, content=f"fact {n}"), Origin.API)
            await s.commit()
    await asyncio.gather(*background)  # any "database is locked" surfaces here
    async with factory() as fresh:
        assert await _count(fresh) == 12
        assert await _audits(fresh, "memory.recorded") == 12
        assert len(background) == 12
