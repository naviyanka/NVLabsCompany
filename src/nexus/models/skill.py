"""Skill registry models."""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Skill(SQLModel, table=True):
    """A registered skill that agents can acquire and use."""

    __tablename__ = "skills"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None, max_length=100)
    version: str = Field(default="1.0.0", max_length=50)
    schema_def: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class AgentSkill(SQLModel, table=True):
    """Links an agent to a skill with a proficiency level."""

    __tablename__ = "agent_skills"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    skill_id: uuid.UUID = Field(foreign_key="skills.id", index=True)
    proficiency: float = Field(default=0.5)
    acquired_at: datetime = Field(default_factory=lambda: datetime.utcnow())
