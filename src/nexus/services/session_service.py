"""Agent session helpers: lifecycle, pinning, sequence allocation, default session, events."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.agent import Agent
from nexus.models.agent_session import ENDED_STATUSES, TRANSITIONS, AgentSessionRecord

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("active", "idle")


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def next_seq(db: AsyncSession, session_id: uuid.UUID) -> int:
    """Atomically allocate the next timeline sequence number for a session.

    A single UPDATE ... RETURNING, so concurrent writers to one session never
    receive the same number; the row lock also bumps last_activity_at.
    """
    result = await db.execute(
        update(AgentSessionRecord)
        .where(AgentSessionRecord.id == session_id)
        .values(event_seq=AgentSessionRecord.event_seq + 1, last_activity_at=_utcnow())
        .returning(AgentSessionRecord.event_seq)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class SessionStateError(HTTPException):
    """A lifecycle transition the state machine does not allow (409)."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def transition(record: AgentSessionRecord, to: str) -> None:
    """Move a session to ``to`` if TRANSITIONS allows it; ending it stamps ended_at.

    Re-asserting an open session's current status is a no-op. Anything out of
    an ended status raises, so a finished session can never silently resume.
    """
    if to == record.status and to in OPEN_STATUSES:
        return
    if to not in TRANSITIONS.get(record.status, ()):
        raise SessionStateError(f"Session is {record.status}; it cannot become {to}")
    record.status = to
    if to in ENDED_STATUSES:
        record.ended_at = _utcnow()


# ---------------------------------------------------------------------------
# Adapter/model pinning
# ---------------------------------------------------------------------------


class SessionPinUnavailable(HTTPException):
    """The session's pinned adapter/connection can no longer run it (409)."""

    def __init__(self, reason: str, session_id: uuid.UUID | None = None) -> None:
        where = f"/api/v1/sessions/{session_id}/repin" if session_id else "the repin route"
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{reason}. The session will not switch models on its own: "
            f"POST {where} to pin it to the agent's current configuration, "
            "or start a new session.",
        )


def agent_pin(agent: Agent) -> dict[str, Any]:
    """The pin a session opened for ``agent`` right now would carry."""
    return {
        "adapter_type": agent.adapter_type or "unknown",
        "model": agent.model,
        "llm_connection_id": agent.connection_id,
    }


def session_pin(record: AgentSessionRecord) -> dict[str, Any]:
    return {
        "adapter_type": record.adapter_type,
        "model": record.model,
        "llm_connection_id": record.llm_connection_id,
    }


def is_pinned(record: AgentSessionRecord) -> bool:
    return record.adapter_type != "unknown"


def apply_pin(record: AgentSessionRecord, pin: dict[str, Any]) -> None:
    for key, value in pin.items():
        setattr(record, key, value)


async def check_pin(
    db: AsyncSession,
    company_id: uuid.UUID,
    pin: dict[str, Any],
    session_id: uuid.UUID | None = None,
) -> None:
    """Raise SessionPinUnavailable unless ``pin`` resolves to an installed adapter.

    A connection must belong to the company and be active. Without one, the
    adapter type must name a known provider: unlike the agent-level resolver
    there is no default-to-anthropic here. The model name itself is not
    checked; the provider rejects an unknown model at call time.
    """
    from nexus.adapters.registry import AdapterRegistry
    from nexus.adapters.uastl import PROVIDER_ALIASES, PROVIDERS
    from nexus.models.connection import LLMConnection

    connection_id = pin["llm_connection_id"]
    if connection_id is not None:
        conn = (
            await db.execute(
                select(LLMConnection).where(
                    LLMConnection.id == connection_id, LLMConnection.company_id == company_id
                )
            )
        ).scalar_one_or_none()
        if conn is None or not conn.is_active:
            raise SessionPinUnavailable(
                f"Pinned LLM connection {connection_id} is no longer available", session_id
            )
        registry_key = conn.wire_format
    else:
        adapter_type = pin["adapter_type"]
        provider = PROVIDERS.get(PROVIDER_ALIASES.get(adapter_type, adapter_type))
        if provider is None:
            raise SessionPinUnavailable(
                f"Pinned adapter {adapter_type!r} is not a known provider", session_id
            )
        registry_key = provider["registry_key"]
    if not AdapterRegistry().is_registered(registry_key):
        raise SessionPinUnavailable(f"Adapter {registry_key!r} is not installed", session_id)


