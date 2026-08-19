"""Trigger models for proactive agent behavior (Aware system)."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Trigger(SQLModel, table=True):
    """A trigger that fires agents proactively based on conditions.

    Trigger types include:
    - cron: fires on a schedule
    - webhook: fires when an external event arrives
    - on_message: fires when a matching message is received
    - on_event: fires when a system event occurs
    - on_condition: fires when a data condition is met
    - on_schedule: fires at a specific datetime
    """

    __tablename__ = "triggers"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    trigger_type: str = Field(max_length=50)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    config: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    last_fired_at: Optional[datetime] = Field(default=None)
    next_fire_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TriggerExecution(SQLModel, table=True):
    """Records an execution of a trigger."""

    __tablename__ = "trigger_executions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    trigger_id: uuid.UUID = Field(foreign_key="triggers.id", index=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    status: str = Field(default="running", max_length=50)
    result: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    error: Optional[str] = Field(default=None)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None)
