"""Authentication endpoints: login, logout, identity, invites, first-run setup.

These are the only routes that may be reached without a principal, and each one
is unauthenticated for a specific reason:

- ``/login`` and ``/invites/accept`` are how a caller obtains a credential.
- ``/setup-required`` and ``/setup`` bootstrap the very first administrator, and
  both refuse to do anything once a user row exists.

Everything else here requires a session. fastapi-users' own routers are not
mounted: login has to choose a company membership and open a server-side
session, and there is no mailer, so registration, verification and
password-reset flows have no implementation to expose.

The session cookie is httpOnly, so the dashboard never reads it. Identity is
fetched from ``GET /me`` instead, and CSRF protection uses the separate,
readable ``nv_csrf`` cookie, which the client echoes in ``X-CSRF-Token``.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.api.deps import (
    CurrentPrincipal,
    DbSession,
    OptionalPrincipal,
    RequireAdmin,
    RequireUser,
)
from nexus.auth.csrf import generate_csrf_token
from nexus.auth.passwords import (
    WeakPasswordError,
    hash_password,
    validate_password,
    verify_password,
)
from nexus.auth.principal import Principal
from nexus.auth.sessions import (
    create_session,
    generate_token,
    hash_token,
    revoke_session,
    revoke_user_sessions,
)
from nexus.auth.users import (
    count_users,
    create_user,
    get_membership,
    get_user_by_email,
    get_user_manager,
    grant_membership,
    list_memberships,
    pick_default_membership,
    pick_setup_company,
)
from nexus.config import settings
from nexus.models._time import utcnow
from nexus.models.auth import VALID_ROLES, Invite, normalize_role
from nexus.models.company import Company
from nexus.models.user_profile import UserProfile, UserSession

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# How long an invite is valid for when the caller does not say.
DEFAULT_INVITE_HOURS = 72


# ─── Schemas ────────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserSummary(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    title: str
    avatar_url: str | None
    timezone: str
    status: str
    two_factor_enabled: bool
    is_superuser: bool


class MembershipSummary(BaseModel):
    company_id: uuid.UUID
    company_name: str
    role: str
    is_current: bool


class MeResponse(BaseModel):
    """Who the caller is, and where they may act.

    ``kind`` distinguishes a human session from an API key so the dashboard can
    hide controls a service principal has no use for.
    """

    kind: str
    role: str
    company_id: uuid.UUID
    company_name: str
    display_name: str
    user: UserSummary | None
    memberships: list[MembershipSummary]


class SessionSummary(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    browser: str
    ip_address: str
    location: str | None
    is_current: bool
    last_active_at: datetime
    expires_at: datetime | None
    created_at: datetime


class SwitchCompanyRequest(BaseModel):
    company_id: uuid.UUID


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class InviteCreateRequest(BaseModel):
    email: EmailStr
    role: str = "viewer"
    expires_in_hours: int = Field(default=DEFAULT_INVITE_HOURS, ge=1, le=720)


class InviteSummary(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class InviteCreateResponse(BaseModel):
    """The created invite plus its one-time token.

    Only the token's hash is stored, so this response is the single opportunity
    to copy it. The admin who created the invite delivers it out of band.
    """

    invite: InviteSummary
    token: str


class InviteAcceptRequest(BaseModel):
    token: str
    password: str = ""
    first_name: str = ""
    last_name: str = ""


class InviteAcceptResponse(BaseModel):
    company_id: uuid.UUID
    role: str
    account_created: bool
    message: str


class SetupStatusResponse(BaseModel):
    setup_required: bool


class SetupRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str = ""
    last_name: str = ""
    company_name: str = "NVLabs"


# ─── Cookie helpers ─────────────────────────────────────────────────────────────


def _samesite() -> Literal["lax", "strict", "none"]:
    """The configured SameSite policy, narrowed to what Starlette accepts."""
    value = settings.session_cookie_samesite.strip().lower()
    if value not in ("lax", "strict", "none"):
        value = "lax"
    return cast(Literal["lax", "strict", "none"], value)


def _issue_cookies(response: Response, session_token: str) -> str:
    """Attach a fresh session and CSRF cookie pair, returning the CSRF token.

    The session cookie is httpOnly so that a script injected into the dashboard
    cannot read it. The CSRF cookie deliberately is not: the double-submit check
    works precisely because the client can read that value and put it in a
    header, which a cross-site request cannot do.
    """
    csrf_token = generate_csrf_token()
    common: dict[str, Any] = {
        "max_age": settings.session_lifetime_seconds,
        "secure": settings.session_cookie_secure,
        "samesite": _samesite(),
        "path": "/",
    }
    response.set_cookie(settings.session_cookie_name, session_token, httponly=True, **common)
    response.set_cookie(settings.csrf_cookie_name, csrf_token, httponly=False, **common)
    return csrf_token


def _clear_cookies(response: Response) -> None:
    """Remove both auth cookies.

    The attributes must match the ones used to set them or the browser keeps the
    original cookie alongside the deletion.
    """
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(
            name,
            path="/",
            secure=settings.session_cookie_secure,
            samesite=_samesite(),
        )


def _client_ip(request: Request) -> str:
    """Best-effort client address for the session record.

    ``X-Forwarded-For`` is trusted only for display; nothing is authorised by
    it. The left-most entry is the original client when a proxy appends.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


