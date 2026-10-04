"""Work hints: how the privileged system runtime tells ordinary workers where work is.

The system runtime is the only process that may look across tenants. It finds the
companies that have recoverable or runnable work and publishes their ids here. An
ordinary worker (which holds only the tenant-bound application role) claims a few ids
and does the work inside ``tenant_session``. A hint carries a company id and nothing
else: no task, goal or message content ever passes through it.

Hints live in a Redis set that expires on its own. They are an optimisation, never the
source of truth: if Redis is missing, or the system runtime is down, a lost hint only
delays recovery until the next publish, and a worker's own in-process wake hints keep
working. Without Redis ``claim`` returns nothing.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable

from nexus.runtime.redis_utils import get_redis

logger = logging.getLogger(__name__)

# The kinds the system runtime publishes. Anything else is refused, so a hint key can
# never be steered by a caller.
KINDS = frozenset({"goals", "chat_turns", "task_attempts"})
_TTL_SECONDS = 300


def _key(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown work hint kind: {kind!r}")
    return f"nexus:hints:{kind}"


async def publish(kind: str, company_ids: Iterable[uuid.UUID]) -> int:
    """Publish company ids that have work of ``kind``. Returns how many were stored."""
    key = _key(kind)
    ids = [str(c) for c in company_ids]
    redis = await get_redis()
    if redis is None or not ids:
        return 0
    try:
        await redis.sadd(key, *ids)
        await redis.expire(key, _TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - a hint is best effort
        logger.warning("Could not publish %s work hints: %s", kind, type(exc).__name__)
        return 0
    return len(ids)


async def claim(kind: str, limit: int = 20) -> list[uuid.UUID]:
    """Take up to ``limit`` company ids off the hint set. Each id goes to one claimer."""
    key = _key(kind)
    redis = await get_redis()
    if redis is None:
        return []
    try:
        raw = await redis.spop(key, limit)
    except Exception as exc:  # noqa: BLE001 - a hint is best effort
        logger.warning("Could not claim %s work hints: %s", kind, type(exc).__name__)
        return []
    out: list[uuid.UUID] = []
    for item in raw or []:
        try:
            out.append(uuid.UUID(str(item)))
        except ValueError:
            continue
    return out
