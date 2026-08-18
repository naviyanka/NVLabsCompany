"""Agent Service - CRUD and management operations for agents."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.agent import Agent


class AgentService:
    """Service layer for agent CRUD operations and management.

    All methods are async and require a database session. Handles
    agent creation, retrieval, updates, deletion, and team/manager assignment.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_agent(
        self,
        company_id: uuid.UUID,
        name: str,
        role: str,
        **kwargs: Any,
    ) -> Agent:
        """Create a new agent in the system.

        Args:
            company_id: The company this agent belongs to.
            name: Display name for the agent.
            role: The agent's organizational role.
            **kwargs: Additional agent fields (title, model, etc.).

        Returns:
            The newly created Agent instance.
        """
        agent = Agent(
            company_id=company_id,
            name=name,
            role=role,
            **kwargs,
        )
        self._db.add(agent)
        await self._db.flush()
        return agent

    async def get_agent(self, agent_id: uuid.UUID) -> Agent | None:
        """Retrieve a single agent by ID.

        Args:
            agent_id: The agent's unique identifier.

        Returns:
            The Agent instance, or None if not found.
        """
        stmt = select(Agent).where(Agent.id == agent_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_agents(
        self,
        company_id: uuid.UUID,
        status: str | None = None,
        department_id: uuid.UUID | None = None,
        team_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Agent]:
        """List agents for a company with optional filters.

        Args:
            company_id: The company to list agents for.
            status: Optional filter by agent status.
            department_id: Optional filter by department.
            team_id: Optional filter by team.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of matching Agent instances.
        """
        stmt = select(Agent).where(Agent.company_id == company_id)

        if status:
            stmt = stmt.where(Agent.status == status)
        if department_id:
            stmt = stmt.where(Agent.department_id == department_id)
        if team_id:
            stmt = stmt.where(Agent.team_id == team_id)

        stmt = stmt.offset(offset).limit(limit).order_by(Agent.created_at.desc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def update_agent(
        self, agent_id: uuid.UUID, **updates: Any
    ) -> Agent | None:
        """Update agent fields.

        Args:
            agent_id: The agent to update.
            **updates: Fields to update with their new values.

        Returns:
            The updated Agent instance, or None if not found.
        """
        updates["updated_at"] = datetime.now(timezone.utc)
        stmt = update(Agent).where(Agent.id == agent_id).values(**updates)
        await self._db.execute(stmt)
        return await self.get_agent(agent_id)

    async def delete_agent(self, agent_id: uuid.UUID) -> bool:
        """Delete an agent from the system.

        Args:
            agent_id: The agent to delete.

        Returns:
            True if the agent was deleted, False if not found.
        """
        stmt = delete(Agent).where(Agent.id == agent_id)
        result = await self._db.execute(stmt)
        return result.rowcount > 0  # type: ignore[union-attr]

    async def assign_to_team(
        self, agent_id: uuid.UUID, team_id: uuid.UUID
    ) -> Agent | None:
        """Assign an agent to a team.

        Args:
            agent_id: The agent to assign.
            team_id: The team to assign the agent to.

        Returns:
            The updated Agent instance.
        """
        return await self.update_agent(agent_id, team_id=team_id)

    async def set_manager(
        self, agent_id: uuid.UUID, manager_id: uuid.UUID
    ) -> Agent | None:
        """Set the manager for an agent.

        Args:
            agent_id: The agent to update.
            manager_id: The manager agent's ID.

        Returns:
            The updated Agent instance.
        """
        return await self.update_agent(agent_id, manager_id=manager_id)
