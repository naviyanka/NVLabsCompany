"""Temporal SDK bridge — decorators and activity dispatch that also work off-Temporal.

``temporalio`` is a declared dependency, but two situations need the activity
layer to run without it. ``api/routes/degradation.py`` reports Temporal as an
optional capability, and ADR 0001 requires the same activity functions to run
in-process when the Temporal server is unreachable ("one code path, two
runners"). So:

- the decorators here are identity functions when the SDK is absent, which keeps
  ``activities.py`` and ``workflows.py`` importable either way;
- :func:`execute_activity` dispatches through Temporal only when it is actually
  running inside a workflow, and otherwise awaits the activity directly.

Retry policy is per-call rather than global because activities are not equally
safe to retry: an LLM call is billed on every attempt, so ADR 0001 requires it
to run once only. Retry-safe activities keep the SDK default of a few attempts.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

try:
    from temporalio import activity as _activity
    from temporalio import workflow as _workflow
    from temporalio.common import RetryPolicy as _RetryPolicy

    HAS_SDK = True
    activity_defn = _activity.defn
    workflow_defn = _workflow.defn
    workflow_run = _workflow.run
    imports_passed_through = _workflow.unsafe.imports_passed_through
except ImportError:  # pragma: no cover — only without temporalio installed
    HAS_SDK = False
    _RetryPolicy = None

    def _passthrough(*args: Any, **kwargs: Any) -> Any:
        """Stand in for a Temporal decorator, used bare or as a factory.

        `temporalio`'s decorators support both `@defn` and `@defn(name="X")`.
        The fallback has to accept the same two shapes, or importing
        workflows.py without the SDK raises TypeError at module load.
        """
        if len(args) == 1 and not kwargs and (callable(args[0]) or isinstance(args[0], type)):
            return args[0]
        return lambda obj: obj

    activity_defn = _passthrough
    workflow_defn = _passthrough
    workflow_run = _passthrough
    imports_passed_through = contextlib.nullcontext

# An LLM call can legitimately take minutes; routing and planning should not.
LLM_TIMEOUT = timedelta(minutes=10)
DEFAULT_TIMEOUT = timedelta(minutes=2)

# Billed activities run once only — a second attempt would be a second charge.
ONCE_ONLY = 1
RETRY_SAFE = 3


async def execute_activity[T](
    fn: Callable[[Any], Awaitable[T]],
    arg: Any,
    *,
    timeout: timedelta = DEFAULT_TIMEOUT,
    maximum_attempts: int = RETRY_SAFE,
) -> T:
    """Run an activity durably inside a workflow, or in-process outside one.

    Args:
        fn: The ``@activity_defn`` function to run.
        arg: Its single dataclass argument.
        timeout: Start-to-close timeout applied when running under Temporal.
        maximum_attempts: Retry ceiling applied when running under Temporal.
            Pass ``ONCE_ONLY`` for anything that bills.

    Returns:
        Whatever the activity returns.
    """
    if HAS_SDK and _workflow.in_workflow():
        return await _workflow.execute_activity(
            fn,
            arg,
            start_to_close_timeout=timeout,
            retry_policy=_RetryPolicy(maximum_attempts=maximum_attempts),
        )
    return await fn(arg)
