"""Short-lived bearer tokens for one agent inside one run (Phase 5.1 / A5).

An agent doing work on behalf of a run needs a credential, and the two we
already had are both wrong for it. An API key is long-lived and company-wide:
minting one per run leaves a key that outlives the run and can read everything
the tenant owns. A session cookie belongs to a human. So a run gets its own
token, signed rather than stored, carrying exactly the three ids that scope the
work — ``(run_id, agent_id, company_id)`` — and expiring on its own without a
revocation sweep.

Signed rather than stored is the point: verification is a local operation, so
the hot path an agent hits on every tool call does not add a database round
trip, and there is no row to clean up when the run ends. The tradeoff is that a
token cannot be revoked before its expiry, which is why the lifetime is minutes
rather than days.

PyJWT, deliberately (5.1.3). ``python-jose`` reaches for the pure-Python
``ecdsa`` package, which carries a known non-constant-time signing weakness
(CVE-2024-23342) its maintainers consider out of scope. PyJWT delegates to
``cryptography`` instead, which we already depend on for secret encryption at
rest. :func:`assert_pyjwt` pins the choice so a future dependency shuffle that
swaps the ``jwt`` import back to python-jose fails a test rather than silently
downgrading the crypto.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import jwt

from nexus.config import settings
from nexus.models._time import utcnow

# HS256 rather than a keypair: the process that mints a run token is the same
# process that verifies it, so there is no third party needing a public key, and
# a shared secret we already have beats introducing key distribution.
ALGORITHM = "HS256"

# Long enough for a run's agent to finish its turn, short enough that a leaked
# token is worth little. Overridable per mint for a long-running run.
DEFAULT_TTL_SECONDS = 900

# Marks our tokens so a token minted for something else cannot be replayed here
# even if it happens to be signed with the same secret.
AUDIENCE = "nexus:run"


class RunTokenError(Exception):
    """A run token was absent, malformed, expired, or not ours."""


def mint_run_token(
    run_id: uuid.UUID,
    agent_id: uuid.UUID,
    company_id: uuid.UUID,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Sign a token scoped to one agent's work inside one run (5.1.1).

    Args:
        run_id: The run the token is valid for.
        agent_id: The agent acting.
        company_id: The tenant both belong to.
        ttl_seconds: Lifetime from now. Keep it to the expected turn length.

    Returns:
        The encoded JWT, to be sent as ``Authorization: Bearer <token>``.
    """
    now = utcnow()
    payload = {
        "sub": str(agent_id),
        "run_id": str(run_id),
        "company_id": str(company_id),
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def verify_run_token(token: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Check a run token's signature and expiry, returning its three ids (5.1.2).

    Args:
        token: The encoded JWT from the ``Authorization`` header.

    Returns:
        ``(run_id, agent_id, company_id)``.

    Raises:
        RunTokenError: Expired, wrong audience, bad signature, or missing a
            claim. All four collapse into one error on purpose — telling a
            caller *why* their token failed tells an attacker which half of a
            forgery attempt was closer.
    """
    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            # A token with no expiry would be a permanent credential; requiring
            # the claim means a minting bug fails closed.
            options={"require": ["exp", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise RunTokenError(str(exc)) from exc

    try:
        return (
            uuid.UUID(claims["run_id"]),
            uuid.UUID(claims["sub"]),
            uuid.UUID(claims["company_id"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise RunTokenError("run token claims are not three UUIDs") from exc


def looks_like_run_token(credential: str) -> bool:
    """Whether a bearer credential is shaped like a JWT rather than an API key.

    Cheap enough to run before attempting verification, which keeps an API key
    from being fed to the JWT decoder and logged as a signature failure. Three
    dot-separated segments is the JWS compact form.
    """
    return credential.count(".") == 2 and " " not in credential


def assert_pyjwt() -> None:
    """Fail loudly if the ``jwt`` name is not PyJWT (5.1.3).

    ``python-jose`` also publishes a ``jwt`` module. If it ever wins the import,
    every call here still appears to work while the signing path quietly moves
    onto the ``ecdsa`` timing weakness PyJWT was chosen to avoid.
    """
    if not hasattr(jwt, "PyJWTError"):
        raise RuntimeError(
            "the 'jwt' module is not PyJWT -- python-jose depends on the "
            "pure-Python 'ecdsa' package (CVE-2024-23342); uninstall it and "
            "keep pyjwt as the only provider of the 'jwt' import"
        )
