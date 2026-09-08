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
