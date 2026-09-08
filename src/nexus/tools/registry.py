"""Tool Registry - manages registration, discovery, and metadata for all available tools."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.models.tool import Tool, ToolAccess


@dataclass
class ToolParameter:
    """Definition of a single tool parameter.

    Attributes:
        name: Parameter name.
        type: JSON Schema type (string, number, boolean, object, array).
        description: Human-readable description.
        required: Whether the parameter is required.
        default: Default value, if any.
    """

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Any = None


@dataclass
class ToolDefinition:
    """Complete definition of a tool available in the registry.

    Attributes:
        id: Unique tool identifier.
        company_id: The company this tool belongs to.
        name: Human-readable tool name.
        description: What the tool does.
        tool_type: Type of tool (mcp, api, function, script).
        parameters: JSON Schema for the tool's input parameters.
        endpoint: URL or reference for tool execution.
        risk_level: Risk classification (low, medium, high, critical).
        is_active: Whether the tool is currently available.
        tags: Categorization tags for discovery.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    company_id: uuid.UUID | None = None
    name: str = ""
    description: str = ""
    tool_type: str = "function"
    parameters: dict[str, Any] = field(default_factory=dict)
    endpoint: str | None = None
    risk_level: str = "low"
    is_active: bool = True
    tags: list[str] = field(default_factory=list)


