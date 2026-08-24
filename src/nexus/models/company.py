"""Company and organizational structure models."""

import uuid
from datetime import timezone, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Company(SQLModel, table=True):
    """Top-level tenant entity representing an autonomous AI company."""

    __tablename__ = "companies"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255, index=True)
    description: Optional[str] = Field(default=None)
    status: str = Field(default="active", max_length=50)
    budget_monthly_cents: int = Field(default=0)
    spent_monthly_cents: int = Field(default=0)
    issue_prefix: Optional[str] = Field(default=None, max_length=10)
    # Business hours (Corporate Clock from AI-Company)
    business_hours_start: int = Field(default=9)   # 0-23 UTC hour
    business_hours_end: int = Field(default=17)    # 0-23 UTC hour
    business_days: str = Field(default="mon,tue,wed,thu,fri", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class CompanyMembership(SQLModel, table=True):
    """Membership linking users to companies with a role."""

    __tablename__ = "company_memberships"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    user_id: uuid.UUID = Field(index=True)
    role: str = Field(default="member", max_length=50)
    joined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class Department(SQLModel, table=True):
    """Organizational department within a company."""

    __tablename__ = "departments"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    head_agent_id: Optional[uuid.UUID] = Field(default=None)
    budget_monthly_cents: int = Field(default=0)
    parent_department_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="departments.id"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class Team(SQLModel, table=True):
    """Team within a department."""

    __tablename__ = "teams"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    department_id: uuid.UUID = Field(foreign_key="departments.id", index=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
