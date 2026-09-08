"""Governance models: approvals, decisions, decision queues, and audit log."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


class Approval(SQLModel, table=True):
    """An approval request for a gated operation."""

    __tablename__ = "approvals"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    type: str = Field(max_length=100)
    requested_by_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id"
    )
    status: str = Field(default="pending", max_length=50)
    payload: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    decision_note: Optional[str] = Field(default=None)
    decided_by: Optional[str] = Field(default=None, max_length=255)
    decided_at: Optional[datetime] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None)
    # How many distinct valid signatures this request needs before it can be
    # approved. 1 keeps every pre-existing approval type behaving exactly as it
    # did; high-risk types (large spend, deployment, destructive file writes) are
    # created with more, so no single compromised operator can wave one through.
    required_signatures: int = Field(default=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class ApprovalSignerKey(SQLModel, table=True):
    """An Ed25519 public key trusted to sign approvals for one company.

    Keys are registered out of band (an operator enrols their key); the private
    half never reaches the platform, which is the whole point -- a database
    breach yields no ability to forge an approval.
    """

    __tablename__ = "approval_signer_keys"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    # Who this key belongs to: an email, user id, or service label. Quorum counts
    # distinct subjects, so one operator with two keys is still one signature.
    subject: str = Field(max_length=255, index=True)
    # Raw Ed25519 public key, base64 (32 bytes decoded).
    public_key: str = Field(max_length=128)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    revoked_at: Optional[datetime] = Field(default=None)


class ApprovalSignature(SQLModel, table=True):
    """One verified signature over an approval's canonical bytes."""

    __tablename__ = "approval_signatures"
    # One signature per party per approval. The service checks this too, but the
    # constraint is what holds when two operators race the same request.
    __table_args__ = (
        UniqueConstraint("approval_id", "subject", name="uq_approval_signature_subject"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    approval_id: uuid.UUID = Field(foreign_key="approvals.id", index=True)
    signer_key_id: uuid.UUID = Field(foreign_key="approval_signer_keys.id")
    # Denormalised so quorum counting and audit reading do not need a join, and
    # so a later key revocation cannot rewrite who signed.
    subject: str = Field(max_length=255)
    # Ed25519 signature over canonical_approval_bytes(), base64.
    signature: str = Field(max_length=128)
    signed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class Decision(SQLModel, table=True):
    """A decision to be made, potentially with multiple options."""

    __tablename__ = "decisions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    title: str = Field(max_length=500)
    body: Optional[str] = Field(default=None)
    options: Optional[list[dict[str, Any]]] = Field(
        default=None, sa_column=Column(JSON)
    )
    status: str = Field(default="open", max_length=50)
    chosen_option_id: Optional[str] = Field(default=None, max_length=255)
    origin_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id"
    )
    decided_by: Optional[str] = Field(default=None, max_length=255)
    decided_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class DecisionQueue(SQLModel, table=True):
    """A queue that collects decisions for review and routing."""

    __tablename__ = "decision_queues"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    auto_approve_policy: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class AuditLog(SQLModel, table=True):
    """Immutable record of every significant action in the system.

    Append-only: a DB trigger rejects DELETE and any UPDATE other than
    ``archived_at``. Rows carry a SHA-256 hash chain
    (``previous_hash`` -> ``entry_hash``) ordered by ``sequence_number``.
    """

    __tablename__ = "audit_log"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="companies.id", index=True
    )
    actor_type: str = Field(max_length=50)  # agent, user, system
    actor_id: Optional[str] = Field(default=None, max_length=255)
    action: str = Field(max_length=255)
    resource_type: Optional[str] = Field(default=None, max_length=100)
    resource_id: Optional[str] = Field(default=None, max_length=255)
    details: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    ip_address: Optional[str] = Field(default=None, max_length=45)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    # Hash-chain columns (Phase 0.1)
    sequence_number: Optional[int] = Field(default=None, index=True, unique=True)
    entry_hash: Optional[str] = Field(default=None, max_length=64)
    previous_hash: Optional[str] = Field(default=None, max_length=64)
    archived_at: Optional[datetime] = Field(default=None)


class AuditLogArchive(SQLModel, table=True):
    """Retention archive: copies of `audit_log` rows past their retention age.

    The source row is never deleted — it stays in the verified chain and is
    only marked with ``archived_at``.
    """

    __tablename__ = "audit_log_archive"

    id: uuid.UUID = Field(primary_key=True)
    company_id: Optional[uuid.UUID] = Field(default=None, index=True)
    actor_type: str = Field(max_length=50)
    actor_id: Optional[str] = Field(default=None, max_length=255)
    action: str = Field(max_length=255)
    resource_type: Optional[str] = Field(default=None, max_length=100)
    resource_id: Optional[str] = Field(default=None, max_length=255)
    details: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    ip_address: Optional[str] = Field(default=None, max_length=45)
    created_at: datetime
    sequence_number: Optional[int] = Field(default=None, index=True)
    entry_hash: Optional[str] = Field(default=None, max_length=64)
    previous_hash: Optional[str] = Field(default=None, max_length=64)
    archived_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
