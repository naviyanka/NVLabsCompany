"""Per-key sliding-window rate limits and single-use tickets, held on ``app.state``."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


class TicketBook:
    """Redeemed ticket ids. In-process: a multi-process deployment needs a shared store."""

    def __init__(self) -> None:
        self._used: dict[str, float] = {}

    def redeem(self, jti: str, exp: float) -> bool:
        now = time.time()
        self._used = {j: e for j, e in self._used.items() if e > now}
        if jti in self._used:
            return False
        self._used[jti] = exp
        return True
