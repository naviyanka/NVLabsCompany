"""Rate Limiter - multi-level rate limiting with token bucket and sliding window.

Provides per-agent, per-company, and per-resource rate limiting using
a token bucket algorithm for O(1) checks and a sliding window counter
for hourly tracking.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenBucket:
    """Token bucket for rate limiting with O(1) check/consume operations.

    Attributes:
        capacity: Maximum number of tokens the bucket can hold.
        refill_rate: Tokens added per second.
        tokens: Current number of tokens available.
        last_refill: Timestamp of the last refill calculation.
        burst_allowance: Extra tokens allowed for bursts above capacity.
    """

    capacity: int = 60
    refill_rate: float = 1.0
    tokens: float = 60.0
    last_refill: float = field(default_factory=time.time)
    burst_allowance: int = 0

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since last refill.

        This is called lazily on each check/consume for O(1) performance.
        """
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(
            self.capacity + self.burst_allowance,
            self.tokens + elapsed * self.refill_rate,
        )
        self.last_refill = now

    def check(self, tokens: int = 1) -> bool:
        """Check if tokens are available without consuming them.

        O(1) operation.

        Args:
            tokens: Number of tokens to check for.

        Returns:
            True if sufficient tokens are available.
        """
        self._refill()
        return self.tokens >= tokens

    def consume(self, tokens: int = 1) -> bool:
        """Attempt to consume tokens from the bucket.

        O(1) operation. Only consumes if sufficient tokens are available.

        Args:
            tokens: Number of tokens to consume.

        Returns:
            True if tokens were consumed, False if insufficient.
        """
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def get_remaining(self) -> int:
        """Get the number of remaining tokens (rounded down).

        Returns:
            Number of available tokens.
        """
        self._refill()
        return int(self.tokens)

    def time_until_available(self, tokens: int = 1) -> float:
        """Calculate time until the requested tokens will be available.

        Args:
            tokens: Number of tokens needed.

        Returns:
            Seconds until tokens are available (0 if already available).
        """
        self._refill()
        if self.tokens >= tokens:
            return 0.0
        deficit = tokens - self.tokens
        if self.refill_rate <= 0:
            return float("inf")
        return deficit / self.refill_rate


