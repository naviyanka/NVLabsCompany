"""SSO/OIDC authentication routes.

Provides /auth/sso/login and /auth/sso/callback endpoints that implement
the OIDC Authorization Code flow. On successful callback, a standard
UserSession is created (same as password login) and cookies are set.
"""

import secrets
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import DbSession
from nexus.auth.sessions import create_session, generate_token
from nexus.config import settings

router = APIRouter(tags=["auth"])

_SSO_STATES: dict[str, dict[str, Any]] = {}


@router.get("/auth/sso/login")
async def sso_login(request: Request) -> dict[str, str]:
    """Initiate OIDC login flow. Returns authorization URL for redirect."""
    if not settings.oidc_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO is not enabled",
        )

    from nexus.auth.oidc import get_authorization_url

    state = secrets.token_urlsafe(32)
    _SSO_STATES[state] = {"used": False}

    url = await get_authorization_url(state=state)
    return {"authorization_url": url, "state": state}


@router.get("/auth/sso/callback")
async def sso_callback(
    code: str,
    state: str,
    response: Response,
    db: DbSession,
) -> dict[str, Any]:
    """Handle OIDC callback after IdP authorization.

    Exchanges code for tokens, provisions/finds user, creates session.
    """
    if not settings.oidc_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO is not enabled",
        )

    stored = _SSO_STATES.pop(state, None)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )

    from nexus.auth.oidc import exchange_code, provision_or_get_user

    try:
        claims = await exchange_code(code)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token exchange failed: {exc}",
        )

    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID token missing email claim",
        )

    company_id = uuid.UUID("00000000-0000-4000-8000-000000000001")

    user = await provision_or_get_user(db, claims, company_id)

    token = generate_token()
    session_row = await create_session(
        db,
        user_id=user.id,
        company_id=user.company_id,
        browser="sso",
        ip_address="",
    )

    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_lifetime_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )

    return {
        "status": "authenticated",
        "user_id": str(user.id),
        "email": user.email,
        "company_id": str(user.company_id),
    }
