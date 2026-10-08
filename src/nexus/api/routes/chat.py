"""Agent Chat API — real LLM-powered conversations with agents.

Connects the soul/persona system, memory, and LLM adapters to provide
genuine agent responses based on their configured personality, role,
capabilities, and conversation history.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession
from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.memory import MemoryRecord
from nexus.models_router.preflight import BudgetInfraUnavailable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nexus.tools.context import ExecutionContext

logger = logging.getLogger(__name__)

FACT_MAX_CHARS = 2000  # longest chat-extracted fact stored as memory
FACT_EXTRACTOR_VERSION = "fact-extractor-v1"  # provenance stamp on chat-extracted memory

router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Request body for sending a message to an agent."""

    prompt: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str | None = None
    # Idempotency key (the Idempotency-Key header wins). A retry with the same
    # key attaches to the turn it already created instead of starting another.
    request_id: str | None = Field(default=None, min_length=1, max_length=255)
    # Fail the turn rather than run a manager or the CEO without its governed
    # tools (on a backend without per-run MCP config; a CEO is refused up front
    # with CEO_TOOLS_UNSUPPORTED). Can only refuse, never grant.
    require_manager_tools: bool = False
    # Store this prompt as a human directive in the CEO's executive memory.
    # Only a human may, and only to the company's current CEO.
    record_directive: bool = False


class ChatMessage(BaseModel):
    """A single message in a conversation."""

    id: str
    sender: str  # "user" or "agent"
    text: str
    timestamp: str
    # Stable placement and provenance, so a client can merge a refetched
    # transcript by ID and label each reply with what actually produced it.
    seq: int | None = None
    session_id: str | None = None
    model_used: str | None = None
    adapter_used: str | None = None
    backend_used: str | None = None
    partial: bool = False


class ChatResponse(BaseModel):
    """Response from an agent chat interaction."""

    message: ChatMessage
    history: list[ChatMessage]
    model_used: str | None = None
    tokens_used: int = 0
    # Which adapter / CLI backend actually produced the reply (None when the
    # adapter reports nothing, e.g. an API adapter has no CLI backend).
    adapter_used: str | None = None
    backend_used: str | None = None
    execution_id: str | None = None


# ---------------------------------------------------------------------------
# Persistent conversation store
# ---------------------------------------------------------------------------
# Conversation store — in-memory for speed, with DB persistence
# ---------------------------------------------------------------------------

_conversations: dict[str, list[dict[str, Any]]] = {}
_cache_loaded_at: dict[str, float] = {}
_CACHE_TTL_SECONDS = 5.0


def _get_history(agent_id: str) -> list[dict[str, Any]]:
    """Get conversation history for an agent (in-memory cache)."""
    return _conversations.get(agent_id, [])


