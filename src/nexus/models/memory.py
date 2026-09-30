"""Memory record model for the 3-temperature memory system."""

import hashlib
import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON, CheckConstraint, Index, UniqueConstraint, event
from sqlmodel import Column, Field, SQLModel

# Closed vocabularies, enforced by check constraints (not DB enums) so adding a value is
# a plain migration. The migration keeps its own frozen copies.
MEMORY_STATUSES = ("candidate", "active", "archived", "superseded", "rejected")
LIVE_STATUSES = ("candidate", "active")  # what readers may recall
TRUST_STATES = ("untrusted", "asserted", "verified")
MEMORY_TYPES = (
    "fact", "preference", "decision", "directive", "lesson", "procedure", "risk", "error",
    "outcome", "summary", "delegation", "commitment", "hiring", "unknown",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class MemoryRecord(SQLModel, table=True):
    """A memory entry in the 3-temperature memory system (hot/warm/cold).

    Memories can be scoped to an agent, team, or company level.
    The tier field determines the storage temperature:
    - hot: in-memory cache (Redis), frequently accessed
    - warm: database, moderately accessed
    - cold: archive, rarely accessed

    Rows are created only by ``nexus.memory.ingest`` and change state only through
    ``nexus.memory.lifecycle``. ``content``, ``content_hash``, source identity and
    ``ingestion_key`` never change after insert; a correction is a new row that
    supersedes the old one.
    """

    __tablename__ = "memory_records"
    __table_args__ = (
        UniqueConstraint("company_id", "ingestion_key", name="uq_memory_records_ingestion"),
        CheckConstraint(_in("status", MEMORY_STATUSES), name="ck_memory_records_status"),
        CheckConstraint(_in("trust_state", TRUST_STATES), name="ck_memory_records_trust_state"),
        CheckConstraint(_in("memory_type", MEMORY_TYPES), name="ck_memory_records_memory_type"),
        Index("ix_memory_records_company_scope_status", "company_id", "scope", "status", "created_at"),
        Index("ix_memory_records_company_source", "company_id", "source_type", "source_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id", index=True
    )
    scope: str = Field(max_length=50)  # agent, team, department, company
    scope_id: Optional[uuid.UUID] = Field(default=None, index=True)
    content: str
    record_metadata: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON, name="metadata")
    )
    importance: float = Field(default=0.5)
    access_count: int = Field(default=0)
    last_accessed_at: Optional[datetime] = Field(default=None)
    tier: str = Field(default="warm", max_length=20)  # hot, warm, cold
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Canonical ingest and lifecycle. Server-owned: no request may set these.
    memory_type: str = Field(default="unknown", max_length=20)
    status: str = Field(default="active", max_length=20)
    trust_state: str = Field(default="untrusted", max_length=20)
    source_type: Optional[str] = Field(default=None, max_length=40)
    source_id: Optional[str] = Field(default=None, max_length=128)
    source_created_at: Optional[datetime] = Field(default=None)
    extractor_version: Optional[str] = Field(default=None, max_length=40)
    content_hash: str = Field(default="", max_length=64)
    ingestion_key: str = Field(default="", max_length=80)
    supersedes_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="memory_records.id", index=True
    )
    lifecycle_changed_at: Optional[datetime] = Field(default=None)
    lifecycle_changed_by: Optional[str] = Field(default=None, max_length=100)


IMMUTABLE_FIELDS = (
    "company_id", "content", "content_hash", "ingestion_key", "source_type", "source_id",
    "source_created_at", "created_at", "supersedes_id",
)


@event.listens_for(MemoryRecord, "before_insert")
def _fill_identity(_mapper: Any, _conn: Any, row: MemoryRecord) -> None:
    """Rows built outside ingest (tests, fixtures) still satisfy the NOT NULL identity columns."""
    if not row.content_hash:
        row.content_hash = hashlib.sha256(row.content.encode()).hexdigest()
    if not row.ingestion_key:
        row.ingestion_key = f"row:{row.id}"


@event.listens_for(MemoryRecord, "before_update")
def _refuse_rewrite(_mapper: Any, _conn: Any, row: MemoryRecord) -> None:
    """Append-only: an ORM flush may not change content, provenance or identity."""
    from sqlalchemy import inspect

    state = inspect(row)
    for name in IMMUTABLE_FIELDS:
        if state.attrs[name].history.has_changes():
            raise ValueError(f"memory_records.{name} is immutable; supersede the record instead")
