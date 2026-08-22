"""CSRF protection for cookie-authenticated requests.

The session cookie is ``SameSite=Lax``, which already blocks cross-site POSTs
from a plain form or link. Lax is not airtight though — top-level GET navigation
still carries the cookie, and browsers vary in their treatment of some
redirects — so mutating requests additionally use the double-submit pattern: a
non-httpOnly ``nv_csrf`` cookie the dashboard reads with JavaScript, echoed back
in an ``X-CSRF-Token`` header. An attacker's page can cause the cookie to be
sent but cannot read it to set the header, because reading it would require the
same-origin access the browser denies them.

Only cookie-authenticated mutating requests are checked. Bearer API keys are
exempt (no browser attaches them ambiently), and safe methods are exempt because
they must not change state in the first place.
"""

import hmac
import secrets

# Methods that may change state, and therefore require a CSRF token.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

CSRF_HEADER = "x-csrf-token"

_TOKEN_BYTES = 32


def generate_csrf_token() -> str:
    """Generate a fresh CSRF token."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def requires_csrf(method: str, *, cookie_authenticated: bool) -> bool:
    """Whether a request must present a matching CSRF token."""
    return cookie_authenticated and method.upper() in MUTATING_METHODS


def tokens_match(cookie_token: str | None, header_token: str | None) -> bool:
    """Compare the cookie and header tokens in constant time.

    An absent or empty value on either side never matches, so a request that
    simply omits the header is rejected rather than treated as a pair of equal
    blanks.
    """
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)
