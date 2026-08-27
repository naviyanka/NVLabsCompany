"""Activity feed endpoints — company-wide and per-agent activity logs."""

import asyncio
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.governance import AuditLog

router = APIRouter(tags=["activity"])


def _audit_to_pulse(log: AuditLog) -> dict[str, Any]:
    """Shape an audit row into the PulseEvent the dashboard ticker expects."""
    details = log.details or {}
    return {
        "id": str(log.id),
        "type": log.action.split(".")[0] if log.action else "event",
        "event": log.action,
        "description": details.get("summary") or log.action,
        "actor": log.actor_id and str(log.actor_id) or log.actor_type,
        "target_type": log.resource_type,
        "target_id": str(log.resource_id) if log.resource_id else None,
        "timestamp": log.created_at.isoformat() if log.created_at else None,
    }


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


@router.get("/api/v1/companies/{company_id}/pulse")
async def get_company_pulse(
    company_id: uuid.UUID,
    db: DbSession,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Recent telemetry events for the Pulse ticker (most recent first).

    This seeds the dashboard's Pulse line; the SSE stream below then pushes
    live updates on top of it.
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.company_id == company_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [_audit_to_pulse(log) for log in result.scalars().all()]


@router.get("/api/v1/companies/{company_id}/activity/stream")
async def stream_company_activity(company_id: uuid.UUID, request: Request) -> StreamingResponse:
    """Server-Sent Events stream of live company activity for the Pulse ticker.

    The company is taken from the path, not a header or session, because a
    browser ``EventSource`` cannot send custom auth headers — this keeps the
    ticker working in both authenticated and header-tenant (dev) modes. It
    subscribes to the realtime event bus and forwards this tenant's events,
    with a periodic keepalive so proxies do not drop an idle connection.
    """
    from nexus.realtime.event_bus import RealtimeEventBus
    from nexus.realtime.events import RealtimeEvent

    bus = RealtimeEventBus()

    async def generator() -> AsyncGenerator[str, None]:
        import json

        queue: asyncio.Queue[RealtimeEvent | None] = asyncio.Queue(maxsize=256)
        bus.subscribe("__all__", queue)
        try:
            # Open the stream immediately so EventSource.onopen fires and the UI
            # leaves its "Reconnecting…" state even before the first event.
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    break
                ev_company = getattr(event, "company_id", None)
                if ev_company and str(ev_company) != str(company_id):
                    continue
                data = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
                payload = {
                    "id": str(getattr(event, "id", "")),
                    "type": (event.event_type.split("_")[0] if event.event_type else "event"),
                    "event": event.event_type,
                    "description": data.get("summary") or data.get("message") or event.event_type,
                    "target_type": data.get("target_type"),
                    "target_id": data.get("target_id"),
                    "timestamp": event.timestamp.isoformat() if getattr(event, "timestamp", None) else None,
                }
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            bus.unsubscribe("__all__", queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
