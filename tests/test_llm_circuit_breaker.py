"""Tests for LLM Circuit Breaker (nexus.adapters.llm_circuit_breaker)."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from nexus.adapters.llm_circuit_breaker import (
    CircuitState,
    LLMCircuitBreaker,
    LLMCircuitBreakerConfig,
    wrap_llm_callable,
)


class TestLLMCircuitBreakerBasic:
    """Basic tests for the LLM circuit breaker."""

    async def test_passes_through_when_closed(self) -> None:
        """Test that calls pass through when circuit is closed."""
        mock_llm = AsyncMock(return_value="Hello, world!")
        breaker = wrap_llm_callable(mock_llm)

        result = await breaker("prompt")
        assert result == "Hello, world!"
        assert breaker.state == CircuitState.CLOSED
        mock_llm.assert_called_once_with("prompt")

    async def test_opens_after_threshold_failures(self) -> None:
        """Test that circuit opens after N consecutive failures."""
        mock_llm = AsyncMock(side_effect=RuntimeError("API error"))
        breaker = wrap_llm_callable(mock_llm, failure_threshold=3)

        # Three failures should open the circuit
        for _ in range(3):
            await breaker("prompt")

        assert breaker.state == CircuitState.OPEN
        assert breaker.consecutive_failures == 3

    async def test_returns_fallback_when_open(self) -> None:
        """Test that fallback is returned when circuit is open."""
        mock_llm = AsyncMock(side_effect=RuntimeError("API error"))
        fallback = "System is busy"
        breaker = wrap_llm_callable(
            mock_llm, failure_threshold=2, fallback_response=fallback
        )

        # Open the circuit
        await breaker("p1")
        await breaker("p2")
        assert breaker.state == CircuitState.OPEN

        # Next call should return fallback without calling LLM
        mock_llm.reset_mock()
        result = await breaker("p3")
        assert result == fallback
        mock_llm.assert_not_called()

    async def test_success_resets_failure_count(self) -> None:
        """Test that a success resets the consecutive failure counter."""
        call_count = 0

        async def flaky_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("fail")
            return "success"

        breaker = wrap_llm_callable(flaky_llm, failure_threshold=3)

        await breaker("p1")  # fail
        await breaker("p2")  # fail
        assert breaker.consecutive_failures == 2

        await breaker("p3")  # success
        assert breaker.consecutive_failures == 0
        assert breaker.state == CircuitState.CLOSED


class TestLLMCircuitBreakerTimeout:
    """Tests for timeout handling."""

    async def test_timeout_counts_as_failure(self) -> None:
        """Test that a timeout is treated as a failure."""
        async def slow_llm(prompt: str) -> str:
            await asyncio.sleep(10)
            return "late"

        breaker = wrap_llm_callable(
            slow_llm, failure_threshold=2, timeout_seconds=0.01
        )

        await breaker("p1")
        assert breaker.consecutive_failures == 1
        assert breaker.state == CircuitState.CLOSED

        await breaker("p2")
        assert breaker.state == CircuitState.OPEN

    async def test_returns_fallback_on_timeout(self) -> None:
        """Test that fallback is returned when LLM times out."""
        async def slow_llm(prompt: str) -> str:
            await asyncio.sleep(10)
            return "late"

        breaker = wrap_llm_callable(
            slow_llm,
            failure_threshold=5,
            timeout_seconds=0.01,
            fallback_response="timed out",
        )

        result = await breaker("prompt")
        assert result == "timed out"


class TestLLMCircuitBreakerHalfOpen:
    """Tests for half-open state transitions."""

    async def test_transitions_to_half_open_after_cooldown(self) -> None:
        """Test that circuit transitions to half-open after cooldown."""
        mock_llm = AsyncMock(side_effect=RuntimeError("fail"))
        breaker = wrap_llm_callable(
            mock_llm, failure_threshold=2, cooldown_seconds=0.01
        )

        # Open the circuit
        await breaker("p1")
        await breaker("p2")
        assert breaker.state == CircuitState.OPEN

        # Wait for cooldown
        await asyncio.sleep(0.02)

        # Next call should transition to half-open and try
        mock_llm.side_effect = None
        mock_llm.return_value = "recovered"
        result = await breaker("p3")

        assert result == "recovered"
        assert breaker.state == CircuitState.CLOSED

    async def test_half_open_failure_reopens(self) -> None:
        """Test that failure in half-open state re-opens the circuit."""
        mock_llm = AsyncMock(side_effect=RuntimeError("fail"))
        breaker = wrap_llm_callable(
            mock_llm, failure_threshold=2, cooldown_seconds=0.01
        )

        # Open the circuit
        await breaker("p1")
        await breaker("p2")
        assert breaker.state == CircuitState.OPEN

        # Wait for cooldown
        await asyncio.sleep(0.02)

        # Probe call fails - should re-open
        result = await breaker("p3")
        assert breaker.state == CircuitState.OPEN


class TestLLMCircuitBreakerReset:
    """Tests for manual reset."""

    async def test_manual_reset(self) -> None:
        """Test that manual reset returns to closed state."""
        mock_llm = AsyncMock(side_effect=RuntimeError("fail"))
        breaker = wrap_llm_callable(mock_llm, failure_threshold=2)

        await breaker("p1")
        await breaker("p2")
        assert breaker.state == CircuitState.OPEN

        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.consecutive_failures == 0


class TestWrapLLMCallable:
    """Tests for the wrap_llm_callable factory function."""

    async def test_factory_creates_breaker(self) -> None:
        """Test that factory creates a properly configured breaker."""
        mock_llm = AsyncMock(return_value="ok")
        breaker = wrap_llm_callable(
            mock_llm,
            failure_threshold=5,
            cooldown_seconds=120.0,
            fallback_response="custom fallback",
            timeout_seconds=10.0,
        )

        assert isinstance(breaker, LLMCircuitBreaker)
        assert breaker._config.failure_threshold == 5
        assert breaker._config.cooldown_seconds == 120.0
        assert breaker._config.fallback_response == "custom fallback"
        assert breaker._config.timeout_seconds == 10.0

    async def test_factory_uses_defaults(self) -> None:
        """Test that factory uses sensible defaults."""
        mock_llm = AsyncMock(return_value="ok")
        breaker = wrap_llm_callable(mock_llm)

        assert breaker._config.failure_threshold == 3
        assert breaker._config.cooldown_seconds == 60.0
        assert breaker._config.timeout_seconds == 30.0

    async def test_breaker_is_callable(self) -> None:
        """Test that the breaker can be called like the original function."""
        mock_llm = AsyncMock(return_value="response")
        breaker = wrap_llm_callable(mock_llm)

        # Should be callable with same signature
        result = await breaker("my prompt")
        assert result == "response"
