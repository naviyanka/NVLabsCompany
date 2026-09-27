"""Agent session API — create, inspect and converse within an AgentSessionRecord.

A session is the unit the workspace UI works in: its timeline merges the
transcript (``chat_messages``), tool calls (``tool_invocations``), committed
spend (``cost_events``) and checkpoints, all linked by ``session_id``. The
legacy per-agent chat routes keep working and write into the agent's default
session, so both views show the same history.

Every route resolves the session within the caller's company; a session from
another tenant is a 404, never a 403, so its existence is not disclosed.

Lifecycle transitions go through ``session_service.transition`` (see
``TRANSITIONS`` in the model): ended sessions never resume. A turn runs on the
session's pinned adapter/model/connection or not at all (409); the pin only
changes through ``POST /api/v1/sessions/{id}/repin``.

This is the one session API. The older ``/api/v1/agents/{id}/sessions/...``
pause/resume/terminate routes in ``adapters.py`` are deprecated aliases over
the same records.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from nexus.api.deps import (
    CurrentCompanyId,
    CurrentPrincipal,
    DbSession,
    PathCompanyId,
    RequireAdmin,
    require_permission,
)
from nexus.api.routes import chat
from nexus.models.agent_session import ENDED_STATUSES, AgentSessionRecord
from nexus.models.budget import CostEvent
from nexus.models.chat import ChatMessage
from nexus.models.tool_invocation import ToolInvocation
from nexus.models.workspace import Workspace
from nexus.runtime.checkpoint import ExecutionCheckpoint
from nexus.services.session_service import (
    agent_pin,
    apply_pin,
    begin_session_turn,
    check_pin,
    new_session_for,
    publish_session_event,
    session_pin,
    transition,
)
from nexus.services.worktree_service import release_session_worktree

router = APIRouter(tags=["sessions"])

READ = [require_permission("read", "session")]
WRITE = [require_permission("write", "session")]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    workspace_id: uuid.UUID | None = None


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    # Only transitions a client may request; terminate has its own route and
    # failed is set by the runtime.
    status: Literal["active", "idle", "completed"] | None = None


class SessionMessageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)


class SessionOut(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID
    workspace_id: uuid.UUID | None
    status: str
    title: str | None
    adapter_type: str
    model: str | None
    llm_connection_id: uuid.UUID | None
    external_session_id: str | None
    event_seq: int
    created_by: str | None
    metadata: dict[str, Any] | None
    started_at: datetime
    last_activity_at: datetime
    ended_at: datetime | None


def _out(s: AgentSessionRecord) -> SessionOut:
    return SessionOut(**s.model_dump(exclude={"session_metadata"}), metadata=s.session_metadata)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


async def _get_session(db: Any, session_id: uuid.UUID, company_id: uuid.UUID) -> AgentSessionRecord:
    record = (
        await db.execute(
            select(AgentSessionRecord).where(
                AgentSessionRecord.id == session_id, AgentSessionRecord.company_id == company_id
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found"
        )
    return record


def _require_open(record: AgentSessionRecord) -> None:
    if record.status in ENDED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Session is {record.status}"
        )


async def _audit(
    db: Any, company_id: uuid.UUID, action: str, record: AgentSessionRecord, **details: Any
) -> None:
    from nexus.governance.audit_service import record_audit

    await record_audit(
        company_id,
        action,
        actor_type="user",
        resource_type="session",
        resource_id=str(record.id),
        details={"agent_id": str(record.agent_id), **details},
        db=db,
    )


async def _publish(db: Any, event_type: str, record: AgentSessionRecord, **extra: Any) -> None:
    """Commit, then announce: a listener that refetches must find the change."""
    await db.commit()
    await publish_session_event(
        event_type,
        record.company_id,
        {
            "session_id": str(record.id),
            "agent_id": str(record.agent_id),
            "status": record.status,
            **extra,
        },
    )


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


@router.get("/api/v1/companies/{company_id}/sessions", dependencies=READ)
async def list_sessions(
    company_id: PathCompanyId,
    db: DbSession,
    agent_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Sessions newest-activity first. ``cursor`` is the previous page's ``next_cursor``."""
    stmt = select(AgentSessionRecord).where(AgentSessionRecord.company_id == company_id)
    if agent_id:
        stmt = stmt.where(AgentSessionRecord.agent_id == agent_id)
    if workspace_id:
        stmt = stmt.where(AgentSessionRecord.workspace_id == workspace_id)
    if status_filter:
        stmt = stmt.where(AgentSessionRecord.status == status_filter)
    if cursor:
        at, _, last_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                AgentSessionRecord.last_activity_at < at,
                and_(AgentSessionRecord.last_activity_at == at, AgentSessionRecord.id < last_id),
            )
        )
    stmt = stmt.order_by(
        AgentSessionRecord.last_activity_at.desc(), AgentSessionRecord.id.desc()
    ).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars())
    page = rows[:limit]
    next_cursor = (
        _encode_cursor(page[-1].last_activity_at, 0, page[-1].id) if len(rows) > limit else None
    )
    return {"items": [_out(r) for r in page], "next_cursor": next_cursor}


