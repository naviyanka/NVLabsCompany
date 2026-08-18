"""Tests for Rate Limiter - token bucket, sliding window, and burst handling.

Tests O(1) token bucket operations, per-agent/company/resource limits,
sliding window tracking, burst allowance, and graceful degradation.
"""

import sys
import time
from pathlib import Path

# Add src to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nexus.governance.rate_limiter import (
    TokenBucket,
    SlidingWindowCounter,
    RateLimiter,
    RateLimitConfig,
    RateLimitResult,
)


class TestTokenBucket:
    """Tests for the TokenBucket algorithm."""

    def test_initial_tokens_equal_capacity(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0, tokens=10.0)
        assert bucket.get_remaining() == 10

    def test_consume_reduces_tokens(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0, tokens=10.0)
        result = bucket.consume(1)
        assert result is True
        assert bucket.get_remaining() == 9

    def test_consume_fails_when_empty(self):
        bucket = TokenBucket(capacity=2, refill_rate=0.0, tokens=2.0)
        assert bucket.consume(1) is True
        assert bucket.consume(1) is True
        assert bucket.consume(1) is False

    def test_check_does_not_consume(self):
        bucket = TokenBucket(capacity=5, refill_rate=0.0, tokens=5.0)
        assert bucket.check(3) is True
        assert bucket.get_remaining() == 5  # Not consumed

    def test_refill_adds_tokens_over_time(self):
        bucket = TokenBucket(capacity=10, refill_rate=100.0, tokens=0.0)
        bucket.last_refill = time.time() - 0.1  # 0.1 seconds ago
        # Should have refilled ~10 tokens (100 per second * 0.1 seconds)
        remaining = bucket.get_remaining()
        assert remaining >= 9  # Allow slight timing variance

    def test_tokens_do_not_exceed_capacity(self):
        bucket = TokenBucket(capacity=10, refill_rate=1000.0, tokens=10.0)
        bucket.last_refill = time.time() - 10  # 10 seconds ago
        assert bucket.get_remaining() == 10  # Capped at capacity

    def test_burst_allowance_exceeds_capacity(self):
        bucket = TokenBucket(
            capacity=10, refill_rate=1000.0, tokens=15.0, burst_allowance=5
        )
        # With burst_allowance=5, max is 15
        assert bucket.get_remaining() == 15

    def test_time_until_available(self):
        bucket = TokenBucket(capacity=10, refill_rate=2.0, tokens=0.0)
        # Need 1 token, refill rate is 2/sec, so ~0.5 seconds
        wait = bucket.time_until_available(1)
        assert 0.0 < wait <= 1.0

    def test_time_until_available_zero_when_sufficient(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0, tokens=10.0)
        assert bucket.time_until_available(1) == 0.0


class TestSlidingWindowCounter:
    """Tests for the SlidingWindowCounter."""

    def test_record_within_limit(self):
        window = SlidingWindowCounter(window_seconds=60, max_requests=10)
        for _ in range(10):
            assert window.record() is True

    def test_record_exceeds_limit(self):
        window = SlidingWindowCounter(window_seconds=60, max_requests=5)
        for _ in range(5):
            window.record()
        assert window.record() is False

    def test_get_remaining_decreases(self):
        window = SlidingWindowCounter(window_seconds=60, max_requests=10)
        assert window.get_remaining() == 10
        window.record()
        assert window.get_remaining() == 9

    def test_window_advances_after_time(self):
        window = SlidingWindowCounter(window_seconds=1, max_requests=5)
        # Fill it up
        for _ in range(5):
            window.record()
        # Simulate time passing (more than 2 windows)
        window.window_start = time.time() - 3
        # Window should have advanced, counts reset
        assert window.record() is True


