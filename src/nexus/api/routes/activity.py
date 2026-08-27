"""Activity feed endpoints — company-wide and per-agent activity logs."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select, union_all, literal, func

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.governance import AuditLog
from nexus.models.communication import Event

router = APIRouter(tags=["activity"])


@router.get("/api/v1/companies/{company_id}/activity")
async def get_company_activity(
    company_id: uuid.UUID,
    db: DbSession,
    limit: int = 50,
    offset: int = 0,
    completion_reason: str | None = None,
) -> list[dict[str, Any]]:
    """Company-wide activity feed from audit log and events.

    ``completion_reason`` filters to entries whose audited details recorded that
    reason (Phase 1.1) — a ``RunCompletionReason`` value.
    """
    # Query audit log entries
    stmt = select(AuditLog).where(AuditLog.company_id == company_id)
    if completion_reason:
        # JSON path comparison — SQLite json_extract and Postgres ->> both work.
        stmt = stmt.where(
            AuditLog.details["completion_reason"].as_string() == completion_reason
        )
    stmt = (
        stmt.order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()

    activities = []
    for log in logs:
        activities.append({
            "id": str(log.id),
            "type": "audit",
            "actor_type": log.actor_type,
            "actor_id": str(log.actor_id) if log.actor_id else None,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": str(log.resource_id) if log.resource_id else None,
            "details": log.details,
            # Phase 1.1: hoisted out of details so the Activity page can filter on it
            "completion_reason": (log.details or {}).get("completion_reason"),
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    return activities


@router.get("/api/v1/agents/{agent_id}/activity")
async def get_agent_activity(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    limit: int = 30,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Activity feed for a specific agent."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.company_id == company_id, AuditLog.actor_id == agent_id)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": str(log.id),
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": str(log.resource_id) if log.resource_id else None,
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
