"""Chat message model for persistent conversation history."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


class ChatMessage(SQLModel, table=True):
    """A single message in an agent conversation, persisted to database."""

    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_chat_messages_session_seq"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    sender: str = Field(max_length=20)  # "user" or "agent"
    text: str
    conversation_id: Optional[str] = Field(default=None, max_length=255, index=True)
    model_used: Optional[str] = Field(default=None, max_length=100)
    tokens_used: int = Field(default=0)
    # Session linkage (nullable: rows that predate sessions, or whose owner
    # could not be determined during backfill, stay unassociated).
    session_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agent_sessions.id", ondelete="CASCADE", index=True
    )
    kind: str = Field(default="message", max_length=20)
    seq: Optional[int] = Field(default=None)
    payload: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
