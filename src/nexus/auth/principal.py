"""The identity behind a request.

A :class:`Principal` is what the rest of the application asks about instead of
reading a header. It is produced once per request by
:mod:`nexus.auth.middleware` and reaches route handlers through
``nexus.api.deps.CurrentPrincipal``.

Two kinds exist. A ``"user"`` principal comes from a session cookie and carries
the human's identity. A ``"service"`` principal comes from an API key in the
``Authorization`` header and has no user behind it. Both are scoped to exactly
one company, and both carry a role, so authorization does not care which kind it
is looking at.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from nexus.governance.rbac import role_allows

PrincipalKind = Literal["user", "service"]


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated caller, scoped to one company with one role.

    Frozen because a request's identity must not change after the middleware
    has resolved it: a handler that could rewrite ``company_id`` would defeat
    tenant isolation.
    """

    kind: PrincipalKind
    company_id: uuid.UUID
    role: str
    user_id: uuid.UUID | None = None
    email: str = ""
    session_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None

    @property
    def is_service(self) -> bool:
        """True when the caller authenticated with an API key."""
        return self.kind == "service"

    @property
    def display_name(self) -> str:
        """A short label for audit lines."""
        if self.kind == "service":
            return f"service:{self.api_key_id}"
        return self.email or f"user:{self.user_id}"

    def has_permission(self, action: str, resource_type: str, resource_id: str = "*") -> bool:
        """Whether this principal's role permits an action on a resource type."""
        return role_allows(self.role, action, resource_type, resource_id)
