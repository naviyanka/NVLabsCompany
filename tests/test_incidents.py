"""Tests for IncidentManager - Incident lifecycle and auto-detection.

Tests incident creation, status transitions, auto-detection from governance
events, timeline tracking, and severity management.
"""

import uuid

import pytest

from nexus.governance.incidents import (
    IncidentManager,
    IncidentData,
    IncidentStatus,
    Severity,
    TimelineEvent,
    ResponseAction,
)


class TestIncidentCreation:
    """Tests for incident creation."""

    def test_create_manual_incident(self):
        """Manual incident creation records all fields."""
        mgr = IncidentManager()
        incident = mgr.create_incident(
            title="Test incident",
            severity=Severity.HIGH,
            description="Something went wrong",
            company_id=uuid.uuid4(),
            trigger="manual",
        )

        assert incident.title == "Test incident"
        assert incident.severity == Severity.HIGH
        assert incident.status == IncidentStatus.OPEN
        assert incident.description == "Something went wrong"
        assert incident.trigger == "manual"
        assert len(incident.timeline) == 1
        assert incident.timeline[0].event_type == "created"

    def test_create_incident_generates_uuid(self):
        """Each incident gets a unique UUID."""
        mgr = IncidentManager()
        i1 = mgr.create_incident(title="A", severity=Severity.LOW)
        i2 = mgr.create_incident(title="B", severity=Severity.LOW)
        assert i1.id != i2.id

    def test_get_incident_by_id(self):
        """Incidents can be retrieved by ID."""
        mgr = IncidentManager()
        incident = mgr.create_incident(title="Find me", severity=Severity.MEDIUM)
        found = mgr.get_incident(incident.id)
        assert found is not None
        assert found.title == "Find me"

    def test_get_nonexistent_returns_none(self):
        """Getting a nonexistent incident returns None."""
        mgr = IncidentManager()
        assert mgr.get_incident(uuid.uuid4()) is None


class TestAutoDetection:
    """Tests for auto-detection of incidents from governance events."""

    def test_budget_exceeded_creates_high_incident(self):
        """Budget exceeded event creates a HIGH severity incident."""
        mgr = IncidentManager()
        incident = mgr.auto_detect_incident(
            event_type="budget_exceeded",
            details={"reason": "Monthly budget exceeded by 200%"},
            company_id=uuid.uuid4(),
        )

        assert incident is not None
        assert incident.severity == Severity.HIGH
        assert incident.trigger == "budget_exceeded"
        assert "Budget limit exceeded" in incident.title

    def test_kill_switch_creates_critical_incident(self):
        """Kill switch activation creates a CRITICAL severity incident."""
        mgr = IncidentManager()
        incident = mgr.auto_detect_incident(
            event_type="kill_switch_activated",
            details={"reason": "Emergency shutdown"},
        )

        assert incident is not None
        assert incident.severity == Severity.CRITICAL
        assert incident.trigger == "kill_switch_activated"

    def test_circuit_breaker_creates_high_incident(self):
        """Circuit breaker trip creates a HIGH severity incident."""
        mgr = IncidentManager()
        incident = mgr.auto_detect_incident(
            event_type="circuit_breaker_tripped",
            details={"reason": "Agent exceeded failure threshold"},
        )

        assert incident is not None
        assert incident.severity == Severity.HIGH
        assert incident.trigger == "circuit_breaker_tripped"

    def test_unknown_event_returns_none(self):
        """Unknown event types do not create incidents."""
        mgr = IncidentManager()
        result = mgr.auto_detect_incident(
            event_type="some_random_event",
            details={},
        )
        assert result is None

    def test_critical_auto_adds_response_actions(self):
        """Critical incidents automatically add response actions."""
        mgr = IncidentManager()
        incident = mgr.auto_detect_incident(
            event_type="kill_switch_activated",
            details={"reason": "Emergency"},
        )

        assert incident is not None
        action_types = [a.action_type for a in incident.actions]
        assert "pause_agents" in action_types
        assert "increase_logging" in action_types
        assert "notify" in action_types

    def test_high_auto_adds_logging_and_notify(self):
        """High severity incidents add logging and notify actions."""
        mgr = IncidentManager()
        incident = mgr.auto_detect_incident(
            event_type="budget_exceeded",
            details={"reason": "Over budget"},
        )

        assert incident is not None
        action_types = [a.action_type for a in incident.actions]
        assert "increase_logging" in action_types
        assert "notify" in action_types
        assert "pause_agents" not in action_types


