"""Heartbeat run model with rich process and liveness tracking."""

import uuid
from datetime import timezone, datetime
from enum import Enum

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class LivenessState(str, Enum):
    """Liveness states for a heartbeat run."""

    healthy = "healthy"
    suspected_stale = "suspected_stale"
    confirmed_dead = "confirmed_dead"


class InvocationSource(str, Enum):
    """How a heartbeat run was triggered."""

    on_demand = "on_demand"
    scheduled = "scheduled"
    trigger = "trigger"
    heartbeat = "heartbeat"


class HeartbeatRun(SQLModel, table=True):
    """Records a single heartbeat run with process metadata and liveness state."""

    __tablename__ = "heartbeat_runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    session_id_before: str | None = None
    session_id_after: str | None = None
    process_pid: int | None = None
    exit_code: int | None = None
    signal: str | None = None
    stdout_excerpt: str | None = Field(default=None, max_length=2000)
    stderr_excerpt: str | None = Field(default=None, max_length=2000)
    liveness_state: str = Field(default="healthy")
    continuation_attempt: int = Field(default=0)
    context_snapshot: dict | None = Field(default=None, sa_column=Column(JSON))
    invocation_source: str = Field(default="on_demand")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    finished_at: datetime | None = None
    last_output_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
