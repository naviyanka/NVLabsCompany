"""Shared retry utility for LLM adapters.

Provides exponential backoff with jitter for rate-limited and transient
error conditions. Used by all adapter implementations.
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay cap in seconds.
        jitter: Whether to add randomized jitter to prevent thundering herd.
        retryable_statuses: HTTP status codes that trigger a retry.
    """

    max_retries: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: bool = True
    retryable_statuses: set[int] = field(
        default_factory=lambda: {429, 500, 502, 503, 529}
    )


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"All {attempts} retry attempts exhausted. Last error: {last_error}"
        )


def _compute_delay(attempt: int, config: RetryConfig) -> float:
    """Compute delay for a given attempt with optional jitter."""
    delay = min(config.base_delay * (2**attempt), config.max_delay)
    if config.jitter:
        delay *= 0.5 + random.random()
    return delay


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    config: RetryConfig | None = None,
    operation_name: str = "request",
) -> T:
    """Execute an async function with exponential backoff retry.

    Retries on httpx.HTTPStatusError when the status code is in the
    retryable set. Non-retryable errors (400, 401, 403, 404) raise
    immediately.

    Args:
        fn: Async callable to execute (no arguments).
        config: Retry configuration. Uses defaults if None.
        operation_name: Name used in log messages for this operation.

    Returns:
        The result of fn() on success.

    Raises:
        RetryExhaustedError: If all retries are exhausted.
        httpx.HTTPStatusError: If error is non-retryable.
    """
    if config is None:
        config = RetryConfig()

    last_error: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            return await fn()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status not in config.retryable_statuses:
                raise
            last_error = exc
            if attempt == config.max_retries:
                break
            delay = _compute_delay(attempt, config)
            logger.warning(
                "%s: HTTP %d, retrying in %.1fs (attempt %d/%d)",
                operation_name,
                status,
                delay,
                attempt + 1,
                config.max_retries,
            )
            await asyncio.sleep(delay)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_error = exc
            if attempt == config.max_retries:
                break
            delay = _compute_delay(attempt, config)
            logger.warning(
                "%s: %s, retrying in %.1fs (attempt %d/%d)",
                operation_name,
                type(exc).__name__,
                delay,
                attempt + 1,
                config.max_retries,
            )
            await asyncio.sleep(delay)

    raise RetryExhaustedError(config.max_retries + 1, last_error)  # type: ignore[arg-type]
