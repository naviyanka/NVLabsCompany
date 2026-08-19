"""Tests for the OKR (Objectives and Key Results) Management System.

Validates Objective/KeyResult dataclasses, OKRManager CRUD operations,
progress computation, risk detection, and API route integration.
"""

import uuid
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

import pytest

from nexus.company.okr import KeyResult, Objective, OKRManager


@pytest.fixture
def manager():
    """Provide an OKRManager instance for tests."""
    return OKRManager(company_id=uuid.UUID("11111111-1111-1111-1111-111111111111"))


@pytest.fixture
def agent_id():
    """Provide a fixed agent UUID for tests."""
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


class TestKeyResult:
    """Tests for KeyResult dataclass."""

    def test_creation_defaults(self):
        """Test KeyResult creation with default values."""
        kr = KeyResult()
        assert isinstance(kr.id, uuid.UUID)
        assert isinstance(kr.objective_id, uuid.UUID)
        assert kr.title == ""
        assert kr.target_value == 100.0
        assert kr.current_value == 0.0
        assert kr.unit == "percent"
        assert kr.status == "on_track"
        assert isinstance(kr.updated_at, datetime)

    def test_creation_with_values(self):
        """Test KeyResult creation with explicit values."""
        obj_id = uuid.uuid4()
        kr = KeyResult(
            objective_id=obj_id,
            title="Increase revenue",
            target_value=500000.0,
            current_value=250000.0,
            unit="dollars",
            status="on_track",
        )
        assert kr.objective_id == obj_id
        assert kr.title == "Increase revenue"
        assert kr.target_value == 500000.0
        assert kr.current_value == 250000.0
        assert kr.unit == "dollars"


class TestObjective:
    """Tests for Objective dataclass."""

    def test_creation_defaults(self):
        """Test Objective creation with default values."""
        obj = Objective()
        assert isinstance(obj.id, uuid.UUID)
        assert obj.title == ""
        assert obj.description == ""
        assert isinstance(obj.owner_agent_id, uuid.UUID)
        assert obj.time_frame == "Q1 2025"
        assert obj.status == "active"
        assert obj.key_results == []
        assert isinstance(obj.created_at, datetime)

    def test_creation_with_values(self):
        """Test Objective creation with explicit values."""
        agent_id = uuid.uuid4()
        obj = Objective(
            title="Grow market share",
            description="Expand into new markets",
            owner_agent_id=agent_id,
            time_frame="H1 2025",
            status="active",
        )
        assert obj.title == "Grow market share"
        assert obj.description == "Expand into new markets"
        assert obj.owner_agent_id == agent_id
        assert obj.time_frame == "H1 2025"

    def test_key_results_list_independence(self):
        """Test that key_results lists are independent between instances."""
        obj1 = Objective(title="Obj 1")
        obj2 = Objective(title="Obj 2")
        kr = KeyResult(title="KR")
        obj1.key_results.append(kr)
        assert len(obj1.key_results) == 1
        assert len(obj2.key_results) == 0


class TestOKRManagerCreate:
    """Tests for OKRManager creation operations."""

    def test_create_objective(self, manager, agent_id):
        """Test creating a new objective."""
        obj = manager.create_objective(
            title="Improve platform reliability",
            description="Achieve 99.9% uptime",
            owner_agent_id=agent_id,
            time_frame="Q2 2025",
        )
        assert isinstance(obj, Objective)
        assert obj.title == "Improve platform reliability"
        assert obj.description == "Achieve 99.9% uptime"
        assert obj.owner_agent_id == agent_id
        assert obj.time_frame == "Q2 2025"
        assert obj.status == "active"

    def test_add_key_result(self, manager, agent_id):
        """Test adding a key result to an objective."""
        obj = manager.create_objective(
            title="Test obj", description="", owner_agent_id=agent_id
        )
        kr = manager.add_key_result(
            objective_id=obj.id,
            title="Reduce latency",
            target_value=100.0,
            unit="milliseconds",
        )
        assert isinstance(kr, KeyResult)
        assert kr.objective_id == obj.id
        assert kr.title == "Reduce latency"
        assert kr.target_value == 100.0
        assert kr.unit == "milliseconds"
        assert kr.current_value == 0.0

    def test_add_key_result_to_nonexistent_objective(self, manager):
        """Test that adding a KR to a missing objective raises KeyError."""
        fake_id = uuid.uuid4()
        with pytest.raises(KeyError, match=str(fake_id)):
            manager.add_key_result(
                objective_id=fake_id,
                title="Test KR",
                target_value=100.0,
            )


