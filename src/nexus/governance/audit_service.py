"""Audit Service — records ALL significant platform events to the AuditLog table.

This service is the single entry point for audit logging. Every subsystem
calls `record_audit()` to write an immutable record. The function is async
and fire-and-forget (errors are swallowed so audit never blocks operations).

Events captured:
- Chat messages sent/received
- Agent status changes (wake, pause, fire, create)
- Task lifecycle (create, assign, status change, complete)
- Pipeline execution (trigger, stage complete, fail)
- Settings changes
- API key operations
- Approval decisions
- Inter-agent communication
- Orchestrator actions (goal decomposition, task routing)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


async def record_audit(
    company_id: uuid.UUID,
    action: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    db: Any | None = None,
) -> None:
    """Write an audit log entry to the database.

    This is fire-and-forget — errors are logged but never raised,
    so audit logging can never block the operation being audited.

    Args:
        company_id: The company/tenant this event belongs to.
        action: What happened (e.g. 'chat.message_sent', 'agent.created').
        actor_type: Who did it — 'user', 'agent', 'system', 'orchestrator'.
        actor_id: Identifier of the actor (user email, agent UUID, etc.).
        resource_type: What was affected — 'agent', 'task', 'pipeline', etc.
        resource_id: The ID of the affected resource.
        details: Additional context as a JSON dict.
        ip_address: Client IP if available.
        db: Optional existing DB session (avoids SQLite locking issues).
    """
    try:
        from nexus.models.governance import AuditLog

        entry = AuditLog(
            id=uuid.uuid4(),
            company_id=company_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        if db is not None:
            # Use the existing session (no locking issue)
            db.add(entry)
            await db.flush()
        else:
            # Create a new session (for background tasks / orchestrator)
            from nexus.database import async_session_factory
            async with async_session_factory() as new_db:
                new_db.add(entry)
                await new_db.commit()

        logger.info("Audit: %s [%s] %s", action, actor_type, resource_type or "")
    except Exception as e:
        logger.warning("Audit log write failed: %s", e)
