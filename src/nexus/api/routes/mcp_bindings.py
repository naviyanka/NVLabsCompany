"""Tool connections, MCP bindings and effective tools (ws05).

A ``ToolConnection`` registers an MCP server for a company; ``discover`` fills
its ``ToolCatalogEntry`` rows. An ``McpBinding`` grants an agent (or one
session) access to a connection. Bindings only grant: every tool call still
goes through ``nexus.tools.access.check_tool_access`` (RBAC, tool policy) and
``guard_tool_call`` (guardrails, autonomy), and none of those can be overridden
here. ``effective-tools`` reports what that server-side check decides, so a UI
can display it without ever being the authority for it.

Every lookup is scoped to the caller's company; another tenant's agent,
session, connection or binding is a 404. Connection credentials are stored as
a reference only (``credential_ref``) and never returned.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexus.api.deps import (
    CurrentCompanyId,
    CurrentPrincipal,
    DbSession,
    RequireAdmin,
    require_permission,
)
from nexus.governance.ssrf_protection import guard_url
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.mcp_binding import McpBinding
from nexus.models.tool import ToolCatalogEntry, ToolConnection
from nexus.realtime.publish import TOPOLOGY_CHANNEL, publish_event
from nexus.tools.access import (
    BUILTIN_ENDPOINT,
    BUILTIN_TRANSPORT,
    UNCLASSIFIED_RISK,
    check_tool_access,
)
from nexus.tools.context import ExecutionContext

router = APIRouter(tags=["mcp-bindings"])

READ = [require_permission("read", "mcp_binding")]
WRITE = [require_permission("write", "mcp_binding")]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Tool connections
# ---------------------------------------------------------------------------


class ConnectionCreate(BaseModel):
    name: str = Field(max_length=255)
    transport_type: str = Field(default="mcp_remote", max_length=50)
    # Required, except for the ``nexus_builtin`` connection, whose endpoint is fixed.
    endpoint_url: str | None = Field(default=None, max_length=2048)
    auth_kind: str = Field(default="none", max_length=50)
    credential_ref: str | None = Field(default=None, max_length=512)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    endpoint_url: str | None = Field(default=None, max_length=2048)
    auth_kind: str | None = Field(default=None, max_length=50)
    credential_ref: str | None = Field(default=None, max_length=512)
    is_active: bool | None = None


class ConnectionOut(BaseModel):
    id: uuid.UUID
    name: str
    transport_type: str
    endpoint_url: str | None
    auth_kind: str
    has_credential: bool
    health_status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CatalogEntryOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    tool_name: str
    description: str | None
    risk_level: str
    is_active: bool


class CatalogEntryUpdate(BaseModel):
    risk_level: Literal["read", "write", "destructive"] | None = None
    is_active: bool | None = None


def _connection_out(c: ToolConnection) -> ConnectionOut:
    return ConnectionOut(
        id=c.id,
        name=c.name,
        transport_type=c.transport_type,
        endpoint_url=c.endpoint_url,
        auth_kind=c.auth_kind,
        has_credential=bool(c.credential_ref),
        health_status=c.health_status,
        is_active=c.is_active,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _entry_out(e: ToolCatalogEntry) -> CatalogEntryOut:
    return CatalogEntryOut(
        id=e.id,
        connection_id=e.connection_id,
        tool_name=e.tool_name,
        description=e.description,
        risk_level=e.risk_level,
        is_active=e.is_active,
    )


def _guard(url: str) -> None:
    try:
        guard_url(url, field="endpoint_url")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def _get_owned(db: Any, model: Any, row_id: uuid.UUID, company_id: uuid.UUID) -> Any:
    row = (
        await db.execute(select(model).where(model.id == row_id, model.company_id == company_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return row


async def _audit(
    db: Any, company_id: uuid.UUID, action: str, principal: Any, **fields: Any
) -> None:
    from nexus.governance.audit_service import record_audit

    await record_audit(
        company_id,
        action,
        actor_type="user",
        actor_id=principal.user_id and str(principal.user_id),
        db=db,
        **fields,
    )


@router.post(
    "/api/v1/tool-connections",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectionOut,
)
async def create_tool_connection(
    body: ConnectionCreate, company_id: CurrentCompanyId, db: DbSession, principal: RequireAdmin
) -> Any:
    """Register an MCP server for the company. Private hosts are rejected.

    ``transport_type="nexus_builtin"`` registers NEXUS's own inbound MCP tools
    (:mod:`nexus.tools.mcp_server`) instead, so bindings and the catalog govern
    them like any other connection. Its endpoint is fixed and there is one per
    company.
    """
    fields = body.model_dump()
    if body.transport_type == BUILTIN_TRANSPORT:
        existing = (
            await db.execute(
                select(ToolConnection.id).where(
                    ToolConnection.company_id == company_id,
                    ToolConnection.endpoint_url == BUILTIN_ENDPOINT,
                )
            )
        ).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The company already has a builtin tool connection",
            )
        fields["endpoint_url"] = BUILTIN_ENDPOINT
    elif not body.endpoint_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="endpoint_url is required"
        )
    else:
        _guard(body.endpoint_url)
    connection = ToolConnection(company_id=company_id, **fields)
    db.add(connection)
    await db.flush()
    await _audit(
        db, company_id, "tool_connection.create", principal,
        resource_type="tool_connection", resource_id=str(connection.id),
        details={"name": connection.name, "endpoint_url": connection.endpoint_url},
    )
    return _connection_out(connection)


@router.get(
    "/api/v1/tool-connections", response_model=list[ConnectionOut], dependencies=READ
)
async def list_tool_connections(company_id: CurrentCompanyId, db: DbSession) -> Any:
    rows = await db.execute(select(ToolConnection).where(ToolConnection.company_id == company_id))
    return [_connection_out(c) for c in rows.scalars().all()]


@router.patch("/api/v1/tool-connections/{connection_id}", response_model=ConnectionOut)
async def update_tool_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdate,
    company_id: CurrentCompanyId,
    db: DbSession,
    principal: RequireAdmin,
) -> Any:
    connection = await _get_owned(db, ToolConnection, connection_id, company_id)
    changes = body.model_dump(exclude_unset=True)
    if "endpoint_url" in changes and connection.transport_type == BUILTIN_TRANSPORT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The builtin connection's endpoint cannot be changed",
        )
    if changes.get("endpoint_url"):
        _guard(changes["endpoint_url"])
    for key, value in changes.items():
        setattr(connection, key, value)
    connection.updated_at = _utcnow()
    await db.flush()
    await _audit(
        db, company_id, "tool_connection.update", principal,
        resource_type="tool_connection", resource_id=str(connection.id),
        details={"fields": sorted(k for k in changes if k != "credential_ref")},
    )
    return _connection_out(connection)


@router.get(
    "/api/v1/tool-connections/{connection_id}/tools",
    response_model=list[CatalogEntryOut],
    dependencies=READ,
)
async def list_connection_tools(
    connection_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> Any:
    await _get_owned(db, ToolConnection, connection_id, company_id)
    rows = await db.execute(
        select(ToolCatalogEntry).where(ToolCatalogEntry.connection_id == connection_id)
    )
    return [_entry_out(e) for e in rows.scalars().all()]


@router.post(
    "/api/v1/tool-connections/{connection_id}/discover",
    response_model=list[CatalogEntryOut],
)
async def discover_connection_tools(
    connection_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession, principal: RequireAdmin
) -> Any:
    """List the server's tools into the catalog.

    New tools start as ``write`` risk until an admin classifies them, so a
    policy that restricts writes also covers tools nobody has reviewed.
    Existing entries keep their risk level and active flag. The builtin
    connection lists NEXUS's own inbound MCP tools, with new entries taking
    the node's read/write classification.
    """
    connection = await _get_owned(db, ToolConnection, connection_id, company_id)
    risk_of: dict[str, str] = {}
    if connection.transport_type == BUILTIN_TRANSPORT:
        from nexus.tools.mcp_client import MCPTool
        from nexus.tools.mcp_server import exposed_nodes, input_schema_for, risk_level_for

        nodes = exposed_nodes()
        tools = [
            MCPTool(name=n.id, description=n.description, input_schema=input_schema_for(n))
            for n in nodes.values()
        ]
        risk_of = {n.id: risk_level_for(n) for n in nodes.values()}
    else:
        tools = await _discover_remote(db, connection)

    existing = {
        e.tool_name: e
        for e in (
            await db.execute(
                select(ToolCatalogEntry).where(ToolCatalogEntry.connection_id == connection.id)
            )
        ).scalars()
    }
    now = _utcnow()
    for tool in tools:
        entry = existing.get(tool.name)
        if entry is None:
            entry = ToolCatalogEntry(
                company_id=company_id,
                connection_id=connection.id,
                tool_name=tool.name,
                risk_level=risk_of.get(tool.name, UNCLASSIFIED_RISK),
            )
            db.add(entry)
            existing[tool.name] = entry
        entry.description = tool.description
        entry.input_schema = tool.input_schema
        entry.updated_at = now
    connection.health_status = "healthy"
    connection.last_health_check_at = now
    await db.flush()
    await _audit(
        db, company_id, "tool_connection.discover", principal,
        resource_type="tool_connection", resource_id=str(connection.id),
        details={"tools": sorted(t.name for t in tools)},
    )
    return [_entry_out(e) for e in existing.values()]


async def _discover_remote(db: Any, connection: ToolConnection) -> list[Any]:
    """Ask a remote MCP server for its tools, marking the connection's health."""
    from nexus.tools.mcp_client import MCPClient

    if not connection.endpoint_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No endpoint_url")
    _guard(connection.endpoint_url)

    client = MCPClient()
    try:
        await client.connect(connection.endpoint_url)
        return await client.list_tools()
    except Exception as exc:  # noqa: BLE001
        connection.health_status = "unhealthy"
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Discovery failed: {exc}"
        ) from exc
    finally:
        await client.disconnect()


