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


def _get_history(agent_id: str) -> list[dict[str, Any]]:
    """Get conversation history for an agent (in-memory cache)."""
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


async def _fetch_agent_memories(
    db: "AsyncSession", agent_id: uuid.UUID, company_id: uuid.UUID, limit: int = 10
) -> list[dict[str, Any]]:
    """Fetch the most relevant memories for an agent from the database.

    Retrieves memories ordered by importance (descending), limited to the top N.
    Returns them as dicts compatible with Persona.build_working_context().
    """
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F811

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

    if working_ctx.recent_memories:
        mem_lines = [
            f"- {m.get('content', str(m))}" for m in working_ctx.recent_memories
        ]
        prompt += f"\n\n--- Relevant Agent Memories ---\n" + "\n".join(mem_lines)

    return prompt


def _resolve_adapter_type(agent: Agent) -> tuple[str, dict[str, Any]]:
    """Resolve the adapter type and config from agent settings.

    Maps agent.adapter_type to the AdapterRegistry key and builds
    the appropriate config dict.
    """
    adapter_type = agent.adapter_type or "anthropic"
    config: dict[str, Any] = {}

    # Map common adapter_type values to registry keys
    adapter_map = {
        "anthropic": "anthropic",
        "openai": "openai",
        "claude": "anthropic",
        "claude_code": "claude_code",
        "cli": "cli",
        "ollama": "ollama",
        "azure": "azure_openai",
        "bedrock": "bedrock",
        "google": "google_gemini",
        "langchain": "anthropic",  # Default fallback
    }

    registry_key = adapter_map.get(adapter_type, "anthropic")

    # Build config based on adapter type
    if registry_key == "anthropic":
        import os

        config = {
            "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "model": agent.model or "claude-sonnet-4-20250514",
        }
    elif registry_key == "openai":
        import os

        config = {
            "api_key": os.environ.get("OPENAI_API_KEY", ""),
            "model": agent.model or "gpt-4o",
        }
    elif registry_key == "ollama":
        config = {
            "model": agent.model or "llama3.1",
            "host": "http://localhost:11434",
        }
    elif registry_key == "cli":
        config = {
            "backend": adapter_type if adapter_type in (
                "claude", "codex", "aider", "kiro-cli", "agy", "opencode"
            ) else "claude",
            "model": agent.model or "",
        }
    else:
        import os

        config = {
            "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "model": agent.model or "claude-sonnet-4-20250514",
        }

    return registry_key, config


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
                        Approval.approval_type == "secret_request",
                        Approval.status == "pending",
                    )
                )
                if (existing.scalar() or 0) < 3:
                    approval = Approval(
                        company_id=agent.company_id if hasattr(agent, 'company_id') else None,
                        approval_type="secret_request",
                        title=f"API Key Required: {env_var}",
                        description=f"Agent {agent.name} ({agent.role}) needs {env_var} to function. Configure this environment variable to enable LLM responses.",
                        requested_by=str(agent.id),
                        status="pending",
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
    agent_memories = await _fetch_agent_memories(db, agent_id, company_id)
    system_prompt = _build_system_prompt(agent, memories=agent_memories)

    # Get history for context
    history = _get_history(str(agent_id))

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
    agent_memories = await _fetch_agent_memories(db, agent_id, company_id)
    system_prompt = _build_system_prompt(agent, memories=agent_memories)

    # Get history for context
    history = _get_history(str(agent_id))

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
