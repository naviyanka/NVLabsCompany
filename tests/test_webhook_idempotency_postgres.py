"""Webhook replay protection against real PostgreSQL, as the RLS-bound app role.

The ledger is ``idempotency_records`` (company-scoped, FORCE RLS); no table or
migration was added. Runs against a disposable PostgreSQL (testcontainers, or
``TEST_DATABASE_URL``); skipped when neither is available.
"""
# ruff: noqa: F811 -- pytest fixtures imported from test_postgres_integration

import asyncio
import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import DBAPIError

from nexus.communication import webhook_idempotency as ledger
from nexus.communication.webhook_idempotency import Outcome
from nexus.database import tenant_session
from nexus.models.idempotency import IdempotencyRecord
from tests.test_postgres_integration import (  # noqa: F401 -- fixtures
    _companies,
    app_role,
    app_user_postgres_url,
    migrated_postgres_url,
    postgres_container,
    system_user_postgres_url,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

HASH = "a" * 64
OTHER_HASH = "b" * 64


def _key() -> str:
    return f"delivery-{uuid.uuid4().hex}"


async def _rows(company_id: uuid.UUID) -> list[IdempotencyRecord]:
    async with tenant_session(company_id) as db:
        return list((await db.execute(sa.select(IdempotencyRecord))).scalars().all())


async def _expire_lease(company_id: uuid.UUID, record_id: uuid.UUID) -> None:
    async with tenant_session(company_id) as db:
        await db.execute(
            sa.update(IdempotencyRecord)
            .where(IdempotencyRecord.id == record_id)
            .values(expires_at=ledger._now() - timedelta(seconds=1))
        )
        await db.commit()


async def _noop(_session) -> None:
    return None


def test_no_migration_was_added_and_there_is_one_head():
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert len(heads) == 1, heads


async def test_ledger_table_has_forced_rls(migrated_postgres_url):
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(migrated_postgres_url)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                        "(SELECT count(*) FROM pg_policies p "
                        " WHERE p.tablename = c.relname) "
                        "FROM pg_class c WHERE c.relname = 'idempotency_records'"
                    )
                )
            ).one()
        assert (row[0], row[1]) == (True, True) and row[2] >= 1
    finally:
        await engine.dispose()


async def test_claim_replay_and_conflict(app_role):
    (company,) = await _companies(app_role, 1)
    trigger, key = uuid.uuid4(), _key()

    first = await ledger.begin(company, trigger, key, HASH)
    assert first.outcome is Outcome.CLAIMED and first.claim is not None

    # Still running: a duplicate is told to wait, a different payload conflicts.
    assert (await ledger.begin(company, trigger, key, HASH)).outcome is Outcome.BUSY
    assert (await ledger.begin(company, trigger, key, OTHER_HASH)).outcome is Outcome.CONFLICT

    effects: list[int] = []

    async def effect(_session) -> None:
        effects.append(1)

    assert await ledger.finish(company, first.claim, effect, 202, {"execution_id": "x"})
    replay = await ledger.begin(company, trigger, key, HASH)
    assert replay.outcome is Outcome.REPLAY
    assert replay.status_code == 202 and replay.body == '{"execution_id":"x"}'
    assert (await ledger.begin(company, trigger, key, OTHER_HASH)).outcome is Outcome.CONFLICT
    assert effects == [1]

    (row,) = await _rows(company)
    assert row.idem_key == f"webhook:{trigger}:{key}"
    assert row.request_hash == HASH and row.state == "complete"


async def test_same_key_is_scoped_by_trigger(app_role):
    (company,) = await _companies(app_role, 1)
    key = _key()
    one = await ledger.begin(company, uuid.uuid4(), key, HASH)
    two = await ledger.begin(company, uuid.uuid4(), key, OTHER_HASH)
    assert one.outcome is Outcome.CLAIMED and two.outcome is Outcome.CLAIMED


async def test_tenants_never_share_a_key_or_see_each_others_rows(app_role):
    a, b = await _companies(app_role, 2)
    trigger, key = uuid.uuid4(), _key()

    claim_a = await ledger.begin(a, trigger, key, HASH)
    # The same trigger id and key under another tenant is its own delivery.
    claim_b = await ledger.begin(b, trigger, key, OTHER_HASH)
    assert claim_a.outcome is claim_b.outcome is Outcome.CLAIMED

    assert [r.company_id for r in await _rows(a)] == [a]
    assert [r.company_id for r in await _rows(b)] == [b]

    # Tenant B cannot finish or release tenant A's claim.
    assert not await ledger.finish(b, claim_a.claim, _noop, 202, {})
    await ledger.release(b, claim_a.claim)
    assert [r.state for r in await _rows(a)] == ["in_flight"]

    # No tenant bound: nothing is visible, and nothing can be forged in.
    async with app_role() as db:
        assert (await db.execute(sa.select(IdempotencyRecord))).scalars().all() == []
    async with tenant_session(a) as db:
        db.add(
            IdempotencyRecord(
                company_id=b,
                idem_key=f"webhook:{trigger}:smuggled",
                endpoint="/api/v1/webhooks/x",
                request_hash=HASH,
                state="in_flight",
                created_at=ledger._now(),
                expires_at=ledger._now() + ledger.LEASE,
            )
        )
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.commit()


