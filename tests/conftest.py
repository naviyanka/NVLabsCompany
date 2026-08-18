"""Shared test fixtures for the NEXUS test suite.

Provides mock database sessions (AsyncMock), sample company/agent/task fixtures,
and pytest-asyncio configuration.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# pytest-asyncio mode configuration
def pytest_configure(config):
    """Configure pytest-asyncio to auto mode."""
    config.addinivalue_line("markers", "asyncio: mark test as async")


@pytest.fixture
def mock_db_session():
    """Create a mock async database session.

    Provides an AsyncMock that simulates SQLAlchemy AsyncSession behavior
    including execute, flush, add, commit, and rollback.
    """
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def sample_company_id():
    """Provide a fixed UUID for company-related tests."""
    return uuid.UUID("12345678-1234-1234-1234-123456789abc")


@pytest.fixture
def sample_agent_id():
    """Provide a fixed UUID for agent-related tests."""
    return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")


@pytest.fixture
def sample_task_id():
    """Provide a fixed UUID for task-related tests."""
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


@pytest.fixture
def sample_team_id():
    """Provide a fixed UUID for team-related tests."""
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def sample_company_data(sample_company_id):
    """Provide sample data for creating a Company instance."""
    return {
        "id": sample_company_id,
        "name": "Test AI Corp",
        "description": "A test autonomous AI company",
        "status": "active",
        "budget_monthly_cents": 100000,
        "spent_monthly_cents": 0,
    }


@pytest.fixture
def sample_agent_data(sample_company_id, sample_agent_id):
    """Provide sample data for creating an Agent instance."""
    return {
        "id": sample_agent_id,
        "company_id": sample_company_id,
        "name": "TestAgent-Alpha",
        "role": "engineer",
        "title": "Senior AI Engineer",
        "status": "idle",
        "adapter_type": "langchain",
        "model": "gpt-4o",
        "budget_monthly_cents": 5000,
    }


@pytest.fixture
def sample_task_data(sample_company_id, sample_agent_id, sample_task_id):
    """Provide sample data for creating a Task instance."""
    return {
        "id": sample_task_id,
        "company_id": sample_company_id,
        "title": "Implement feature X",
        "description": "Build the feature X integration",
        "status": "pending",
        "priority": 1,
        "assigned_agent_id": sample_agent_id,
    }
