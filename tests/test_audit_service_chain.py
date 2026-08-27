"""The production audit writer must maintain the tamper-evident hash chain.

Every real audit write goes through ``record_audit`` in ``nexus.governance.audit_service``.
Phase 0.1 gave ``audit_log`` a SHA-256 hash chain, but the chain columns are
nullable, so a writer that ignores them inserts perfectly valid unchained rows
and the chain silently covers nothing. These tests pin the wiring in place.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from nexus.governance.audit_persistent import PersistentAuditEntry, compute_entry_hash
from nexus.governance.audit_service import record_audit
from nexus.models.governance import AuditLog


@pytest.fixture
async def session_factory():
    """An isolated in-memory database with the audit table created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def fetch_chain(session: AsyncSession) -> list[AuditLog]:
    """Return every chained row in sequence order."""
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.sequence_number.is_not(None))
        .order_by(AuditLog.sequence_number)
    )
    return list(result.scalars())


def chain_is_valid(rows: list[AuditLog]) -> bool:
    """Recompute every link and compare against what was stored."""
    previous = "genesis"
    for index, row in enumerate(rows, start=1):
        if row.sequence_number != index:
            return False
        if row.previous_hash != previous:
            return False
        expected = compute_entry_hash(PersistentAuditEntry.from_row(row), previous)
        if row.entry_hash != expected:
            return False
        previous = row.entry_hash
    return True


class TestChainIsMaintained:
    """record_audit stamps chain columns, not just the event fields."""

    async def test_single_write_is_chained(self, session_factory) -> None:
        company_id = uuid.uuid4()
        async with session_factory() as session:
            await record_audit(
                company_id=company_id,
                actor_type="user",
                action="agent.created",
                db=session,
            )
            await session.commit()

        async with session_factory() as session:
            rows = await fetch_chain(session)

        assert len(rows) == 1
        assert rows[0].sequence_number == 1
        assert rows[0].previous_hash == "genesis"
        assert rows[0].entry_hash
        assert chain_is_valid(rows)

    async def test_sequential_writes_form_a_verifiable_chain(self, session_factory) -> None:
        company_id = uuid.uuid4()
        async with session_factory() as session:
            for index in range(10):
                await record_audit(
                    company_id=company_id,
                    actor_type="agent",
                    action=f"task.step.{index}",
                    db=session,
                )
            await session.commit()

        async with session_factory() as session:
            rows = await fetch_chain(session)

        assert len(rows) == 10
        assert [row.sequence_number for row in rows] == list(range(1, 11))
        assert chain_is_valid(rows)

    async def test_chain_continues_across_sessions(self, session_factory) -> None:
        """A later write picks up the tail left by an earlier one."""
        company_id = uuid.uuid4()
        for action in ("first", "second", "third"):
            async with session_factory() as session:
                await record_audit(
                    company_id=company_id,
                    actor_type="system",
                    action=action,
                    db=session,
                )
                await session.commit()

        async with session_factory() as session:
            rows = await fetch_chain(session)

        assert len(rows) == 3
        assert chain_is_valid(rows)

    async def test_system_event_without_company_is_chained(self, session_factory) -> None:
        """company_id is nullable for system events; the hash must cope."""
        async with session_factory() as session:
            await record_audit(
                company_id=None,
                actor_type="system",
                action="startup",
                db=session,
            )
            await session.commit()

        async with session_factory() as session:
            rows = await fetch_chain(session)

        assert len(rows) == 1
        assert rows[0].company_id is None
        assert chain_is_valid(rows)


class TestTamperingIsDetectable:
    """The point of the chain is that edits and gaps do not go unnoticed."""

    async def test_rewritten_field_breaks_verification(self, session_factory) -> None:
        company_id = uuid.uuid4()
        async with session_factory() as session:
            for index in range(3):
                await record_audit(
                    company_id=company_id,
                    actor_type="user",
                    action=f"action.{index}",
                    db=session,
                )
            await session.commit()

        async with session_factory() as session:
            rows = await fetch_chain(session)
            assert chain_is_valid(rows)
            # Simulate an attacker rewriting the action but leaving the stored
            # hash alone, which is what a raw UPDATE would do.
            rows[1].action = "action.tampered"
            assert not chain_is_valid(rows)

    async def test_removed_row_breaks_verification(self, session_factory) -> None:
        company_id = uuid.uuid4()
        async with session_factory() as session:
            for index in range(4):
                await record_audit(
                    company_id=company_id,
                    actor_type="user",
                    action=f"action.{index}",
                    db=session,
                )
            await session.commit()

        async with session_factory() as session:
            rows = await fetch_chain(session)

        # Dropping a middle row leaves a sequence gap and a dangling link.
        assert not chain_is_valid(rows[:1] + rows[2:])


class TestConcurrentWriters:
    """sequence_number is UNIQUE, so racing writers must not collide."""

    async def test_concurrent_writes_do_not_duplicate_a_sequence(
        self, session_factory, monkeypatch
    ) -> None:
        import nexus.database as database

        monkeypatch.setattr(database, "async_session_factory", session_factory)

        company_id = uuid.uuid4()
        await asyncio.gather(
            *(
                record_audit(
                    company_id=company_id,
                    actor_type="agent",
                    action=f"concurrent.{index}",
                )
                for index in range(8)
            )
        )

        async with session_factory() as session:
            result = await session.execute(select(AuditLog))
            rows = list(result.scalars())

        assert len(rows) == 8
        sequences = [row.sequence_number for row in rows if row.sequence_number is not None]
        assert len(sequences) == len(set(sequences)), "sequence numbers must be unique"


class TestFailureHandling:
    """A chain problem must not cost us the audit row itself."""

    async def test_row_is_written_even_if_chaining_fails(
        self, session_factory, monkeypatch
    ) -> None:
        import nexus.governance.audit_service as audit_service

        async def exploding_chain(session, entry):
            raise RuntimeError("chain tail unavailable")

        monkeypatch.setattr(audit_service, "_chain", exploding_chain)

        company_id = uuid.uuid4()
        async with session_factory() as session:
            await record_audit(
                company_id=company_id,
                actor_type="user",
                action="still.recorded",
                db=session,
            )
            await session.commit()

        async with session_factory() as session:
            result = await session.execute(select(AuditLog))
            rows = list(result.scalars())

        assert len(rows) == 1
        assert rows[0].action == "still.recorded"
        assert rows[0].sequence_number is None
