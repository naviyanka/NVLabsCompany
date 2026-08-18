"""Audit Logger - records all significant actions for accountability and compliance."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AuditEntry:
    """A single audit log entry.

    Attributes:
        id: Unique entry identifier.
        actor_type: Type of actor (agent, user, system).
        actor_id: Identifier of the actor.
        action: The action performed.
        resource_type: Type of resource affected.
        resource_id: Identifier of the affected resource.
        details: Additional context about the action.
        company_id: Company scope.
        timestamp: When the action occurred.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    actor_type: str = ""
    actor_id: str = ""
    action: str = ""
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    company_id: uuid.UUID | None = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AuditLogger:
    """Async audit logger for recording all significant system actions.

    Provides methods for logging agent, user, and system actions with
    structured metadata. In production, writes to the AuditLog database
    table. This implementation maintains an in-memory log for testing.
    """

    def __init__(self) -> None:
        """Initialize the audit logger."""
        self._entries: list[AuditEntry] = []

    async def log(
        self,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        company_id: uuid.UUID | None = None,
    ) -> AuditEntry:
        """Log an audit event.

        Args:
            actor_type: Type of actor (agent, user, system).
            actor_id: Identifier of the actor.
            action: Description of the action performed.
            resource_type: Type of resource affected.
            resource_id: Identifier of the affected resource.
            details: Additional context about the action.
            company_id: Company scope.

        Returns:
            The created AuditEntry.
        """
        entry = AuditEntry(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            company_id=company_id,
        )
        self._entries.append(entry)
        return entry

    async def log_agent_action(
        self,
        agent_id: uuid.UUID,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        company_id: uuid.UUID | None = None,
    ) -> AuditEntry:
        """Convenience method for logging agent actions.

        Args:
            agent_id: The agent performing the action.
            action: Description of the action.
            resource_type: Type of resource affected.
            resource_id: Identifier of the affected resource.
            details: Additional context.
            company_id: Company scope.

        Returns:
            The created AuditEntry.
        """
        return await self.log(
            actor_type="agent",
            actor_id=str(agent_id),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            company_id=company_id,
        )

    async def log_user_action(
        self,
        user_id: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        company_id: uuid.UUID | None = None,
    ) -> AuditEntry:
        """Convenience method for logging user actions.

        Args:
            user_id: The user performing the action.
            action: Description of the action.
            resource_type: Type of resource affected.
            resource_id: Identifier of the affected resource.
            details: Additional context.
            company_id: Company scope.

        Returns:
            The created AuditEntry.
        """
        return await self.log(
            actor_type="user",
            actor_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            company_id=company_id,
        )

    async def log_system_action(
        self,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        company_id: uuid.UUID | None = None,
    ) -> AuditEntry:
        """Convenience method for logging system-generated actions.

        Args:
            action: Description of the action.
            resource_type: Type of resource affected.
            resource_id: Identifier of the affected resource.
            details: Additional context.
            company_id: Company scope.

        Returns:
            The created AuditEntry.
        """
        return await self.log(
            actor_type="system",
            actor_id="system",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            company_id=company_id,
        )

    def get_entries(
        self,
        company_id: uuid.UUID | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Retrieve audit log entries with optional filters.

        Args:
            company_id: Filter by company.
            actor_type: Filter by actor type.
            actor_id: Filter by actor ID.
            action: Filter by action.
            limit: Maximum entries to return.

        Returns:
            List of matching AuditEntry objects.
        """
        results: list[AuditEntry] = []
        for entry in reversed(self._entries):
            if company_id and entry.company_id != company_id:
                continue
            if actor_type and entry.actor_type != actor_type:
                continue
            if actor_id and entry.actor_id != actor_id:
                continue
            if action and entry.action != action:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results