async def test_concurrent_identical_deliveries_have_one_winner(app_role):
    (company,) = await _companies(app_role, 1)
    trigger, key = uuid.uuid4(), _key()

    results = await asyncio.gather(
        *(ledger.begin(company, trigger, key, HASH) for _ in range(12))
    )
    claimed = [r for r in results if r.outcome is Outcome.CLAIMED]
    assert len(claimed) == 1
    assert all(r.outcome is Outcome.BUSY for r in results if r is not claimed[0])
    assert len(await _rows(company)) == 1

    effects: list[int] = []

    async def effect(_session) -> None:
        effects.append(1)

    assert await ledger.finish(company, claimed[0].claim, effect, 202, {"ok": True})

    after = await asyncio.gather(
        *(ledger.begin(company, trigger, key, HASH) for _ in range(12))
    )
    assert {r.outcome for r in after} == {Outcome.REPLAY}
    assert {r.body for r in after} == {'{"ok":true}'}
    assert effects == [1]


async def test_a_crashed_worker_is_recovered_and_cannot_double_record(app_role):
    (company,) = await _companies(app_role, 1)
    trigger, key = uuid.uuid4(), _key()

    crashed = await ledger.begin(company, trigger, key, HASH)
    assert (await ledger.begin(company, trigger, key, HASH)).outcome is Outcome.BUSY

    await _expire_lease(company, crashed.claim.record_id)

    # Racing recoveries: exactly one takes the expired lease.
    takeovers = await asyncio.gather(
        *(ledger.begin(company, trigger, key, HASH) for _ in range(8))
    )
    winners = [r for r in takeovers if r.outcome is Outcome.CLAIMED]
    assert len(winners) == 1
    assert all(r.outcome is Outcome.BUSY for r in takeovers if r is not winners[0])
    assert winners[0].claim.fence != crashed.claim.fence

    # The stalled original wakes up late: it records nothing and cannot release.
    effects: list[str] = []

    async def stale(_session) -> None:
        effects.append("stale")

    async def fresh(_session) -> None:
        effects.append("fresh")

    assert not await ledger.finish(company, crashed.claim, stale, 202, {"who": "stale"})
    await ledger.release(company, crashed.claim)
    assert [r.state for r in await _rows(company)] == ["in_flight"]

    assert await ledger.finish(company, winners[0].claim, fresh, 202, {"who": "fresh"})
    assert effects == ["fresh"]
    replay = await ledger.begin(company, trigger, key, HASH)
    assert replay.outcome is Outcome.REPLAY and replay.body == '{"who":"fresh"}'


async def test_release_lets_a_retry_run_at_once(app_role):
    (company,) = await _companies(app_role, 1)
    trigger, key = uuid.uuid4(), _key()

    first = await ledger.begin(company, trigger, key, HASH)
    await ledger.release(company, first.claim)
    assert await _rows(company) == []

    assert (await ledger.begin(company, trigger, key, HASH)).outcome is Outcome.CLAIMED


async def test_expired_rows_are_purged_and_the_key_becomes_reusable(app_role):
    (company,) = await _companies(app_role, 1)
    trigger, key = uuid.uuid4(), _key()

    claim = (await ledger.begin(company, trigger, key, HASH)).claim
    assert await ledger.finish(company, claim, _noop, 202, {})
    await _expire_lease(company, claim.record_id)  # retention deadline passed

    # A new delivery under another key purges it; the old key starts fresh.
    await ledger.begin(company, trigger, _key(), HASH)
    assert all(r.idem_key != f"webhook:{trigger}:{key}" for r in await _rows(company))
    assert (await ledger.begin(company, trigger, key, OTHER_HASH)).outcome is Outcome.CLAIMED


async def test_ledger_stores_a_hash_and_the_response_but_no_payload(app_role):
    (company,) = await _companies(app_role, 1)
    claim = (await ledger.begin(company, uuid.uuid4(), _key(), HASH)).claim
    await ledger.finish(company, claim, _noop, 202, {"status": "accepted"})

    (row,) = await _rows(company)
    assert len(row.request_hash) == 64 and row.response_body == '{"status":"accepted"}'
