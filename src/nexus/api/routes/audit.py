"""Audit log query endpoints for Settings > Audit Logs tab."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select, func

from nexus.api.deps import DbSession
from nexus.models.governance import AuditLog

router = APIRouter(tags=["audit"])


@router.get("/api/v1/companies/{company_id}/audit-logs")
async def list_audit_logs(
    company_id: uuid.UUID,
    db: DbSession,
    actor_type: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List audit log entries with optional filters."""
    stmt = select(AuditLog).where(AuditLog.company_id == company_id)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": str(log.id),
            "actor_type": log.actor_type,
            "actor_id": str(log.actor_id) if log.actor_id else None,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": str(log.resource_id) if log.resource_id else None,
            "details": log.details,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@router.get("/api/v1/companies/{company_id}/audit-logs/verify")
async def verify_audit_chain(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Verify the audit hash chain's integrity.

    Recomputes each entry's hash over the persisted chain and reports whether
    it is intact. The hash chain is global (one sequence across the whole
    deployment), so this verifies the entire chain, not just this company's
    rows — tampering anywhere invalidates it. `checked` is the number of
    persisted entries the verifier walked.
    """
    from nexus.database import async_session_factory
    from nexus.governance.audit_persistent import PersistentAuditLogger

    logger = PersistentAuditLogger(session_factory=async_session_factory)
    valid = await logger.verify_chain_integrity()
    checked = await logger.total_entries()

    return {
        "valid": bool(valid),
        "checked": int(checked),
        "scope": "global",
    }


@router.get("/api/v1/companies/{company_id}/audit-logs/stats")
async def audit_log_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Audit log statistics (total entries, by action type)."""
    total = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.company_id == company_id)
    )
    by_action = await db.execute(
        select(AuditLog.action, func.count(AuditLog.id))
        .where(AuditLog.company_id == company_id)
        .group_by(AuditLog.action)
    )
    return {
        "total": total.scalar() or 0,
        "by_action": dict(by_action.all()),
    }
