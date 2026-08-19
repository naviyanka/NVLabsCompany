"""Phase Machine - team collaboration state machine for leader-driven workflows.

Implements the CREATE -> DESIGN -> EXECUTE -> COMPLETE lifecycle for team
collaboration, with transitions gated by plan detection, human approval,
result verification, and user feedback.
"""

import json
import os
import tempfile
import uuid
from enum import Enum
from pathlib import Path


class TeamPhase(str, Enum):
    """Lifecycle phases for team collaboration.

    Values:
        CREATE: Initial phase where the leader is generating ideas/output.
        DESIGN: Plan has been detected and is awaiting approval.
        EXECUTE: Plan approved, execution in progress.
        COMPLETE: Execution finished, results delivered.
    """

    CREATE = "create"
    DESIGN = "design"
    EXECUTE = "execute"
    COMPLETE = "complete"


class PhaseTransitionError(Exception):
    """Raised when an invalid phase transition is attempted.

    Attributes:
        current_phase: The phase the machine is currently in.
        attempted_phase: The phase that was attempted.
        leader_id: The leader whose phase transition failed.
    """

    def __init__(
        self,
        current_phase: TeamPhase,
        attempted_phase: TeamPhase,
        leader_id: uuid.UUID,
    ) -> None:
        self.current_phase = current_phase
        self.attempted_phase = attempted_phase
        self.leader_id = leader_id
        super().__init__(
            f"Invalid phase transition for leader {leader_id}: "
            f"{current_phase.value} -> {attempted_phase.value}"
        )


class PhaseMachine:
    """Tracks and enforces phase transitions per leader_id.

    Each leader has an independent phase state. The machine enforces
    the valid transition cycle:
        CREATE -> DESIGN -> EXECUTE -> COMPLETE -> CREATE (loop)

    Transitions are triggered by:
        - CREATE -> DESIGN: plan detection ([PLAN] marker in leader output)
        - DESIGN -> EXECUTE: explicit approve_plan call (human gate)
        - EXECUTE -> COMPLETE: check_final_result (task completed)
        - COMPLETE -> CREATE: handle_user_feedback (new iteration)

    Example usage:
        machine = PhaseMachine()
        leader_id = uuid.uuid4()
        machine.check_plan_detected(leader_id, "Here is my [PLAN] for the project")
        machine.approve_plan(leader_id)
        machine.check_final_result(leader_id, "Task completed successfully")
        machine.handle_user_feedback(leader_id, "Please iterate on this")
    """

    def __init__(self, persist_path: Path | None = None) -> None:
        """Initialize the phase machine with no tracked leaders.

        Args:
            persist_path: Optional path to a JSON file for persisting state.
                When provided, state is saved after every mutation and loaded
                on init if the file exists. When None, no persistence occurs.
        """
        self._persist_path = persist_path
        self._phases: dict[uuid.UUID, TeamPhase] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Atomically write current state to the persist file."""
        if self._persist_path is None:
            return
        data: dict[str, str] = {
            str(leader_id): phase.value
            for leader_id, phase in self._phases.items()
        }
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._persist_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._persist_path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _load(self) -> None:
        """Load state from the persist file if it exists."""
        if self._persist_path is None or not self._persist_path.exists():
            return
        with open(self._persist_path) as f:
            data: dict[str, str] = json.load(f)
        for leader_id_str, phase_value in data.items():
            self._phases[uuid.UUID(leader_id_str)] = TeamPhase(phase_value)

    def get_phase(self, leader_id: uuid.UUID) -> TeamPhase:
        """Get the current phase for a leader.

        Returns CREATE if the leader has not been seen before.

        Args:
            leader_id: The leader's unique identifier.

        Returns:
            The current TeamPhase for this leader.
        """
        return self._phases.get(leader_id, TeamPhase.CREATE)

    def get_all_phases(self) -> dict[uuid.UUID, TeamPhase]:
        """Get the current phase for all tracked leaders.

        Returns:
            Dictionary mapping leader_id to their current TeamPhase.
        """
        return dict(self._phases)

    def reset(self, leader_id: uuid.UUID | None = None) -> None:
        """Reset phase state.

        If leader_id is provided, resets only that leader to CREATE.
        If leader_id is None, clears all tracked leaders.

        Args:
            leader_id: Optional leader to reset. If None, resets all.
        """
        if leader_id is not None:
            self._phases.pop(leader_id, None)
        else:
            self._phases.clear()
        self._persist()

    def check_plan_detected(self, leader_id: uuid.UUID, leader_output: str) -> bool:
        """Check if a plan was detected in the leader's output.

        Looks for the [PLAN] marker in the output. If found and the leader
        is in CREATE phase, transitions to DESIGN.

        Args:
            leader_id: The leader's unique identifier.
            leader_output: The output text from the leader to check.

        Returns:
            True if a plan was detected and transition occurred.

        Raises:
            PhaseTransitionError: If the leader is not in CREATE phase
                but a [PLAN] marker is found.
        """
        if "[PLAN]" not in leader_output:
            return False

        current = self.get_phase(leader_id)
        if current != TeamPhase.CREATE:
            raise PhaseTransitionError(current, TeamPhase.DESIGN, leader_id)

        self._phases[leader_id] = TeamPhase.DESIGN
        self._persist()
        return True

    def approve_plan(self, leader_id: uuid.UUID) -> None:
        """Approve the current plan, transitioning from DESIGN to EXECUTE.

        This is the human gate - only an explicit approval call moves
        the workflow forward from the design phase.

        Args:
            leader_id: The leader's unique identifier.

        Raises:
            PhaseTransitionError: If the leader is not in DESIGN phase.
        """
        current = self.get_phase(leader_id)
        if current != TeamPhase.DESIGN:
            raise PhaseTransitionError(current, TeamPhase.EXECUTE, leader_id)

        self._phases[leader_id] = TeamPhase.EXECUTE
        self._persist()

    def check_final_result(self, leader_id: uuid.UUID, result: str = "") -> None:
        """Mark execution as complete.

        Transitions from EXECUTE to COMPLETE when the final result
        is available.

        Args:
            leader_id: The leader's unique identifier.
            result: The final result output (for logging/auditing).

        Raises:
            PhaseTransitionError: If the leader is not in EXECUTE phase.
        """
        current = self.get_phase(leader_id)
        if current != TeamPhase.EXECUTE:
            raise PhaseTransitionError(current, TeamPhase.COMPLETE, leader_id)

        self._phases[leader_id] = TeamPhase.COMPLETE
        self._persist()

    def handle_user_feedback(self, leader_id: uuid.UUID, feedback: str = "") -> None:
        """Handle user feedback, looping back to CREATE phase.

        Allows the workflow to iterate by returning to the creation
        phase after completion.

        Args:
            leader_id: The leader's unique identifier.
            feedback: The user's feedback text (for logging/auditing).

        Raises:
            PhaseTransitionError: If the leader is not in COMPLETE phase.
        """
        current = self.get_phase(leader_id)
        if current != TeamPhase.COMPLETE:
            raise PhaseTransitionError(current, TeamPhase.CREATE, leader_id)

        self._phases[leader_id] = TeamPhase.CREATE
        self._persist()