async def _get_history_fresh(
    db: "AsyncSession", agent_id: str, company_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Return history for an agent, re-reading from DB when the cache is stale.

    The in-memory cache is per-process; with multiple workers a message written
    by one worker would otherwise never appear to the others. A short TTL keeps
    reads cheap locally while bounding cross-worker staleness.
    """
    import time

    loaded_at = _cache_loaded_at.get(agent_id)
    if loaded_at is not None and (time.monotonic() - loaded_at) < _CACHE_TTL_SECONDS:
        return _conversations.get(agent_id, [])
    records = await _load_history_from_db(db, uuid.UUID(agent_id), company_id)
    if records:
        _conversations[agent_id] = records
        _cache_loaded_at[agent_id] = time.monotonic()
    return _conversations.get(agent_id, [])


async def _persist_from_generator(
    agent_id: uuid.UUID,
    company_id: uuid.UUID,
    sender: str,
    text: str,
    *,
    session_id: uuid.UUID | None = None,
    model_used: str | None = None,
    tokens_used: int = 0,
    payload: dict[str, Any] | None = None,
) -> None:
    """Persist a message on its own session, for use inside an SSE generator.

    The request's session is closed once the endpoint returns its
    StreamingResponse, but the generator body runs after that. A streamed message
    therefore needs a session of its own, or it only ever reaches the in-process
    cache and is gone on restart.
    """
    try:
        from nexus.database import tenant_session

        # Tenant-scoped so RLS admits the insert and the session seq UPDATE.
        async with tenant_session(company_id) as own:
            await _persist_message_to_db(
                own, agent_id, company_id, sender, text,
                session_id=session_id, model_used=model_used, tokens_used=tokens_used,
                payload=payload,
            )
            await own.commit()
    except Exception as exc:  # noqa: BLE001 - persistence must not break the stream
        logger.warning("Could not persist streamed message for agent %s: %s", agent_id, exc)


def _add_message(agent_id: str, sender: str, text: str) -> dict[str, Any]:
    """Add a message to the conversation history (in-memory + DB persist)."""
    if agent_id not in _conversations:
        _conversations[agent_id] = []
    msg = {
        "id": f"msg-{uuid.uuid4().hex[:8]}",
        "sender": sender,
        "text": text,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    _conversations[agent_id].append(msg)
    # Keep last 100 messages per agent
    if len(_conversations[agent_id]) > 100:
        _conversations[agent_id] = _conversations[agent_id][-100:]
    return msg


async def _persist_message_to_db(
    db: "AsyncSession",
    agent_id: uuid.UUID,
    company_id: uuid.UUID,
    sender: str,
    text: str,
    *,
    session_id: uuid.UUID | None = None,
    model_used: str | None = None,
    tokens_used: int = 0,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Persist a chat message to the database for durability.

    With a ``session_id`` the row joins that session's timeline and takes the
    next ``seq``. Returns the stored row, or None if persistence failed.
    """
    try:
        from nexus.models.chat import ChatMessage as ChatMessageModel
        seq = None
        if session_id is not None:
            from nexus.services.session_service import next_seq

            seq = await next_seq(db, session_id)
        record = ChatMessageModel(
            company_id=company_id,
            agent_id=agent_id,
            sender=sender,
            text=text[:10000],
            session_id=session_id,
            seq=seq,
            model_used=model_used,
            tokens_used=tokens_used,
            payload=payload,
        )
        db.add(record)
        await db.flush()
        return record
    except Exception:
        return None  # Best-effort persistence, don't break chat flow


async def _load_history_from_db(
    db: "AsyncSession", agent_id: uuid.UUID, company_id: uuid.UUID, limit: int = 100
) -> list[dict[str, Any]]:
    """The agent's last ``limit`` messages in conversation order, as ``_message_out``.

    Sessions in the order they started, each in ``seq`` order (``seq`` is the
    session's commit order; ``created_at`` is taken before the session lock
    and can disagree with it under concurrent turns). A reply sits right after
    its prompt even when a later prompt was stored first, as the model saw it
    (``chat_turns.session_history``).
    """
    try:
        from nexus.models.agent_session import AgentSessionRecord
        from nexus.models.chat import ChatMessage as ChatMessageModel
        from nexus.models.chat_turn import ChatTurn

        started = func.coalesce(AgentSessionRecord.started_at, ChatMessageModel.created_at)
        place = func.coalesce(ChatTurn.turn_seq, ChatMessageModel.seq)
        stmt = (
            select(ChatMessageModel)
            .outerjoin(
                AgentSessionRecord,
                (AgentSessionRecord.id == ChatMessageModel.session_id)
                & (AgentSessionRecord.company_id == company_id),
            )
            .outerjoin(
                ChatTurn,
                (ChatTurn.response_message_id == ChatMessageModel.id)
                & (ChatTurn.company_id == company_id),
            )
            .where(
                ChatMessageModel.agent_id == agent_id,
                ChatMessageModel.company_id == company_id,
                ChatMessageModel.kind == "message",
            )
            .order_by(
                started.desc(),
                place.desc(),
                ChatMessageModel.seq.desc(),
                ChatMessageModel.created_at.desc(),
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        return [_message_out(r) for r in reversed(list(result.scalars().all()))]
    except Exception:
        logger.warning("could not load chat history for agent %s", agent_id, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Adapter → LLM call logic
# ---------------------------------------------------------------------------


async def _fetch_live_platform_context(
    db: "AsyncSession", company_id: uuid.UUID, user_prompt: str
) -> str:
    """Fetch live platform data relevant to the user's question from the database.

    Read-only: queries the real database to provide accurate, real-time answers
    about agents, tasks, goals and budget. Prompt text never creates or assigns
    work; that goes through governed tools.
    """
    from nexus.models.task import Task, Goal

    context_parts: list[str] = []
    prompt_lower = user_prompt.lower()

    # Query all agents for the company
    stmt = select(Agent).where(Agent.company_id == company_id)
    result = await db.execute(stmt)
    agents = list(result.scalars().all())
    active = [a for a in agents if a.status in ("active", "ready", "idle")]

    agent_by_name = {a.name.lower(): a for a in agents}

    # Include the workforce roster when agents/tasks are mentioned
    include_agents = any(
        kw in prompt_lower
        for kw in ["agent", "workforce", "team", "hired", "who", "assign", "task", "member"]
    ) or any(name in prompt_lower for name in agent_by_name)
    if include_agents or len(agents) > 0:
        agent_lines = "\n".join(
            f"  - Name: {a.name} | ID: {a.id} | Role: {a.role} | Title: {a.title or a.role} | Adapter: {a.adapter_type} | Model: {a.model or 'default'} | Status: {a.status}"
            for a in agents
        )
        context_parts.append(
            f"[LIVE WORKFORCE DATA] Company has {len(agents)} registered agents ({len(active)} active/ready):\n{agent_lines}"
        )

    # Task-related queries
    include_tasks = any(
        kw in prompt_lower for kw in ["task", "pending", "progress", "work", "assigned", "assign", "do"]
    )
    if include_tasks:
        stmt = select(Task).where(Task.company_id == company_id).order_by(Task.created_at.desc()).limit(20)
        result = await db.execute(stmt)
        tasks = list(result.scalars().all())
        if tasks:
            task_lines = "\n".join(
                f"  - Task ID: {t.id} | Title: {t.title} | Status: {t.status} | Assigned Agent ID: {t.assigned_agent_id or 'unassigned'}"
                for t in tasks
            )
            context_parts.append(
                f"[LIVE TASK DATA] Total {len(tasks)} tasks:\n{task_lines}"
            )

    # Goal-related queries
    if any(kw in prompt_lower for kw in ["goal", "objective", "okr", "strategy"]):
        stmt = select(Goal).where(Goal.company_id == company_id).limit(10)
        result = await db.execute(stmt)
        goals = list(result.scalars().all())
        if goals:
            goal_lines = "\n".join(
                f"  - [{g.status}] {g.title} (Owner Agent ID: {g.owner_agent_id or 'unassigned'})" for g in goals
            )
            context_parts.append(
                f"[LIVE GOALS DATA] {len(goals)} strategic goals:\n{goal_lines}"
            )

    # Budget-related queries
    if any(kw in prompt_lower for kw in ["budget", "spend", "cost", "money"]):
        from nexus.models.company import Company
        stmt = select(Company).where(Company.id == company_id)
        result = await db.execute(stmt)
        company = result.scalar_one_or_none()
        if company:
            budget = company.budget_monthly_cents / 100
            spent = company.spent_monthly_cents / 100
            context_parts.append(
                f"[LIVE BUDGET DATA] Budget: ${spent:.2f} spent of ${budget:.2f} monthly cap"
                if budget > 0 else
                f"[LIVE BUDGET DATA] Budget: ${spent:.2f} spent (no cap configured)"
            )

    if not context_parts:
        return ""

    return "\n\n".join(context_parts)


async def _fetch_agent_memories(
    db: "AsyncSession", agent_id: uuid.UUID, company_id: uuid.UUID,
    query: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """Fetch the most relevant memories for an agent from the database.

    When a query is provided (e.g. the user's chat prompt), performs keyword
    matching against memory content to surface the most relevant context.
    Falls back to top-N by importance when no query is given.
    """
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F811

    if query:
        # Keyword-based retrieval: match query terms against memory content
        keywords = [w.lower() for w in query.split() if len(w) > 2]
        # Fetch more candidates then rank by relevance
        stmt = (
            select(MemoryRecord)
            # Executive memory reaches the CEO only through ceo_service.
            .where(MemoryRecord.agent_id == agent_id, MemoryRecord.company_id == company_id,
                   MemoryRecord.scope != "executive",
                   MemoryRecord.status == "active")
            .order_by(MemoryRecord.importance.desc())
            .limit(100)  # Fetch larger pool for re-ranking
        )
        result = await db.execute(stmt)
        all_records = list(result.scalars().all())

        # Score by keyword overlap
        scored = []
        for r in all_records:
            content_lower = (r.content or "").lower()
            tags_lower = (getattr(r, "tags", "") or "").lower()
            # Count matching keywords
            matches = sum(1 for kw in keywords if kw in content_lower or kw in tags_lower)
            # Boost by importance
            score = matches * 2 + (r.importance or 0)
            if matches > 0 or r.importance >= 0.9:
                scored.append((score, r))

        # Sort by relevance score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        records = [r for _, r in scored[:limit]]
    else:
        stmt = (
            select(MemoryRecord)
            .where(MemoryRecord.agent_id == agent_id, MemoryRecord.company_id == company_id,
                   MemoryRecord.scope != "executive",
                   MemoryRecord.status == "active")
            .order_by(MemoryRecord.importance.desc(), MemoryRecord.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        records = list(result.scalars().all())

    memories = [
        {
            "content": r.content,
            "scope": r.scope,
            "importance": r.importance,
            "tier": r.tier,
            "trust": (r.record_metadata or {}).get("trust", "unspecified"),
            "origin": (r.record_metadata or {}).get("origin", "unspecified"),
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in records
    ]

    # L3 (shared) rows carry the *source* agent's id, so the agent-scoped query
    # above can never see them. Reading them here is what makes a fact one agent
    # promoted visible to the rest of the company.
    memories += await _fetch_shared_knowledge(company_id)
    return memories


async def _fetch_shared_knowledge(
    company_id: uuid.UUID, limit: int = 5
) -> list[dict[str, Any]]:
    """Read the company's promoted L3 facts through PersistentLayeredMemory.

    Its own session factory rather than the request's session: the layered store
    owns its transaction boundaries (it bumps access counts as it reads), and a
    failure here must not roll back the caller's work.

    Args:
        company_id: Tenant whose shared knowledge to read.
        limit: Maximum facts to return.

    Returns:
        Memory dicts in the shape ``_build_system_prompt`` expects, or an empty
        list when the lookup fails.
    """
    try:
        from nexus.database import tenant_session_factory
        from nexus.memory.layered_persistent import L3_SCOPE, PersistentLayeredMemory

        memory = PersistentLayeredMemory(
            session_factory=tenant_session_factory(company_id), company_id=company_id
        )
        return [
            {
                "content": fact.content,
                "scope": L3_SCOPE,
                # Shared knowledge earned promotion, so it outranks a raw L2 row
                # when the persona layer trims to its memory budget.
                "importance": 0.9,
                "tier": "warm",
                "trust": (fact.metadata or {}).get("trust", "unspecified"),
                "origin": (fact.metadata or {}).get("origin", "unspecified"),
                "created_at": fact.created_at.isoformat(),
            }
            for fact in await memory.get_shared_knowledge(limit=limit)
        ]
    except Exception as exc:  # noqa: BLE001 - missing shared context must not break chat
        logger.warning(
            "Shared knowledge lookup failed for %s: %s", company_id, type(exc).__name__
        )
        return []


async def _remember_response(
    agent: Agent, response_text: str, *, turn_id: uuid.UUID | None = None
) -> int:
    """Extract durable facts from an agent's reply and store them in L2.

    Chat history is a transcript: it is replayed verbatim and trimmed to the last
    few turns, so anything an agent worked out beyond that window was lost on the
    next request. This puts what the reply actually established into
    ``memory_records`` through :class:`PersistentLayeredMemory`, which dedups
    against the agent's existing rows and evicts its oldest when full -- so the
    knowledge survives a restart while the transcript stays bounded.

    Args:
        agent: The agent that produced the reply.
        response_text: The reply text.
        turn_id: The durable ChatTurn that produced the reply, set only by the turn
            worker. It is the source identity, so replaying the turn returns the
            facts it already stored. Without a turn (orchestrator, scheduler,
            webhooks) the source is a digest of agent and reply text, so a retry
            of the same reply still collapses.

    Returns:
        How many new facts were stored.
    """
    try:
        from nexus.database import tenant_session_factory
        from nexus.memory.extract import FactExtractor
        from nexus.memory.ingest import Origin
        from nexus.memory.layered_persistent import PersistentLayeredMemory
        from nexus.memory.safety import MemoryRejected

        facts = FactExtractor().extract_facts(response_text, agent.id)
        if not facts:
            return 0

        memory = PersistentLayeredMemory(
            session_factory=tenant_session_factory(agent.company_id),
            company_id=agent.company_id,
        )
        # One stable source per reply, never a random id: a replay must derive the same
        # ingestion keys. The reply message row is written after this call, so the turn
        # (or, with no turn, the reply text) is the identity; facts differ by category
        # and ordinal within it.
        digest = hashlib.sha256(f"{agent.id}\n{response_text}".encode()).hexdigest()
        reply_id = str(turn_id) if turn_id is not None else f"reply:{digest[:40]}"
        ordinals: dict[str, int] = {}
        stored = 0
        for fact in facts:
            category = str(fact.metadata.get("fact_type", "fact"))
            ordinal = ordinals[category] = ordinals.get(category, -1) + 1
            try:
                # Origin, not the extractor's metadata, makes this an untrusted candidate.
                wrote = await memory.store_fact(
                    agent.id,
                    fact.content,
                    metadata=fact.metadata,
                    origin=Origin.CHAT_EXTRACTION,
                    source_type="chat_reply",
                    source_id=reply_id,
                    extractor_version=FACT_EXTRACTOR_VERSION,
                    item_key=f"{category}:{ordinal}",
                    max_chars=FACT_MAX_CHARS,
                )
            except MemoryRejected:
                continue  # an oversized or malformed fact is dropped, not stored
            if wrote:
                stored += 1
        return stored
    except Exception as exc:  # noqa: BLE001 - remembering must not break chat
        # Class name only: the message can carry the rejected text.
        logger.warning("Could not store memory for agent %s: %s", agent.id, type(exc).__name__)
        return 0


def _build_system_prompt(agent: Agent, memories: list[dict[str, Any]] | None = None) -> str:
    """Build a system prompt from the agent's stored configuration and memory context.

    Uses Persona.build_working_context() to assemble identity, soul, memories,
    and task objectives under token budget constraints.
    """
    from nexus.identity.persona import ContextBudget, Persona
    from nexus.identity.soul import Soul

    # Try to build a proper Soul from agent fields
    soul = Soul(
        name=agent.name,
        role=agent.role or "",
        personality_traits=[],
        communication_style="",
        expertise=agent.capabilities or [],
        values=[],
        constraints=[],
        background=agent.soul_description or "",
        tone="professional",
    )

    # If soul_description contains structured persona data (from our hiring form),
    # parse the sections
    desc = agent.soul_description or ""
    if "Personality:" in desc:
        for line in desc.split("\n\n"):
            if line.startswith("Personality:"):
                soul.personality_traits = [
                    t.strip() for t in line.replace("Personality:", "").split(",")
                ]
            elif line.startswith("Communication:"):
                soul.communication_style = line.replace("Communication:", "").strip()
            elif line.startswith("Values:"):
                soul.values = [
                    v.strip() for v in line.replace("Values:", "").split(",")
                ]
            elif line.startswith("Constraints:"):
                soul.constraints = [
                    c.strip()
                    for c in line.replace("Constraints:", "").strip().split("\n")
                    if c.strip()
                ]
            elif line.startswith("Tone:"):
                soul.tone = line.replace("Tone:", "").strip()
            else:
                if not soul.background:
                    soul.background = line

    # Assemble WorkingContext using Persona token budgeting
    persona = Persona(agent_id=str(agent.id))
    budget = ContextBudget(
        total_tokens=4096,
        identity_tokens=1500,
        memory_tokens=1500,
        task_tokens=1096,
    )
    task_context: dict[str, Any] = {}
    if agent.responsibilities:
        task_context["responsibilities"] = agent.responsibilities
    if agent.objectives:
        task_context["objectives"] = agent.objectives

    working_ctx = persona.build_working_context(
        soul=soul,
        memories=memories or [],
        task=task_context,
        budget=budget,
    )

    prompt = working_ctx.system_prompt

    # Add role-specific context
    if agent.responsibilities:
        prompt += f"\n\nResponsibilities: {agent.responsibilities}"
    if agent.objectives:
        prompt += f"\n\nObjectives: {agent.objectives}"

    # No role-string authority: the designated CEO's instructions come from
    # ceo_service.chat_context, which _build_chat_prompt adds per turn.

    if working_ctx.recent_memories:
        # Recalled memory is reference data: escaped JSON in a fixed envelope, with
        # its trust label, so a stored string cannot pose as an instruction.
        from nexus.memory.safety import render_memory_data

        items = []
        for m in working_ctx.recent_memories:
            m = m if isinstance(m, dict) else {"content": m}  # a malformed entry is still data
            if m.get("content") is None:
                continue
            items.append(
                {
                    "content": str(m["content"]),
                    "scope": m.get("scope"),
                    "trust": m.get("trust", "unspecified"),
                    "origin": m.get("origin", "unspecified"),
                    "created_at": m.get("created_at"),
                }
            )
        if items:
            prompt += "\n\n" + render_memory_data(items)

    return prompt


async def _resolve_connection(agent: Agent) -> dict[str, Any] | None:
    """Load the agent's LLM Connection and resolve its api key, or None.

    Returns a plain dict {wire_format, base_url, api_key} so uastl stays free
    of model/DB imports. The raw key is resolved from the secret backend by
    ``api_key_ref``; a missing/unresolvable key yields api_key="".
    """
    if not getattr(agent, "connection_id", None):
        return None
    from nexus.database import tenant_session
    from nexus.models.connection import LLMConnection

    async with tenant_session(agent.company_id) as conn_db:
        conn = await conn_db.get(LLMConnection, agent.connection_id)
        if conn is None or not conn.is_active:
            return None
        api_key = ""
        if conn.api_key_ref:
            # The secret backend singleton is installed at app startup
            # (main.py -> rotation.set_backend). Resolve the key by ref; a
            # missing backend or ref leaves api_key empty (fail to no-key).
            from nexus.api.routes import rotation as _rotation

            backend = getattr(_rotation, "_backend", None)
            if backend is not None:
                api_key = await _maybe_await(backend.decrypt(conn.api_key_ref)) or ""
        return {
            "wire_format": conn.wire_format,
            "base_url": conn.base_url,
            "api_key": api_key,
        }


async def _maybe_await(value: Any) -> Any:
    """Await value if it is awaitable, else return it (decrypt may be sync)."""
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value


def _resolve_adapter_type(
    agent: Agent, connection: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """Resolve the adapter type and config from agent settings.

    Delegates to the UASTL provider registry (nexus.adapters.uastl), which is
    the single source of truth for adapter resolution. Legacy agent.adapter_type
    values (anthropic/openai/claude/claude_code/cli/ollama/azure/bedrock/google/
    langchain) keep their historical mappings; hermes resolves to the Hermes
    adapter with Ollama host + OpenRouter key config. When a resolved LLM
    Connection is passed, it overrides all of the above (WP-22b). Loading the
    Connection is async, so callers use :func:`_resolve_connection` first; this
    stays sync so the existing resolution tests keep working.
    """
    from nexus.adapters.uastl import ProviderResolutionError, resolve_provider

    try:
        return resolve_provider(
            agent.adapter_type or "anthropic",
            agent.model,
            connection=connection,
            adapter_config=getattr(agent, "adapter_config", None),
        )
    except ProviderResolutionError as exc:
        # Fail closed: never answer through a provider nobody configured.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "ADAPTER_CONFIG_INVALID", "message": str(exc)},
        ) from exc


async def _reserve_budget(
    agent: Agent,
    system_prompt: str,
    user_message: str,
    history: list[dict[str, Any]],
    config: dict[str, Any],
    session_id: uuid.UUID | None = None,
) -> Any:
    """Hold the estimated cost of an LLM call before making it.

    Checking after the fact only reports an overspend; checking without holding
    lets every concurrent worker pass the same check. This writes a reservation
    in the same transaction as the check, so the next worker sums this hold and
    refuses. :func:`_settle_budget` reconciles it to the real cost afterwards.

    Returns:
        The reservation row, or None when no reservation could be taken (no
        database, lookup failure) -- the call proceeds unheld rather than
        breaking chat.

    Raises:
        BudgetExceededError: When the cap would be reached and the configured
            policy is to stop.
    """
    from nexus.models_router.preflight import (
        BudgetExceededError,
        BudgetInfraUnavailable,
        estimate_min_call_cost,
    )

    # Rough token estimate: the adapters do not expose a tokenizer here, and the
    # ~4-characters-per-token rule is close enough for a floor. The last 10
    # history messages are what _call_llm actually sends.
    prompt_chars = len(system_prompt) + len(user_message)
    prompt_chars += sum(len(str(msg.get("text", ""))) for msg in history[-10:])
    estimate_usd = estimate_min_call_cost(config.get("model"), prompt_chars // 4)
    estimate_cents = max(1, round(estimate_usd * 100))

    try:
        from nexus.database import tenant_session
        from nexus.services.budget_service import BudgetService

        async with tenant_session(agent.company_id) as budget_db:
            # BudgetService already scopes to active policies and to the policy's
            # own window, so a monthly cap stays monthly rather than becoming a
            # lifetime one.
            allowed, reservation_ids, result = await BudgetService(
                budget_db
            ).reserve_chain(
                company_id=agent.company_id,
                estimate_cents=estimate_cents,
                agent_id=agent.id,
                provider=agent.adapter_type or "anthropic",
                model=config.get("model"),
            )
            if session_id is not None and reservation_ids:
                await _link_cost_events(budget_db, agent.company_id, reservation_ids, session_id)
    except Exception as exc:  # noqa: BLE001
        # R12: fail closed on budget. If the ledger is unreachable we refuse
        # the call rather than let unmetered spend through. The old behaviour
        # (allow on failure) is available behind BUDGET_FAIL_OPEN for operators
        # who would rather keep serving than enforce during an outage.
        from nexus.config import settings

        if settings.budget_fail_open:
            logger.warning(
                "Budget reservation failed, allowing call (fail-open): %s", type(exc).__name__
            )
            return None
        logger.error(
            "Budget reservation failed, refusing call (fail-closed): %s", type(exc).__name__
        )
        raise BudgetInfraUnavailable(
            "Budget ledger is unavailable and BUDGET_FAIL_OPEN is off"
        ) from exc

    if not allowed:
        raise BudgetExceededError(
            config.get("model"),
            estimate_usd,
            result.used_cents / 100.0,
            result.limit_cents / 100.0,
        )

    return reservation_ids or None


async def _link_cost_events(
    db: "AsyncSession", company_id: uuid.UUID, event_ids: list[Any], session_id: uuid.UUID
) -> None:
    """Attribute budget holds to a session; settlement updates these rows in place."""
    try:
        from sqlalchemy import update

        from nexus.models.budget import CostEvent

        await db.execute(
            update(CostEvent)
            .where(CostEvent.company_id == company_id, CostEvent.id.in_(event_ids))
            .values(session_id=session_id)
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - attribution must not refuse a paid-for call
        logger.warning(
            "Could not link cost events to session %s: %s", session_id, type(exc).__name__
        )


async def _settle_budget(
    reservation_id: Any,
    cost_cents: int,
    *,
    company_id: uuid.UUID,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str | None = None,
) -> None:
    """Phase two of the spend: reconcile or release a hold from ``_reserve_budget``.

    A zero cost means the call never billed (provider error, in-character
    fallback), so the hold is released rather than settled at zero -- otherwise
    the row stays on the books as reserved until its TTL and makes the budget
    look more spent than it is.

    Args:
        reservation_id: Id from :func:`_reserve_budget`, or None when no hold
            was taken.
        cost_cents: Actual cost in cents.
        company_id: Tenant of the holds; settling updates its budget policies.
        input_tokens: Actual input tokens.
        output_tokens: Actual output tokens.
        model: Model actually used.
    """
    if reservation_id is None:
        return
    # _reserve_budget returns a list of holds (one per policy scope: company +
    # agent). Settle every one. A bare id is still accepted for back-compat.
    ids = reservation_id if isinstance(reservation_id, list) else [reservation_id]
    for rid in ids:
        await _settle_one(rid, cost_cents, company_id, input_tokens, output_tokens, model)


async def _settle_one(
    reservation_id: Any,
    cost_cents: int,
    company_id: uuid.UUID,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str | None = None,
) -> None:
    """Settle or release a single hold."""
    try:
        from nexus.database import tenant_session
        from nexus.services.budget_service import BudgetService

        async with tenant_session(company_id) as budget_db:
            service = BudgetService(budget_db)
            if cost_cents > 0:
                await service.commit_reservation(
                    reservation_id,
                    cost_cents=cost_cents,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model=model,
                )
            else:
                await service.release_reservation(reservation_id)
    except Exception as exc:  # noqa: BLE001 - settlement must not break chat
        # The hold expires on its own, so a failure here overstates spend for
        # the TTL rather than losing the guardrail.
        logger.warning("Budget settlement failed for %s: %s", reservation_id, type(exc).__name__)


PROVIDER_UNAVAILABLE_CODE = "PROVIDER_UNAVAILABLE"
PROVIDER_UNAVAILABLE_MESSAGE = (
    "I'm unable to reach the configured model provider right now. Please try again."
)


async def _call_llm(
    agent: Agent,
    system_prompt: str,
    user_message: str,
    history: list[dict[str, Any]],
    temperature: float | None = None,
    session_id: uuid.UUID | None = None,
    principal: Principal | None = None,
    source: str | None = None,
    context: ExecutionContext | None = None,
    execution: dict[str, Any] | None = None,
    turn_id: uuid.UUID | None = None,
    turn_epoch: tuple[str | None, int] | None = None,
) -> tuple[str, str, int]:
    """Call the LLM adapter to get a real response.

    Args:
        agent: The agent whose adapter to use.
        system_prompt: Generated system prompt from soul.
        user_message: The user's message.
        history: Conversation history for context.
        temperature: Optional sampling temperature override. Judges and other
            deterministic callers should pass 0.0.
        session_id: Optional agent session the call belongs to; its budget
            holds (and so its settled cost) are attributed to that session.
        principal: The authenticated caller. Every HTTP route must pass it,
            so tool calls are authorized with that principal's company and
            role. ``None`` means autonomous work (scheduler, orchestrator,
            webhook), which acts as the agent itself with the ``agent`` role.
        source: Request type recorded with each tool call; defaults to
            ``chat`` for a principal and ``background`` otherwise.
        context: A context the server built where the work was authorized
            and carried here, such as a pipeline run's through a Temporal
            activity. Used instead of ``principal``: its principal, role and
            source are kept and it is bound to ``agent``. It must be for the
            agent's company and name no other agent.
        execution: Optional dict the caller passes to learn which adapter,
            CLI backend and execution ID produced the reply.
        turn_id: The durable chat turn this call serves, set only by the turn
            worker; it becomes the source of any memory extracted from the reply.
        turn_epoch: ``(execution_id, attempt_count)`` of the turn as the worker claimed it,
            set only with ``turn_id``. It is what a ledgered write is fenced by: the write is
            refused once a recovery has moved the turn on. Never taken from ``context``.

    Returns:
        Tuple of (response_text, model_used, tokens_used).
    """
    from dataclasses import replace

    from nexus.adapters.registry import AdapterRegistry
    from nexus.tools.context import ExecutionContext

    if getattr(agent, "status", None) == "configuration_required":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "AGENT_CONFIGURATION_REQUIRED",
                "message": f"{agent.name} must be configured before it can receive work",
            },
        )
    connection = await _resolve_connection(agent)
    registry_key, config = _resolve_adapter_type(agent, connection)
    if execution is not None:
        execution.update(adapter=registry_key, backend=config.get("backend"))
    try:
        if context is None:
            execution_context = ExecutionContext.for_call(
                agent,
                principal,
                source=source or ("chat" if principal is not None else "background"),
                session_id=session_id,
                adapter=registry_key,
                model=config.get("model"),
            )
        else:
            if principal is not None:
                raise ValueError("pass either principal or context, not both")
            # A run token's context is fixed to its own agent, as in
            # ExecutionContext.for_principal.
            if context.company_id != agent.company_id or context.agent_id not in (None, agent.id):
                raise PermissionError("execution context is for a different company or agent")
            execution_context = replace(
                context,
                agent_id=agent.id,
                session_id=session_id or context.session_id,
                adapter=registry_key,
                model=config.get("model"),
            )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if turn_id is not None and execution_context.turn_id is None:
        # The turn's stable id is what lets a recovered turn recognise a tool call it already
        # made (nexus.tools.effects). Unlike the per-claim execution id, it survives requeue.
        execution_context = replace(execution_context, turn_id=turn_id)
    if turn_id is not None:
        # Always overwritten, so a context that arrived carrying an epoch cannot choose one.
        execution_context = replace(
            execution_context,
            turn_execution=turn_epoch[0] if turn_epoch else None,
            turn_attempt=turn_epoch[1] if turn_epoch else None,
        )

    # A session that holds a worktree runs its work in that worktree and
    # nowhere else. An unusable one (not activated, gone, off its branch) is a
    # refusal, not a fallback to another directory. Outside the broad try below
    # so the refusal reaches the caller.
    workspace = None
    if execution_context.session_id is not None:
        from nexus.database import tenant_session
        from nexus.services.worktree_service import session_workspace

        async with tenant_session(agent.company_id) as worktree_db:
            workspace = await session_workspace(
                worktree_db, agent.company_id, agent.id, execution_context.session_id
            )

    # Check if API key is available. A Connection that supplies its own key
    # satisfies this — the blocker must not fire on the gateway path (WP-22b).
    api_key = config.get("api_key", "")
    if registry_key in ("anthropic", "openai", "azure_openai") and not api_key:
        # No API key configured — create a Secret Proposal for human approval
        try:
            from nexus.database import tenant_session
            from nexus.models.governance import Approval
            async with tenant_session(agent.company_id) as proposal_db:
                env_var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "azure_openai": "AZURE_OPENAI_API_KEY"}.get(registry_key, f"{registry_key.upper()}_API_KEY")
                # Check if a proposal already exists to avoid duplicates
                from sqlalchemy import func
                existing = await proposal_db.execute(
                    select(func.count(Approval.id)).where(
                        Approval.type == "secret_request",
                        Approval.status == "pending",
                    )
                )
                if (existing.scalar() or 0) < 3:
                    approval = Approval(
                        company_id=agent.company_id,
                        type="secret_request",
                        payload={
                            "env_var": env_var,
                            "agent_id": str(agent.id),
                            "agent_name": agent.name,
                            "agent_role": agent.role,
                            "adapter_type": registry_key,
                        },
                    )
                    proposal_db.add(approval)
                    await proposal_db.commit()
        except Exception:
            pass  # Best-effort proposal creation

        return (
            f"[{agent.name}] I'm configured as a {agent.role} but my "
            f"provider API key ({registry_key}) is not set. "
            f"A secret proposal has been created for operator approval.\n\n"
            f"My capabilities: {', '.join(agent.capabilities or ['general'])}.\n"
            f"My objective: {agent.objectives or 'Execute assigned tasks.'}",
            config.get("model", "none"),
            0,
        )

    # Budget reservation. Every LLM dispatch in the app funnels through this
    # function, so guarding here covers the orchestrator, pipelines, triggers and
    # Temporal activities rather than just the chat route. It sits outside the try
    # below on purpose: that block catches Exception broadly and answers in
    # character, which would turn a budget refusal into a friendly message and let
    # the call proceed anyway.
    # A self-metering adapter reserves and settles every streamed round itself;
    # a second hold here would count the same call twice.
    # Self-metering is a capability of the registered adapter type, not of agent config.
    # A registry that cannot be built reserves as usual; the try below reports the failure.
    try:
        adapter_registry = AdapterRegistry()
    except Exception:
        adapter_registry = None
    self_metered = adapter_registry is not None and adapter_registry.is_self_metered(registry_key)

    reservation_id = (
        None
        if self_metered
        else await _reserve_budget(
            agent, system_prompt, user_message, history, config, session_id=session_id
        )
    )
    # Filled in only on a billed call; the finally below releases the hold when
    # it stays zero, so every exit path settles exactly once.
    spend: dict[str, Any] = {"cost_cents": 0, "input": 0, "output": 0, "model": None}

    try:
        if adapter_registry is None:
            adapter_registry = AdapterRegistry()
        adapter = adapter_registry.create_adapter(registry_key)

        # Hermes tool calls use same DB-backed ToolAccess, autonomy, approval,
        # vault-grant, and writer path as every other governed tool. The
        # designated CEO gets none: its authority is only the MCP CEO tools,
        # so free-form <tool_call> text from a CEO turn executes nothing.
        # A task attempt (work_mode set) is offered no tool at all.
        if (
            hasattr(adapter, "register_tool")
            and not agent.is_ceo
            and execution_context.work_mode is None
        ):
            from nexus.database import tenant_session, tenant_session_factory
            from nexus.tools import (
                OBSIDIAN_NOTE_REPLACE_NAME,
                OBSIDIAN_NOTE_REPLACE_SCHEMA,
                ObsidianNoteReplaceTool,
                ToolRegistry,
                build_tool_executor,
                register_obsidian_note_replace,
            )
            from nexus.tools.effects import EffectClass

            tenant_factory = tenant_session_factory(agent.company_id)
            tool_registry = ToolRegistry(tenant_factory)
            definition = register_obsidian_note_replace(tool_registry, agent.company_id)
            await tool_registry.persist_tool(definition)
            tool_id = definition.id

            async def _execute_obsidian(arguments: dict[str, Any]) -> Any:
                call_arguments = dict(arguments)
                # Approval identity comes only from AutonomyGate, never model input.
                call_arguments.pop("approval_id", None)
                async with tenant_session(agent.company_id) as tool_db:
                    executor = build_tool_executor(tool_db, default_autonomy_level=3)
                    tool = ObsidianNoteReplaceTool(
                        tool_db,
                        registry=tool_registry,
                        session_factory=tenant_factory,
                        company_id=agent.company_id,
                        agent_id=agent.id,
                        tool_id=tool_id,
                    )
                    governed = await executor.execute(
                        agent_id=agent.id,
                        tool_id=tool_id,
                        arguments=call_arguments,
                        execute_fn=tool.execute,
                        company_id=agent.company_id,
                        tool_name=OBSIDIAN_NOTE_REPLACE_NAME,
                    )
                    if not governed.success:
                        return governed.output or {
                            "status": "governance_failure",
                            "reason": governed.error,
                        }
                    return governed.output

            adapter.register_tool(
                OBSIDIAN_NOTE_REPLACE_NAME,
                _execute_obsidian,
                {
                    "description": "Replace one existing Markdown note through governed vault write controls.",
                    "parameters": OBSIDIAN_NOTE_REPLACE_SCHEMA["properties"],
                },
                # Replaces a note only if it still has the hash the caller read, so a
                # second run after success conflicts instead of writing again.
                effect=EffectClass.IDEMPOTENT_WRITE,
            )

        # Tool calls act under the server-built context, never under anything
        # in config, which an agent's stored adapter settings can supply.
        session_config = {**config, "system_prompt": system_prompt}
        session = await adapter.create_session(agent.id, session_config)
        session.context = execution_context
        session.worktree_path = str(workspace) if workspace is not None else None

        # Build conversation messages for context
        messages = []
        for msg in history[-10:]:  # Last 10 messages for context window
            messages.append({
                "role": "user" if msg["sender"] == "user" else "assistant",
                "content": msg["text"],
            })

        # Execute the chat task with GenAI tracing and metrics
        # A durable turn fixes its execution ID when it is claimed.
        preset = (execution or {}).get("execution_id")
        task_id = uuid.UUID(preset) if preset else uuid.uuid4()
        payload = {
            "objective": user_message,
            "messages": messages,
            "prompt": user_message,
            "system_prompt": system_prompt,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if turn_id is not None and self_metered:
            payload["turn_id"] = str(turn_id)  # identity for the adapter's budget log

        from nexus.observability.metrics import record_llm_metrics
        from nexus.observability.tracing import record_llm_usage, start_llm_span
        import time

        model_name = config.get("model", "unknown")
        start_t = time.time()

        with start_llm_span(
            model=model_name,
            provider=registry_key,
            company_id=agent.company_id,
            agent_id=agent.id,
            prompt=user_message,
        ) as llm_span:
            result = await adapter.execute_task(session, task_id, payload)
            duration_t = time.time() - start_t

            # Clean up session
            await adapter.terminate(session)

            if execution is not None:
                execution["execution_id"] = str(task_id)
                for artifact in result.artifacts or []:
                    if isinstance(artifact, dict) and artifact.get("type") == "cli_execution":
                        execution["cli"] = artifact

            if result.success and result.output:
                response_text = str(result.output)
                tokens = result.input_tokens + result.output_tokens
                model_used = config.get("model", "unknown")
                # Reconcile against the provider's own token counts rather than the
                # ~4-chars-per-token floor the reservation used.
                from nexus.models_router.pricing import TokenSplit, estimate_cost_usd

                actual_usd = estimate_cost_usd(
                    model_used,
                    TokenSplit(result.input_tokens, result.output_tokens),
                )
                cost_cents = max(1, round(actual_usd * 100)) if tokens else 0
                spend.update(
                    cost_cents=cost_cents,
                    input=result.input_tokens,
                    output=result.output_tokens,
                    model=model_used,
                )

                # Record GenAI span attributes and Prometheus metrics
                record_llm_usage(
                    llm_span,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_cents=cost_cents,
                    finish_reason="stop",
                    model=model_used,
                )
                record_llm_metrics(
                    company_id=agent.company_id,
                    agent_id=agent.id,
                    provider=registry_key,
                    model=model_used,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_cents=cost_cents,
                    duration_seconds=duration_t,
                )
                # Durable memory. Sits here rather than in the route because
                # every LLM dispatch in the app funnels through this function,
                # so the orchestrator, pipelines and triggers remember too.
                await _remember_response(agent, response_text, turn_id=turn_id)
                return response_text, model_used, tokens
            elif result.error:
                record_llm_usage(
                    llm_span,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_cents=0,
                    finish_reason="error",
                    model=model_name,
                )
                # result.error can carry provider-controlled text; neither the reply nor the
                # log repeats it. The provider's doctor/status reports the sanitized cause.
                logger.warning(
                    "LLM call reported an error: code=%s adapter=%s agent=%s",
                    PROVIDER_UNAVAILABLE_CODE, registry_key, agent.id,
                )
                if execution is not None:
                    # The reply below is server text, not the model's: a work attempt must
                    # not submit it as a deliverable (work_service.submit_from_turn).
                    execution["error_code"] = PROVIDER_UNAVAILABLE_CODE
                return (
                    PROVIDER_UNAVAILABLE_MESSAGE,
                    config.get("model", "unknown"),
                    0,
                )
            else:
                return (
                    f"[{agent.name}] No response generated.",
                    config.get("model", "unknown"),
                    0,
                )

    except BudgetInfraUnavailable:
        # R12: a fail-closed budget refusal must not be dressed up as a friendly
        # "can't reach my provider" fallback below — that would let the call be
        # treated as a soft error and retried. Propagate it as a real refusal.
        raise
    except Exception as e:
        # The class only: the message and traceback of a provider or registry failure can
        # carry credentials, URLs or response bodies.
        logger.warning(
            "LLM call failed: code=%s adapter=%s exc_class=%s agent=%s turn=%s execution=%s",
            PROVIDER_UNAVAILABLE_CODE, registry_key, type(e).__name__, agent.id, turn_id,
            (execution or {}).get("execution_id"),
        )
        if execution is not None:
            execution["error_code"] = PROVIDER_UNAVAILABLE_CODE
        # A fixed, server-owned reply: deterministic, no model call, nothing from the failure.
        return PROVIDER_UNAVAILABLE_MESSAGE, "fallback", 0

    finally:
        # Every exit above — success, provider error, in-character fallback,
        # a cancelled request — passes through here, so a hold is never left
        # dangling for its TTL. Shielded: a cancelled scope re-cancels awaits.
        import anyio

        with anyio.CancelScope(shield=True):
            await _settle_budget(
                reservation_id,
                cost_cents=spend["cost_cents"],
                company_id=agent.company_id,
                input_tokens=spend["input"],
                output_tokens=spend["output"],
                model=spend["model"],
            )


# ---------------------------------------------------------------------------
# Turn helpers (shared by the legacy per-agent routes and the session routes)
# ---------------------------------------------------------------------------


async def _load_agent(db: "AsyncSession", agent_id: uuid.UUID, company_id: uuid.UUID) -> Agent:
    """The tenant's agent, or 404."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return agent


async def _build_chat_prompt(db: "AsyncSession", agent: Agent, company_id: uuid.UUID, prompt: str) -> str:
    """System prompt from the agent's soul/persona, memories and live platform data.

    The designated CEO gets the bounded, snapshot-backed executive context
    instead of live platform data: no aggregation and no model call per turn.
    """
    from nexus.services import ceo_service

    agent_memories = await _fetch_agent_memories(db, agent.id, company_id, query=prompt)
    system_prompt = _build_system_prompt(agent, memories=agent_memories)
    executive = await ceo_service.chat_context(db, company_id, agent.id)
    if executive is not None:
        return f"{system_prompt}\n\n{executive}"

    # Inject live platform context (workforce roster, active tasks, goals, live assignment) directly from DB
    live_platform_context = await _fetch_live_platform_context(db, company_id, prompt)
    if live_platform_context:
        system_prompt += (
            f"\n\n--- LIVE PLATFORM WORKFORCE & TASK DATA ---\n"
            f"{live_platform_context}\n"
            f"--- INSTRUCTION: Use this live data for answering and task assignment. "
            f"Always refer to agents by their real names in this roster (e.g. Punni, Navi). ---"
        )
    return system_prompt


async def _record_chat_audit(
    db: "AsyncSession",
    company_id: uuid.UUID,
    agent_id: uuid.UUID,
    prompt: str,
    response_text: str,
    model_used: str,
    tokens_used: int,
    session_id: uuid.UUID,
    execution_id: str | None = None,
    previews: bool = True,
) -> None:
    """Audit both sides of a turn and record its spend on the in-process tracker.

    ``previews=False`` (task-attempt turns) records sizes instead of text: a work
    prompt and its deliverable never reach the audit log.
    """
    from nexus.governance.audit_service import record_audit

    await record_audit(
        company_id, "chat.message_sent",
        actor_type="user", resource_type="agent", resource_id=str(agent_id),
        details={**({"prompt_preview": prompt[:100]} if previews else {"prompt_chars": len(prompt)}),
                 "model": model_used, "tokens": tokens_used, "session_id": str(session_id),
                 "execution_id": execution_id},
        db=db,
    )
    await record_audit(
        company_id, "chat.response_generated",
        actor_type="agent", actor_id=str(agent_id),
        resource_type="chat", resource_id=str(session_id),
        details={"model": model_used, "tokens": tokens_used,
                 **({"response_preview": response_text[:100]} if previews
                    else {"response_chars": len(response_text)}),
                 "session_id": str(session_id),
                 "execution_id": execution_id},
        db=db,
    )

    # Record spend against company budget
    if tokens_used > 0:
        from nexus.api.middleware import _budget_tracker
        # Rough cost estimate: ~$0.003 per 1K input tokens, ~$0.015 per 1K output tokens
        # Simplified: ~1 cent per 500 tokens
        estimated_cost_cents = max(1, tokens_used // 500)
        _budget_tracker.record_spend(company_id, estimated_cost_cents)


async def _stream_llm(
    agent: Agent,
    system_prompt: str,
    prompt: str,
    history: list[dict[str, Any]],
    *,
    session_id: uuid.UUID,
    context: ExecutionContext | None,
    execution: dict[str, Any],
    on_chunk: Any,
    turn_id: uuid.UUID | None = None,
    turn_epoch: tuple[str | None, int] | None = None,
) -> tuple[str, str, int]:
    """One turn's model call, reporting text through ``on_chunk`` as it is generated.

    Token streaming for API adapters that support it; any other adapter goes
    through ``_call_llm`` and its reply arrives whole. The caller (the turn
    worker) stores the result either way.
    """
    from dataclasses import replace

    import anyio

    from nexus.adapters.registry import AdapterRegistry
    from nexus.tools.context import ExecutionContext

    registry_key, config = _resolve_adapter_type(agent, await _resolve_connection(agent))
    adapter = None
    if registry_key in ("anthropic", "openai") and config.get("api_key"):
        adapter = AdapterRegistry().create_adapter(registry_key)
    if adapter is None or not hasattr(adapter, "stream_execute"):
        return await _call_llm(
            agent, system_prompt, prompt, history, session_id=session_id, context=context,
            execution=execution, turn_id=turn_id, turn_epoch=turn_epoch,
        )

    execution.update(adapter=registry_key, backend=config.get("backend"))
    model_used = config.get("model", "unknown")
    # Streaming is metered like any other call: hold before the request, settle or
    # release however the stream ends. Raised outside the try so a refusal reaches the caller.
    reservation_id = await _reserve_budget(
        agent, system_prompt, prompt, history, config, session_id=session_id
    )
    text = ""
    try:
        session = await adapter.create_session(agent.id, {**config, "system_prompt": system_prompt})
        if context is None:
            session.context = ExecutionContext.for_agent(
                agent, source="chat", session_id=session_id, adapter=registry_key, model=model_used
            )
        else:
            session.context = replace(
                context, agent_id=agent.id, session_id=session_id, adapter=registry_key,
                model=model_used,
            )
        preset = execution.get("execution_id")
        task_id = uuid.UUID(preset) if preset else uuid.uuid4()
        execution["execution_id"] = str(task_id)
        try:
            request = {"prompt": prompt, "max_tokens": 4096}
            async for chunk in adapter.stream_execute(session, task_id, request):
                text += chunk
                on_chunk(chunk)
        finally:
            with anyio.CancelScope(shield=True):
                await adapter.terminate(session)
    finally:
        # The stream reports no usage, so settle on a conservative estimate once any
        # text arrived (a cancelled or failed stream is not free); release when none did.
        from nexus.models_router.pricing import TokenSplit, estimate_cost_usd

        in_chars = len(system_prompt) + len(prompt) + sum(
            len(str(msg.get("text", ""))) for msg in history[-10:]
        )
        in_tokens, out_tokens = in_chars // 3 + 1, len(text) // 3 + 1
        cents = max(1, round(estimate_cost_usd(model_used, TokenSplit(in_tokens, out_tokens)) * 100))
        with anyio.CancelScope(shield=True):
            await _settle_budget(
                reservation_id,
                cost_cents=cents if text else 0,
                company_id=agent.company_id,
                input_tokens=in_tokens if text else 0,
                output_tokens=out_tokens if text else 0,
                model=model_used,
            )
    return text, model_used, len(text.split()) * 2  # rough estimate


def _message_out(row: Any) -> dict[str, Any]:
    """A stored chat message in the API's message shape."""
    payload = row.payload or {}
    execution = payload.get("execution") or {}
    return {
        "id": str(row.id),
        "sender": row.sender,
        "text": row.text,
        "timestamp": row.created_at.isoformat() if row.created_at else "",
        "seq": row.seq,
        "session_id": str(row.session_id) if row.session_id else None,
        "model_used": row.model_used,
        "adapter_used": execution.get("adapter"),
        "backend_used": execution.get("backend"),
        "partial": bool(payload.get("partial")),
    }


async def _load_message(company_id: uuid.UUID, message_id: uuid.UUID | None) -> Any:
    from nexus.database import tenant_session
    from nexus.models.chat import ChatMessage as ChatMessageModel

    if message_id is None:
        return None
    async with tenant_session(company_id) as db:
        return (
            await db.execute(
                select(ChatMessageModel).where(
                    ChatMessageModel.id == message_id, ChatMessageModel.company_id == company_id
                )
            )
        ).scalar_one_or_none()


def turn_reply(turn: Any, reply: Any) -> dict[str, Any]:
    """A finished turn as every entry point reports it (POST body, SSE done event)."""
    return {
        "session_id": str(turn.session_id),
        "agent_id": str(turn.agent_id),
        "turn_id": str(turn.id),
        "status": turn.status,
        "message": _message_out(reply) if reply is not None else None,
        "message_id": str(reply.id) if reply is not None else None,
        "seq": reply.seq if reply is not None else None,
        "model_used": turn.model_used,
        "tokens_used": (turn.result or {}).get("tokens_used", 0),
        "adapter_used": turn.adapter_used,
        "backend_used": turn.backend_used,
        "execution_id": turn.execution_id,
    }


def _pending(turn: Any, retry_after: int | None) -> JSONResponse:
    from nexus.runtime import chat_turns

    retry_after = retry_after or 5
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=chat_turns.turn_state(turn, retry_after),
        headers={"Retry-After": str(retry_after)},
    )


async def run_turn(company_id: uuid.UUID, turn: Any) -> dict[str, Any] | JSONResponse:
    """Wait for a queued turn: its reply once it completes, 202 while it is still pending.

    The turn does not depend on this request. If the client goes away, or the
    wait ends first, the turn still runs and is read back later by its ID.
    """
    from nexus.config import settings
    from nexus.models.chat_turn import TERMINAL_STATUSES
    from nexus.runtime import chat_turns

    chat_turns.get_worker().wake(company_id)
    turn, retry_after = await chat_turns.wait_for_turn(
        company_id, turn.id, settings.chat_turn_wait_seconds
    )
    if turn.status not in TERMINAL_STATUSES:
        return _pending(turn, retry_after)
    chat_turns.raise_for_outcome(turn)
    return turn_reply(turn, await _load_message(company_id, turn.response_message_id))


def _sse(data: Any, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}data: {json.dumps(data, default=str)}\n\n"


def _words(text: str) -> list[str]:
    return [w if i == 0 else " " + w for i, w in enumerate(text.split(" "))] if text else []


def resume_offset(last_event_id: str | None) -> int:
    """Characters of the reply a reconnecting client already has (its Last-Event-ID)."""
    try:
        return max(0, int(last_event_id or 0))
    except ValueError:
        return 0


async def turn_events(turn_id: uuid.UUID, company_id: uuid.UUID, offset: int = 0):
    """SSE for one turn. Attaches to the turn and never executes it.

    The frontend expects Server-Sent Events with JSON payloads:
      data: {"type": "turn", "turn_id": ..., "status": "queued" | "running" | ...}
      data: {"type": "chunk", "text": "partial..."}      (id: characters so far)
      data: {"type": "done", "message": {...}, "turn_id": ..., "execution_id": ...}
      data: [DONE]

    A client that disconnects loses nothing: the turn keeps running and stores
    its reply. Reconnecting (``GET .../turns/{id}/events``, or retrying the
    POST with the same idempotency key) with ``Last-Event-ID`` resumes after
    the text the client already has; the done event always carries the whole
    stored reply. Chunks are live only while the turn runs in this process;
    otherwise the reply is sent once the turn finishes.
    """
    from nexus.config import settings
    from nexus.models.chat_turn import TERMINAL_STATUSES
    from nexus.runtime import chat_turns

    worker = chat_turns.get_worker()
    queue, buffered = worker.subscribe(turn_id)
    sent = offset
    try:
        turn = await chat_turns.get_turn(company_id, turn_id)
        if turn is None:
            yield _sse({"type": "error", "status": 404, "text": f"Turn {turn_id} not found"})
            yield "data: [DONE]\n\n"
            return
        shown = turn.status
        yield _sse({"type": "turn", **chat_turns.turn_state(turn, worker.saturated.get(turn_id))})
        if len(buffered) > sent:
            yield _sse({"type": "chunk", "text": buffered[sent:]}, len(buffered))
            sent = len(buffered)
        quiet = 0
        while turn.status not in TERMINAL_STATUSES:
            try:
                item = await asyncio.wait_for(queue.get(), settings.chat_turn_poll_seconds)
            except TimeoutError:
                item = None
                quiet += 1
                if quiet % 15 == 0:
                    yield ": keepalive\n\n"
            if item is not None:
                quiet = 0
                sent += len(item)
                yield _sse({"type": "chunk", "text": item}, sent)
                continue
            turn = await chat_turns.get_turn(company_id, turn_id)
            if turn.status != shown and turn.status not in TERMINAL_STATUSES:
                shown = turn.status
                yield _sse({"type": "turn", **chat_turns.turn_state(turn)})

        reply = await _load_message(company_id, turn.response_message_id)
        if turn.status == "completed" and reply is not None:
            for chunk in _words(reply.text[sent:]):
                sent += len(chunk)
                yield _sse({"type": "chunk", "text": chunk}, sent)
            yield _sse({"type": "done", **turn_reply(turn, reply)}, sent)
        else:
            result = turn.result or {}
            detail = result.get("detail")
            if not isinstance(detail, dict):
                detail = {"message": detail or turn.error_message}
            code = {"cancelled": "TURN_CANCELLED", "expired": "TURN_EXPIRED"}.get(turn.status)
            yield _sse({
                **detail,
                **({"code": code} if code else {}),
                "text": detail.get("message") or f"The turn was {turn.status}",
                **turn_reply(turn, reply),
                "type": "error",
                "status": result.get("http_status", 409),
                "turn_status": turn.status,
            })
        yield "data: [DONE]\n\n"
    finally:
        worker.unsubscribe(turn_id, queue)


def _sse_response(events) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/v1/agents/{agent_id}/chat")
async def get_chat_history(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> list[dict[str, Any]]:
    """Get conversation history for an agent."""
    await _load_agent(db, agent_id, company_id)
    # Always load from DB (authoritative source for multi-worker consistency)
    history = await _load_history_from_db(db, agent_id, company_id)
    # Update in-memory cache for fast access during streaming
    if history:
        _conversations[str(agent_id)] = history
    return history


@router.get("/api/v1/agents/{agent_id}/chat/turns")
async def list_agent_chat_turns(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    pending: bool = Query(default=False, description="Only turns that are not finished"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """The agent's latest chat turns, oldest first.

    A refreshed page calls this with ``pending=true`` to show which prompts
    are still queued or running and to re-attach to them
    (``GET /api/v1/agent-sessions/{session_id}/turns/{turn_id}/events``).
    """
    from nexus.models.chat_turn import TERMINAL_STATUSES, ChatTurn
    from nexus.runtime import chat_turns

    await _load_agent(db, agent_id, company_id)
    stmt = select(ChatTurn).where(ChatTurn.company_id == company_id, ChatTurn.agent_id == agent_id)
    if pending:
        stmt = stmt.where(ChatTurn.status.not_in(TERMINAL_STATUSES))
    rows = (await db.execute(stmt.order_by(ChatTurn.queued_at.desc()).limit(limit))).scalars()
    return [chat_turns.turn_state(t) for t in reversed(list(rows))]


@router.post("/api/v1/agents/{agent_id}/chat", response_model=ChatResponse)
async def chat_with_agent(
    agent_id: uuid.UUID,
    body: ChatRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)] = None,
) -> Any:
    """Send a message to an agent and get a real LLM-powered response.

    The prompt and a queued turn are stored in the agent's default session in
    one transaction, and the turn worker runs it on the session's pinned
    adapter/model (see ``nexus.runtime.chat_turns``). The request waits for
    the reply up to ``chat_turn_wait_seconds``. If the turn is still queued or
    running then, or the tenant is at its concurrency limit, the answer is 202
    with the ``turn_id``, and the turn completes on its own.

    An unusable pin, an agent that needs configuration or an unresolvable
    adapter fails with 409/422 before anything is stored.
    """
    from nexus.runtime import chat_turns
    from nexus.services.session_service import get_or_create_default_session

    agent = await _load_agent(db, agent_id, company_id)
    # The legacy per-agent conversation lives in the agent's default session.
    session = await get_or_create_default_session(db, agent)
    queued = await chat_turns.create_turn(
        db, session, agent, body.prompt, principal=principal,
        idempotency_key=idempotency_key or body.request_id,
        require_manager_tools=body.require_manager_tools,
        record_directive=body.record_directive,
    )
    result = await run_turn(company_id, queued.turn)
    if isinstance(result, JSONResponse):
        return result

    history = await _load_history_from_db(db, agent_id, company_id)
    _conversations[str(agent_id)] = history
    return ChatResponse(
        message=ChatMessage(**result["message"]),
        history=[ChatMessage(**m) for m in history],
        model_used=result["model_used"],
        tokens_used=result["tokens_used"],
        adapter_used=result["adapter_used"],
        backend_used=result["backend_used"],
        execution_id=result["execution_id"],
    )


@router.delete("/api/v1/agents/{agent_id}/chat", status_code=status.HTTP_204_NO_CONTENT)
async def clear_chat_history(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> None:
    """Clear all conversation history for an agent."""
    await _load_agent(db, agent_id, company_id)
    _conversations.pop(str(agent_id), None)


@router.post("/api/v1/agents/{agent_id}/chat/stream")
async def chat_with_agent_stream(
    agent_id: uuid.UUID,
    body: ChatRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Send a message to an agent and stream the turn via SSE (see ``turn_events``).

    Stores the turn exactly like ``chat_with_agent``. The stream only attaches
    to it, so a dropped connection neither stops nor repeats the turn.
    """
    from nexus.runtime import chat_turns
    from nexus.services.session_service import get_or_create_default_session

    agent = await _load_agent(db, agent_id, company_id)
    session = await get_or_create_default_session(db, agent)
    queued = await chat_turns.create_turn(
        db, session, agent, body.prompt, principal=principal,
        idempotency_key=idempotency_key or body.request_id, stream=True,
        require_manager_tools=body.require_manager_tools,
        record_directive=body.record_directive,
    )
    chat_turns.get_worker().wake(company_id)
    return _sse_response(turn_events(queued.turn.id, company_id, resume_offset(last_event_id)))
