"""Authentication middleware: turns credentials into a :class:`Principal`.

This runs as ASGI middleware rather than as a route dependency because
:class:`~nexus.api.middleware.GovernanceMiddleware` executes before any
dependency does. The kill switch, policy evaluation and budget pre-check all key
off the caller's company, so if identity were resolved at the dependency layer
those gates would still be deciding based on a client-supplied header — a caller
could pick which company's kill switch and budget they are measured against.
Resolving identity further out fixes all four at once.

Resolving identity is only half the job. The middleware also decides whether the
request may continue at all, against :data:`PUBLIC_PATH_PREFIXES`: an HTTP
request to anything else without a credential is a 401, and a request whose URL
names a company other than the caller's is a 403.

Enforcing that here rather than per route is deliberate. The first cut left it to
``nexus.api.deps.get_principal``, which meant every router had to opt in — and
roughly twenty of them never did, so ``/api/v1/companies/{id}/agents`` answered
anonymous callers and accepted any company id in the path. A route that forgets
to ask about identity is the normal failure, so the default has to be denial.
Routes still declare what they need: ``CurrentPrincipal`` for a caller,
``PathCompanyId`` for the tenant check, ``require_permission`` for a role. Those
now narrow an already-authenticated request instead of being the only thing
standing in front of it.

Two further rejections have no route-level equivalent: a mutating
cookie-authenticated request without a matching CSRF token, and a WebSocket
handshake from an unlisted origin. WebSocket authentication stays at the route,
which can close the socket with a status code a browser will actually surface.

That last one matters more than it looks. The CORS middleware does not police
WebSockets — the browser sends no preflight for them — so without this check any
web page could open an authenticated socket to this API using the visitor's
cookie and read the tenant's event stream.
"""

import logging
import re
import uuid
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from nexus.auth.api_keys import resolve_api_key, touch_api_key
from nexus.auth.csrf import CSRF_HEADER, requires_csrf, tokens_match
from nexus.auth.principal import Principal
from nexus.auth.sessions import resolve_session, touch_session
from nexus.auth.users import get_membership
from nexus.config import settings
from nexus.database import async_session_factory
from nexus.models._time import utcnow
from nexus.models.auth import normalize_role
from nexus.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

# How stale a session's last_active_at may get before it is rewritten. Without a
# threshold every authenticated request would issue an UPDATE.
_TOUCH_INTERVAL_SECONDS = 60

# Paths that answer without a credential. `/api/v1/auth/` is listed whole rather
# than endpoint by endpoint because the endpoints inside it that do need a caller
# (`/me`, `/logout`, `/sessions`, `/invites`) already declare it as a dependency,
# and an allowlist of individual login routes drifts out of date the moment one
# is added.
PUBLIC_PATH_PREFIXES = (
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/",
)

# Exact paths, for the two cases a prefix would over-match.
PUBLIC_PATHS = frozenset({"/api/v1/auth", "/favicon.ico"})

# ``/api/v1/companies/{company_id}/...`` — a large share of the API is shaped
# this way, and the company in the URL has to be the one the caller proved
# membership of.
_COMPANY_PATH_RE = re.compile(r"^/api/v1/companies/([0-9a-fA-F-]{36})(?:/|$)")


def is_public_path(path: str) -> bool:
    """Whether ``path`` is reachable without a credential."""
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PATH_PREFIXES)


def rejection_for(path: str, principal: Principal | None) -> JSONResponse | None:
    """The response an HTTP request gets instead of reaching its route.

    ``None`` means the request continues. Split out as a plain function so the
    policy can be tested without an ASGI round trip.
    """
    if is_public_path(path):
        return None

    if principal is None:
        if not settings.auth_enabled:
            # Legacy mode: no credential and no ``X-Company-Id`` either. Let the
            # route answer as it did before auth existed.
            return None
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required", "code": "UNAUTHENTICATED"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    match = _COMPANY_PATH_RE.match(path)
    if match is None:
        return None

    try:
        requested_company_id = uuid.UUID(match.group(1))
    except ValueError:
        # Not a company id at all; let routing produce its own 404 or 422.
        return None

    if requested_company_id != principal.company_id:
        # 403 rather than 404: the caller is authenticated and the company
        # probably exists, they simply have no standing in it.
        return JSONResponse(
            status_code=403,
            content={
                "detail": "You do not have access to that company",
                "code": "TENANT_MISMATCH",
            },
        )

    return None


def get_principal_from_scope(scope: Scope) -> Principal | None:
    """Read the principal the middleware resolved for this connection."""
    state = scope.get("state") or {}
    principal = state.get("principal")
    return principal if isinstance(principal, Principal) else None


def allowed_origins() -> set[str]:
    """Origins permitted to open a credentialed connection."""
    return {o.strip() for o in settings.cors_origins.split(",") if o.strip()}


