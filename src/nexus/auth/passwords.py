"""Password hashing and strength rules.

Hashing is delegated to fastapi-users' :class:`PasswordHelper`, which wraps
pwdlib with Argon2 as the primary scheme and bcrypt kept for verifying older
hashes. ``verify_and_update`` returns a rehashed value when a stored hash used
an outdated scheme, so callers should persist it when it is not ``None``.
"""

from fastapi_users.password import PasswordHelper

from nexus.config import settings

_helper = PasswordHelper()


class WeakPasswordError(ValueError):
    """Raised when a proposed password fails the strength rules."""


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return _helper.hash(password)


def verify_password(password: str, hashed_password: str) -> tuple[bool, str | None]:
    """Check a password against a stored hash.

    Returns whether it matched and, when the stored hash used a superseded
    scheme, a fresh hash the caller should write back.
    """
    return _helper.verify_and_update(password, hashed_password)


def generate_password() -> str:
    """Generate a random password, for seeding an account the user will reset."""
    return _helper.generate()


def validate_password(password: str, email: str = "") -> None:
    """Raise :class:`WeakPasswordError` if a password is unacceptable.

    Deliberately minimal: a length floor and a check that the password is not
    the account's own email address. Long passwords beat complex ones, and
    rules that reject characters shrink the search space rather than growing it.
    """
    if len(password) < settings.password_min_length:
        raise WeakPasswordError(
            f"Password must be at least {settings.password_min_length} characters"
        )
    if email and password.strip().lower() == email.strip().lower():
        raise WeakPasswordError("Password must not be your email address")