@router.patch(
    "/api/v1/tool-connections/{connection_id}/tools/{entry_id}",
    response_model=CatalogEntryOut,
)
async def update_catalog_entry(
    connection_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: CatalogEntryUpdate,
    company_id: CurrentCompanyId,
    db: DbSession,
    principal: RequireAdmin,
) -> Any:
    """Classify a tool's risk or switch it off for every binding."""
    entry = await _get_owned(db, ToolCatalogEntry, entry_id, company_id)
    if entry.connection_id != connection_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(entry, key, value)
    entry.updated_at = _utcnow()
    await db.flush()
    await _audit(
        db, company_id, "tool_catalog.update", principal,
        resource_type="tool_catalog_entry", resource_id=str(entry.id),
        details={"tool_name": entry.tool_name, **changes},
    )
    return _entry_out(entry)


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


class BindingCreate(BaseModel):
    connection_id: uuid.UUID
    disabled_tools: list[str] = Field(default_factory=list)
    instructions: str | None = None
    status: Literal["active", "disabled"] = "active"


class BindingUpdate(BaseModel):
    disabled_tools: list[str] | None = None
    instructions: str | None = None
    status: Literal["active", "disabled"] | None = None


class BindingOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    target_type: str
    agent_id: uuid.UUID | None
    session_id: uuid.UUID | None
    disabled_tools: list[str]
    instructions: str | None
    status: str
    version: int
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