class AuthenticationMiddleware:
    """Resolves the caller's identity before governance runs, and enforces it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry point."""
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)

        if scope["type"] == "websocket" and not self._origin_allowed(headers):
            logger.warning(
                "rejected websocket handshake from origin %r", headers.get("origin", "")
            )
            await send({"type": "websocket.close", "code": 1008})
            return

        principal, cookie_authenticated = await self._resolve(headers)

        if principal is None and not settings.auth_enabled:
            principal = self._legacy_header_principal(headers)

        if scope["type"] == "http":
            # CORS sits outside this middleware, so a browser preflight has
            # already been answered and never reaches here.
            rejection = rejection_for(scope.get("path", ""), principal)
            if rejection is not None:
                await rejection(scope, receive, send)
                return

        if scope["type"] == "http" and requires_csrf(
            scope.get("method", "GET"), cookie_authenticated=cookie_authenticated
        ):
            cookies = self._parse_cookies(headers)
            if not tokens_match(
                cookies.get(settings.csrf_cookie_name), headers.get(CSRF_HEADER)
            ):
                response = JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Missing or invalid CSRF token",
                        "code": "CSRF_FAILED",
                    },
                )
                await response(scope, receive, send)
                return

        state = scope.setdefault("state", {})
        state["principal"] = principal

        await self.app(scope, receive, send)

    def _origin_allowed(self, headers: Headers) -> bool:
        """Whether a WebSocket handshake's Origin is one we serve.

        A handshake with no Origin header is allowed: non-browser clients omit
        it, and they are the ones using API keys rather than ambient cookies.
        """
        origin = headers.get("origin")
        if not origin:
            return True
        return origin in allowed_origins()

    def _parse_cookies(self, headers: Headers) -> dict[str, str]:
        """Parse the Cookie header into a mapping."""
        raw = headers.get("cookie")
        if not raw:
            return {}

        cookies: dict[str, str] = {}
        for part in raw.split(";"):
            name, _, value = part.partition("=")
            name = name.strip()
            if name:
                cookies[name] = value.strip()
        return cookies

    def _bearer_credential(self, headers: Headers) -> str:
        """Extract a bearer credential from the Authorization header."""
        authorization = headers.get("authorization", "")
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() != "bearer":
            return ""
        return credential.strip()

    def _legacy_header_principal(self, headers: Headers) -> Principal | None:
        """Build a principal from ``X-Company-Id`` when auth is switched off.

        Only reachable with ``AUTH_ENABLED=false``, which the config validator
        warns about, because it makes every tenant impersonable. It exists so a
        deployment mid-rollout can fall back without a code change.
        """
        raw = headers.get("x-company-id")
        if not raw:
            return None
        try:
            company_id = uuid.UUID(raw)
        except ValueError:
            return None

        return Principal(kind="service", company_id=company_id, role="admin")

    async def _resolve(self, headers: Headers) -> tuple[Principal | None, bool]:
        """Resolve credentials to a principal.

        Returns the principal, if any, and whether it came from a cookie — the
        CSRF check applies only to cookie-authenticated requests.
        """
        credential = self._bearer_credential(headers)
        cookie_token = self._parse_cookies(headers).get(settings.session_cookie_name, "")

        if not credential and not cookie_token:
            return None, False

        async with async_session_factory() as db:
            try:
                if credential:
                    principal = await self._principal_from_api_key(db, credential)
                    if principal is not None:
                        await db.commit()
                        return principal, False

                if cookie_token:
                    principal = await self._principal_from_cookie(db, cookie_token)
                    if principal is not None:
                        await db.commit()
                        return principal, True

                await db.rollback()
            except Exception:
                # A failure to resolve identity must not surface as a 500 on a
                # public route; the request simply continues as anonymous and
                # any protected route will answer 401.
                await db.rollback()
                logger.exception("failed to resolve request principal")

        return None, False

    async def _principal_from_api_key(self, db: Any, credential: str) -> Principal | None:
        """Resolve an API key to a service principal."""
        key = await resolve_api_key(db, credential)
        if key is None:
            return None

        if key.last_used_at is None or (
            (now(timezone.utc) - key.last_used_at).total_seconds() > _TOUCH_INTERVAL_SECONDS
        ):
            await touch_api_key(db, key.id)

        return Principal(
            kind="service",
            company_id=key.company_id,
            role=normalize_role(key.role),
            api_key_id=key.id,
        )

    async def _principal_from_cookie(self, db: Any, token: str) -> Principal | None:
        """Resolve a session cookie to a user principal.

        The session's company is re-checked against the membership table on every
        request, so revoking someone's membership takes effect immediately rather
        than when their cookie happens to expire.
        """
        session = await resolve_session(db, token)
        if session is None:
            return None

        user = await db.get(UserProfile, session.user_id)
        if user is None or not user.is_active:
            return None

        membership = await get_membership(db, user.id, session.company_id)
        if membership is None:
            return None

        if session.last_active_at is None or (
            (now(timezone.utc) - session.last_active_at).total_seconds() > _TOUCH_INTERVAL_SECONDS
        ):
            await touch_session(db, session.id)

        return Principal(
            kind="user",
            company_id=session.company_id,
            role=normalize_role(membership.role),
            user_id=user.id,
            email=user.email,
            session_id=session.id,
        )
