"""SSO / OIDC authentication provider.

Implements OpenID Connect Authorization Code flow using authlib.
Discovers issuer metadata from the well-known endpoint, handles
authorization URL generation and token exchange, and provisions
local UserProfile + UserSession on successful callback.
"""

import logging
import uuid
from typing import Any, Optional

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from authlib.jose import jwt

from nexus.config import settings

logger = logging.getLogger(__name__)

_oidc_metadata: Optional[dict[str, Any]] = None


async def _discover_metadata() -> dict[str, Any]:
    """Fetch and cache OIDC provider metadata from .well-known endpoint."""
    global _oidc_metadata
    if _oidc_metadata is not None:
        return _oidc_metadata

    url = settings.oidc_issuer_url.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _oidc_metadata = resp.json()
    return _oidc_metadata


def _build_client() -> AsyncOAuth2Client:
    """Build an authlib OAuth2 client configured for OIDC."""
    return AsyncOAuth2Client(
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        redirect_uri=settings.oidc_redirect_uri,
        scope=settings.oidc_scopes,
    )


async def get_authorization_url(state: str) -> str:
    """Generate the IdP authorization URL for the user to visit.

    Args:
        state: CSRF state parameter to verify on callback.

    Returns:
        Full authorization URL to redirect the user to.
    """
    metadata = await _discover_metadata()
    client = _build_client()
    url, _ = client.create_authorization_url(
        metadata["authorization_endpoint"],
        state=state,
    )
    return url


async def exchange_code(code: str) -> dict[str, Any]:
    """Exchange authorization code for tokens and extract user claims.

    Args:
        code: The authorization code returned by the IdP.

    Returns:
        Dict with keys: sub, email, name (from ID token claims).

    Raises:
        ValueError: If token exchange or ID token validation fails.
    """
    metadata = await _discover_metadata()
    client = _build_client()

    token = await client.fetch_token(
        metadata["token_endpoint"],
        code=code,
        grant_type="authorization_code",
    )

    id_token = token.get("id_token")
    if not id_token:
        raise ValueError("No id_token in token response")

    jwks_uri = metadata.get("jwks_uri", "")
    async with httpx.AsyncClient(timeout=10.0) as http:
        jwks_resp = await http.get(jwks_uri)
        jwks_resp.raise_for_status()
        jwks = jwks_resp.json()

    claims = jwt.decode(id_token, jwks)
    claims.validate()

    return {
        "sub": claims.get("sub", ""),
        "email": claims.get("email", ""),
        "name": claims.get("name", claims.get("preferred_username", "")),
    }


async def provision_or_get_user(
    db: Any,
    claims: dict[str, Any],
    company_id: uuid.UUID,
) -> Any:
    """Find existing user by email or create a new one from OIDC claims.

    Args:
        db: AsyncSession instance.
        claims: Decoded ID token claims (sub, email, name).
        company_id: Company to associate the user with.

    Returns:
        UserProfile instance (existing or newly created).
    """
    from sqlmodel import select
    from nexus.models.user_profile import UserProfile

    email = claims["email"]
    result = await db.execute(
        select(UserProfile).where(UserProfile.email == email)
    )
    user = result.scalar_one_or_none()

    if user is not None:
        return user

    user = UserProfile(
        email=email,
        hashed_password="",
        company_id=company_id,
        display_name=claims.get("name", ""),
        is_active=True,
        is_verified=True,
        is_superuser=False,
        oidc_sub=claims.get("sub", ""),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("Provisioned OIDC user %s for company %s", email, company_id)
    return user
