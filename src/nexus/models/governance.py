"""Governance models: approvals, decisions, decision queues, and audit log."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Approval(SQLModel, table=True):
    """An approval request for a gated operation."""

    __tablename__ = "approvals"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    type: str = Field(max_length=100)
    requested_by_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id"
    )
    status: str = Field(default="pending", max_length=50)
    payload: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    decision_note: Optional[str] = Field(default=None)
    decided_by: Optional[str] = Field(default=None, max_length=255)
    decided_at: Optional[datetime] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Decision(SQLModel, table=True):
    """A decision to be made, potentially with multiple options."""

    __tablename__ = "decisions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    title: str = Field(max_length=500)
    body: Optional[str] = Field(default=None)
    options: Optional[list[dict[str, Any]]] = Field(
        default=None, sa_column=Column(JSON)
    )
    status: str = Field(default="open", max_length=50)
    chosen_option_id: Optional[str] = Field(default=None, max_length=255)
    origin_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id"
    )
    decided_by: Optional[str] = Field(default=None, max_length=255)
    decided_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DecisionQueue(SQLModel, table=True):
    """A queue that collects decisions for review and routing."""

    __tablename__ = "decision_queues"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    auto_approve_policy: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditLog(SQLModel, table=True):
    """Immutable record of every significant action in the system."""

    __tablename__ = "audit_log"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    actor_type: str = Field(max_length=50)  # agent, user, system
    actor_id: Optional[str] = Field(default=None, max_length=255)
    action: str = Field(max_length=255)
    resource_type: Optional[str] = Field(default=None, max_length=100)
    resource_id: Optional[str] = Field(default=None, max_length=255)
    details: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    ip_address: Optional[str] = Field(default=None, max_length=45)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