# ─── Identity ───────────────────────────────────────────────────────────────────


async def _company_name(db: AsyncSession, company_id: uuid.UUID) -> str:
    company = await db.get(Company, company_id)
    return company.name if company else ""


async def _build_me(db: AsyncSession, principal: Principal) -> MeResponse:
    """Assemble the identity payload the dashboard renders its header from."""
    user_summary: UserSummary | None = None
    memberships: list[MembershipSummary] = []

    if principal.user_id is not None:
        user = await db.get(UserProfile, principal.user_id)
        if user is not None:
            user_summary = UserSummary(
                id=user.id,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                title=user.title,
                avatar_url=user.avatar_url,
                timezone=user.timezone,
                status=user.status,
                two_factor_enabled=user.two_factor_enabled,
                is_superuser=user.is_superuser,
            )

        for membership in await list_memberships(db, principal.user_id):
            memberships.append(
                MembershipSummary(
                    company_id=membership.company_id,
                    company_name=await _company_name(db, membership.company_id),
                    role=normalize_role(membership.role),
                    is_current=membership.company_id == principal.company_id,
                )
            )

    return MeResponse(
        kind=principal.kind,
        role=principal.role,
        company_id=principal.company_id,
        company_name=await _company_name(db, principal.company_id),
        display_name=principal.display_name,
        user=user_summary,
        memberships=memberships,
    )


@router.get("/me", response_model=MeResponse)
async def read_me(db: DbSession, principal: CurrentPrincipal) -> Any:
    """Return the authenticated caller's identity and company memberships."""
    return await _build_me(db, principal)


@router.get("/csrf")
async def issue_csrf(response: Response, principal: CurrentPrincipal) -> dict[str, str]:
    """Re-issue the CSRF cookie for a caller whose session cookie survived it.

    Session and CSRF cookies share a lifetime, but the CSRF cookie is readable
    and therefore clearable by the page. This restores it without forcing a new
    login.
    """
    csrf_token = generate_csrf_token()
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=settings.session_lifetime_seconds,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite=_samesite(),
        path="/",
    )
    return {"csrf_token": csrf_token}


# ─── Login and logout ───────────────────────────────────────────────────────────


@router.post("/login", response_model=MeResponse)
async def login(body: LoginRequest, request: Request, response: Response, db: DbSession) -> Any:
    """Exchange an email and password for a session cookie.

    Every failure answers with the same message. Distinguishing "no such user"
    from "wrong password" would turn this endpoint into an account enumerator,
    and ``UserManager.authenticate`` already hashes a throwaway password when no
    user matches so the two paths take comparable time.
    """
    manager = get_user_manager(db)
    credentials = OAuth2PasswordRequestForm(username=body.email, password=body.password)
    user = await manager.authenticate(credentials)

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    membership = await pick_default_membership(db, user)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not a member of any company",
        )

    token, _session = await create_session(
        db,
        user_id=user.id,
        company_id=membership.company_id,
        browser=request.headers.get("user-agent", ""),
        ip_address=_client_ip(request),
    )
    user.last_login_at = utcnow()
    db.add(user)
    await db.flush()

    _issue_cookies(response, token)

    principal = Principal(
        kind="user",
        company_id=membership.company_id,
        role=normalize_role(membership.role),
        user_id=user.id,
        email=user.email,
    )
    return await _build_me(db, principal)


@router.post("/logout")
async def logout(
    response: Response, db: DbSession, principal: OptionalPrincipal
) -> dict[str, bool]:
    """Revoke the current session and clear its cookies.

    Anonymous callers get the same success answer: the point of the request is
    to end up logged out, and there is nothing to protect by reporting that the
    session was already gone.
    """
    if principal is not None and principal.session_id is not None:
        await revoke_session(db, principal.session_id)
    _clear_cookies(response)
    return {"success": True}


# ─── Sessions ───────────────────────────────────────────────────────────────────


