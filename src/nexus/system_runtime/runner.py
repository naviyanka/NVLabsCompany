"""Runs the catalogued operations: leader lease, timeout, audit and metrics around each.

One :class:`SystemRuntime` per process. :meth:`SystemRuntime.tick` is what the shared
scheduler loop (``nexus.runtime.scheduler``) calls, so the system runtime has no polling
loop of its own. Each operation holds a Redis lease while it runs, so with several system
runtime replicas an operation runs on one of them at a time. The operations are also
idempotent per company, so a lease lost mid-run (a hung leader) costs duplicated work at
worst, never a wrong write.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from nexus.observability.metrics import record_system_runtime_event, record_system_runtime_op
from nexus.system_runtime import audit, status
from nexus.system_runtime.ops import OPERATIONS, DiscoveryFactory, Operation, OpResult, _now

logger = logging.getLogger(__name__)

LeaderAcquire = Callable[[str, str, int], Awaitable[bool]]
LeaderRelease = Callable[[str, str], Awaitable[None]]


class SystemRuntime:
    def __init__(
        self,
        discovery_for: Callable[[str], DiscoveryFactory],
        *,
        operations: dict[str, Operation] | None = None,
        acquire: LeaderAcquire | None = None,
        release: LeaderRelease | None = None,
        clock: Callable[[], float] = time.monotonic,
        instance_id: str | None = None,
    ) -> None:
        from nexus.runtime.redis_utils import release_leader, try_acquire_leader

        self._discovery_for = discovery_for
        self.operations = operations if operations is not None else OPERATIONS
        self._acquire = acquire or try_acquire_leader
        self._release = release or release_leader
        self._clock = clock
        self._instance = instance_id or f"system-runtime-{uuid.uuid4().hex[:8]}"
        self._last_started: dict[str, float] = {}
        self.last_success: dict[str, float] = {}
        self.role_validation = "ok"

    async def run_operation(self, op: Operation) -> OpResult | None:
        """Run one operation under its lease. Returns None when another instance holds it."""
        lease = f"system_runtime:{op.name}"
        ttl = int(op.timeout_seconds) + 30
        if not await self._acquire(lease, self._instance, ttl):
            record_system_runtime_event("lock_contention")
            audit.emit("op_skipped_not_leader", operation=op.name)
            return None

        audit.emit("op_started", operation=op.name)
        started = time.monotonic()
        result = OpResult()
        code: str | None = None
        try:
            result = await asyncio.wait_for(
                op.run(self._discovery_for(op.name), _now()), op.timeout_seconds
            )
        except TimeoutError:
            code = "OP_TIMEOUT"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a failing operation must not stop the runtime
            code = "OP_FAILED"
            logger.warning("system runtime: %s failed (%s)", op.name, type(exc).__name__)
        finally:
            await self._release(lease, self._instance)

        duration = time.monotonic() - started
        ok = code is None
        record_system_runtime_op(
            op.name, duration, processed=result.processed, failed=result.failed, ok=ok
        )
        if ok:
            record_system_runtime_event("op_completed")
            self.last_success[op.name] = time.time()
            audit.emit(
                "op_completed",
                operation=op.name,
                companies_seen=result.seen,
                companies_processed=result.processed,
                companies_failed=result.failed,
                batches=result.batches,
                duration_ms=int(duration * 1000),
            )
        else:
            record_system_runtime_event("op_failed")
            audit.emit("op_failed", operation=op.name, code=code, duration_ms=int(duration * 1000))
        return result

    async def tick(self) -> None:
        """Run every operation whose interval has elapsed, then publish status."""
        for op in self.operations.values():
            last = self._last_started.get(op.name)
            if last is not None and self._clock() - last < op.interval_seconds:
                continue
            self._last_started[op.name] = self._clock()
            await self.run_operation(op)
        await status.publish(
            ops_enabled=list(self.operations),
            role_validation=self.role_validation,
            last_success=self.last_success,
        )
