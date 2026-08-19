"""Tests for Budget Incidents, auto-pause, cancel-work hooks, and multi-metric support.

Covers:
- BudgetIncident creation on hard_stop
- auto_pause_callback invocation
- cancel_work_callback invocation
- Multi-metric tracking (cost_cents + tokens + api_calls)
- Lifetime window type
- Incident log retrieval
"""

import uuid
from unittest.mock import MagicMock

import pytest

from nexus.governance.budget_enforcer import (
    BudgetDecision,
    BudgetCheckResult,
    BudgetEnforcer,
    WindowKind,
)
from nexus.governance.budget_incident import BudgetIncident, BudgetIncidentLog


# ============================================================
# BudgetIncident Dataclass Tests
# ============================================================


class TestBudgetIncident:
    """Tests for the BudgetIncident dataclass."""

    def test_incident_has_all_fields(self):
        """BudgetIncident has all required fields with correct types."""
        agent_id = uuid.uuid4()
        scope_id = uuid.uuid4()

        incident = BudgetIncident(
            scope_type="agent",
            scope_id=scope_id,
            agent_id=agent_id,
            metric="cost_cents",
            threshold_amount=10000,
            actual_amount=10500,
            overage_amount=500,
            was_agent_paused=True,
        )

        assert isinstance(incident.id, uuid.UUID)
        assert incident.scope_type == "agent"
        assert incident.scope_id == scope_id
        assert incident.agent_id == agent_id
        assert incident.metric == "cost_cents"
        assert incident.threshold_amount == 10000
        assert incident.actual_amount == 10500
        assert incident.overage_amount == 500
        assert incident.was_agent_paused is True
        assert incident.created_at is not None

    def test_incident_defaults(self):
        """BudgetIncident has sensible defaults."""
        incident = BudgetIncident()

        assert isinstance(incident.id, uuid.UUID)
        assert incident.scope_type == ""
        assert incident.agent_id is None
        assert incident.metric == "cost_cents"
        assert incident.threshold_amount == 0
        assert incident.actual_amount == 0
        assert incident.overage_amount == 0
        assert incident.was_agent_paused is False

    def test_incident_supports_all_metrics(self):
        """BudgetIncident supports tokens and api_calls metrics."""
        token_incident = BudgetIncident(metric="tokens")
        api_incident = BudgetIncident(metric="api_calls")

        assert token_incident.metric == "tokens"
        assert api_incident.metric == "api_calls"


# ============================================================
# BudgetIncidentLog Tests
# ============================================================


class TestBudgetIncidentLog:
    """Tests for the BudgetIncidentLog storage."""

    def test_record_and_get_all(self):
        """record() stores incidents, get_all() retrieves them."""
        log = BudgetIncidentLog()
        incident1 = BudgetIncident(scope_type="agent", metric="cost_cents")
        incident2 = BudgetIncident(scope_type="company", metric="tokens")

        log.record(incident1)
        log.record(incident2)

        all_incidents = log.get_all()
        assert len(all_incidents) == 2
        # Most recent first
        assert all_incidents[0].scope_type == "company"
        assert all_incidents[1].scope_type == "agent"

    def test_get_by_scope(self):
        """get_by_scope() filters by scope_type and scope_id."""
        log = BudgetIncidentLog()
        scope_id_1 = uuid.uuid4()
        scope_id_2 = uuid.uuid4()

        log.record(BudgetIncident(scope_type="agent", scope_id=scope_id_1))
        log.record(BudgetIncident(scope_type="company", scope_id=scope_id_2))
        log.record(BudgetIncident(scope_type="agent", scope_id=scope_id_1))

        results = log.get_by_scope("agent", scope_id_1)
        assert len(results) == 2

    def test_get_by_agent(self):
        """get_by_agent() filters by agent_id."""
        log = BudgetIncidentLog()
        agent_id = uuid.uuid4()
        other_agent = uuid.uuid4()

        log.record(BudgetIncident(agent_id=agent_id))
        log.record(BudgetIncident(agent_id=other_agent))
        log.record(BudgetIncident(agent_id=agent_id))

        results = log.get_by_agent(agent_id)
        assert len(results) == 2

    def test_empty_log(self):
        """Empty log returns empty lists."""
        log = BudgetIncidentLog()

        assert log.get_all() == []
        assert log.get_by_scope("agent", uuid.uuid4()) == []
        assert log.get_by_agent(uuid.uuid4()) == []


