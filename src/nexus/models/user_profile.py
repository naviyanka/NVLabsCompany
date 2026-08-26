"""User profile and session models."""

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from nexus.models._time import utcnow


class UserProfile(SQLModel, table=True):
    """A human login for the platform.

    Doubles as the fastapi-users user table: ``email``, ``hashed_password``,
    ``is_active``, ``is_superuser`` and ``is_verified`` satisfy the
    ``UserProtocol`` that ``SQLAlchemyUserDatabase`` and ``BaseUserManager``
    expect, so no second user table is needed.

    ``company_id`` is the user's home company — the tenant selected right
    after login. Access to any company (including this one) is granted by a
    :class:`~nexus.models.company.CompanyMembership` row, never by this
    column alone.
    """

    __tablename__ = "user_profiles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    email: str = Field(max_length=255, index=True, unique=True)
    hashed_password: str = Field(default="", max_length=255)
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    is_verified: bool = Field(default=False)
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    title: str = Field(default="", max_length=100)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    phone: Optional[str] = Field(default=None, max_length=50)
    timezone: str = Field(default="UTC", max_length=50)
    status: str = Field(default="online", max_length=20)  # online/busy/dnd/offline
    two_factor_enabled: bool = Field(default=False)
    oidc_sub: Optional[str] = Field(default=None, max_length=255)
    last_login_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class UserSession(SQLModel, table=True):
    """A server-side session backing one httpOnly cookie.

    The cookie carries a random opaque token; only its SHA-256 hash is stored,
    so a database leak does not yield usable session credentials. A session is
    valid while ``revoked_at`` is NULL and ``expires_at`` is in the future.
    """

    __tablename__ = "user_sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user_profiles.id", index=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    token_hash: str = Field(default="", max_length=64, index=True, unique=True)
    browser: str = Field(default="", max_length=255)
    ip_address: str = Field(default="", max_length=45)
    location: Optional[str] = Field(default=None, max_length=255)
    is_current: bool = Field(default=False)
    expires_at: Optional[datetime] = Field(default=None)
    revoked_at: Optional[datetime] = Field(default=None)
    last_active_at: datetime = Field(default_factory=utcnow)
    created_at: datetime = Field(default_factory=utcnow)
