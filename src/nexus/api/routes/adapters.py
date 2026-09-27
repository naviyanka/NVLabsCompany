"""Adapter management API endpoints.

Provides endpoints for managing adapter types and agent task execution.

The ``/api/v1/agents/{agent_id}/sessions`` GET and the pause/resume/terminate
routes under it are deprecated aliases kept for existing clients. They read
and write the persistent agent sessions (``AgentSessionRecord``) with the same
tenant scoping, permissions and lifecycle rules as the canonical session API:

- list:      GET  /api/v1/companies/{company_id}/sessions?agent_id=...
- pause:     PATCH /api/v1/sessions/{id}  {"status": "idle"}
- resume:    PATCH /api/v1/sessions/{id}  {"status": "active"}
- terminate: POST /api/v1/sessions/{id}/terminate

"paused" is the canonical "idle" status and is reported as such.
"""

import uuid
from datetime import timezone, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession, require_permission

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
    return result


# ---------------------------------------------------------------------------
# Deprecated session aliases (see the module docstring)
# ---------------------------------------------------------------------------


async def _agent_session(
    db: Any, agent_id: uuid.UUID, session_id: uuid.UUID, company_id: uuid.UUID
):
    """The tenant's session belonging to ``agent_id``, or 404."""
    from nexus.models.agent_session import AgentSessionRecord

    record = (
        await db.execute(
            select(AgentSessionRecord).where(
                AgentSessionRecord.id == session_id,
                AgentSessionRecord.agent_id == agent_id,
                AgentSessionRecord.company_id == company_id,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found for agent {agent_id}",
        )
    return record


async def _session_action(
    db: Any, agent_id: uuid.UUID, session_id: uuid.UUID, company_id: uuid.UUID, action: str, to: str
) -> dict[str, Any]:
    """Apply one lifecycle transition through the canonical state machine, audited."""
    from nexus.governance.audit_service import record_audit
    from nexus.services.session_service import publish_session_event, transition
    from nexus.services.worktree_service import release_session_worktree

    record = await _agent_session(db, agent_id, session_id, company_id)
    transition(record, to)
    await release_session_worktree(db, record)
    await db.flush()
    await record_audit(
        company_id,
        f"session.{action}",
        actor_type="user",
        resource_type="session",
        resource_id=str(record.id),
        details={"agent_id": str(agent_id), "status": record.status, "via": "deprecated_alias"},
        db=db,
    )
    await db.commit()  # listeners refetch on the event: the change must be visible
    await publish_session_event(
        "session.updated",
        company_id,
        {"session_id": str(record.id), "agent_id": str(agent_id), "status": record.status},
    )
    return {
        "session_id": str(record.id),
        "agent_id": str(agent_id),
        "action": action,
        "status": record.status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/api/v1/agents/{agent_id}/sessions",
    response_model=list[SessionResponse],
    dependencies=[require_permission("read", "session")],
    deprecated=True,
)
async def list_agent_sessions(
    agent_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> list[dict[str, Any]]:
    """Deprecated: use GET /api/v1/companies/{company_id}/sessions?agent_id=...

    Lists the agent's persistent sessions, newest activity first.
    """
    from nexus.models.agent_session import AgentSessionRecord

    rows = (
        await db.execute(
            select(AgentSessionRecord)
            .where(
                AgentSessionRecord.company_id == company_id,
                AgentSessionRecord.agent_id == agent_id,
            )
            .order_by(AgentSessionRecord.last_activity_at.desc())
            .limit(200)
        )
    ).scalars()
    return [
        {
            "session_id": str(r.id),
            "agent_id": str(r.agent_id),
            "status": r.status,
            "created_at": r.started_at.isoformat(),
            "last_activity_at": r.last_activity_at.isoformat(),
        }
        for r in rows
    ]


@router.post(
    "/api/v1/agents/{agent_id}/sessions/{session_id}/pause",
    response_model=SessionActionResponse,
    dependencies=[require_permission("write", "session")],
    deprecated=True,
)
async def pause_session(
    agent_id: uuid.UUID, session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> dict[str, Any]:
    """Deprecated: use PATCH /api/v1/sessions/{id} with {"status": "idle"}."""
    return await _session_action(db, agent_id, session_id, company_id, "pause", "idle")


@router.post(
    "/api/v1/agents/{agent_id}/sessions/{session_id}/resume",
    response_model=SessionActionResponse,
    dependencies=[require_permission("write", "session")],
    deprecated=True,
)
async def resume_session(
    agent_id: uuid.UUID, session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> dict[str, Any]:
    """Deprecated: use PATCH /api/v1/sessions/{id} with {"status": "active"}."""
    return await _session_action(db, agent_id, session_id, company_id, "resume", "active")


@router.post(
    "/api/v1/agents/{agent_id}/sessions/{session_id}/terminate",
    response_model=SessionActionResponse,
    dependencies=[require_permission("write", "session")],
    deprecated=True,
)
async def terminate_session(
    agent_id: uuid.UUID, session_id: uuid.UUID, company_id: CurrentCompanyId, db: DbSession
) -> dict[str, Any]:
    """Deprecated: use POST /api/v1/sessions/{id}/terminate."""
    return await _session_action(db, agent_id, session_id, company_id, "terminate", "terminated")


# ---------------------------------------------------------------------------
# CLI Backend Detection
# ---------------------------------------------------------------------------


@router.get("/api/v1/adapters/cli-backends")
async def list_cli_backends() -> list[dict[str, Any]]:
    """List all known CLI backends with their installation status.

    Probes the system PATH to detect which CLI tools are installed.
    Returns id, name, command, description, and installed (bool).
    """
    from nexus.adapters.cli_registry import CLIRegistry

    registry = CLIRegistry(auto_detect=True)
    all_backends = registry.get_all()

    results = []
    for backend in all_backends:
        installed = registry.is_available(backend.id)
        version = None
        if installed:
            version = registry.probe_version(backend.id)

        results.append({
            "id": backend.id,
            "name": backend.name,
            "command": backend.command,
            "description": getattr(backend, 'description', ''),
            "guard_type": getattr(backend, 'guard_type', 'none'),
            "installed": installed,
            "path": registry.get_path(backend.id),
            "version": version,
        })

    return results