# ============================================================
# Hard Stop + Incident Creation Tests
# ============================================================


class TestHardStopIncidentCreation:
    """Tests for incident creation when hard_stop is triggered."""

    def test_incident_created_on_hard_stop(self):
        """A BudgetIncident is created when budget is exceeded with hard_stop."""
        agent_id = uuid.uuid4()
        scope_id = uuid.uuid4()
        auto_pause = MagicMock()

        enforcer = BudgetEnforcer(
            auto_pause_callback=auto_pause,
            hard_stop_enabled=True,
        )
        enforcer.set_budget(
            "agent", scope_id, total_cents=1000, agent_id=agent_id
        )

        # Spend to exceed budget
        enforcer.on_cost_event("agent", scope_id, 800, "first call")
        decision = enforcer.on_cost_event(
            "agent", scope_id, 300, "over budget", agent_id=agent_id
        )

        assert decision == BudgetDecision.DENIED

        # Verify incident was created
        incidents = enforcer.incident_log.get_all()
        assert len(incidents) == 1
        incident = incidents[0]
        assert incident.scope_type == "agent"
        assert incident.scope_id == scope_id
        assert incident.agent_id == agent_id
        assert incident.metric == "cost_cents"
        assert incident.threshold_amount == 1000
        assert incident.actual_amount == 1100
        assert incident.overage_amount == 100
        assert incident.was_agent_paused is True

    def test_no_incident_when_hard_stop_disabled(self):
        """No incident when hard_stop is not enabled."""
        scope_id = uuid.uuid4()

        enforcer = BudgetEnforcer(hard_stop_enabled=False)
        enforcer.set_budget("agent", scope_id, total_cents=1000)

        # Exceed budget
        enforcer.on_cost_event("agent", scope_id, 1200, "over")

        incidents = enforcer.incident_log.get_all()
        assert len(incidents) == 0

    def test_incident_without_agent_id(self):
        """Incident created without agent_id when scope has no agent."""
        scope_id = uuid.uuid4()
        cancel_work = MagicMock()

        enforcer = BudgetEnforcer(
            cancel_work_callback=cancel_work,
            hard_stop_enabled=True,
        )
        enforcer.set_budget("company", scope_id, total_cents=500)

        enforcer.on_cost_event("company", scope_id, 600, "overspend")

        incidents = enforcer.incident_log.get_all()
        assert len(incidents) == 1
        assert incidents[0].agent_id is None
        assert incidents[0].was_agent_paused is False


# ============================================================
# Auto-Pause Callback Tests
# ============================================================


