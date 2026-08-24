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


from fastapi import BackgroundTasks


async def _execute_pipeline_bg(run_id: uuid.UUID, pipeline_id: uuid.UUID, company_id: uuid.UUID) -> None:
    """Background task to execute pipeline stages sequentially.

    Each stage is a dict with:
    - name: stage name
    - prompt: the instruction/prompt for this stage (required)
    - agent_id: optional specific agent to use (falls back to any active agent)
    - adapter_type: optional override (e.g., "anthropic", "cli")
    - model: optional model override

    Output from stage N is injected into stage N+1's prompt as context.
    """
    import logging
    from nexus.database import async_session_factory
    from nexus.models.agent import Agent

    logger = logging.getLogger(__name__)

    async with async_session_factory() as db:
        # Load the run
        stmt = select(PipelineRun).where(PipelineRun.id == run_id)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if not run:
            return

        # Load the pipeline definition
        pipeline_stmt = select(Pipeline).where(Pipeline.id == pipeline_id)
        p_res = await db.execute(pipeline_stmt)
        pipeline = p_res.scalar_one_or_none()
        if not pipeline or not pipeline.stages:
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            db.add(run)
            await db.commit()
            return

        stage_results: list[dict[str, Any]] = []
        previous_output = ""

        for i, stage in enumerate(pipeline.stages):
            # Check if run was cancelled/paused externally
            await db.refresh(run)
            if run.status in ("cancelled", "paused"):
                break

            stage_name = stage.get("name", f"Stage-{i+1}")
            stage_prompt = stage.get("prompt", stage.get("instruction", ""))
            stage_agent_id = stage.get("agent_id")
            is_parallel = stage.get("parallel", False)
            sub_prompts = stage.get("sub_prompts", [])

            # Update current stage progress
            run.current_stage = i
            db.add(run)
            await db.commit()

            # --- Parallel fan-out stage ---
            if is_parallel and sub_prompts:
                from nexus.orchestration.parallel import ParallelExecutor
                from nexus.api.routes.chat import _build_system_prompt, _call_llm, _fetch_agent_memories

                # Find agents for parallel execution
                agent_stmt = select(Agent).where(
                    Agent.company_id == company_id,
                    Agent.status.in_(["active", "ready"]),
                ).limit(len(sub_prompts))
                a_res = await db.execute(agent_stmt)
                available_agents = list(a_res.scalars().all())

                if not available_agents:
                    stage_results.append({
                        "stage": stage_name,
                        "stage_index": i,
                        "status": "failed",
                        "error": "No available agents for parallel execution",
                        "completed_at": datetime.utcnow().isoformat(),
                    })
                    run.status = "failed"
                    run.error = f"Stage '{stage_name}': No agents for parallel"
                    break

                # Build parallel task payloads
                parallel_tasks = []
                for j, sp in enumerate(sub_prompts):
                    prompt_text = sp if isinstance(sp, str) else sp.get("prompt", "")
                    if previous_output and i > 0:
                        prompt_text = f"Context from previous stage:\n---\n{previous_output}\n---\n\n{prompt_text}"
                    agent_for_task = available_agents[j % len(available_agents)]
                    parallel_tasks.append({
                        "id": str(uuid.uuid4()),
                        "prompt": prompt_text,
                        "agent": agent_for_task,
                    })

                # Executor function for ParallelExecutor
                async def _execute_one(task_payload: dict[str, Any]) -> str:
                    agent_obj = task_payload["agent"]
                    memories = await _fetch_agent_memories(db, agent_obj.id, company_id, limit=3)
                    sys_prompt = _build_system_prompt(agent_obj, memories=memories)
                    text, _, _ = await _call_llm(agent_obj, sys_prompt, task_payload["prompt"], [])
                    return text

                executor = ParallelExecutor(max_concurrency=3, timeout_seconds=120.0)
                parallel_result = await executor.execute_parallel(parallel_tasks, _execute_one)

                # Collect parallel outputs
                outputs = []
                for pr in parallel_result.results:
                    outputs.append(str(pr.output) if pr.success else f"[FAILED: {pr.error}]")

                previous_output = "\n---\n".join(outputs)
                stage_results.append({
                    "stage": stage_name,
                    "stage_index": i,
                    "status": "success" if parallel_result.failed == 0 else "partial",
                    "parallel": True,
                    "total_tasks": parallel_result.total_tasks,
                    "succeeded": parallel_result.succeeded,
                    "failed": parallel_result.failed,
                    "outputs": [o[:2000] for o in outputs],
                    "duration_ms": parallel_result.total_duration_ms,
                    "completed_at": datetime.utcnow().isoformat(),
                })
                continue

            # Inject previous stage output as context
            full_prompt = stage_prompt
            if previous_output and i > 0:
                full_prompt = (
                    f"Previous stage output:\n---\n{previous_output}\n---\n\n"
                    f"Current task:\n{stage_prompt}"
                )

            # Find the agent to use for this stage
            agent = None
            if stage_agent_id:
                agent_stmt = select(Agent).where(
                    Agent.id == uuid.UUID(stage_agent_id) if isinstance(stage_agent_id, str) else Agent.id == stage_agent_id,
                    Agent.company_id == company_id,
                )
                a_res = await db.execute(agent_stmt)
                agent = a_res.scalar_one_or_none()

            if not agent:
                # Fallback: pick any active agent in the company
                agent_stmt = select(Agent).where(
                    Agent.company_id == company_id,
                    Agent.status.in_(["active", "ready"]),
                ).limit(1)
                a_res = await db.execute(agent_stmt)
                agent = a_res.scalar_one_or_none()

            if not agent:
                stage_results.append({
                    "stage": stage_name,
                    "stage_index": i,
                    "status": "failed",
                    "error": "No available agent to execute this stage",
                    "completed_at": datetime.utcnow().isoformat(),
                })
                run.status = "failed"
                run.error = f"Stage '{stage_name}': No agent available"
                break

            # Execute the stage via the chat/adapter system
            try:
                from nexus.api.routes.chat import _build_system_prompt, _call_llm, _fetch_agent_memories

                # Build context with agent's soul + memories
                memories = await _fetch_agent_memories(db, agent.id, company_id, limit=5)
                system_prompt = _build_system_prompt(agent, memories=memories)

                # Call the LLM adapter
                response_text, model_used, tokens_used = await _call_llm(
                    agent, system_prompt, full_prompt, []
                )

                # Optional quality gate via CriticEvaluator
                quality_score = None
                quality_passed = True
                if stage.get("quality_gate", False):
                    try:
                        # Try LLM-based critic first (better quality assessment)
                        from nexus.orchestration.llm_critic import LLMCriticEvaluator
                        from nexus.orchestration.critic import CriticEvaluator
                        threshold = stage.get("quality_threshold", 0.7)

                        try:
                            async def critic_llm_fn(prompt: str) -> str:
                                t, _, _ = await _call_llm(agent, system_prompt, prompt, [])
                                return t
                            critic = LLMCriticEvaluator(llm_callable=critic_llm_fn, quality_threshold=threshold)
                        except Exception:
                            critic = CriticEvaluator(quality_threshold=threshold)

                        eval_result = await critic.evaluate(
                            task_id=run_id,
                            task_description=stage_prompt,
                            result=response_text,
                        )
                        quality_score = eval_result.score
                        quality_passed = eval_result.passed
                        if not quality_passed:
                            logger.warning(
                                "Pipeline stage %d failed quality gate (%.2f < threshold)",
                                i, quality_score
                            )
                    except Exception as qe:
                        logger.warning("Quality gate error (non-blocking): %s", qe)

                previous_output = response_text

                stage_results.append({
                    "stage": stage_name,
                    "stage_index": i,
                    "status": "success" if quality_passed else "quality_failed",
                    "output": response_text[:5000],
                    "agent_id": str(agent.id),
                    "agent_name": agent.name,
                    "model_used": model_used,
                    "tokens_used": tokens_used,
                    "quality_score": quality_score,
                    "completed_at": datetime.utcnow().isoformat(),
                })

            except Exception as e:
                logger.error("Pipeline stage %d failed: %s", i, e)
                stage_results.append({
                    "stage": stage_name,
                    "stage_index": i,
                    "status": "failed",
                    "error": f"{type(e).__name__}: {e}",
                    "completed_at": datetime.utcnow().isoformat(),
                })

                # Conditional branching: if stage has on_fail, jump to that stage index
                on_fail = stage.get("on_fail")
                if on_fail is not None and isinstance(on_fail, int) and on_fail < len(pipeline.stages):
                    logger.info("Pipeline stage %d failed → branching to stage %d", i, on_fail)
                    # Inject the on_fail stage as next iteration
                    fallback_stage = pipeline.stages[on_fail]
                    stage_results.append({
                        "stage": f"Branch → {fallback_stage.get('name', f'Stage-{on_fail+1}')}",
                        "stage_index": on_fail,
                        "status": "branched",
                        "triggered_by_failure_of": stage_name,
                    })
                    # Don't mark run as failed — continue with the fallback path
                    continue

                run.status = "failed"
                run.error = f"Stage '{stage_name}' failed: {e}"
                break

        # Finalize run
        if run.status == "running":
            run.status = "completed"
        run.results = stage_results
        run.completed_at = datetime.utcnow()
        db.add(run)
        await db.commit()


@router.post("/api/v1/pipelines/{pipeline_id}/run", status_code=status.HTTP_201_CREATED, response_model=PipelineRunResponse)
async def run_pipeline(
    pipeline_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Trigger a pipeline execution with background stage runner."""
    stmt = select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.company_id == company_id)
    result = await db.execute(stmt)
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    run = PipelineRun(pipeline_id=pipeline_id, company_id=company_id, status="running")
    db.add(run)
    await db.flush()

    # Schedule background execution worker
    background_tasks.add_task(_execute_pipeline_bg, run.id, pipeline_id, company_id)
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


class PipelineImportBody(BaseModel):
    """Request body for importing a pipeline."""

    name: str
    description: str | None = None
    stages: list[dict[str, Any]] | None = None


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
