"""Tests for the Failure Alchemy system.

Validates that the FailureAlchemist correctly transforms failure events into
Antibody, Vaccine, and Catalyst artifacts using rule-based heuristics.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from nexus.evolution.failure_alchemy import (
    Antibody,
    ArtifactType,
    Catalyst,
    FailureAlchemist,
    FailureLearning,
    Vaccine,
)


@pytest.fixture
def alchemist():
    """Create a fresh FailureAlchemist instance for testing."""
    return FailureAlchemist()


@pytest.fixture
def sample_task_id():
    """Provide a fixed UUID for task-related tests."""
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


@pytest.fixture
def sample_agent_id():
    """Provide a fixed UUID for agent-related tests."""
    return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")


class TestArtifactTypes:
    """Tests for the ArtifactType enum."""

    def test_artifact_type_values(self):
        """ArtifactType enum has correct values."""
        assert ArtifactType.ANTIBODY == "antibody"
        assert ArtifactType.VACCINE == "vaccine"
        assert ArtifactType.CATALYST == "catalyst"


class TestAnalyzeFailure:
    """Tests for FailureAlchemist.analyze_failure method."""

    def test_produces_valid_antibody(self, alchemist, sample_task_id, sample_agent_id):
        """analyze_failure produces a valid Antibody with rule and severity."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Connection refused: could not reach API endpoint",
            context={"action": "API call", "component": "external_api"},
        )

        assert isinstance(learning.antibody, Antibody)
        assert "API call" in learning.antibody.rule
        assert learning.antibody.source_error == "Connection refused: could not reach API endpoint"
        assert learning.antibody.severity in ("low", "medium", "high", "critical")
        assert isinstance(learning.antibody.created_at, datetime)

    def test_produces_valid_vaccine(self, alchemist, sample_task_id, sample_agent_id):
        """analyze_failure produces a valid Vaccine with scenario and root cause."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Request timed out after 30 seconds",
            context={"action": "data fetch", "component": "data_pipeline"},
        )

        assert isinstance(learning.vaccine, Vaccine)
        assert "data_pipeline" in learning.vaccine.scenario
        assert learning.vaccine.expected != ""
        assert learning.vaccine.actual != ""
        assert learning.vaccine.root_cause != ""
        assert isinstance(learning.vaccine.created_at, datetime)

    def test_catalyst_none_for_first_occurrence(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """Catalyst is None for non-systemic (first occurrence) errors."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Some unique one-off error occurred",
            context={"action": "unique task", "component": "misc"},
        )

        assert learning.catalyst is None

    def test_catalyst_generated_for_recurring_patterns(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """Catalyst is generated after 3+ occurrences of the same pattern."""
        # First two occurrences: no catalyst
        for _ in range(2):
            learning = alchemist.analyze_failure(
                task_id=sample_task_id,
                agent_id=sample_agent_id,
                error="Connection refused to database server",
                context={"action": "db query", "component": "database"},
            )
            assert learning.catalyst is None

        # Third occurrence: catalyst should be generated
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Connection refused to API server",
            context={"action": "api call", "component": "network"},
        )

        assert learning.catalyst is not None
        assert isinstance(learning.catalyst, Catalyst)
        assert learning.catalyst.target_system == "connectivity"
        assert learning.catalyst.priority in ("low", "medium", "high")

    def test_produces_complete_failure_learning(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """analyze_failure produces a complete FailureLearning with all fields."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Permission denied: cannot write to /etc/config",
            context={"action": "config write", "component": "system_config"},
        )

        assert isinstance(learning, FailureLearning)
        assert learning.task_id == sample_task_id
        assert learning.agent_id == sample_agent_id
        assert isinstance(learning.created_at, datetime)
        assert learning.antibody is not None
        assert learning.vaccine is not None


class TestDifferentErrorPatterns:
    """Tests that different error types produce contextually appropriate antibodies."""

    def test_timeout_error_produces_timeout_antibody(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """Timeout errors produce antibodies about timeout guards."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Operation timed out after 60s",
            context={"action": "long computation", "component": "compute"},
        )

        assert "timeout" in learning.antibody.rule.lower()
        assert learning.antibody.severity == "high"

    def test_budget_error_produces_budget_antibody(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """Budget errors produce antibodies about budget checking."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Budget exceeded limit for this month",
            context={"action": "expensive operation", "component": "billing"},
        )

        assert "budget" in learning.antibody.rule.lower()
        assert learning.antibody.severity == "critical"

    def test_permission_error_produces_permission_antibody(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """Permission errors produce antibodies about verifying permissions."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="403 Forbidden: Access denied to resource",
            context={"action": "resource access", "component": "auth"},
        )

        assert "permission" in learning.antibody.rule.lower()
        assert learning.antibody.severity == "high"

    def test_not_found_error_produces_resource_antibody(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """Not found errors produce antibodies about confirming resource existence."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="404 Not Found: /api/v1/resource/abc",
            context={"action": "resource lookup", "component": "api"},
        )

        assert "resource" in learning.antibody.rule.lower() or "exist" in learning.antibody.rule.lower()
        assert learning.antibody.severity == "medium"

    def test_rate_limit_error_produces_rate_antibody(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """Rate limit errors produce antibodies about rate limiting."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="429 Too Many Requests: rate limit exceeded",
            context={"action": "API batch call", "component": "api_client"},
        )

        assert "rate limit" in learning.antibody.rule.lower()
        assert learning.antibody.severity == "medium"

    def test_memory_error_produces_memory_antibody(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """Memory errors produce antibodies about checking available memory."""
        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Out of memory: heap allocation failed",
            context={"action": "data processing", "component": "processor"},
        )

        assert "memory" in learning.antibody.rule.lower()
        assert learning.antibody.severity == "critical"


