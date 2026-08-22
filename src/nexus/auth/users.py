"""User lookup, authentication, and company membership resolution.

:class:`UserManager` is a fastapi-users manager over :class:`UserProfile`, which
is possible without a second user table because SQLModel classes are SQLAlchemy
declarative models. Only the parts of fastapi-users that earn their place are
used: :meth:`BaseUserManager.authenticate` for credential checking (it hashes a
dummy password when no user matches, so a wrong email and a wrong password take
the same time and the login endpoint does not leak which accounts exist), and
the password helper for hashing.

Registration and password-reset flows are deliberately absent. Onboarding is
invite-only, and there is no mailer in this application, so a reset endpoint
could only hand a reset token back to whoever asked for it — an account-takeover
primitive, not a feature.
"""

import uuid

from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.auth.passwords import hash_password
from nexus.config import settings
from nexus.models.auth import normalize_role
from nexus.models.company import Company, CompanyMembership
from nexus.models.user_profile import UserProfile

# The company ``main.lifespan`` seeds for local development. First-run setup
# adopts it when it exists, so the first administrator lands in the same tenant
# as the seeded demo data instead of creating an empty second company.
DEFAULT_COMPANY_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


class UserManager(UUIDIDMixin, BaseUserManager[UserProfile, uuid.UUID]):
    """fastapi-users manager bound to the application's user table.

    The token secrets are required by the base class even though the flows that
    consume them are not mounted; they are wired to the application secret so
    that nothing here silently uses a placeholder.
    """

    reset_password_token_secret = settings.secret_key
    verification_token_secret = settings.secret_key


def get_user_db(db: AsyncSession) -> SQLAlchemyUserDatabase[UserProfile, uuid.UUID]:
    """Build a fastapi-users database adapter over ``user_profiles``."""
    return SQLAlchemyUserDatabase(db, UserProfile)


def get_user_manager(db: AsyncSession) -> UserManager:
    """Build a user manager for one request's session."""
    return UserManager(get_user_db(db))


async def get_user_by_email(db: AsyncSession, email: str) -> UserProfile | None:
    """Find a user by email, case-insensitively."""
    return await get_user_db(db).get_by_email(email)


async def count_users(db: AsyncSession) -> int:
    """Count user rows. Drives the one-shot first-run setup endpoint."""
    result = await db.execute(select(UserProfile.id))
    return len(result.scalars().all())


async def list_memberships(db: AsyncSession, user_id: uuid.UUID) -> list[CompanyMembership]:
    """Every company a user may act in."""
    stmt = select(CompanyMembership).where(CompanyMembership.user_id == user_id)
    return list((await db.execute(stmt)).scalars().all())


async def get_membership(
    db: AsyncSession, user_id: uuid.UUID, company_id: uuid.UUID
) -> CompanyMembership | None:
    """The user's membership in one company, or ``None`` if they have none.

    A missing membership is the only thing that denies cross-tenant access.
    Callers must not fall back to ``UserProfile.company_id``.
    """
    stmt = select(CompanyMembership).where(
        CompanyMembership.user_id == user_id,
        CompanyMembership.company_id == company_id,
    )
    return (await db.execute(stmt)).scalars().first()


async def pick_default_membership(
    db: AsyncSession, user: UserProfile
) -> CompanyMembership | None:
    """Choose the company a fresh login lands in.

    The user's home company wins when they are still a member of it; otherwise
    the earliest membership does, so a user removed from their home company can
    still log in.
    """
    memberships = await list_memberships(db, user.id)
    if not memberships:
        return None

    for membership in memberships:
        if membership.company_id == user.company_id:
            return membership

    return sorted(memberships, key=lambda m: (m.joined_at, str(m.id)))[0]


async def grant_membership(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    role: str,
) -> CompanyMembership:
    """Give a user a role in a company, or update the role if already a member."""
    existing = await get_membership(db, user_id, company_id)
    if existing is not None:
        existing.role = normalize_role(role)
        db.add(existing)
        await db.flush()
        return existing

    membership = CompanyMembership(
        user_id=user_id,
        company_id=company_id,
        role=normalize_role(role),
    )
    db.add(membership)
    await db.flush()
    return membership


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    company_id: uuid.UUID,
    role: str = "viewer",
    first_name: str = "",
    last_name: str = "",
    is_superuser: bool = False,
) -> UserProfile:
    """Create a user with a membership in one company.

    The caller is responsible for validating the password first; this function
    only hashes it. Email is lowercased so the unique index behaves
    case-insensitively in practice.
    """
    user = UserProfile(
        email=email.strip().lower(),
        hashed_password=hash_password(password),
        company_id=company_id,
        first_name=first_name,
        last_name=last_name,
        is_active=True,
        is_verified=True,
        is_superuser=is_superuser,
    )
    db.add(user)
    await db.flush()
    await grant_membership(db, user_id=user.id, company_id=company_id, role=role)
    return user


async def pick_setup_company(
    db: AsyncSession,
    *,
    company_id: uuid.UUID | None = None,
    company_name: str = "NVLabs",
) -> Company:
    """Find or create the company an out-of-band administrator belongs to.

    Shared by first-run setup and the bootstrap command so both land in the same
    tenant. An explicit id must already exist — silently creating a company under
    a caller-supplied id would let a typo split a deployment in two. Otherwise
    the seeded development company wins, then the oldest existing company, and
    only an entirely empty install creates one.
    """
    if company_id is not None:
        company = await db.get(Company, company_id)
        if company is None:
            raise LookupError(f"No company with id {company_id}")
        return company

    company = await db.get(Company, DEFAULT_COMPANY_ID)
    if company is not None:
        return company

    stmt = select(Company).order_by(Company.created_at)  # type: ignore[arg-type]
    company = (await db.execute(stmt)).scalars().first()
    if company is not None:
        return company

    company = Company(
        name=company_name.strip() or "NVLabs",
        description="Created during first-run setup",
        status="active",
    )
    db.add(company)
    await db.flush()
    return company

