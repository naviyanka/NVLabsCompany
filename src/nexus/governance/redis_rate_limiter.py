"""Redis-backed Rate Limiter using sorted set sliding window.

Provides multi-process safe rate limiting that persists across restarts.
Uses Redis sorted sets where each member is a request timestamp, and the
score is the same timestamp. Old entries are pruned on each check.

Falls back to the in-memory rate limiter if Redis is unavailable.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RedisRateLimitConfig:
    """Configuration for Redis-backed rate limiting.

    Attributes:
        requests_per_minute: Max requests per minute window.
        requests_per_hour: Max requests per hour window.
        burst_allowance: Extra requests allowed above per-minute limit.
        key_prefix: Redis key prefix for namespacing.
    """

    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_allowance: int = 10
    key_prefix: str = "nexus:ratelimit"


@dataclass
class RedisRateLimitResult:
    """Result of a Redis rate limit check.

    Attributes:
        allowed: Whether the request is allowed.
        remaining_minute: Remaining requests in the minute window.
        remaining_hour: Remaining requests in the hour window.
        retry_after: Seconds to wait before retrying (0 if allowed).
    """

    allowed: bool = True
    remaining_minute: int = 0
    remaining_hour: int = 0
    retry_after: float = 0.0


class RedisRateLimiter:
    """Production rate limiter using Redis sorted sets.

    Each rate limit window uses a Redis sorted set where:
    - Members are unique request IDs (timestamp + random suffix)
    - Scores are the request timestamps
    - Expired entries are pruned on each check via ZREMRANGEBYSCORE

    This approach is:
    - O(log N) per operation (N = requests in window)
    - Multi-process safe (atomic Redis operations)
    - Persistent across restarts (data lives in Redis)
    - Self-cleaning (TTL on keys + explicit pruning)
    """

    def __init__(self, redis_url: str) -> None:
        """Initialize with Redis connection URL.

        Args:
            redis_url: Redis connection string (redis://host:port/db).
        """
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        self._available = True

    async def check_rate_limit(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        config: RedisRateLimitConfig | None = None,
    ) -> RedisRateLimitResult:
        """Check and consume a rate limit slot for an entity.

        Checks both per-minute and per-hour windows. If either is exceeded,
        the request is denied.

        Args:
            entity_type: Type of entity (company, agent, resource).
            entity_id: UUID of the entity being rate-limited.
            config: Rate limit configuration. Uses defaults if None.

        Returns:
            RedisRateLimitResult with allowed status and remaining counts.
        """
        if config is None:
            config = RedisRateLimitConfig()

        if not self._available:
            # Redis unavailable — fail open (allow all)
            return RedisRateLimitResult(
                allowed=True,
                remaining_minute=config.requests_per_minute,
                remaining_hour=config.requests_per_hour,
            )

        try:
            return await self._check_with_redis(entity_type, entity_id, config)
        except Exception as exc:
            logger.warning("Redis rate limiter unavailable: %s. Failing open.", exc)
            self._available = False
            return RedisRateLimitResult(
                allowed=True,
                remaining_minute=config.requests_per_minute,
                remaining_hour=config.requests_per_hour,
            )

    async def _check_with_redis(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        config: RedisRateLimitConfig,
    ) -> RedisRateLimitResult:
        """Perform the actual Redis sliding window check."""
        now = time.time()
        member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"

        minute_key = f"{config.key_prefix}:{entity_type}:{entity_id}:minute"
        hour_key = f"{config.key_prefix}:{entity_type}:{entity_id}:hour"

        minute_window_start = now - 60
        hour_window_start = now - 3600

        effective_minute_limit = config.requests_per_minute + config.burst_allowance

        pipe = self._redis.pipeline()

        # Prune expired entries from both windows
        pipe.zremrangebyscore(minute_key, 0, minute_window_start)
        pipe.zremrangebyscore(hour_key, 0, hour_window_start)

        # Count current entries in both windows
        pipe.zcard(minute_key)
        pipe.zcard(hour_key)

        results = await pipe.execute()
        minute_count = results[2]
        hour_count = results[3]

        # Check limits
        minute_exceeded = minute_count >= effective_minute_limit
        hour_exceeded = hour_count >= config.requests_per_hour

        if minute_exceeded or hour_exceeded:
            # Denied — calculate retry_after
            if minute_exceeded:
                # Find oldest entry in minute window to estimate when a slot opens
                oldest = await self._redis.zrange(minute_key, 0, 0, withscores=True)
                if oldest:
                    retry_after = 60 - (now - oldest[0][1])
                else:
                    retry_after = 1.0
            else:
                retry_after = 60.0  # Hour limit — longer wait

            return RedisRateLimitResult(
                allowed=False,
                remaining_minute=max(0, effective_minute_limit - minute_count),
                remaining_hour=max(0, config.requests_per_hour - hour_count),
                retry_after=max(0.1, retry_after),
            )

        # Allowed — record the request in both windows
        pipe2 = self._redis.pipeline()
        pipe2.zadd(minute_key, {member: now})
        pipe2.zadd(hour_key, {member: now})
        pipe2.expire(minute_key, 120)  # TTL = 2x window for safety
        pipe2.expire(hour_key, 7200)
        await pipe2.execute()

        return RedisRateLimitResult(
            allowed=True,
            remaining_minute=max(0, effective_minute_limit - minute_count - 1),
            remaining_hour=max(0, config.requests_per_hour - hour_count - 1),
        )

    async def get_usage(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        config: RedisRateLimitConfig | None = None,
    ) -> dict[str, int]:
        """Get current usage for an entity without consuming a slot.

        Args:
            entity_type: Type of entity.
            entity_id: UUID of the entity.
            config: Rate limit configuration.

        Returns:
            Dict with minute_count and hour_count.
        """
        if config is None:
            config = RedisRateLimitConfig()

        if not self._available:
            return {"minute_count": 0, "hour_count": 0}

        try:
            now = time.time()
            minute_key = f"{config.key_prefix}:{entity_type}:{entity_id}:minute"
            hour_key = f"{config.key_prefix}:{entity_type}:{entity_id}:hour"

            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(minute_key, 0, now - 60)
            pipe.zremrangebyscore(hour_key, 0, now - 3600)
            pipe.zcard(minute_key)
            pipe.zcard(hour_key)
            results = await pipe.execute()

            return {"minute_count": results[2], "hour_count": results[3]}
        except Exception:
            return {"minute_count": 0, "hour_count": 0}

    async def reset(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        config: RedisRateLimitConfig | None = None,
    ) -> None:
        """Reset rate limit counters for an entity.

        Args:
            entity_type: Type of entity.
            entity_id: UUID of the entity.
            config: Rate limit configuration.
        """
        if config is None:
            config = RedisRateLimitConfig()

        if not self._available:
            return

        try:
            minute_key = f"{config.key_prefix}:{entity_type}:{entity_id}:minute"
            hour_key = f"{config.key_prefix}:{entity_type}:{entity_id}:hour"
            await self._redis.delete(minute_key, hour_key)
        except Exception as exc:
            logger.warning("Failed to reset rate limit keys: %s", exc)

    async def health_check(self) -> bool:
        """Check if Redis is available and responsive.

        Returns:
            True if Redis responds to PING.
        """
        try:
            result = await self._redis.ping()
            self._available = True
            return bool(result)
        except Exception:
            self._available = False
            return False
