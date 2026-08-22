"""Knowledge models for organizational knowledge base and experience tracking."""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class KnowledgePage(SQLModel, table=True):
    """A versioned knowledge page in the company knowledge base.

    Pages represent structured documentation, guides, policies, or runbooks
    authored by agents. They support draft/published/archived lifecycle and
    versioning for change tracking.
    """

    __tablename__ = "knowledge_pages"
    __table_args__ = {"extend_existing": True}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    title: str = Field(max_length=500)
    content: str
    category: Optional[str] = Field(default=None, max_length=100, index=True)
    tags: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    version: int = Field(default=1)
    author_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id", index=True
    )
    status: str = Field(default="draft", max_length=50)  # draft/published/archived
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: Optional[datetime] = Field(default=None)


class KnowledgeChunk(SQLModel, table=True):
    """A chunked segment of a knowledge page for retrieval and embedding.

    Chunks break long pages into indexable segments with optional embedding
    vectors for semantic search. The chunk_index preserves ordering within
    the source page.
    """

    __tablename__ = "knowledge_chunks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    page_id: uuid.UUID = Field(foreign_key="knowledge_pages.id", index=True)
    content: str
    chunk_index: int = Field(default=0)
    chunk_metadata: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON, name="metadata"))
    embedding_vector: Optional[list[float]] = Field(
        default=None, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class ExperienceRecord(SQLModel, table=True):
    """A record of an agent's experience completing a task.

    Experience records capture the outcome, approach, and lessons learned from
    task execution, enabling agents to learn from past work and improve over time.
    """

    __tablename__ = "experience_records"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    task_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="tasks.id", index=True
    )
    outcome: str = Field(max_length=50)  # success/failure/partial
    approach: Optional[str] = Field(default=None)
    result_quality: Optional[float] = Field(default=None)
    lessons_learned: Optional[str] = Field(default=None)
    tags: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
