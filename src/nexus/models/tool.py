"""Tool registry and access control models."""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Tool(SQLModel, table=True):
    """A registered tool available for agent use."""

    __tablename__ = "tools"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    tool_type: str = Field(max_length=100)  # mcp, api, function, script
    schema_def: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    endpoint: Optional[str] = Field(default=None, max_length=2048)
    is_active: bool = Field(default=True)
    risk_level: str = Field(default="low", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class ToolAccess(SQLModel, table=True):
    """Permission grant for an agent to use a specific tool."""

    __tablename__ = "tool_access"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    tool_id: uuid.UUID = Field(foreign_key="tools.id", index=True)
    granted_by: Optional[str] = Field(default=None, max_length=255)
    permission_level: str = Field(default="execute", max_length=50)
    expires_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
