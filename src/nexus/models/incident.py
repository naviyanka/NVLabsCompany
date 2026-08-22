"""Incident models: incidents, events, and actions."""

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Incident(SQLModel, table=True):
    """A system incident requiring investigation or response."""

    __tablename__ = "incidents"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    title: str = Field(max_length=500)
    severity: str = Field(default="medium", max_length=50)
    status: str = Field(default="open", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    resolved_at: Optional[datetime] = Field(default=None)
    rca: Optional[str] = Field(default=None)


class IncidentEvent(SQLModel, table=True):
    """A timeline event within an incident."""

    __tablename__ = "incident_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    incident_id: uuid.UUID = Field(foreign_key="incidents.id", index=True)
    event_type: str = Field(max_length=100)
    description: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=lambda: datetime.utcnow())
    actor: Optional[str] = Field(default=None, max_length=255)


class IncidentAction(SQLModel, table=True):
    """An action taken during incident response."""

    __tablename__ = "incident_actions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    incident_id: uuid.UUID = Field(foreign_key="incidents.id", index=True)
    action_type: str = Field(max_length=100)
    target: Optional[str] = Field(default=None, max_length=255)
    executed_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    result: Optional[str] = Field(default=None)
