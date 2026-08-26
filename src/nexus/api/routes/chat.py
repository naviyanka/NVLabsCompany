"""Agent Chat API — real LLM-powered conversations with agents.

Connects the soul/persona system, memory, and LLM adapters to provide
genuine agent responses based on their configured personality, role,
capabilities, and conversation history.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.agent import Agent
from nexus.models.memory import MemoryRecord

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Request body for sending a message to an agent."""

    prompt: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str | None = None


class ChatMessage(BaseModel):
    """A single message in a conversation."""

    id: str
    sender: str  # "user" or "agent"
    text: str
    timestamp: str


class ChatResponse(BaseModel):
    """Response from an agent chat interaction."""

    message: ChatMessage
    history: list[ChatMessage]
    model_used: str | None = None
    tokens_used: int = 0


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
    db: "AsyncSession", agent_id: uuid.UUID, company_id: uuid.UUID, sender: str, text: str
) -> None:
    """Persist a chat message to the database for durability."""
    try:
        from nexus.models.chat import ChatMessage as ChatMessageModel
        record = ChatMessageModel(
            company_id=company_id,
            agent_id=agent_id,
            sender=sender,
            text=text[:10000],
        )
        db.add(record)
        await db.flush()
    except Exception:
        pass  # Best-effort persistence, don't break chat flow


