"""Per-tenant concurrency bulkhead (F5).

Prevents a high-throughput tenant from exhausting shared worker execution pools.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator


class TenantSaturated(Exception):
    """Raised when a tenant exhausts its concurrency quota."""

    def __init__(self, company_id: uuid.UUID, retry_after: int = 5) -> None:
        super().__init__(f"Tenant {company_id} concurrency limit reached")
        self.company_id = company_id
        self.retry_after = retry_after


class TenantBulkhead:
    """Isolates tenant concurrency with global and per-tenant caps."""

    def __init__(self, per_tenant: int = 16, global_cap: int = 128) -> None:
        self.per_tenant = per_tenant
        self._global_sem = asyncio.Semaphore(global_cap)
        self._tenant_sems: dict[uuid.UUID, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    async def _get_tenant_semaphore(self, company_id: uuid.UUID) -> asyncio.Semaphore:
        async with self._lock:
            if company_id not in self._tenant_sems:
                self._tenant_sems[company_id] = asyncio.Semaphore(self.per_tenant)
            return self._tenant_sems[company_id]

    @asynccontextmanager
    async def acquire(self, company_id: uuid.UUID) -> AsyncIterator[None]:
        sem = await self._get_tenant_semaphore(company_id)
        if sem.locked() and sem._value <= 0:
            raise TenantSaturated(company_id)

        async with self._global_sem, sem:
            yield
