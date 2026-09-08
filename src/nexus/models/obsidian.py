"""Obsidian vault document identity and index state (ADR 0002 §17).

The vault owns the note body; this table owns everything needed to find that
body again after a human moves or renames the file, and to tell whether the
derived `knowledge_chunks` rows are still current.

`vault_path` is a mutable attribute, never an identity: `nexus_id` is minted by
NEXUS and mirrored into the note's frontmatter, so a `nexus_id` seen at a new
path is a move rather than a new document plus an orphan.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

# index_status values. `partial` means the body indexed but its vectors did not
# (see ADR 0002 §21 — a width mismatch must surface, not degrade silently).
INDEX_STATUS_INDEXED = "indexed"
INDEX_STATUS_PARTIAL = "partial"
INDEX_STATUS_FAILED = "failed"
INDEX_STATUS_STALE = "stale"

# Attempts allowed before a `failed` document stops being retried. Deliberately
# small: an indexing failure that survives three tries is a real problem for an
# operator to look at, not something to keep grinding on. A non-retryable failure
# (a security rejection, a deterministic parse error) is charged the whole budget
# at once, so it is excluded from the next pass without needing its own status.
MAX_INDEX_ATTEMPTS = 3


class VaultWriteGrantRecord(SQLModel, table=True):
    """Database-backed per-agent authority for one vault subtree."""

    __tablename__ = "vault_write_grants"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    tool_id: uuid.UUID = Field(foreign_key="tools.id", index=True)
    subtree: str = Field(max_length=1024)
    granted_by: Optional[str] = Field(default=None, max_length=255)
    granted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    revoked_at: Optional[datetime] = Field(default=None, index=True)


class ObsidianDocument(SQLModel, table=True):
    """A vault note NEXUS has seen, and the state of its derived index."""

    __tablename__ = "obsidian_documents"
    # Mirrors migration c2f9a4d81b70. Declared here too, otherwise the
    # create_all path used by dev SQLite and every test would accept duplicate
    # rows that PostgreSQL rejects.
    __table_args__ = (
        UniqueConstraint(
            "company_id", "vault_path", name="uq_obsidian_documents_company_path"
        ),
    )

    nexus_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    # Vault-relative POSIX path, e.g. "Knowledge/SSRF Protection.md". Relative
    # so a vault root move does not invalidate every row.
    vault_path: str = Field(max_length=1024, index=True)
    doc_type: Optional[str] = Field(default=None, max_length=50, index=True)
    title: Optional[str] = Field(default=None, max_length=500)
    content_hash: str = Field(max_length=64)
    mtime: datetime
    # Wikilink targets parsed out of the note (ADR 0002 §14). The link text a
    # human wrote, not resolved ids: a link may name a note that does not exist
    # yet, and that dangling state is information the graph shows rather than an
    # error. Stored here so deriving the graph is a query, not a vault re-read;
    # edges themselves stay derive-on-read, with no edge table.
    wikilink_targets: Optional[list[str]] = Field(
        default=None, sa_column=Column(JSON)
    )
    index_status: str = Field(default=INDEX_STATUS_STALE, max_length=20, index=True)
    embedding_model: Optional[str] = Field(default=None, max_length=100)
    embedding_dimension: Optional[int] = Field(default=None)
    indexed_at: Optional[datetime] = Field(default=None)
    # Retry state. Counts consecutive failures, reset to 0 on any success, so a
    # document that fails once and then indexes does not carry the failure into
    # its next edit. A row at MAX_INDEX_ATTEMPTS is excluded from the next pass:
    # that is the bound that keeps failed -> retry -> failed from looping.
    attempt_count: int = Field(default=0)
    last_attempt_at: Optional[datetime] = Field(default=None)
    # Safe reason only (see obsidian.security.safe_reason) — this is returned to
    # API clients, so it must never carry an absolute host path.
    last_error: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: Optional[datetime] = Field(default=None)
