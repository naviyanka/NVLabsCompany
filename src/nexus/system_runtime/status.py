"""Credential-free status of the system runtime.

The runtime publishes a small status record to Redis with a short expiry. The public API
and the ``status`` command read it; neither opens a database connection with the system
credential. A missing or expired record reads as unavailable, with a stable reason.
"""

from __future__ import annotations

import json
import time

from nexus.runtime.redis_utils import get_redis

STATUS_KEY = "nexus:system_runtime:status"
STATUS_TTL_SECONDS = 180


async def publish(
    *, ops_enabled: list[str], role_validation: str, last_success: dict[str, float]
) -> None:
    """Write the current status. Best effort: a Redis outage must not stop the runtime."""
    redis = await get_redis()
    if redis is None:
        return
    record = {
        "process_type": "system-runtime",
        "ops_enabled": sorted(ops_enabled),
        "role_validation": role_validation,
        "last_success": last_success,
        "published_at": time.time(),
    }
    try:
        await redis.set(STATUS_KEY, json.dumps(record), ex=STATUS_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        return


async def read() -> dict:
    """The published status, or ``{"available": False, "reason": <stable code>}``."""
    redis = await get_redis()
    if redis is None:
        return {"available": False, "reason": "STATUS_STORE_UNAVAILABLE"}
    try:
        raw = await redis.get(STATUS_KEY)
    except Exception:  # noqa: BLE001
        return {"available": False, "reason": "STATUS_STORE_UNAVAILABLE"}
    if not raw:
        return {"available": False, "reason": "SYSTEM_RUNTIME_NOT_REPORTING"}
    record = json.loads(raw)
    record["available"] = record.get("role_validation") == "ok"
    if not record["available"]:
        record["reason"] = "ROLE_VALIDATION_FAILED"
    return record
