"""Tool API endpoints - tool registry and access control."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.tool import Tool, ToolAccess

router = APIRouter(tags=["tools"])


class ToolCreate(BaseModel):
    """Request body for registering a tool."""

    name: str
    description: str | None = None
    tool_type: str
    schema_def: dict[str, Any] | None = None
    endpoint: str | None = None
    risk_level: str = "low"


class ToolAccessGrant(BaseModel):
    """Request body for granting tool access to an agent."""

    tool_id: uuid.UUID
    permission_level: str = "execute"
    granted_by: str | None = None
    expires_at: datetime | None = None


class ToolResponse(BaseModel):
    """Response model for a tool."""

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None = None
    tool_type: str
    schema_def: dict[str, Any] | None = None
    endpoint: str | None = None
    is_active: bool
    risk_level: str
    created_at: datetime


class ToolAccessResponse(BaseModel):
    """Response model for a tool access grant."""

    id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID
    tool_id: uuid.UUID
    granted_by: str | None = None
    permission_level: str
    expires_at: datetime | None = None
    created_at: datetime


@router.post(
    "/api/v1/companies/{company_id}/tools",
    status_code=status.HTTP_201_CREATED,
    response_model=ToolResponse,
)
async def create_tool(
    company_id: uuid.UUID, body: ToolCreate, db: DbSession
) -> Any:
    """Register a new tool in the company."""
    tool = Tool(
        company_id=company_id,
        name=body.name,
        description=body.description,
        tool_type=body.tool_type,
        schema_def=body.schema_def,
        endpoint=body.endpoint,
        risk_level=body.risk_level,
    )
    db.add(tool)
    await db.flush()
    return tool


@router.get(
    "/api/v1/companies/{company_id}/tools",
    response_model=list[ToolResponse],
)
async def list_tools(
    company_id: uuid.UUID,
    db: DbSession,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List tools for a company."""
    stmt = (
        select(Tool)
        .where(Tool.company_id == company_id)
        .offset(offset)
        .limit(limit)
        .order_by(Tool.name)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/agents/{agent_id}/tool-access",
    status_code=status.HTTP_201_CREATED,
    response_model=ToolAccessResponse,
)
async def grant_tool_access(
    agent_id: uuid.UUID, body: ToolAccessGrant, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Grant an agent access to a tool."""
    # Verify tool belongs to company
    tool_stmt = select(Tool).where(Tool.id == body.tool_id, Tool.company_id == company_id)
    tool_result = await db.execute(tool_stmt)
    tool = tool_result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {body.tool_id} not found",
        )

    # Verify agent belongs to company
    from nexus.models.agent import Agent

    agent_stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    access = ToolAccess(
        company_id=company_id,
        agent_id=agent_id,
        tool_id=body.tool_id,
        granted_by=body.granted_by,
        permission_level=body.permission_level,
        expires_at=body.expires_at,
    )
    db.add(access)
    await db.flush()
    return access


@router.get(
    "/api/v1/agents/{agent_id}/tools",
    response_model=list[ToolAccessResponse],
)
async def list_agent_tools(
    agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """List tools an agent has access to."""
    stmt = select(ToolAccess).where(ToolAccess.agent_id == agent_id, ToolAccess.company_id == company_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
