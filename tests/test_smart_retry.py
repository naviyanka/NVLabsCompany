"""Tests for Smart Retry with Escalation."""

import uuid

import pytest

from nexus.orchestration.smart_retry import (
    EscalationAction,
    FailureDiagnosis,
    SmartRetryResult,
    SmartRetryWithEscalation,
)


@pytest.fixture
def smart_retry() -> SmartRetryWithEscalation:
    """Create a SmartRetryWithEscalation with default settings."""
    return SmartRetryWithEscalation(max_retries=5, budget_limit_cents=1000)


@pytest.fixture
def task_id() -> uuid.UUID:
    """Create a test task UUID."""
    return uuid.uuid4()


class TestSuccessfulExecution:
    """Tests for successful execution without retries."""

    @pytest.mark.asyncio
    async def test_success_first_attempt(
        self, smart_retry: SmartRetryWithEscalation, task_id: uuid.UUID
    ) -> None:
        """Successful execution on first attempt returns success."""

        async def success_fn() -> tuple[str, int]:
            return ("result", 50)

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=success_fn,
            estimated_cost_per_attempt_cents=50,
        )

        assert result.success is True
        assert result.output == "result"
        assert result.attempts == 1
        assert result.total_cost_cents == 50
        assert result.budget_exhausted is False
        assert result.escalation_action is None
        assert result.diagnosis is None

    @pytest.mark.asyncio
    async def test_success_no_escalation(
        self, smart_retry: SmartRetryWithEscalation, task_id: uuid.UUID
    ) -> None:
        """Successful execution has no escalation action."""

        async def success_fn() -> tuple[str, int]:
            return ("done", 10)

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id, execute_fn=success_fn
        )

        assert result.escalation_action is None
        assert result.diagnosis is None
        assert result.attempt_history == [(1, None)]


class TestTransientFailureRetry:
    """Tests for transient failures that succeed on retry."""

    @pytest.mark.asyncio
    async def test_succeeds_after_transient_failure(
        self, smart_retry: SmartRetryWithEscalation, task_id: uuid.UUID
    ) -> None:
        """Transient failure followed by success returns success."""
        call_count = 0

        async def flaky_fn() -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Temporary network error")
            return ("recovered", 50)

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=flaky_fn,
            estimated_cost_per_attempt_cents=50,
        )

        assert result.success is True
        assert result.output == "recovered"
        assert result.attempts == 3
        assert result.escalation_action is None

    @pytest.mark.asyncio
    async def test_attempt_history_records_failures_and_success(
        self, smart_retry: SmartRetryWithEscalation, task_id: uuid.UUID
    ) -> None:
        """Attempt history records both failures and final success."""
        call_count = 0

        async def flaky_fn() -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("oops")
            return ("ok", 10)

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=flaky_fn,
            estimated_cost_per_attempt_cents=10,
        )

        assert result.success is True
        assert result.attempts == 2
        assert result.attempt_history[0] == (1, "oops")
        assert result.attempt_history[1] == (2, None)


class TestPermanentBlockerDetection:
    """Tests for permanent blocker detection (same error 3+ times)."""

    @pytest.mark.asyncio
    async def test_same_error_three_times_reports_blocker(
        self, smart_retry: SmartRetryWithEscalation, task_id: uuid.UUID
    ) -> None:
        """Same error repeated 3 times triggers REPORT_BLOCKER."""

        async def always_fail() -> tuple[str, int]:
            raise RuntimeError("Permission denied: access blocked")

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=always_fail,
            estimated_cost_per_attempt_cents=50,
        )

        assert result.success is False
        assert result.escalation_action == EscalationAction.REPORT_BLOCKER
        assert result.diagnosis is not None
        assert result.diagnosis.is_permanent is True
        assert result.diagnosis.suggested_action == EscalationAction.REPORT_BLOCKER
        assert "Permission denied" in result.diagnosis.error_pattern

    @pytest.mark.asyncio
    async def test_blocker_stops_early(
        self, smart_retry: SmartRetryWithEscalation, task_id: uuid.UUID
    ) -> None:
        """Permanent blocker detection stops retrying early."""

        async def always_fail() -> tuple[str, int]:
            raise RuntimeError("Same error every time")

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=always_fail,
            estimated_cost_per_attempt_cents=50,
        )

        # Should stop at 3 attempts (threshold), not exhaust all 6
        assert result.attempts == 3
        assert result.escalation_action == EscalationAction.REPORT_BLOCKER


