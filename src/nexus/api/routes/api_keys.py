"""API key management endpoints.

An API key is a credential that authenticates a service caller as a member of
one company with one role, so issuing one is a privilege escalation primitive:
whoever can mint a key can hand out authority that outlives their own session.
Every route here is therefore administrator-only.

The company comes from the caller's principal, not from the path. The path still
carries ``{company_id}`` because the dashboard's URLs are built that way, but a
mismatch is a 403 rather than a cross-tenant read — before, any authenticated
user could list or create keys for any company whose UUID they knew.

The full key is shown exactly once, in the creation response. Only its SHA-256
hash is stored, so a lost key cannot be recovered — it is revoked and replaced.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from nexus.api.deps import DbSession, PathCompanyId, RequireAdmin
from nexus.models._time import utcnow
from nexus.models.api_key import ApiKey
from nexus.models.auth import VALID_ROLES

router = APIRouter(tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str
    description: str | None = None
    environment: str = "production"
    # A key may be issued with less authority than the administrator creating
    # it, which is the point: an integration that only reads dashboards should
    # not hold a credential that can delete agents.
    role: str = "viewer"
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None
    key_prefix: str
    environment: str
    status: str
    role: str
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class ApiKeyCreateResponse(ApiKeyResponse):
    """Returned only on creation — includes the full key (only time it's shown)."""
    full_key: str


@router.get("/api/v1/companies/{company_id}/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    company_id: PathCompanyId, db: DbSession, principal: RequireAdmin
) -> Any:
    """List all API keys for the caller's company (keys are masked)."""
    stmt = (
        select(ApiKey)
        .where(ApiKey.company_id == principal.company_id)
        .order_by(ApiKey.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/companies/{company_id}/api-keys",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiKeyCreateResponse,
)
async def create_api_key(
    company_id: PathCompanyId, body: ApiKeyCreate, db: DbSession, principal: RequireAdmin
) -> Any:
    """Generate a new API key. The full key is returned ONLY in this response."""
    # Rejected rather than silently normalised to "viewer": an administrator who
    # mistypes a role should learn about it now, not when the integration turns
    # out to hold less authority than they meant to grant.
    role = body.role.strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown role '{body.role}'. Valid roles: {list(VALID_ROLES)}",
        )

    expires_at = (
        utcnow() + timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None
        else None
    )

    raw_key = ApiKey.generate_key()
    key = ApiKey(
        company_id=principal.company_id,
        name=body.name,
        description=body.description,
        key_prefix=ApiKey.get_prefix(raw_key),
        key_hash=ApiKey.hash_key(raw_key),
        environment=body.environment,
        role=role,
        expires_at=expires_at,
        created_by=principal.user_id,
    )
    db.add(key)
    await db.flush()

    # Return with full key (only time it's visible)
    return {
        "id": key.id,
        "company_id": key.company_id,
        "name": key.name,
        "description": key.description,
        "key_prefix": key.key_prefix,
        "environment": key.environment,
        "status": key.status,
        "role": key.role,
        "last_used_at": key.last_used_at,
        "expires_at": key.expires_at,
        "created_at": key.created_at,
        "full_key": raw_key,
    }


@router.post("/api/v1/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: uuid.UUID, db: DbSession, principal: RequireAdmin
) -> dict:
    """Revoke an API key.

    The company predicate is part of the UPDATE rather than a separate lookup,
    so a key belonging to another tenant matches nothing and reads as 404
    instead of confirming that the id exists.
    """
    stmt = (
        update(ApiKey)
        .where(ApiKey.id == key_id, ApiKey.company_id == principal.company_id)
        .values(status="revoked")
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"id": str(key_id), "status": "revoked"}


@router.delete("/api/v1/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: uuid.UUID, db: DbSession, principal: RequireAdmin
) -> None:
    """Permanently delete an API key."""
    from sqlalchemy import delete as sa_delete

    stmt = sa_delete(ApiKey).where(
        ApiKey.id == key_id, ApiKey.company_id == principal.company_id
    )
    await db.execute(stmt)