class TestIncidentLifecycle:
    """Tests for incident lifecycle transitions."""

    def test_resolve_incident(self):
        """Resolving an incident updates status and records timestamp."""
        mgr = IncidentManager()
        incident = mgr.create_incident(title="Fix me", severity=Severity.MEDIUM)

        resolved = mgr.resolve_incident(incident.id, resolution_notes="Fixed the bug")

        assert resolved is not None
        assert resolved.status == IncidentStatus.RESOLVED
        assert resolved.resolved_at is not None

    def test_resolve_adds_timeline_event(self):
        """Resolution adds a timeline event."""
        mgr = IncidentManager()
        incident = mgr.create_incident(title="To resolve", severity=Severity.LOW)
        mgr.resolve_incident(incident.id, resolution_notes="Done")

        timeline = mgr.get_timeline(incident.id)
        event_types = [e.event_type for e in timeline]
        assert "resolved" in event_types

    def test_record_rca(self):
        """Root cause analysis can be recorded."""
        mgr = IncidentManager()
        incident = mgr.create_incident(title="RCA test", severity=Severity.HIGH)
        mgr.resolve_incident(incident.id)

        result = mgr.record_rca(incident.id, "Root cause was a misconfiguration")

        assert result is not None
        assert result.rca == "Root cause was a misconfiguration"

    def test_update_severity(self):
        """Severity can be updated with a reason."""
        mgr = IncidentManager()
        incident = mgr.create_incident(title="Escalate", severity=Severity.LOW)

        updated = mgr.update_severity(incident.id, Severity.CRITICAL, reason="Getting worse")

        assert updated is not None
        assert updated.severity == Severity.CRITICAL

    def test_severity_change_recorded_in_timeline(self):
        """Severity changes are recorded in the timeline."""
        mgr = IncidentManager()
        incident = mgr.create_incident(title="Track", severity=Severity.MEDIUM)
        mgr.update_severity(incident.id, Severity.HIGH)

        timeline = mgr.get_timeline(incident.id)
        severity_events = [e for e in timeline if e.event_type == "severity_changed"]
        assert len(severity_events) == 1
        assert severity_events[0].details["old"] == "medium"
        assert severity_events[0].details["new"] == "high"


class TestTimelineTracking:
    """Tests for incident timeline tracking."""

    def test_creation_event_in_timeline(self):
        """Incident creation is the first timeline event."""
        mgr = IncidentManager()
        incident = mgr.create_incident(title="Timeline test", severity=Severity.LOW)

        timeline = mgr.get_timeline(incident.id)
        assert len(timeline) >= 1
        assert timeline[0].event_type == "created"

    def test_add_custom_timeline_event(self):
        """Custom timeline events can be added."""
        mgr = IncidentManager()
        incident = mgr.create_incident(title="Custom events", severity=Severity.MEDIUM)

        event = mgr.add_timeline_event(
            incident.id,
            event_type="investigation",
            description="Started investigating root cause",
            actor="engineer-1",
        )

        assert event is not None
        assert event.event_type == "investigation"
        assert event.actor == "engineer-1"

        timeline = mgr.get_timeline(incident.id)
        assert len(timeline) == 2

    def test_response_action_adds_timeline_event(self):
        """Adding a response action also adds a timeline entry."""
        mgr = IncidentManager()
        incident = mgr.create_incident(title="Action test", severity=Severity.HIGH)

        mgr.add_response_action(
            incident.id,
            action_type="pause_agents",
            description="Pausing all agents",
        )

        timeline = mgr.get_timeline(incident.id)
        action_events = [e for e in timeline if e.event_type == "action"]
        assert len(action_events) == 1

    def test_timeline_for_nonexistent_incident(self):
        """Timeline for nonexistent incident returns empty list."""
        mgr = IncidentManager()
        timeline = mgr.get_timeline(uuid.uuid4())
        assert timeline == []


class TestIncidentListing:
    """Tests for incident listing and filtering."""

    def test_list_all_incidents(self):
        """All incidents can be listed."""
        mgr = IncidentManager()
        mgr.create_incident(title="A", severity=Severity.LOW)
        mgr.create_incident(title="B", severity=Severity.HIGH)

        incidents = mgr.list_incidents()
        assert len(incidents) == 2

    def test_filter_by_status(self):
        """Incidents can be filtered by status."""
        mgr = IncidentManager()
        i1 = mgr.create_incident(title="Open", severity=Severity.LOW)
        i2 = mgr.create_incident(title="Resolved", severity=Severity.LOW)
        mgr.resolve_incident(i2.id)

        open_incidents = mgr.list_incidents(status=IncidentStatus.OPEN)
        assert len(open_incidents) == 1
        assert open_incidents[0].title == "Open"

    def test_filter_by_severity(self):
        """Incidents can be filtered by severity."""
        mgr = IncidentManager()
        mgr.create_incident(title="Low", severity=Severity.LOW)
        mgr.create_incident(title="Critical", severity=Severity.CRITICAL)

        critical = mgr.list_incidents(severity=Severity.CRITICAL)
        assert len(critical) == 1
        assert critical[0].title == "Critical"

    def test_filter_by_company(self):
        """Incidents can be filtered by company_id."""
        mgr = IncidentManager()
        company_a = uuid.uuid4()
        company_b = uuid.uuid4()
        mgr.create_incident(title="A", severity=Severity.LOW, company_id=company_a)
        mgr.create_incident(title="B", severity=Severity.LOW, company_id=company_b)

        results = mgr.list_incidents(company_id=company_a)
        assert len(results) == 1
        assert results[0].title == "A"
