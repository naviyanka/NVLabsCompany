"""Workflow execution API endpoints.

Starts and monitors real CompanyWorkflow / TaskFlow executions. Run state is
persisted in the ``workflow_runs`` table and updated by background runners, so
status, traces, and costs survive process restarts.
"""

import asyncio
import uuid
from datetime import timezone, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.workflow_run import WorkflowRun

router = APIRouter(tags=["workflows"])

_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "blocked"}


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
# Serialization helpers
# ---------------------------------------------------------------------------


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt is not None else None


def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _coerce_company_uuid(value: str | None, fallback: uuid.UUID) -> uuid.UUID:
    """Resolve the tenant scope, honoring legacy body overrides when valid."""
    if value:
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            pass
    return fallback


def _steps_to_dicts(steps: list[Any]) -> list[dict[str, Any]]:
    """Serialize engine WorkflowStep dataclasses into JSON-safe dicts."""
    result = []
    for step in steps or []:
        result.append({
            "step_id": step.step_id,
            "agent_role": step.agent_role,
            "action": step.action,
            "status": step.status,
            "cost_cents": step.cost_cents,
            "started_at": _iso(step.started_at),
            "completed_at": _iso(step.completed_at),
            "error": step.error,
        })
    return result


def _execution_to_step_dicts(execution: Any) -> list[dict[str, Any]]:
    """Map a TaskExecution record onto the trace-step response shape."""
    return [{
        "step_id": execution.execution_id,
        "agent_role": execution.agent_id or "system",
        "action": f"execute_task:{execution.adapter_type or 'default'}",
        "status": str(getattr(execution.status, "value", execution.status)),
        "cost_cents": execution.cost_cents,
        "started_at": _iso(execution.started_at),
        "completed_at": _iso(execution.completed_at),
        "error": execution.error,
    }]


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
# Background execution
# ---------------------------------------------------------------------------

_running_tasks: dict[str, asyncio.Task[None]] = {}


async def _persist_completion(
    run_id: uuid.UUID,
    company_id: uuid.UUID,
    *,
    status_value: str,
    steps: list[dict[str, Any]] | None = None,
    total_cost_cents: int = 0,
    current_step: str | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
    completed_at: datetime | None = None,
) -> None:
    """Write final engine output to the run row.

    A cancelled run keeps its cancelled status — the engine finishing after a
    cancel request must not resurrect it.

    The ``company_id`` filter is not defensive padding: a run id is a UUID the
    caller of the flow supplies, and without it a background runner would write
    another tenant's run row on a collision or a mixed-up id.
    """
    from nexus.database import async_session_factory

    async with async_session_factory() as session:
        result_q = await session.execute(
            select(WorkflowRun).where(
                WorkflowRun.id == run_id, WorkflowRun.company_id == company_id
            )
        )
        run = result_q.scalar_one_or_none()
        if run is None or run.status in _TERMINAL_STATUSES:
            return
        run.status = status_value
        run.steps = steps
        run.total_cost_cents = total_cost_cents
        run.current_step = current_step
        run.error = error
        run.result = result
        run.completed_at = completed_at or _naive_now()
        run.updated_at = _naive_now()
        session.add(run)
        await session.commit()


async def _register_company_agents(company_uuid: uuid.UUID, task_flow: Any) -> None:
    """Load the company's agents into a TaskFlow so selection works on real rows."""
    from nexus.database import async_session_factory
    from nexus.models.agent import Agent

    async with async_session_factory() as session:
        result = await session.execute(
            select(Agent).where(Agent.company_id == company_uuid, Agent.status != "terminated")
        )
        agents = result.scalars().all()

    for agent in agents:
        capabilities = agent.capabilities if isinstance(agent.capabilities, list) else []
        task_flow.register_agent(
            str(agent.id),
            capabilities,
            agent.adapter_type or "anthropic",
            config={"model": agent.model} if agent.model else None,
        )


async def _run_company_flow(
    run_id: uuid.UUID,
    company_uuid: uuid.UUID,
    objective: str,
    estimated_cost_cents: int,
    metadata: dict[str, Any] | None,
) -> None:
    """Execute a CompanyWorkflow and persist its trace."""
    try:
        from nexus.adapters.registry import AdapterRegistry
        from nexus.workflows.company_flow import CompanyWorkflow

        try:
            adapter_registry: Any = AdapterRegistry()
        except Exception:
            adapter_registry = None

        workflow = CompanyWorkflow(
            company_id=str(company_uuid),
            adapter_registry=adapter_registry,
        )
        trace = await workflow.execute(
            objective,
            estimated_cost_cents=estimated_cost_cents,
            metadata=metadata,
        )
        await _persist_completion(
            run_id,
            company_uuid,
            status_value=str(getattr(trace.status, "value", trace.status)),
            steps=_steps_to_dicts(trace.steps),
            total_cost_cents=trace.total_cost_cents,
            completed_at=trace.completed_at,
        )
    except asyncio.CancelledError:
        await _persist_completion(run_id, company_uuid, status_value="cancelled")
        raise
    except Exception as exc:
        await _persist_completion(
            run_id, company_uuid, status_value="failed", error=str(exc)
        )


