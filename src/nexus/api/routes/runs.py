"""Run liveness endpoints — surface heartbeat/watchdog state to the UI.

`HeartbeatRun` rows have no company_id; they are scoped through their owning
agent. This read-only endpoint joins the two so an operator can see which runs
are live, which look stale, and which the watchdog has confirmed dead.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from nexus.api.deps import DbSession, PathCompanyId
from nexus.models.agent import Agent
from nexus.models.heartbeat_run import HeartbeatRun

router = APIRouter(tags=["runs"])

# Silence thresholds mirror the watchdog's suspicion window (seconds).
_SUSPECT_AFTER_SECONDS = 3600  # 1h


@router.get("/api/v1/companies/{company_id}/runs/liveness")
async def list_run_liveness(
    company_id: PathCompanyId,
    db: DbSession,
    include_finished: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """List heartbeat runs for the company's agents with liveness detail.

    By default only unfinished runs are returned (the ones worth watching).
    `stalled` is a derived hint: unfinished, not confirmed dead, and silent for
    longer than the suspicion window.
    """
    stmt = (
        select(HeartbeatRun, Agent.name)
        .join(Agent, Agent.id == HeartbeatRun.agent_id)
        .where(Agent.company_id == company_id)
    )
    if not include_finished:
        stmt = stmt.where(HeartbeatRun.finished_at.is_(None))
    stmt = stmt.order_by(HeartbeatRun.started_at.desc()).limit(limit)

    rows = (await db.execute(stmt)).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    items: list[dict[str, Any]] = []
    for run, agent_name in rows:
        reference = run.last_output_at or run.started_at
        silent_seconds = int((now - reference).total_seconds()) if reference else None
        stalled = (
            run.finished_at is None
            and run.liveness_state != "confirmed_dead"
            and silent_seconds is not None
            and silent_seconds > _SUSPECT_AFTER_SECONDS
        )
        items.append({
            "id": str(run.id),
            "agent_id": str(run.agent_id),
            "agent_name": agent_name,
            "liveness_state": run.liveness_state,
            "invocation_source": run.invocation_source,
            "process_pid": run.process_pid,
            "continuation_attempt": run.continuation_attempt,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "last_output_at": run.last_output_at.isoformat() if run.last_output_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "silent_seconds": silent_seconds,
            "stalled": bool(stalled),
        })

    summary = {
        "total": len(items),
        "healthy": sum(1 for i in items if i["liveness_state"] == "healthy" and not i["stalled"]),
        "stalled": sum(1 for i in items if i["stalled"]),
        "confirmed_dead": sum(1 for i in items if i["liveness_state"] == "confirmed_dead"),
    }
    return {"items": items, "summary": summary}
