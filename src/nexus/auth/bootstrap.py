"""Create or repair the first administrator from the command line.

``POST /api/v1/auth/setup`` covers the normal first run, but it answers only
while the user table is empty. This command is the way back in afterwards: it
can reset a forgotten password, re-enable a deactivated account, or promote an
existing user to administrator, none of which the HTTP API offers to an
anonymous caller by design.

Run it from the project root::

    python -m nexus.auth.bootstrap --email you@example.com --password '...'
    python -m nexus.auth.bootstrap --email you@example.com --prompt

It is idempotent. Running it twice with the same arguments leaves one account
in the state those arguments describe.
"""

import argparse
import asyncio
import getpass
import sys
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.auth.passwords import WeakPasswordError, hash_password, validate_password
from nexus.auth.users import (
    create_user,
    get_user_by_email,
    grant_membership,
    pick_setup_company,
)
from nexus.database import async_session_factory
from nexus.models.auth import VALID_ROLES, normalize_role


async def ensure_admin(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    company_id: uuid.UUID | None = None,
    company_name: str = "NVLabs",
    role: str = "admin",
) -> tuple[str, uuid.UUID, uuid.UUID]:
    """Create the account, or bring an existing one back to a usable state.

    Returns ``(action, user_id, company_id)`` where ``action`` is ``"created"``
    or ``"updated"``, so the caller can report what actually happened rather
    than assuming.

    An existing account is reset rather than rejected: the password is replaced,
    ``is_active`` is restored, and the membership role is raised to ``role``.
    That is the whole point of the command — a locked-out administrator has no
    other route in.
    """
    validate_password(password, email)
    company = await pick_setup_company(db, company_id=company_id, company_name=company_name)
    role = normalize_role(role)

    user = await get_user_by_email(db, email)
    if user is None:
        user = await create_user(
            db,
            email=email,
            password=password,
            company_id=company.id,
            role=role,
            is_superuser=role == "admin",
        )
        return "created", user.id, company.id

    user.hashed_password = hash_password(password)
    user.is_active = True
    user.is_verified = True
    if role == "admin":
        user.is_superuser = True
    db.add(user)
    await db.flush()
    await grant_membership(db, user_id=user.id, company_id=company.id, role=role)
    return "updated", user.id, company.id


def _read_password(args: argparse.Namespace) -> str:
    """Take the password from ``--password``, or ask for it twice."""
    if args.password:
        return args.password
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    return first


def build_parser() -> argparse.ArgumentParser:
    """Command line interface for the bootstrap command."""
    parser = argparse.ArgumentParser(
        prog="python -m nexus.auth.bootstrap",
        description="Create or repair an administrator account.",
    )
    parser.add_argument("--email", required=True, help="Administrator email address")
    parser.add_argument(
        "--password",
        default="",
        help="Password. Omit to be prompted, which keeps it out of shell history.",
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Always prompt for the password, ignoring --password.",
    )
    parser.add_argument(
        "--company-id",
        default="",
        help="Existing company UUID to attach the account to. Must already exist.",
    )
    parser.add_argument(
        "--company-name",
        default="NVLabs",
        help="Name used only if no company exists yet (default: NVLabs).",
    )
    parser.add_argument(
        "--role",
        default="admin",
        choices=sorted(VALID_ROLES),
        help="Role granted in the company (default: admin).",
    )
    return parser


async def _main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.prompt:
        args.password = ""

    try:
        password = _read_password(args)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2

    company_id: uuid.UUID | None = None
    if args.company_id:
        try:
            company_id = uuid.UUID(args.company_id)
        except ValueError:
            print(f"Not a valid UUID: {args.company_id}", file=sys.stderr)
            return 2

    async with async_session_factory() as session:
        try:
            action, user_id, resolved_company = await ensure_admin(
                session,
                email=args.email,
                password=password,
                company_id=company_id,
                company_name=args.company_name,
                role=args.role,
            )
        except WeakPasswordError as exc:
            print(f"Password rejected: {exc}", file=sys.stderr)
            return 1
        except LookupError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        await session.commit()

    print(f"{action} {args.email} (user {user_id}) as {args.role} in company {resolved_company}")
    return 0


def main() -> None:
    """Console entry point."""
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
