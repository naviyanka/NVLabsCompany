"""Tests for the Phase Machine - team collaboration state machine."""

import uuid

import pytest

from nexus.orchestration.phase_machine import (
    PhaseMachine,
    PhaseTransitionError,
    TeamPhase,
)


@pytest.fixture
def machine() -> PhaseMachine:
    """Create a fresh PhaseMachine instance."""
    return PhaseMachine()


@pytest.fixture
def leader_id() -> uuid.UUID:
    """Create a test leader UUID."""
    return uuid.uuid4()


class TestTeamPhaseEnum:
    """Tests for the TeamPhase enum values."""

    def test_phase_values(self) -> None:
        """All expected phase values are present."""
        assert TeamPhase.CREATE == "create"
        assert TeamPhase.DESIGN == "design"
        assert TeamPhase.EXECUTE == "execute"
        assert TeamPhase.COMPLETE == "complete"


class TestGetPhase:
    """Tests for get_phase method."""

    def test_unknown_leader_returns_create(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """A leader not yet tracked defaults to CREATE."""
        assert machine.get_phase(leader_id) == TeamPhase.CREATE

    def test_returns_current_phase(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """Returns the actual current phase after a transition."""
        machine.check_plan_detected(leader_id, "Here is my [PLAN]")
        assert machine.get_phase(leader_id) == TeamPhase.DESIGN


class TestValidTransitions:
    """Tests for the full valid transition cycle."""

    def test_create_to_design_on_plan_detected(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """CREATE -> DESIGN when [PLAN] marker is found."""
        result = machine.check_plan_detected(leader_id, "Output with [PLAN] marker")
        assert result is True
        assert machine.get_phase(leader_id) == TeamPhase.DESIGN

    def test_design_to_execute_on_approve(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """DESIGN -> EXECUTE on explicit approve_plan call."""
        machine.check_plan_detected(leader_id, "[PLAN] something")
        machine.approve_plan(leader_id)
        assert machine.get_phase(leader_id) == TeamPhase.EXECUTE

    def test_execute_to_complete_on_final_result(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """EXECUTE -> COMPLETE on check_final_result."""
        machine.check_plan_detected(leader_id, "[PLAN]")
        machine.approve_plan(leader_id)
        machine.check_final_result(leader_id, "Done!")
        assert machine.get_phase(leader_id) == TeamPhase.COMPLETE

    def test_complete_to_create_on_feedback(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """COMPLETE -> CREATE on handle_user_feedback (loop)."""
        machine.check_plan_detected(leader_id, "[PLAN]")
        machine.approve_plan(leader_id)
        machine.check_final_result(leader_id)
        machine.handle_user_feedback(leader_id, "Please iterate")
        assert machine.get_phase(leader_id) == TeamPhase.CREATE

    def test_full_cycle_loops_back(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """Complete cycle returns to CREATE, allowing another iteration."""
        # First cycle
        machine.check_plan_detected(leader_id, "[PLAN] v1")
        machine.approve_plan(leader_id)
        machine.check_final_result(leader_id)
        machine.handle_user_feedback(leader_id, "Try again")

        # Second cycle starts from CREATE
        assert machine.get_phase(leader_id) == TeamPhase.CREATE
        result = machine.check_plan_detected(leader_id, "[PLAN] v2")
        assert result is True
        assert machine.get_phase(leader_id) == TeamPhase.DESIGN


class TestPlanDetection:
    """Tests for plan detection logic."""

    def test_no_plan_marker_returns_false(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """No [PLAN] marker means no transition."""
        result = machine.check_plan_detected(leader_id, "Just normal output")
        assert result is False
        assert machine.get_phase(leader_id) == TeamPhase.CREATE

    def test_plan_marker_in_middle_of_text(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """[PLAN] marker anywhere in text triggers transition."""
        result = machine.check_plan_detected(
            leader_id, "Before text [PLAN] after text"
        )
        assert result is True
        assert machine.get_phase(leader_id) == TeamPhase.DESIGN

    def test_plan_marker_case_sensitive(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """[PLAN] marker is case-sensitive."""
        result = machine.check_plan_detected(leader_id, "[plan] lowercase")
        assert result is False
        assert machine.get_phase(leader_id) == TeamPhase.CREATE


class TestInvalidTransitions:
    """Tests for invalid transition error handling."""

    def test_approve_from_create_raises(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """Cannot approve_plan when in CREATE phase."""
        with pytest.raises(PhaseTransitionError) as exc_info:
            machine.approve_plan(leader_id)
        assert exc_info.value.current_phase == TeamPhase.CREATE
        assert exc_info.value.attempted_phase == TeamPhase.EXECUTE

    def test_approve_from_execute_raises(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """Cannot approve_plan when in EXECUTE phase."""
        machine.check_plan_detected(leader_id, "[PLAN]")
        machine.approve_plan(leader_id)
        with pytest.raises(PhaseTransitionError) as exc_info:
            machine.approve_plan(leader_id)
        assert exc_info.value.current_phase == TeamPhase.EXECUTE

    def test_final_result_from_create_raises(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """Cannot check_final_result when in CREATE phase."""
        with pytest.raises(PhaseTransitionError) as exc_info:
            machine.check_final_result(leader_id)
        assert exc_info.value.current_phase == TeamPhase.CREATE
        assert exc_info.value.attempted_phase == TeamPhase.COMPLETE

    def test_feedback_from_create_raises(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """Cannot handle_user_feedback when in CREATE phase."""
        with pytest.raises(PhaseTransitionError) as exc_info:
            machine.handle_user_feedback(leader_id)
        assert exc_info.value.current_phase == TeamPhase.CREATE
        assert exc_info.value.attempted_phase == TeamPhase.CREATE

    def test_plan_detected_from_design_raises(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """Cannot detect [PLAN] again when already in DESIGN phase."""
        machine.check_plan_detected(leader_id, "[PLAN] first")
        with pytest.raises(PhaseTransitionError) as exc_info:
            machine.check_plan_detected(leader_id, "[PLAN] second")
        assert exc_info.value.current_phase == TeamPhase.DESIGN
        assert exc_info.value.attempted_phase == TeamPhase.DESIGN

    def test_error_message_is_descriptive(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """PhaseTransitionError has a descriptive message."""
        with pytest.raises(PhaseTransitionError) as exc_info:
            machine.approve_plan(leader_id)
        assert "create" in str(exc_info.value)
        assert "execute" in str(exc_info.value)
        assert str(leader_id) in str(exc_info.value)


class TestApprovalGate:
    """Tests for the approve_plan human gate."""

    def test_approve_only_from_design(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """approve_plan only works from DESIGN phase."""
        # Must first get to DESIGN
        machine.check_plan_detected(leader_id, "[PLAN]")
        # Now approve works
        machine.approve_plan(leader_id)
        assert machine.get_phase(leader_id) == TeamPhase.EXECUTE

    def test_cannot_skip_approval(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """Cannot jump from CREATE to EXECUTE without going through DESIGN."""
        with pytest.raises(PhaseTransitionError):
            machine.approve_plan(leader_id)


class TestReset:
    """Tests for the reset method."""

    def test_reset_specific_leader(
        self, machine: PhaseMachine, leader_id: uuid.UUID
    ) -> None:
        """Reset a specific leader back to CREATE."""
        machine.check_plan_detected(leader_id, "[PLAN]")
        assert machine.get_phase(leader_id) == TeamPhase.DESIGN
        machine.reset(leader_id)
        assert machine.get_phase(leader_id) == TeamPhase.CREATE

    def test_reset_all(self, machine: PhaseMachine) -> None:
        """Reset clears all tracked leaders."""
        leader1 = uuid.uuid4()
        leader2 = uuid.uuid4()
        machine.check_plan_detected(leader1, "[PLAN]")
        machine.check_plan_detected(leader2, "[PLAN]")
        machine.reset()
        assert machine.get_all_phases() == {}
        assert machine.get_phase(leader1) == TeamPhase.CREATE
        assert machine.get_phase(leader2) == TeamPhase.CREATE

    def test_reset_unknown_leader_is_safe(
        self, machine: PhaseMachine
    ) -> None:
        """Resetting an unknown leader does not raise."""
        machine.reset(uuid.uuid4())  # Should not raise


class TestGetAllPhases:
    """Tests for get_all_phases method."""

    def test_empty_initially(self, machine: PhaseMachine) -> None:
        """No phases tracked initially."""
        assert machine.get_all_phases() == {}

    def test_tracks_multiple_leaders(self, machine: PhaseMachine) -> None:
        """Multiple leaders are tracked independently."""
        leader1 = uuid.uuid4()
        leader2 = uuid.uuid4()
        machine.check_plan_detected(leader1, "[PLAN]")
        machine.check_plan_detected(leader2, "[PLAN]")
        machine.approve_plan(leader2)

        phases = machine.get_all_phases()
        assert phases[leader1] == TeamPhase.DESIGN
        assert phases[leader2] == TeamPhase.EXECUTE