@dataclass
class CatalogEntry:
    """In-memory representation of a discovered tool from a connection.

    Attributes:
        id: Unique catalog entry identifier.
        company_id: The company this entry belongs to.
        connection_id: The connection this tool was discovered from.
        tool_name: The canonical tool name.
        display_name: Human-friendly display name.
        description: What the tool does.
        risk_level: Risk classification (read, write, destructive).
        input_schema: JSON Schema for tool input.
        output_schema: JSON Schema for tool output.
        version: Tool version string.
        is_active: Whether the entry is currently available.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    company_id: uuid.UUID | None = None
    connection_id: uuid.UUID | None = None
    tool_name: str = ""
    display_name: str | None = None
    description: str = ""
    risk_level: str = "read"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    version: str | None = None
    is_active: bool = True


class ToolRegistry:
    """Central registry for all tools available within the system.

    Provides registration, lookup, filtering, and agent-scoped discovery.
    Tools are scoped to companies and access is controlled via ToolAccess records.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        """Initialize registry with database-backed access authority."""
        self._tools: dict[uuid.UUID, ToolDefinition] = {}
        self._catalog_entries: dict[uuid.UUID, CatalogEntry] = {}
        if session_factory is None:
            from nexus.database import async_session_factory

            session_factory = async_session_factory
        self._session_factory = session_factory

    async def grant_access(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
        granted_by: str | None = None,
        expires_at: datetime | None = None,
    ) -> ToolAccess:
        """Persist an agent/tool grant."""
        if self._session_factory is None:
            raise RuntimeError("database session factory is required")
        async with self._session_factory() as session:
            tool = await session.get(Tool, tool_id)
            if tool is None or tool.company_id != company_id:
                raise ValueError("tool does not belong to company")
            access = ToolAccess(
                company_id=company_id,
                agent_id=agent_id,
                tool_id=tool_id,
                granted_by=granted_by,
                expires_at=expires_at,
            )
            session.add(access)
            await session.commit()
            await session.refresh(access)
            return access

    async def revoke_access(
        self, company_id: uuid.UUID, agent_id: uuid.UUID, tool_id: uuid.UUID
    ) -> None:
        """Remove active database grants for an agent/tool pair."""
        if self._session_factory is None:
            raise RuntimeError("database session factory is required")
        async with self._session_factory() as session:
            await session.execute(
                delete(ToolAccess).where(
                    ToolAccess.company_id == company_id,
                    ToolAccess.agent_id == agent_id,
                    ToolAccess.tool_id == tool_id,
                )
            )
            await session.commit()

    async def has_access(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
    ) -> bool:
        """Check current, unexpired database authority."""
        if self._session_factory is None:
            return False
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with self._session_factory() as session:
            result = await session.execute(
                select(ToolAccess.id)
                .join(Tool, Tool.id == ToolAccess.tool_id)
                .where(
                    ToolAccess.company_id == company_id,
                    ToolAccess.agent_id == agent_id,
                    ToolAccess.tool_id == tool_id,
                    Tool.company_id == company_id,
                    (ToolAccess.expires_at.is_(None) | (ToolAccess.expires_at > now)),
                    Tool.is_active.is_(True),
                )
                .limit(1)
            )
            return result.scalar_one_or_none() is not None

    def register_tool(self, tool: ToolDefinition) -> ToolDefinition:
        """Register a new tool in the registry.

        Args:
            tool: The tool definition to register.

        Returns:
            The registered tool definition (with generated ID if needed).
        """
        self._tools[tool.id] = tool
        return tool

    def unregister_tool(self, tool_id: uuid.UUID) -> bool:
        """Remove a tool from the registry.

        Args:
            tool_id: The tool to remove.

        Returns:
            True if the tool was removed, False if not found.
        """
        if tool_id in self._tools:
            del self._tools[tool_id]
            return True
        return False

    def get_tool(self, tool_id: uuid.UUID) -> ToolDefinition | None:
        """Retrieve a tool by its ID.

        Args:
            tool_id: The unique tool identifier.

        Returns:
            The ToolDefinition, or None if not found.
        """
        return self._tools.get(tool_id)

    def list_tools(
        self,
        company_id: uuid.UUID | None = None,
        tool_type: str | None = None,
        risk_level: str | None = None,
        active_only: bool = True,
        tags: list[str] | None = None,
    ) -> list[ToolDefinition]:
        """List tools with optional filters.

        Args:
            company_id: Filter by company. None means all.
            tool_type: Filter by tool type.
            risk_level: Filter by risk level.
            active_only: Whether to only include active tools.
            tags: Filter by any matching tag.

        Returns:
            List of matching ToolDefinition objects.
        """
        results: list[ToolDefinition] = []

        for tool in self._tools.values():
            if active_only and not tool.is_active:
                continue
            if company_id and tool.company_id != company_id:
                continue
            if tool_type and tool.tool_type != tool_type:
                continue
            if risk_level and tool.risk_level != risk_level:
                continue
            if tags:
                if not any(t in tool.tags for t in tags):
                    continue
            results.append(tool)

        return results

    async def discover_tools_async(
        self, company_id: uuid.UUID, agent_id: uuid.UUID
    ) -> list[Tool]:
        """Discover active tools currently granted in the database."""
        if self._session_factory is None:
            return []
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with self._session_factory() as session:
            result = await session.execute(
                select(Tool)
                .join(ToolAccess, ToolAccess.tool_id == Tool.id)
                .where(
                    Tool.company_id == company_id,
                    ToolAccess.company_id == company_id,
                    ToolAccess.agent_id == agent_id,
                    (ToolAccess.expires_at.is_(None) | (ToolAccess.expires_at > now)),
                    Tool.is_active.is_(True),
                )
            )
            return list(result.scalars().all())

    def discover_tools(
        self,
        agent_id: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> list[ToolDefinition]:
        """Return local definitions; database discovery uses ``discover_tools_async``."""
        return [
            tool
            for tool in self._tools.values()
            if tool.is_active and (company_id is None or tool.company_id == company_id)
        ]

    # --- Catalog Entry Methods ---

    def register_catalog_entry(self, entry: CatalogEntry) -> CatalogEntry:
        """Register a catalog entry discovered from a connection.

        Args:
            entry: The catalog entry to register.

        Returns:
            The registered catalog entry.
        """
        self._catalog_entries[entry.id] = entry
        return entry

    def discover_from_connection(self, connection_id: uuid.UUID) -> list[CatalogEntry]:
        """Return all catalog entries discovered from a specific connection.

        Args:
            connection_id: The connection to filter by.

        Returns:
            List of CatalogEntry objects for the given connection.
        """
        return [
            entry
            for entry in self._catalog_entries.values()
            if entry.connection_id == connection_id and entry.is_active
        ]

    def list_catalog_entries(
        self,
        company_id: uuid.UUID | None = None,
        risk_level: str | None = None,
        connection_id: uuid.UUID | None = None,
    ) -> list[CatalogEntry]:
        """List catalog entries with optional filters.

        Args:
            company_id: Filter by company. None means all.
            risk_level: Filter by risk level (read, write, destructive).
            connection_id: Filter by connection. None means all.

        Returns:
            List of matching CatalogEntry objects.
        """
        results: list[CatalogEntry] = []

        for entry in self._catalog_entries.values():
            if not entry.is_active:
                continue
            if company_id and entry.company_id != company_id:
                continue
            if risk_level and entry.risk_level != risk_level:
                continue
            if connection_id and entry.connection_id != connection_id:
                continue
            results.append(entry)

        return results
