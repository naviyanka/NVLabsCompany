"""Tests for the Replay Engine - timeline reconstruction for debugging and audit."""

import uuid
from datetime import datetime, timedelta, timezone

from nexus.runtime.replay import (
    ReplayEngine,
    ReplayStats,
    TaskReplay,
    TimelineEvent,
    TimelineEventType,
)


class TestEventRecording:
    """Tests for recording events into the replay engine."""

    def test_record_single_event(self) -> None:
        """A single event is stored and retrievable."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.CREATED, "Task created")

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert len(replay.timeline) == 1
        assert replay.timeline[0].event_type == TimelineEventType.CREATED
        assert replay.timeline[0].description == "Task created"

    def test_record_event_with_agent_id(self) -> None:
        """Events can include an agent_id."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()
        agent_id = uuid.uuid4()

        engine.record_event(
            task_id,
            TimelineEventType.DELEGATED,
            "Delegated to agent",
            agent_id=agent_id,
        )

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.timeline[0].agent_id == agent_id

    def test_record_event_with_details(self) -> None:
        """Events can include flexible metadata details."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()
        details = {"model": "gpt-4", "tokens": 1500}

        engine.record_event(
            task_id,
            TimelineEventType.CHECKPOINT,
            "Progress checkpoint",
            details=details,
        )

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.timeline[0].details == details

    def test_record_event_with_cost(self) -> None:
        """Events can include a cost in cents."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(
            task_id,
            TimelineEventType.COST_INCURRED,
            "LLM inference",
            cost_cents=75,
        )

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.timeline[0].cost_cents == 75

    def test_record_multiple_events(self) -> None:
        """Multiple events are all stored for the same task."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.CREATED, "Created")
        engine.record_event(task_id, TimelineEventType.STARTED, "Started")
        engine.record_event(task_id, TimelineEventType.COMPLETED, "Done")

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert len(replay.timeline) == 3

    def test_record_event_defaults(self) -> None:
        """Default values are applied when optional params are omitted."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.STARTED, "Started")

        replay = engine.get_replay(task_id)
        assert replay is not None
        event = replay.timeline[0]
        assert event.agent_id is None
        assert event.details == {}
        assert event.cost_cents == 0


