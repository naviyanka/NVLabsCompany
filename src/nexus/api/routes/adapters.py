"""Adapter management API endpoints.

Provides endpoints for managing adapter types, agent execution sessions,
and session lifecycle operations (pause, resume, terminate).
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(tags=["adapters"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class AdapterTypeResponse(BaseModel):
    """Response model for an adapter type listing."""

    adapter_type: str
    description: str = ""


class AdapterCapabilitiesResponse(BaseModel):
    """Response model for adapter capabilities."""

    adapter_type: str
    capabilities: list[str]


class ExecuteTaskRequest(BaseModel):
    """Request body for executing a task via an agent's adapter."""

    objective: str
    payload: dict[str, Any] | None = None
    estimated_cost_cents: int = 0
    timeout_seconds: int = 300


class TaskResultResponse(BaseModel):
    """Response model for a task execution result."""

    task_id: str
    agent_id: str
    status: str
    output: str | None = None
    cost_cents: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class SessionResponse(BaseModel):
    """Response model for an agent session."""

    session_id: str
    agent_id: str
    status: str
    created_at: str
    last_activity_at: str | None = None


class SessionActionResponse(BaseModel):
    """Response model for session lifecycle actions."""

    session_id: str
    agent_id: str
    action: str
    status: str
    timestamp: str


# ---------------------------------------------------------------------------
# In-memory state for demo purposes
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}
_task_results: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/adapters",
    response_model=list[AdapterTypeResponse],
)
async def list_adapters() -> list[dict[str, Any]]:
    """List all available adapter types.

    Returns registered adapter types from the AdapterRegistry that can
    be used for agent execution.
    """
    from nexus.adapters.registry import AdapterRegistry

    registry = AdapterRegistry(auto_register=True)

    # Descriptions for registered adapter types
    descriptions: dict[str, str] = {
        "openai": "OpenAI chat completions (GPT-4o, o1, o3)",
        "anthropic": "Anthropic Claude models",
        "ollama": "Local Ollama models",
        "claude_code": "Claude Code CLI as subprocess",
        "http": "Generic HTTP agent endpoints",
        "mcp": "MCP server-based execution",
    }

    adapter_types = []
    for adapter_type in registry.get_adapter_types():
        adapter_types.append({
            "adapter_type": adapter_type,
            "description": descriptions.get(adapter_type, ""),
        })
    return adapter_types


@router.get(
    "/api/v1/adapters/{adapter_type}/capabilities",
    response_model=AdapterCapabilitiesResponse,
)
async def get_adapter_capabilities(adapter_type: str) -> dict[str, Any]:
    """Get capabilities for a specific adapter type.

    Queries the AdapterRegistry for the actual capabilities advertised
    by the adapter implementation.

    Args:
        adapter_type: The adapter type to query capabilities for.

    Returns:
        The adapter type and its list of capabilities.

    Raises:
        HTTPException: If the adapter type is unknown.
    """
    from nexus.adapters.registry import AdapterRegistry

    registry = AdapterRegistry(auto_register=True)

    if not registry.is_registered(adapter_type):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown adapter type: '{adapter_type}'. "
            f"Available: {registry.get_adapter_types()}",
        )

    capabilities = registry.get_capabilities(adapter_type)
    return {
        "adapter_type": adapter_type,
        "capabilities": capabilities,
    }


@router.post(
    "/api/v1/agents/{agent_id}/execute",
    response_model=TaskResultResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_task(agent_id: uuid.UUID, body: ExecuteTaskRequest) -> dict[str, Any]:
    """Execute a task via an agent's configured adapter.

    Submits a task for execution through the agent's assigned adapter.
    Returns immediately with a task reference for tracking.

    Args:
        agent_id: The agent to execute the task.
        body: Task execution parameters.

    Returns:
        A TaskResultResponse with the initial execution state.
    """
    now = datetime.now(timezone.utc)
    task_id = str(uuid.uuid4())

    # Create a task execution record
    result = {
        "task_id": task_id,
        "agent_id": str(agent_id),
        "status": "accepted",
        "output": None,
        "cost_cents": 0,
        "started_at": now.isoformat(),
        "completed_at": None,
        "error": None,
    }
    _task_results[task_id] = result

    # Create or reuse a session for this agent
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "session_id": session_id,
        "agent_id": str(agent_id),
        "status": "active",
        "created_at": now.isoformat(),
        "last_activity_at": now.isoformat(),
        "task_id": task_id,
    }

    return result


