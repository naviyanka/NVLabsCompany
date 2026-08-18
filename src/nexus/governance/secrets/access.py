"""Secret Access Control - permission management for secret access.

Provides fine-grained access control including time-limited grants,
one-time-use secrets, and emergency revocation capabilities.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AccessGrant:
    """A grant of access to a secret for an agent.

    Attributes:
        id: Unique grant identifier.
        secret_id: The secret being granted access to.
        agent_id: The agent receiving access.
        granted_at: When access was granted.
        expires_at: Optional expiration for time-limited access.
        is_one_time: If True, access is consumed after first use.
        is_used: Whether a one-time grant has been consumed.
        is_revoked: Whether this grant has been revoked.
        granted_by: Who granted access.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    secret_id: uuid.UUID = field(default_factory=uuid.uuid4)
    agent_id: str = ""
    granted_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime | None = None
    is_one_time: bool = False
    is_used: bool = False
    is_revoked: bool = False
    granted_by: str = "system"


@dataclass
class AccessAuditEntry:
    """Record of an access control action.

    Attributes:
        id: Unique entry identifier.
        action: The action taken.
        agent_id: The agent involved.
        secret_id: The secret involved.
        timestamp: When the action occurred.
        result: Outcome of the action.
        details: Additional context.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    action: str = ""
    agent_id: str = ""
    secret_id: uuid.UUID = field(default_factory=uuid.uuid4)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    result: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class SecretAccessController:
    """Manages access permissions for secrets.

    Provides binding of secrets to agents/roles, time-limited access,
    one-time-use secrets, and emergency revocation. Every access attempt
    is recorded in an audit trail.
    """

    def __init__(self) -> None:
        """Initialize the access controller."""
        # grant_id -> AccessGrant
        self._grants: dict[uuid.UUID, AccessGrant] = {}
        # agent_id -> list of grant_ids
        self._agent_grants: dict[str, list[uuid.UUID]] = {}
        # secret_id -> list of grant_ids
        self._secret_grants: dict[uuid.UUID, list[uuid.UUID]] = {}
        # Audit trail
        self._audit_trail: list[AccessAuditEntry] = []

    async def bind_secret_to_agent(
        self,
        secret_id: uuid.UUID,
        agent_id: str,
        granted_by: str = "system",
    ) -> AccessGrant:
        """Bind a secret to an agent, granting permanent access.

        Args:
            secret_id: The secret to grant access to.
            agent_id: The agent receiving access.
            granted_by: Who is granting access.

        Returns:
            The created AccessGrant.
        """
        grant = AccessGrant(
            secret_id=secret_id,
            agent_id=agent_id,
            granted_by=granted_by,
        )
        self._store_grant(grant)
        self._log_audit("bind", agent_id, secret_id, "granted")
        return grant

    async def unbind_secret(
        self,
        secret_id: uuid.UUID,
        agent_id: str,
    ) -> bool:
        """Remove an agent's access to a secret.

        Args:
            secret_id: The secret to revoke access from.
            agent_id: The agent losing access.

        Returns:
            True if a grant was revoked, False if no active grant found.
        """
        grant_ids = self._agent_grants.get(agent_id, [])
        revoked = False
        for grant_id in grant_ids:
            grant = self._grants.get(grant_id)
            if grant and grant.secret_id == secret_id and not grant.is_revoked:
                grant.is_revoked = True
                revoked = True
        if revoked:
            self._log_audit("unbind", agent_id, secret_id, "revoked")
        else:
            self._log_audit("unbind", agent_id, secret_id, "no_active_grant")
        return revoked

    async def check_access(
        self,
        secret_id: uuid.UUID,
        agent_id: str,
    ) -> bool:
        """Check if an agent has valid access to a secret.

        Validates that a non-revoked, non-expired grant exists.
        For one-time grants, marks them as used on successful check.

        Args:
            secret_id: The secret to check access for.
            agent_id: The agent requesting access.

        Returns:
            True if access is allowed, False otherwise.
        """
        grant_ids = self._agent_grants.get(agent_id, [])
        now = datetime.now(timezone.utc)

        for grant_id in grant_ids:
            grant = self._grants.get(grant_id)
            if grant is None:
                continue
            if grant.secret_id != secret_id:
                continue
            if grant.is_revoked:
                continue
            # Check expiration
            if grant.expires_at and now > grant.expires_at:
                continue
            # Check one-time use
            if grant.is_one_time and grant.is_used:
                continue

            # Valid grant found
            if grant.is_one_time:
                grant.is_used = True

            self._log_audit("check_access", agent_id, secret_id, "allowed")
            return True

        self._log_audit("check_access", agent_id, secret_id, "denied")
        return False

    async def grant_time_limited_access(
        self,
        secret_id: uuid.UUID,
        agent_id: str,
        expires_at: datetime,
        granted_by: str = "system",
    ) -> AccessGrant:
        """Grant time-limited access to a secret.

        Args:
            secret_id: The secret to grant access to.
            agent_id: The agent receiving access.
            expires_at: When access expires.
            granted_by: Who is granting access.

        Returns:
            The created AccessGrant with expiration.
        """
        grant = AccessGrant(
            secret_id=secret_id,
            agent_id=agent_id,
            expires_at=expires_at,
            granted_by=granted_by,
        )
        self._store_grant(grant)
        self._log_audit(
            "grant_time_limited", agent_id, secret_id, "granted",
            details={"expires_at": expires_at.isoformat()},
        )
        return grant

    async def grant_one_time_access(
        self,
        secret_id: uuid.UUID,
        agent_id: str,
        granted_by: str = "system",
    ) -> AccessGrant:
        """Grant one-time access to a secret.

        The grant is consumed after the first successful access check.

        Args:
            secret_id: The secret to grant access to.
            agent_id: The agent receiving access.
            granted_by: Who is granting access.

        Returns:
            The created one-time AccessGrant.
        """
        grant = AccessGrant(
            secret_id=secret_id,
            agent_id=agent_id,
            is_one_time=True,
            granted_by=granted_by,
        )
        self._store_grant(grant)
        self._log_audit("grant_one_time", agent_id, secret_id, "granted")
        return grant

    async def emergency_revoke_all(
        self,
        agent_id: str,
        revoked_by: str = "system",
    ) -> int:
        """Emergency revocation of all access grants for an agent.

        Args:
            agent_id: The agent whose access should be revoked.
            revoked_by: Who initiated the revocation.

        Returns:
            Number of grants revoked.
        """
        grant_ids = self._agent_grants.get(agent_id, [])
        count = 0
        for grant_id in grant_ids:
            grant = self._grants.get(grant_id)
            if grant and not grant.is_revoked:
                grant.is_revoked = True
                count += 1
        self._log_audit(
            "emergency_revoke_all", agent_id, uuid.UUID(int=0), "revoked",
            details={"grants_revoked": count, "revoked_by": revoked_by},
        )
        return count

    def get_access_audit_trail(
        self,
        agent_id: str | None = None,
        secret_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[AccessAuditEntry]:
        """Retrieve the access control audit trail.

        Args:
            agent_id: Filter by agent.
            secret_id: Filter by secret.
            limit: Maximum entries to return.

        Returns:
            List of AccessAuditEntry objects.
        """
        results: list[AccessAuditEntry] = []
        for entry in reversed(self._audit_trail):
            if agent_id and entry.agent_id != agent_id:
                continue
            if secret_id and entry.secret_id != secret_id:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_active_grants(
        self,
        agent_id: str | None = None,
        secret_id: uuid.UUID | None = None,
    ) -> list[AccessGrant]:
        """Get all active (non-revoked, non-expired) grants.

        Args:
            agent_id: Filter by agent.
            secret_id: Filter by secret.

        Returns:
            List of active AccessGrant objects.
        """
        now = datetime.now(timezone.utc)
        results: list[AccessGrant] = []
        for grant in self._grants.values():
            if grant.is_revoked:
                continue
            if grant.expires_at and now > grant.expires_at:
                continue
            if grant.is_one_time and grant.is_used:
                continue
            if agent_id and grant.agent_id != agent_id:
                continue
            if secret_id and grant.secret_id != secret_id:
                continue
            results.append(grant)
        return results

    def _store_grant(self, grant: AccessGrant) -> None:
        """Store a grant in all indices."""
        self._grants[grant.id] = grant

        if grant.agent_id not in self._agent_grants:
            self._agent_grants[grant.agent_id] = []
        self._agent_grants[grant.agent_id].append(grant.id)

        if grant.secret_id not in self._secret_grants:
            self._secret_grants[grant.secret_id] = []
        self._secret_grants[grant.secret_id].append(grant.id)

    def _log_audit(
        self,
        action: str,
        agent_id: str,
        secret_id: uuid.UUID,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record an access control action in the audit trail."""
        entry = AccessAuditEntry(
            action=action,
            agent_id=agent_id,
            secret_id=secret_id,
            result=result,
            details=details or {},
        )
        self._audit_trail.append(entry)
