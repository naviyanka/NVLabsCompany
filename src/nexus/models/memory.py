"""Memory record model for the 3-temperature memory system."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class MemoryRecord(SQLModel, table=True):
    """A memory entry in the 3-temperature memory system (hot/warm/cold).

    Memories can be scoped to an agent, team, or company level.
    The tier field determines the storage temperature:
    - hot: in-memory cache (Redis), frequently accessed
    - warm: database, moderately accessed
    - cold: archive, rarely accessed
    """

    __tablename__ = "memory_records"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id", index=True
    )
    scope: str = Field(max_length=50)  # agent, team, department, company
    scope_id: Optional[uuid.UUID] = Field(default=None, index=True)
    content: str
    record_metadata: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON, name="metadata")
    )
    importance: float = Field(default=0.5)
    access_count: int = Field(default=0)
    last_accessed_at: Optional[datetime] = Field(default=None)
    tier: str = Field(default="warm", max_length=20)  # hot, warm, cold
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
