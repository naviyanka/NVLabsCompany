"""Tool registry and access control models."""

import uuid
from datetime import datetime, timezone
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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ToolConnection(SQLModel, table=True):
    """A connection endpoint for tool integrations (MCP servers, REST APIs, local processes)."""

    __tablename__ = "tool_connections"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    transport_type: str = Field(max_length=50)  # mcp_remote, rest_api, local_stdio
    endpoint_url: str | None = Field(default=None, max_length=2048)
    auth_kind: str = Field(default="none", max_length=50)  # none, api_key, oauth, bearer
    credential_ref: str | None = Field(default=None, max_length=512)
    health_status: str = Field(
        default="unknown", max_length=50
    )  # healthy, degraded, unhealthy, unknown
    last_health_check_at: datetime | None = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolCatalogEntry(SQLModel, table=True):
    """A discovered tool from a connection, representing a single callable capability."""

    __tablename__ = "tool_catalog_entries"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    connection_id: uuid.UUID = Field(foreign_key="tool_connections.id", index=True)
    tool_name: str = Field(max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None)
    risk_level: str = Field(default="read", max_length=50)  # read, write, destructive
    input_schema: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    output_schema: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    version: str | None = Field(default=None, max_length=100)
    is_active: bool = Field(default=True)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolProfile(SQLModel, table=True):
    """A named collection of tool policies that can be bound to agents/departments/companies."""

    __tablename__ = "tool_profiles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None)
    default_action: str = Field(default="allow", max_length=50)  # allow, deny
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolProfileBinding(SQLModel, table=True):
    """Binds a ToolProfile to a target (agent, department, or company)."""

    __tablename__ = "tool_profile_bindings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    profile_id: uuid.UUID = Field(foreign_key="tool_profiles.id", index=True)
    target_type: str = Field(max_length=50)  # agent, department, company
    target_id: uuid.UUID = Field(index=True)
    priority: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolPolicy(SQLModel, table=True):
    """A policy rule governing tool access, evaluated by the policy engine."""

    __tablename__ = "tool_policies"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None)
    priority: int = Field(default=0)
    effect: str = Field(max_length=50)  # allow, deny
    conditions: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
