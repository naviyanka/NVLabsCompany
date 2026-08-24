"""Policy models: policies, policy rules, and policy versions."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Policy(SQLModel, table=True):
    """A governance policy that defines rules for system behavior."""

    __tablename__ = "policies"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    rules: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    priority: int = Field(default=0)
    enabled: bool = Field(default=True)
    version: int = Field(default=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class PolicyRule(SQLModel, table=True):
    """An individual rule within a policy."""

    __tablename__ = "policy_rules"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    policy_id: uuid.UUID = Field(foreign_key="policies.id", index=True)
    rule_type: str = Field(max_length=100)
    conditions: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class PolicyVersion(SQLModel, table=True):
    """A versioned snapshot of a policy's rules for audit trail."""

    __tablename__ = "policy_versions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    policy_id: uuid.UUID = Field(foreign_key="policies.id", index=True)
    version_number: int = Field(default=1)
    rules_snapshot: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    changed_by: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
