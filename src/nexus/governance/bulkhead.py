"""Per-tenant concurrency bulkhead (F5 / WP-10).

Prevents a high-throughput tenant from exhausting shared worker execution pools.
Thread-safe / task-safe tracking of in-flight executions with lock-guarded counters,
bounded tenant cache, and fast-fail TenantSaturated exception without touching private sem._value.
"""

import asyncio
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import AsyncIterator


class TenantSaturated(Exception):
    """Raised when a tenant exhausts its concurrency quota."""

    def __init__(self, company_id: uuid.UUID, retry_after: int = 5) -> None:
        super().__init__(f"Tenant {company_id} concurrency limit reached")
        self.company_id = company_id
        self.retry_after = retry_after


class GlobalSaturated(Exception):
    """Raised when the process exhausts its global concurrency cap (WP-19d)."""

    def __init__(self, retry_after: int = 5) -> None:
        super().__init__("Global concurrency cap reached")
        self.retry_after = retry_after


class TenantBulkhead:
    """Isolates tenant concurrency with global and per-tenant caps."""

    def __init__(
        self,
        per_tenant: int = 16,
        global_cap: int = 128,
        max_cached_tenants: int = 1000,
    ) -> None:
        self.per_tenant = per_tenant
        self.global_cap = global_cap
        self.max_cached_tenants = max_cached_tenants
        self._global_in_flight: int = 0
        self._tenant_in_flight: OrderedDict[uuid.UUID, int] = OrderedDict()
        self._lock = asyncio.Lock()

    def in_flight(self, company_id: uuid.UUID) -> int:
        """Read active count for a tenant (snapshot)."""
        return self._tenant_in_flight.get(company_id, 0)

    @property
    def global_in_flight(self) -> int:
        """Read global active count (snapshot)."""
        return self._global_in_flight

    @asynccontextmanager
    async def acquire(self, company_id: uuid.UUID) -> AsyncIterator[None]:
        """Atomically claim a slot under per-tenant and global caps."""
        async with self._lock:
            if self._global_in_flight >= self.global_cap:
                raise GlobalSaturated()

            current_tenant = self._tenant_in_flight.get(company_id, 0)
            if current_tenant >= self.per_tenant:
                raise TenantSaturated(company_id)

            self._tenant_in_flight[company_id] = current_tenant + 1
            self._tenant_in_flight.move_to_end(company_id)
            self._global_in_flight += 1

            # Prune inactive tenants if cache size exceeded (scan up to 20 oldest items)
            if len(self._tenant_in_flight) > self.max_cached_tenants:
                prune_candidates = [k for k, v in list(self._tenant_in_flight.items())[:20] if v == 0]
                for k in prune_candidates:
                    del self._tenant_in_flight[k]

        try:
            yield
        finally:
            async with self._lock:
                self._global_in_flight = max(0, self._global_in_flight - 1)
                if company_id in self._tenant_in_flight:
                    new_count = max(0, self._tenant_in_flight[company_id] - 1)
                    if new_count == 0:
                        del self._tenant_in_flight[company_id]
                    else:
                        self._tenant_in_flight[company_id] = new_count
