"""Comprehensive tests for the ClosingTimeController module."""

import re

import pytest

from nexus.governance.control_registry import ControlRegistry
from nexus.runtime.closing_time import (
    ACK_RE,
    COMPLETE_RE,
    TEARDOWN_GRACE_SECONDS,
    TIMEOUT_SECONDS,
    ClosingTimeController,
    ClosingTimeEvent,
    ClosingTimePhase,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


class MessageLog:
    """Records sent messages for assertion."""

    def __init__(self) -> None:
        """Initialize an empty message log."""
        self.messages: list[tuple[str, str, str, str]] = []

    def send(self, to: str, act: str, subject: str, body: str) -> None:
        """Record a sent message."""
        self.messages.append((to, act, subject, body))


def _make_controller(
    live_agents: list[str] | None = None,
    god_id: str = "god",
    with_registry: bool = True,
) -> tuple[ClosingTimeController, MessageLog, list[bool], ControlRegistry | None]:
    """Create a controller with test doubles.

    Args:
        live_agents: List of agent IDs to return from get_live_agent_ids.
        god_id: The god agent ID.
        with_registry: Whether to include a ControlRegistry.

    Returns:
        Tuple of (controller, message_log, concluded_flags, registry).
    """
    if live_agents is None:
        live_agents = ["god", "worker-1", "worker-2"]

    msg_log = MessageLog()
    concluded: list[bool] = []
    registry = ControlRegistry() if with_registry else None

    # Mutable reference so tests can update live_agents dynamically.
    current_live = list(live_agents)

    def get_live() -> list[str]:
        return list(current_live)

    controller = ClosingTimeController(
        send_message=msg_log.send,
        get_live_agent_ids=get_live,
        on_concluded=lambda: concluded.append(True),
        control_registry=registry,
        god_id=god_id,
    )

    # Stash the mutable list on the controller for test manipulation.
    controller._live_ref = current_live  # type: ignore[attr-defined]

    return controller, msg_log, concluded, registry


# ── Test: Start Validation ───────────────────────────────────────────────────


class TestStart:
    """Tests for the start() method."""

    def test_start_with_no_live_god_returns_error(self):
        """start() returns an error when god is not in the live list."""
        ctrl, msg_log, concluded, _ = _make_controller(live_agents=["worker-1"])

        result = ctrl.start()

        assert result["ok"] is False
        assert "error" in result
        assert "orchestrator" in str(result["error"]).lower()
        assert ctrl.is_active() is False
        assert len(msg_log.messages) == 0

    def test_start_with_live_god_sends_brief_and_steers(self):
        """start() with a live god sends brief, steers agents, returns ok."""
        ctrl, msg_log, concluded, registry = _make_controller(
            live_agents=["god", "worker-1", "worker-2"]
        )

        result = ctrl.start()

        assert result == {"ok": True}
        assert ctrl.is_active() is True

        # Brief sent to god.
        assert len(msg_log.messages) == 1
        to, act, subject, body = msg_log.messages[0]
        assert to == "god"
        assert act == "request"
        assert "CLOSING TIME" in subject
        assert "worker-1" in body or "worker-2" in body

        # Workers tracked.
        assert ctrl.workers == {"worker-1", "worker-2"}
        assert ctrl.acked == set()

        # Events emitted.
        assert len(ctrl.events) == 1
        assert ctrl.events[0].phase == ClosingTimePhase.STARTED
        assert ctrl.events[0].total == 2
        assert ctrl.events[0].acked == 0

    def test_start_steers_god_and_workers_via_registry(self):
        """start() enqueues steer notes for god and all workers."""
        ctrl, msg_log, concluded, registry = _make_controller(
            live_agents=["god", "worker-1", "worker-2"]
        )
        assert registry is not None

        ctrl.start()

        # God should have a steer queued.
        god_steer = registry.take_steer("god")
        assert god_steer is not None
        assert "CLOSING TIME" in god_steer

        # Each worker should have a steer queued.
        w1_steer = registry.take_steer("worker-1")
        assert w1_steer is not None
        assert "CLOSING TIME" in w1_steer

        w2_steer = registry.take_steer("worker-2")
        assert w2_steer is not None
        assert "CLOSING TIME" in w2_steer

    def test_start_without_registry_still_works(self):
        """start() works fine when no control_registry is provided."""
        ctrl, msg_log, concluded, _ = _make_controller(
            live_agents=["god", "worker-1"], with_registry=False
        )

        result = ctrl.start()

        assert result == {"ok": True}
        assert ctrl.is_active() is True
        assert len(msg_log.messages) == 1

    def test_start_with_only_god_no_workers(self):
        """start() with only god live sets empty worker roster."""
        ctrl, msg_log, concluded, _ = _make_controller(live_agents=["god"])

        result = ctrl.start()

        assert result == {"ok": True}
        assert ctrl.workers == set()
        assert ctrl.events[0].total == 0


# ── Test: on_routed ACK Handling ─────────────────────────────────────────────


class TestOnRoutedAck:
    """Tests for ACK message handling in on_routed()."""

    def test_ack_from_known_worker_increments_acked(self):
        """ACK from a known worker adds it to the acked set."""
        ctrl, msg_log, concluded, _ = _make_controller()
        ctrl.start()
        msg_log.messages.clear()

        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])

        assert "worker-1" in ctrl.acked
        assert len(ctrl.acked) == 1
        # Progress event emitted.
        progress_events = [e for e in ctrl.events if e.phase == ClosingTimePhase.PROGRESS]
        assert len(progress_events) == 1
        assert progress_events[0].acked == 1
        assert progress_events[0].total == 2

    def test_ack_from_unknown_agent_ignored(self):
        """ACK from an agent not in the worker roster is ignored."""
        ctrl, msg_log, concluded, _ = _make_controller()
        ctrl.start()
        initial_event_count = len(ctrl.events)

        ctrl.on_routed("unknown-agent", "CLOSING-TIME-ACK", ["god"])

        assert "unknown-agent" not in ctrl.acked
        assert len(ctrl.events) == initial_event_count

    def test_ack_not_targeting_god_ignored(self):
        """ACK message not targeting god is ignored."""
        ctrl, msg_log, concluded, _ = _make_controller()
        ctrl.start()
        initial_event_count = len(ctrl.events)

        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["worker-2"])

        assert "worker-1" not in ctrl.acked
        assert len(ctrl.events) == initial_event_count

    def test_duplicate_ack_not_counted_twice(self):
        """Same worker ACKing twice does not double-count."""
        ctrl, msg_log, concluded, _ = _make_controller()
        ctrl.start()

        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])
        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])

        assert len(ctrl.acked) == 1
        # Only one PROGRESS event for duplicate.
        progress_events = [e for e in ctrl.events if e.phase == ClosingTimePhase.PROGRESS]
        assert len(progress_events) == 1

    def test_ack_when_not_active_ignored(self):
        """ACK messages are ignored when protocol is not active."""
        ctrl, msg_log, concluded, _ = _make_controller()
        # Not started.
        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])

        assert len(ctrl.acked) == 0
        assert len(ctrl.events) == 0


