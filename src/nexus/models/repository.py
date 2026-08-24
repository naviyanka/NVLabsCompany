"""Repository model for connected git repositories."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Repository(SQLModel, table=True):
    """A connected git repository."""

    __tablename__ = "repositories"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    url: str = Field(max_length=500)
    provider: str = Field(default="github", max_length=50)  # github/gitlab/bitbucket
    default_branch: str = Field(default="main", max_length=100)
    description: Optional[str] = Field(default=None)
    language: Optional[str] = Field(default=None, max_length=50)
    is_active: bool = Field(default=True)
    last_synced_at: Optional[datetime] = Field(default=None)
    stats: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
