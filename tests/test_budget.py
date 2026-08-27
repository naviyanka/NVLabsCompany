"""Tests for BudgetEnforcer and CostTracker.

Tests real budget enforcement logic: threshold checks, spending limits,
and cost computation based on model pricing tables.
"""

import math
import uuid

from nexus.governance.budget_enforcer import (
    BudgetDecision,
    BudgetEnforcer,
)
from nexus.models_router.cost_tracker import CostTracker, InvocationRecord

# ============================================================
# BudgetEnforcer Tests
# ============================================================


class TestBudgetEnforcerSetup:
    """Tests for BudgetEnforcer initialization and setup."""

    def test_set_budget(self):
        """set_budget configures a budget allocation."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()

        enforcer.set_budget("agent", scope_id, total_cents=10000, warn_percent=80)

        remaining = enforcer.get_remaining_budget("agent", scope_id)
        assert remaining == 10000

    def test_no_budget_defaults_to_allowed(self):
        """Without a configured budget, spending is always allowed."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()

        result = enforcer.check_can_spend("agent", scope_id, 5000)

        assert result.decision == BudgetDecision.ALLOWED
        assert result.message == "No budget configured for this scope"


class TestBudgetEnforcerChecks:
    """Tests for budget check decision logic."""

    def test_check_within_budget_allowed(self):
        """Spending well within budget returns ALLOWED."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("company", scope_id, total_cents=10000, warn_percent=80)

        result = enforcer.check_can_spend("company", scope_id, 1000)

        assert result.decision == BudgetDecision.ALLOWED
        assert result.remaining_cents == 10000
        assert result.budget_total_cents == 10000
        assert result.spent_cents == 0
        assert "within budget" in result.message.lower()

    def test_check_at_warning_threshold(self):
        """Spending that crosses warning threshold returns WARNING."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, total_cents=10000, warn_percent=80)

        # Spend enough to be at exactly 80% after the proposed spend
        # Currently 0 spent, proposing 8000 -> 80% of 10000
        result = enforcer.check_can_spend("agent", scope_id, 8000)

        assert result.decision == BudgetDecision.WARNING
        assert "warning" in result.message.lower()

    def test_check_above_warning_threshold(self):
        """Spending above warning threshold returns WARNING."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, total_cents=10000, warn_percent=80)

        # Record some spending first
        enforcer.on_cost_event("agent", scope_id, 7000, "prior costs")

        # Now propose spending 1500 more (total would be 8500/10000 = 85%)
        result = enforcer.check_can_spend("agent", scope_id, 1500)

        assert result.decision == BudgetDecision.WARNING
        assert result.spent_cents == 7000

    def test_check_exceeds_hard_limit_denied(self):
        """Spending that exceeds remaining budget returns DENIED."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("project", scope_id, total_cents=5000, warn_percent=80)

        # Record some spending
        enforcer.on_cost_event("project", scope_id, 4000, "initial costs")

        # Try to spend more than remaining (5000 - 4000 = 1000 remaining)
        result = enforcer.check_can_spend("project", scope_id, 2000)

        assert result.decision == BudgetDecision.DENIED
        assert result.remaining_cents == 1000
        assert result.spent_cents == 4000
        assert "insufficient" in result.message.lower()

    def test_check_exact_budget_remaining(self):
        """Spending exactly the remaining budget is still allowed (at warning)."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, total_cents=1000, warn_percent=50)

        # Spend exactly remaining (will be 100% after, which is above 50% warn)
        result = enforcer.check_can_spend("agent", scope_id, 1000)

        # This should be WARNING since 1000/1000 = 100% > 50%
        assert result.decision == BudgetDecision.WARNING


class TestBudgetEnforcerCostEvents:
    """Tests for cost event recording and tracking."""

    def test_on_cost_event_updates_spent(self):
        """Recording a cost event increases spent counter."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, total_cents=10000)

        enforcer.on_cost_event("agent", scope_id, 500, "LLM call")
        enforcer.on_cost_event("agent", scope_id, 300, "Tool use")

        remaining = enforcer.get_remaining_budget("agent", scope_id)
        assert remaining == 10000 - 500 - 300

    def test_get_cost_events_returns_recorded(self):
        """get_cost_events retrieves recorded events."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, total_cents=10000)

        enforcer.on_cost_event("agent", scope_id, 100, "test event 1")
        enforcer.on_cost_event("agent", scope_id, 200, "test event 2")

        events = enforcer.get_cost_events(scope_type="agent", scope_id=scope_id)
        assert len(events) == 2
        # Events are returned in reverse order (most recent first)
        assert events[0].amount_cents == 200
        assert events[1].amount_cents == 100

    def test_on_cost_event_returns_current_status(self):
        """on_cost_event returns the current budget decision."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, total_cents=1000, warn_percent=50)

        # Small spend (under 50%)
        decision = enforcer.on_cost_event("agent", scope_id, 100, "small")
        assert decision == BudgetDecision.ALLOWED

        # Push over warning threshold
        decision = enforcer.on_cost_event("agent", scope_id, 500, "medium")
        # Now at 600/1000 = 60% > 50% warning
        assert decision == BudgetDecision.WARNING