class TestArtifactRetrieval:
    """Tests for get_antibodies, get_vaccines, get_catalysts methods."""

    def test_get_antibodies_returns_all(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """get_antibodies returns all antibodies from analyzed failures."""
        alchemist.analyze_failure(
            sample_task_id, sample_agent_id,
            "Timeout error", {"action": "op1", "component": "c1"},
        )
        alchemist.analyze_failure(
            sample_task_id, sample_agent_id,
            "Permission denied", {"action": "op2", "component": "c2"},
        )

        antibodies = alchemist.get_antibodies()
        assert len(antibodies) == 2
        assert all(isinstance(a, Antibody) for a in antibodies)

    def test_get_vaccines_returns_all(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """get_vaccines returns all vaccines from analyzed failures."""
        alchemist.analyze_failure(
            sample_task_id, sample_agent_id,
            "Connection refused", {"action": "op1", "component": "c1"},
        )
        alchemist.analyze_failure(
            sample_task_id, sample_agent_id,
            "Resource not found", {"action": "op2", "component": "c2"},
        )

        vaccines = alchemist.get_vaccines()
        assert len(vaccines) == 2
        assert all(isinstance(v, Vaccine) for v in vaccines)

    def test_get_catalysts_returns_only_non_none(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """get_catalysts returns only non-None catalysts from systemic failures."""
        # Produce single errors (no catalyst)
        alchemist.analyze_failure(
            sample_task_id, sample_agent_id,
            "Timeout error", {"action": "op1", "component": "c1"},
        )

        assert len(alchemist.get_catalysts()) == 0

        # Produce recurring errors (triggers catalyst)
        for _ in range(2):
            alchemist.analyze_failure(
                sample_task_id, sample_agent_id,
                "Timeout again", {"action": "op2", "component": "c2"},
            )

        catalysts = alchemist.get_catalysts()
        assert len(catalysts) == 1
        assert isinstance(catalysts[0], Catalyst)


class TestAccumulation:
    """Tests that multiple failures accumulate artifacts correctly."""

    def test_multiple_failures_accumulate(
        self, alchemist, sample_task_id, sample_agent_id
    ):
        """Multiple analyze_failure calls accumulate all artifacts."""
        errors = [
            ("Timeout error 1", {"action": "op1", "component": "c1"}),
            ("Permission denied", {"action": "op2", "component": "c2"}),
            ("Connection refused", {"action": "op3", "component": "c3"}),
            ("Resource not found", {"action": "op4", "component": "c4"}),
            ("Memory OOM error", {"action": "op5", "component": "c5"}),
        ]

        for error, context in errors:
            alchemist.analyze_failure(sample_task_id, sample_agent_id, error, context)

        assert len(alchemist.get_antibodies()) == 5
        assert len(alchemist.get_vaccines()) == 5


class TestEventBusIntegration:
    """Tests for emit_learning_event method."""

    @pytest.mark.asyncio
    async def test_emit_learning_event_calls_event_bus(
        self, sample_task_id, sample_agent_id
    ):
        """emit_learning_event publishes to the event bus when available."""
        mock_bus = AsyncMock()
        alchemist = FailureAlchemist(event_bus=mock_bus)

        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Test error for event emission",
            context={"action": "test op", "component": "test"},
        )

        await alchemist.emit_learning_event(learning)

        mock_bus.publish.assert_called_once()
        call_kwargs = mock_bus.publish.call_args
        assert call_kwargs[1]["event_type"] == "failure_learning.created"
        assert call_kwargs[1]["payload"]["task_id"] == str(sample_task_id)

    @pytest.mark.asyncio
    async def test_emit_learning_event_noop_without_bus(
        self, sample_task_id, sample_agent_id
    ):
        """emit_learning_event does nothing if no event bus is configured."""
        alchemist = FailureAlchemist(event_bus=None)

        learning = alchemist.analyze_failure(
            task_id=sample_task_id,
            agent_id=sample_agent_id,
            error="Test error without bus",
            context={"action": "test op", "component": "test"},
        )

        # Should not raise
        await alchemist.emit_learning_event(learning)
