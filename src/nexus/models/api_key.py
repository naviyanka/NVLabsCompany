"""API Key model for external service authentication."""

import secrets
import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from nexus.models._time import utcnow


class ApiKey(SQLModel, table=True):
    """An API key for authenticating external services.

    A key authenticates a service principal scoped to one company and carries
    its own role, so a key can be issued with less authority than the admin who
    created it. Only the SHA-256 hash of the key is stored.
    """

    __tablename__ = "api_keys"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=500)
    key_prefix: str = Field(max_length=20)  # First 8 chars for identification
    key_hash: str = Field(max_length=255, index=True)   # SHA-256 hash of full key
    environment: str = Field(default="production", max_length=50)
    status: str = Field(default="active", max_length=20)  # active/expired/revoked
    # Authority granted to requests bearing this key. One of
    # nexus.models.auth.VALID_ROLES; unrecognised values resolve to "viewer".
    role: str = Field(default="viewer", max_length=20)
    created_by: uuid.UUID | None = Field(default=None, foreign_key="user_profiles.id")
    # Timestamps are naive UTC because the underlying columns are declared
    # without a timezone; see nexus.models._time for why.
    last_used_at: datetime | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)

    @staticmethod
    def generate_key() -> str:
        """Generate a new API key with nv_ prefix."""
        return f"nv_{secrets.token_hex(24)}"

    @staticmethod
    def hash_key(key: str) -> str:
        """Hash an API key for storage."""
        import hashlib
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def get_prefix(key: str) -> str:
        """Get the displayable prefix of a key."""
        return key[:10]
