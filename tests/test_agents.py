"""Tests for AgentService CRUD and AgentLifecycleManager state transitions.

Tests the agent service layer and lifecycle state machine using mocked
database sessions.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from nexus.models.agent import Agent
from nexus.services.agent_service import AgentService
from nexus.runtime.lifecycle import (
    AgentLifecycleManager,
    LifecycleError,
    _VALID_TRANSITIONS,
)


class TestAgentServiceCreate:
    """Tests for AgentService.create_agent."""

    @pytest.mark.asyncio
    async def test_create_agent(self, mock_db_session, sample_company_id):
        """AgentService creates an agent with correct fields."""
        service = AgentService(mock_db_session)

        result = await service.create_agent(
            company_id=sample_company_id,
            name="TestBot",
            role="engineer",
            title="Lead Engineer",
        )

        assert result.name == "TestBot"
        assert result.role == "engineer"
        assert result.company_id == sample_company_id
        assert result.title == "Lead Engineer"
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_agent_default_status(self, mock_db_session, sample_company_id):
        """Created agent defaults to idle status."""
        service = AgentService(mock_db_session)

        result = await service.create_agent(
            company_id=sample_company_id,
            name="DefaultBot",
            role="analyst",
        )

        assert result.status == "idle"


class TestAgentServiceList:
    """Tests for AgentService.list_agents."""

    @pytest.mark.asyncio
    async def test_list_agents_by_company(self, mock_db_session, sample_company_id):
        """list_agents queries by company_id."""
        # Create mock result
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [
            Agent(company_id=sample_company_id, name="Bot1", role="dev"),
            Agent(company_id=sample_company_id, name="Bot2", role="dev"),
        ]
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute.return_value = mock_result

        service = AgentService(mock_db_session)
        results = await service.list_agents(company_id=sample_company_id)

        assert len(results) == 2
        assert results[0].name == "Bot1"
        assert results[1].name == "Bot2"
        mock_db_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_agents_with_status_filter(self, mock_db_session, sample_company_id):
        """list_agents can filter by status."""
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute.return_value = mock_result

        service = AgentService(mock_db_session)
        results = await service.list_agents(
            company_id=sample_company_id, status="executing"
        )

        assert results == []
        mock_db_session.execute.assert_awaited_once()


class TestAgentServiceUpdate:
    """Tests for AgentService.update_agent and assign_to_team."""

    @pytest.mark.asyncio
    async def test_update_agent_status(self, mock_db_session, sample_agent_id):
        """update_agent can change status."""
        # Mock get_agent to return updated agent
        updated_agent = Agent(
            id=sample_agent_id,
            company_id=uuid.uuid4(),
            name="Bot",
            role="dev",
            status="paused",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = updated_agent
        mock_db_session.execute.return_value = mock_result

        service = AgentService(mock_db_session)
        result = await service.update_agent(sample_agent_id, status="paused")

        assert result is not None
        assert result.status == "paused"

    @pytest.mark.asyncio
    async def test_assign_to_team(self, mock_db_session, sample_agent_id, sample_team_id):
        """assign_to_team sets team_id on the agent."""
        updated_agent = Agent(
            id=sample_agent_id,
            company_id=uuid.uuid4(),
            name="Bot",
            role="dev",
            team_id=sample_team_id,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = updated_agent
        mock_db_session.execute.return_value = mock_result

        service = AgentService(mock_db_session)
        result = await service.assign_to_team(sample_agent_id, sample_team_id)

        assert result is not None
        assert result.team_id == sample_team_id


class TestLifecycleValidTransitions:
    """Tests for the lifecycle state transition validation logic."""

    def test_idle_to_ready_valid(self):
        """Transition from idle to ready is allowed."""
        assert "ready" in _VALID_TRANSITIONS["idle"]

    def test_ready_to_executing_valid(self):
        """Transition from ready to executing is allowed."""
        assert "executing" in _VALID_TRANSITIONS["ready"]

    def test_executing_to_idle_valid(self):
        """Transition from executing to idle is allowed."""
        assert "idle" in _VALID_TRANSITIONS["executing"]

    def test_terminated_has_no_transitions(self):
        """Terminated is a final state with no outgoing transitions."""
        assert _VALID_TRANSITIONS["terminated"] == set()

    def test_any_state_to_terminated(self):
        """All non-terminal states can transition to terminated."""
        for state, targets in _VALID_TRANSITIONS.items():
            if state != "terminated":
                assert "terminated" in targets, (
                    f"State '{state}' should be able to transition to terminated"
                )


class TestLifecycleManager:
    """Tests for AgentLifecycleManager state transitions."""

    @pytest.mark.asyncio
    async def test_validate_transition_raises_on_invalid(self, mock_db_session):
        """Invalid transition raises LifecycleError."""
        mock_adapter = AsyncMock()
        manager = AgentLifecycleManager(mock_db_session, mock_adapter)

        agent_id = uuid.uuid4()
        with pytest.raises(LifecycleError) as exc_info:
            manager._validate_transition(agent_id, "idle", "executing")

        assert exc_info.value.from_state == "idle"
        assert exc_info.value.to_state == "executing"
        assert "Invalid transition" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validate_transition_allows_valid(self, mock_db_session):
        """Valid transition does not raise."""
        mock_adapter = AsyncMock()
        manager = AgentLifecycleManager(mock_db_session, mock_adapter)

        agent_id = uuid.uuid4()
        # Should not raise
        manager._validate_transition(agent_id, "idle", "ready")
        manager._validate_transition(agent_id, "ready", "executing")
        manager._validate_transition(agent_id, "executing", "idle")

    @pytest.mark.asyncio
    async def test_create_agent_sets_idle(self, mock_db_session, sample_company_id):
        """create_agent creates agent in idle state."""
        mock_adapter = AsyncMock()
        manager = AgentLifecycleManager(mock_db_session, mock_adapter)

        agent = await manager.create_agent(
            company_id=sample_company_id,
            name="NewAgent",
            role="worker",
        )

        assert agent.status == "idle"
        assert agent.name == "NewAgent"
        mock_db_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifecycle_error_contains_details(self):
        """LifecycleError provides agent_id and state info."""
        agent_id = uuid.uuid4()
        error = LifecycleError(agent_id, "idle", "executing")

        assert error.agent_id == agent_id
        assert error.from_state == "idle"
        assert error.to_state == "executing"
        assert str(agent_id) in str(error)

    @pytest.mark.asyncio
    async def test_error_state_can_recover_to_idle(self, mock_db_session):
        """Agent in error state can transition back to idle."""
        mock_adapter = AsyncMock()
        manager = AgentLifecycleManager(mock_db_session, mock_adapter)

        agent_id = uuid.uuid4()
        # error -> idle is valid
        manager._validate_transition(agent_id, "error", "idle")

    @pytest.mark.asyncio
    async def test_paused_to_ready(self, mock_db_session):
        """Agent in paused state can transition to ready."""
        mock_adapter = AsyncMock()
        manager = AgentLifecycleManager(mock_db_session, mock_adapter)

        agent_id = uuid.uuid4()
        manager._validate_transition(agent_id, "paused", "ready")
