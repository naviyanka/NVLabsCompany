"""Legacy workflow API endpoints.

CompanyWorkflow / TaskFlow are no longer started from the API: they ran outside
the canonical execution intake (no budget reservation, approval gate, lease or
recovery). The start routes answer ``410 Gone``; governed work is submitted via
``POST /api/v1/work``. Existing ``workflow_runs`` rows stay readable, tenant
scoped, and can still be marked cancelled. None of these routes execute work.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession, PathCompanyId, require_permission
from nexus.models.workflow_run import WorkflowRun

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workflows"])

_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "blocked"}


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class WorkflowStatusResponse(BaseModel):
    """Response model for workflow status."""

    workflow_id: str
    status: str
    objective: str
    current_step: str | None = None
    total_cost_cents: int = 0
    started_at: str | None = None
    completed_at: str | None = None


class WorkflowStepResponse(BaseModel):
    """Response model for a single workflow step in a trace."""

    step_id: str
    agent_role: str
    action: str
    status: str
    cost_cents: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class WorkflowTraceResponse(BaseModel):
    """Response model for a complete workflow trace."""

    workflow_id: str
    objective: str
    status: str
    steps: list[WorkflowStepResponse]
    total_cost_cents: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt is not None else None


def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _row_to_status(run: WorkflowRun) -> dict[str, Any]:
    return {
        "workflow_id": str(run.id),
        "status": run.status,
        "objective": run.objective,
        "current_step": run.current_step,
        "total_cost_cents": run.total_cost_cents,
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
    }


def _row_to_trace(run: WorkflowRun) -> dict[str, Any]:
    return {
        "workflow_id": str(run.id),
        "objective": run.objective,
        "status": run.status,
        "steps": [
            {
                "step_id": s.get("step_id", ""),
                "agent_role": s.get("agent_role", ""),
                "action": s.get("action", ""),
                "status": s.get("status", ""),
                "cost_cents": s.get("cost_cents", 0),
                "started_at": s.get("started_at"),
                "completed_at": s.get("completed_at"),
                "error": s.get("error"),
            }
            for s in (run.steps or [])
        ],
        "total_cost_cents": run.total_cost_cents,
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "metadata": run.input_payload,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# Machine-readable reason for the retired start routes.
LEGACY_WORKFLOW_START_DISABLED = "LEGACY_WORKFLOW_START_DISABLED"


def _start_disabled() -> JSONResponse:
    """Refuse a legacy start without reading the body or touching the database.

    The caller must still be authenticated (401 otherwise), so the route does
    not become an anonymous probe.

    CompanyWorkflow / TaskFlow ran in an in-process ``asyncio`` task with no
    budget reservation, approval gate, lease or recovery. Governed work goes
    through ``POST /api/v1/work`` (Task + TaskAttempt). Nothing is created here,
    so a retried request cannot create duplicate work.
    """
    logger.warning("Legacy workflow start rejected")
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={
            "detail": (
                "Legacy workflow execution is retired. "
                "Submit governed work via POST /api/v1/work."
            ),
            "code": LEGACY_WORKFLOW_START_DISABLED,
        },
    )


@router.post("/api/v1/workflows/company", deprecated=True)
async def start_company_flow(_company_id: CurrentCompanyId) -> JSONResponse:
    """Retired: the CEO -> CTO -> Engineers -> QA chain bypassed governance."""
    return _start_disabled()


@router.post("/api/v1/workflows/task", deprecated=True)
async def start_task_flow(_company_id: CurrentCompanyId) -> JSONResponse:
    """Retired: the single-task flow bypassed governance."""
    return _start_disabled()


@router.get(
    "/api/v1/workflows/{workflow_id}/status",
    response_model=WorkflowStatusResponse,
)
async def get_workflow_status(
    workflow_id: str,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Get the current status of a workflow."""
    try:
        wf_uuid = uuid.UUID(workflow_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found")

    result = await db.execute(
        select(WorkflowRun).where(WorkflowRun.id == wf_uuid, WorkflowRun.company_id == company_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )
    return _row_to_status(run)


@router.get(
    "/api/v1/workflows/{workflow_id}/trace",
    response_model=WorkflowTraceResponse,
)
async def get_workflow_trace(
    workflow_id: str,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Get the full execution trace for a workflow."""
    try:
        wf_uuid = uuid.UUID(workflow_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found")

    result = await db.execute(
        select(WorkflowRun).where(WorkflowRun.id == wf_uuid, WorkflowRun.company_id == company_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )
    return _row_to_trace(run)


@router.get("/api/v1/companies/{company_id}/workflows")
async def list_company_workflows(
    company_id: PathCompanyId,
    db: DbSession,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List persisted workflows for a company, newest first."""
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.company_id == company_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()
    return [
        {
            "workflow_id": str(run.id),
            "workflow_type": run.workflow_type,
            "status": run.status,
            "objective": run.objective,
            "started_at": _iso(run.started_at),
            "completed_at": _iso(run.completed_at),
        }
        for run in runs
    ]


@router.post(
    "/api/v1/workflows/{workflow_id}/cancel",
    dependencies=[require_permission("write", "task")],
)
async def cancel_workflow(
    workflow_id: str,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Mark a non-terminal legacy run cancelled.

    No runner is started any more, so this only closes rows left ``running``
    by a process that died before the start routes were retired.
    """
    try:
        wf_uuid = uuid.UUID(workflow_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found")

    result = await db.execute(
        select(WorkflowRun).where(WorkflowRun.id == wf_uuid, WorkflowRun.company_id == company_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    if run.status not in _TERMINAL_STATUSES:
        run.status = "cancelled"
        run.completed_at = _naive_now()
        run.updated_at = run.completed_at
        db.add(run)

    return {
        "workflow_id": workflow_id,
        "status": "cancelled",
        "completed_at": _iso(run.completed_at),
    }
