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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from nexus.governance.audit_persistent import (
    PersistentAuditEntry,
    PersistentAuditLogger,
    compute_entry_hash,
)
from nexus.governance.audit_service import AuditChainError, record_audit
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


class TestOneChainPerCompany:
    """Each company's rows form their own chain, verifiable on their own."""

    async def test_each_company_starts_its_own_chain(self, session_factory) -> None:
        first, second = uuid.uuid4(), uuid.uuid4()
        async with session_factory() as session:
            for index in range(3):
                for company_id in (first, second):
                    await record_audit(
                        company_id=company_id, action=f"step.{index}", db=session
                    )
            await session.commit()

        for company_id in (first, second):
            logger = PersistentAuditLogger(session_factory=session_factory, company_id=company_id)
            entries = await logger.chain_entries()
            assert [e.sequence_number for e in entries] == [1, 2, 3]
            assert entries[0].previous_hash == "genesis"
            assert {e.company_id for e in entries} == {company_id}
            assert await logger.verify_chain_integrity()

    async def test_a_sequence_is_unique_within_a_company_only(self, session_factory) -> None:
        first, second = uuid.uuid4(), uuid.uuid4()
        async with session_factory() as session:
            session.add(AuditLog(company_id=first, actor_type="x", action="a", sequence_number=1))
            session.add(AuditLog(company_id=second, actor_type="x", action="a", sequence_number=1))
            await session.commit()
            session.add(AuditLog(company_id=first, actor_type="x", action="b", sequence_number=1))
            with pytest.raises(IntegrityError):
                await session.commit()

    async def test_tampering_in_one_company_leaves_the_other_valid(
        self, session_factory
    ) -> None:
        from nexus.governance.audit_persistent import chain_is_intact

        first, second = uuid.uuid4(), uuid.uuid4()
        async with session_factory() as session:
            for company_id in (first, second, first, second):
                await record_audit(company_id=company_id, action="step", db=session)
            await session.commit()

        chains = {
            company_id: await PersistentAuditLogger(
                session_factory=session_factory, company_id=company_id
            ).chain_entries()
            for company_id in (first, second)
        }
        chains[first][0].action = "rewritten"
        assert not chain_is_intact(chains[first])
        assert chain_is_intact(chains[second])


class TestConcurrentWriters:
    """(company_id, sequence_number) is unique, so racing writers must not collide."""

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
        assert sorted(row.sequence_number for row in rows) == list(range(1, 9))

    async def test_concurrent_writes_in_two_companies_form_two_chains(
        self, session_factory, monkeypatch
    ) -> None:
        import nexus.database as database

        monkeypatch.setattr(database, "async_session_factory", session_factory)

        companies = (uuid.uuid4(), uuid.uuid4())
        await asyncio.gather(
            *(
                record_audit(company_id=companies[index % 2], action=f"concurrent.{index}")
                for index in range(12)
            )
        )

        for company_id in companies:
            logger = PersistentAuditLogger(session_factory=session_factory, company_id=company_id)
            entries = await logger.chain_entries()
            assert [e.sequence_number for e in entries] == list(range(1, 7))
            assert await logger.verify_chain_integrity()

    async def test_contended_writes_survive_an_earlier_event_loop(
        self, session_factory, monkeypatch
    ) -> None:
        """A burst on one event loop must not break bursts on the next.

        The chain lock used to be a module-level asyncio.Lock. Once contended it
        binds to that loop, and every contended write on a later loop raised
        inside record_audit and was silently dropped.
        """
        import nexus.database as database

        async def burst(prefix: str) -> None:
            await asyncio.gather(
                *(
                    record_audit(company_id=uuid.uuid4(), actor_type="agent", action=f"{prefix}.{i}")
                    for i in range(4)
                )
            )

        async def burst_on_its_own_database() -> None:
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            monkeypatch.setattr(
                database,
                "async_session_factory",
                async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
            )
            await burst("other-loop")
            await engine.dispose()

        await asyncio.to_thread(asyncio.run, burst_on_its_own_database())

        monkeypatch.setattr(database, "async_session_factory", session_factory)
        await burst("this-loop")

        async with session_factory() as session:
            rows = list((await session.execute(select(AuditLog))).scalars())
        assert len(rows) == 4


class TestFailureHandling:
    """A row is written with its chain links or not at all."""

    @pytest.fixture
    def exploding_chain(self, monkeypatch):
        import nexus.governance.audit_service as audit_service

        calls = []

        async def exploding(session, entry):
            calls.append(entry.action)
            raise RuntimeError("chain tail unavailable")

        monkeypatch.setattr(audit_service, "_chain", exploding)
        return calls

    @pytest.fixture
    def colliding_chain(self, monkeypatch):
        """Every allocation claims sequence 1, which is already taken."""
        import nexus.governance.audit_service as audit_service

        real_chain = audit_service._chain
        calls = []

        async def colliding(session, entry):
            await real_chain(session, entry)
            calls.append(entry.sequence_number)
            entry.sequence_number = 1

        monkeypatch.setattr(audit_service, "_chain", colliding)
        return calls

    async def rows(self, session_factory) -> list[AuditLog]:
        async with session_factory() as session:
            return list((await session.execute(select(AuditLog))).scalars())

    async def test_a_failed_link_writes_no_row_and_keeps_the_callers_transaction(
        self, session_factory, exploding_chain
    ) -> None:
        async with session_factory() as session:
            await record_audit(company_id=uuid.uuid4(), action="not.recorded", db=session)
            session.add(AuditLog(company_id=None, actor_type="x", action="caller.work"))
            await session.commit()

        assert exploding_chain == ["not.recorded"] * 5
        assert [row.action for row in await self.rows(session_factory)] == ["caller.work"]

    async def test_raise_on_error_fails_closed(self, session_factory, exploding_chain) -> None:
        async with session_factory() as session:
            with pytest.raises(RuntimeError, match="audit log write failed") as caught:
                await record_audit(
                    company_id=uuid.uuid4(), action="x", db=session, raise_on_error=True
                )
        assert isinstance(caught.value.__cause__, AuditChainError)
        assert await self.rows(session_factory) == []

    async def test_collisions_until_retries_run_out_write_no_unchained_row(
        self, session_factory, colliding_chain, monkeypatch
    ) -> None:
        import nexus.database as database

        monkeypatch.setattr(database, "async_session_factory", session_factory)
        company_id = uuid.uuid4()
        async with session_factory() as session:
            session.add(AuditLog(
                company_id=company_id, actor_type="x", action="first",
                sequence_number=1, previous_hash="genesis", entry_hash="h",
            ))
            await session.commit()

        await record_audit(company_id=company_id, action="own.session")
        async with session_factory() as session:
            await record_audit(company_id=company_id, action="caller.session", db=session)
            await session.commit()

        assert colliding_chain == [2] * 10
        rows = await self.rows(session_factory)
        assert [row.action for row in rows] == ["first"]
        assert all(row.sequence_number is not None for row in rows)
