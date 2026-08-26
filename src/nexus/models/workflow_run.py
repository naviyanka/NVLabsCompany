"""WorkflowRun model for persisted workflow executions."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class WorkflowRun(SQLModel, table=True):
    """A persisted workflow execution (company delegation chain or task flow).

    Rows are created when a workflow is started via the API and updated by the
    background runner as the real engine produces its trace, so status and
    history survive process restarts.
    """

    __tablename__ = "workflow_runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    workflow_type: str = Field(default="company", max_length=20)  # "company" | "task"
    status: str = Field(default="pending", max_length=50)
    objective: str = Field(default="", max_length=4000)
    input_payload: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    current_step: Optional[str] = Field(default=None, max_length=255)
    total_cost_cents: int = Field(default=0)
    steps: Optional[list[dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    result: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    error: Optional[str] = Field(default=None)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
