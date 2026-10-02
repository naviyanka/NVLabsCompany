"""Append-only evidence for memory trust, and the ledger that makes each change replayable.

``memory_evidence`` rows are created only by ``nexus.memory.evidence`` and never change:
the table refuses UPDATE and DELETE (ORM guard here, trigger in the migration), and every
foreign key is RESTRICT, so deleting a memory, company or user cannot erase the history.
A row stores ids, a grade the server derived and a digest of the source's qualifying
state. It never stores memory text, chat text, tool arguments or deliverables.

``memory_operations`` is the idempotency ledger for the four mutating memory-evidence
operations. It is unique per (company, idempotency key); the request digest tells a
retry from a key reused for something else, and ``result`` holds ids and states only.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Index, UniqueConstraint, event
from sqlmodel import Column, Field, SQLModel

from nexus.models._time import utcnow

EVIDENCE_KINDS = ("human_attestation", "chat_turn", "tool_invocation", "task_attempt")
SOURCE_TYPES = ("user", "chat_turn", "tool_invocation", "task_attempt")
# What the evidence can support. ``none`` is recorded provenance that qualifies for nothing.
EVIDENCE_GRADES = ("none", "assert", "verify")
OPERATIONS = ("attach_evidence", "accept_candidate", "assert_trust", "verify_trust")
POLICY_VERSION = "memory-evidence-v1"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class MemoryEvidence(SQLModel, table=True):
    """One immutable piece of evidence about one memory."""

    __tablename__ = "memory_evidence"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "memory_id", "source_type", "source_id", "reason_code",
            name="uq_memory_evidence_source",
        ),
        UniqueConstraint("company_id", "idempotency_key", name="uq_memory_evidence_idempotency"),
        CheckConstraint(_in("evidence_kind", EVIDENCE_KINDS), name="ck_memory_evidence_kind"),
        CheckConstraint(_in("source_type", SOURCE_TYPES), name="ck_memory_evidence_source_type"),
        CheckConstraint(_in("grade", EVIDENCE_GRADES), name="ck_memory_evidence_grade"),
        Index("ix_memory_evidence_company_memory", "company_id", "memory_id"),
        Index("ix_memory_evidence_company_source", "company_id", "source_type", "source_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", ondelete="RESTRICT")
    memory_id: uuid.UUID = Field(foreign_key="memory_records.id", ondelete="RESTRICT")
    evidence_kind: str = Field(max_length=30)
    source_type: str = Field(max_length=30)
    source_id: str = Field(max_length=64)
    # Attestation only (a fixed allowlist); '' for every other kind, so the unique key has no NULL.
    reason_code: str = Field(default="", max_length=40)
    grade: str = Field(max_length=10)
    source_digest: str = Field(max_length=64)
    policy_version: str = Field(max_length=40)
    idempotency_key: str = Field(max_length=128)
    created_by: str = Field(max_length=100)
    # Timestamps are naive UTC because the underlying columns are declared
    # without a timezone; see nexus.models._time for why.
    created_at: datetime = Field(default_factory=utcnow)


class MemoryOperation(SQLModel, table=True):
    """One completed evidence/trust operation, keyed by the caller's idempotency key."""

    __tablename__ = "memory_operations"
    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_memory_operations_key"),
        CheckConstraint(_in("operation", OPERATIONS), name="ck_memory_operations_operation"),
        Index("ix_memory_operations_company_memory", "company_id", "memory_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", ondelete="RESTRICT")
    memory_id: uuid.UUID = Field(foreign_key="memory_records.id", ondelete="RESTRICT")
    operation: str = Field(max_length=30)
    idempotency_key: str = Field(max_length=128)
    request_digest: str = Field(max_length=64)
    actor: str = Field(max_length=100)
    result: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


def _immutable(table: str):
    def refuse(_mapper: Any, _conn: Any, _row: Any) -> None:
        raise ValueError(f"{table} is append-only")

    return refuse


for _model, _name in ((MemoryEvidence, "memory_evidence"), (MemoryOperation, "memory_operations")):
    event.listen(_model, "before_update", _immutable(_name))
    event.listen(_model, "before_delete", _immutable(_name))
