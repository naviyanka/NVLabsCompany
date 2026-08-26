"""Redis lease-based leader election for singleton background services.

Multi-process deployments must not run the watchdog, scheduler, or orchestrator
in every replica. A leader lease (SET NX + TTL) ensures one active worker per
service name; if the leader dies, the lease expires and another replica takes
over on its next tick.

Without Redis configured/reachable, :class:`NoopLeaderElection` reports
leadership for everyone — identical to today's single-process behavior.
"""

import logging
import uuid

logger = logging.getLogger(__name__)

DEFAULT_LEASE_TTL_SECONDS = 30
_KEY_PREFIX = "nexus:leader"


class LeaderElection:
    """Redis-backed leader lease."""

    def __init__(self, redis_url: str, instance_id: str | None = None) -> None:
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        self.instance_id = instance_id or uuid.uuid4().hex[:12]

    async def try_acquire(self, name: str, ttl: int = DEFAULT_LEASE_TTL_SECONDS) -> bool:
        """Acquire or renew the lease for `name`. True when this instance leads."""
        key = f"{_KEY_PREFIX}:{name}"
        current = await self._redis.get(key)
        if current == self.instance_id:
            # Renew our own lease.
            await self._redis.expire(key, ttl)
            return True
        acquired = await self._redis.set(key, self.instance_id, nx=True, ex=ttl)
        return bool(acquired)

    async def release(self, name: str) -> None:
        """Release the lease (only if we still hold it)."""
        key = f"{_KEY_PREFIX}:{name}"
        current = await self._redis.get(key)
        if current == self.instance_id:
            await self._redis.delete(key)


class NoopLeaderElection:
    """Always-leader fallback used when Redis is not configured or reachable."""

    def __init__(self) -> None:
        self.instance_id = "solo"

    async def try_acquire(self, name: str, ttl: int = DEFAULT_LEASE_TTL_SECONDS) -> bool:
        return True

    async def release(self, name: str) -> None:
        return None


_election = None
_initialized = False


def get_leader_election() -> LeaderElection | NoopLeaderElection:
    """Process-wide election client; Redis when usable, no-op otherwise."""
    global _election, _initialized
    if _initialized:
        return _election
    _initialized = True
    try:
        from nexus.config import settings

        if settings.redis_url:
            _election = LeaderElection(settings.redis_url)
    except Exception as exc:
        logger.info("Leader election falling back to solo mode: %s", exc)
        _election = NoopLeaderElection()
    if _election is None:
        _election = NoopLeaderElection()
    return _election


async def is_leader(name: str) -> bool:
    """Convenience check used at the top of background service loops."""
    election = get_leader_election()
    try:
        return await election.try_acquire(name)
    except Exception as exc:
        logger.warning("Leader election error for '%s' (%s); assuming leader", name, exc)
        return True
