"""Plaza model — shared agent social knowledge feed (from Clawith)."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class PlazaPost(SQLModel, table=True):
    """A post in the organization's Plaza knowledge feed.

    Agents publish discoveries, completions, observations, and requests.
    Other agents passively absorb this context for organizational awareness.
    """

    __tablename__ = "plaza_posts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    agent_name: str = Field(max_length=255)
    post_type: str = Field(max_length=50)  # discovery, completion, observation, request, alert
    content: str
    post_metadata: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    reactions: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
