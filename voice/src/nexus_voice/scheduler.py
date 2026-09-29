"""Serialised model scheduler: one transcription call at a time on the shared model.

Exclusivity is held by a single runner that awaits the model thread to finish, so
cancelling a caller never frees the model while its thread is still running. Finals go
first; each connection has at most one queued partial (a newer one replaces it).
"""

from __future__ import annotations

import asyncio
import collections
from collections.abc import Callable
from typing import Any


class _Job:
    __slots__ = ("fn", "fut", "owner")

    def __init__(self, fn: Callable[[], Any], owner: object, fut: asyncio.Future) -> None:
        self.fn, self.owner, self.fut = fn, owner, fut


class ModelScheduler:
    def __init__(self) -> None:
        self._finals: collections.deque[_Job] = collections.deque()
        self._partials: dict[object, _Job] = {}
        self._wake = asyncio.Event()
        self._runner: asyncio.Task | None = None
        self.running = 0  # jobs executing right now; never above 1
        self.max_running = 0

    @property
    def queued(self) -> int:
        return len(self._finals) + len(self._partials)

    def _start(self) -> None:
        if self._runner is None or self._runner.done():
            self._runner = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while True:
            job = self._next()
            if job is None:
                self._wake.clear()
                await self._wake.wait()
                continue
            if job.fut.cancelled():  # caller left while queued
                continue
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            try:
                result = await asyncio.to_thread(job.fn)  # runner is not cancelled with callers
                if not job.fut.cancelled():
                    job.fut.set_result(result)
            except Exception as exc:
                if not job.fut.cancelled():
                    job.fut.set_exception(exc)
            finally:
                self.running -= 1

    def _next(self) -> _Job | None:
        if self._finals:
            return self._finals.popleft()
        if self._partials:
            return self._partials.pop(next(iter(self._partials)))
        return None

    def _submit(self, job: _Job) -> None:
        self._start()
        self._wake.set()

    async def final(self, owner: object, fn: Callable[[], Any]) -> Any:
        """Queue a final job ahead of every partial and wait for its result."""
        self._drop_partial(owner)  # its partials are stale the moment the final exists
        job = _Job(fn, owner, asyncio.get_running_loop().create_future())
        self._finals.append(job)
        self._submit(job)
        return await job.fut

    async def partial(self, owner: object, fn: Callable[[], Any]) -> Any:
        """Queue a partial (replacing this owner's queued one). Returns None if superseded."""
        self._drop_partial(owner)
        job = _Job(fn, owner, asyncio.get_running_loop().create_future())
        self._partials[owner] = job
        self._submit(job)
        try:
            return await job.fut
        except asyncio.CancelledError:
            if self._partials.get(owner) is job:
                del self._partials[owner]
            raise

    def _drop_partial(self, owner: object) -> None:
        old = self._partials.pop(owner, None)
        if old is not None and not old.fut.done():
            old.fut.set_result(None)

    def release(self, owner: object) -> None:
        """Connection gone: discard everything it has queued. A running job just finishes."""
        self._drop_partial(owner)
        for job in [j for j in self._finals if j.owner is owner]:
            self._finals.remove(job)
            job.fut.cancel()

    async def close(self) -> None:
        if self._runner:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)