@router.get(
    "/api/v1/agents/{agent_id}/sessions",
    response_model=list[SessionResponse],
)
async def list_agent_sessions(agent_id: uuid.UUID) -> list[dict[str, Any]]:
    """List all sessions for a specific agent.

    Args:
        agent_id: The agent whose sessions to list.

    Returns:
        List of session records for this agent.
    """
    agent_id_str = str(agent_id)
    agent_sessions = [
        {
            "session_id": s["session_id"],
            "agent_id": s["agent_id"],
            "status": s["status"],
            "created_at": s["created_at"],
            "last_activity_at": s.get("last_activity_at"),
        }
        for s in _sessions.values()
        if s["agent_id"] == agent_id_str
    ]
    return agent_sessions


@router.post(
    "/api/v1/agents/{agent_id}/sessions/{session_id}/pause",
    response_model=SessionActionResponse,
)
async def pause_session(agent_id: uuid.UUID, session_id: uuid.UUID) -> dict[str, Any]:
    """Pause an active agent session.

    Args:
        agent_id: The agent that owns the session.
        session_id: The session to pause.

    Returns:
        Confirmation of the pause action.

    Raises:
        HTTPException: If the session is not found or not active.
    """
    session_id_str = str(session_id)
    session = _sessions.get(session_id_str)

    if session is None or session["agent_id"] != str(agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found for agent {agent_id}",
        )

    if session["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session cannot be paused from status '{session['status']}'",
        )

    now = datetime.now(timezone.utc)
    session["status"] = "paused"
    session["last_activity_at"] = now.isoformat()

    return {
        "session_id": session_id_str,
        "agent_id": str(agent_id),
        "action": "pause",
        "status": "paused",
        "timestamp": now.isoformat(),
    }


@router.post(
    "/api/v1/agents/{agent_id}/sessions/{session_id}/resume",
    response_model=SessionActionResponse,
)
async def resume_session(agent_id: uuid.UUID, session_id: uuid.UUID) -> dict[str, Any]:
    """Resume a paused agent session.

    Args:
        agent_id: The agent that owns the session.
        session_id: The session to resume.

    Returns:
        Confirmation of the resume action.

    Raises:
        HTTPException: If the session is not found or not paused.
    """
    session_id_str = str(session_id)
    session = _sessions.get(session_id_str)

    if session is None or session["agent_id"] != str(agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found for agent {agent_id}",
        )

    if session["status"] != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session cannot be resumed from status '{session['status']}'",
        )

    now = datetime.now(timezone.utc)
    session["status"] = "active"
    session["last_activity_at"] = now.isoformat()

    return {
        "session_id": session_id_str,
        "agent_id": str(agent_id),
        "action": "resume",
        "status": "active",
        "timestamp": now.isoformat(),
    }


@router.post(
    "/api/v1/agents/{agent_id}/sessions/{session_id}/terminate",
    response_model=SessionActionResponse,
)
async def terminate_session(
    agent_id: uuid.UUID, session_id: uuid.UUID
) -> dict[str, Any]:
    """Terminate an agent session.

    Args:
        agent_id: The agent that owns the session.
        session_id: The session to terminate.

    Returns:
        Confirmation of the termination action.

    Raises:
        HTTPException: If the session is not found or already terminated.
    """
    session_id_str = str(session_id)
    session = _sessions.get(session_id_str)

    if session is None or session["agent_id"] != str(agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found for agent {agent_id}",
        )

    if session["status"] == "terminated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session is already terminated",
        )

    now = datetime.now(timezone.utc)
    session["status"] = "terminated"
    session["last_activity_at"] = now.isoformat()

    return {
        "session_id": session_id_str,
        "agent_id": str(agent_id),
        "action": "terminate",
        "status": "terminated",
        "timestamp": now.isoformat(),
    }
