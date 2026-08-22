"""Company settings and user preferences models."""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class CompanySettings(SQLModel, table=True):
    """Company-wide configuration settings."""

    __tablename__ = "company_settings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True, unique=True)
    workspace_name: str = Field(default="NVLabs Mission Control", max_length=255)
    workspace_description: Optional[str] = Field(default=None)
    default_language: str = Field(default="en", max_length=10)
    timezone: str = Field(default="UTC", max_length=50)
    default_model: str = Field(default="gpt-4o", max_length=100)
    default_adapter: str = Field(default="openai", max_length=100)
    default_budget_cents: int = Field(default=30000)
    max_retries: int = Field(default=5)
    heartbeat_interval_seconds: int = Field(default=30)
    auto_pause_idle: bool = Field(default=True)
    evolution_enabled: bool = Field(default=True)
    rate_limit_per_minute: int = Field(default=100)
    circuit_breaker_threshold: int = Field(default=5)
    require_approval_high_risk: bool = Field(default=True)
    audit_logging_enabled: bool = Field(default=True)
    auto_assign_tasks: bool = Field(default=False)
    daily_standup_enabled: bool = Field(default=True)
    standup_time: str = Field(default="09:00", max_length=5)
    sprint_duration_days: int = Field(default=14)
    settings_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