# ── Test: on_routed COMPLETE Handling ────────────────────────────────────────


class TestOnRoutedComplete:
    """Tests for COMPLETE message handling in on_routed()."""

    def test_complete_from_god_with_all_acks_triggers_concluded(self):
        """COMPLETE from god with all workers ACKed triggers teardown."""
        ctrl, msg_log, concluded, _ = _make_controller()
        ctrl.start()
        msg_log.messages.clear()

        # Both workers ACK.
        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])
        ctrl.on_routed("worker-2", "CLOSING-TIME-ACK", ["god"])

        # God sends COMPLETE.
        ctrl.on_routed("god", "CLOSING-TIME-COMPLETE", ["human"])

        # Concluded callback fired.
        assert len(concluded) == 1
        assert ctrl.is_active() is False

        # COMPLETE event emitted.
        complete_events = [e for e in ctrl.events if e.phase == ClosingTimePhase.COMPLETE]
        assert len(complete_events) == 1
        assert complete_events[0].acked == 2
        assert complete_events[0].total == 2

        # No refuse message sent.
        refuse_msgs = [m for m in msg_log.messages if m[1] == "refuse"]
        assert len(refuse_msgs) == 0

    def test_premature_complete_rejected_when_live_workers_missing_acks(self):
        """COMPLETE from god rejected when live workers have not ACKed."""
        ctrl, msg_log, concluded, _ = _make_controller()
        ctrl.start()
        msg_log.messages.clear()

        # Only worker-1 ACKs - worker-2 is still live but has not.
        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])

        # God tries COMPLETE prematurely.
        ctrl.on_routed("god", "CLOSING-TIME-COMPLETE", ["human"])

        # Concluded NOT called.
        assert len(concluded) == 0
        assert ctrl.is_active() is True

        # Refuse message sent to god.
        assert len(msg_log.messages) == 1
        to, act, subject, body = msg_log.messages[0]
        assert to == "god"
        assert act == "refuse"
        assert "rejected" in subject.lower()
        assert "worker-2" in body

        # PROGRESS event emitted (not COMPLETE).
        phases = [e.phase for e in ctrl.events]
        assert ClosingTimePhase.COMPLETE not in phases

    def test_dead_workers_excused_from_ack_requirement(self):
        """Workers no longer in the live list are excused from ACKing."""
        ctrl, msg_log, concluded, _ = _make_controller(
            live_agents=["god", "worker-1", "worker-2"]
        )
        ctrl.start()
        msg_log.messages.clear()

        # worker-1 ACKs.
        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])

        # worker-2 dies (remove from live list).
        ctrl._live_ref.remove("worker-2")  # type: ignore[attr-defined]

        # God sends COMPLETE - worker-2 is dead, so it's excused.
        ctrl.on_routed("god", "CLOSING-TIME-COMPLETE", ["human"])

        # Concluded fires because dead worker is excused.
        assert len(concluded) == 1
        assert ctrl.is_active() is False

    def test_complete_from_non_god_ignored(self):
        """COMPLETE message from a non-god agent is ignored."""
        ctrl, msg_log, concluded, _ = _make_controller()
        ctrl.start()

        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])
        ctrl.on_routed("worker-2", "CLOSING-TIME-ACK", ["god"])

        # Worker tries to send COMPLETE.
        ctrl.on_routed("worker-1", "CLOSING-TIME-COMPLETE", ["human"])

        assert len(concluded) == 0
        assert ctrl.is_active() is True

    def test_complete_with_no_workers_triggers_immediately(self):
        """COMPLETE with zero workers (just god) triggers concluded."""
        ctrl, msg_log, concluded, _ = _make_controller(live_agents=["god"])
        ctrl.start()
        msg_log.messages.clear()

        ctrl.on_routed("god", "CLOSING-TIME-COMPLETE", ["human"])

        assert len(concluded) == 1
        assert ctrl.is_active() is False


