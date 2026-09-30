"""Governance Studio tables: policy versions and drafts, temporary access, restrictions.

The active ToolPolicy rules stay in ``tool_policies`` (the one engine). A *version*
is an immutable snapshot of a company's rule set taken when a draft is published
or rolled back; ``(company_id, version_number)`` is unique, so two concurrent
publishes against the same base cannot both win.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017


class GovernancePolicyVersion(SQLModel, table=True):
    """Immutable snapshot of a company's ToolPolicy rules."""

    __tablename__ = "governance_policy_versions"
    __table_args__ = (UniqueConstraint("company_id", "version_number"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    version_number: int
    status: str = Field(default="active", max_length=30)  # active, superseded
    rules_snapshot: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    base_version: int | None = Field(default=None)
    published_by: str = Field(max_length=255)
    reason: str = Field(default="")
    rollback_of: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=_now)


class GovernancePolicyDraft(SQLModel, table=True):
    """A proposed rule set, edited and reviewed before it is published."""

    __tablename__ = "governance_policy_drafts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    base_version: int = Field(default=0)
    proposed_rules: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    reason: str = Field(default="")
    ticket_ref: str | None = Field(default=None, max_length=255)
    created_by: str = Field(max_length=255)
    reviewers: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="draft", max_length=30, index=True)  # draft, published, discarded
    published_version: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class GovernanceTempAccess(SQLModel, table=True):
    """A time-boxed allow or deny for one tool (or a literal-prefix pattern) on one agent."""

    __tablename__ = "governance_temp_access"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    effect: str = Field(max_length=10)  # allow, deny
    tool_name: str = Field(max_length=255)
    risk_level: str = Field(default="low", max_length=30)
    # pending_approval -> active -> (used_up | expired | revoked); rejected is terminal.
    status: str = Field(default="active", max_length=30, index=True)
    starts_at: datetime = Field(default_factory=_now)
    expires_at: datetime
    max_uses: int | None = Field(default=None)
    used_count: int = Field(default=0)
    task_id: uuid.UUID | None = Field(default=None)
    session_id: uuid.UUID | None = Field(default=None)
    reason: str = Field(default="")
    requested_by: str = Field(max_length=255)
    approved_by: str | None = Field(default=None, max_length=255)
    approval_id: uuid.UUID | None = Field(default=None, index=True)
    revoked_by: str | None = Field(default=None, max_length=255)
    revoked_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_now)


class GovernanceRestriction(SQLModel, table=True):
    """Company lockdown or single-agent isolation: a hard deny for write/external tools."""

    __tablename__ = "governance_restrictions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    scope: str = Field(max_length=20)  # company, agent
    agent_id: uuid.UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    kind: str = Field(max_length=20)  # lockdown, isolation
    active: bool = Field(default=True, index=True)
    reason: str
    created_by: str = Field(max_length=255)
    released_by: str | None = Field(default=None, max_length=255)
    released_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_now)
