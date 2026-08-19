"""Tests for Pipeline Stages with Enforced Transitions."""

import pytest

from nexus.workflows.pipeline import (
    CaseStatus,
    InvalidTransitionError,
    PipelineCase,
    PipelineEngine,
    PipelineStage,
    PipelineTransition,
    StageKind,
    TransitionRecord,
)


@pytest.fixture
def stages() -> list[PipelineStage]:
    """Create a standard three-stage pipeline: working -> review -> done."""
    return [
        PipelineStage(id="draft", name="Draft", kind=StageKind.WORKING, position=0),
        PipelineStage(id="review", name="Review", kind=StageKind.REVIEW, position=1),
        PipelineStage(id="done", name="Done", kind=StageKind.DONE, position=2),
        PipelineStage(
            id="cancelled", name="Cancelled", kind=StageKind.CANCELLED, position=3
        ),
    ]


@pytest.fixture
def transitions() -> list[PipelineTransition]:
    """Define valid transitions for the standard pipeline."""
    return [
        PipelineTransition(from_stage_id="draft", to_stage_id="review"),
        PipelineTransition(from_stage_id="review", to_stage_id="done"),
        PipelineTransition(from_stage_id="review", to_stage_id="draft"),
        PipelineTransition(from_stage_id="draft", to_stage_id="cancelled"),
        PipelineTransition(from_stage_id="review", to_stage_id="cancelled"),
    ]


@pytest.fixture
def engine(
    stages: list[PipelineStage], transitions: list[PipelineTransition]
) -> PipelineEngine:
    """Create a PipelineEngine with standard stages and transitions."""
    return PipelineEngine(stages, transitions)


class TestPipelineCreation:
    """Tests for pipeline and case creation."""

    def test_create_pipeline_with_stages_and_transitions(
        self, stages: list[PipelineStage], transitions: list[PipelineTransition]
    ) -> None:
        """Create a pipeline engine with stages and transitions."""
        engine = PipelineEngine(stages, transitions)
        assert engine.get_stage("draft") is not None
        assert engine.get_stage("review") is not None
        assert engine.get_stage("done") is not None
        assert engine.get_stage("cancelled") is not None

    def test_create_case_starts_at_first_stage(self, engine: PipelineEngine) -> None:
        """create_case starts at the stage with position 0."""
        case = engine.create_case("pipeline-1")
        assert case.current_stage_id == "draft"
        assert case.pipeline_id == "pipeline-1"
        assert case.status == CaseStatus.ACTIVE
        assert case.history == []
        assert case.created_at is not None
        assert case.updated_at is not None

    def test_create_case_generates_unique_id(self, engine: PipelineEngine) -> None:
        """Each created case gets a unique identifier."""
        case1 = engine.create_case("pipeline-1")
        case2 = engine.create_case("pipeline-1")
        assert case1.id != case2.id


class TestAdvanceCase:
    """Tests for advancing cases through transitions."""

    def test_advance_case_moves_through_valid_transition(
        self, engine: PipelineEngine
    ) -> None:
        """advance_case moves the case to the target stage."""
        case = engine.create_case("pipeline-1")
        assert case.current_stage_id == "draft"

        case = engine.advance_case(case, "review")
        assert case.current_stage_id == "review"

    def test_advance_case_raises_for_invalid_transition(
        self, engine: PipelineEngine
    ) -> None:
        """advance_case raises InvalidTransitionError for invalid transitions."""
        case = engine.create_case("pipeline-1")
        # draft -> done is not a valid direct transition
        with pytest.raises(InvalidTransitionError) as exc_info:
            engine.advance_case(case, "done")

        assert exc_info.value.from_stage_id == "draft"
        assert exc_info.value.to_stage_id == "done"
        assert "draft" in exc_info.value.message
        assert "done" in exc_info.value.message

    def test_advance_case_raises_for_same_stage(
        self, engine: PipelineEngine
    ) -> None:
        """advance_case raises InvalidTransitionError when targeting current stage."""
        case = engine.create_case("pipeline-1")
        with pytest.raises(InvalidTransitionError):
            engine.advance_case(case, "draft")


