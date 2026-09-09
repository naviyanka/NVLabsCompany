"""Tests for TenantBulkhead concurrency governor (F5)."""

import asyncio
import uuid
import pytest

from nexus.governance.bulkhead import TenantBulkhead, TenantSaturated


@pytest.mark.asyncio
async def test_tenant_bulkhead_enforces_per_tenant_cap():
    bulkhead = TenantBulkhead(per_tenant=2, global_cap=10)
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()

    # Company A uses quota (2 slots)
    async with bulkhead.acquire(company_a):
        async with bulkhead.acquire(company_a):
            # Third request for Company A fails fast
            with pytest.raises(TenantSaturated):
                async with bulkhead.acquire(company_a):
                    pass

            # Company B still has slots
            async with bulkhead.acquire(company_b):
                pass


@pytest.mark.asyncio
async def test_tenant_bulkhead_restores_slots_after_exit():
    bulkhead = TenantBulkhead(per_tenant=1, global_cap=10)
    cid = uuid.uuid4()

    async with bulkhead.acquire(cid):
        pass

    # Next call succeeds because slot was released
    async with bulkhead.acquire(cid):
        pass


@pytest.mark.asyncio
async def test_tenant_bulkhead_enforces_global_cap():
    bulkhead = TenantBulkhead(per_tenant=10, global_cap=2)
    c1, c2, c3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async with bulkhead.acquire(c1):
        async with bulkhead.acquire(c2):
            with pytest.raises(TenantSaturated):
                async with bulkhead.acquire(c3):
                    pass
    assert bulkhead.global_in_flight == 0


@pytest.mark.asyncio
async def test_tenant_bulkhead_bounded_cache():
    bulkhead = TenantBulkhead(per_tenant=5, global_cap=50, max_cached_tenants=2)
    c1, c2, c3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async with bulkhead.acquire(c1):
        pass
    async with bulkhead.acquire(c2):
        pass
    async with bulkhead.acquire(c3):
        pass

    assert len(bulkhead._tenant_in_flight) <= 2