# ============================================================
# CostTracker Tests
# ============================================================


class TestCostTrackerPricing:
    """Tests for CostTracker cost computation."""

    def test_get_cost_for_known_model(self):
        """Known model pricing is applied correctly."""
        tracker = CostTracker()

        # gpt-4o: input=0.25, output=1.0 per 1000 tokens
        cost = tracker.get_cost_for_invocation(
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=1000,
        )

        # Expected: (1000/1000)*0.25 + (1000/1000)*1.0 = 1.25, ceil = 2 cents
        assert cost == math.ceil(0.25 + 1.0)

    def test_get_cost_for_unknown_model(self):
        """An unknown model falls through to the shared pricing table.

        It used to get a local default of 0.1/0.3 cents per 1K, which was
        cheaper than what the pre-flight budget guard charges for the same call,
        so a refused call could still be recorded as affordable. It now resolves
        through pricing.py, whose unknown-model fallback is Sonnet.
        """
        tracker = CostTracker()

        cost = tracker.get_cost_for_invocation(
            provider="custom",
            model="unknown-model-xyz",
            input_tokens=1000,
            output_tokens=1000,
        )

        # pricing.py's fallback is Sonnet at $3/M input, $15/M output:
        # 1000 tokens each is $0.003 + $0.015 = $0.018, or 1.8 cents, ceil = 2
        assert cost == 2

    def test_get_cost_for_free_model(self):
        """Local models (llama3, mistral) have zero cost."""
        tracker = CostTracker()

        cost = tracker.get_cost_for_invocation(
            provider="ollama",
            model="llama3",
            input_tokens=10000,
            output_tokens=5000,
        )

        assert cost == 0

    def test_cost_scales_with_tokens(self):
        """Cost increases with token count."""
        tracker = CostTracker()

        cost_small = tracker.get_cost_for_invocation(
            provider="openai", model="gpt-4o", input_tokens=100, output_tokens=50
        )
        cost_large = tracker.get_cost_for_invocation(
            provider="openai", model="gpt-4o", input_tokens=10000, output_tokens=5000
        )

        assert cost_large > cost_small


class TestCostTrackerRecording:
    """Tests for CostTracker invocation recording."""

    def test_record_invocation(self):
        """record_invocation stores a record with computed cost."""
        tracker = CostTracker()
        agent_id = uuid.uuid4()
        company_id = uuid.uuid4()

        record = tracker.record_invocation(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            input_tokens=2000,
            output_tokens=500,
            agent_id=agent_id,
            company_id=company_id,
        )

        assert isinstance(record, InvocationRecord)
        assert record.provider == "anthropic"
        assert record.model == "claude-sonnet-4-20250514"
        assert record.input_tokens == 2000
        assert record.output_tokens == 500
        assert record.cost_cents > 0
        assert record.agent_id == agent_id
        assert record.company_id == company_id

    def test_get_total_cost(self):
        """get_total_cost sums all recorded invocations."""
        tracker = CostTracker()
        company_id = uuid.uuid4()

        tracker.record_invocation(
            provider="openai", model="gpt-4o",
            input_tokens=1000, output_tokens=500, company_id=company_id
        )
        tracker.record_invocation(
            provider="openai", model="gpt-4o",
            input_tokens=2000, output_tokens=1000, company_id=company_id
        )

        total = tracker.get_total_cost(company_id=company_id)
        assert total > 0

    def test_get_total_cost_filters_by_agent(self):
        """get_total_cost can filter by agent_id."""
        tracker = CostTracker()
        agent_1 = uuid.uuid4()
        agent_2 = uuid.uuid4()

        tracker.record_invocation(
            provider="openai", model="gpt-4o",
            input_tokens=1000, output_tokens=500, agent_id=agent_1
        )
        tracker.record_invocation(
            provider="openai", model="gpt-4o",
            input_tokens=5000, output_tokens=3000, agent_id=agent_2
        )

        total_1 = tracker.get_total_cost(agent_id=agent_1)
        total_2 = tracker.get_total_cost(agent_id=agent_2)

        assert total_1 > 0
        assert total_2 > 0
        assert total_2 > total_1  # agent_2 used more tokens

    def test_update_pricing(self):
        """update_pricing changes cost calculation for a model."""
        tracker = CostTracker()

        # Update llama3 to have a cost
        tracker.update_pricing("llama3", input_price=0.01, output_price=0.02)

        cost = tracker.get_cost_for_invocation(
            provider="ollama", model="llama3",
            input_tokens=10000, output_tokens=5000
        )

        # (10000/1000)*0.01 + (5000/1000)*0.02 = 0.1 + 0.1 = 0.2, ceil = 1
        assert cost == math.ceil(0.1 + 0.1)
