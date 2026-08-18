"""Memory Scope Manager - controls memory visibility based on agent permissions."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.agent import Agent
from nexus.models.memory import MemoryRecord


@dataclass
class MemoryScope:
    """Represents an accessible memory scope for an agent."""

    scope: str  # agent, team, department, company
    scope_id: uuid.UUID | None

    @property
    def key(self) -> str:
        """Generate a unique key for this scope."""
        return f"{self.scope}:{self.scope_id or 'global'}"


class MemoryScopeManager:
    """Manages memory visibility and access control based on organizational hierarchy.

    Agents can access memories in the following scopes (from most private to most public):
    - agent: Their own private memories
    - team: Shared with team members
    - department: Shared with department members
    - company: Company-wide shared knowledge

    Access is determined by the agent's position in the org chart.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the scope manager.

        Args:
            db: Async database session.
        """
        self._db = db

    async def get_accessible_scopes(
        self, agent_id: uuid.UUID
    ) -> list[MemoryScope]:
        """Get all memory scopes accessible to an agent.

        Based on the agent's team, department, and company memberships,
        returns the list of scopes they can read from.

        Args:
            agent_id: The agent requesting access.

        Returns:
            List of MemoryScope instances the agent can access.
        """
        # Fetch agent details
        stmt = select(Agent).where(Agent.id == agent_id)
        result = await self._db.execute(stmt)
        agent = result.scalar_one_or_none()

        if agent is None:
            return []

        scopes: list[MemoryScope] = []

        # 1. Agent's own scope (always accessible)
        scopes.append(MemoryScope(scope="agent", scope_id=agent_id))

        # 2. Team scope (if agent belongs to a team)
        if agent.team_id:
            scopes.append(MemoryScope(scope="team", scope_id=agent.team_id))

        # 3. Department scope (if agent belongs to a department)
        if agent.department_id:
            scopes.append(
                MemoryScope(scope="department", scope_id=agent.department_id)
            )

        # 4. Company scope (always accessible for company members)
        scopes.append(MemoryScope(scope="company", scope_id=agent.company_id))

        return scopes

    def filter_by_scope(
        self,
        memories: list[MemoryRecord],
        allowed_scopes: list[MemoryScope],
    ) -> list[MemoryRecord]:
        """Filter a list of memories to only those in allowed scopes.

        Args:
            memories: List of MemoryRecord instances to filter.
            allowed_scopes: List of MemoryScope instances that are permitted.

        Returns:
            Filtered list containing only memories within allowed scopes.
        """
        allowed_keys = {scope.key for scope in allowed_scopes}

        filtered: list[MemoryRecord] = []
        for memory in memories:
            memory_key = f"{memory.scope}:{memory.scope_id or 'global'}"
            if memory_key in allowed_keys:
                filtered.append(memory)

        return filtered

    async def can_access(
        self, agent_id: uuid.UUID, memory: MemoryRecord
    ) -> bool:
        """Check if an agent can access a specific memory.

        Args:
            agent_id: The agent requesting access.
            memory: The memory being accessed.

        Returns:
            True if the agent has access to the memory's scope.
        """
        scopes = await self.get_accessible_scopes(agent_id)
        allowed_keys = {scope.key for scope in scopes}
        memory_key = f"{memory.scope}:{memory.scope_id or 'global'}"
        return memory_key in allowed_keys
