"""Goal, Project, and Task models for work management."""

import uuid
from datetime import timezone, datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class RunCompletionReason(str, Enum):
    """Why a run (goal drive or subtask execution) reached a terminal state.

    Every terminal path in ``runtime/orchestrator.py`` sets exactly one of
    these, so "why did this stop?" is answerable without reading logs.
    """

    goal = "goal"  # judge confirmed the goal was achieved
    no_tool_calls = "no_tool_calls"  # model produced no actionable output
    max_iterations = "max_iterations"  # iteration cap hit before completion
    timeout = "timeout"  # wall-clock budget for the step expired
    budget_exhausted = "budget_exhausted"  # no spend headroom left
    doom_loop = "doom_loop"  # repeated re-decomposition without progress
    needs_help = "needs_help"  # agent explicitly escalated to a human
    error = "error"  # unhandled failure


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
    completion_reason: Optional[str] = Field(default=None, max_length=32, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


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
    # Set when the task was decomposed out of a goal. Distinct from
    # parent_task_id, which points at another task.
    goal_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="goals.id", index=True
    )
    result: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
    completion_reason: Optional[str] = Field(default=None, max_length=32, index=True)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