class TestAutoPauseCallback:
    """Tests for auto_pause_callback invocation on hard_stop."""

    def test_auto_pause_called_on_deny(self):
        """auto_pause_callback is invoked when budget is denied."""
        agent_id = uuid.uuid4()
        scope_id = uuid.uuid4()
        auto_pause = MagicMock()

        enforcer = BudgetEnforcer(
            auto_pause_callback=auto_pause,
            hard_stop_enabled=True,
        )
        enforcer.set_budget(
            "agent", scope_id, total_cents=500, agent_id=agent_id
        )

        enforcer.on_cost_event(
            "agent", scope_id, 600, "exceed", agent_id=agent_id
        )

        auto_pause.assert_called_once()
        call_args = auto_pause.call_args
        assert call_args[0][0] == agent_id
        assert isinstance(call_args[0][1], BudgetIncident)

    def test_auto_pause_not_called_when_allowed(self):
        """auto_pause_callback is not called for normal spending."""
        auto_pause = MagicMock()
        scope_id = uuid.uuid4()

        enforcer = BudgetEnforcer(
            auto_pause_callback=auto_pause,
            hard_stop_enabled=True,
        )
        enforcer.set_budget("agent", scope_id, total_cents=10000)

        enforcer.on_cost_event("agent", scope_id, 100, "small")

        auto_pause.assert_not_called()

    def test_auto_pause_not_called_without_agent_id(self):
        """auto_pause_callback is not called if no agent_id is available."""
        auto_pause = MagicMock()
        scope_id = uuid.uuid4()

        enforcer = BudgetEnforcer(
            auto_pause_callback=auto_pause,
            hard_stop_enabled=True,
        )
        enforcer.set_budget("company", scope_id, total_cents=500)

        enforcer.on_cost_event("company", scope_id, 600, "exceed")

        auto_pause.assert_not_called()

    def test_auto_pause_uses_scope_agent_mapping(self):
        """auto_pause_callback uses agent_id from set_budget if not in event."""
        agent_id = uuid.uuid4()
        scope_id = uuid.uuid4()
        auto_pause = MagicMock()

        enforcer = BudgetEnforcer(
            auto_pause_callback=auto_pause,
            hard_stop_enabled=True,
        )
        enforcer.set_budget(
            "agent", scope_id, total_cents=500, agent_id=agent_id
        )

        # No agent_id in the event call, but set_budget registered it
        enforcer.on_cost_event("agent", scope_id, 600, "exceed")

        auto_pause.assert_called_once()
        call_args = auto_pause.call_args
        assert call_args[0][0] == agent_id


# ============================================================
# Cancel Work Callback Tests
# ============================================================


class TestCancelWorkCallback:
    """Tests for cancel_work_callback invocation on hard_stop."""

    def test_cancel_work_called_on_deny(self):
        """cancel_work_callback is invoked when budget is denied."""
        scope_id = uuid.uuid4()
        cancel_work = MagicMock()

        enforcer = BudgetEnforcer(
            cancel_work_callback=cancel_work,
            hard_stop_enabled=True,
        )
        enforcer.set_budget("project", scope_id, total_cents=1000)

        enforcer.on_cost_event("project", scope_id, 1100, "over limit")

        cancel_work.assert_called_once_with("project", scope_id)

    def test_cancel_work_not_called_when_within_budget(self):
        """cancel_work_callback is not called for allowed spending."""
        cancel_work = MagicMock()
        scope_id = uuid.uuid4()

        enforcer = BudgetEnforcer(
            cancel_work_callback=cancel_work,
            hard_stop_enabled=True,
        )
        enforcer.set_budget("project", scope_id, total_cents=10000)

        enforcer.on_cost_event("project", scope_id, 100, "ok")

        cancel_work.assert_not_called()

    def test_cancel_work_called_without_auto_pause(self):
        """cancel_work_callback works independently of auto_pause_callback."""
        scope_id = uuid.uuid4()
        cancel_work = MagicMock()

        enforcer = BudgetEnforcer(
            cancel_work_callback=cancel_work,
            auto_pause_callback=None,
            hard_stop_enabled=True,
        )
        enforcer.set_budget("project", scope_id, total_cents=500)

        enforcer.on_cost_event("project", scope_id, 600, "exceed")

        cancel_work.assert_called_once_with("project", scope_id)


# ============================================================
# Multi-Metric Tracking Tests
# ============================================================


