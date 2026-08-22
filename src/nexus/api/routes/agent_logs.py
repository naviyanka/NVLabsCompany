"""Agent execution log endpoints."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select, func

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.trigger import TriggerExecution

router = APIRouter(tags=["agent-logs"])


@router.get("/api/v1/agents/{agent_id}/logs")
async def get_agent_logs(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    level: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Get execution logs for an agent.

    Uses TriggerExecution records as the source of execution history.
    In production, this would query a dedicated log store.
    """
    # Use trigger executions as proxy for agent activity logs
    stmt = (
        select(TriggerExecution)
        .where(TriggerExecution.company_id == company_id)
        .order_by(TriggerExecution.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    executions = result.scalars().all()

    logs = []
    for ex in executions:
        logs.append({
            "id": str(ex.id),
            "trigger_id": str(ex.trigger_id),
            "status": ex.status,
            "result": ex.result,
            "error": ex.error,
            "started_at": ex.started_at.isoformat() if ex.started_at else None,
            "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
        })

    return logs


@router.get("/api/v1/agents/{agent_id}/logs/summary")
async def get_agent_log_summary(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Summary stats for agent execution logs."""
    total = await db.execute(
        select(func.count(TriggerExecution.id)).where(TriggerExecution.company_id == company_id)
    )
    errors = await db.execute(
        select(func.count(TriggerExecution.id)).where(
            TriggerExecution.company_id == company_id,
            TriggerExecution.status == "failed",
        )
    )
    return {
        "total_executions": total.scalar() or 0,
        "failed_executions": errors.scalar() or 0,
        "success_rate": round((1 - (errors.scalar() or 0) / max(total.scalar() or 1, 1)) * 100, 1),
    }
