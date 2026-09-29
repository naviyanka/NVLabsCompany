"""Shared voice state: single-use tickets, per-user/per-company rate limits, revocation.

Redis is the shared store (already used for NEXUS rate limiting), so every API worker
sees the same redemptions and counters. If it is unreachable the gateway fails closed;
an in-process store is used only when ``VOICE_ALLOW_LOCAL_STATE=true`` (single-process dev).
"""

from __future__ import annotations

import logging
import math
import time

from nexus.config import settings
from nexus.runtime.redis_utils import tenant_key
from nexus.voice.limits import RateLimiter, TicketBook

logger = logging.getLogger(__name__)


class SharedStateUnavailableError(Exception):
    pass


def _limits(kind: str) -> tuple[int, int]:
    """(per user, per company) per minute for ``utterance`` or ``session``."""
    user = getattr(settings, f"voice_{kind}s_per_minute")
    return user, getattr(settings, f"voice_company_{kind}s_per_minute")


class MemoryStore:
    """Single process only. Not shared between workers; development fallback."""

    shared = False

    def __init__(self) -> None:
        self._tickets = TicketBook()
        self._limiters: dict[tuple[str, str], RateLimiter] = {}
        self._revoked: set[str] = set()

    async def redeem(self, company_id, jti: str, ttl: float) -> bool:
        return self._tickets.redeem(f"{company_id}:{jti}", time.time() + ttl)

    async def allow(self, kind: str, company_id, user_id) -> bool:
        user, company = _limits(kind)

        def lim(scope: str, n: int) -> RateLimiter:
            return self._limiters.setdefault((kind, scope), RateLimiter(n))

        return lim(f"c:{company_id}", company).allow("c") and lim(
            f"u:{company_id}:{user_id}", user
        ).allow("u")

    async def revoke(self, company_id, session_id: str) -> None:
        self._revoked.add(f"{company_id}:{session_id}")

    async def revoked(self, company_id, session_id: str) -> bool:
        return f"{company_id}:{session_id}" in self._revoked


class RedisStore:
    shared = True

    def __init__(self, client) -> None:
        self.r = client

    async def _do(self, coro):
        from redis.exceptions import RedisError

        try:
            return await coro
        except (RedisError, OSError, TimeoutError) as exc:
            raise SharedStateUnavailableError(type(exc).__name__) from exc

    async def redeem(self, company_id, jti: str, ttl: float) -> bool:
        """Atomic consume-once: SET NX with the ticket's remaining lifetime as TTL."""
        key = tenant_key(company_id, "voice", "ticket", jti)
        return bool(await self._do(self.r.set(key, "1", nx=True, ex=max(1, math.ceil(ttl)))))

    async def allow(self, kind: str, company_id, user_id) -> bool:
        # ponytail: fixed 1-min windows (2x burst at edges); sliding window if needed
        window = int(time.time() // 60)
        keys = [
            tenant_key(company_id, "voice", "rl", kind, "user", user_id, window),
            tenant_key(company_id, "voice", "rl", kind, "company", window),
        ]
        pipe = self.r.pipeline(transaction=True)
        for k in keys:
            pipe.incr(k)
            pipe.expire(k, 120)
        counts = (await self._do(pipe.execute()))[::2]
        user, company = _limits(kind)
        return counts[0] <= user and counts[1] <= company

    async def revoke(self, company_id, session_id: str) -> None:
        key = tenant_key(company_id, "voice", "revoked", session_id)
        await self._do(self.r.set(key, "1", ex=settings.voice_session_ttl_seconds + 60))

    async def revoked(self, company_id, session_id: str) -> bool:
        return bool(
            await self._do(self.r.exists(tenant_key(company_id, "voice", "revoked", session_id)))
        )


async def get_store(app):
    """The app's store: Redis, or the explicit dev fallback, else fail closed."""
    st = app.state
    if getattr(st, "voice_store", None) is not None:
        return st.voice_store
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        await client.ping()
        st.voice_store = RedisStore(client)
    except Exception as exc:  # noqa: BLE001 - any connect failure means "not shared"
        if not settings.voice_allow_local_state:
            raise SharedStateUnavailableError("shared voice state (Redis) is unreachable") from exc
        logger.warning(
            "voice: using in-process state (VOICE_ALLOW_LOCAL_STATE); single worker only"
        )
        st.voice_store = MemoryStore()
    return st.voice_store