class TestMultiMetricTracking:
    """Tests for multi-metric tracking (cost_cents, tokens, api_calls)."""

    def test_track_all_metrics(self):
        """on_cost_event tracks cost_cents, tokens, and api_calls."""
        scope_id = uuid.uuid4()
        enforcer = BudgetEnforcer()
        enforcer.set_budget("agent", scope_id, total_cents=10000)

        enforcer.on_cost_event(
            "agent", scope_id, 100, "llm call",
            tokens=1500, api_calls=1,
        )

        metrics = enforcer.get_metrics("agent", scope_id)
        assert metrics["cost_cents"] == 100
        assert metrics["tokens"] == 1500
        assert metrics["api_calls"] == 1

    def test_metrics_accumulate(self):
        """Multiple events accumulate metric totals."""
        scope_id = uuid.uuid4()
        enforcer = BudgetEnforcer()
        enforcer.set_budget("agent", scope_id, total_cents=10000)

        enforcer.on_cost_event(
            "agent", scope_id, 50, "call 1", tokens=500, api_calls=1
        )
        enforcer.on_cost_event(
            "agent", scope_id, 75, "call 2", tokens=800, api_calls=1
        )

        metrics = enforcer.get_metrics("agent", scope_id)
        assert metrics["cost_cents"] == 125
        assert metrics["tokens"] == 1300
        assert metrics["api_calls"] == 2

    def test_token_budget_enforcement(self):
        """Token budget is enforced independently of cost budget."""
        scope_id = uuid.uuid4()
        cancel_work = MagicMock()

        enforcer = BudgetEnforcer(
            cancel_work_callback=cancel_work,
            hard_stop_enabled=True,
        )
        enforcer.set_budget("agent", scope_id, total_cents=100000)
        enforcer.set_budget(
            "agent", scope_id, total_cents=1000,
            metric="tokens",
        )

        # Cost is fine but tokens exceed
        decision = enforcer.on_cost_event(
            "agent", scope_id, 50, "big token call", tokens=1200, api_calls=1
        )

        assert decision == BudgetDecision.DENIED
        cancel_work.assert_called_once()

    def test_api_calls_budget_enforcement(self):
        """API calls budget is enforced independently."""
        scope_id = uuid.uuid4()
        cancel_work = MagicMock()

        enforcer = BudgetEnforcer(
            cancel_work_callback=cancel_work,
            hard_stop_enabled=True,
        )
        enforcer.set_budget("agent", scope_id, total_cents=100000)
        enforcer.set_budget(
            "agent", scope_id, total_cents=5,
            metric="api_calls",
        )

        # Make 6 calls
        for i in range(6):
            enforcer.on_cost_event(
                "agent", scope_id, 10, f"call {i}", api_calls=1
            )

        metrics = enforcer.get_metrics("agent", scope_id)
        assert metrics["api_calls"] == 6
        cancel_work.assert_called()

    def test_check_can_spend_with_token_metric(self):
        """check_can_spend works with tokens metric."""
        scope_id = uuid.uuid4()
        enforcer = BudgetEnforcer()
        enforcer.set_budget(
            "agent", scope_id, total_cents=5000, metric="tokens"
        )

        # Track some tokens
        enforcer.on_cost_event(
            "agent", scope_id, 0, "call", tokens=3000
        )

        result = enforcer.check_can_spend(
            "agent", scope_id, 3000, metric="tokens"
        )
        assert result.decision == BudgetDecision.DENIED

    def test_get_metrics_default_empty(self):
        """get_metrics returns zeros for unknown scope."""
        enforcer = BudgetEnforcer()
        metrics = enforcer.get_metrics("unknown", uuid.uuid4())
        assert metrics == {"cost_cents": 0, "tokens": 0, "api_calls": 0}


# ============================================================
# Lifetime Window Type Tests
# ============================================================


