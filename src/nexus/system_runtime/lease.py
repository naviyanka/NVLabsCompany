"""Per-operation leases for the system runtime: fail closed and fenced by a token.

``redis_utils.try_acquire_leader`` is built for ordinary services and fails open: with no
Redis, or on a Redis error, it reports "you are the leader". The system runtime holds the
cross-tenant credential, so it must not inherit that. Here an unreachable lease store raises
:class:`LeaseUnavailable`, the operation does not run, and the runtime reports a stable code.

Every acquisition carries a fresh random token. Releasing deletes the key only if it still
holds that token (one atomic script), and :func:`held` lets the caller check, before it
records a success, that its lease was not lost and taken by another runtime meanwhile. A
lease that is never released (a crash) expires on its own after its TTL.
"""

from __future__ import annotations

import asyncio
import logging

from nexus.runtime import redis_utils

logger = logging.getLogger(__name__)

KEY_PREFIX = "nexus:system_runtime:lease:"
CALL_TIMEOUT_SECONDS = 2.0
RELEASE_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
    "else return 0 end"
)


class LeaseUnavailable(Exception):  # noqa: N818 - a state, not an error class
    """The lease store cannot be reached, so no lease can be granted or confirmed."""

    code = "LEASE_STORE_UNAVAILABLE"


async def _client():
    redis = await redis_utils.get_redis()
    if redis is None:
        if redis_utils.get_redis_url():
            redis_utils.forget_failed_connection()  # try again on the next call
        raise LeaseUnavailable
    return redis


async def acquire(name: str, token: str, ttl_seconds: int) -> bool:
    """True if ``token`` now holds ``name``; False if another holder has it."""
    try:
        redis = await asyncio.wait_for(_client(), CALL_TIMEOUT_SECONDS)
        granted = await asyncio.wait_for(
            redis.set(KEY_PREFIX + name, token, nx=True, ex=ttl_seconds), CALL_TIMEOUT_SECONDS
        )
    except LeaseUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - any store failure means no lease
        raise LeaseUnavailable from exc
    return bool(granted)


async def held(name: str, token: str) -> bool:
    """True while ``token`` still holds ``name``."""
    try:
        redis = await asyncio.wait_for(_client(), CALL_TIMEOUT_SECONDS)
        current = await asyncio.wait_for(redis.get(KEY_PREFIX + name), CALL_TIMEOUT_SECONDS)
    except LeaseUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LeaseUnavailable from exc
    return current == token


async def release(name: str, token: str) -> None:
    """Free ``name`` if ``token`` still holds it. Never raises: the TTL is the backstop."""
    try:
        redis = await asyncio.wait_for(_client(), CALL_TIMEOUT_SECONDS)
        await asyncio.wait_for(
            redis.eval(RELEASE_SCRIPT, 1, KEY_PREFIX + name, token), CALL_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("system runtime: lease release failed (%s)", type(exc).__name__)
