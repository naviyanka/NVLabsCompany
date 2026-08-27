"""Tests for pre-flight budget estimation (nexus.models_router.preflight)."""

import pytest

from nexus.models_router.preflight import (
    DEFAULT_OUTPUT_RESERVATION_TOKENS,
    BudgetExceededError,
    check_budget_preflight,
    estimate_min_call_cost,
)
from nexus.models_router.pricing import HAIKU, SONNET


class TestEstimateMinCallCost:
    """estimate_min_call_cost pricing behaviour."""

    def test_uses_model_family_price(self) -> None:
        """Input and output are priced from the resolved model family row."""
        cost = estimate_min_call_cost("claude-3-5-haiku-20241022", 1_000_000, 1_000_000)
        assert cost == pytest.approx(HAIKU.input_per_m + HAIKU.output_per_m)

    def test_unknown_model_falls_back_to_sonnet(self) -> None:
        """An unrecognised model id uses the default price row."""
        cost = estimate_min_call_cost("who-knows", 1_000_000, 0)
        assert cost == pytest.approx(SONNET.input_per_m)

    def test_default_output_reservation_when_max_output_none(self) -> None:
        """A non-empty prompt with no max_output reserves the default output size."""
        cost = estimate_min_call_cost("sonnet", 1000, None)
        expected = estimate_min_call_cost(
            "sonnet", 1000, DEFAULT_OUTPUT_RESERVATION_TOKENS
        )
        assert cost == pytest.approx(expected)
        assert cost > estimate_min_call_cost("sonnet", 1000, 0)

    def test_empty_prompt_reserves_nothing(self) -> None:
        """No prompt means no call, so the estimate is zero."""
        assert estimate_min_call_cost("sonnet", 0, None) == 0.0

    def test_explicit_zero_max_output_is_respected(self) -> None:
        """max_output=0 is not treated as None."""
        cost = estimate_min_call_cost("sonnet", 1_000_000, 0)
        assert cost == pytest.approx(SONNET.input_per_m)

    def test_negative_inputs_clamped(self) -> None:
        """Negative token counts clamp to zero rather than crediting cost."""
        assert estimate_min_call_cost("sonnet", -500, -500) == 0.0


class TestCheckBudgetPreflight:
    """check_budget_preflight refusal semantics."""

    def test_allows_call_within_limit(self) -> None:
        """A call that stays under the cap returns its estimate and does not raise."""
        estimate = check_budget_preflight("sonnet", 1000, spent_usd=0.0, limit_usd=100.0)
        assert estimate > 0

    def test_refuses_when_projected_reaches_limit(self) -> None:
        """spent + estimate >= limit raises BudgetExceededError before dispatch."""
        estimate = estimate_min_call_cost("sonnet", 100_000, 1000)
        with pytest.raises(BudgetExceededError) as exc:
            check_budget_preflight(
                "sonnet",
                100_000,
                spent_usd=1.0,
                limit_usd=1.0 + estimate,
                max_output=1000,
            )
        assert exc.value.estimate_usd == pytest.approx(estimate)
        assert exc.value.spent_usd == pytest.approx(1.0)

    def test_run_one_cent_under_cap_does_not_start_overrunning_call(self) -> None:
        """Phase 1.5 accept criterion: a nearly-exhausted run refuses dispatch."""
        # A call whose minimum estimate is well over one cent.
        prompt_tokens = 100_000
        estimate = estimate_min_call_cost("sonnet", prompt_tokens, 4096)
        assert estimate > 0.01
        with pytest.raises(BudgetExceededError):
            check_budget_preflight(
                "sonnet",
                prompt_tokens,
                spent_usd=0.99,
                limit_usd=1.00,
                max_output=4096,
            )

    def test_unlimited_when_limit_none_or_zero(self) -> None:
        """None and non-positive limits mean unlimited."""
        for limit in (None, 0.0, -1.0):
            estimate = check_budget_preflight(
                "sonnet", 100_000, spent_usd=999.0, limit_usd=limit
            )
            assert estimate > 0

    def test_warn_policy_allows_call(self) -> None:
        """on_budget_exceeded='warn' logs and lets the call through."""
        estimate = check_budget_preflight(
            "sonnet",
            100_000,
            spent_usd=999.0,
            limit_usd=1.0,
            on_budget_exceeded="warn",
        )
        assert estimate > 0

    def test_callable_policy_invoked_with_projection(self) -> None:
        """A callable policy receives (projected, limit) and suppresses the raise."""
        seen: list[tuple[float, float]] = []
        estimate = check_budget_preflight(
            "sonnet",
            100_000,
            spent_usd=5.0,
            limit_usd=1.0,
            on_budget_exceeded=lambda projected, limit: seen.append((projected, limit)),
        )
        assert len(seen) == 1
        projected, limit = seen[0]
        assert projected == pytest.approx(5.0 + estimate)
        assert limit == pytest.approx(1.0)

    def test_error_carries_model_and_limit(self) -> None:
        """The error exposes the fields a caller needs to report the refusal."""
        with pytest.raises(BudgetExceededError) as exc:
            check_budget_preflight("claude-opus-4", 100_000, spent_usd=10.0, limit_usd=1.0)
        assert exc.value.model == "claude-opus-4"
        assert exc.value.limit_usd == pytest.approx(1.0)
        assert "Budget exceeded before dispatch" in str(exc.value)


class TestPublicExports:
    """The package re-exports the pre-flight API."""

    def test_exported_from_models_router(self) -> None:
        """Phase 1.5 helpers are importable from the package root."""
        import nexus.models_router as mr

        assert mr.estimate_min_call_cost is estimate_min_call_cost
        assert mr.check_budget_preflight is check_budget_preflight
        assert mr.BudgetExceededError is BudgetExceededError
