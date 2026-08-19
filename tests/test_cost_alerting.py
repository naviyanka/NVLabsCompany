"""Tests for the Cost Alerting Service."""

import uuid

import pytest

from nexus.governance.budget_enforcer import BudgetEnforcer
from nexus.governance.cost_alerting import (
    AlertSeverity,
    AlertThreshold,
    CostAlert,
    CostAlertService,
)


@pytest.fixture
def enforcer() -> BudgetEnforcer:
    """Create a fresh BudgetEnforcer instance."""
    return BudgetEnforcer()


@pytest.fixture
def service(enforcer: BudgetEnforcer) -> CostAlertService:
    """Create a CostAlertService with a BudgetEnforcer."""
    return CostAlertService(enforcer)


class TestAlertThreshold:
    """Tests for AlertThreshold dataclass validation."""

    def test_valid_threshold(self) -> None:
        """Test creating a valid threshold."""
        t = AlertThreshold(warn_pct=70.0, critical_pct=90.0)
        assert t.warn_pct == 70.0
        assert t.critical_pct == 90.0

    def test_default_threshold(self) -> None:
        """Test default threshold values."""
        t = AlertThreshold()
        assert t.warn_pct == 80.0
        assert t.critical_pct == 95.0

    def test_invalid_warn_pct_zero(self) -> None:
        """Test that warn_pct at 0 raises ValueError."""
        with pytest.raises(ValueError, match="warn_pct"):
            AlertThreshold(warn_pct=0.0, critical_pct=90.0)

    def test_invalid_warn_pct_100(self) -> None:
        """Test that warn_pct at 100 raises ValueError."""
        with pytest.raises(ValueError, match="warn_pct"):
            AlertThreshold(warn_pct=100.0, critical_pct=100.0)

    def test_invalid_critical_pct_zero(self) -> None:
        """Test that critical_pct at 0 raises ValueError."""
        with pytest.raises(ValueError, match="critical_pct"):
            AlertThreshold(warn_pct=50.0, critical_pct=0.0)

    def test_warn_must_be_less_than_critical(self) -> None:
        """Test that warn_pct must be less than critical_pct."""
        with pytest.raises(ValueError, match="warn_pct must be less"):
            AlertThreshold(warn_pct=90.0, critical_pct=80.0)

    def test_warn_equal_critical_raises(self) -> None:
        """Test that warn_pct equal to critical_pct raises."""
        with pytest.raises(ValueError, match="warn_pct must be less"):
            AlertThreshold(warn_pct=80.0, critical_pct=80.0)


class TestCostAlert:
    """Tests for CostAlert dataclass."""

    def test_alert_creation(self) -> None:
        """Test creating a CostAlert with defaults."""
        alert = CostAlert()
        assert alert.id is not None
        assert alert.severity == AlertSeverity.WARNING
        assert alert.current_spend == 0
        assert alert.limit == 0

    def test_alert_with_values(self) -> None:
        """Test creating a CostAlert with specific values."""
        scope_id = uuid.uuid4()
        alert = CostAlert(
            agent_id="agent-1",
            scope=("agent", scope_id),
            current_spend=8500,
            limit=10000,
            severity=AlertSeverity.CRITICAL,
            message="Budget critical",
        )
        assert alert.agent_id == "agent-1"
        assert alert.scope == ("agent", scope_id)
        assert alert.current_spend == 8500
        assert alert.limit == 10000
        assert alert.severity == AlertSeverity.CRITICAL