class TestOKRManagerProgress:
    """Tests for OKRManager progress operations."""

    def test_update_progress(self, manager, agent_id):
        """Test updating key result progress."""
        obj = manager.create_objective(
            title="Test", description="", owner_agent_id=agent_id
        )
        kr = manager.add_key_result(
            objective_id=obj.id, title="KR1", target_value=100.0
        )
        updated_kr = manager.update_progress(kr.id, 75.0)
        assert updated_kr.current_value == 75.0
        assert updated_kr.status == "on_track"  # 75% > 70%

    def test_update_progress_at_risk_status(self, manager, agent_id):
        """Test that progress between 30% and 70% sets status to at_risk."""
        obj = manager.create_objective(
            title="Test", description="", owner_agent_id=agent_id
        )
        kr = manager.add_key_result(
            objective_id=obj.id, title="KR1", target_value=100.0
        )
        updated_kr = manager.update_progress(kr.id, 40.0)
        assert updated_kr.status == "at_risk"

    def test_update_progress_behind_status(self, manager, agent_id):
        """Test that progress below 30% sets status to behind."""
        obj = manager.create_objective(
            title="Test", description="", owner_agent_id=agent_id
        )
        kr = manager.add_key_result(
            objective_id=obj.id, title="KR1", target_value=100.0
        )
        updated_kr = manager.update_progress(kr.id, 10.0)
        assert updated_kr.status == "behind"

    def test_update_progress_nonexistent_kr(self, manager):
        """Test updating progress on a nonexistent KR raises KeyError."""
        fake_id = uuid.uuid4()
        with pytest.raises(KeyError, match=str(fake_id)):
            manager.update_progress(fake_id, 50.0)

    def test_compute_objective_progress(self, manager, agent_id):
        """Test computing objective progress as weighted average."""
        obj = manager.create_objective(
            title="Multi-KR", description="", owner_agent_id=agent_id
        )
        kr1 = manager.add_key_result(
            objective_id=obj.id, title="KR1", target_value=100.0
        )
        kr2 = manager.add_key_result(
            objective_id=obj.id, title="KR2", target_value=200.0
        )
        manager.update_progress(kr1.id, 50.0)   # 50% progress
        manager.update_progress(kr2.id, 100.0)  # 50% progress

        progress = manager.compute_objective_progress(obj.id)
        assert progress == pytest.approx(0.5)  # (0.5 + 0.5) / 2

    def test_compute_progress_empty_key_results(self, manager, agent_id):
        """Test that progress is 0.0 when there are no key results."""
        obj = manager.create_objective(
            title="Empty", description="", owner_agent_id=agent_id
        )
        progress = manager.compute_objective_progress(obj.id)
        assert progress == 0.0

    def test_compute_progress_caps_at_one(self, manager, agent_id):
        """Test that individual KR progress is capped at 1.0."""
        obj = manager.create_objective(
            title="Capped", description="", owner_agent_id=agent_id
        )
        kr = manager.add_key_result(
            objective_id=obj.id, title="KR1", target_value=50.0
        )
        manager.update_progress(kr.id, 100.0)  # 200% but capped to 100%

        progress = manager.compute_objective_progress(obj.id)
        assert progress == pytest.approx(1.0)

    def test_compute_progress_nonexistent_objective(self, manager):
        """Test computing progress for missing objective raises KeyError."""
        with pytest.raises(KeyError):
            manager.compute_objective_progress(uuid.uuid4())


class TestOKRManagerQueries:
    """Tests for OKRManager query operations."""

    def test_get_company_okrs_empty(self, manager):
        """Test getting OKRs when none exist."""
        okrs = manager.get_company_okrs()
        assert okrs == []

    def test_get_company_okrs_multiple(self, manager, agent_id):
        """Test getting multiple objectives."""
        manager.create_objective(title="Obj 1", description="", owner_agent_id=agent_id)
        manager.create_objective(title="Obj 2", description="", owner_agent_id=agent_id)
        manager.create_objective(title="Obj 3", description="", owner_agent_id=agent_id)

        okrs = manager.get_company_okrs()
        assert len(okrs) == 3

    def test_get_objective_by_id(self, manager, agent_id):
        """Test getting a single objective by ID."""
        obj = manager.create_objective(
            title="Find me", description="", owner_agent_id=agent_id
        )
        found = manager.get_objective(obj.id)
        assert found is not None
        assert found.title == "Find me"

    def test_get_objective_not_found(self, manager):
        """Test getting a nonexistent objective returns None."""
        result = manager.get_objective(uuid.uuid4())
        assert result is None


class TestOKRManagerRiskDetection:
    """Tests for OKRManager risk detection."""

    def test_detect_at_risk_no_objectives(self, manager):
        """Test risk detection with no objectives returns empty list."""
        at_risk = manager.detect_at_risk_objectives(time_elapsed_fraction=0.8)
        assert at_risk == []

    def test_detect_at_risk_below_threshold(self, manager, agent_id):
        """Test that objectives with low progress are detected as at risk."""
        obj = manager.create_objective(
            title="At risk", description="", owner_agent_id=agent_id
        )
        manager.add_key_result(
            objective_id=obj.id, title="KR1", target_value=100.0
        )
        # KR1 has 0% progress (default), time is 80% elapsed

        at_risk = manager.detect_at_risk_objectives(time_elapsed_fraction=0.8)
        assert len(at_risk) == 1
        assert at_risk[0].id == obj.id

    def test_detect_at_risk_healthy_objectives(self, manager, agent_id):
        """Test that healthy objectives are not flagged as at risk."""
        obj = manager.create_objective(
            title="Healthy", description="", owner_agent_id=agent_id
        )
        kr = manager.add_key_result(
            objective_id=obj.id, title="KR1", target_value=100.0
        )
        manager.update_progress(kr.id, 80.0)  # 80% progress

        at_risk = manager.detect_at_risk_objectives(time_elapsed_fraction=0.8)
        assert len(at_risk) == 0

    def test_detect_at_risk_early_time(self, manager, agent_id):
        """Test that no objectives are flagged when time is below 70%."""
        obj = manager.create_objective(
            title="Early", description="", owner_agent_id=agent_id
        )
        manager.add_key_result(
            objective_id=obj.id, title="KR1", target_value=100.0
        )
        # KR1 at 0%, but time is only 50% elapsed - should not flag

        at_risk = manager.detect_at_risk_objectives(time_elapsed_fraction=0.5)
        assert len(at_risk) == 0

    def test_detect_at_risk_skips_completed(self, manager, agent_id):
        """Test that completed objectives are not flagged."""
        obj = manager.create_objective(
            title="Done", description="", owner_agent_id=agent_id
        )
        manager.add_key_result(
            objective_id=obj.id, title="KR1", target_value=100.0
        )
        obj.status = "completed"

        at_risk = manager.detect_at_risk_objectives(time_elapsed_fraction=0.9)
        assert len(at_risk) == 0