@dataclass
class SlidingWindowCounter:
    """Sliding window counter for per-hour tracking.

    Uses a fixed-window approximation for efficiency while maintaining
    acceptable accuracy.

    Attributes:
        window_seconds: Size of the sliding window.
        max_requests: Maximum requests allowed in the window.
        current_count: Requests in the current window.
        previous_count: Requests in the previous window.
        window_start: Start of the current window.
    """

    window_seconds: int = 3600
    max_requests: int = 1000
    current_count: int = 0
    previous_count: int = 0
    window_start: float = field(default_factory=time.time)

    def _advance_window(self) -> None:
        """Advance the window if needed."""
        now = time.time()
        elapsed = now - self.window_start
        if elapsed >= self.window_seconds * 2:
            # More than 2 windows have passed, reset everything
            self.previous_count = 0
            self.current_count = 0
            self.window_start = now
        elif elapsed >= self.window_seconds:
            # One window has passed, rotate
            self.previous_count = self.current_count
            self.current_count = 0
            self.window_start = now

    def get_count(self) -> float:
        """Get the estimated count in the sliding window.

        Uses weighted average of current and previous window counts.

        Returns:
            Estimated request count in the current sliding window.
        """
        self._advance_window()
        now = time.time()
        elapsed_in_window = now - self.window_start
        if self.window_seconds <= 0:
            return float(self.current_count)
        weight = elapsed_in_window / self.window_seconds
        return self.previous_count * (1 - weight) + self.current_count

    def record(self) -> bool:
        """Record a request in the sliding window.

        Returns:
            True if the request was allowed, False if limit exceeded.
        """
        self._advance_window()
        if self.get_count() >= self.max_requests:
            return False
        self.current_count += 1
        return True

    def get_remaining(self) -> int:
        """Get remaining requests allowed in the window.

        Returns:
            Number of requests remaining.
        """
        count = self.get_count()
        remaining = self.max_requests - count
        return max(0, int(remaining))


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit.

    Attributes:
        requests_per_minute: Max requests per minute.
        requests_per_hour: Max requests per hour.
        burst_allowance: Extra burst tokens above capacity.
        soft_limit_ratio: Ratio of capacity at which soft limit kicks in.
        queue_at_soft_limit: Whether to queue instead of reject at soft limit.
    """

    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_allowance: int = 10
    soft_limit_ratio: float = 0.8
    queue_at_soft_limit: bool = True


@dataclass
class RateLimitResult:
    """Result of a rate limit check.

    Attributes:
        allowed: Whether the request is allowed.
        remaining: Remaining requests.
        limit: The configured limit.
        reset_seconds: Seconds until the limit resets.
        queued: Whether the request was queued (soft limit).
        retry_after: Seconds to wait before retrying (if rejected).
    """

    allowed: bool = True
    remaining: int = 0
    limit: int = 60
    reset_seconds: float = 0.0
    queued: bool = False
    retry_after: float = 0.0


class RateLimiter:
    """Multi-level rate limiter with token bucket and sliding window.

    Provides per-agent, per-company, and per-resource rate limiting.
    Uses token bucket for O(1) minute-level checks and sliding window
    for hourly tracking.
    """

    def __init__(self) -> None:
        """Initialize the rate limiter."""
        # agent_id -> TokenBucket (per-minute)
        self._agent_buckets: dict[str, TokenBucket] = {}
        # agent_id -> SlidingWindowCounter (per-hour)
        self._agent_windows: dict[str, SlidingWindowCounter] = {}
        # company_id -> TokenBucket
        self._company_buckets: dict[str, TokenBucket] = {}
        # company_id -> SlidingWindowCounter
        self._company_windows: dict[str, SlidingWindowCounter] = {}
        # resource_key -> TokenBucket
        self._resource_buckets: dict[str, TokenBucket] = {}
        # resource_key -> SlidingWindowCounter
        self._resource_windows: dict[str, SlidingWindowCounter] = {}
        # Configurations
        self._agent_configs: dict[str, RateLimitConfig] = {}
        self._company_configs: dict[str, RateLimitConfig] = {}
        self._resource_configs: dict[str, RateLimitConfig] = {}
        # Default configuration
        self._default_config = RateLimitConfig()
        # Queue for soft-limited requests
        self._queued_requests: list[dict[str, Any]] = []

    def configure_agent_limit(
        self,
        agent_id: str,
        config: RateLimitConfig,
    ) -> None:
        """Configure rate limits for a specific agent.

        Args:
            agent_id: The agent to configure.
            config: Rate limit configuration.
        """
        self._agent_configs[agent_id] = config
        # Create/update bucket - start full including burst allowance
        self._agent_buckets[agent_id] = TokenBucket(
            capacity=config.requests_per_minute,
            refill_rate=config.requests_per_minute / 60.0,
            tokens=float(config.requests_per_minute + config.burst_allowance),
            burst_allowance=config.burst_allowance,
        )
        self._agent_windows[agent_id] = SlidingWindowCounter(
            window_seconds=3600,
            max_requests=config.requests_per_hour,
        )

    def configure_company_limit(
        self,
        company_id: str,
        config: RateLimitConfig,
    ) -> None:
        """Configure rate limits for a company.

        Args:
            company_id: The company to configure.
            config: Rate limit configuration.
        """
        self._company_configs[company_id] = config
        self._company_buckets[company_id] = TokenBucket(
            capacity=config.requests_per_minute,
            refill_rate=config.requests_per_minute / 60.0,
            tokens=float(config.requests_per_minute + config.burst_allowance),
            burst_allowance=config.burst_allowance,
        )
        self._company_windows[company_id] = SlidingWindowCounter(
            window_seconds=3600,
            max_requests=config.requests_per_hour,
        )

    def configure_resource_limit(
        self,
        resource_key: str,
        config: RateLimitConfig,
    ) -> None:
        """Configure rate limits for a specific resource.

        Args:
            resource_key: Resource identifier (e.g., "deploy", "api_call").
            config: Rate limit configuration.
        """
        self._resource_configs[resource_key] = config
        self._resource_buckets[resource_key] = TokenBucket(
            capacity=config.requests_per_minute,
            refill_rate=config.requests_per_minute / 60.0,
            tokens=float(config.requests_per_minute + config.burst_allowance),
            burst_allowance=config.burst_allowance,
        )
        self._resource_windows[resource_key] = SlidingWindowCounter(
            window_seconds=3600,
            max_requests=config.requests_per_hour,
        )

    def check_rate_limit(
        self,
        agent_id: str | None = None,
        company_id: str | None = None,
        resource_key: str | None = None,
    ) -> RateLimitResult:
        """Check if a request is within rate limits (O(1) operation).

        Checks all applicable limits (agent, company, resource).
        Returns the most restrictive result.

        Args:
            agent_id: The agent making the request.
            company_id: The company context.
            resource_key: The resource being accessed.

        Returns:
            RateLimitResult indicating whether the request is allowed.
        """
        results: list[RateLimitResult] = []

        if agent_id:
            results.append(self._check_agent_limit(agent_id))
        if company_id:
            results.append(self._check_company_limit(company_id))
        if resource_key:
            results.append(self._check_resource_limit(resource_key))

        if not results:
            return RateLimitResult(allowed=True, remaining=999, limit=999)

        # Return the most restrictive result
        denied = [r for r in results if not r.allowed]
        if denied:
            return denied[0]

        # All allowed - return the one with lowest remaining
        return min(results, key=lambda r: r.remaining)

    def consume(
        self,
        agent_id: str | None = None,
        company_id: str | None = None,
        resource_key: str | None = None,
    ) -> RateLimitResult:
        """Consume a token from all applicable rate limiters.

        Actually deducts the token, unlike check_rate_limit which only peeks.

        Args:
            agent_id: The agent making the request.
            company_id: The company context.
            resource_key: The resource being accessed.

        Returns:
            RateLimitResult indicating whether the request was allowed.
        """
        # First check if allowed
        result = self.check_rate_limit(agent_id, company_id, resource_key)

        if not result.allowed:
            # Check if we should queue (soft limit)
            config = self._get_config(agent_id, company_id, resource_key)
            if config and config.queue_at_soft_limit:
                result.queued = True
                self._queued_requests.append({
                    "agent_id": agent_id,
                    "company_id": company_id,
                    "resource_key": resource_key,
                    "queued_at": time.time(),
                })
            return result

        # Consume from all applicable buckets
        if agent_id:
            bucket = self._get_or_create_agent_bucket(agent_id)
            bucket.consume()
            window = self._get_or_create_agent_window(agent_id)
            window.record()

        if company_id:
            bucket = self._get_or_create_company_bucket(company_id)
            bucket.consume()
            window = self._get_or_create_company_window(company_id)
            window.record()

        if resource_key:
            bucket = self._get_or_create_resource_bucket(resource_key)
            bucket.consume()
            window = self._get_or_create_resource_window(resource_key)
            window.record()

        return result

    def get_remaining(
        self,
        agent_id: str | None = None,
        company_id: str | None = None,
        resource_key: str | None = None,
    ) -> int:
        """Get the minimum remaining requests across all applicable limits.

        Args:
            agent_id: The agent to check.
            company_id: The company to check.
            resource_key: The resource to check.

        Returns:
            Minimum remaining tokens across all applicable limits.
        """
        remaining_values: list[int] = []

        if agent_id:
            bucket = self._agent_buckets.get(agent_id)
            if bucket:
                remaining_values.append(bucket.get_remaining())

        if company_id:
            bucket = self._company_buckets.get(company_id)
            if bucket:
                remaining_values.append(bucket.get_remaining())

        if resource_key:
            bucket = self._resource_buckets.get(resource_key)
            if bucket:
                remaining_values.append(bucket.get_remaining())

        if not remaining_values:
            return self._default_config.requests_per_minute

        return min(remaining_values)

    def get_headers(
        self,
        agent_id: str | None = None,
        company_id: str | None = None,
        resource_key: str | None = None,
    ) -> dict[str, str]:
        """Get rate limit headers for HTTP responses.

        Returns standard rate limit headers per RFC 6585.

        Args:
            agent_id: The agent context.
            company_id: The company context.
            resource_key: The resource context.

        Returns:
            Dictionary of rate limit headers.
        """
        config = self._get_config(agent_id, company_id, resource_key)
        if config is None:
            config = self._default_config

        remaining = self.get_remaining(agent_id, company_id, resource_key)
        limit = config.requests_per_minute

        # Calculate reset time
        reset_seconds = 60.0  # Default to 1 minute
        if agent_id:
            bucket = self._agent_buckets.get(agent_id)
            if bucket:
                reset_seconds = bucket.time_until_available()

        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(time.time() + reset_seconds)),
        }

        if remaining <= 0:
            headers["Retry-After"] = str(int(reset_seconds) + 1)

        return headers

    def get_queued_requests(self) -> list[dict[str, Any]]:
        """Get the list of queued requests (soft-limited).

        Returns:
            List of queued request details.
        """
        return list(self._queued_requests)

    def clear_queue(self) -> int:
        """Clear the request queue.

        Returns:
            Number of queued requests cleared.
        """
        count = len(self._queued_requests)
        self._queued_requests = []
        return count

    def _check_agent_limit(self, agent_id: str) -> RateLimitResult:
        """Check rate limit for a specific agent."""
        bucket = self._get_or_create_agent_bucket(agent_id)
        config = self._agent_configs.get(agent_id, self._default_config)

        if not bucket.check():
            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=config.requests_per_minute,
                reset_seconds=bucket.time_until_available(),
                retry_after=bucket.time_until_available(),
            )

        return RateLimitResult(
            allowed=True,
            remaining=bucket.get_remaining(),
            limit=config.requests_per_minute,
            reset_seconds=bucket.time_until_available(),
        )

    def _check_company_limit(self, company_id: str) -> RateLimitResult:
        """Check rate limit for a specific company."""
        bucket = self._get_or_create_company_bucket(company_id)
        config = self._company_configs.get(company_id, self._default_config)

        if not bucket.check():
            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=config.requests_per_minute,
                reset_seconds=bucket.time_until_available(),
                retry_after=bucket.time_until_available(),
            )

        return RateLimitResult(
            allowed=True,
            remaining=bucket.get_remaining(),
            limit=config.requests_per_minute,
            reset_seconds=bucket.time_until_available(),
        )

    def _check_resource_limit(self, resource_key: str) -> RateLimitResult:
        """Check rate limit for a specific resource."""
        bucket = self._get_or_create_resource_bucket(resource_key)
        config = self._resource_configs.get(resource_key, self._default_config)

        if not bucket.check():
            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=config.requests_per_minute,
                reset_seconds=bucket.time_until_available(),
                retry_after=bucket.time_until_available(),
            )

        return RateLimitResult(
            allowed=True,
            remaining=bucket.get_remaining(),
            limit=config.requests_per_minute,
            reset_seconds=bucket.time_until_available(),
        )

    def _get_or_create_agent_bucket(self, agent_id: str) -> TokenBucket:
        """Get or create a token bucket for an agent."""
        if agent_id not in self._agent_buckets:
            config = self._agent_configs.get(agent_id, self._default_config)
            self._agent_buckets[agent_id] = TokenBucket(
                capacity=config.requests_per_minute,
                refill_rate=config.requests_per_minute / 60.0,
                tokens=float(config.requests_per_minute + config.burst_allowance),
                burst_allowance=config.burst_allowance,
            )
        return self._agent_buckets[agent_id]

    def _get_or_create_agent_window(self, agent_id: str) -> SlidingWindowCounter:
        """Get or create a sliding window for an agent."""
        if agent_id not in self._agent_windows:
            config = self._agent_configs.get(agent_id, self._default_config)
            self._agent_windows[agent_id] = SlidingWindowCounter(
                window_seconds=3600,
                max_requests=config.requests_per_hour,
            )
        return self._agent_windows[agent_id]

    def _get_or_create_company_bucket(self, company_id: str) -> TokenBucket:
        """Get or create a token bucket for a company."""
        if company_id not in self._company_buckets:
            config = self._company_configs.get(company_id, self._default_config)
            self._company_buckets[company_id] = TokenBucket(
                capacity=config.requests_per_minute,
                refill_rate=config.requests_per_minute / 60.0,
                tokens=float(config.requests_per_minute + config.burst_allowance),
                burst_allowance=config.burst_allowance,
            )
        return self._company_buckets[company_id]

    def _get_or_create_company_window(self, company_id: str) -> SlidingWindowCounter:
        """Get or create a sliding window for a company."""
        if company_id not in self._company_windows:
            config = self._company_configs.get(company_id, self._default_config)
            self._company_windows[company_id] = SlidingWindowCounter(
                window_seconds=3600,
                max_requests=config.requests_per_hour,
            )
        return self._company_windows[company_id]

    def _get_or_create_resource_bucket(self, resource_key: str) -> TokenBucket:
        """Get or create a token bucket for a resource."""
        if resource_key not in self._resource_buckets:
            config = self._resource_configs.get(resource_key, self._default_config)
            self._resource_buckets[resource_key] = TokenBucket(
                capacity=config.requests_per_minute,
                refill_rate=config.requests_per_minute / 60.0,
                tokens=float(config.requests_per_minute + config.burst_allowance),
                burst_allowance=config.burst_allowance,
            )
        return self._resource_buckets[resource_key]

    def _get_or_create_resource_window(self, resource_key: str) -> SlidingWindowCounter:
        """Get or create a sliding window for a resource."""
        if resource_key not in self._resource_windows:
            config = self._resource_configs.get(resource_key, self._default_config)
            self._resource_windows[resource_key] = SlidingWindowCounter(
                window_seconds=3600,
                max_requests=config.requests_per_hour,
            )
        return self._resource_windows[resource_key]

    def _get_config(
        self,
        agent_id: str | None,
        company_id: str | None,
        resource_key: str | None,
    ) -> RateLimitConfig | None:
        """Get the most specific config available."""
        if resource_key and resource_key in self._resource_configs:
            return self._resource_configs[resource_key]
        if agent_id and agent_id in self._agent_configs:
            return self._agent_configs[agent_id]
        if company_id and company_id in self._company_configs:
            return self._company_configs[company_id]
        return self._default_config
