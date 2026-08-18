"""Secret models: secrets, versions, bindings, and access records.

IMPORTANT: Secret values (encrypted_value) must NEVER appear in logs,
error messages, or API responses. Only metadata is exposed.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Secret(SQLModel, table=True):
    """A managed secret with metadata. Values are stored encrypted."""

    __tablename__ = "secrets"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    category: str = Field(default="general", max_length=100)
    encrypted_value: str = Field(max_length=4096, exclude=True)
    current_version: int = Field(default=1)
    expires_at: Optional[datetime] = Field(default=None)
    is_revoked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class SecretVersion(SQLModel, table=True):
    """A versioned snapshot of a secret value."""

    __tablename__ = "secret_versions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    secret_id: uuid.UUID = Field(foreign_key="secrets.id", index=True)
    version_number: int = Field(default=1)
    encrypted_value: str = Field(max_length=4096, exclude=True)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    revoked_at: Optional[datetime] = Field(default=None)


class SecretBinding(SQLModel, table=True):
    """A binding that grants an agent access to a secret."""

    __tablename__ = "secret_bindings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    secret_id: uuid.UUID = Field(foreign_key="secrets.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    granted_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    expires_at: Optional[datetime] = Field(default=None)
    one_time_use: bool = Field(default=False)
    is_used: bool = Field(default=False)
    revoked: bool = Field(default=False)


class SecretAccess(SQLModel, table=True):
    """An audit record of secret access attempts."""

    __tablename__ = "secret_accesses"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    secret_id: uuid.UUID = Field(foreign_key="secrets.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    access_type: str = Field(max_length=50)
    accessed_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    success: bool = Field(default=True)
