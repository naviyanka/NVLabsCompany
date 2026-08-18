"""Agent model - the core autonomous employee entity."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Column, Field, Index, SQLModel
from sqlalchemy import JSON


class Agent(SQLModel, table=True):
    """An autonomous AI agent operating as an employee within the company.

    Agents have persistent identity, configurable runtime, skills, tools,
    budget constraints, and memory namespaces. They can be managed through
    lifecycle operations (hire, configure, wake, pause, terminate).
    """

    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_company_status", "company_id", "status"),
        Index("ix_agents_company_manager", "company_id", "manager_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    title: Optional[str] = Field(default=None, max_length=255)
    role: str = Field(max_length=100)
    department_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="departments.id"
    )
    team_id: Optional[uuid.UUID] = Field(default=None, foreign_key="teams.id")
    manager_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id"
    )

    # Status and lifecycle
    status: str = Field(default="idle", max_length=50)
    pause_reason: Optional[str] = Field(default=None)
    paused_at: Optional[datetime] = Field(default=None)
    error_reason: Optional[str] = Field(default=None)

    # Runtime configuration
    adapter_type: str = Field(default="langchain", max_length=100)
    adapter_config: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    runtime_config: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    model: Optional[str] = Field(default=None, max_length=255)

    # Capabilities and identity
    capabilities: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    responsibilities: Optional[str] = Field(default=None)
    objectives: Optional[str] = Field(default=None)
    skills: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    tools: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    permissions: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    soul_description: Optional[str] = Field(default=None)

    # Budget and performance
    budget_monthly_cents: int = Field(default=0)
    spent_monthly_cents: int = Field(default=0)
    performance_score: Optional[float] = Field(default=None)

    # Memory
    memory_namespace: Optional[str] = Field(default=None, max_length=255)

    # Heartbeat and monitoring
    last_heartbeat_at: Optional[datetime] = Field(default=None)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