class TestTimelineOrdering:
    """Tests for timeline ordering in get_replay."""

    def test_events_sorted_by_timestamp(self) -> None:
        """Timeline events are sorted by timestamp regardless of insertion order."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        # Manually create events with controlled timestamps
        now = datetime.now(timezone.utc)
        event_early = TimelineEvent(
            timestamp=now - timedelta(seconds=10),
            event_type=TimelineEventType.CREATED,
            description="First",
        )
        event_late = TimelineEvent(
            timestamp=now,
            event_type=TimelineEventType.COMPLETED,
            description="Last",
        )
        event_middle = TimelineEvent(
            timestamp=now - timedelta(seconds=5),
            event_type=TimelineEventType.STARTED,
            description="Middle",
        )

        # Insert out of order
        engine._events[task_id] = [event_late, event_early, event_middle]

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.timeline[0].description == "First"
        assert replay.timeline[1].description == "Middle"
        assert replay.timeline[2].description == "Last"


class TestReplayStats:
    """Tests for ReplayStats computation."""

    def test_total_duration_with_multiple_events(self) -> None:
        """Duration is computed from first to last event timestamp."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        now = datetime.now(timezone.utc)
        engine._events[task_id] = [
            TimelineEvent(
                timestamp=now,
                event_type=TimelineEventType.CREATED,
                description="Start",
            ),
            TimelineEvent(
                timestamp=now + timedelta(seconds=120),
                event_type=TimelineEventType.COMPLETED,
                description="End",
            ),
        ]

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.stats.total_duration_seconds == 120.0

    def test_total_duration_none_with_single_event(self) -> None:
        """Duration is None when fewer than two events exist."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.CREATED, "Only event")

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.stats.total_duration_seconds is None

    def test_total_cost_cents(self) -> None:
        """Total cost is the sum of all event costs."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(
            task_id, TimelineEventType.COST_INCURRED, "Call 1", cost_cents=50
        )
        engine.record_event(
            task_id, TimelineEventType.COST_INCURRED, "Call 2", cost_cents=30
        )
        engine.record_event(
            task_id, TimelineEventType.STARTED, "Started", cost_cents=0
        )

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.stats.total_cost_cents == 80

    def test_total_retries(self) -> None:
        """Total retries counts RETRIED events."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.STARTED, "Started")
        engine.record_event(task_id, TimelineEventType.RETRIED, "Retry 1")
        engine.record_event(task_id, TimelineEventType.RETRIED, "Retry 2")
        engine.record_event(task_id, TimelineEventType.COMPLETED, "Done")

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.stats.total_retries == 2

    def test_delegation_depth(self) -> None:
        """Delegation depth counts unique agents from DELEGATED events."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()

        engine.record_event(
            task_id, TimelineEventType.DELEGATED, "To A", agent_id=agent_a
        )
        engine.record_event(
            task_id, TimelineEventType.DELEGATED, "To B", agent_id=agent_b
        )
        # Duplicate delegation to A should not increase depth
        engine.record_event(
            task_id, TimelineEventType.DELEGATED, "Back to A", agent_id=agent_a
        )

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.stats.delegation_depth == 2

    def test_event_count(self) -> None:
        """Event count reflects total number of events."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.CREATED, "Created")
        engine.record_event(task_id, TimelineEventType.STARTED, "Started")

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.stats.event_count == 2

    def test_started_at_and_completed_at(self) -> None:
        """started_at and completed_at come from STARTED and COMPLETED events."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        now = datetime.now(timezone.utc)
        start_time = now
        complete_time = now + timedelta(seconds=60)

        engine._events[task_id] = [
            TimelineEvent(
                timestamp=now - timedelta(seconds=10),
                event_type=TimelineEventType.CREATED,
                description="Created",
            ),
            TimelineEvent(
                timestamp=start_time,
                event_type=TimelineEventType.STARTED,
                description="Started",
            ),
            TimelineEvent(
                timestamp=complete_time,
                event_type=TimelineEventType.COMPLETED,
                description="Completed",
            ),
        ]

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.started_at == start_time
        assert replay.completed_at == complete_time

    def test_started_at_none_when_no_started_event(self) -> None:
        """started_at is None if no STARTED event exists."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.CREATED, "Only created")

        replay = engine.get_replay(task_id)
        assert replay is not None
        assert replay.started_at is None
        assert replay.completed_at is None


class TestDelegationChain:
    """Tests for get_delegation_chain."""

    def test_delegation_chain_ordered(self) -> None:
        """Delegation chain returns agents in order of first appearance."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()
        agent_c = uuid.uuid4()

        now = datetime.now(timezone.utc)
        engine._events[task_id] = [
            TimelineEvent(
                timestamp=now,
                event_type=TimelineEventType.DELEGATED,
                description="To A",
                agent_id=agent_a,
            ),
            TimelineEvent(
                timestamp=now + timedelta(seconds=1),
                event_type=TimelineEventType.DELEGATED,
                description="To B",
                agent_id=agent_b,
            ),
            TimelineEvent(
                timestamp=now + timedelta(seconds=2),
                event_type=TimelineEventType.DELEGATED,
                description="To C",
                agent_id=agent_c,
            ),
        ]

        chain = engine.get_delegation_chain(task_id)
        assert chain == [agent_a, agent_b, agent_c]

    def test_delegation_chain_unique(self) -> None:
        """Delegation chain contains only unique agent IDs."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()

        engine.record_event(
            task_id, TimelineEventType.DELEGATED, "To A", agent_id=agent_a
        )
        engine.record_event(
            task_id, TimelineEventType.DELEGATED, "To B", agent_id=agent_b
        )
        engine.record_event(
            task_id, TimelineEventType.DELEGATED, "Back to A", agent_id=agent_a
        )

        chain = engine.get_delegation_chain(task_id)
        assert chain == [agent_a, agent_b]

    def test_delegation_chain_empty_no_events(self) -> None:
        """Empty list returned for a task with no events."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        chain = engine.get_delegation_chain(task_id)
        assert chain == []

    def test_delegation_chain_empty_no_delegations(self) -> None:
        """Empty list returned when no DELEGATED events exist."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.STARTED, "Started")
        engine.record_event(task_id, TimelineEventType.COMPLETED, "Done")

        chain = engine.get_delegation_chain(task_id)
        assert chain == []

    def test_delegation_chain_ignores_none_agent_id(self) -> None:
        """DELEGATED events without agent_id are excluded from chain."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()
        agent_a = uuid.uuid4()

        engine.record_event(
            task_id, TimelineEventType.DELEGATED, "No agent", agent_id=None
        )
        engine.record_event(
            task_id, TimelineEventType.DELEGATED, "To A", agent_id=agent_a
        )

        chain = engine.get_delegation_chain(task_id)
        assert chain == [agent_a]


