"""Redis utilities — optional Redis backing for rate limiter, budget, and leader election.

All functions gracefully fall back to in-memory implementations when Redis
is not configured (REDIS_URL env var not set) or unavailable.

Environment:
    REDIS_URL: Redis connection URL (e.g., redis://localhost:6379/0)
               If not set, all Redis operations return None and callers
               use their in-memory fallbacks.
"""

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

_redis_client: Any = None
_redis_available: bool | None = None  # None = not yet checked


def get_redis_url() -> str | None:
    """Get Redis URL from environment, or None if not configured."""
    return os.environ.get("REDIS_URL")


# Prefix for every key holding one tenant's data (Phase 5.2.3). One database is
# shared by all tenants, so the prefix is the only thing separating them.
TENANT_PREFIX = "tenant"


def tenant_key(company_id: Any, *parts: Any) -> str:
    """Build a Redis key namespaced to one company.

    ``tenant_key(company_id, "ratelimit", "minute")`` gives
    ``tenant:<company_id>:ratelimit:minute``.

    Putting the company first rather than last is what makes the namespace
    usable: ``SCAN tenant:<id>:*`` finds everything one tenant owns, which is
    what deleting a company or debugging one tenant's limiter needs. With the
    company buried mid-key, neither is possible without walking every key in the
    database.

    Args:
        company_id: The tenant. Stringified, so a UUID or a str both work.
        *parts: Further key segments, joined with ``:``.

    Returns:
        The full key.

    Raises:
        ValueError: If ``company_id`` is falsy. A key reading ``tenant:None:``
            would be one shared bucket every tenant writes into, which is the
            exact failure the prefix exists to prevent -- and it would look like
            a working cache.
    """
    if not company_id:
        raise ValueError("tenant_key() needs a company_id; refusing to build a shared key")
    return ":".join([TENANT_PREFIX, str(company_id), *(str(p) for p in parts)])


async def get_redis() -> Any:
    """Get the Redis async client, or None if Redis is not available.

    Caches the connection and availability check. Thread-safe for asyncio.
    """
    global _redis_client, _redis_available

    if _redis_available is False:
        return None

    if _redis_client is not None:
        return _redis_client

    url = get_redis_url()
    if not url:
        _redis_available = False
        return None

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(url, decode_responses=True)
        # Test connection
        await _redis_client.ping()
        _redis_available = True
        logger.info("Redis connected: %s", url.split("@")[-1] if "@" in url else url)
        return _redis_client
    except ImportError:
        logger.info("redis package not installed — using in-memory fallbacks")
        _redis_available = False
        return None
    except Exception as e:
        logger.warning("Redis connection failed (%s) — using in-memory fallbacks", e)
        _redis_available = False
        return None


async def try_acquire_leader(
    service_name: str, instance_id: str, ttl_seconds: int = 120
) -> bool:
    """Try to acquire leadership for a background service using Redis SET NX.

    If Redis is not available, always returns True (single-instance mode).

    Args:
        service_name: Name of the service (e.g., "scheduler", "orchestrator")
        instance_id: Unique identifier for this instance
        ttl_seconds: How long the lock lasts before expiring

    Returns:
        True if this instance is the leader, False if another instance holds the lock.
    """
    r = await get_redis()
    if r is None:
        return True  # No Redis = single instance = always leader

    key = f"nexus:leader:{service_name}"
    try:
        # SET NX with TTL — only succeeds if key doesn't exist
        acquired = await r.set(key, instance_id, nx=True, ex=ttl_seconds)
        if acquired:
            return True

        # Check if we already hold it (re-entrant)
        current_holder = await r.get(key)
        if current_holder == instance_id:
            # Refresh TTL
            await r.expire(key, ttl_seconds)
            return True

        return False
    except Exception as e:
        logger.warning("Leader election error for %s: %s — assuming leader", service_name, e)
        return True  # On error, assume leader (fail-open)


async def release_leader(service_name: str, instance_id: str) -> None:
    """Release leadership lock. Only releases if we hold it."""
    r = await get_redis()
    if r is None:
        return

    key = f"nexus:leader:{service_name}"
    try:
        current = await r.get(key)
        if current == instance_id:
            await r.delete(key)
    except Exception:
        pass
