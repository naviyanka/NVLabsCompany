"""Goal, Project, and Task models for work management."""

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Goal(SQLModel, table=True):
    """Strategic goal or OKR within the company hierarchy."""

    __tablename__ = "goals"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    title: str = Field(max_length=500)
    description: Optional[str] = Field(default=None)
    level: str = Field(default="company", max_length=50)
    status: str = Field(default="active", max_length=50)
    parent_id: Optional[uuid.UUID] = Field(default=None, foreign_key="goals.id")
    owner_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class Project(SQLModel, table=True):
    """A project that groups related tasks toward a goal."""

    __tablename__ = "projects"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    status: str = Field(default="active", max_length=50)
    goal_id: Optional[uuid.UUID] = Field(default=None, foreign_key="goals.id")
    lead_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id"
    )
    budget_cents: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class Task(SQLModel, table=True):
    """An individual unit of work assignable to an agent."""

    __tablename__ = "tasks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    project_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="projects.id", index=True
    )
    title: str = Field(max_length=500)
    description: Optional[str] = Field(default=None)
    status: str = Field(default="pending", max_length=50)
    priority: int = Field(default=0)
    assigned_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id", index=True
    )
    parent_task_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="tasks.id"
    )
    result: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
