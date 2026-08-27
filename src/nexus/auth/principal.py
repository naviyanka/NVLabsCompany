"""The identity behind a request.

A :class:`Principal` is what the rest of the application asks about instead of
reading a header. It is produced once per request by
:mod:`nexus.auth.middleware` and reaches route handlers through
``nexus.api.deps.CurrentPrincipal``.

Three kinds exist. A ``"user"`` principal comes from a session cookie and
carries the human's identity. A ``"service"`` principal comes from an API key in
the ``Authorization`` header and has no user behind it. A ``"run"`` principal
comes from a short-lived run JWT (:mod:`nexus.auth.run_tokens`) and names the
agent acting inside one run. All three are scoped to exactly one company, and
all three carry a role, so authorization does not care which kind it is looking
at.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from nexus.governance.rbac import role_allows

PrincipalKind = Literal["user", "service", "run"]


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
    # Set only on a ``"run"`` principal: which run the token was minted for and
    # which agent it names. A handler can refuse work aimed at a different run
    # without re-parsing the token.
    run_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None

    @property
    def is_service(self) -> bool:
        """True when the caller authenticated with an API key."""
        return self.kind == "service"

    @property
    def display_name(self) -> str:
        """A short label for audit lines."""
        if self.kind == "service":
            return f"service:{self.api_key_id}"
        if self.kind == "run":
            return f"run:{self.run_id}:agent:{self.agent_id}"
        return self.email or f"user:{self.user_id}"

    def has_permission(self, action: str, resource_type: str, resource_id: str = "*") -> bool:
        """Whether this principal's role permits an action on a resource type."""
        return role_allows(self.role, action, resource_type, resource_id)