# ── Test: Cancel ─────────────────────────────────────────────────────────────


class TestCancel:
    """Tests for the cancel() method."""

    def test_cancel_clears_state_and_emits_cancelled(self):
        """cancel() sets active=False and emits CANCELLED event."""
        ctrl, msg_log, concluded, registry = _make_controller()
        ctrl.start()
        msg_log.messages.clear()

        ctrl.cancel()

        assert ctrl.is_active() is False

        # CANCELLED event emitted.
        cancelled_events = [
            e for e in ctrl.events if e.phase == ClosingTimePhase.CANCELLED
        ]
        assert len(cancelled_events) == 1

        # Cancellation notice sent to god.
        assert len(msg_log.messages) == 1
        to, act, subject, body = msg_log.messages[0]
        assert to == "god"
        assert act == "inform"
        assert "CANCELLED" in subject
        assert "cancelled" in body.lower()

    def test_cancel_clears_steers_via_registry(self):
        """cancel() clears pending steers for god and all workers."""
        ctrl, msg_log, concluded, registry = _make_controller()
        assert registry is not None
        ctrl.start()

        # Verify steers were queued.
        assert registry.snapshot("god").pending_steers >= 1

        ctrl.cancel()

        # Steers should be cleared.
        assert registry.take_steer("god") is None
        assert registry.take_steer("worker-1") is None
        assert registry.take_steer("worker-2") is None

    def test_cancel_when_not_active_is_noop(self):
        """cancel() does nothing if protocol is not active."""
        ctrl, msg_log, concluded, _ = _make_controller()

        ctrl.cancel()

        assert len(ctrl.events) == 0
        assert len(msg_log.messages) == 0

    def test_cancel_without_registry_still_works(self):
        """cancel() works when no control_registry is provided."""
        ctrl, msg_log, concluded, _ = _make_controller(
            live_agents=["god", "worker-1"], with_registry=False
        )
        ctrl.start()
        msg_log.messages.clear()

        ctrl.cancel()

        assert ctrl.is_active() is False
        assert len(msg_log.messages) == 1


# ── Test: Regex Patterns ─────────────────────────────────────────────────────


class TestRegexPatterns:
    """Tests for ACK_RE and COMPLETE_RE pattern matching."""

    @pytest.mark.parametrize(
        "subject",
        [
            "CLOSING-TIME-ACK",
            "closing-time-ack",
            "Closing Time Ack",
            "CLOSING_TIME_ACK",
            "closing_time_ack",
            "ClosingTimeAck",
            "CLOSING TIME ACK",
            "closing time ack",
            "Re: CLOSING-TIME-ACK from worker",
        ],
    )
    def test_ack_re_matches_variants(self, subject: str):
        """ACK_RE matches various case and separator combinations."""
        assert ACK_RE.search(subject) is not None

    @pytest.mark.parametrize(
        "subject",
        [
            "CLOSING-TIME-COMPLETE",
            "closing-time-complete",
            "Closing Time Complete",
            "CLOSING_TIME_COMPLETE",
            "closing_time_complete",
            "ClosingTimeComplete",
            "CLOSING TIME COMPLETE",
            "closing time complete",
        ],
    )
    def test_complete_re_matches_variants(self, subject: str):
        """COMPLETE_RE matches various case and separator combinations."""
        assert COMPLETE_RE.search(subject) is not None

    def test_ack_re_does_not_match_unrelated(self):
        """ACK_RE does not match unrelated subjects."""
        assert ACK_RE.search("Hello world") is None
        assert ACK_RE.search("CLOSING something ACK") is None

    def test_complete_re_does_not_match_unrelated(self):
        """COMPLETE_RE does not match unrelated subjects."""
        assert COMPLETE_RE.search("task complete") is None
        assert COMPLETE_RE.search("CLOSING something COMPLETE") is None


