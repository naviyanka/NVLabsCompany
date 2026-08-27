"""Secret management API endpoints.

IMPORTANT: Secret values must NEVER be returned in API responses.
Only metadata (name, category, version, timestamps) is exposed.
"""

import uuid
from datetime import timezone, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from cryptography.fernet import Fernet

from nexus.api.deps import CurrentCompanyId, DbSession, require_permission
from nexus.config import settings
from nexus.governance.secret_backend import FernetSecretBackend, _derive_fernet_key
from nexus.models.secret import Secret, SecretBinding, SecretVersion

_DEV_DEFAULT_SECRET_KEY = "dev-secret-key-change-in-production"


def _make_fernet() -> Fernet | None:
    """Derive the row-encryption key from the app secret, or None if unsafe.

    Fail-closed: an unset or still-default SECRET_KEY yields no encryptor, so
    write endpoints reject rather than store secrets under a known key.
    """
    key = settings.secret_key
    if not key or key == _DEV_DEFAULT_SECRET_KEY:
        return None
    return Fernet(
        _derive_fernet_key(
            key, FernetSecretBackend._SALT, FernetSecretBackend._ITERATIONS
        )
    )


_fernet = _make_fernet()


def _encrypt(plaintext: str) -> str:
    if _fernet is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Secret encryption unavailable: SECRET_KEY is unset or still "
                "the development default."
            ),
        )
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

router = APIRouter(tags=["secrets"])


# --- Request/Response Models ---


class SecretCreate(BaseModel):
    """Request body for creating a secret."""

    name: str
    category: str = "general"
    value: str  # Accepted on input but NEVER returned
    expires_at: datetime | None = None


class SecretMetadataResponse(BaseModel):
    """Response model for secret metadata. NEVER includes the value."""

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    category: str
    current_version: int
    expires_at: datetime | None = None
    is_revoked: bool
    created_at: datetime
    updated_at: datetime


class SecretBindRequest(BaseModel):
    """Request body for binding a secret to an agent."""

    agent_id: uuid.UUID
    expires_at: datetime | None = None
    one_time_use: bool = False


class SecretBindResponse(BaseModel):
    """Response model for a secret binding."""

    id: uuid.UUID
    secret_id: uuid.UUID
    agent_id: uuid.UUID
    granted_at: datetime
    expires_at: datetime | None = None
    one_time_use: bool
    revoked: bool


class SecretRotateRequest(BaseModel):
    """Request body for rotating a secret."""

    new_value: str  # Accepted on input but NEVER returned


# --- Routes ---


@router.post(
    "/api/v1/secrets",
    status_code=status.HTTP_201_CREATED,
    response_model=SecretMetadataResponse,
    dependencies=[require_permission("write", "secret")],
)
async def create_secret(
    body: SecretCreate,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Create a new managed secret.

    The value is stored encrypted. Responses only include metadata.
    """
    encrypted_value = _encrypt(body.value)

    secret = Secret(
        company_id=company_id,
        name=body.name,
        category=body.category,
        encrypted_value=encrypted_value,
        current_version=1,
        expires_at=body.expires_at,
    )
    db.add(secret)
    await db.flush()

    # Create initial version record
    version = SecretVersion(
        secret_id=secret.id,
        version_number=1,
        encrypted_value=encrypted_value,
    )
    db.add(version)
    await db.flush()

    return secret


@router.get(
    "/api/v1/secrets",
    response_model=list[SecretMetadataResponse],
    dependencies=[require_permission("read", "secret")],
)
async def list_secrets(
    db: DbSession,
    company_id: CurrentCompanyId,
    include_revoked: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List secrets for the current company.

    Returns metadata only - secret values are NEVER included in responses.
    """
    stmt = select(Secret).where(Secret.company_id == company_id)
    if not include_revoked:
        stmt = stmt.where(Secret.is_revoked == False)  # noqa: E712
    stmt = stmt.order_by(Secret.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/secrets/{secret_id}/bind",
    status_code=status.HTTP_201_CREATED,
    response_model=SecretBindResponse,
    dependencies=[require_permission("write", "secret")],
)
async def bind_secret(
    secret_id: uuid.UUID,
    body: SecretBindRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Bind a secret to an agent, granting access."""
    # Verify secret exists and belongs to company
    stmt = select(Secret).where(
        Secret.id == secret_id, Secret.company_id == company_id
    )
    result = await db.execute(stmt)
    secret = result.scalar_one_or_none()

    if not secret:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret {secret_id} not found",
        )

    if secret.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot bind a revoked secret",
        )

    binding = SecretBinding(
        secret_id=secret_id,
        agent_id=body.agent_id,
        expires_at=body.expires_at,
        one_time_use=body.one_time_use,
    )
    db.add(binding)
    await db.flush()

    return binding


@router.post(
    "/api/v1/secrets/{secret_id}/revoke",
    response_model=SecretMetadataResponse,
    dependencies=[require_permission("write", "secret")],
)
async def revoke_secret(
    secret_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Revoke a secret, invalidating all bindings."""
    stmt = (
        update(Secret)
        .where(Secret.id == secret_id, Secret.company_id == company_id)
        .values(is_revoked=True, updated_at=datetime.now(timezone.utc))
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret {secret_id} not found",
        )

    # Also revoke all active bindings
    await db.execute(
        update(SecretBinding)
        .where(SecretBinding.secret_id == secret_id, SecretBinding.revoked == False)  # noqa: E712
        .values(revoked=True)
    )

    query = await db.execute(select(Secret).where(Secret.id == secret_id))
    return query.scalar_one()


@router.post(
    "/api/v1/secrets/{secret_id}/rotate",
    response_model=SecretMetadataResponse,
    dependencies=[require_permission("write", "secret")],
)
async def rotate_secret(
    secret_id: uuid.UUID,
    body: SecretRotateRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Rotate a secret to a new version.

    Creates a new version with the provided value and increments the
    current version number. Old versions are marked as revoked.
    """
    # Verify secret exists and belongs to company
    stmt = select(Secret).where(
        Secret.id == secret_id, Secret.company_id == company_id
    )
    result = await db.execute(stmt)
    secret = result.scalar_one_or_none()

    if not secret:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret {secret_id} not found",
        )

    if secret.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot rotate a revoked secret",
        )

    new_version_number = secret.current_version + 1

    # Encrypt the new secret value before storage
    encrypted_new_value = _encrypt(body.new_value)

    # Revoke old version
    await db.execute(
        update(SecretVersion)
        .where(
            SecretVersion.secret_id == secret_id,
            SecretVersion.revoked_at == None,  # noqa: E711
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )

    # Create new version
    new_version = SecretVersion(
        secret_id=secret_id,
        version_number=new_version_number,
        encrypted_value=encrypted_new_value,
    )
    db.add(new_version)

    # Update secret metadata
    await db.execute(
        update(Secret)
        .where(Secret.id == secret_id)
        .values(
            current_version=new_version_number,
            encrypted_value=encrypted_new_value,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()

    # Return updated metadata (never the value)
    query = await db.execute(select(Secret).where(Secret.id == secret_id))
    return query.scalar_one()
