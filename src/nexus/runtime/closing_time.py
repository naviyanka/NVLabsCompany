"""Closing Time Protocol - graceful, data-loss-free shutdown for multi-agent systems.

Ported from munder-difflin/src/main/closingTime.ts. Protocol phases:
STARTED -> PROGRESS -> COMPLETE -> teardown (or TIMEOUT/CANCELLED).

Manages ACK tracking from workers, premature COMPLETE rejection when live
workers are missing ACKs, dead worker exclusion, and steer-based interrupt
via ControlRegistry integration.

The protocol flow:
  1. start() sends a shutdown brief to the god agent and steers all live agents.
  2. Workers ACK by sending messages matching CLOSING-TIME-ACK to god.
  3. God confirms by sending CLOSING-TIME-COMPLETE.
  4. The controller verifies all live workers have ACKed, then triggers teardown.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from nexus.governance.control_registry import ControlRegistry


class ClosingTimePhase(StrEnum):
    """Protocol phases for the closing time shutdown sequence.

    Values:
        STARTED: Protocol initiated, brief sent to god agent.
        PROGRESS: One or more workers have ACKed or events are in flight.
        COMPLETE: All workers ACKed and god confirmed - teardown imminent.
        TIMEOUT: Protocol exceeded the allowed time window.
        CANCELLED: Human cancelled the shutdown.
    """

    STARTED = "started"
    PROGRESS = "progress"
    COMPLETE = "complete"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ClosingTimeEvent:
    """Event emitted during the closing time protocol.

    Attributes:
        phase: Current protocol phase.
        acked: Number of workers that have sent ACK so far.
        total: Total number of workers being waited on.
    """

    phase: ClosingTimePhase
    acked: int
    total: int


# Subject markers. Deliberately forgiving (case, -/_/space) because agents
# write these by hand, so "Closing Time Ack" counts as well as the canonical
# CLOSING-TIME-ACK the brief requests.
ACK_RE: re.Pattern[str] = re.compile(r"CLOSING[-_\s]*TIME[-_\s]*ACK", re.IGNORECASE)
COMPLETE_RE: re.Pattern[str] = re.compile(
    r"CLOSING[-_\s]*TIME[-_\s]*COMPLETE", re.IGNORECASE
)

# How long to wait before surfacing a timeout. Compaction or a long tool call
# can hold an ACK for several minutes. The runtime must call tick(now) periodically
# for this timeout to be enforced.
TIMEOUT_SECONDS: float = 360

# Grace period (seconds) after COMPLETE before the runtime should tear down.
# This is advisory: the integrating runtime is responsible for waiting this
# duration after on_concluded fires before killing processes, so final disk
# writes can land. The controller itself does not enforce the delay.
TEARDOWN_GRACE_SECONDS: float = 2.5


class ClosingTimeController:
    """Manages the graceful shutdown protocol for the multi-agent system.

    Coordinates the closing-time sequence: sends a shutdown brief to the god
    agent, tracks ACK messages from workers, rejects premature COMPLETE
    attempts, and triggers teardown once all live workers have confirmed.

    Constructor args:
        send_message: Callable (to, act, subject, body) to send a hive message.
        get_live_agent_ids: Callable returning currently live agent IDs.
        on_concluded: Callback invoked when shutdown is fully concluded.
        control_registry: Optional ControlRegistry for steer-based interrupt.
        god_id: ID of the god/orchestrator agent (default 'god').
    """

    def __init__(
        self,
        send_message: Callable[[str, str, str, str], None],
        get_live_agent_ids: Callable[[], list[str]],
        on_concluded: Callable[[], None],
        control_registry: ControlRegistry | None = None,
        god_id: str = "god",
    ) -> None:
        """Initialize the ClosingTimeController.

        Args:
            send_message: Callable (to, act, subject, body) to send hive messages.
            get_live_agent_ids: Callable returning list of currently live agent IDs.
            on_concluded: Callback invoked when teardown is triggered.
            control_registry: Optional ControlRegistry for steer injection.
            god_id: ID of the god/orchestrator agent.
        """
        self._send_message = send_message
        self._get_live_agent_ids = get_live_agent_ids
        self._on_concluded = on_concluded
        self._control_registry = control_registry
        self._god_id = god_id

        self._active: bool = False
        self._started_at: float | None = None
        self._workers: set[str] = set()
        self._acked: set[str] = set()
        self._events: list[ClosingTimeEvent] = []

    @property
    def events(self) -> list[ClosingTimeEvent]:
        """Return the list of emitted protocol events."""
        return self._events

    @property
    def workers(self) -> set[str]:
        """Return the set of worker agent IDs being waited on."""
        return self._workers

    @property
    def acked(self) -> set[str]:
        """Return the set of workers that have sent ACK."""
        return self._acked

    def is_active(self) -> bool:
        """Check if the closing time protocol is currently active.

        Returns:
            True if the protocol is running, False otherwise.
        """
        return self._active

    def start(self) -> dict[str, bool | str]:
        """Kick off the closing time protocol.

        Validates that the god agent is live, builds a worker roster from
        live agents excluding god, sends the shutdown brief to god, steers
        all agents, and emits a STARTED event.

        Returns:
            Dict with 'ok': True on success, or 'ok': False with 'error' string.
        """
        live = self._get_live_agent_ids()
        live_set = set(live)

        if self._god_id not in live_set:
            return {
                "ok": False,
                "error": (
                    "No orchestrator is running - closing time needs "
                    "the god agent to collect the reports."
                ),
            }

        # Build worker roster: live agents excluding god.
        self._workers = {agent_id for agent_id in live_set if agent_id != self._god_id}
        self._acked = set()
        self._active = True
        self._started_at = None  # Set by tick() on first call, or by caller

        # Send shutdown brief to god.
        worker_names = ", ".join(sorted(self._workers)) or "(none)"
        brief_body = (
            "The human pressed closing time: the harness will close as soon as "
            "you confirm the floor is safe. Run this protocol now:\n"
            "\n"
            f"1. BROADCAST closing time to the team. Current workers: {worker_names}.\n"
            "   Tell each worker to: park or commit WIP, append state + next steps "
            'to memory.md, reply with subject "CLOSING-TIME-ACK".\n'
            "2. WAIT until EVERY worker has sent its CLOSING-TIME-ACK.\n"
            "3. Save your own state: update board.md, append shift summary to memory.md.\n"
            '4. CONCLUDE by sending subject "CLOSING-TIME-COMPLETE" - the harness '
            "watches for it. Do not send before every worker has acked.\n"
            "\n"
            "This is a shutdown: do not start new work."
        )
        self._send_message(
            self._god_id,
            "request",
            "CLOSING TIME - run the shutdown protocol now",
            brief_body,
        )

        # Steer-based interrupt: reaches agents at their next hook boundary.
        if self._control_registry is not None:
            self._control_registry.steer(
                self._god_id,
                "CLOSING TIME was pressed by the human: pause your current work "
                "and drain your inbox NOW - a shutdown brief is waiting there.",
            )
            for worker_id in self._workers:
                self._control_registry.steer(
                    worker_id,
                    "CLOSING TIME - the office is shutting down. Finish your current "
                    "step but do NOT start new work. Park or commit WIP, append state "
                    "to memory.md, then reply to god with subject CLOSING-TIME-ACK.",
                )

        self._emit_event(ClosingTimePhase.STARTED)
        return {"ok": True}

    def on_routed(self, from_agent: str, subject: str, targets: list[str]) -> None:
        """Observe a routed message for closing time protocol markers.

        Called by the message router for every routed message. Checks for
        ACK messages from workers and COMPLETE messages from god.

        Args:
            from_agent: ID of the agent that sent the message.
            subject: Subject line of the message.
            targets: List of target agent IDs the message was routed to.
        """
        if not self._active:
            return

        # Worker ACK: counted only for known workers, only when god is a target.
        if (
            ACK_RE.search(subject)
            and from_agent in self._workers
            and self._god_id in targets
        ):
            if from_agent not in self._acked:
                self._acked.add(from_agent)
                self._emit_event(ClosingTimePhase.PROGRESS)
            return

        # God COMPLETE: only honored from the god agent itself.
        if COMPLETE_RE.search(subject) and from_agent == self._god_id:
            # Verify all live workers have ACKed. Dead workers are excused.
            live_now = set(self._get_live_agent_ids())
            pending = [
                worker_id
                for worker_id in self._workers
                if worker_id not in self._acked and worker_id in live_now
            ]

            if pending:
                # Premature COMPLETE - reject and inform god.
                pending_names = ", ".join(sorted(pending))
                self._send_message(
                    self._god_id,
                    "refuse",
                    "CLOSING TIME - conclusion rejected, workers still missing",
                    (
                        f"Still missing CLOSING-TIME-ACK from: {pending_names}.\n"
                        "The app stays open until every worker has confirmed.\n"
                        "Chase the stragglers, wait for ACKs, then send "
                        "CLOSING-TIME-COMPLETE again."
                    ),
                )
                self._emit_event(ClosingTimePhase.PROGRESS)
                return

            # All clear - emit COMPLETE and trigger teardown.
            self._emit_event(ClosingTimePhase.COMPLETE)
            self._active = False
            self._on_concluded()

    def tick(self, now: float) -> None:
        """Check whether the protocol has exceeded TIMEOUT_SECONDS.

        The runtime event loop should call this method periodically (e.g. every
        second) with the current monotonic time. On the first call after start(),
        the timestamp is recorded as the protocol start time. If elapsed time
        exceeds TIMEOUT_SECONDS, the controller emits a TIMEOUT phase event and
        deactivates the protocol.

        Args:
            now: Current monotonic timestamp (e.g. from time.monotonic()).
        """
        if not self._active:
            return

        if self._started_at is None:
            self._started_at = now
            return

        elapsed = now - self._started_at
        if elapsed >= TIMEOUT_SECONDS:
            self._active = False
            self._emit_event(ClosingTimePhase.TIMEOUT)

    def cancel(self) -> None:
        """Cancel the closing time protocol.

        Clears the active state, removes pending steers for all agents,
        emits a CANCELLED event, and informs god of the cancellation.
        """
        if not self._active:
            return

        self._active = False

        # Clear steers that no hook boundary has consumed yet.
        if self._control_registry is not None:
            self._control_registry.clear_steers(self._god_id)
            for worker_id in self._workers:
                self._control_registry.clear_steers(worker_id)

        self._emit_event(ClosingTimePhase.CANCELLED)

        self._send_message(
            self._god_id,
            "inform",
            "CLOSING TIME CANCELLED",
            "The human cancelled the shutdown - disregard the closing-time "
            "protocol and resume normal operation.",
        )

    def _emit_event(self, phase: ClosingTimePhase) -> None:
        """Create and record a protocol event.

        Args:
            phase: The protocol phase to emit.
        """
        event = ClosingTimeEvent(
            phase=phase,
            acked=len(self._acked),
            total=len(self._workers),
        )
        self._events.append(event)
