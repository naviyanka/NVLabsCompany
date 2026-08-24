"""Chat message model for persistent conversation history."""

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ChatMessage(SQLModel, table=True):
    """A single message in an agent conversation, persisted to database."""

    __tablename__ = "chat_messages"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    sender: str = Field(max_length=20)  # "user" or "agent"
    text: str
    conversation_id: Optional[str] = Field(default=None, max_length=255, index=True)
    model_used: Optional[str] = Field(default=None, max_length=100)
    tokens_used: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
