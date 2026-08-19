"""Replay Engine - reconstruct task execution timelines for debugging and audit.

Builds complete timelines with lifecycle events, delegation chains, cost
accumulation, and checkpoints. Allows post-mortem inspection of how a task
was executed: which agents handled it, how many retries occurred, total cost
incurred, and the full ordered sequence of events.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TimelineEventType(str, Enum):
    """Types of events that can occur in a task's timeline.

    Values:
        CREATED: Task was created.
        STARTED: Task execution began.
        DELEGATED: Task was delegated to another agent.
        RETRIED: Task execution was retried after failure.
        COMPLETED: Task finished successfully.
        FAILED: Task execution failed.
        ESCALATED: Task was escalated to a higher authority.
        CHECKPOINT: A progress checkpoint was recorded.
        COST_INCURRED: A cost was recorded against the task.
    """

    CREATED = "created"
    STARTED = "started"
    DELEGATED = "delegated"
    RETRIED = "retried"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    CHECKPOINT = "checkpoint"
    COST_INCURRED = "cost_incurred"


@dataclass
class TimelineEvent:
    """A single event in a task's execution timeline.

    Attributes:
        timestamp: When the event occurred.
        event_type: The type of timeline event.
        description: Human-readable description of what happened.
        agent_id: The agent involved in this event, if applicable.
        details: Flexible metadata dict for event-specific information.
        cost_cents: Cost in cents associated with this event.
    """

    timestamp: datetime
    event_type: TimelineEventType
    description: str
    agent_id: uuid.UUID | None = None
    details: dict[str, Any] = field(default_factory=dict)
    cost_cents: int = 0


@dataclass
class ReplayStats:
    """Computed statistics for a task's execution replay.

    Attributes:
        total_duration_seconds: Total wall-clock time from first to last event,
            or None if fewer than two events exist.
        total_cost_cents: Sum of all cost_cents across events.
        total_retries: Count of RETRIED events.
        delegation_depth: Number of unique agents involved in DELEGATED events.
        event_count: Total number of events in the timeline.
    """

    total_duration_seconds: float | None
    total_cost_cents: int
    total_retries: int
    delegation_depth: int
    event_count: int


@dataclass
class TaskReplay:
    """Complete replay of a task's execution timeline.

    Attributes:
        task_id: The task this replay represents.
        task_title: Human-readable title for the task.
        started_at: Timestamp of the first STARTED event, or None.
        completed_at: Timestamp of the first COMPLETED event, or None.
        timeline: Ordered list of timeline events (sorted by timestamp).
        stats: Computed statistics for this replay.
    """

    task_id: uuid.UUID
    task_title: str
    started_at: datetime | None
    completed_at: datetime | None
    timeline: list[TimelineEvent]
    stats: ReplayStats


class ReplayEngine:
    """Records and reconstructs task execution timelines.

    Stores events per task and provides methods to build complete replays,
    extract delegation chains, and compute cost breakdowns. Uses in-memory
    storage with a dict mapping task_id to a list of TimelineEvents.

    Example usage:
        engine = ReplayEngine()
        task_id = uuid.uuid4()
        engine.record_event(task_id, TimelineEventType.CREATED, "Task created")
        engine.record_event(task_id, TimelineEventType.STARTED, "Execution began")
        engine.record_event(
            task_id, TimelineEventType.COST_INCURRED,
            "LLM call", cost_cents=50,
        )
        replay = engine.get_replay(task_id)
    """

    def __init__(self) -> None:
        """Initialize the replay engine with empty event storage."""
        self._events: dict[uuid.UUID, list[TimelineEvent]] = {}

    def record_event(
        self,
        task_id: uuid.UUID,
        event_type: TimelineEventType,
        description: str,
        agent_id: uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
        cost_cents: int = 0,
    ) -> None:
        """Record a timeline event for a task.

        Creates a TimelineEvent with the current UTC timestamp and appends
        it to the task's event list.

        Args:
            task_id: The task to record the event against.
            event_type: The type of event being recorded.
            description: Human-readable description of the event.
            agent_id: The agent involved, if applicable.
            details: Optional metadata dict for additional context.
            cost_cents: Cost in cents associated with this event.
        """
        event = TimelineEvent(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            description=description,
            agent_id=agent_id,
            details=details if details is not None else {},
            cost_cents=cost_cents,
        )
        if task_id not in self._events:
            self._events[task_id] = []
        self._events[task_id].append(event)

    def get_replay(self, task_id: uuid.UUID) -> TaskReplay | None:
        """Build a complete TaskReplay for the given task.

        Sorts events by timestamp, computes stats (duration, cost, retries,
        delegation depth), and identifies start/completion times.

        Args:
            task_id: The task to build a replay for.

        Returns:
            A TaskReplay with the full ordered timeline and computed stats,
            or None if no events exist for the task.
        """
        events = self._events.get(task_id)
        if events is None:
            return None

        # Sort timeline by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        # Compute stats
        total_cost_cents = sum(e.cost_cents for e in sorted_events)
        total_retries = sum(
            1 for e in sorted_events if e.event_type == TimelineEventType.RETRIED
        )

        # Delegation depth: unique agents from DELEGATED events
        delegation_agents: list[uuid.UUID] = []
        for e in sorted_events:
            if e.event_type == TimelineEventType.DELEGATED and e.agent_id is not None:
                if e.agent_id not in delegation_agents:
                    delegation_agents.append(e.agent_id)
        delegation_depth = len(delegation_agents)

        # Duration: first event to last event
        total_duration_seconds: float | None = None
        if len(sorted_events) >= 2:
            delta = sorted_events[-1].timestamp - sorted_events[0].timestamp
            total_duration_seconds = delta.total_seconds()

        # Find started_at and completed_at
        started_at: datetime | None = None
        completed_at: datetime | None = None
        for e in sorted_events:
            if e.event_type == TimelineEventType.STARTED and started_at is None:
                started_at = e.timestamp
            if e.event_type == TimelineEventType.COMPLETED and completed_at is None:
                completed_at = e.timestamp

        stats = ReplayStats(
            total_duration_seconds=total_duration_seconds,
            total_cost_cents=total_cost_cents,
            total_retries=total_retries,
            delegation_depth=delegation_depth,
            event_count=len(sorted_events),
        )

        return TaskReplay(
            task_id=task_id,
            task_title="",
            started_at=started_at,
            completed_at=completed_at,
            timeline=sorted_events,
            stats=stats,
        )

    def get_delegation_chain(self, task_id: uuid.UUID) -> list[uuid.UUID]:
        """Extract the ordered delegation chain for a task.

        Returns unique agent IDs from DELEGATED events in the order they
        first appear in the timeline.

        Args:
            task_id: The task to get the delegation chain for.

        Returns:
            Ordered list of unique agent UUIDs from delegation events.
            Empty list if no events or no delegations exist.
        """
        events = self._events.get(task_id)
        if events is None:
            return []

        sorted_events = sorted(events, key=lambda e: e.timestamp)
        chain: list[uuid.UUID] = []
        for e in sorted_events:
            if e.event_type == TimelineEventType.DELEGATED and e.agent_id is not None:
                if e.agent_id not in chain:
                    chain.append(e.agent_id)
        return chain

    def get_cost_breakdown(self, task_id: uuid.UUID) -> list[tuple[str, int]]:
        """Get a cost breakdown for a task.

        Returns event description and cost for each COST_INCURRED event,
        ordered by timestamp.

        Args:
            task_id: The task to get the cost breakdown for.

        Returns:
            List of (description, cost_cents) tuples for cost events.
            Empty list if no events or no cost events exist.
        """
        events = self._events.get(task_id)
        if events is None:
            return []

        sorted_events = sorted(events, key=lambda e: e.timestamp)
        return [
            (e.description, e.cost_cents)
            for e in sorted_events
            if e.event_type == TimelineEventType.COST_INCURRED
        ]

    def list_tasks_with_events(self) -> list[uuid.UUID]:
        """List all task IDs that have recorded events.

        Returns:
            List of task UUIDs that have at least one event recorded.
        """
        return list(self._events.keys())
