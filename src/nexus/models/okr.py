"""OKR relational models — Objective and KeyResult tables.

Replaces the JSON-file-backed OKR system with proper SQLModel tables,
enabling multi-tenant persistence, migrations, and relational queries.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class OKRObjective(SQLModel, table=True):
    __tablename__ = "okr_objectives"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    title: str = Field(max_length=500)
    description: Optional[str] = Field(default=None)
    owner_agent_id: Optional[uuid.UUID] = Field(default=None, foreign_key="agents.id")
    time_frame: str = Field(default="Q1 2025", max_length=100)
    status: str = Field(default="active", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class OKRKeyResult(SQLModel, table=True):
    __tablename__ = "okr_key_results"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    objective_id: uuid.UUID = Field(foreign_key="okr_objectives.id", index=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    title: str = Field(max_length=500)
    target_value: float = Field(default=100.0)
    current_value: float = Field(default=0.0)
    unit: str = Field(default="percent", max_length=50)
    status: str = Field(default="on_track", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