class TestCostAlertService:
    """Tests for CostAlertService."""

    def test_no_alerts_when_under_threshold(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that no alerts fire when spending is below thresholds."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 500)

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        alerts = service.check_budgets()
        assert len(alerts) == 0

    def test_warning_alert_fired(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that a warning alert fires at warn_pct threshold."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 8500)

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        alerts = service.check_budgets()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING
        assert alerts[0].current_spend == 8500
        assert alerts[0].limit == 10000

    def test_critical_alert_fired(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that a critical alert fires at critical_pct threshold."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 9600)

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        alerts = service.check_budgets()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_callback_invoked(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that registered callbacks are invoked on alerts."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 8500)

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        received: list[CostAlert] = []
        service.register_callback(lambda a: received.append(a))

        service.check_budgets()
        assert len(received) == 1
        assert received[0].severity == AlertSeverity.WARNING

    def test_multiple_callbacks(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that multiple callbacks are all invoked."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 9000)

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        received_a: list[CostAlert] = []
        received_b: list[CostAlert] = []
        service.register_callback(lambda a: received_a.append(a))
        service.register_callback(lambda a: received_b.append(a))

        service.check_budgets()
        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_multiple_scopes(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test alerting across multiple budget scopes."""
        scope_a = uuid.uuid4()
        scope_b = uuid.uuid4()

        enforcer.set_budget("agent", scope_a, 10000)
        enforcer.set_budget("agent", scope_b, 5000)
        enforcer.on_cost_event("agent", scope_a, 8500)  # 85% - warning
        enforcer.on_cost_event("agent", scope_b, 1000)  # 20% - ok

        service.set_threshold(
            "agent", scope_a, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )
        service.set_threshold(
            "agent", scope_b, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        alerts = service.check_budgets()
        assert len(alerts) == 1
        assert alerts[0].scope == ("agent", scope_a)

    def test_no_budget_set_no_alert(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that scopes with no budget configured produce no alerts."""
        scope_id = uuid.uuid4()
        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        alerts = service.check_budgets()
        assert len(alerts) == 0

    def test_get_fired_alerts(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test retrieving all previously fired alerts."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 8500)

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        service.check_budgets()
        fired = service.get_fired_alerts()
        assert len(fired) == 1
        assert fired[0].severity == AlertSeverity.WARNING

    def test_alert_message_contains_scope_info(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that alert messages contain useful scope information."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 9600)

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        alerts = service.check_budgets()
        assert "CRITICAL" in alerts[0].message
        assert "agent" in alerts[0].message

    def test_agent_id_resolved_from_enforcer(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that agent_id is resolved from budget enforcer mapping."""
        scope_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        enforcer.set_budget(
            "agent", scope_id, 10000, agent_id=agent_id
        )
        enforcer.on_cost_event("agent", scope_id, 9000)

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        alerts = service.check_budgets()
        assert len(alerts) == 1
        assert alerts[0].agent_id == str(agent_id)

    def test_deduplication_suppresses_same_severity(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that repeated checks at same severity do not re-fire."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 8500)  # 85% - warning

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        # First check fires
        alerts = service.check_budgets()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING

        # Second check at same spend level does NOT re-fire
        alerts = service.check_budgets()
        assert len(alerts) == 0

    def test_deduplication_allows_escalation(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that escalation from WARNING to CRITICAL fires a new alert."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 8500)  # 85% - warning

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        # First check fires WARNING
        alerts = service.check_budgets()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING

        # Spend increases past critical
        enforcer.on_cost_event("agent", scope_id, 1200)  # now 9700 = 97%

        # Second check fires CRITICAL (escalation)
        alerts = service.check_budgets()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_deduplication_resets_when_below_threshold(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that severity resets when spending drops below threshold."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 8500)  # 85% - warning

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        # First check fires
        alerts = service.check_budgets()
        assert len(alerts) == 1

        # Budget increases (e.g., new allocation), spending now below threshold
        enforcer.set_budget("agent", scope_id, 20000)  # 8500/20000 = 42.5%

        # Check with spending below threshold - resets state
        alerts = service.check_budgets()
        assert len(alerts) == 0

        # Budget goes back to original, re-fires
        enforcer.set_budget("agent", scope_id, 10000)  # 8500/10000 = 85%
        alerts = service.check_budgets()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING

    def test_deduplication_critical_does_not_refire(
        self, enforcer: BudgetEnforcer, service: CostAlertService
    ) -> None:
        """Test that CRITICAL does not re-fire on repeated checks."""
        scope_id = uuid.uuid4()
        enforcer.set_budget("agent", scope_id, 10000)
        enforcer.on_cost_event("agent", scope_id, 9600)  # 96% - critical

        service.set_threshold(
            "agent", scope_id, AlertThreshold(warn_pct=80.0, critical_pct=95.0)
        )

        # First check fires CRITICAL
        alerts = service.check_budgets()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL

        # Second check does NOT re-fire
        alerts = service.check_budgets()
        assert len(alerts) == 0
