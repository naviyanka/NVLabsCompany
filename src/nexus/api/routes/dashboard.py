"""Dashboard stats and metrics endpoints."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select, func

from nexus.api.deps import DbSession
from nexus.models.agent import Agent
from nexus.models.task import Task, Goal, Project
from nexus.models.budget import CostEvent
from nexus.models.notification import Notification

router = APIRouter(tags=["dashboard"])


@router.get("/api/v1/companies/{company_id}/stats")
async def get_company_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Aggregated stats for the dashboard overview."""
    # Agent counts by status
    agent_result = await db.execute(
        select(Agent.status, func.count(Agent.id))
        .where(Agent.company_id == company_id)
        .group_by(Agent.status)
    )
    agent_counts = dict(agent_result.all())
    total_agents = sum(agent_counts.values())

    # Task counts by status
    task_result = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.company_id == company_id)
        .group_by(Task.status)
    )
    task_counts = dict(task_result.all())
    total_tasks = sum(task_counts.values())

    # Budget usage this month
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cost_result = await db.execute(
        select(func.coalesce(func.sum(CostEvent.cost_cents), 0))
        .where(CostEvent.company_id == company_id, CostEvent.occurred_at >= month_start)
    )
    monthly_spend = cost_result.scalar() or 0

    # Goals count
    goal_count = await db.execute(
        select(func.count(Goal.id)).where(Goal.company_id == company_id)
    )

    # Unread notifications
    unread_result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.company_id == company_id,
            Notification.read == False,
            Notification.dismissed == False,
        )
    )

    return {
        "agents": {
            "total": total_agents,
            "by_status": agent_counts,
        },
        "tasks": {
            "total": total_tasks,
            "by_status": task_counts,
        },
        "budget": {
            "monthly_spend_cents": monthly_spend,
        },
        "goals": {
            "total": goal_count.scalar() or 0,
        },
        "notifications": {
            "unread": unread_result.scalar() or 0,
        },
    }


@router.get("/api/v1/companies/{company_id}/metrics/daily")
async def get_daily_metrics(company_id: uuid.UUID, db: DbSession, days: int = 7) -> list[dict[str, Any]]:
    """Daily metrics for the last N days (tasks completed, cost, tokens)."""
    now = datetime.utcnow()
    metrics = []

    for i in range(days):
        day = now - timedelta(days=days - 1 - i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        # Tasks completed that day
        task_count = await db.execute(
            select(func.count(Task.id)).where(
                Task.company_id == company_id,
                Task.status == "completed",
                Task.completed_at >= day_start,
                Task.completed_at < day_end,
            )
        )

        # Cost that day
        cost = await db.execute(
            select(
                func.coalesce(func.sum(CostEvent.cost_cents), 0),
                func.coalesce(func.sum(CostEvent.input_tokens), 0),
                func.coalesce(func.sum(CostEvent.output_tokens), 0),
            ).where(
                CostEvent.company_id == company_id,
                CostEvent.occurred_at >= day_start,
                CostEvent.occurred_at < day_end,
            )
        )
        cost_row = cost.one()

        metrics.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "tasks_completed": task_count.scalar() or 0,
            "cost_cents": cost_row[0],
            "input_tokens": cost_row[1],
            "output_tokens": cost_row[2],
        })

    return metrics


@router.get("/api/v1/companies/{company_id}/dashboard/token-usage")
async def get_token_usage(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """Hourly token usage for the last 24 hours."""
    now = datetime.utcnow()
    start = now - timedelta(hours=24)

    stmt = (
        select(
            func.strftime("%Y-%m-%dT%H:00:00", CostEvent.occurred_at).label("hour"),
            func.coalesce(func.sum(CostEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(CostEvent.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(CostEvent.cost_cents), 0).label("cost_cents"),
        )
        .where(CostEvent.company_id == company_id, CostEvent.occurred_at >= start)
        .group_by("hour")
        .order_by("hour")
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "hour": row.hour,
            "input_tokens": int(row.input_tokens),
            "output_tokens": int(row.output_tokens),
            "cost_cents": int(row.cost_cents),
        }
        for row in rows
    ]



@router.get("/api/v1/companies/{company_id}/dashboard/pipelines-summary")
async def get_pipelines_summary(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """Top active pipelines with progress."""
    from nexus.models.pipeline import Pipeline, PipelineRun
    stmt = select(Pipeline).where(Pipeline.company_id == company_id, Pipeline.is_active == True).limit(5)
    result = await db.execute(stmt)
    pipelines = list(result.scalars().all())
    summaries = []
    for p in pipelines:
        run_stmt = select(PipelineRun).where(PipelineRun.pipeline_id == p.id).order_by(PipelineRun.started_at.desc()).limit(1)
        run_result = await db.execute(run_stmt)
        latest_run = run_result.scalar_one_or_none()
        total_stages = len(p.stages) if p.stages else 1
        summaries.append({
            "id": str(p.id), "name": p.name, "status": latest_run.status if latest_run else "idle",
            "progress": int((latest_run.current_stage / total_stages) * 100) if latest_run else 0,
        })
    return summaries


@router.get("/api/v1/companies/{company_id}/dashboard/top-agents")
async def get_top_agents(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """Top 5 agents by performance score."""
    from nexus.models.agent import Agent
    stmt = select(Agent).where(Agent.company_id == company_id).order_by(Agent.performance_score.desc().nulls_last()).limit(5)
    result = await db.execute(stmt)
    return [{"id": str(a.id), "name": a.name, "role": a.role, "model": a.model, "status": a.status, "performance_score": a.performance_score} for a in result.scalars().all()]


@router.get("/api/v1/companies/{company_id}/dashboard/token-usage")
async def get_token_usage_hourly(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """Hourly token usage for last 24h."""
    from nexus.models.budget import CostEvent
    now = datetime.utcnow()
    results = []
    for i in range(24):
        hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23 - i)
        hour_end = hour_start + timedelta(hours=1)
        row = await db.execute(
            select(func.coalesce(func.sum(CostEvent.input_tokens), 0), func.coalesce(func.sum(CostEvent.output_tokens), 0), func.coalesce(func.sum(CostEvent.cost_cents), 0))
            .where(CostEvent.company_id == company_id, CostEvent.occurred_at >= hour_start, CostEvent.occurred_at < hour_end)
        )
        r = row.one()
        results.append({"hour": hour_start.strftime("%H:00"), "input_tokens": r[0], "output_tokens": r[1], "cost_cents": r[2]})
    return results
