"""Pipeline models for multi-step automated workflows."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Pipeline(SQLModel, table=True):
    """A defined multi-step pipeline (template)."""

    __tablename__ = "pipelines"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    stages: Optional[list[dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    trigger_type: str = Field(default="manual", max_length=50)  # manual/schedule/webhook
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class PipelineRun(SQLModel, table=True):
    """A single execution of a pipeline."""

    __tablename__ = "pipeline_runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pipeline_id: uuid.UUID = Field(foreign_key="pipelines.id", index=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    status: str = Field(default="running", max_length=50)  # running/completed/failed/cancelled
    current_stage: int = Field(default=0)
    results: Optional[list[dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    error: Optional[str] = Field(default=None)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    completed_at: Optional[datetime] = Field(default=None)
