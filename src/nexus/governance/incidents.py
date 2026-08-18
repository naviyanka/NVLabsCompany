"""Incident Manager - Incident handling and response system.

Provides incident creation (auto-detect or manual), severity management,
response actions, timeline tracking, and post-incident analysis support.
Auto-creates incidents on critical governance events.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """Incident severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentStatus(str, Enum):
    """Incident lifecycle status."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"


@dataclass
class TimelineEvent:
    """A single event in an incident timeline.

    Attributes:
        id: Unique event identifier.
        timestamp: When the event occurred.
        event_type: Category of event (created, updated, action, note).
        description: Human-readable description.
        actor: Who performed the action.
        details: Additional context.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = ""
    description: str = ""
    actor: str = "system"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResponseAction:
    """An action taken in response to an incident.

    Attributes:
        id: Unique action identifier.
        action_type: Type of action (pause_agents, increase_logging, notify).
        description: Human-readable description.
        executed_at: When the action was executed.
        executed_by: Who executed the action.
        status: Action status (pending, executed, failed).
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    action_type: str = ""
    description: str = ""
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    executed_by: str = "system"
    status: str = "executed"


@dataclass
class IncidentData:
    """Full incident record.

    Attributes:
        id: Unique incident identifier.
        title: Short descriptive title.
        severity: Severity level.
        status: Current lifecycle status.
        created_at: When the incident was created.
        resolved_at: When the incident was resolved (if applicable).
        timeline: Ordered list of timeline events.
        actions: Response actions taken.
        rca: Root cause analysis (filled after resolution).
        company_id: Tenant scope.
        trigger: What triggered the incident (auto-detect source).
        description: Detailed description.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = ""
    severity: Severity = Severity.MEDIUM
    status: IncidentStatus = IncidentStatus.OPEN
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    timeline: list[TimelineEvent] = field(default_factory=list)
    actions: list[ResponseAction] = field(default_factory=list)
    rca: str = ""
    company_id: uuid.UUID | None = None
    trigger: str = ""
    description: str = ""