async def begin_session_turn(db: AsyncSession, record: AgentSessionRecord, agent: Agent) -> Agent:
    """Wake the session for a turn and return the agent as the session runs it.

    An ended session raises SessionStateError and an unusable pin raises
    SessionPinUnavailable, both before anything is stored or spent. An
    unpinned (ws03 legacy) session adopts the agent's current config here.
    The returned Agent is a transient copy carrying the session's adapter,
    model and connection; it is never added to a database session.
    """
    transition(record, "active")
    if not is_pinned(record):
        apply_pin(record, agent_pin(agent))
    # ponytail: checked here, re-resolved inside _call_llm; a connection
    # deactivated between the two falls back the old agent-level way.
    await check_pin(db, record.company_id, session_pin(record), record.id)
    return Agent(
        **{
            **agent.model_dump(),
            "adapter_type": record.adapter_type,
            "model": record.model,
            "connection_id": record.llm_connection_id,
        }
    )


def new_session_for(agent: Agent, **fields: Any) -> AgentSessionRecord:
    """A session pinned to the agent's current adapter, model and connection."""
    return AgentSessionRecord(
        company_id=agent.company_id, agent_id=agent.id, **agent_pin(agent), **fields
    )


async def get_or_create_default_session(db: AsyncSession, agent: Agent) -> AgentSessionRecord:
    """The session the legacy per-agent chat routes write into.

    Reuses the agent's most recently active open session (a ws03-backfilled
    legacy session is idle, so pre-session history continues in place),
    otherwise creates one. The legacy routes have no repin operation, so when
    the agent's adapter/model/connection changed since that session was
    pinned, the session is completed and a new one opened on the new config:
    changing the agent is the explicit act, and no session is re-pinned
    behind the client's back. Legacy history reads by agent, so the
    conversation still reads as one.
    """
    # ponytail: two concurrent first messages can each create a session; both
    # stay valid, later turns converge on the most recent. A partial unique
    # index on (agent_id) WHERE default would close it if it ever matters.
    existing = (
        await db.execute(
            select(AgentSessionRecord)
            .where(
                AgentSessionRecord.company_id == agent.company_id,
                AgentSessionRecord.agent_id == agent.id,
                AgentSessionRecord.status.in_(OPEN_STATUSES),
            )
            .order_by(AgentSessionRecord.last_activity_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None and (
        not is_pinned(existing) or session_pin(existing) == agent_pin(agent)
    ):
        return existing
    record = new_session_for(agent, created_by="chat")
    db.add(record)
    await db.flush()
    if existing is not None:
        from nexus.governance.audit_service import record_audit

        transition(existing, "completed")
        await record_audit(
            agent.company_id,
            "session.rolled_over",
            actor_type="system",
            resource_type="session",
            resource_id=str(existing.id),
            details={
                "agent_id": str(agent.id),
                "reason": "agent adapter/model/connection changed",
                "next_session_id": str(record.id),
            },
            db=db,
        )
    return record


# SSE channel the workspace UI subscribes to; the stream still filters by tenant.
SESSION_CHANNEL = "sessions"


async def publish_session_event(
    event_type: str, company_id: uuid.UUID, payload: dict[str, Any]
) -> None:
    """Fan a session lifecycle event out on the SSE bus, tenant-scoped."""
    try:
        from nexus.api.routes.events import event_bus
        from nexus.realtime.events import RealtimeEvent

        await event_bus.publish(
            event_type,
            RealtimeEvent(
                event_type=event_type,
                payload=payload,
                channel=SESSION_CHANNEL,
                company_id=company_id,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - realtime is best-effort
        logger.debug("session event %s not published: %s", event_type, exc)