class TestRateLimiter:
    """Tests for the multi-level RateLimiter."""

    def test_default_allows_requests(self):
        limiter = RateLimiter()
        result = limiter.check_rate_limit(agent_id="agent-1")
        assert result.allowed is True

    def test_configure_and_consume_agent_limit(self):
        limiter = RateLimiter()
        config = RateLimitConfig(
            requests_per_minute=5,
            requests_per_hour=100,
            burst_allowance=0,
        )
        limiter.configure_agent_limit("agent-1", config)

        # Consume 5 tokens
        for _ in range(5):
            result = limiter.consume(agent_id="agent-1")
            assert result.allowed is True

        # 6th should be denied
        result = limiter.consume(agent_id="agent-1")
        assert result.allowed is False

    def test_per_company_limit(self):
        limiter = RateLimiter()
        config = RateLimitConfig(
            requests_per_minute=3,
            requests_per_hour=100,
            burst_allowance=0,
        )
        limiter.configure_company_limit("company-1", config)

        for _ in range(3):
            result = limiter.consume(company_id="company-1")
            assert result.allowed is True

        result = limiter.consume(company_id="company-1")
        assert result.allowed is False

    def test_per_resource_limit(self):
        limiter = RateLimiter()
        config = RateLimitConfig(
            requests_per_minute=2,
            requests_per_hour=100,
            burst_allowance=0,
        )
        limiter.configure_resource_limit("deploy", config)

        result = limiter.consume(resource_key="deploy")
        assert result.allowed is True
        result = limiter.consume(resource_key="deploy")
        assert result.allowed is True
        result = limiter.consume(resource_key="deploy")
        assert result.allowed is False

    def test_get_remaining(self):
        limiter = RateLimiter()
        config = RateLimitConfig(
            requests_per_minute=10,
            requests_per_hour=100,
            burst_allowance=0,
        )
        limiter.configure_agent_limit("agent-1", config)

        assert limiter.get_remaining(agent_id="agent-1") == 10
        limiter.consume(agent_id="agent-1")
        assert limiter.get_remaining(agent_id="agent-1") == 9

    def test_get_headers(self):
        limiter = RateLimiter()
        config = RateLimitConfig(requests_per_minute=60, requests_per_hour=1000)
        limiter.configure_agent_limit("agent-1", config)

        headers = limiter.get_headers(agent_id="agent-1")
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers
        assert headers["X-RateLimit-Limit"] == "60"

    def test_burst_allowance(self):
        limiter = RateLimiter()
        config = RateLimitConfig(
            requests_per_minute=5,
            requests_per_hour=100,
            burst_allowance=3,
        )
        limiter.configure_agent_limit("agent-burst", config)

        # Should allow capacity + burst = 8 requests
        for i in range(8):
            result = limiter.consume(agent_id="agent-burst")
            assert result.allowed is True, f"Failed at request {i+1}"

        # 9th should be denied
        result = limiter.consume(agent_id="agent-burst")
        assert result.allowed is False

    def test_graceful_degradation_queues(self):
        limiter = RateLimiter()
        config = RateLimitConfig(
            requests_per_minute=2,
            requests_per_hour=100,
            burst_allowance=0,
            queue_at_soft_limit=True,
        )
        limiter.configure_agent_limit("agent-q", config)

        # Exhaust limit
        limiter.consume(agent_id="agent-q")
        limiter.consume(agent_id="agent-q")

        # Next request should be queued
        result = limiter.consume(agent_id="agent-q")
        assert result.allowed is False
        assert result.queued is True

        # Verify it's in the queue
        queued = limiter.get_queued_requests()
        assert len(queued) >= 1

    def test_multiple_limits_most_restrictive_wins(self):
        limiter = RateLimiter()
        # Agent has generous limit
        limiter.configure_agent_limit(
            "agent-1",
            RateLimitConfig(requests_per_minute=100, requests_per_hour=1000),
        )
        # Resource has tight limit
        limiter.configure_resource_limit(
            "deploy",
            RateLimitConfig(
                requests_per_minute=2, requests_per_hour=10, burst_allowance=0,
            ),
        )

        # Consume resource limit
        limiter.consume(agent_id="agent-1", resource_key="deploy")
        limiter.consume(agent_id="agent-1", resource_key="deploy")

        # Third should fail due to resource limit
        result = limiter.check_rate_limit(agent_id="agent-1", resource_key="deploy")
        assert result.allowed is False

    def test_clear_queue(self):
        limiter = RateLimiter()
        config = RateLimitConfig(
            requests_per_minute=1,
            requests_per_hour=100,
            burst_allowance=0,
            queue_at_soft_limit=True,
        )
        limiter.configure_agent_limit("agent-cq", config)
        limiter.consume(agent_id="agent-cq")
        limiter.consume(agent_id="agent-cq")  # This gets queued

        cleared = limiter.clear_queue()
        assert cleared >= 1
        assert len(limiter.get_queued_requests()) == 0


if __name__ == "__main__":
    # Run tests directly
    passed = 0
    failed = 0

    for cls in [TestTokenBucket, TestSlidingWindowCounter, TestRateLimiter]:
        instance = cls()
        for method_name in sorted(dir(instance)):
            if method_name.startswith("test_"):
                try:
                    getattr(instance, method_name)()
                    passed += 1
                    print(f"  PASS: {cls.__name__}.{method_name}")
                except Exception as e:
                    failed += 1
                    print(f"  FAIL: {cls.__name__}.{method_name}: {e}")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
