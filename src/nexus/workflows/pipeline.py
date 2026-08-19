"""Pipeline Stages with Enforced Transitions.

Provides a multi-step workflow automation system with named stages,
valid transitions between them, cases that track progress, and a
hook system for stage entry/exit callbacks.

Key components:
- PipelineStage: A named stage with a kind and position in the pipeline.
- PipelineTransition: Defines a valid edge between two stages.
- PipelineCase: Tracks a single case moving through the pipeline.
- PipelineEngine: Orchestrates cases, enforces transitions, fires hooks.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable


class StageKind(str, Enum):
    """Classification of pipeline stages.

    Values:
        WORKING: Active work stage.
        REVIEW: Review/approval stage.
        DONE: Terminal success stage.
        CANCELLED: Terminal cancellation stage.
    """

    WORKING = "working"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class CaseStatus(str, Enum):
    """Lifecycle status of a pipeline case.

    Values:
        ACTIVE: Case is actively progressing through stages.
        COMPLETED: Case reached a 'done' stage.
        CANCELLED: Case reached a 'cancelled' stage.
    """

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InvalidTransitionError(Exception):
    """Raised when an invalid stage transition is attempted.

    Attributes:
        from_stage_id: The source stage of the attempted transition.
        to_stage_id: The target stage of the attempted transition.
        message: Human-readable description of the error.
    """

    def __init__(self, from_stage_id: str, to_stage_id: str, message: str) -> None:
        self.from_stage_id = from_stage_id
        self.to_stage_id = to_stage_id
        self.message = message
        super().__init__(message)


@dataclass
class PipelineStage:
    """A named stage in a pipeline.

    Attributes:
        id: Unique identifier for this stage.
        name: Human-readable stage name.
        kind: Classification of this stage (working, review, done, cancelled).
        position: Ordering position in the pipeline (0-based).
        config: Optional configuration dictionary for this stage.
    """

    id: str
    name: str
    kind: StageKind
    position: int
    config: dict = field(default_factory=dict)


@dataclass
class PipelineTransition:
    """Defines a valid edge between two pipeline stages.

    Attributes:
        from_stage_id: Source stage identifier.
        to_stage_id: Target stage identifier.
        condition: Optional condition expression for this transition.
    """

    from_stage_id: str
    to_stage_id: str
    condition: str | None = None


@dataclass
class TransitionRecord:
    """Record of a completed stage transition.

    Attributes:
        from_stage_id: Stage the case moved from.
        to_stage_id: Stage the case moved to.
        timestamp: When the transition occurred.
    """

    from_stage_id: str
    to_stage_id: str
    timestamp: datetime


@dataclass
class PipelineCase:
    """A case moving through a pipeline.

    Tracks current position, status, and full transition history.

    Attributes:
        id: Unique case identifier.
        pipeline_id: Identifier of the pipeline this case belongs to.
        current_stage_id: The stage the case is currently at.
        status: Current lifecycle status.
        history: Ordered list of all transitions this case has undergone.
        created_at: When the case was created.
        updated_at: When the case was last modified.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pipeline_id: str = ""
    current_stage_id: str = ""
    status: CaseStatus = CaseStatus.ACTIVE
    history: list[TransitionRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PipelineEngine:
    """Orchestrates pipeline cases through stages with enforced transitions.

    Manages a set of stages and valid transitions between them. Creates
    cases that start at the first stage (position 0) and advance through
    validated transitions. Supports hooks that fire on stage entry and exit.

    Example usage:
        stages = [
            PipelineStage(id="draft", name="Draft", kind=StageKind.WORKING, position=0),
            PipelineStage(id="review", name="Review", kind=StageKind.REVIEW, position=1),
            PipelineStage(id="done", name="Done", kind=StageKind.DONE, position=2),
        ]
        transitions = [
            PipelineTransition(from_stage_id="draft", to_stage_id="review"),
            PipelineTransition(from_stage_id="review", to_stage_id="done"),
        ]
        engine = PipelineEngine(stages, transitions)
        case = engine.create_case("pipeline-1")
        case = engine.advance_case(case, "review")
        case = engine.advance_case(case, "done")
    """

    def __init__(
        self,
        stages: list[PipelineStage],
        transitions: list[PipelineTransition],
    ) -> None:
        """Initialize the pipeline engine.

        Args:
            stages: List of pipeline stages.
            transitions: List of valid transitions between stages.
        """
        self._stages: dict[str, PipelineStage] = {s.id: s for s in stages}
        self._transitions = transitions
        # Index transitions by from_stage_id for fast lookup
        self._transition_index: dict[str, list[PipelineTransition]] = defaultdict(list)
        for t in transitions:
            self._transition_index[t.from_stage_id].append(t)
        # Hooks: stage_id -> event -> list of callbacks
        self._hooks: dict[str, dict[str, list[Callable]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def create_case(self, pipeline_id: str) -> PipelineCase:
        """Create a new case starting at the first stage (position 0).

        Args:
            pipeline_id: Identifier for the pipeline this case belongs to.

        Returns:
            A new PipelineCase positioned at the first stage.

        Raises:
            ValueError: If no stage with position 0 exists.
        """
        first_stage = self._get_first_stage()
        if first_stage is None:
            raise ValueError("No stage with position 0 found")

        now = datetime.now(timezone.utc)
        return PipelineCase(
            pipeline_id=pipeline_id,
            current_stage_id=first_stage.id,
            created_at=now,
            updated_at=now,
        )

    def advance_case(self, case: PipelineCase, target_stage_id: str) -> PipelineCase:
        """Move a case to a target stage, enforcing valid transitions.

        Validates that the transition is allowed, fires on_exit hooks for
        the current stage, moves the case, then fires on_enter hooks for
        the new stage. Updates case status based on the target stage kind.

        Args:
            case: The case to advance.
            target_stage_id: The stage to move the case to.

        Returns:
            The updated PipelineCase.

        Raises:
            InvalidTransitionError: If the transition is not valid.
        """
        if not self.validate_transition(case.current_stage_id, target_stage_id):
            raise InvalidTransitionError(
                from_stage_id=case.current_stage_id,
                to_stage_id=target_stage_id,
                message=(
                    f"No valid transition from '{case.current_stage_id}' "
                    f"to '{target_stage_id}'"
                ),
            )

        old_stage_id = case.current_stage_id
        old_stage = self._stages.get(old_stage_id)
        new_stage = self._stages.get(target_stage_id)

        # Fire on_exit hooks for old stage
        if old_stage is not None:
            self._fire_hooks(old_stage_id, "on_exit", case, old_stage)

        # Transition the case
        now = datetime.now(timezone.utc)
        record = TransitionRecord(
            from_stage_id=old_stage_id,
            to_stage_id=target_stage_id,
            timestamp=now,
        )
        case.history.append(record)
        case.current_stage_id = target_stage_id
        case.updated_at = now

        # Update status based on target stage kind
        if new_stage is not None:
            if new_stage.kind == StageKind.DONE:
                case.status = CaseStatus.COMPLETED
            elif new_stage.kind == StageKind.CANCELLED:
                case.status = CaseStatus.CANCELLED

        # Fire on_enter hooks for new stage
        if new_stage is not None:
            self._fire_hooks(target_stage_id, "on_enter", case, new_stage)

        return case

    def validate_transition(self, from_stage_id: str, to_stage_id: str) -> bool:
        """Check if a transition between two stages is valid.

        Args:
            from_stage_id: Source stage identifier.
            to_stage_id: Target stage identifier.

        Returns:
            True if the transition is defined, False otherwise.
        """
        for t in self._transition_index.get(from_stage_id, []):
            if t.to_stage_id == to_stage_id:
                return True
        return False

    def get_available_transitions(self, stage_id: str) -> list[PipelineTransition]:
        """Get all valid transitions from a given stage.

        Args:
            stage_id: The stage to get transitions from.

        Returns:
            List of PipelineTransition objects available from this stage.
        """
        return list(self._transition_index.get(stage_id, []))

    def register_hook(
        self,
        stage_id: str,
        event: str,
        callback: Callable,
    ) -> None:
        """Register a hook callback for a stage event.

        Args:
            stage_id: The stage to attach the hook to.
            event: The event type ('on_enter' or 'on_exit').
            callback: Function to call. Signature: (case, stage) -> None.
        """
        self._hooks[stage_id][event].append(callback)

    def get_stage(self, stage_id: str) -> PipelineStage | None:
        """Retrieve a stage by its identifier.

        Args:
            stage_id: The stage identifier to look up.

        Returns:
            The PipelineStage if found, None otherwise.
        """
        return self._stages.get(stage_id)

    def _get_first_stage(self) -> PipelineStage | None:
        """Find the stage with position 0.

        Returns:
            The first stage, or None if no stage has position 0.
        """
        for stage in self._stages.values():
            if stage.position == 0:
                return stage
        return None

    def _fire_hooks(
        self,
        stage_id: str,
        event: str,
        case: PipelineCase,
        stage: PipelineStage,
    ) -> None:
        """Fire all registered hooks for a stage event.

        Args:
            stage_id: The stage whose hooks to fire.
            event: The event type ('on_enter' or 'on_exit').
            case: The case being transitioned.
            stage: The stage being entered or exited.
        """
        for callback in self._hooks[stage_id][event]:
            callback(case, stage)