class TestReassignmentSuggestion:
    """Tests for reassignment when all errors are different."""

    @pytest.mark.asyncio
    async def test_different_errors_suggest_reassign(
        self, task_id: uuid.UUID
    ) -> None:
        """All different errors suggest REASSIGN."""
        # Use max_retries=2 so we get exactly 3 attempts with 3 unique errors
        # but threshold is 3, so blocker won't trigger
        smart_retry = SmartRetryWithEscalation(
            max_retries=2, budget_limit_cents=1000, permanent_blocker_threshold=4
        )
        call_count = 0
        errors = ["Error A: connection refused", "Error B: auth failed", "Error C: not found"]

        async def varied_fail() -> tuple[str, int]:
            nonlocal call_count
            error = errors[call_count]
            call_count += 1
            raise RuntimeError(error)

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=varied_fail,
            estimated_cost_per_attempt_cents=50,
        )

        assert result.success is False
        assert result.escalation_action == EscalationAction.REASSIGN
        assert result.diagnosis is not None
        assert result.diagnosis.suggested_action == EscalationAction.REASSIGN
        assert "different" in result.diagnosis.diagnosis_detail


class TestDecompositionSuggestion:
    """Tests for decomposition when error mentions size/complexity keywords."""

    @pytest.mark.asyncio
    async def test_too_large_error_suggests_decompose(
        self, task_id: uuid.UUID
    ) -> None:
        """Error containing 'too large' suggests DECOMPOSE."""
        smart_retry = SmartRetryWithEscalation(
            max_retries=1, budget_limit_cents=1000, permanent_blocker_threshold=5
        )

        async def large_error() -> tuple[str, int]:
            raise RuntimeError("Payload too large for single execution")

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=large_error,
            estimated_cost_per_attempt_cents=50,
        )

        assert result.success is False
        assert result.escalation_action == EscalationAction.DECOMPOSE
        assert result.diagnosis is not None
        assert result.diagnosis.suggested_action == EscalationAction.DECOMPOSE

    @pytest.mark.asyncio
    async def test_complex_error_suggests_decompose(
        self, task_id: uuid.UUID
    ) -> None:
        """Error containing 'complex' suggests DECOMPOSE."""
        smart_retry = SmartRetryWithEscalation(
            max_retries=1, budget_limit_cents=1000, permanent_blocker_threshold=5
        )

        async def complex_error() -> tuple[str, int]:
            raise RuntimeError("Task too complex to handle in one pass")

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=complex_error,
            estimated_cost_per_attempt_cents=50,
        )

        assert result.success is False
        assert result.escalation_action == EscalationAction.DECOMPOSE

    @pytest.mark.asyncio
    async def test_timeout_error_suggests_decompose(
        self, task_id: uuid.UUID
    ) -> None:
        """Error containing 'timeout' suggests DECOMPOSE."""
        smart_retry = SmartRetryWithEscalation(
            max_retries=1, budget_limit_cents=1000, permanent_blocker_threshold=5
        )

        async def timeout_error() -> tuple[str, int]:
            raise RuntimeError("Operation timeout after 60s")

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=timeout_error,
            estimated_cost_per_attempt_cents=50,
        )

        assert result.success is False
        assert result.escalation_action == EscalationAction.DECOMPOSE


