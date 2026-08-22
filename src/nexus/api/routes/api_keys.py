"""API Key management endpoints."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import DbSession
from nexus.models.api_key import ApiKey

router = APIRouter(tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str
    description: str | None = None
    environment: str = "production"


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None
    key_prefix: str
    environment: str
    status: str
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class ApiKeyCreateResponse(ApiKeyResponse):
    """Returned only on creation — includes the full key (only time it's shown)."""
    full_key: str


@router.get("/api/v1/companies/{company_id}/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(company_id: uuid.UUID, db: DbSession) -> Any:
    """List all API keys for a company (keys are masked)."""
    stmt = select(ApiKey).where(ApiKey.company_id == company_id).order_by(ApiKey.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/api/v1/companies/{company_id}/api-keys", status_code=status.HTTP_201_CREATED, response_model=ApiKeyCreateResponse)
async def create_api_key(company_id: uuid.UUID, body: ApiKeyCreate, db: DbSession) -> Any:
    """Generate a new API key. The full key is returned ONLY in this response."""
    raw_key = ApiKey.generate_key()
    key = ApiKey(
        company_id=company_id,
        name=body.name,
        description=body.description,
        key_prefix=ApiKey.get_prefix(raw_key),
        key_hash=ApiKey.hash_key(raw_key),
        environment=body.environment,
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
        "last_used_at": key.last_used_at,
        "expires_at": key.expires_at,
        "created_at": key.created_at,
        "full_key": raw_key,
    }


@router.post("/api/v1/api-keys/{key_id}/revoke")
async def revoke_api_key(key_id: uuid.UUID, db: DbSession) -> dict:
    """Revoke an API key."""
    stmt = update(ApiKey).where(ApiKey.id == key_id).values(status="revoked")
    result = await db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"id": str(key_id), "status": "revoked"}


@router.delete("/api/v1/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(key_id: uuid.UUID, db: DbSession) -> None:
    """Permanently delete an API key."""
    from sqlalchemy import delete as sa_delete
    stmt = sa_delete(ApiKey).where(ApiKey.id == key_id)
    await db.execute(stmt)
