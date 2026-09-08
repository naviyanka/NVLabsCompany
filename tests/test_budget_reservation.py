"""Tests for two-phase budget reservation (BudgetService.reserve/commit/release).

The point of the reservation is that a hold counts against the budget the same
as settled spend, so two concurrent workers cannot both pass a check only one of
them fits under. These tests drive a real SQLite database because the guarantee
lives in the window-sum SQL, not in Python.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexus.models.budget import BudgetPolicy, CostEvent
from nexus.services.budget_service import BudgetService


@pytest.fixture
async def session_factory(tmp_path):
    """A SQLite database holding just the two budget tables."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'budget.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[BudgetPolicy.__table__, CostEvent.__table__],
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_policy(factory, company_id: uuid.UUID, amount: int) -> None:
    """Give the company a monthly hard-stop cap of ``amount`` cents."""
    async with factory() as db:
        db.add(
            BudgetPolicy(
                company_id=company_id,
                scope_type="company",
                scope_id=company_id,
                metric="cost_cents",
                window_kind="monthly",
                amount=amount,
                hard_stop_enabled=True,
            )
        )
        await db.commit()


class TestReservationBlocksConcurrentSpend:
    """A live hold has to be visible to the next worker's check."""

    async def test_second_reservation_denied_by_first_hold(self, session_factory):
        """Two workers, one budget: the second sees the first hold and is refused."""
        company_id = uuid.uuid4()
        await _seed_policy(session_factory, company_id, amount=100)

        async with session_factory() as db_a:
            allowed_a, res_a, _ = await BudgetService(db_a).reserve(
                company_id, estimate_cents=80
            )
        assert allowed_a is True
        assert res_a is not None

        # Nothing has been billed yet -- only held. Without the hold counting,
        # this second check would see zero spend and pass.
        async with session_factory() as db_b:
            allowed_b, res_b, check_b = await BudgetService(db_b).reserve(
                company_id, estimate_cents=80
            )
        assert allowed_b is False
        assert res_b is None
        assert check_b.used_cents == 80

    async def test_released_hold_frees_the_budget(self, session_factory):
        """A call that never billed returns its hold to the pool."""
        company_id = uuid.uuid4()
        await _seed_policy(session_factory, company_id, amount=100)

        async with session_factory() as db:
            _, res, _ = await BudgetService(db).reserve(company_id, estimate_cents=80)
            assert await BudgetService(db).release_reservation(res.id) is True

        async with session_factory() as db:
            allowed, _, check = await BudgetService(db).reserve(
                company_id, estimate_cents=80
            )
        assert allowed is True
        assert check.used_cents == 0

    async def test_expired_hold_stops_counting(self, session_factory):
        """A worker that died mid-call must not pin the budget forever."""
        company_id = uuid.uuid4()
        await _seed_policy(session_factory, company_id, amount=100)

        async with session_factory() as db:
            _, res, _ = await BudgetService(db).reserve(company_id, estimate_cents=80)
            # Simulate the TTL elapsing rather than sleeping through it.
            res.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                seconds=1
            )
            db.add(res)
            await db.commit()

        async with session_factory() as db:
            allowed, _, check = await BudgetService(db).reserve(
                company_id, estimate_cents=80
            )
        assert allowed is True
        assert check.used_cents == 0


class TestCommitReconcilesToActualCost:
    """Phase two replaces the estimate with the real figure."""

    async def test_commit_overwrites_estimate(self, session_factory):
        """A cheaper-than-estimated call frees the difference for the next call."""
        company_id = uuid.uuid4()
        await _seed_policy(session_factory, company_id, amount=100)

        async with session_factory() as db:
            _, res, _ = await BudgetService(db).reserve(company_id, estimate_cents=80)
            settled = await BudgetService(db).commit_reservation(
                res.id, cost_cents=10, input_tokens=100, output_tokens=50
            )
        assert settled is True

        async with session_factory() as db:
            allowed, _, check = await BudgetService(db).reserve(
                company_id, estimate_cents=80
            )
        assert allowed is True
        assert check.used_cents == 10

    async def test_commit_is_idempotent(self, session_factory):
        """Settling twice must not double-charge: only reserved rows are settled."""
        company_id = uuid.uuid4()
        await _seed_policy(session_factory, company_id, amount=1000)

        async with session_factory() as db:
            service = BudgetService(db)
            _, res, _ = await service.reserve(company_id, estimate_cents=80)
            assert await service.commit_reservation(res.id, cost_cents=10) is True
            assert await service.commit_reservation(res.id, cost_cents=10) is False

        async with session_factory() as db:
            usage = await BudgetService(db).get_usage("company", company_id)
        assert usage.total_cost_cents == 10

    async def test_release_after_commit_does_not_refund(self, session_factory):
        """A settled row is real spend; a stray release must not erase it."""
        company_id = uuid.uuid4()
        await _seed_policy(session_factory, company_id, amount=1000)

        async with session_factory() as db:
            service = BudgetService(db)
            _, res, _ = await service.reserve(company_id, estimate_cents=80)
            await service.commit_reservation(res.id, cost_cents=40)
            assert await service.release_reservation(res.id) is False

        async with session_factory() as db:
            usage = await BudgetService(db).get_usage("company", company_id)
        assert usage.total_cost_cents == 40


class TestLegacyRowsStillCount:
    """Spend recorded before reservations existed is settled spend."""

    async def test_record_cost_row_counts_against_budget(self, session_factory):
        """record_cost writes a committed row, so it shows up in the window sum."""
        company_id = uuid.uuid4()
        await _seed_policy(session_factory, company_id, amount=100)

        async with session_factory() as db:
            await BudgetService(db).record_cost(company_id, cost_cents=95)
            await db.commit()

        async with session_factory() as db:
            allowed, _, check = await BudgetService(db).reserve(
                company_id, estimate_cents=10
            )
        assert allowed is False
        assert check.used_cents == 95

    async def test_reaper_clears_expired_reservation(self, session_factory):
        """Expired reservations are reaped, releasing held capacity."""
        company_id = uuid.uuid4()
        await _seed_policy(session_factory, company_id, amount=100)

        async with session_factory() as db:
            service = BudgetService(db)
            # Hold with -1 TTL (immediately expired)
            allowed, res, _ = await service.reserve(
                company_id, estimate_cents=80, ttl_seconds=-10
            )
            assert allowed is True

            reaped = await service.reap_expired_reservations()
            assert reaped == 1

            # Capacity is restored
            allowed_again, _, check = await service.reserve(
                company_id, estimate_cents=50
            )
            assert allowed_again is True
            assert check.used_cents == 0