@router.post(
    "/api/v1/agents/{agent_id}/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionOut,
    dependencies=WRITE,
)
async def create_session(
    agent_id: uuid.UUID, body: SessionCreate, company_id: CurrentCompanyId, db: DbSession
) -> SessionOut:
    """Open a session pinned to the agent's current adapter, model and connection.

    The client cannot choose the model or connection: they come from the agent
    row, server-side, and must be usable now (409 otherwise).
    """
    agent = await chat._load_agent(db, agent_id, company_id)
    await check_pin(db, company_id, agent_pin(agent))
    if body.workspace_id is not None:
        owned = (
            await db.execute(
                select(Workspace.id).where(
                    Workspace.id == body.workspace_id, Workspace.company_id == company_id
                )
            )
        ).scalar_one_or_none()
        if owned is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace {body.workspace_id} not found",
            )
    record = new_session_for(
        agent, title=body.title, workspace_id=body.workspace_id, created_by="api"
    )
    db.add(record)
    await db.flush()
    await _audit(db, company_id, "session.created", record)
    await _publish(db, "session.created", record)
    return _out(record)


@router.get("/api/v1/sessions/{session_id}", response_model=SessionOut, dependencies=READ)
async def get_session(
    session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> SessionOut:
    return _out(await _get_session(db, session_id, company_id))


@router.patch("/api/v1/sessions/{session_id}", response_model=SessionOut, dependencies=WRITE)
async def update_session(
    session_id: uuid.UUID, body: SessionUpdate, company_id: CurrentCompanyId, db: DbSession
) -> SessionOut:
    record = await _get_session(db, session_id, company_id)
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes:
        transition(record, changes["status"])
        await release_session_worktree(db, record)
    if "title" in changes:
        record.title = changes["title"]
    await db.flush()
    await _audit(db, company_id, "session.updated", record, changes=changes)
    await _publish(db, "session.updated", record)
    return _out(record)


@router.post(
    "/api/v1/sessions/{session_id}/terminate", response_model=SessionOut, dependencies=WRITE
)
async def terminate_session(
    session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> SessionOut:
    record = await _get_session(db, session_id, company_id)
    transition(record, "terminated")
    await release_session_worktree(db, record)
    await db.flush()
    await _audit(db, company_id, "session.terminated", record)
    await _publish(db, "session.terminated", record)
    return _out(record)


@router.post("/api/v1/sessions/{session_id}/repin", response_model=SessionOut, dependencies=WRITE)
async def repin_session(
    session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> SessionOut:
    """Pin an open session to its agent's current adapter, model and connection.

    The only way a session changes model. The new pin comes from the agent
    row, server-side, and is checked before it is saved.
    """
    record = await _get_session(db, session_id, company_id)
    _require_open(record)
    agent = await chat._load_agent(db, record.agent_id, company_id)
    before, after = session_pin(record), agent_pin(agent)
    await check_pin(db, company_id, after, record.id)
    apply_pin(record, after)
    await db.flush()
    await _audit(
        db,
        company_id,
        "session.repinned",
        record,
        before=jsonable_encoder(before),
        after=jsonable_encoder(after),
    )
    await _publish(db, "session.repinned", record)
    return _out(record)


@router.delete("/api/v1/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession, principal: RequireAdmin
) -> None:
    """Delete an ended session and its transcript; other linked rows keep their data."""
    record = await _get_session(db, session_id, company_id)
    if record.status not in ENDED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="End the session before deleting it"
        )
    # Explicit rather than relying on FK actions, which SQLite leaves off by default.
    from sqlalchemy import delete, update

    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == record.id))
    for model in (ToolInvocation, CostEvent, ExecutionCheckpoint):
        await db.execute(update(model).where(model.session_id == record.id).values(session_id=None))
    await _audit(db, company_id, "session.deleted", record)
    await db.delete(record)
    await db.flush()
    await _publish(db, "session.deleted", record)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

