"""Parallel Executor - runs multiple tasks concurrently with configurable limits."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable


@dataclass
class TaskResult:
    """Result of a single task execution within a parallel batch.

    Attributes:
        task_id: Identifier of the executed task.
        success: Whether the task completed successfully.
        output: The task output, if successful.
        error: Error message, if failed.
        duration_ms: Execution time in milliseconds.
    """

    task_id: uuid.UUID
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: int = 0


@dataclass
class ParallelResult:
    """Aggregated result of a parallel execution batch.

    Attributes:
        results: Individual results for each task.
        total_tasks: Total number of tasks attempted.
        succeeded: Number of successful tasks.
        failed: Number of failed tasks.
        total_duration_ms: Wall-clock duration of the entire batch.
    """

    results: list[TaskResult] = field(default_factory=list)
    total_tasks: int = 0
    succeeded: int = 0
    failed: int = 0
    total_duration_ms: int = 0


class ParallelExecutor:
    """Executes multiple tasks concurrently using asyncio with a semaphore.

    Provides configurable concurrency limits and handles partial failures
    gracefully - one failing task does not cancel others.
    """

    def __init__(
        self,
        max_concurrency: int = 5,
        timeout_seconds: float = 300.0,
    ) -> None:
        """Initialize the parallel executor.

        Args:
            max_concurrency: Maximum number of concurrent task executions.
            timeout_seconds: Per-task timeout in seconds.
        """
        self._max_concurrency = max_concurrency
        self._timeout_seconds = timeout_seconds

    async def execute_parallel(
        self,
        tasks: list[dict[str, Any]],
        executor_fn: Callable[[dict[str, Any]], Awaitable[Any]],
    ) -> ParallelResult:
        """Execute tasks in parallel with bounded concurrency.

        Each task dictionary is passed to the executor_fn. Failures in
        individual tasks do not affect others. Tasks that exceed the
        timeout are marked as failed.

        Args:
            tasks: List of task payloads to execute.
            executor_fn: Async callable that processes a single task.

        Returns:
            A ParallelResult with individual outcomes and aggregate stats.
        """
        start = datetime.now(timezone.utc)
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _run_one(task: dict[str, Any]) -> TaskResult:
            task_id = uuid.UUID(task["id"]) if "id" in task else uuid.uuid4()
            task_start = datetime.now(timezone.utc)
            async with semaphore:
                try:
                    output = await asyncio.wait_for(
                        executor_fn(task), timeout=self._timeout_seconds
                    )
                    elapsed = (
                        datetime.now(timezone.utc) - task_start
                    ).total_seconds()
                    return TaskResult(
                        task_id=task_id,
                        success=True,
                        output=output,
                        duration_ms=int(elapsed * 1000),
                    )
                except asyncio.TimeoutError:
                    elapsed = (
                        datetime.now(timezone.utc) - task_start
                    ).total_seconds()
                    return TaskResult(
                        task_id=task_id,
                        success=False,
                        error=f"Task timed out after {self._timeout_seconds}s",
                        duration_ms=int(elapsed * 1000),
                    )
                except Exception as exc:
                    elapsed = (
                        datetime.now(timezone.utc) - task_start
                    ).total_seconds()
                    return TaskResult(
                        task_id=task_id,
                        success=False,
                        error=str(exc),
                        duration_ms=int(elapsed * 1000),
                    )

        results = await asyncio.gather(*[_run_one(t) for t in tasks])
        end = datetime.now(timezone.utc)
        total_ms = int((end - start).total_seconds() * 1000)

        succeeded = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)

        return ParallelResult(
            results=list(results),
            total_tasks=len(tasks),
            succeeded=succeeded,
            failed=failed,
            total_duration_ms=total_ms,
        )