class TestCostBreakdown:
    """Tests for get_cost_breakdown."""

    def test_cost_breakdown_returns_cost_events(self) -> None:
        """Cost breakdown lists all COST_INCURRED events with description and cost."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(
            task_id, TimelineEventType.COST_INCURRED, "LLM call", cost_cents=50
        )
        engine.record_event(
            task_id, TimelineEventType.COST_INCURRED, "Tool use", cost_cents=25
        )

        breakdown = engine.get_cost_breakdown(task_id)
        assert breakdown == [("LLM call", 50), ("Tool use", 25)]

    def test_cost_breakdown_excludes_non_cost_events(self) -> None:
        """Only COST_INCURRED events appear in the breakdown."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.STARTED, "Started", cost_cents=0)
        engine.record_event(
            task_id, TimelineEventType.COST_INCURRED, "API call", cost_cents=100
        )
        engine.record_event(
            task_id, TimelineEventType.COMPLETED, "Done", cost_cents=0
        )

        breakdown = engine.get_cost_breakdown(task_id)
        assert breakdown == [("API call", 100)]

    def test_cost_breakdown_empty_no_events(self) -> None:
        """Empty list returned for a task with no events."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        breakdown = engine.get_cost_breakdown(task_id)
        assert breakdown == []

    def test_cost_breakdown_empty_no_cost_events(self) -> None:
        """Empty list returned when no COST_INCURRED events exist."""
        engine = ReplayEngine()
        task_id = uuid.uuid4()

        engine.record_event(task_id, TimelineEventType.STARTED, "Started")

        breakdown = engine.get_cost_breakdown(task_id)
        assert breakdown == []


class TestEmptyTaskHandling:
    """Tests for handling tasks with no recorded events."""

    def test_get_replay_returns_none_for_unknown_task(self) -> None:
        """get_replay returns None for a task that has never had events recorded."""
        engine = ReplayEngine()
        unknown_id = uuid.uuid4()

        replay = engine.get_replay(unknown_id)
        assert replay is None

    def test_delegation_chain_empty_for_unknown_task(self) -> None:
        """get_delegation_chain returns empty list for unknown task."""
        engine = ReplayEngine()
        unknown_id = uuid.uuid4()

        chain = engine.get_delegation_chain(unknown_id)
        assert chain == []

    def test_cost_breakdown_empty_for_unknown_task(self) -> None:
        """get_cost_breakdown returns empty list for unknown task."""
        engine = ReplayEngine()
        unknown_id = uuid.uuid4()

        breakdown = engine.get_cost_breakdown(unknown_id)
        assert breakdown == []


class TestMultipleTasksIsolation:
    """Tests for isolation between multiple tasks."""

    def test_events_isolated_between_tasks(self) -> None:
        """Events recorded for one task do not appear in another task's replay."""
        engine = ReplayEngine()
        task_a = uuid.uuid4()
        task_b = uuid.uuid4()

        engine.record_event(task_a, TimelineEventType.CREATED, "Task A created")
        engine.record_event(task_b, TimelineEventType.CREATED, "Task B created")
        engine.record_event(task_a, TimelineEventType.STARTED, "Task A started")

        replay_a = engine.get_replay(task_a)
        replay_b = engine.get_replay(task_b)

        assert replay_a is not None
        assert replay_b is not None
        assert len(replay_a.timeline) == 2
        assert len(replay_b.timeline) == 1
        assert replay_a.timeline[0].description == "Task A created"
        assert replay_b.timeline[0].description == "Task B created"

    def test_costs_isolated_between_tasks(self) -> None:
        """Cost totals are computed independently per task."""
        engine = ReplayEngine()
        task_a = uuid.uuid4()
        task_b = uuid.uuid4()

        engine.record_event(
            task_a, TimelineEventType.COST_INCURRED, "Cost A", cost_cents=100
        )
        engine.record_event(
            task_b, TimelineEventType.COST_INCURRED, "Cost B", cost_cents=200
        )

        replay_a = engine.get_replay(task_a)
        replay_b = engine.get_replay(task_b)

        assert replay_a is not None
        assert replay_b is not None
        assert replay_a.stats.total_cost_cents == 100
        assert replay_b.stats.total_cost_cents == 200

    def test_delegation_chains_isolated(self) -> None:
        """Delegation chains are separate per task."""
        engine = ReplayEngine()
        task_a = uuid.uuid4()
        task_b = uuid.uuid4()
        agent_x = uuid.uuid4()
        agent_y = uuid.uuid4()

        engine.record_event(
            task_a, TimelineEventType.DELEGATED, "To X", agent_id=agent_x
        )
        engine.record_event(
            task_b, TimelineEventType.DELEGATED, "To Y", agent_id=agent_y
        )

        chain_a = engine.get_delegation_chain(task_a)
        chain_b = engine.get_delegation_chain(task_b)

        assert chain_a == [agent_x]
        assert chain_b == [agent_y]


class TestListTasksWithEvents:
    """Tests for list_tasks_with_events."""

    def test_list_empty_initially(self) -> None:
        """No tasks are listed when no events have been recorded."""
        engine = ReplayEngine()
        assert engine.list_tasks_with_events() == []

    def test_list_returns_all_tasks(self) -> None:
        """All tasks with events are listed."""
        engine = ReplayEngine()
        task_a = uuid.uuid4()
        task_b = uuid.uuid4()

        engine.record_event(task_a, TimelineEventType.CREATED, "A")
        engine.record_event(task_b, TimelineEventType.CREATED, "B")

        tasks = engine.list_tasks_with_events()
        assert set(tasks) == {task_a, task_b}