class TestLifetimeWindowType:
    """Tests for the lifetime window kind."""

    def test_lifetime_window_accumulates(self):
        """Lifetime window tracks cumulative spending without resets."""
        scope_id = uuid.uuid4()
        enforcer = BudgetEnforcer(hard_stop_enabled=True)
        enforcer.set_budget(
            "agent", scope_id, total_cents=5000,
            window_kind=WindowKind.LIFETIME,
        )

        # Simulate multiple periods of spending
        enforcer.on_cost_event("agent", scope_id, 1000, "month 1")
        enforcer.on_cost_event("agent", scope_id, 1500, "month 2")
        enforcer.on_cost_event("agent", scope_id, 2000, "month 3")

        remaining = enforcer.get_remaining_budget("agent", scope_id)
        assert remaining == 500  # 5000 - 4500

    def test_lifetime_window_kind_set(self):
        """WindowKind.LIFETIME is properly stored."""
        scope_id = uuid.uuid4()
        enforcer = BudgetEnforcer()
        enforcer.set_budget(
            "agent", scope_id, total_cents=10000,
            window_kind=WindowKind.LIFETIME,
        )

        assert enforcer._window_kinds[("agent", scope_id)] == WindowKind.LIFETIME

    def test_lifetime_budget_denied_when_exhausted(self):
        """Lifetime budget returns DENIED when fully exhausted."""
        scope_id = uuid.uuid4()
        cancel_work = MagicMock()

        enforcer = BudgetEnforcer(
            cancel_work_callback=cancel_work,
            hard_stop_enabled=True,
        )
        enforcer.set_budget(
            "agent", scope_id, total_cents=100,
            window_kind=WindowKind.LIFETIME,
        )

        decision = enforcer.on_cost_event("agent", scope_id, 150, "big spend")
        assert decision == BudgetDecision.DENIED
        cancel_work.assert_called_once()

    def test_window_kind_string_conversion(self):
        """set_budget accepts window_kind as string."""
        scope_id = uuid.uuid4()
        enforcer = BudgetEnforcer()
        enforcer.set_budget(
            "agent", scope_id, total_cents=10000,
            window_kind="lifetime",
        )

        assert enforcer._window_kinds[("agent", scope_id)] == WindowKind.LIFETIME

    def test_all_window_kinds_accepted(self):
        """All WindowKind values can be set."""
        enforcer = BudgetEnforcer()

        for kind in WindowKind:
            scope_id = uuid.uuid4()
            enforcer.set_budget(
                "agent", scope_id, total_cents=1000,
                window_kind=kind,
            )
            assert enforcer._window_kinds[("agent", scope_id)] == kind


# ============================================================
# WindowKind Enum Tests
# ============================================================


class TestWindowKind:
    """Tests for the WindowKind enum."""

    def test_enum_values(self):
        """WindowKind has all expected members."""
        assert WindowKind.MONTHLY == "monthly"
        assert WindowKind.WEEKLY == "weekly"
        assert WindowKind.DAILY == "daily"
        assert WindowKind.PER_EXECUTION == "per_execution"
        assert WindowKind.LIFETIME == "lifetime"

    def test_enum_from_string(self):
        """WindowKind can be constructed from string value."""
        assert WindowKind("monthly") == WindowKind.MONTHLY
        assert WindowKind("lifetime") == WindowKind.LIFETIME


# ============================================================
# Backward Compatibility Tests
# ============================================================


class TestBackwardCompatibility:
    """Tests ensuring existing API remains backward-compatible."""

    def test_set_budget_without_metric_or_window(self):
        """set_budget works without metric or window_kind params."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()

        enforcer.set_budget("agent", scope_id, total_cents=10000)

        remaining = enforcer.get_remaining_budget("agent", scope_id)
        assert remaining == 10000

    def test_check_can_spend_without_metric(self):
        """check_can_spend works without metric parameter."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, total_cents=10000)

        result = enforcer.check_can_spend("agent", scope_id, 5000)
        assert result.decision == BudgetDecision.ALLOWED

    def test_on_cost_event_without_extra_params(self):
        """on_cost_event works without tokens/api_calls params."""
        enforcer = BudgetEnforcer()
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, total_cents=10000)

        decision = enforcer.on_cost_event("agent", scope_id, 500, "test")
        assert decision == BudgetDecision.ALLOWED

    def test_enforcer_init_without_args(self):
        """BudgetEnforcer() works without any arguments."""
        enforcer = BudgetEnforcer()
        assert enforcer is not None
        assert enforcer._hard_stop_enabled is False
        assert enforcer._auto_pause_callback is None
        assert enforcer._cancel_work_callback is None