# Rank breaks timestamp ties so the merged order is total: (at, rank, id).
_SOURCES: list[tuple[str, Any, Any]] = [
    ("checkpoint", ExecutionCheckpoint, ExecutionCheckpoint.created_at),
    ("message", ChatMessage, ChatMessage.created_at),
    ("tool_call", ToolInvocation, ToolInvocation.created_at),
    ("usage", CostEvent, CostEvent.occurred_at),
]


def _encode_cursor(at: datetime, rank: int, row_id: uuid.UUID) -> str:
    raw = json.dumps({"at": at.isoformat(), "r": rank, "id": str(row_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, int, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(data["at"]), int(data["r"]), uuid.UUID(data["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc


def _serialize(kind: str, row: Any) -> dict[str, Any]:
    if kind == "message":
        return {
            "seq": row.seq,
            "kind": row.kind,
            "sender": row.sender,
            "text": row.text,
            "model_used": row.model_used,
            "tokens_used": row.tokens_used,
            "payload": row.payload,
        }
    if kind == "tool_call":
        return {
            "tool_name": row.tool_name,
            "status": row.status,
            "duration_ms": row.duration_ms,
            "approval_state": row.approval_state,
            "error": row.error,
            "cost_cents": row.cost_cents,
        }
    if kind == "usage":
        return {
            "provider": row.provider,
            "model": row.model,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cost_cents": row.cost_cents,
        }
    return {"task_id": str(row.task_id), "step_index": row.step_index, "status": row.status}


@router.get("/api/v1/sessions/{session_id}/timeline", dependencies=READ)
async def get_timeline(
    session_id: uuid.UUID,
    company_id: CurrentCompanyId,
    db: DbSession,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Messages, tool calls, committed usage and checkpoints in one ordered stream."""
    record = await _get_session(db, session_id, company_id)
    after = _decode_cursor(cursor) if cursor else None

    merged: list[tuple[datetime, int, uuid.UUID, str, Any]] = []
    for rank, (kind, model, at_col) in enumerate(_SOURCES):
        stmt = select(model).where(model.session_id == record.id)
        if model is CostEvent:
            stmt = stmt.where(CostEvent.status == "committed")
        if after:
            c_at, c_rank, c_id = after
            if rank > c_rank:
                stmt = stmt.where(at_col >= c_at)
            elif rank < c_rank:
                stmt = stmt.where(at_col > c_at)
            else:
                stmt = stmt.where(or_(at_col > c_at, and_(at_col == c_at, model.id > c_id)))
        stmt = stmt.order_by(at_col, model.id).limit(limit)
        for row in (await db.execute(stmt)).scalars():
            merged.append((getattr(row, at_col.key), rank, row.id, kind, row))

    merged.sort(key=lambda item: item[:3])
    page = merged[:limit]
    items = [
        {"type": kind, "id": str(row_id), "at": at.isoformat(), **_serialize(kind, row)}
        for at, _, row_id, kind, row in page
    ]
    next_cursor = _encode_cursor(*page[-1][:3]) if len(merged) > limit else None
    return {"session_id": str(record.id), "items": items, "next_cursor": next_cursor}


@router.get("/api/v1/sessions/{session_id}/usage", dependencies=READ)
async def get_usage(
    session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> dict[str, Any]:
    """Committed spend attributed to the session (cost_events is the source of truth)."""
    record = await _get_session(db, session_id, company_id)
    row = (
        await db.execute(
            select(
                func.count(CostEvent.id),
                func.coalesce(func.sum(CostEvent.cost_cents), 0),
                func.coalesce(func.sum(CostEvent.input_tokens), 0),
                func.coalesce(func.sum(CostEvent.output_tokens), 0),
            ).where(
                CostEvent.session_id == record.id,
                CostEvent.company_id == company_id,
                CostEvent.status == "committed",
            )
        )
    ).one()
    return {
        "session_id": str(record.id),
        "events": row[0],
        "cost_cents": int(row[1]),
        "input_tokens": int(row[2]),
        "output_tokens": int(row[3]),
    }


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


async def _session_history(
    db: Any, company_id: uuid.UUID, session_id: uuid.UUID, limit: int = 10
) -> list[dict[str, Any]]:
    """The last ``limit`` messages of the session in order, in _call_llm's shape."""
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.company_id == company_id,
                ChatMessage.session_id == session_id,
                ChatMessage.kind == "message",
            )
            .order_by(ChatMessage.seq.desc())
            .limit(limit)
        )
    ).scalars()
    return [{"sender": r.sender, "text": r.text} for r in reversed(list(rows))]


async def _begin_turn(db: Any, session_id: uuid.UUID, company_id: uuid.UUID, prompt: str):
    """Shared setup for a turn: wake the session, check its pin, store the user message.

    Returns the agent as pinned by the session; state and pin errors (409)
    are raised before anything is stored or spent.
    """
    record = await _get_session(db, session_id, company_id)
    agent = await begin_session_turn(
        db, record, await chat._load_agent(db, record.agent_id, company_id)
    )
    system_prompt = await chat._build_chat_prompt(db, agent, company_id, prompt)
    history = await _session_history(db, company_id, record.id)
    stored = await chat._persist_message_to_db(
        db, agent.id, company_id, "user", prompt, session_id=record.id
    )
    if stored is None:
        # Nothing has been spent yet; refuse rather than run an unrecorded turn.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not record message"
        )
    return record, agent, system_prompt, history


@router.post("/api/v1/sessions/{session_id}/messages", dependencies=WRITE)
async def send_message(
    session_id: uuid.UUID,
    body: SessionMessageRequest,
    company_id: CurrentCompanyId,
    db: DbSession,
    principal: CurrentPrincipal = None,
) -> dict[str, Any]:
    """Run one turn. The reply's place in the session is ``seq``; read the rest via the timeline."""
    record, agent, system_prompt, history = await _begin_turn(
        db, session_id, company_id, body.prompt
    )
    text, model_used, tokens_used = await chat._call_llm(
        agent, system_prompt, body.prompt, history, session_id=record.id, principal=principal
    )
    reply = await chat._persist_message_to_db(
        db,
        agent.id,
        company_id,
        "agent",
        text,
        session_id=record.id,
        model_used=model_used,
        tokens_used=tokens_used,
    )
    await chat._record_chat_audit(
        db, company_id, agent.id, body.prompt, text, model_used, tokens_used, record.id
    )
    await _publish(db, "session.message", record, seq=reply.seq if reply else None)
    return {
        "session_id": str(record.id),
        "message": {
            "id": str(reply.id) if reply else None,
            "sender": "agent",
            "text": text,
            "timestamp": (reply.created_at if reply else _utcnow()).isoformat(),
        },
        "seq": reply.seq if reply else None,
        "model_used": model_used,
        "tokens_used": tokens_used,
    }


@router.post("/api/v1/sessions/{session_id}/messages/stream", dependencies=WRITE)
async def stream_message(
    session_id: uuid.UUID,
    body: SessionMessageRequest,
    company_id: CurrentCompanyId,
    db: DbSession,
    principal: CurrentPrincipal = None,
) -> StreamingResponse:
    """Same as ``send_message`` but streamed as SSE, in the legacy chat stream format."""
    record, agent, system_prompt, history = await _begin_turn(
        db, session_id, company_id, body.prompt
    )
    # The generator writes the reply on its own connection and bumps this
    # session row; commit first so it does not wait on this transaction.
    await db.commit()
    await _publish(db, "session.message", record)
    return chat._sse_response(
        chat._stream_reply(
            agent, company_id, system_prompt, body.prompt, history, record.id, principal
        )
    )
