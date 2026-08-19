"""Smart Retry with Escalation - intelligent retry with failure diagnosis and escalation.

Extends the RetryWithBudget pattern with error pattern tracking, failure
diagnosis, and escalation actions. Detects permanent blockers, suggests
task decomposition for complexity issues, and recommends reassignment
when varied errors indicate a mismatch.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable


class EscalationAction(str, Enum):
    """Actions that can be taken when retries are insufficient.

    Values:
        RETRY: Continue retrying (transient error).
        REASSIGN: Assign to a different agent (varied failures suggest mismatch).
        DECOMPOSE: Break the task into smaller pieces (complexity/size issue).
        REPORT_BLOCKER: Report as a permanent blocker (repeated identical error).
    """

    RETRY = "retry"
    REASSIGN = "reassign"
    DECOMPOSE = "decompose"
    REPORT_BLOCKER = "report_blocker"


@dataclass
class FailureDiagnosis:
    """Diagnosis of a failure pattern after analysis.

    Attributes:
        error_pattern: The most common error pattern observed.
        is_permanent: Whether the error is deemed permanent (non-transient).
        suggested_action: The recommended escalation action.
        diagnosis_detail: Human-readable explanation of the diagnosis.
    """

    error_pattern: str
    is_permanent: bool
    suggested_action: EscalationAction
    diagnosis_detail: str


@dataclass
class SmartRetryResult:
    """Outcome of a smart retry execution with escalation information.

    Extends the RetryResult concept with escalation context, diagnosis,
    and full attempt history for post-mortem analysis.

    Attributes:
        task_id: The task that was executed.
        success: Whether the task ultimately succeeded.
        output: Final output, if successful.
        error: Last error message, if all retries failed.
        attempts: Total number of attempts made.
        total_cost_cents: Cumulative cost across all attempts.
        budget_exhausted: Whether the budget limit was hit.
        escalation_action: Recommended next action if the task failed.
        diagnosis: Failure diagnosis if the task failed.
        attempt_history: List of (attempt_number, error_or_None) for each attempt.
    """

    task_id: uuid.UUID
    success: bool
    output: Any = None
    error: str | None = None
    attempts: int = 0
    total_cost_cents: int = 0
    budget_exhausted: bool = False
    escalation_action: EscalationAction | None = None
    diagnosis: FailureDiagnosis | None = None
    attempt_history: list[tuple[int, str | None]] = field(default_factory=list)


# Keywords that suggest the task should be decomposed into smaller pieces
_DECOMPOSE_KEYWORDS: list[str] = ["too large", "complex", "timeout"]

# Threshold for identical errors before declaring a permanent blocker
_PERMANENT_BLOCKER_THRESHOLD: int = 3


class SmartRetryWithEscalation:
    """Retries failed tasks with intelligent escalation based on error patterns.

    Wraps the retry-with-budget pattern and adds:
    1. Error pattern tracking via Counter to detect repeated identical errors.
    2. Diagnosis protocol that classifies errors as transient, permanent,
       or decomposable.
    3. Escalation logic:
       - Same error 3+ times -> REPORT_BLOCKER (permanent failure)
       - Different errors each time -> REASSIGN (agent mismatch)
       - Error mentions 'too large', 'complex', 'timeout' -> DECOMPOSE

    Example usage:
        smart_retry = SmartRetryWithEscalation(max_retries=5, budget_limit_cents=500)
        result = await smart_retry.execute_with_smart_retry(
            task_id=uuid.uuid4(),
            execute_fn=my_async_task,
            estimated_cost_per_attempt_cents=50,
        )
        if not result.success:
            print(f"Escalation: {result.escalation_action}")
            print(f"Diagnosis: {result.diagnosis.diagnosis_detail}")
    """

    def __init__(
        self,
        max_retries: int = 3,
        budget_limit_cents: int = 1000,
        permanent_blocker_threshold: int = _PERMANENT_BLOCKER_THRESHOLD,
    ) -> None:
        """Initialize the smart retry handler.

        Args:
            max_retries: Maximum number of retry attempts after first failure.
            budget_limit_cents: Maximum cumulative cost in cents before stopping.
            permanent_blocker_threshold: Number of identical errors before
                declaring a permanent blocker.
        """
        self._max_retries = max_retries
        self._budget_limit_cents = budget_limit_cents
        self._permanent_blocker_threshold = permanent_blocker_threshold

    async def execute_with_smart_retry(
        self,
        task_id: uuid.UUID,
        execute_fn: Callable[[], Awaitable[tuple[Any, int]]],
        estimated_cost_per_attempt_cents: int = 0,
    ) -> SmartRetryResult:
        """Execute a task with smart retry and escalation logic.

        The execute_fn should return a tuple of (output, cost_cents) on
        success, or raise an exception on failure.

        Args:
            task_id: Identifier for the task being executed.
            execute_fn: Async callable that returns (result, cost_cents).
            estimated_cost_per_attempt_cents: Estimated cost per attempt for
                pre-checking budget availability.

        Returns:
            A SmartRetryResult with the final outcome and escalation info.
        """
        total_cost = 0
        last_error: str | None = None
        attempts = 0
        max_attempts = 1 + self._max_retries
        error_counter: Counter[str] = Counter()
        attempt_history: list[tuple[int, str | None]] = []

        for attempt in range(max_attempts):
            attempts = attempt + 1

            # Pre-check: would the next attempt exceed budget?
            if estimated_cost_per_attempt_cents > 0:
                remaining = self._budget_limit_cents - total_cost
                if remaining < estimated_cost_per_attempt_cents:
                    diagnosis = self._diagnose_errors(error_counter)
                    return SmartRetryResult(
                        task_id=task_id,
                        success=False,
                        error=last_error or "Budget exhausted before execution",
                        attempts=attempts,
                        total_cost_cents=total_cost,
                        budget_exhausted=True,
                        escalation_action=diagnosis.suggested_action if diagnosis else None,
                        diagnosis=diagnosis,
                        attempt_history=attempt_history,
                    )

            try:
                output, cost_cents = await execute_fn()
                total_cost += cost_cents
                attempt_history.append((attempts, None))

                return SmartRetryResult(
                    task_id=task_id,
                    success=True,
                    output=output,
                    attempts=attempts,
                    total_cost_cents=total_cost,
                    budget_exhausted=total_cost > self._budget_limit_cents,
                    escalation_action=None,
                    diagnosis=None,
                    attempt_history=attempt_history,
                )

            except Exception as exc:
                error_msg = str(exc)
                last_error = error_msg
                error_counter[error_msg] += 1
                attempt_history.append((attempts, error_msg))

                # Estimate cost even for failed attempts
                total_cost += estimated_cost_per_attempt_cents

                # Check budget after failed attempt
                if total_cost >= self._budget_limit_cents:
                    diagnosis = self._diagnose_errors(error_counter)
                    return SmartRetryResult(
                        task_id=task_id,
                        success=False,
                        error=last_error,
                        attempts=attempts,
                        total_cost_cents=total_cost,
                        budget_exhausted=True,
                        escalation_action=diagnosis.suggested_action if diagnosis else None,
                        diagnosis=diagnosis,
                        attempt_history=attempt_history,
                    )

                # Check for early escalation: permanent blocker detected
                most_common_count = error_counter.most_common(1)[0][1]
                if most_common_count >= self._permanent_blocker_threshold:
                    diagnosis = self._diagnose_errors(error_counter)
                    return SmartRetryResult(
                        task_id=task_id,
                        success=False,
                        error=last_error,
                        attempts=attempts,
                        total_cost_cents=total_cost,
                        budget_exhausted=False,
                        escalation_action=diagnosis.suggested_action,
                        diagnosis=diagnosis,
                        attempt_history=attempt_history,
                    )

        # All retries exhausted without early escalation
        diagnosis = self._diagnose_errors(error_counter)
        return SmartRetryResult(
            task_id=task_id,
            success=False,
            error=last_error,
            attempts=attempts,
            total_cost_cents=total_cost,
            budget_exhausted=False,
            escalation_action=diagnosis.suggested_action if diagnosis else None,
            diagnosis=diagnosis,
            attempt_history=attempt_history,
        )

    def _diagnose_errors(self, error_counter: Counter[str]) -> FailureDiagnosis | None:
        """Diagnose the failure pattern from collected errors.

        Applies the diagnosis protocol:
        1. Same error N+ times -> REPORT_BLOCKER (permanent)
        2. Error mentions decompose keywords -> DECOMPOSE
        3. All different errors -> REASSIGN (agent mismatch)
        4. Otherwise -> RETRY (transient)

        Args:
            error_counter: Counter of error messages seen.

        Returns:
            A FailureDiagnosis with the classification, or None if no errors.
        """
        if not error_counter:
            return None

        most_common_error, most_common_count = error_counter.most_common(1)[0]

        # Check for permanent blocker: same error repeated N+ times
        if most_common_count >= self._permanent_blocker_threshold:
            return FailureDiagnosis(
                error_pattern=most_common_error,
                is_permanent=True,
                suggested_action=EscalationAction.REPORT_BLOCKER,
                diagnosis_detail=(
                    f"Permanent blocker detected: error '{most_common_error}' "
                    f"repeated {most_common_count} times"
                ),
            )

        # Check for decomposition keywords in any error
        all_errors = " ".join(error_counter.keys()).lower()
        for keyword in _DECOMPOSE_KEYWORDS:
            if keyword in all_errors:
                return FailureDiagnosis(
                    error_pattern=most_common_error,
                    is_permanent=False,
                    suggested_action=EscalationAction.DECOMPOSE,
                    diagnosis_detail=(
                        f"Task appears too complex or large: "
                        f"error contains '{keyword}'"
                    ),
                )

        # Check for varied errors (all different = agent mismatch)
        unique_error_count = len(error_counter)
        total_error_count = sum(error_counter.values())
        if unique_error_count == total_error_count and total_error_count > 1:
            return FailureDiagnosis(
                error_pattern=most_common_error,
                is_permanent=False,
                suggested_action=EscalationAction.REASSIGN,
                diagnosis_detail=(
                    f"All {unique_error_count} errors are different, "
                    f"suggesting agent mismatch"
                ),
            )

        # Default: transient, suggest retry
        return FailureDiagnosis(
            error_pattern=most_common_error,
            is_permanent=False,
            suggested_action=EscalationAction.RETRY,
            diagnosis_detail=(
                f"Transient errors detected: {total_error_count} total, "
                f"{unique_error_count} unique patterns"
            ),
        )
