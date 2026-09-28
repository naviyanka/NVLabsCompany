"""Migration e7a1c2d3f404 turns the global audit chain into per-company chains.

Rows written before it belong to one global chain whose links cross
companies. The migration appends a seal row to each company's chain instead of
rewriting them (the table is append-only). These tests build a pre-migration
database, upgrade it, and check that every company's chain verifies on its
own, that later writes continue it, and that tampering is still detected.
"""

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import nexus.models  # noqa: F401
from alembic import command
from nexus.governance.audit_persistent import (
    CHAIN_SEALED_ACTION,
    PersistentAuditEntry,
    PersistentAuditLogger,
    chain_is_intact,
    compute_entry_hash,
)
from nexus.governance.audit_service import record_audit
from nexus.models.governance import AuditLog

BEFORE = "e7a1c2d3f403"
FIRST, SECOND = uuid.uuid4(), uuid.uuid4()
# One global chain, interleaved across two companies and a system event.
LEGACY = [FIRST, SECOND, FIRST, None, SECOND, FIRST]


def _legacy_rows(break_link_at: int | None = None) -> list[dict]:
    rows, previous = [], "genesis"
    start = datetime(2026, 9, 1, 12, 0, 0, 123456)
    for index, company_id in enumerate(LEGACY):
        entry = PersistentAuditEntry(
            id=uuid.uuid4(),
            actor_type="system",
            actor_id="",
            action=f"legacy.{index}",
            resource_type="task",
            resource_id=None,
            details={},
            company_id=company_id,
            timestamp=start + timedelta(seconds=index),
            sequence_number=index + 1,
        )
        link = "not-a-known-hash" if index == break_link_at else previous
        entry_hash = compute_entry_hash(entry, link)
        rows.append({
            "id": entry.id, "company_id": company_id, "actor_type": "system",
            "actor_id": None, "action": entry.action, "resource_type": "task",
            "resource_id": None, "details": {}, "created_at": entry.timestamp,
            "sequence_number": index + 1, "previous_hash": link, "entry_hash": entry_hash,
        })
        previous = entry_hash
    return rows


def _migrate(db_file, break_link_at: int | None = None) -> None:
    """Build a pre-migration database and upgrade it. Alembic's env runs its own loop."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    command.upgrade(cfg, BEFORE)
    engine = sa.create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.begin() as conn:
        conn.execute(sa.insert(AuditLog.__table__), _legacy_rows(break_link_at))
        # A row the former writer left unchained after a sequence collision.
        conn.execute(sa.insert(AuditLog.__table__).values(
            id=uuid.uuid4(), company_id=FIRST, actor_type="system", action="unchained",
            created_at=datetime(2026, 9, 2),
        ))
    engine.dispose()
    command.upgrade(cfg, "head")


@pytest.fixture
async def migrated(tmp_path):
    db_file = tmp_path / "audit.db"
    await asyncio.to_thread(_migrate, db_file)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _chain(factory, company_id) -> list[PersistentAuditEntry]:
    logger = PersistentAuditLogger(session_factory=factory, company_id=company_id)
    return await logger.chain_entries()


async def test_every_company_chain_verifies_after_the_migration(migrated) -> None:
    for company_id, legacy_sequences in ((FIRST, [1, 3, 6]), (SECOND, [2, 5]), (None, [4])):
        entries = await _chain(migrated, company_id)
        assert [e.sequence_number for e in entries[:-1]] == legacy_sequences
        seal = entries[-1]
        assert seal.action == CHAIN_SEALED_ACTION
        assert seal.sequence_number == legacy_sequences[-1] + 1
        assert chain_is_intact(entries)
    first_seal = (await _chain(migrated, FIRST))[-1]
    assert first_seal.details["legacy_unchained_rows"] == 1


async def test_new_writes_continue_from_the_seal(migrated) -> None:
    async with migrated() as session:
        await record_audit(company_id=FIRST, action="after.migration", db=session)
        await record_audit(company_id=SECOND, action="after.migration", db=session)
        await session.commit()

    first = await _chain(migrated, FIRST)
    assert [e.sequence_number for e in first] == [1, 3, 6, 7, 8]
    assert first[-1].previous_hash == first[-2].entry_hash
    assert chain_is_intact(first)
    second = await _chain(migrated, SECOND)
    assert [e.sequence_number for e in second] == [2, 5, 6, 7]
    assert chain_is_intact(second)


async def test_changing_or_removing_a_legacy_row_is_detected(migrated) -> None:
    entries = await _chain(migrated, FIRST)
    assert not chain_is_intact(entries[:1] + entries[2:])  # a legacy row removed
    entries[1].action = "rewritten"
    assert not chain_is_intact(entries)


async def test_a_chain_already_broken_before_the_migration_stays_broken(tmp_path) -> None:
    db_file = tmp_path / "broken.db"
    # Legacy row 4 (SECOND's) links to a hash that never existed.
    await asyncio.to_thread(_migrate, db_file, 4)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        for company_id in (FIRST, SECOND, None):
            assert not chain_is_intact(await _chain(factory, company_id))
    finally:
        await engine.dispose()
