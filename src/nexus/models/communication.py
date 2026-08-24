"""Communication models for inter-agent messaging and events."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Message(SQLModel, table=True):
    """A message sent between agents for communication, delegation, or handoff.

    Messages support multiple delivery routes (direct, broadcast, team) and
    types (request, response, notification, delegation, handoff). A correlation_id
    enables deduplication and request-response tracking.
    """

    __tablename__ = "messages"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    sender_agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    recipient_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id", index=True
    )
    group_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="groups.id", index=True
    )
    message_type: str = Field(max_length=50)  # request/response/notification/delegation/handoff
    priority: str = Field(default="normal", max_length=20)  # urgent/normal/low
    content: str
    msg_metadata: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, name="metadata"))
    correlation_id: Optional[str] = Field(default=None, max_length=255, index=True)
    delivered: bool = Field(default=False)
    delivery_route: str = Field(default="direct", max_length=50)  # direct/broadcast/team
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(default=None)


class Group(SQLModel, table=True):
    """A named group of agents for broadcast or team communication.

    Groups enable multi-agent conversations, team channels, and broadcast
    messaging patterns within a company.
    """

    __tablename__ = "groups"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GroupMember(SQLModel, table=True):
    """Membership record linking an agent to a communication group.

    Each member can have a role within the group (e.g., admin, member, observer).
    """

    __tablename__ = "group_members"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    group_id: uuid.UUID = Field(foreign_key="groups.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    role: str = Field(default="member", max_length=50)
    joined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Event(SQLModel, table=True):
    """A system event emitted by an agent for asynchronous processing.

    Events follow a pub/sub pattern where agents can emit events that other
    agents or system components can subscribe to and handle.
    """

    __tablename__ = "events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    event_type: str = Field(max_length=100, index=True)
    source_agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    payload: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    handled: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
