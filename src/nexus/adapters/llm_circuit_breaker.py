"""LLM Circuit Breaker - wraps async LLM callables with failure protection.

When N consecutive failures (timeout, 5xx, rate limit) occur, the breaker
opens and returns a configurable fallback response for a cooldown period.
After the cooldown, the breaker enters half-open state and allows one
probe call through.

Usage:
    from nexus.adapters.llm_circuit_breaker import wrap_llm_callable

    safe_llm = wrap_llm_callable(my_llm_fn, failure_threshold=3)
    result = await safe_llm("Hello")
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """States for the circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class LLMCircuitBreakerConfig:
    """Configuration for the LLM circuit breaker.

    Attributes:
        failure_threshold: Number of consecutive failures before opening.
        cooldown_seconds: How long the breaker stays open before half-open.
        fallback_response: Response to return when the breaker is open.
        timeout_seconds: Timeout for individual LLM calls.
        success_threshold: Successes needed in half-open to close the breaker.
    """

    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    fallback_response: str = "[LLM unavailable - circuit breaker open]"
    timeout_seconds: float = 30.0
    success_threshold: int = 1


class LLMCircuitBreaker:
    """Circuit breaker that wraps an async LLM callable.

    Tracks consecutive failures and opens the circuit after a configurable
    threshold. In the open state, calls return the fallback response
    immediately without invoking the LLM. After a cooldown period, the
    breaker enters half-open state and allows probe calls through.
    """

    def __init__(
        self,
        llm_callable: Callable[[str], Awaitable[str]],
        config: LLMCircuitBreakerConfig | None = None,
    ) -> None:
        """Initialize the circuit breaker around an LLM callable.

        Args:
            llm_callable: The async LLM function to protect.
            config: Breaker configuration. Uses defaults if None.
        """
        self._llm = llm_callable
        self._config = config or LLMCircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_failure_time: float = 0.0
        self._half_open_successes = 0

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state."""
        return self._state

    @property
    def consecutive_failures(self) -> int:
        """Return the current consecutive failure count."""
        return self._consecutive_failures

    async def __call__(self, prompt: str) -> str:
        """Execute the LLM call with circuit breaker protection.

        Args:
            prompt: The prompt to send to the LLM.

        Returns:
            The LLM response, or the fallback if the circuit is open.
        """
        # Check if we should transition from OPEN to HALF_OPEN
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._config.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_successes = 0
                logger.info("LLM circuit breaker entering half-open state")
            else:
                return self._config.fallback_response

        # Attempt the LLM call
        try:
            result = await asyncio.wait_for(
                self._llm(prompt),
                timeout=self._config.timeout_seconds,
            )
            self._on_success()
            return result
        except (asyncio.TimeoutError, TimeoutError) as exc:
            logger.warning("LLM call timed out: %s", exc)
            self._on_failure()
            return self._config.fallback_response
        except Exception as exc:
            logger.warning("LLM call failed: %s", exc)
            self._on_failure()
            return self._config.fallback_response

    def _on_success(self) -> None:
        """Handle a successful LLM call."""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self._config.success_threshold:
                self._state = CircuitState.CLOSED
                self._consecutive_failures = 0
                logger.info("LLM circuit breaker closed (recovered)")
        else:
            self._consecutive_failures = 0

    def _on_failure(self) -> None:
        """Handle a failed LLM call."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Half-open probe failed - back to open
            self._state = CircuitState.OPEN
            logger.warning("LLM circuit breaker re-opened (half-open probe failed)")
        elif self._consecutive_failures >= self._config.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "LLM circuit breaker opened after %d consecutive failures",
                self._consecutive_failures,
            )

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_successes = 0


def wrap_llm_callable(
    llm_callable: Callable[[str], Awaitable[str]],
    failure_threshold: int = 3,
    cooldown_seconds: float = 60.0,
    fallback_response: str = "[LLM unavailable - circuit breaker open]",
    timeout_seconds: float = 30.0,
) -> LLMCircuitBreaker:
    """Factory function to wrap an LLM callable with circuit breaker protection.

    Args:
        llm_callable: The async LLM function to protect.
        failure_threshold: Consecutive failures before opening the circuit.
        cooldown_seconds: How long the circuit stays open.
        fallback_response: Response returned when the circuit is open.
        timeout_seconds: Timeout for individual LLM calls.

    Returns:
        An LLMCircuitBreaker instance that can be called like the original.
    """
    config = LLMCircuitBreakerConfig(
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
        fallback_response=fallback_response,
        timeout_seconds=timeout_seconds,
    )
    return LLMCircuitBreaker(llm_callable, config)