@router.get("/sessions", response_model=list[SessionSummary])
async def list_own_sessions(db: DbSession, principal: RequireUser) -> Any:
    """List the caller's own live sessions, newest activity first."""
    stmt = (
        select(UserSession)
        .where(
            UserSession.user_id == principal.user_id,
            UserSession.revoked_at.is_(None),  # type: ignore[union-attr]
        )
        .order_by(UserSession.last_active_at.desc())  # type: ignore[attr-defined]
    )
    sessions = list((await db.execute(stmt)).scalars().all())
    return [
        SessionSummary(
            id=s.id,
            company_id=s.company_id,
            browser=s.browser,
            ip_address=s.ip_address,
            location=s.location,
            is_current=s.id == principal.session_id,
            last_active_at=s.last_active_at,
            expires_at=s.expires_at,
            created_at=s.created_at,
        )
        for s in sessions
    ]


@router.delete("/sessions/{session_id}")
async def revoke_own_session(
    session_id: uuid.UUID, db: DbSession, principal: RequireUser
) -> dict[str, bool]:
    """Revoke one of the caller's sessions.

    The ownership check is what stops this from being a way to log anyone out:
    a session belonging to another user reads as absent.
    """
    session = await db.get(UserSession, session_id)
    if session is None or session.user_id != principal.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    revoked = await revoke_session(db, session_id)
    return {"revoked": revoked}


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(db: DbSession, principal: RequireUser) -> dict[str, int]:
    """Sign the caller out everywhere except the device making the request."""
    count = await revoke_user_sessions(
        db, principal.user_id, keep_session_id=principal.session_id
    )
    return {"revoked_count": count}


# ─── Companies ──────────────────────────────────────────────────────────────────


@router.get("/companies", response_model=list[MembershipSummary])
async def list_own_companies(db: DbSession, principal: RequireUser) -> Any:
    """List the companies the caller may act in."""
    me = await _build_me(db, principal)
    return me.memberships


@router.post("/switch-company", response_model=MeResponse)
async def switch_company(
    body: SwitchCompanyRequest,
    request: Request,
    response: Response,
    db: DbSession,
    principal: RequireUser,
) -> Any:
    """Move the caller's session to another company they belong to.

    A session is bound to one company, so switching means opening a new session
    and revoking the old one rather than mutating a row — a token that was valid
    for the previous company must not keep working.
    """
    membership = await get_membership(db, principal.user_id, body.company_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of that company",
        )

    if principal.session_id is not None:
        await revoke_session(db, principal.session_id)

    token, _session = await create_session(
        db,
        user_id=principal.user_id,
        company_id=body.company_id,
        browser=request.headers.get("user-agent", ""),
        ip_address=_client_ip(request),
    )
    _issue_cookies(response, token)

    switched = Principal(
        kind="user",
        company_id=body.company_id,
        role=normalize_role(membership.role),
        user_id=principal.user_id,
        email=principal.email,
    )
    return await _build_me(db, switched)


# ─── Password ───────────────────────────────────────────────────────────────────


@router.post("/change-password")
async def change_password(
    body: PasswordChangeRequest, db: DbSession, principal: RequireUser
) -> dict[str, Any]:
    """Change the caller's password and invalidate their other sessions.

    Revoking the rest is the point of requiring the current password: whoever
    changes it should be able to push out a session opened by someone who knew
    the old one.
    """
    user = await db.get(UserProfile, principal.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    verified, _ = verify_password(body.current_password, user.hashed_password)
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    try:
        validate_password(body.new_password, user.email)
    except WeakPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    user.hashed_password = hash_password(body.new_password)
    user.updated_at = utcnow()
    db.add(user)
    await db.flush()

    revoked = await revoke_user_sessions(
        db, principal.user_id, keep_session_id=principal.session_id
    )
    return {"success": True, "other_sessions_revoked": revoked}


# ─── Invites ────────────────────────────────────────────────────────────────────


@router.get("/invites", response_model=list[InviteSummary])
async def list_invites(db: DbSession, principal: RequireAdmin) -> Any:
    """List invites for the administrator's company, newest first."""
    stmt = (
        select(Invite)
        .where(Invite.company_id == principal.company_id)
        .order_by(Invite.created_at.desc())  # type: ignore[attr-defined]
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("/invites", response_model=InviteCreateResponse, status_code=201)
async def create_invite(
    body: InviteCreateRequest, db: DbSession, principal: RequireAdmin
) -> Any:
    """Invite someone to the administrator's company at a given role.

    The invite is scoped to the creator's company; an admin cannot invite into a
    tenant they are not administering, because the company is taken from their
    principal rather than the request body.
    """
    role = body.role.strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role must be one of: {', '.join(VALID_ROLES)}",
        )

    email = body.email.strip().lower()
    existing_user = await get_user_by_email(db, email)
    if existing_user is not None:
        existing_membership = await get_membership(db, existing_user.id, principal.company_id)
        if existing_membership is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That user is already a member of this company",
            )

    token = generate_token()
    invite = Invite(
        company_id=principal.company_id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(hours=body.expires_in_hours),
        created_by=principal.user_id,
    )
    db.add(invite)
    await db.flush()

    return InviteCreateResponse(
        invite=InviteSummary.model_validate(invite, from_attributes=True),
        token=token,
    )