class TestValidateTransition:
    """Tests for transition validation."""

    def test_validate_transition_returns_true_for_valid(
        self, engine: PipelineEngine
    ) -> None:
        """validate_transition returns True for a defined transition."""
        assert engine.validate_transition("draft", "review") is True
        assert engine.validate_transition("review", "done") is True

    def test_validate_transition_returns_false_for_invalid(
        self, engine: PipelineEngine
    ) -> None:
        """validate_transition returns False for an undefined transition."""
        assert engine.validate_transition("draft", "done") is False
        assert engine.validate_transition("done", "draft") is False
        assert engine.validate_transition("draft", "draft") is False


class TestGetAvailableTransitions:
    """Tests for getting available transitions from a stage."""

    def test_get_available_transitions_returns_valid_targets(
        self, engine: PipelineEngine
    ) -> None:
        """get_available_transitions returns all transitions from the given stage."""
        transitions = engine.get_available_transitions("draft")
        target_ids = [t.to_stage_id for t in transitions]
        assert "review" in target_ids
        assert "cancelled" in target_ids
        assert len(transitions) == 2

    def test_get_available_transitions_empty_for_terminal(
        self, engine: PipelineEngine
    ) -> None:
        """Terminal stages have no available transitions."""
        transitions = engine.get_available_transitions("done")
        assert transitions == []

    def test_get_available_transitions_for_review(
        self, engine: PipelineEngine
    ) -> None:
        """Review stage has transitions to done, draft, and cancelled."""
        transitions = engine.get_available_transitions("review")
        target_ids = [t.to_stage_id for t in transitions]
        assert "done" in target_ids
        assert "draft" in target_ids
        assert "cancelled" in target_ids
        assert len(transitions) == 3


class TestHooks:
    """Tests for the hook system."""

    def test_on_enter_hook_fires_when_entering_stage(
        self, engine: PipelineEngine
    ) -> None:
        """on_enter hook fires when a case enters the stage."""
        entered: list[tuple[PipelineCase, PipelineStage]] = []

        def on_enter_review(case: PipelineCase, stage: PipelineStage) -> None:
            entered.append((case, stage))

        engine.register_hook("review", "on_enter", on_enter_review)

        case = engine.create_case("pipeline-1")
        engine.advance_case(case, "review")

        assert len(entered) == 1
        assert entered[0][0] is case
        assert entered[0][1].id == "review"

    def test_on_exit_hook_fires_when_leaving_stage(
        self, engine: PipelineEngine
    ) -> None:
        """on_exit hook fires when a case leaves the stage."""
        exited: list[tuple[PipelineCase, PipelineStage]] = []

        def on_exit_draft(case: PipelineCase, stage: PipelineStage) -> None:
            exited.append((case, stage))

        engine.register_hook("draft", "on_exit", on_exit_draft)

        case = engine.create_case("pipeline-1")
        engine.advance_case(case, "review")

        assert len(exited) == 1
        assert exited[0][0] is case
        assert exited[0][1].id == "draft"

    def test_both_on_exit_and_on_enter_fire_during_advance(
        self, engine: PipelineEngine
    ) -> None:
        """Both on_exit and on_enter hooks fire during advance (exit old, enter new)."""
        events: list[str] = []

        def on_exit_draft(case: PipelineCase, stage: PipelineStage) -> None:
            events.append(f"exit:{stage.id}")

        def on_enter_review(case: PipelineCase, stage: PipelineStage) -> None:
            events.append(f"enter:{stage.id}")

        engine.register_hook("draft", "on_exit", on_exit_draft)
        engine.register_hook("review", "on_enter", on_enter_review)

        case = engine.create_case("pipeline-1")
        engine.advance_case(case, "review")

        assert events == ["exit:draft", "enter:review"]