def _binding_out(b: McpBinding) -> BindingOut:
    return BindingOut.model_validate(b, from_attributes=True)


async def _announce(db: Any, event_type: str, company_id: uuid.UUID, binding: BindingOut) -> None:
    """Commit, then tell the tenant's Canvas the binding changed."""
    await db.commit()
    await publish_event(
        TOPOLOGY_CHANNEL,
        event_type,
        company_id,
        {
            "binding_id": str(binding.id),
            "connection_id": str(binding.connection_id),
            "agent_id": binding.agent_id and str(binding.agent_id),
            "session_id": binding.session_id and str(binding.session_id),
            "status": binding.status,
        },
    )


def _actor(principal: Any) -> str | None:
    return str(principal.user_id or principal.api_key_id or principal.kind)


async def _create_binding(
    db: Any, company_id: uuid.UUID, principal: Any, body: BindingCreate, **target: Any
) -> McpBinding:
    await _get_owned(db, ToolConnection, body.connection_id, company_id)
    duplicate = (
        await db.execute(
            select(McpBinding.id).where(
                McpBinding.connection_id == body.connection_id,
                *(getattr(McpBinding, k) == v for k, v in target.items() if k != "target_type"),
            )
        )
    ).first()
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Binding already exists for this target"
        )
    binding = McpBinding(
        company_id=company_id,
        created_by=_actor(principal),
        updated_by=_actor(principal),
        **body.model_dump(),
        **target,
    )
    db.add(binding)
    await db.flush()
    await _audit(
        db, company_id, "mcp_binding.create", principal,
        resource_type="mcp_binding", resource_id=str(binding.id),
        details=_binding_out(binding).model_dump(mode="json"),
    )
    await _announce(db, "mcp_binding.created", company_id, _binding_out(binding))
    return binding


