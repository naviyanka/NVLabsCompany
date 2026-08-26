"""SCIM 2.0 provisioning endpoint for directory sync.

Implements a subset of the SCIM 2.0 protocol (RFC 7644) that external
identity providers (Okta, Azure AD, OneLogin) use to push user lifecycle
events (create, update, deactivate, delete) into NEXUS.

Endpoints:
  GET  /scim/v2/Users          - List/filter users
  GET  /scim/v2/Users/:id      - Get single user
  POST /scim/v2/Users          - Create user (provision)
  PUT  /scim/v2/Users/:id      - Replace user
  PATCH /scim/v2/Users/:id     - Partial update (e.g. deactivate)
  DELETE /scim/v2/Users/:id    - Deprovision user

Auth: Bearer token validated against SCIM_BEARER_TOKEN env var.
"""

import hmac
import logging
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from nexus.api.deps import DbSession
from nexus.auth.sessions import revoke_user_sessions
from nexus.auth.users import grant_membership, pick_setup_company
from nexus.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scim"])

SCIM_SCHEMA_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_SCHEMA_LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"

# Role granted to an IdP-provisioned user. The least-privileged role in
# VALID_ROLES — an external directory should not be able to mint admins.
SCIM_DEFAULT_ROLE = "viewer"


def _verify_scim_token(request: Request) -> None:
    expected = os.environ.get("SCIM_BEARER_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=501, detail="SCIM not configured")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], expected):
        raise HTTPException(status_code=401, detail="Invalid SCIM bearer token")


class ScimName(BaseModel):
    givenName: str = ""
    familyName: str = ""


class ScimEmail(BaseModel):
    value: str
    primary: bool = True


class ScimUserRequest(BaseModel):
    schemas: list[str] = [SCIM_SCHEMA_USER]
    userName: str = ""
    name: Optional[ScimName] = None
    emails: list[ScimEmail] = []
    active: bool = True
    externalId: Optional[str] = None


def _user_to_scim(user: UserProfile) -> dict[str, Any]:
    return {
        "schemas": [SCIM_SCHEMA_USER],
        "id": str(user.id),
        "externalId": user.oidc_sub or "",
        "userName": user.email,
        "name": {
            "givenName": user.first_name,
            "familyName": user.last_name,
        },
        "emails": [{"value": user.email, "primary": True}],
        "active": user.is_active,
        "meta": {
            "resourceType": "User",
            "created": user.created_at.isoformat() if user.created_at else "",
            "lastModified": user.updated_at.isoformat() if user.updated_at else "",
        },
    }


@router.get("/scim/v2/Users")
async def list_users(
    request: Request,
    db: DbSession,
    startIndex: int = 1,
    count: int = 100,
    filter: Optional[str] = None,
) -> dict[str, Any]:
    _verify_scim_token(request)

    stmt = select(UserProfile)

    if filter and 'userName eq' in filter:
        email = filter.split('"')[1] if '"' in filter else ""
        if email:
            stmt = stmt.where(UserProfile.email == email)

    result = await db.execute(stmt.offset(startIndex - 1).limit(count))
    users = result.scalars().all()

    # totalResults is the size of the whole match, not of this page — an IdP pages
    # until startIndex + itemsPerPage exceeds it, so returning the page size makes
    # every full page look like the last one.
    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar() or 0

    return {
        "schemas": [SCIM_SCHEMA_LIST],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": count,
        "Resources": [_user_to_scim(u) for u in users],
    }


@router.get("/scim/v2/Users/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    _verify_scim_token(request)
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_to_scim(user)


@router.post("/scim/v2/Users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: ScimUserRequest,
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    _verify_scim_token(request)

    email = body.userName or (body.emails[0].value if body.emails else "")
    if not email:
        raise HTTPException(status_code=400, detail="userName or email required")

    existing = await db.execute(select(UserProfile).where(UserProfile.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already exists")

    # Resolve the tenant the same way first-run setup and the bootstrap command do
    # instead of hardcoding the seeded development UUID: on a deployment where that
    # row does not exist, a hardcoded company_id writes a user row pointing at a
    # company that is not there.
    company = await pick_setup_company(db)

    user = UserProfile(
        email=email,
        hashed_password="",
        company_id=company.id,
        first_name=body.name.givenName if body.name else "",
        last_name=body.name.familyName if body.name else "",
        is_active=body.active,
        is_verified=True,
        oidc_sub=body.externalId or "",
    )
    db.add(user)
    await db.flush()

    # Without a membership row the provisioned user cannot authenticate at all:
    # authenticate_session() in auth/middleware.py returns None when
    # get_membership() finds nothing, so an IdP-provisioned account would be
    # created and then rejected at every login.
    await grant_membership(db, user_id=user.id, company_id=company.id, role=SCIM_DEFAULT_ROLE)

    await db.commit()
    await db.refresh(user)
    logger.info("SCIM provisioned user %s in company %s", email, company.id)
    return _user_to_scim(user)


@router.put("/scim/v2/Users/{user_id}")
async def replace_user(
    user_id: uuid.UUID,
    body: ScimUserRequest,
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    _verify_scim_token(request)

    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.name:
        user.first_name = body.name.givenName
        user.last_name = body.name.familyName
    user.is_active = body.active
    if body.externalId:
        user.oidc_sub = body.externalId

    await db.commit()
    await db.refresh(user)
    return _user_to_scim(user)


@router.patch("/scim/v2/Users/{user_id}")
async def patch_user(
    user_id: uuid.UUID,
    request: Request,
    db: DbSession,
) -> dict[str, Any]:
    _verify_scim_token(request)

    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    body = await request.json()
    operations = body.get("Operations", [])
    if not isinstance(operations, list):
        raise HTTPException(status_code=400, detail="Operations must be a list")

    for op in operations:
        op_type = op.get("op", "").lower()
        path = op.get("path", "")
        value = op.get("value")

        if path == "active" or (not path and isinstance(value, dict) and "active" in value):
            if isinstance(value, bool):
                active_val = value
            elif isinstance(value, dict):
                active_val = value.get("active", True)
            else:
                raise HTTPException(
                    status_code=400, detail="active must be a boolean"
                )
            user.is_active = bool(active_val)
        elif path == "name.givenName" and value:
            user.first_name = str(value)
        elif path == "name.familyName" and value:
            user.last_name = str(value)

    await db.commit()
    await db.refresh(user)
    return _user_to_scim(user)


@router.delete("/scim/v2/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    db: DbSession,
) -> None:
    _verify_scim_token(request)

    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    await db.commit()
    logger.info("SCIM deprovisioned user %s (soft delete)", user.email)
