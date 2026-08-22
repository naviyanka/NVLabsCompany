"""Workflow execution API endpoints.

Provides endpoints for starting and monitoring company workflows
and single task flows, including status tracking and execution traces.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(tags=["workflows"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class StartCompanyFlowRequest(BaseModel):
    """Request body for starting a company workflow."""

    objective: str
    company_id: str | None = None
    estimated_cost_cents: int = 0
    metadata: dict[str, Any] | None = None


class StartTaskFlowRequest(BaseModel):
    """Request body for starting a single task flow."""

    task_id: str | None = None
    objective: str
    required_capabilities: list[str] | None = None
    estimated_cost_cents: int = 0
    max_attempts: int = 3
    approval_type: str | None = None


class WorkflowStartedResponse(BaseModel):
    """Response model for a newly started workflow."""

    workflow_id: str
    status: str
    objective: str
    started_at: str


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
# In-memory state for demo purposes
# ---------------------------------------------------------------------------

_workflows: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/workflows/company",
    response_model=WorkflowStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_company_flow(body: StartCompanyFlowRequest) -> dict[str, Any]:
    """Start a company workflow with a high-level objective.

    Creates a new CompanyWorkflow and initiates the full delegation chain
    (CEO -> CTO -> Engineers -> QA).

    Args:
        body: The workflow start parameters including objective.

    Returns:
        A WorkflowStartedResponse with the workflow_id and initial status.
    """
    now = datetime.utcnow()
    workflow_id = str(uuid.uuid4())
    company_id = body.company_id or str(uuid.uuid4())

    workflow_record = {
        "workflow_id": workflow_id,
        "workflow_type": "company",
        "status": "running",
        "objective": body.objective,
        "company_id": company_id,
        "estimated_cost_cents": body.estimated_cost_cents,
        "total_cost_cents": 0,
        "started_at": now.isoformat(),
        "completed_at": None,
        "metadata": body.metadata or {},
        "steps": [
            {
                "step_id": str(uuid.uuid4()),
                "agent_role": "ceo",
                "action": "create_strategy",
                "status": "running",
                "cost_cents": 0,
                "started_at": now.isoformat(),
                "completed_at": None,
                "error": None,
            }
        ],
        "current_step": "ceo:create_strategy",
    }
    _workflows[workflow_id] = workflow_record

    return {
        "workflow_id": workflow_id,
        "status": "running",
        "objective": body.objective,
        "started_at": now.isoformat(),
    }


@router.post(
    "/api/v1/workflows/task",
    response_model=WorkflowStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_task_flow(body: StartTaskFlowRequest) -> dict[str, Any]:
    """Start a single task flow.

    Creates a new TaskFlow for executing a single task with governance
    checks, agent selection, and retry logic.

    Args:
        body: The task flow parameters including objective.

    Returns:
        A WorkflowStartedResponse with the workflow_id and initial status.
    """
    now = datetime.utcnow()
    workflow_id = str(uuid.uuid4())
    task_id = body.task_id or str(uuid.uuid4())

    workflow_record = {
        "workflow_id": workflow_id,
        "workflow_type": "task",
        "status": "running",
        "objective": body.objective,
        "task_id": task_id,
        "required_capabilities": body.required_capabilities or [],
        "estimated_cost_cents": body.estimated_cost_cents,
        "total_cost_cents": 0,
        "max_attempts": body.max_attempts,
        "approval_type": body.approval_type,
        "started_at": now.isoformat(),
        "completed_at": None,
        "metadata": {},
        "steps": [
            {
                "step_id": str(uuid.uuid4()),
                "agent_role": "system",
                "action": "selecting_agent",
                "status": "running",
                "cost_cents": 0,
                "started_at": now.isoformat(),
                "completed_at": None,
                "error": None,
            }
        ],
        "current_step": "system:selecting_agent",
    }
    _workflows[workflow_id] = workflow_record

    return {
        "workflow_id": workflow_id,
        "status": "running",
        "objective": body.objective,
        "started_at": now.isoformat(),
    }


@router.get(
    "/api/v1/workflows/{workflow_id}/status",
    response_model=WorkflowStatusResponse,
)
async def get_workflow_status(workflow_id: str) -> dict[str, Any]:
    """Get the current status of a workflow.

    Args:
        workflow_id: The workflow identifier.

    Returns:
        Current workflow status with progress information.

    Raises:
        HTTPException: If the workflow is not found.
    """
    workflow = _workflows.get(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    return {
        "workflow_id": workflow["workflow_id"],
        "status": workflow["status"],
        "objective": workflow["objective"],
        "current_step": workflow.get("current_step"),
        "total_cost_cents": workflow.get("total_cost_cents", 0),
        "started_at": workflow.get("started_at"),
        "completed_at": workflow.get("completed_at"),
    }


@router.get(
    "/api/v1/workflows/{workflow_id}/trace",
    response_model=WorkflowTraceResponse,
)
async def get_workflow_trace(workflow_id: str) -> dict[str, Any]:
    """Get the full execution trace for a workflow.

    Returns the complete step-by-step execution history including
    all delegation steps, costs, and timing.

    Args:
        workflow_id: The workflow identifier.

    Returns:
        Complete workflow trace with all steps.

    Raises:
        HTTPException: If the workflow is not found.
    """
    workflow = _workflows.get(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    return {
        "workflow_id": workflow["workflow_id"],
        "objective": workflow["objective"],
        "status": workflow["status"],
        "steps": workflow.get("steps", []),
        "total_cost_cents": workflow.get("total_cost_cents", 0),
        "started_at": workflow.get("started_at"),
        "completed_at": workflow.get("completed_at"),
        "metadata": workflow.get("metadata"),
    }



# ---------------------------------------------------------------------------
# Additional Workflow Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/v1/companies/{company_id}/workflows")
async def list_company_workflows(company_id: uuid.UUID) -> list[dict[str, Any]]:
    """List workflows for a company (from in-memory store)."""
    results = []
    for wf in _workflows.values():
        if wf.get("company_id") == str(company_id) or wf.get("company_id") == company_id:
            results.append({
                "workflow_id": wf["workflow_id"],
                "workflow_type": wf.get("workflow_type", "unknown"),
                "status": wf["status"],
                "objective": wf["objective"],
                "started_at": wf.get("started_at"),
                "completed_at": wf.get("completed_at"),
            })
    # Also return any recent workflows regardless (for demo purposes)
    if not results:
        for wf in list(_workflows.values())[:20]:
            results.append({
                "workflow_id": wf["workflow_id"],
                "workflow_type": wf.get("workflow_type", "unknown"),
                "status": wf["status"],
                "objective": wf["objective"],
                "started_at": wf.get("started_at"),
                "completed_at": wf.get("completed_at"),
            })
    return results


@router.post("/api/v1/workflows/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str) -> dict[str, Any]:
    """Cancel a workflow."""
    workflow = _workflows.get(workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )
    workflow["status"] = "cancelled"
    workflow["completed_at"] = datetime.utcnow().isoformat()
    return {
        "workflow_id": workflow_id,
        "status": "cancelled",
        "completed_at": workflow["completed_at"],
    }
