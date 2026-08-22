"""Pipeline CRUD and execution endpoints."""

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.pipeline import Pipeline, PipelineRun

router = APIRouter(tags=["pipelines"])


class PipelineCreate(BaseModel):
    name: str
    description: str | None = None
    stages: list[dict[str, Any]] | None = None
    trigger_type: str = "manual"


class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    stages: list[dict[str, Any]] | None = None
    trigger_type: str | None = None
    is_active: bool | None = None


class PipelineResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None
    stages: list[dict[str, Any]] | None
    is_active: bool
    trigger_type: str
    created_at: datetime
    updated_at: datetime


class PipelineRunResponse(BaseModel):
    id: uuid.UUID
    pipeline_id: uuid.UUID
    company_id: uuid.UUID
    status: str
    current_stage: int
    results: list[dict[str, Any]] | None
    error: str | None
    started_at: datetime
    completed_at: datetime | None


@router.get("/api/v1/companies/{company_id}/pipelines", response_model=list[PipelineResponse])
async def list_pipelines(company_id: uuid.UUID, db: DbSession, limit: int = 50, offset: int = 0) -> Any:
    """List pipelines for a company."""
    stmt = select(Pipeline).where(Pipeline.company_id == company_id).offset(offset).limit(limit).order_by(Pipeline.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/api/v1/companies/{company_id}/pipelines", status_code=status.HTTP_201_CREATED, response_model=PipelineResponse)
async def create_pipeline(company_id: uuid.UUID, body: PipelineCreate, db: DbSession) -> Any:
    """Create a new pipeline."""
    pipeline = Pipeline(company_id=company_id, name=body.name, description=body.description, stages=body.stages, trigger_type=body.trigger_type)
    db.add(pipeline)
    await db.flush()
    return pipeline


@router.get("/api/v1/pipelines/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(pipeline_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get pipeline detail."""
    stmt = select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.company_id == company_id)
    result = await db.execute(stmt)
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline


@router.put("/api/v1/pipelines/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(pipeline_id: uuid.UUID, body: PipelineUpdate, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Update a pipeline."""
    stmt = select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.company_id == company_id)
    result = await db.execute(stmt)
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    updates = body.model_dump(exclude_unset=True)
    updates["updated_at"] = datetime.utcnow()
    for k, v in updates.items():
        setattr(pipeline, k, v)
    await db.flush()
    return pipeline


@router.delete("/api/v1/pipelines/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(pipeline_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete a pipeline."""
    from sqlalchemy import delete as sa_delete
    stmt = sa_delete(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.company_id == company_id)
    await db.execute(stmt)


@router.post("/api/v1/pipelines/{pipeline_id}/run", status_code=status.HTTP_201_CREATED, response_model=PipelineRunResponse)
async def run_pipeline(pipeline_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Trigger a pipeline execution."""
    stmt = select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.company_id == company_id)
    result = await db.execute(stmt)
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    run = PipelineRun(pipeline_id=pipeline_id, company_id=company_id, status="running")
    db.add(run)
    await db.flush()
    return run


@router.get("/api/v1/pipelines/{pipeline_id}/runs", response_model=list[PipelineRunResponse])
async def list_pipeline_runs(pipeline_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, limit: int = 20) -> Any:
    """List execution history for a pipeline."""
    stmt = select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id, PipelineRun.company_id == company_id).order_by(PipelineRun.started_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/api/v1/pipeline-runs/{run_id}", response_model=PipelineRunResponse)
async def get_pipeline_run(run_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get a specific pipeline run."""
    stmt = select(PipelineRun).where(PipelineRun.id == run_id, PipelineRun.company_id == company_id)
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return run



# ---------------------------------------------------------------------------
# Pipeline Stats, Templates, and Control Actions
# ---------------------------------------------------------------------------


@router.get("/api/v1/companies/{company_id}/pipelines/stats")
async def get_pipeline_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Pipeline statistics for a company."""
    from sqlalchemy import func

    # Total pipelines
    total_result = await db.execute(
        select(func.count(Pipeline.id)).where(Pipeline.company_id == company_id)
    )
    total = total_result.scalar() or 0

    # Active pipelines
    active_result = await db.execute(
        select(func.count(Pipeline.id)).where(
            Pipeline.company_id == company_id, Pipeline.is_active == True
        )
    )
    active = active_result.scalar() or 0

    # By status from latest runs
    run_status_result = await db.execute(
        select(PipelineRun.status, func.count(PipelineRun.id))
        .where(PipelineRun.company_id == company_id)
        .group_by(PipelineRun.status)
    )
    by_status = dict(run_status_result.all())

    # Average stages
    all_pipelines = await db.execute(
        select(Pipeline.stages).where(Pipeline.company_id == company_id)
    )
    stages_list = all_pipelines.scalars().all()
    stage_counts = [len(s) for s in stages_list if s]
    avg_stages = round(sum(stage_counts) / len(stage_counts), 1) if stage_counts else 0

    return {
        "total": total,
        "active": active,
        "by_status": by_status,
        "avg_stages": avg_stages,
    }


@router.get("/api/v1/companies/{company_id}/pipelines/templates")
async def list_pipeline_templates(company_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return hardcoded list of pipeline templates."""
    return [
        {
            "id": "tpl-ci-cd",
            "name": "CI/CD Pipeline",
            "description": "Build, test, and deploy application code",
            "stages_count": 4,
            "category": "deployment",
        },
        {
            "id": "tpl-data-etl",
            "name": "Data ETL Pipeline",
            "description": "Extract, transform, and load data from sources",
            "stages_count": 3,
            "category": "data",
        },
        {
            "id": "tpl-code-review",
            "name": "Code Review Pipeline",
            "description": "Automated code review with multiple agents",
            "stages_count": 5,
            "category": "quality",
        },
        {
            "id": "tpl-onboarding",
            "name": "Agent Onboarding",
            "description": "Onboard a new agent with training and evaluation",
            "stages_count": 6,
            "category": "hr",
        },
        {
            "id": "tpl-incident-response",
            "name": "Incident Response",
            "description": "Detect, triage, and resolve incidents automatically",
            "stages_count": 4,
            "category": "operations",
        },
    ]


@router.post("/api/v1/pipelines/{pipeline_id}/pause")
async def pause_pipeline(pipeline_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict[str, Any]:
    """Pause the latest running pipeline run."""
    stmt = (
        select(PipelineRun)
        .where(
            PipelineRun.pipeline_id == pipeline_id,
            PipelineRun.company_id == company_id,
            PipelineRun.status == "running",
        )
        .order_by(PipelineRun.started_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No running pipeline run found")
    run.status = "paused"
    await db.flush()
    return {"pipeline_id": str(pipeline_id), "run_id": str(run.id), "status": "paused"}


@router.post("/api/v1/pipelines/{pipeline_id}/stop")
async def stop_pipeline(pipeline_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict[str, Any]:
    """Stop (cancel) the latest running pipeline run."""
    stmt = (
        select(PipelineRun)
        .where(
            PipelineRun.pipeline_id == pipeline_id,
            PipelineRun.company_id == company_id,
            PipelineRun.status == "running",
        )
        .order_by(PipelineRun.started_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No running pipeline run found")
    run.status = "cancelled"
    run.completed_at = datetime.utcnow()
    await db.flush()
    return {"pipeline_id": str(pipeline_id), "run_id": str(run.id), "status": "cancelled"}


class PipelineImportBody(BaseModel):
    """Request body for importing a pipeline."""

    name: str
    description: str | None = None
    stages: list[dict[str, Any]] | None = None


@router.post(
    "/api/v1/companies/{company_id}/pipelines/import",
    status_code=status.HTTP_201_CREATED,
    response_model=PipelineResponse,
)
async def import_pipeline(company_id: uuid.UUID, body: PipelineImportBody, db: DbSession) -> Any:
    """Import a pipeline definition."""
    pipeline = Pipeline(
        company_id=company_id,
        name=body.name,
        description=body.description,
        stages=body.stages,
        trigger_type="manual",
    )
    db.add(pipeline)
    await db.flush()
    return pipeline



@router.get("/api/v1/companies/{company_id}/pipelines/stats")
async def pipeline_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Pipeline statistics."""
    from sqlalchemy import func
    total = await db.execute(select(func.count(Pipeline.id)).where(Pipeline.company_id == company_id))
    active = await db.execute(select(func.count(Pipeline.id)).where(Pipeline.company_id == company_id, Pipeline.is_active == True))
    return {"total": total.scalar() or 0, "active": active.scalar() or 0}


@router.get("/api/v1/companies/{company_id}/pipelines/templates")
async def pipeline_templates(company_id: uuid.UUID) -> list[dict[str, Any]]:
    """Available pipeline templates."""
    return [
        {"id": "recon", "name": "Reconnaissance Pipeline", "description": "Multi-step recon: subdomain enum, port scan, tech detection", "stages_count": 5, "category": "security"},
        {"id": "code-review", "name": "Code Review Automation", "description": "Lint, test, security scan, review, merge", "stages_count": 4, "category": "development"},
        {"id": "data-etl", "name": "Data ETL Pipeline", "description": "Extract, transform, validate, load, notify", "stages_count": 5, "category": "data"},
        {"id": "deploy", "name": "CI/CD Deployment", "description": "Build, test, stage, deploy, verify", "stages_count": 5, "category": "devops"},
        {"id": "content", "name": "Content Generation", "description": "Research, draft, review, publish", "stages_count": 4, "category": "content"},
    ]


@router.post("/api/v1/pipelines/{pipeline_id}/pause")
async def pause_pipeline(pipeline_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict:
    """Pause the latest running execution."""
    stmt = select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id, PipelineRun.company_id == company_id, PipelineRun.status == "running").order_by(PipelineRun.started_at.desc()).limit(1)
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No running execution found")
    run.status = "paused"
    await db.flush()
    return {"run_id": str(run.id), "status": "paused"}


@router.post("/api/v1/pipelines/{pipeline_id}/stop")
async def stop_pipeline(pipeline_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict:
    """Stop/cancel the latest running execution."""
    from datetime import datetime
    stmt = select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id, PipelineRun.company_id == company_id, PipelineRun.status.in_(["running", "paused"])).order_by(PipelineRun.started_at.desc()).limit(1)
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No active execution found")
    run.status = "cancelled"
    run.completed_at = datetime.utcnow()
    await db.flush()
    return {"run_id": str(run.id), "status": "cancelled"}


@router.post("/api/v1/companies/{company_id}/pipelines/import", status_code=status.HTTP_201_CREATED, response_model=PipelineResponse)
async def import_pipeline(company_id: uuid.UUID, body: PipelineCreate, db: DbSession) -> Any:
    """Import a pipeline definition."""
    pipeline = Pipeline(company_id=company_id, name=body.name, description=body.description, stages=body.stages, trigger_type=body.trigger_type)
    db.add(pipeline)
    await db.flush()
    return pipeline