class IncidentManager:
    """Manages incident lifecycle from creation through resolution.

    Supports both manual incident creation and auto-detection from
    critical governance events (budget blow-up, kill switch activation,
    circuit breaker trips).
    """

    def __init__(self) -> None:
        """Initialize the incident manager."""
        self._incidents: dict[uuid.UUID, IncidentData] = {}

    def create_incident(
        self,
        title: str,
        severity: Severity,
        description: str = "",
        company_id: uuid.UUID | None = None,
        trigger: str = "manual",
    ) -> IncidentData:
        """Create a new incident.

        Args:
            title: Short descriptive title.
            severity: Severity level.
            description: Detailed description.
            company_id: Tenant scope.
            trigger: What triggered the incident.

        Returns:
            The created IncidentData.
        """
        incident = IncidentData(
            title=title,
            severity=severity,
            description=description,
            company_id=company_id,
            trigger=trigger,
        )

        # Add creation event to timeline
        event = TimelineEvent(
            event_type="created",
            description=f"Incident created: {title}",
            details={"severity": severity.value, "trigger": trigger},
        )
        incident.timeline.append(event)

        self._incidents[incident.id] = incident
        return incident

    def auto_detect_incident(
        self,
        event_type: str,
        details: dict[str, Any],
        company_id: uuid.UUID | None = None,
    ) -> IncidentData | None:
        """Auto-detect and create an incident from a governance event.

        Triggers on:
        - budget_exceeded: Budget blow-up
        - kill_switch_activated: Kill switch engagement
        - circuit_breaker_tripped: Circuit breaker opening

        Args:
            event_type: Type of governance event.
            details: Event details.
            company_id: Tenant scope.

        Returns:
            The created IncidentData, or None if event type is not recognized.
        """
        severity_map = {
            "budget_exceeded": Severity.HIGH,
            "kill_switch_activated": Severity.CRITICAL,
            "circuit_breaker_tripped": Severity.HIGH,
        }

        title_map = {
            "budget_exceeded": "Budget limit exceeded",
            "kill_switch_activated": "Kill switch activated",
            "circuit_breaker_tripped": "Circuit breaker tripped",
        }

        if event_type not in severity_map:
            return None

        severity = severity_map[event_type]
        title = title_map[event_type]
        description = details.get("reason", f"Auto-detected: {event_type}")

        incident = self.create_incident(
            title=title,
            severity=severity,
            description=description,
            company_id=company_id,
            trigger=event_type,
        )

        # Auto-add response actions based on severity
        if severity == Severity.CRITICAL:
            self.add_response_action(
                incident.id,
                action_type="pause_agents",
                description="Auto-pausing all agents due to critical incident",
            )
            self.add_response_action(
                incident.id,
                action_type="increase_logging",
                description="Increasing log verbosity for investigation",
            )
            self.add_response_action(
                incident.id,
                action_type="notify",
                description="Notifying on-call team of critical incident",
            )
        elif severity == Severity.HIGH:
            self.add_response_action(
                incident.id,
                action_type="increase_logging",
                description="Increasing log verbosity for investigation",
            )
            self.add_response_action(
                incident.id,
                action_type="notify",
                description="Notifying team of high-severity incident",
            )

        return incident

    def update_severity(
        self, incident_id: uuid.UUID, new_severity: Severity, reason: str = ""
    ) -> IncidentData | None:
        """Update the severity of an incident.

        Args:
            incident_id: The incident to update.
            new_severity: The new severity level.
            reason: Why the severity is being changed.

        Returns:
            The updated IncidentData, or None if not found.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            return None

        old_severity = incident.severity
        incident.severity = new_severity

        event = TimelineEvent(
            event_type="severity_changed",
            description=f"Severity changed from {old_severity.value} to {new_severity.value}",
            details={"old": old_severity.value, "new": new_severity.value, "reason": reason},
        )
        incident.timeline.append(event)

        return incident

    def add_timeline_event(
        self,
        incident_id: uuid.UUID,
        event_type: str,
        description: str,
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> TimelineEvent | None:
        """Add a timeline event to an incident.

        Args:
            incident_id: The incident to update.
            event_type: Category of event.
            description: Human-readable description.
            actor: Who is adding the event.
            details: Additional context.

        Returns:
            The created TimelineEvent, or None if incident not found.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            return None

        event = TimelineEvent(
            event_type=event_type,
            description=description,
            actor=actor,
            details=details or {},
        )
        incident.timeline.append(event)
        return event

    def add_response_action(
        self,
        incident_id: uuid.UUID,
        action_type: str,
        description: str,
        executed_by: str = "system",
    ) -> ResponseAction | None:
        """Add a response action to an incident.

        Supported action types: pause_agents, increase_logging, notify.

        Args:
            incident_id: The incident to update.
            action_type: Type of action.
            description: Human-readable description.
            executed_by: Who executed the action.

        Returns:
            The created ResponseAction, or None if incident not found.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            return None

        action = ResponseAction(
            action_type=action_type,
            description=description,
            executed_by=executed_by,
        )
        incident.actions.append(action)

        # Also add to timeline
        event = TimelineEvent(
            event_type="action",
            description=f"Response action: {action_type} - {description}",
            details={"action_type": action_type},
        )
        incident.timeline.append(event)

        return action

    def resolve_incident(
        self,
        incident_id: uuid.UUID,
        resolution_notes: str = "",
    ) -> IncidentData | None:
        """Resolve an incident.

        Args:
            incident_id: The incident to resolve.
            resolution_notes: Notes about the resolution.

        Returns:
            The updated IncidentData, or None if not found.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            return None

        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = datetime.now(timezone.utc)

        event = TimelineEvent(
            event_type="resolved",
            description=f"Incident resolved: {resolution_notes}",
            details={"resolution_notes": resolution_notes},
        )
        incident.timeline.append(event)

        return incident

    def record_rca(
        self, incident_id: uuid.UUID, rca: str
    ) -> IncidentData | None:
        """Record the root cause analysis for a resolved incident.

        Args:
            incident_id: The incident to update.
            rca: The root cause analysis text.

        Returns:
            The updated IncidentData, or None if not found.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            return None

        incident.rca = rca

        event = TimelineEvent(
            event_type="rca_recorded",
            description="Root cause analysis recorded",
            details={"rca_length": len(rca)},
        )
        incident.timeline.append(event)

        return incident

    def list_incidents(
        self,
        status: IncidentStatus | None = None,
        severity: Severity | None = None,
        company_id: uuid.UUID | None = None,
    ) -> list[IncidentData]:
        """List incidents with optional filters.

        Args:
            status: Filter by status.
            severity: Filter by severity.
            company_id: Filter by tenant.

        Returns:
            List of matching incidents.
        """
        results: list[IncidentData] = []
        for incident in self._incidents.values():
            if status is not None and incident.status != status:
                continue
            if severity is not None and incident.severity != severity:
                continue
            if company_id is not None and incident.company_id != company_id:
                continue
            results.append(incident)
        return results

    def get_incident(self, incident_id: uuid.UUID) -> IncidentData | None:
        """Get a single incident by ID.

        Args:
            incident_id: The incident to retrieve.

        Returns:
            The IncidentData, or None if not found.
        """
        return self._incidents.get(incident_id)

    def get_timeline(self, incident_id: uuid.UUID) -> list[TimelineEvent]:
        """Get the timeline for an incident.

        Args:
            incident_id: The incident to get timeline for.

        Returns:
            List of timeline events, or empty list if incident not found.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            return []
        return list(incident.timeline)
