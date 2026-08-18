"""Skill Service - skill registry and agent skill management."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.skill import AgentSkill, Skill


class SkillService:
    """Service layer for skill registry and agent-skill associations.

    Manages skill registration, assignment to agents, and discovery
    of agents with specific skills.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def register_skill(
        self,
        company_id: uuid.UUID,
        name: str,
        description: str | None = None,
        category: str | None = None,
        version: str = "1.0.0",
        schema_def: dict[str, Any] | None = None,
    ) -> Skill:
        """Register a new skill in the company's skill registry.

        Args:
            company_id: The company this skill belongs to.
            name: Skill name.
            description: Optional description.
            category: Optional category for grouping.
            version: Skill version string.
            schema_def: Optional JSON schema defining skill parameters.

        Returns:
            The newly created Skill instance.
        """
        skill = Skill(
            company_id=company_id,
            name=name,
            description=description,
            category=category,
            version=version,
            schema_def=schema_def,
        )
        self._db.add(skill)
        await self._db.flush()
        return skill

    async def assign_skill_to_agent(
        self,
        agent_id: uuid.UUID,
        skill_id: uuid.UUID,
        proficiency: float = 0.5,
    ) -> AgentSkill:
        """Assign a skill to an agent with a proficiency level.

        Args:
            agent_id: The agent to assign the skill to.
            skill_id: The skill to assign.
            proficiency: Proficiency level (0.0 to 1.0).

        Returns:
            The newly created AgentSkill instance.
        """
        agent_skill = AgentSkill(
            agent_id=agent_id,
            skill_id=skill_id,
            proficiency=proficiency,
        )
        self._db.add(agent_skill)
        await self._db.flush()
        return agent_skill

    async def get_agent_skills(
        self, agent_id: uuid.UUID
    ) -> list[AgentSkill]:
        """Get all skills assigned to an agent.

        Args:
            agent_id: The agent to query.

        Returns:
            List of AgentSkill instances.
        """
        stmt = select(AgentSkill).where(AgentSkill.agent_id == agent_id)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def find_agents_with_skill(
        self,
        skill_id: uuid.UUID,
        min_proficiency: float = 0.0,
    ) -> list[AgentSkill]:
        """Find all agents that have a specific skill.

        Args:
            skill_id: The skill to search for.
            min_proficiency: Minimum proficiency threshold.

        Returns:
            List of AgentSkill instances matching the criteria.
        """
        stmt = select(AgentSkill).where(
            AgentSkill.skill_id == skill_id,
            AgentSkill.proficiency >= min_proficiency,
        )
        stmt = stmt.order_by(AgentSkill.proficiency.desc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def list_skills(
        self,
        company_id: uuid.UUID,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Skill]:
        """List skills registered for a company.

        Args:
            company_id: The company to list skills for.
            category: Optional category filter.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of Skill instances.
        """
        stmt = select(Skill).where(Skill.company_id == company_id)

        if category:
            stmt = stmt.where(Skill.category == category)

        stmt = stmt.offset(offset).limit(limit).order_by(Skill.name)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())
