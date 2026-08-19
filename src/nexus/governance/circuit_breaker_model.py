"""Circuit Breaker database model for persistent state."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class CircuitBreakerRecord(SQLModel, table=True):
    """Persistent record of a circuit breaker state for an agent.

    Each row tracks the circuit breaker state for a specific agent.
    When the circuit opens (too many consecutive failures), the agent
    is blocked until the cooldown period elapses or a manual reset occurs.
    """

    __tablename__ = "circuit_breaker_records"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(index=True)
    consecutive_failures: int = Field(default=0)
    is_open: bool = Field(default=False)
    last_failure_at: Optional[datetime] = Field(default=None)
    opened_at: Optional[datetime] = Field(default=None)
    cooldown_seconds: int = Field(default=300)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
