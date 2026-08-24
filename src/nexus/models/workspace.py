"""Workspace model for multi-project switching."""

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Workspace(SQLModel, table=True):
    """A workspace represents a project directory that agents can operate in."""

    __tablename__ = "workspaces"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    path: str = Field(max_length=1000)
    description: Optional[str] = Field(default=None)
    is_active: bool = Field(default=False)
    is_git_repo: bool = Field(default=False)
    default_branch: Optional[str] = Field(default="main", max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    last_accessed_at: Optional[datetime] = Field(default=None)
