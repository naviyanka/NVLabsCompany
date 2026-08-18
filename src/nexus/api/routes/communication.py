"""Communication API endpoints - messaging, groups, and events."""

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.communication import Event, Group, GroupMember, Message

router = APIRouter(tags=["communication"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class SendMessageRequest(BaseModel):
    """Request body for sending a direct message."""

    sender_agent_id: uuid.UUID
    recipient_agent_id: uuid.UUID
    message_type: str
    content: str
    priority: str = "normal"
    metadata: Optional[dict[str, Any]] = None


class MessageResponse(BaseModel):
    """Response model for a message."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: uuid.UUID
    company_id: uuid.UUID
    sender_agent_id: uuid.UUID
    recipient_agent_id: Optional[uuid.UUID] = None
    group_id: Optional[uuid.UUID] = None
    message_type: str
    priority: str
    content: str
    metadata: Optional[dict[str, Any]] = Field(default=None, validation_alias="msg_metadata")
    delivered: bool
    delivery_route: str
    created_at: datetime


class CreateGroupRequest(BaseModel):
    """Request body for creating a communication group."""

    name: str
    description: Optional[str] = None
    agent_ids: list[uuid.UUID] = []


class GroupResponse(BaseModel):
    """Response model for a group."""

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: Optional[str] = None
    created_at: datetime


class SendGroupMessageRequest(BaseModel):
    """Request body for sending a message to a group."""

    sender_agent_id: uuid.UUID
    message_type: str
    content: str
    priority: str = "normal"
    metadata: Optional[dict[str, Any]] = None


class PublishEventRequest(BaseModel):
    """Request body for publishing an event."""

    event_type: str
    source_agent_id: uuid.UUID
    payload: Optional[dict[str, Any]] = None


class EventResponse(BaseModel):
    """Response model for an event."""

    id: uuid.UUID
    company_id: uuid.UUID
    event_type: str
    source_agent_id: uuid.UUID
    payload: Optional[dict[str, Any]] = None
    handled: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Message Routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageResponse,
)
async def send_message(
    company_id: uuid.UUID, body: SendMessageRequest, db: DbSession
) -> Any:
    """Send a direct message between agents."""
    message = Message(
        company_id=company_id,
        sender_agent_id=body.sender_agent_id,
        recipient_agent_id=body.recipient_agent_id,
        message_type=body.message_type,
        content=body.content,
        priority=body.priority,
        msg_metadata=body.metadata,
        delivery_route="direct",
    )
    db.add(message)
    await db.flush()
    return message


@router.get(
    "/api/v1/companies/{company_id}/messages",
    response_model=list[MessageResponse],
)
async def list_messages(
    company_id: uuid.UUID,
    db: DbSession,
    agent_id: Optional[uuid.UUID] = None,
    message_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List messages for a company with optional filters."""
    stmt = select(Message).where(Message.company_id == company_id)
    if agent_id:
        stmt = stmt.where(
            (Message.sender_agent_id == agent_id)
            | (Message.recipient_agent_id == agent_id)
        )
    if message_type:
        stmt = stmt.where(Message.message_type == message_type)
    stmt = stmt.offset(offset).limit(limit).order_by(Message.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Group Routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/groups",
    status_code=status.HTTP_201_CREATED,
    response_model=GroupResponse,
)
async def create_group(
    company_id: uuid.UUID, body: CreateGroupRequest, db: DbSession
) -> Any:
    """Create a communication group."""
    group = Group(
        company_id=company_id,
        name=body.name,
        description=body.description,
    )
    db.add(group)
    await db.flush()

    # Add members
    for agent_id in body.agent_ids:
        member = GroupMember(group_id=group.id, agent_id=agent_id)
        db.add(member)
    await db.flush()

    return group


@router.get(
    "/api/v1/companies/{company_id}/groups",
    response_model=list[GroupResponse],
)
async def list_groups(company_id: uuid.UUID, db: DbSession) -> Any:
    """List communication groups for a company."""
    stmt = select(Group).where(Group.company_id == company_id).order_by(Group.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/groups/{group_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageResponse,
)
async def send_group_message(
    group_id: uuid.UUID, body: SendGroupMessageRequest, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Send a message to a group."""
    # Verify group exists and belongs to company
    stmt = select(Group).where(Group.id == group_id, Group.company_id == company_id)
    result = await db.execute(stmt)
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group {group_id} not found",
        )

    message = Message(
        company_id=group.company_id,
        sender_agent_id=body.sender_agent_id,
        group_id=group_id,
        message_type=body.message_type,
        content=body.content,
        priority=body.priority,
        msg_metadata=body.metadata,
        delivery_route="team",
    )
    db.add(message)
    await db.flush()
    return message


@router.get(
    "/api/v1/groups/{group_id}/messages",
    response_model=list[MessageResponse],
)
async def get_group_messages(
    group_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """Get message history for a group."""
    # Verify group belongs to company
    group_stmt = select(Group).where(Group.id == group_id, Group.company_id == company_id)
    group_result = await db.execute(group_stmt)
    group = group_result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group {group_id} not found",
        )

    stmt = (
        select(Message)
        .where(Message.group_id == group_id, Message.company_id == company_id)
        .offset(offset)
        .limit(limit)
        .order_by(Message.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Event Routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/events",
    status_code=status.HTTP_201_CREATED,
    response_model=EventResponse,
)
async def publish_event(
    company_id: uuid.UUID, body: PublishEventRequest, db: DbSession
) -> Any:
    """Publish an event for async processing."""
    event = Event(
        company_id=company_id,
        event_type=body.event_type,
        source_agent_id=body.source_agent_id,
        payload=body.payload,
    )
    db.add(event)
    await db.flush()
    return event


@router.get(
    "/api/v1/companies/{company_id}/events",
    response_model=list[EventResponse],
)
async def list_events(
    company_id: uuid.UUID,
    db: DbSession,
    event_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List events for a company with optional type filter."""
    stmt = select(Event).where(Event.company_id == company_id)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    stmt = stmt.offset(offset).limit(limit).order_by(Event.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
