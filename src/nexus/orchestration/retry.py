"""Retry with Budget - retries failed tasks up to limits or budget exhaustion."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable


@dataclass
class RetryResult:
    """Outcome of a retry-enabled execution.

    Attributes:
        task_id: The task that was executed.
        success: Whether the task ultimately succeeded.
        output: Final output, if successful.
        error: Last error message, if all retries failed.
        attempts: Total number of attempts made.
        total_cost_cents: Cumulative cost across all attempts.
        budget_exhausted: Whether the budget limit was hit.
    """

    task_id: uuid.UUID
    success: bool
    output: Any = None
    error: str | None = None
    attempts: int = 0
    total_cost_cents: int = 0
    budget_exhausted: bool = False


class RetryWithBudget:
    """Retries failed tasks up to a maximum count or until budget is exhausted.

    Tracks cumulative cost across retries and will not attempt another
    retry if the estimated cost would exceed the remaining budget.
    """

    def __init__(
        self,
        max_retries: int = 3,
        budget_limit_cents: int = 1000,
        backoff_base_ms: int = 1000,
    ) -> None:
        """Initialize the retry handler.

        Args:
            max_retries: Maximum number of retry attempts after first failure.
            budget_limit_cents: Maximum cumulative cost in cents before stopping.
            backoff_base_ms: Base backoff time in milliseconds (doubles each retry).
        """
        self._max_retries = max_retries
        self._budget_limit_cents = budget_limit_cents
        self._backoff_base_ms = backoff_base_ms

    async def execute_with_retry(
        self,
        task_id: uuid.UUID,
        execute_fn: Callable[[], Awaitable[tuple[Any, int]]],
        estimated_cost_per_attempt_cents: int = 0,
    ) -> RetryResult:
        """Execute a task with retry logic bounded by attempts and budget.

        The execute_fn should return a tuple of (output, cost_cents) on
        success, or raise an exception on failure.

        Args:
            task_id: Identifier for the task being executed.
            execute_fn: Async callable that returns (result, cost_cents).
            estimated_cost_per_attempt_cents: Estimated cost per attempt for
                pre-checking budget availability.

        Returns:
            A RetryResult with the final outcome.
        """
        total_cost = 0
        last_error: str | None = None
        attempts = 0
        max_attempts = 1 + self._max_retries

        for attempt in range(max_attempts):
            attempts = attempt + 1

            # Pre-check: would the next attempt exceed budget?
            if estimated_cost_per_attempt_cents > 0:
                remaining = self._budget_limit_cents - total_cost
                if remaining < estimated_cost_per_attempt_cents:
                    return RetryResult(
                        task_id=task_id,
                        success=False,
                        error=last_error or "Budget exhausted before execution",
                        attempts=attempts,
                        total_cost_cents=total_cost,
                        budget_exhausted=True,
                    )

            try:
                output, cost_cents = await execute_fn()
                total_cost += cost_cents

                # Check if budget is now over limit
                if total_cost > self._budget_limit_cents:
                    return RetryResult(
                        task_id=task_id,
                        success=True,
                        output=output,
                        attempts=attempts,
                        total_cost_cents=total_cost,
                        budget_exhausted=True,
                    )

                return RetryResult(
                    task_id=task_id,
                    success=True,
                    output=output,
                    attempts=attempts,
                    total_cost_cents=total_cost,
                    budget_exhausted=False,
                )

            except Exception as exc:
                last_error = str(exc)
                # Estimate cost even for failed attempts (some providers charge)
                total_cost += estimated_cost_per_attempt_cents

                # Check budget after failed attempt
                if total_cost >= self._budget_limit_cents:
                    return RetryResult(
                        task_id=task_id,
                        success=False,
                        error=last_error,
                        attempts=attempts,
                        total_cost_cents=total_cost,
                        budget_exhausted=True,
                    )

                # Apply backoff before next retry (except on last attempt)
                if attempt < max_attempts - 1:
                    import asyncio
                    backoff_ms = self._backoff_base_ms * (2 ** attempt)
                    await asyncio.sleep(backoff_ms / 1000.0)

        return RetryResult(
            task_id=task_id,
            success=False,
            error=last_error,
            attempts=attempts,
            total_cost_cents=total_cost,
            budget_exhausted=False,
        )
