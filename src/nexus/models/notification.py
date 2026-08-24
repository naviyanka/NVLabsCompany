"""Notification model for platform-wide event notifications."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Notification(SQLModel, table=True):
    """A notification event delivered to users/operators."""

    __tablename__ = "notifications"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    title: str = Field(max_length=500)
    description: Optional[str] = Field(default=None)
    notification_type: str = Field(default="info", max_length=50)  # info/success/warning/error
    module: str = Field(default="system", max_length=100)  # agents/tasks/pipelines/system/etc
    priority: str = Field(default="low", max_length=20)  # low/medium/high/critical
    read: bool = Field(default=False)
    dismissed: bool = Field(default=False)
    notification_metadata: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, name="notification_metadata"))
    agent_id: Optional[uuid.UUID] = Field(default=None, foreign_key="agents.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationPreference(SQLModel, table=True):
    """User/company notification preferences."""

    __tablename__ = "notification_preferences"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    email_enabled: bool = Field(default=True)
    push_enabled: bool = Field(default=True)
    slack_enabled: bool = Field(default=False)
    quiet_hours_enabled: bool = Field(default=True)
    quiet_start: str = Field(default="22:00", max_length=5)
    quiet_end: str = Field(default="07:00", max_length=5)
    agent_completions: bool = Field(default=True)
    pipeline_failures: bool = Field(default=True)
    security_alerts: bool = Field(default=True)
    system_updates: bool = Field(default=True)
    mentions: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