# ── Test: Protocol Phase Order ───────────────────────────────────────────────


class TestProtocolPhaseOrder:
    """Tests that protocol phases are emitted in correct order."""

    def test_full_protocol_phases_in_order(self):
        """Full happy-path: STARTED -> PROGRESS -> PROGRESS -> COMPLETE."""
        ctrl, msg_log, concluded, _ = _make_controller()
        ctrl.start()

        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])
        ctrl.on_routed("worker-2", "CLOSING-TIME-ACK", ["god"])
        ctrl.on_routed("god", "CLOSING-TIME-COMPLETE", ["human"])

        phases = [e.phase for e in ctrl.events]
        assert phases == [
            ClosingTimePhase.STARTED,
            ClosingTimePhase.PROGRESS,
            ClosingTimePhase.PROGRESS,
            ClosingTimePhase.COMPLETE,
        ]

    def test_cancelled_phase_after_start(self):
        """Cancel emits STARTED -> CANCELLED."""
        ctrl, msg_log, concluded, _ = _make_controller()
        ctrl.start()
        ctrl.cancel()

        phases = [e.phase for e in ctrl.events]
        assert phases == [ClosingTimePhase.STARTED, ClosingTimePhase.CANCELLED]


# ── Test: is_active State ────────────────────────────────────────────────────


class TestIsActive:
    """Tests for is_active() reflecting protocol state."""

    def test_is_active_false_before_start(self):
        """is_active() is False before start() is called."""
        ctrl, _, _, _ = _make_controller()
        assert ctrl.is_active() is False

    def test_is_active_true_after_start(self):
        """is_active() is True after start() succeeds."""
        ctrl, _, _, _ = _make_controller()
        ctrl.start()
        assert ctrl.is_active() is True

    def test_is_active_false_after_complete(self):
        """is_active() is False after COMPLETE is accepted."""
        ctrl, _, _, _ = _make_controller()
        ctrl.start()
        ctrl.on_routed("worker-1", "CLOSING-TIME-ACK", ["god"])
        ctrl.on_routed("worker-2", "CLOSING-TIME-ACK", ["god"])
        ctrl.on_routed("god", "CLOSING-TIME-COMPLETE", ["human"])
        assert ctrl.is_active() is False

    def test_is_active_false_after_cancel(self):
        """is_active() is False after cancel()."""
        ctrl, _, _, _ = _make_controller()
        ctrl.start()
        ctrl.cancel()
        assert ctrl.is_active() is False

    def test_is_active_remains_true_after_failed_start(self):
        """is_active() remains False when start() fails."""
        ctrl, _, _, _ = _make_controller(live_agents=["worker-1"])
        ctrl.start()
        assert ctrl.is_active() is False


# ── Test: Constants ──────────────────────────────────────────────────────────


class TestConstants:
    """Tests for module-level constants."""

    def test_timeout_seconds(self):
        """TIMEOUT_SECONDS is 360 (6 minutes)."""
        assert TIMEOUT_SECONDS == 360

    def test_teardown_grace_seconds(self):
        """TEARDOWN_GRACE_SECONDS is 2.5."""
        assert TEARDOWN_GRACE_SECONDS == 2.5

    def test_ack_re_is_compiled_pattern(self):
        """ACK_RE is a compiled regex pattern."""
        assert isinstance(ACK_RE, re.Pattern)

    def test_complete_re_is_compiled_pattern(self):
        """COMPLETE_RE is a compiled regex pattern."""
        assert isinstance(COMPLETE_RE, re.Pattern)


# ── Test: ClosingTimeEvent Dataclass ─────────────────────────────────────────


class TestClosingTimeEvent:
    """Tests for the ClosingTimeEvent dataclass."""

    def test_event_fields(self):
        """ClosingTimeEvent has correct fields."""
        event = ClosingTimeEvent(
            phase=ClosingTimePhase.STARTED, acked=0, total=3
        )
        assert event.phase == ClosingTimePhase.STARTED
        assert event.acked == 0
        assert event.total == 3

    def test_phase_enum_values(self):
        """ClosingTimePhase enum has expected string values."""
        assert ClosingTimePhase.STARTED.value == "started"
        assert ClosingTimePhase.PROGRESS.value == "progress"
        assert ClosingTimePhase.COMPLETE.value == "complete"
        assert ClosingTimePhase.TIMEOUT.value == "timeout"
        assert ClosingTimePhase.CANCELLED.value == "cancelled"