class TestCaseHistory:
    """Tests for case transition history tracking."""

    def test_case_history_tracks_all_transitions(
        self, engine: PipelineEngine
    ) -> None:
        """Case history records all transitions with timestamps."""
        case = engine.create_case("pipeline-1")
        case = engine.advance_case(case, "review")
        case = engine.advance_case(case, "done")

        assert len(case.history) == 2

        first = case.history[0]
        assert first.from_stage_id == "draft"
        assert first.to_stage_id == "review"
        assert first.timestamp is not None

        second = case.history[1]
        assert second.from_stage_id == "review"
        assert second.to_stage_id == "done"
        assert second.timestamp is not None

        # Second transition happened at same time or later
        assert second.timestamp >= first.timestamp


class TestCaseStatus:
    """Tests for case status updates based on stage kind."""

    def test_case_status_completed_when_reaching_done_stage(
        self, engine: PipelineEngine
    ) -> None:
        """Case status set to completed when reaching a 'done' stage."""
        case = engine.create_case("pipeline-1")
        case = engine.advance_case(case, "review")
        assert case.status == CaseStatus.ACTIVE

        case = engine.advance_case(case, "done")
        assert case.status == CaseStatus.COMPLETED

    def test_case_status_cancelled_when_reaching_cancelled_stage(
        self, engine: PipelineEngine
    ) -> None:
        """Case status set to cancelled when reaching a 'cancelled' stage."""
        case = engine.create_case("pipeline-1")
        case = engine.advance_case(case, "cancelled")
        assert case.status == CaseStatus.CANCELLED


class TestFullLifecycle:
    """Full pipeline lifecycle integration test."""

    def test_full_pipeline_lifecycle_working_review_done(
        self, engine: PipelineEngine
    ) -> None:
        """Full lifecycle: working -> review -> done with hooks and history."""
        events: list[str] = []

        engine.register_hook(
            "draft", "on_exit", lambda c, s: events.append("exit:draft")
        )
        engine.register_hook(
            "review", "on_enter", lambda c, s: events.append("enter:review")
        )
        engine.register_hook(
            "review", "on_exit", lambda c, s: events.append("exit:review")
        )
        engine.register_hook(
            "done", "on_enter", lambda c, s: events.append("enter:done")
        )

        # Create case
        case = engine.create_case("my-pipeline")
        assert case.current_stage_id == "draft"
        assert case.status == CaseStatus.ACTIVE
        assert case.pipeline_id == "my-pipeline"

        # Move to review
        case = engine.advance_case(case, "review")
        assert case.current_stage_id == "review"
        assert case.status == CaseStatus.ACTIVE

        # Move to done
        case = engine.advance_case(case, "done")
        assert case.current_stage_id == "done"
        assert case.status == CaseStatus.COMPLETED

        # Verify hooks fired in order
        assert events == ["exit:draft", "enter:review", "exit:review", "enter:done"]

        # Verify history
        assert len(case.history) == 2
        assert case.history[0].from_stage_id == "draft"
        assert case.history[0].to_stage_id == "review"
        assert case.history[1].from_stage_id == "review"
        assert case.history[1].to_stage_id == "done"


class TestGetStage:
    """Tests for get_stage method."""

    def test_get_stage_returns_stage(self, engine: PipelineEngine) -> None:
        """get_stage returns the stage when it exists."""
        stage = engine.get_stage("draft")
        assert stage is not None
        assert stage.id == "draft"
        assert stage.name == "Draft"
        assert stage.kind == StageKind.WORKING
        assert stage.position == 0

    def test_get_stage_returns_none_for_unknown(
        self, engine: PipelineEngine
    ) -> None:
        """get_stage returns None for an unknown stage id."""
        assert engine.get_stage("nonexistent") is None
