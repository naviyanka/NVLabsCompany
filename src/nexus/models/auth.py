"""Authorization models: invitations, and the role vocabulary.

A user's access to a company is expressed by a
:class:`nexus.models.company.CompanyMembership` row, not by a header and not by
:attr:`nexus.models.user_profile.UserProfile.company_id`. That table already
existed and is reused here rather than duplicated. Every request resolves to
exactly one membership, and that membership's role decides what the request may
do. Legacy rows carrying a role outside :data:`VALID_ROLES` (the table's own
default was ``"member"``) are treated as ``"viewer"`` when resolved.

Onboarding is invite-only: there is no self-service registration endpoint. The
first administrator is created out of band by ``python -m nexus.auth.bootstrap``
or by the one-shot first-run setup endpoint; everyone else arrives through an
:class:`Invite`.
"""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from nexus.models._time import utcnow

# Role names recognised across memberships, invites and API keys. These mirror
# the keys of nexus.governance.rbac.STANDARD_ROLES.
VALID_ROLES = ("admin", "manager", "agent", "viewer")

# Role assumed for a membership row whose role is not in VALID_ROLES.
FALLBACK_ROLE = "viewer"


def normalize_role(role: str | None) -> str:
    """Coerce a stored role string to a role the RBAC layer understands."""
    if role and role.lower() in VALID_ROLES:
        return role.lower()
    return FALLBACK_ROLE


class Invite(SQLModel, table=True):
    """A single-use invitation to join a company at a given role.

    Only the SHA-256 hash of the invite token is stored. The plaintext token is
    returned once, to the admin who created the invite, and is never
    recoverable afterwards.
    """

    __tablename__ = "auth_invites"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    email: str = Field(max_length=255, index=True)
    role: str = Field(default="viewer", max_length=20)
    token_hash: str = Field(max_length=64, index=True, unique=True)
    # Timestamps are naive UTC because the underlying columns are declared
    # without a timezone; see nexus.models._time for why.
    expires_at: datetime
    accepted_at: datetime | None = Field(default=None)
    created_by: uuid.UUID | None = Field(default=None, foreign_key="user_profiles.id")
    created_at: datetime = Field(default_factory=utcnow)