async def _run_task_flow(
    run_id: uuid.UUID,
    company_uuid: uuid.UUID,
    task_id: str,
    payload: dict[str, Any],
    required_capabilities: list[str] | None,
    estimated_cost_cents: int,
    approval_type: str | None,
    max_attempts: int,
) -> None:
    """Execute a TaskFlow and persist its outcome."""
    try:
        from nexus.adapters.registry import AdapterRegistry
        from nexus.workflows.task_flow import TaskFlow

        try:
            adapter_registry: Any = AdapterRegistry()
        except Exception:
            adapter_registry = None

        flow = TaskFlow(
            company_id=str(company_uuid),
            adapter_registry=adapter_registry,
        )
        await _register_company_agents(company_uuid, flow)

        execution = await flow.execute_task(
            task_id=task_id,
            payload=payload,
            required_capabilities=required_capabilities,
            estimated_cost_cents=estimated_cost_cents,
            approval_type=approval_type,
            max_attempts=max_attempts,
        )
        await _persist_completion(
            run_id,
            company_uuid,
            status_value=str(getattr(execution.status, "value", execution.status)),
            steps=_execution_to_step_dicts(execution),
            total_cost_cents=execution.cost_cents,
            error=execution.error,
            result={
                "task_id": task_id,
                "execution_id": execution.execution_id,
                "attempt": execution.attempt,
                "max_attempts": execution.max_attempts,
                "output": execution.result,
            },
        )
    except asyncio.CancelledError:
        await _persist_completion(run_id, company_uuid, status_value="cancelled")
        raise
    except Exception as exc:
        await _persist_completion(
            run_id, company_uuid, status_value="failed", error=str(exc)
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/workflows/company",
    response_model=WorkflowStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_company_flow(
    body: StartCompanyFlowRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Start a company workflow with a high-level objective.

    Creates a persisted WorkflowRun and initiates the real delegation chain
    (CEO -> CTO -> Engineers -> QA) as a background task.
    """
    effective_company = _coerce_company_uuid(body.company_id, company_id)
    now = _naive_now()

    run = WorkflowRun(
        company_id=effective_company,
        workflow_type="company",
        status="running",
        objective=body.objective,
        input_payload={
            "estimated_cost_cents": body.estimated_cost_cents,
            "metadata": body.metadata or {},
        },
        current_step="ceo:create_strategy",
        steps=[{
            "step_id": str(uuid.uuid4()),
            "agent_role": "ceo",
            "action": "create_strategy",
            "status": "running",
            "cost_cents": 0,
            "started_at": now.isoformat(),
            "completed_at": None,
            "error": None,
        }],
        started_at=now,
        updated_at=now,
    )
    db.add(run)
    await db.flush()

    task = asyncio.create_task(
        _run_company_flow(
            run.id,
            effective_company,
            body.objective,
            body.estimated_cost_cents,
            body.metadata,
        )
    )
    _running_tasks[str(run.id)] = task

    return {
        "workflow_id": str(run.id),
        "status": "running",
        "objective": body.objective,
        "started_at": now.isoformat(),
    }


@router.post(
    "/api/v1/workflows/task",
    response_model=WorkflowStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_task_flow(
    body: StartTaskFlowRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Start a single task flow.

    Creates a persisted WorkflowRun and runs the governed task lifecycle
    (governance checks -> agent selection -> execution -> validation) as a
    background task.
    """
    effective_company = _coerce_company_uuid(None, company_id)
    now = _naive_now()
    task_id = body.task_id or str(uuid.uuid4())

    run = WorkflowRun(
        company_id=effective_company,
        workflow_type="task",
        status="running",
        objective=body.objective,
        input_payload={
            "task_id": task_id,
            "required_capabilities": body.required_capabilities or [],
            "estimated_cost_cents": body.estimated_cost_cents,
            "max_attempts": body.max_attempts,
            "approval_type": body.approval_type,
        },
        current_step="system:selecting_agent",
        steps=[{
            "step_id": str(uuid.uuid4()),
            "agent_role": "system",
            "action": "selecting_agent",
            "status": "running",
            "cost_cents": 0,
            "started_at": now.isoformat(),
            "completed_at": None,
            "error": None,
        }],
        started_at=now,
        updated_at=now,
    )
    db.add(run)
    await db.flush()

    task = asyncio.create_task(
        _run_task_flow(
            run.id,
            effective_company,
            task_id,
            {"objective": body.objective},
            body.required_capabilities,
            body.estimated_cost_cents,
            body.approval_type,
            body.max_attempts,
        )
    )
    _running_tasks[str(run.id)] = task

    return {
        "workflow_id": str(run.id),
        "status": "running",
        "objective": body.objective,
        "started_at": now.isoformat(),
    }


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
    company_id: uuid.UUID,
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


@router.post("/api/v1/workflows/{workflow_id}/cancel")
async def cancel_workflow(
    workflow_id: str,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Cancel a running workflow.

    Marks the run cancelled immediately and signals the background task; the
    runner never overwrites a terminal status, so a late engine finish cannot
    resurrect the run.
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

    running = _running_tasks.pop(workflow_id, None)
    if running is not None and not running.done():
        running.cancel()

    return {
        "workflow_id": workflow_id,
        "status": "cancelled",
        "completed_at": _iso(run.completed_at),
    }