class TestBudgetExhaustion:
    """Tests for budget exhaustion during smart retry."""

    @pytest.mark.asyncio
    async def test_budget_exhausted_returns_failure(
        self, task_id: uuid.UUID
    ) -> None:
        """Budget exhaustion stops retries and reports failure."""
        smart_retry = SmartRetryWithEscalation(
            max_retries=10, budget_limit_cents=100, permanent_blocker_threshold=20
        )

        async def expensive_fail() -> tuple[str, int]:
            raise RuntimeError("Some error")

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=expensive_fail,
            estimated_cost_per_attempt_cents=40,
        )

        assert result.success is False
        assert result.budget_exhausted is True
        # Should stop well before max_retries due to budget
        # After 2 attempts at 40 each = 80, pre-check sees 20 < 40 = stop
        assert result.attempts < 11  # Well below max_retries
        assert result.total_cost_cents <= 100

    @pytest.mark.asyncio
    async def test_budget_pre_check_prevents_execution(
        self, task_id: uuid.UUID
    ) -> None:
        """Pre-check prevents execution when budget is insufficient."""
        smart_retry = SmartRetryWithEscalation(
            max_retries=5, budget_limit_cents=50, permanent_blocker_threshold=10
        )
        call_count = 0

        async def fail_then_block() -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Some failure")

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=fail_then_block,
            estimated_cost_per_attempt_cents=30,
        )

        assert result.success is False
        assert result.budget_exhausted is True
        # First attempt fails (cost=30), second attempt pre-check fails (30+30>50)
        assert call_count <= 2


class TestDiagnosisProtocol:
    """Tests for the diagnosis protocol output."""

    @pytest.mark.asyncio
    async def test_diagnosis_has_error_pattern(
        self, smart_retry: SmartRetryWithEscalation, task_id: uuid.UUID
    ) -> None:
        """Diagnosis contains the most common error pattern."""

        async def always_fail() -> tuple[str, int]:
            raise RuntimeError("specific error message")

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=always_fail,
            estimated_cost_per_attempt_cents=50,
        )

        assert result.diagnosis is not None
        assert "specific error message" in result.diagnosis.error_pattern

    @pytest.mark.asyncio
    async def test_diagnosis_detail_is_descriptive(
        self, smart_retry: SmartRetryWithEscalation, task_id: uuid.UUID
    ) -> None:
        """Diagnosis detail provides human-readable explanation."""

        async def always_fail() -> tuple[str, int]:
            raise RuntimeError("Cannot connect")

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id,
            execute_fn=always_fail,
            estimated_cost_per_attempt_cents=50,
        )

        assert result.diagnosis is not None
        assert len(result.diagnosis.diagnosis_detail) > 0
        assert "Cannot connect" in result.diagnosis.diagnosis_detail

    @pytest.mark.asyncio
    async def test_smart_retry_result_dataclass_fields(
        self, smart_retry: SmartRetryWithEscalation, task_id: uuid.UUID
    ) -> None:
        """SmartRetryResult has all expected fields."""

        async def success_fn() -> tuple[str, int]:
            return ("output", 25)

        result = await smart_retry.execute_with_smart_retry(
            task_id=task_id, execute_fn=success_fn
        )

        assert isinstance(result, SmartRetryResult)
        assert result.task_id == task_id
        assert result.success is True
        assert result.output == "output"
        assert result.error is None
        assert result.attempts == 1
        assert result.total_cost_cents == 25
        assert result.budget_exhausted is False
        assert result.escalation_action is None
        assert result.diagnosis is None
        assert isinstance(result.attempt_history, list)


class TestEscalationActionEnum:
    """Tests for EscalationAction enum values."""

    def test_enum_values(self) -> None:
        """All expected escalation actions are present."""
        assert EscalationAction.RETRY == "retry"
        assert EscalationAction.REASSIGN == "reassign"
        assert EscalationAction.DECOMPOSE == "decompose"
        assert EscalationAction.REPORT_BLOCKER == "report_blocker"


class TestFailureDiagnosisDataclass:
    """Tests for the FailureDiagnosis dataclass."""

    def test_create_diagnosis(self) -> None:
        """FailureDiagnosis can be created with all fields."""
        diagnosis = FailureDiagnosis(
            error_pattern="test error",
            is_permanent=True,
            suggested_action=EscalationAction.REPORT_BLOCKER,
            diagnosis_detail="Repeated failure",
        )
        assert diagnosis.error_pattern == "test error"
        assert diagnosis.is_permanent is True
        assert diagnosis.suggested_action == EscalationAction.REPORT_BLOCKER
        assert diagnosis.diagnosis_detail == "Repeated failure"