async def _load_history_from_db(
    db: "AsyncSession", agent_id: uuid.UUID, company_id: uuid.UUID, limit: int = 100
) -> list[dict[str, Any]]:
    """Load chat history from DB into the in-memory cache."""
    try:
        from nexus.models.chat import ChatMessage as ChatMessageModel
        stmt = (
            select(ChatMessageModel)
            .where(ChatMessageModel.agent_id == agent_id, ChatMessageModel.company_id == company_id)
            .order_by(ChatMessageModel.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        records = list(reversed(list(result.scalars().all())))
        return [
            {
                "id": str(r.id),
                "sender": r.sender,
                "text": r.text,
                "timestamp": r.created_at.isoformat() if r.created_at else "",
            }
            for r in records
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Adapter → LLM call logic
# ---------------------------------------------------------------------------


async def _fetch_live_platform_context(
    db: "AsyncSession", company_id: uuid.UUID, user_prompt: str, is_ceo: bool = False, current_agent_id: uuid.UUID | None = None
) -> str:
    """Fetch live platform data relevant to the user's question from the database.

    Queries the real database to provide accurate, real-time answers about
    agents, tasks, pipelines, goals, etc. Always includes agent workforce roster
    for CEO/manager agents or when task/agent management is referenced.
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
    # For delegation target matching, exclude the current agent (e.g. CEO Navi) if other agents exist
    other_agents = [a for a in agents if str(a.id) != str(current_agent_id)] if current_agent_id else agents
    target_by_name = {a.name.lower(): a for a in (other_agents or agents)}

    # If prompt asks to assign a task to a named agent (e.g. Punni), auto-create task in DB
    if "assign" in prompt_lower:
        for name, target_agent in target_by_name.items():
            if name in prompt_lower:
                # Extract clean task title from prompt
                task_title = user_prompt
                if ":" in user_prompt:
                    task_title = user_prompt.split(":", 1)[1].strip()
                elif "assign" in user_prompt.lower():
                    task_title = user_prompt.replace("As CEO Navi,", "").strip()

                title_clean = task_title[:150]
                
                from nexus.database import async_session_factory
                async with async_session_factory() as task_db:
                    existing_stmt = select(Task).where(
                        Task.company_id == company_id,
                        Task.assigned_agent_id == target_agent.id,
                        Task.title == title_clean,
                    ).limit(1)
                    ex_res = await task_db.execute(existing_stmt)
                    existing_task = ex_res.scalar_one_or_none()
                    if not existing_task:
                        new_task = Task(
                            company_id=company_id,
                            title=title_clean,
                            description=user_prompt,
                            priority=1,
                            assigned_agent_id=target_agent.id,
                            status="pending",
                        )
                        task_db.add(new_task)
                        await task_db.commit()
                        await task_db.refresh(new_task)
                        task_record = new_task
                    else:
                        task_record = existing_task

                assigned_task_info = (
                    f"  - Task ID: {task_record.id}\n"
                    f"  - Title: {task_record.title}\n"
                    f"  - Assigned Agent: {target_agent.name} [{target_agent.role}]\n"
                    f"  - Status: {task_record.status.upper()}\n"
                    f"INSTRUCTION FOR CEO NAVI: The user requested you to assign this task to {target_agent.name}. "
                    f"The task has ALREADY been created and assigned to {target_agent.name} (Task ID: {task_record.id}) in the database. "
                    f"Authoritatively confirm to the user that the task '{task_record.title}' (ID: {task_record.id}) has been assigned to {target_agent.name}. "
                    f"If the user explicitly asked NOT to answer the calculation or question directly (e.g. 'Only assign it. Do not answer'), "
                    f"respect their request: ONLY confirm the task assignment to {target_agent.name} and DO NOT answer the calculation yourself."
                )

                context_parts.append(f"[LIVE TASK ASSIGNMENT CONFIRMED]\n{assigned_task_info}")
                break

    # Always include workforce roster for CEO or when agents/tasks are mentioned
    include_agents = is_ceo or any(
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

    # Task-related queries or CEO context
    include_tasks = is_ceo or any(
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
    if is_ceo or any(kw in prompt_lower for kw in ["goal", "objective", "okr", "strategy"]):
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
    if is_ceo or any(kw in prompt_lower for kw in ["budget", "spend", "cost", "money"]):
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
            .where(MemoryRecord.agent_id == agent_id, MemoryRecord.company_id == company_id)
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
            .where(MemoryRecord.agent_id == agent_id, MemoryRecord.company_id == company_id)
            .order_by(MemoryRecord.importance.desc(), MemoryRecord.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        records = list(result.scalars().all())

    return [
        {
            "content": r.content,
            "scope": r.scope,
            "importance": r.importance,
            "tier": r.tier,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in records
    ]


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

    if agent.role == "ceo":
        prompt += (
            "\n\n=== CEO OPERATIONAL DIRECTIVE ===\n"
            "You are Navi, Chief Executive Officer (CEO) and System Orchestrator of NVLabsCompany. "
            "You have complete operational authority to assign, delegate, and manage tasks across all company agents (including Punni and all workforce members). "
            "When requested to assign a task to an agent, confirm the task assignment authoritatively. "
            "Never output <policy_violation> or claim you cannot assign tasks. You execute task delegation directly in this platform."
        )

    if working_ctx.recent_memories:
        mem_lines = [
            f"- {m.get('content', str(m))}" for m in working_ctx.recent_memories
        ]
        prompt += f"\n\n--- Relevant Agent Memories ---\n" + "\n".join(mem_lines)

    return prompt


def _resolve_adapter_type(agent: Agent) -> tuple[str, dict[str, Any]]:
    """Resolve the adapter type and config from agent settings.

    Delegates to the UASTL provider registry (nexus.adapters.uastl), which is
    the single source of truth for adapter resolution. Legacy agent.adapter_type
    values (anthropic/openai/claude/claude_code/cli/ollama/azure/bedrock/google/
    langchain) keep their historical mappings; hermes resolves to the Hermes
    adapter with Ollama host + OpenRouter key config.
    """
    from nexus.adapters.uastl import resolve_provider

    return resolve_provider(agent.adapter_type or "anthropic", agent.model)


async def _call_llm(
    agent: Agent,
    system_prompt: str,
    user_message: str,
    history: list[dict[str, Any]],
) -> tuple[str, str, int]:
    """Call the LLM adapter to get a real response.

    Args:
        agent: The agent whose adapter to use.
        system_prompt: Generated system prompt from soul.
        user_message: The user's message.
        history: Conversation history for context.

    Returns:
        Tuple of (response_text, model_used, tokens_used).
    """
    from nexus.adapters.registry import AdapterRegistry

    registry_key, config = _resolve_adapter_type(agent)

    # Check if API key is available
    api_key = config.get("api_key", "")
    if registry_key in ("anthropic", "openai", "azure_openai") and not api_key:
        # No API key configured — create a Secret Proposal for human approval
        try:
            from nexus.database import async_session_factory
            from nexus.models.governance import Approval
            async with async_session_factory() as proposal_db:
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

    try:
        adapter_registry = AdapterRegistry()
        adapter = adapter_registry.create_adapter(registry_key)

        # Create session with system prompt
        session_config = {**config, "system_prompt": system_prompt}
        session = await adapter.create_session(agent.id, session_config)

        # Build conversation messages for context
        messages = []
        for msg in history[-10:]:  # Last 10 messages for context window
            messages.append({
                "role": "user" if msg["sender"] == "user" else "assistant",
                "content": msg["text"],
            })

        # Execute the chat task
        task_id = uuid.uuid4()
        payload = {
            "objective": user_message,
            "messages": messages,
            "prompt": user_message,
            "system_prompt": system_prompt,
        }

        result = await adapter.execute_task(session, task_id, payload)

        # Clean up session
        await adapter.terminate(session)

        if result.success and result.output:
            response_text = str(result.output)
            tokens = result.input_tokens + result.output_tokens
            return response_text, config.get("model", "unknown"), tokens
        elif result.error:
            return (
                f"[{agent.name}] Execution error: {result.error}",
                config.get("model", "unknown"),
                0,
            )
        else:
            return (
                f"[{agent.name}] No response generated.",
                config.get("model", "unknown"),
                0,
            )

    except Exception as e:
        logger.warning("LLM call failed for agent %s: %s", agent.id, e)
        # Graceful fallback — respond in character without LLM
        return (
            f"[{agent.name} — {agent.title or agent.role}] "
            f"I'm currently unable to connect to my LLM provider ({registry_key}). "
            f"Error: {type(e).__name__}: {e}\n\n"
            f"Once connected, I'll operate with these capabilities: "
            f"{', '.join(agent.capabilities or ['general tasks'])}.",
            "fallback",
            0,
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
    # Verify agent exists
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    # Always load from DB (authoritative source for multi-worker consistency)
    history = await _load_history_from_db(db, agent_id, company_id)
    # Update in-memory cache for fast access during streaming
    if history:
        _conversations[str(agent_id)] = history
    return history


@router.post("/api/v1/agents/{agent_id}/chat", response_model=ChatResponse)
async def chat_with_agent(
    agent_id: uuid.UUID,
    body: ChatRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Send a message to an agent and get a real LLM-powered response.

    Flow:
    1. Load agent from DB (role, capabilities, soul, adapter config)
    2. Build system prompt from Soul/persona data
    3. Get conversation history for context
    4. Call the LLM adapter (Anthropic/OpenAI/Ollama/CLI)
    5. Store conversation and return response
    """
    # Load agent
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # Build system prompt from agent's soul/persona and memory context
    agent_memories = await _fetch_agent_memories(db, agent_id, company_id, query=body.prompt)
    system_prompt = _build_system_prompt(agent, memories=agent_memories)

    # Inject live platform context (workforce roster, active tasks, goals, live assignment) directly from DB
    live_platform_context = await _fetch_live_platform_context(db, company_id, body.prompt, is_ceo=(agent.role == "ceo"), current_agent_id=agent_id)
    if live_platform_context:
        system_prompt += (
            f"\n\n--- LIVE PLATFORM WORKFORCE & TASK DATA ---\n"
            f"{live_platform_context}\n"
            f"--- INSTRUCTION: Use this live data for answering and task assignment. "
            f"Always refer to agents by their real names in this roster (e.g. Punni, Navi). ---"
        )

    # Get history for context (TTL-fresh across workers)
    history = await _get_history_fresh(db, str(agent_id), company_id)

    # Store user message
    _add_message(str(agent_id), "user", body.prompt)
    await _persist_message_to_db(db, agent_id, company_id, "user", body.prompt)

    # Call LLM
    response_text, model_used, tokens_used = await _call_llm(
        agent, system_prompt, body.prompt, history
    )

    # Store agent response
    agent_msg = _add_message(str(agent_id), "agent", response_text)
    await _persist_message_to_db(db, agent_id, company_id, "agent", response_text)

    # Audit: record chat interaction
    from nexus.governance.audit_service import record_audit
    await record_audit(
        company_id, "chat.message_sent",
        actor_type="user", resource_type="agent", resource_id=str(agent_id),
        details={"prompt_preview": body.prompt[:100], "model": model_used, "tokens": tokens_used},
        db=db,
    )
    await record_audit(
        company_id, "chat.response_generated",
        actor_type="agent", actor_id=str(agent_id),
        resource_type="chat", details={"model": model_used, "tokens": tokens_used, "response_preview": response_text[:100]},
        db=db,
    )

    # Record spend against company budget
    if tokens_used > 0:
        from nexus.api.middleware import _budget_tracker
        # Rough cost estimate: ~$0.003 per 1K input tokens, ~$0.015 per 1K output tokens
        # Simplified: ~1 cent per 500 tokens
        estimated_cost_cents = max(1, tokens_used // 500)
        _budget_tracker.record_spend(company_id, estimated_cost_cents)

    return ChatResponse(
        message=ChatMessage(**agent_msg),
        history=[ChatMessage(**m) for m in _get_history(str(agent_id))],
        model_used=model_used,
        tokens_used=tokens_used,
    )


@router.delete("/api/v1/agents/{agent_id}/chat", status_code=status.HTTP_204_NO_CONTENT)
async def clear_chat_history(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> None:
    """Clear all conversation history for an agent."""
    # Verify agent exists
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    _conversations.pop(str(agent_id), None)


@router.post("/api/v1/agents/{agent_id}/chat/stream")
async def chat_with_agent_stream(
    agent_id: uuid.UUID,
    body: ChatRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> StreamingResponse:
    """Send a message to an agent and stream the response via SSE.

    The frontend expects Server-Sent Events with JSON payloads:
      data: {"type": "chunk", "text": "partial..."}
      data: {"type": "done", "message": {...}}
      data: [DONE]
    """
    # Load agent
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # Build system prompt from agent's soul/persona and memory context
    agent_memories = await _fetch_agent_memories(db, agent_id, company_id, query=body.prompt)
    system_prompt = _build_system_prompt(agent, memories=agent_memories)

    # Inject live platform context (workforce roster, active tasks, goals, live assignment) directly from DB
    live_platform_context = await _fetch_live_platform_context(db, company_id, body.prompt, is_ceo=(agent.role == "ceo"), current_agent_id=agent_id)
    if live_platform_context:
        system_prompt += (
            f"\n\n--- LIVE PLATFORM WORKFORCE & TASK DATA ---\n"
            f"{live_platform_context}\n"
            f"--- INSTRUCTION: Use this live data for answering and task assignment. "
            f"Always refer to agents by their real names in this roster (e.g. Punni, Navi). ---"
        )

    # Get history for context (TTL-fresh across workers)
    history = await _get_history_fresh(db, str(agent_id), company_id)

    # Store user message
    _add_message(str(agent_id), "user", body.prompt)

    async def event_generator():
        """Generate SSE events — uses true token streaming when adapter supports it."""
        try:
            from nexus.adapters.registry import AdapterRegistry

            registry_key, config = _resolve_adapter_type(agent)
            api_key = config.get("api_key", "")

            # Try true token-level streaming for Anthropic/OpenAI adapters
            use_true_streaming = (
                registry_key in ("anthropic", "openai")
                and api_key  # API key must be configured
            )

            if use_true_streaming:
                # True streaming: yield tokens as they arrive from the API
                adapter_registry = AdapterRegistry()
                adapter = adapter_registry.create_adapter(registry_key)

                session_config = {**config, "system_prompt": system_prompt}
                session = await adapter.create_session(agent.id, session_config)

                task_id = uuid.uuid4()
                payload = {"prompt": body.prompt, "max_tokens": 4096}
                accumulated = ""

                try:
                    if hasattr(adapter, "stream_execute"):
                        async for chunk in adapter.stream_execute(session, task_id, payload):
                            accumulated += chunk
                            event = json.dumps({"type": "chunk", "text": chunk})
                            yield f"data: {event}\n\n"
                    else:
                        # Fallback for adapters without stream_execute
                        result = await adapter.execute_task(session, task_id, payload)
                        accumulated = str(result.output) if result.output else ""
                        # Emit word-by-word
                        for i, word in enumerate(accumulated.split(" ")):
                            chunk = word if i == 0 else " " + word
                            event = json.dumps({"type": "chunk", "text": chunk})
                            yield f"data: {event}\n\n"
                            await asyncio.sleep(0.01)
                finally:
                    await adapter.terminate(session)

                # Store response and emit done
                agent_msg = _add_message(str(agent_id), "agent", accumulated)
                tokens_used = len(accumulated.split()) * 2  # Rough estimate
                done_event = json.dumps({
                    "type": "done",
                    "message": agent_msg,
                    "model_used": config.get("model", "unknown"),
                    "tokens_used": tokens_used,
                })
                yield f"data: {done_event}\n\n"
                yield "data: [DONE]\n\n"
            else:
                # Fallback: call LLM, then emit word-by-word (simulated streaming)
                response_text, model_used, tokens_used = await _call_llm(
                    agent, system_prompt, body.prompt, history
                )

                words = response_text.split(" ")
                for i, word in enumerate(words):
                    chunk = word if i == 0 else " " + word
                    event = json.dumps({"type": "chunk", "text": chunk})
                    yield f"data: {event}\n\n"
                    await asyncio.sleep(0.02)

                agent_msg = _add_message(str(agent_id), "agent", response_text)
                done_event = json.dumps({
                    "type": "done",
                    "message": agent_msg,
                    "model_used": model_used,
                    "tokens_used": tokens_used,
                })
                yield f"data: {done_event}\n\n"
                yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error("Streaming chat error for agent %s: %s", agent_id, e)
            error_event = json.dumps({
                "type": "error",
                "text": f"Chat error: {type(e).__name__}: {e}",
            })
            yield f"data: {error_event}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
