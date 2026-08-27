"""Delegation permits - caps how many sub-agents a lead runs concurrently.

A lead that fans out ten sub-tasks should not spawn ten sandboxes at once.
Each sub-task must hold a permit for its whole life and give it back on every
terminal path, including a crash.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

# Default number of sub-agents a single lead may run concurrently.
DEFAULT_SUBAGENT_CAP: int = 3


class SubagentPermits:
    """Concurrency permits for sub-agent delegation, scoped per lead agent.

    Attributes:
        cap: Maximum number of concurrent sub-agents per lead.
    """

    def __init__(self, cap: int = DEFAULT_SUBAGENT_CAP) -> None:
        """Initialize the permit pool.

        Args:
            cap: Maximum concurrent sub-agents per lead. Must be at least 1.

        Raises:
            ValueError: If cap is less than 1.
        """
        if cap < 1:
            raise ValueError(f"cap must be >= 1, got {cap}")
        self.cap = cap
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._held: dict[str, int] = {}
        # (lead, holder) pairs currently holding a slot. Tracking the holder is
        # what makes acquire idempotent: a retried or replayed delegation must
        # not consume a second slot for work already running.
        self._holders: set[tuple[str, str]] = set()

    def _semaphore(self, lead_id: Any) -> asyncio.Semaphore:
        lead = str(lead_id)
        sem = self._semaphores.get(lead)
        if sem is None:
            sem = asyncio.Semaphore(self.cap)
            self._semaphores[lead] = sem
        return sem

    async def acquire_subagent_permit(
        self,
        lead_id: Any,
        holder_id: Any = None,
        timeout: float | None = None,
    ) -> bool:
        """Acquire a permit for one sub-agent under a lead.

        Waits in FIFO order when the cap is reached.

        Args:
            lead_id: The lead agent spawning the sub-agent; the cap is per lead.
            holder_id: Optional id of the sub-agent taking the slot. When given,
                re-acquiring for a holder that already holds one is a no-op, so
                retries and replays do not consume two slots.
            timeout: Optional seconds to wait before giving up.

        Returns:
            True if a permit is held, False if the timeout elapsed.
        """
        lead = str(lead_id)
        key = (lead, str(holder_id)) if holder_id is not None else None
        if key is not None and key in self._holders:
            return True

        sem = self._semaphore(lead_id)
        # ponytail: semaphore FIFO wait instead of poll-with-backoff; swap in
        # backoff only if permits ever move to a shared store like Redis.
        if timeout is None:
            await sem.acquire()
        else:
            try:
                await asyncio.wait_for(sem.acquire(), timeout)
            except TimeoutError:
                return False

        self._held[lead] = self._held.get(lead, 0) + 1
        if key is not None:
            self._holders.add(key)
        return True

    def release_subagent_permit(self, lead_id: Any, holder_id: Any = None) -> bool:
        """Release a permit held under a lead.

        Safe to call more than once for the same sub-agent; extra calls are
        ignored so crash-recovery sweeps cannot inflate the cap.

        Args:
            lead_id: The lead agent whose permit is returned.
            holder_id: Optional id of the sub-agent releasing the slot.

        Returns:
            True if a permit was released, False if none was held.
        """
        lead = str(lead_id)
        if holder_id is not None:
            key = (lead, str(holder_id))
            if key not in self._holders:
                return False
            self._holders.discard(key)
        elif self._held.get(lead, 0) <= 0:
            return False

        self._held[lead] = max(0, self._held.get(lead, 0) - 1)
        self._semaphore(lead_id).release()
        return True

    @asynccontextmanager
    async def permit(
        self,
        lead_id: Any,
        holder_id: Any = None,
        timeout: float | None = None,
    ) -> AsyncIterator[bool]:
        """Hold a permit for the duration of a block, releasing on every exit.

        Args:
            lead_id: The lead agent spawning the sub-agent.
            holder_id: Optional id of the sub-agent taking the slot.
            timeout: Optional seconds to wait for a permit.

        Yields:
            True if a permit is held inside the block, False on timeout.
        """
        acquired = await self.acquire_subagent_permit(lead_id, holder_id, timeout)
        try:
            yield acquired
        finally:
            if acquired:
                self.release_subagent_permit(lead_id, holder_id)

    def available(self, lead_id: Any) -> int:
        """Return how many permits remain free for a lead.

        Args:
            lead_id: The lead agent.

        Returns:
            Number of permits still available.
        """
        return self.cap - self._held.get(str(lead_id), 0)

    def held(self, lead_id: Any) -> int:
        """Return how many permits a lead currently holds.

        Args:
            lead_id: The lead agent.

        Returns:
            Number of permits held.
        """
        return self._held.get(str(lead_id), 0)

    def release_all(self, lead_id: Any) -> int:
        """Release every permit held by a lead, for crash recovery.

        Args:
            lead_id: The lead agent to sweep.

        Returns:
            Number of permits released.
        """
        lead = str(lead_id)
        released = 0
        for held_lead, holder in list(self._holders):
            if held_lead == lead and self.release_subagent_permit(lead, holder):
                released += 1
        while self.release_subagent_permit(lead):
            released += 1
        return released