@router.delete("/invites/{invite_id}")
async def revoke_invite(
    invite_id: uuid.UUID, db: DbSession, principal: RequireAdmin
) -> dict[str, bool]:
    """Delete an unaccepted invite belonging to the administrator's company."""
    invite = await db.get(Invite, invite_id)
    if invite is None or invite.company_id != principal.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    await db.delete(invite)
    return {"revoked": True}


@router.post("/invites/accept", response_model=InviteAcceptResponse)
async def accept_invite(body: InviteAcceptRequest, db: DbSession) -> Any:
    """Redeem an invite token.

    Unauthenticated by necessity — the recipient has no account yet. Two cases:
    a new email creates an account, and an email that already has one is simply
    granted membership, in which case the existing password keeps working and
    any password supplied here is ignored rather than silently overwriting it.
    An invalid, expired or already-used token gives one indistinguishable error.
    """
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invite is invalid, expired, or already used",
    )

    if not body.token:
        raise invalid

    stmt = select(Invite).where(Invite.token_hash == hash_token(body.token))
    invite = (await db.execute(stmt)).scalars().first()
    if invite is None or invite.accepted_at is not None or invite.expires_at <= utcnow():
        raise invalid

    role = normalize_role(invite.role)
    user = await get_user_by_email(db, invite.email)
    created = False

    if user is None:
        try:
            validate_password(body.password, invite.email)
        except WeakPasswordError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        user = await create_user(
            db,
            email=invite.email,
            password=body.password,
            company_id=invite.company_id,
            role=role,
            first_name=body.first_name,
            last_name=body.last_name,
        )
        created = True
    else:
        await grant_membership(
            db, user_id=user.id, company_id=invite.company_id, role=role
        )

    invite.accepted_at = utcnow()
    db.add(invite)
    await db.flush()

    return InviteAcceptResponse(
        company_id=invite.company_id,
        role=role,
        account_created=created,
        message=(
            "Account created. You can now sign in."
            if created
            else "Company access granted. Sign in with your existing password."
        ),
    )


# ─── First-run setup ────────────────────────────────────────────────────────────


@router.get("/setup-required", response_model=SetupStatusResponse)
async def setup_required(db: DbSession) -> Any:
    """Whether the deployment still has no users.

    The dashboard calls this before showing the login form so a fresh install
    sends the operator to setup instead of a form nobody can pass. It leaks only
    whether the instance has been claimed, which is the same thing the setup
    endpoint's own refusal would reveal.
    """
    return SetupStatusResponse(setup_required=await count_users(db) == 0)


@router.post("/setup", response_model=MeResponse, status_code=201)
async def run_setup(
    body: SetupRequest, request: Request, response: Response, db: DbSession
) -> Any:
    """Create the first administrator and log them in.

    Open exactly once. The guard is that ``user_profiles`` is empty, so the
    window closes the moment this succeeds; the unique index on email closes the
    narrow race between two simultaneous callers. There is no way to reopen it
    from the API — later administrators arrive through invites, and a
    forgotten-password lockout is recovered with
    ``python -m nexus.auth.bootstrap``.
    """
    if await count_users(db) != 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has already been completed",
        )

    try:
        validate_password(body.password, body.email)
    except WeakPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    company = await pick_setup_company(db, company_name=body.company_name)

    user = await create_user(
        db,
        email=body.email,
        password=body.password,
        company_id=company.id,
        role="admin",
        first_name=body.first_name,
        last_name=body.last_name,
        is_superuser=True,
    )
    user.last_login_at = utcnow()
    db.add(user)

    token, _session = await create_session(
        db,
        user_id=user.id,
        company_id=company.id,
        browser=request.headers.get("user-agent", ""),
        ip_address=_client_ip(request),
    )
    await db.flush()
    _issue_cookies(response, token)

    principal = Principal(
        kind="user",
        company_id=company.id,
        role="admin",
        user_id=user.id,
        email=user.email,
    )
    return await _build_me(db, principal)
