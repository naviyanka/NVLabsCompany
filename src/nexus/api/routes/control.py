"""Control API endpoints - operator control over running agents."""

from fastapi import APIRouter, status
from pydantic import BaseModel

from nexus.governance.control_registry import AgentControlSnapshot, ControlRegistry

router = APIRouter(tags=["control"])

# Module-level singleton registry; in production this would be injected via DI.
_registry = ControlRegistry()


def get_registry() -> ControlRegistry:
    """Return the module-level ControlRegistry instance."""
    return _registry


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class PauseRequest(BaseModel):
    """Request body for pause/unpause."""

    on: bool


class GateToolRequest(BaseModel):
    """Request body for gating/ungating a tool."""

    tool: str
    on: bool


class SteerRequest(BaseModel):
    """Request body for injecting a steer note."""

    text: str


class SnapshotResponse(BaseModel):
    """Response model for agent control snapshot."""

    paused: bool
    halted: bool
    auto_delivery_paused: bool
    gated_tools: list[str]
    pending_steers: int


class ControlActionResponse(BaseModel):
    """Generic response for control actions."""

    ok: bool = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/control/{agent_id}/pause",
    status_code=status.HTTP_200_OK,
    response_model=ControlActionResponse,
)
def pause_agent(agent_id: str, body: PauseRequest) -> ControlActionResponse:
    """Pause or unpause an agent."""
    _registry.pause(agent_id, body.on)
    return ControlActionResponse()


@router.post(
    "/control/{agent_id}/gate-tool",
    status_code=status.HTTP_200_OK,
    response_model=ControlActionResponse,
)
def gate_tool(agent_id: str, body: GateToolRequest) -> ControlActionResponse:
    """Gate or ungate a tool for an agent."""
    _registry.gate_tool(agent_id, body.tool, body.on)
    return ControlActionResponse()


@router.post(
    "/control/{agent_id}/steer",
    status_code=status.HTTP_200_OK,
    response_model=ControlActionResponse,
)
def steer_agent(agent_id: str, body: SteerRequest) -> ControlActionResponse:
    """Inject a steer guidance note into the agent's queue."""
    _registry.steer(agent_id, body.text)
    return ControlActionResponse()


@router.post(
    "/control/{agent_id}/halt",
    status_code=status.HTTP_200_OK,
    response_model=ControlActionResponse,
)
def halt_agent(agent_id: str) -> ControlActionResponse:
    """Request a graceful halt for an agent."""
    _registry.halt(agent_id)
    return ControlActionResponse()


@router.post(
    "/control/{agent_id}/resume",
    status_code=status.HTTP_200_OK,
    response_model=ControlActionResponse,
)
def resume_agent(agent_id: str) -> ControlActionResponse:
    """Resume an agent (clears pause and halt, keeps gates)."""
    _registry.resume(agent_id)
    return ControlActionResponse()


@router.get(
    "/control/{agent_id}/snapshot",
    status_code=status.HTTP_200_OK,
    response_model=SnapshotResponse,
)
def get_snapshot(agent_id: str) -> SnapshotResponse:
    """Get the current control snapshot for an agent."""
    snap: AgentControlSnapshot = _registry.snapshot(agent_id)
    return SnapshotResponse(
        paused=snap.paused,
        halted=snap.halted,
        auto_delivery_paused=snap.auto_delivery_paused,
        gated_tools=snap.gated_tools,
        pending_steers=snap.pending_steers,
    )