@router.post(
    "/api/v1/agents/{agent_id}/mcp-bindings",
    status_code=status.HTTP_201_CREATED,
    response_model=BindingOut,
    dependencies=WRITE,
)
async def create_agent_binding(
    agent_id: uuid.UUID,
    body: BindingCreate,
    company_id: CurrentCompanyId,
    db: DbSession,
    principal: CurrentPrincipal,
) -> Any:
    await _get_owned(db, Agent, agent_id, company_id)
    binding = await _create_binding(
        db, company_id, principal, body, target_type="agent", agent_id=agent_id
    )
    return _binding_out(binding)


@router.post(
    "/api/v1/sessions/{session_id}/mcp-bindings",
    status_code=status.HTTP_201_CREATED,
    response_model=BindingOut,
    dependencies=WRITE,
)
async def create_session_binding(
    session_id: uuid.UUID,
    body: BindingCreate,
    company_id: CurrentCompanyId,
    db: DbSession,
    principal: CurrentPrincipal,
) -> Any:
    await _get_owned(db, AgentSessionRecord, session_id, company_id)
    binding = await _create_binding(
        db, company_id, principal, body, target_type="session", session_id=session_id
    )
    return _binding_out(binding)


@router.get(
    "/api/v1/agents/{agent_id}/mcp-bindings", response_model=list[BindingOut], dependencies=READ
)
async def list_agent_bindings(
    agent_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> Any:
    await _get_owned(db, Agent, agent_id, company_id)
    rows = await db.execute(
        select(McpBinding).where(
            McpBinding.company_id == company_id, McpBinding.agent_id == agent_id
        )
    )
    return [_binding_out(b) for b in rows.scalars().all()]


@router.get(
    "/api/v1/sessions/{session_id}/mcp-bindings",
    response_model=list[BindingOut],
    dependencies=READ,
)
async def list_session_bindings(
    session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> Any:
    """The session's own bindings plus the ones it inherits from its agent."""
    record = await _get_owned(db, AgentSessionRecord, session_id, company_id)
    rows = await db.execute(
        select(McpBinding).where(
            McpBinding.company_id == company_id,
            (McpBinding.session_id == session_id) | (McpBinding.agent_id == record.agent_id),
        )
    )
    return [_binding_out(b) for b in rows.scalars().all()]


@router.patch(
    "/api/v1/mcp-bindings/{binding_id}", response_model=BindingOut, dependencies=WRITE
)
async def update_binding(
    binding_id: uuid.UUID,
    body: BindingUpdate,
    company_id: CurrentCompanyId,
    db: DbSession,
    principal: CurrentPrincipal,
) -> Any:
    binding = await _get_owned(db, McpBinding, binding_id, company_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(binding, key, value)
    binding.version += 1
    binding.updated_by = _actor(principal)
    binding.updated_at = _utcnow()
    await db.flush()
    await _audit(
        db, company_id, "mcp_binding.update", principal,
        resource_type="mcp_binding", resource_id=str(binding.id),
        details={"version": binding.version, **changes},
    )
    out = _binding_out(binding)
    await _announce(db, "mcp_binding.updated", company_id, out)
    return out


@router.delete(
    "/api/v1/mcp-bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=WRITE,
)
async def delete_binding(
    binding_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession, principal: CurrentPrincipal
) -> None:
    binding = await _get_owned(db, McpBinding, binding_id, company_id)
    removed = _binding_out(binding)
    details = removed.model_dump(mode="json")
    await db.delete(binding)
    await db.flush()
    await _audit(
        db, company_id, "mcp_binding.delete", principal,
        resource_type="mcp_binding", resource_id=str(binding_id), details=details,
    )
    await _announce(db, "mcp_binding.deleted", company_id, removed)


# ---------------------------------------------------------------------------
# Effective tools
# ---------------------------------------------------------------------------


class EffectiveTool(BaseModel):
    connection_id: uuid.UUID
    tool_name: str
    risk_level: str
    outcome: str
    problems: list[dict[str, Any]]


async def _effective_tools(
    db: Any, agent_id: uuid.UUID, company_id: uuid.UUID, session_id: uuid.UUID | None = None
) -> list[EffectiveTool]:
    """Run the server-side access check for every catalog tool in scope."""
    targets = McpBinding.agent_id == agent_id
    if session_id is not None:
        targets = targets | (McpBinding.session_id == session_id)
    connection_ids = set(
        (
            await db.execute(
                select(McpBinding.connection_id).where(McpBinding.company_id == company_id, targets)
            )
        ).scalars()
    )
    if not connection_ids:
        return []
    entries = (
        await db.execute(
            select(ToolCatalogEntry).where(ToolCatalogEntry.connection_id.in_(connection_ids))
        )
    ).scalars().all()
    # A preview of what the agent itself may call, so it is evaluated as the
    # agent principal; a human-started run may be narrower (by RBAC role).
    ctx = ExecutionContext(
        company_id=company_id,
        principal_id=f"agent:{agent_id}",
        principal_role="agent",
        source="effective_tools",
        agent_id=agent_id,
        session_id=session_id,
    )
    out = []
    for entry in entries:
        decision = await check_tool_access(
            db, ctx, tool_name=entry.tool_name, connection_id=entry.connection_id
        )
        out.append(
            EffectiveTool(
                connection_id=entry.connection_id,
                tool_name=entry.tool_name,
                risk_level=decision.risk_level,
                outcome=decision.outcome,
                problems=decision.problems,
            )
        )
    return out


@router.get(
    "/api/v1/agents/{agent_id}/effective-tools",
    response_model=list[EffectiveTool],
    dependencies=READ,
)
async def agent_effective_tools(
    agent_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> Any:
    await _get_owned(db, Agent, agent_id, company_id)
    return await _effective_tools(db, agent_id, company_id)


@router.get(
    "/api/v1/sessions/{session_id}/effective-tools",
    response_model=list[EffectiveTool],
    dependencies=READ,
)
async def session_effective_tools(
    session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> Any:
    record = await _get_owned(db, AgentSessionRecord, session_id, company_id)
    return await _effective_tools(db, record.agent_id, company_id, session_id)
