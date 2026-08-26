"""Agent performance profiling — per-agent latency/cost/success dashboards.

Aggregates real usage data from tool_invocations (duration, status, cost) and
cost_events (tokens, cost) into per-agent performance metrics.
"""

import uuid
from datetime import timezone, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from nexus.api.deps import DbSession
from nexus.models.agent import Agent
from nexus.models.budget import CostEvent
from nexus.models.tool_invocation import ToolInvocation

router = APIRouter(tags=["agents"])


@router.get("/api/v1/companies/{company_id}/agents/profiling")
async def agent_profiling(
    company_id: uuid.UUID,
    db: DbSession,
    days: int = 30,
) -> dict[str, Any]:
    """Return performance metrics for every agent in the company.

    Metrics derive from ToolInvocation (tool calls) and CostEvent (LLM spend):
      - calls, success_rate, avg_duration_ms, total_cost_cents
      - tokens_in, tokens_out, llm_cost_cents
    """
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    agents = (await db.execute(
        select(Agent).where(Agent.company_id == company_id)
    )).scalars().all()

    tool_rows = (await db.execute(
        select(
            ToolInvocation.agent_id,
            func.count(ToolInvocation.id),
            func.avg(ToolInvocation.duration_ms),
            func.sum(ToolInvocation.cost_cents),
            func.sum(func.case((ToolInvocation.status == "success", 1), else_=0)),
        )
        .where(
            ToolInvocation.company_id == company_id,
            ToolInvocation.created_at >= since,
        )
        .group_by(ToolInvocation.agent_id)
    )).all()

    cost_rows = (await db.execute(
        select(
            CostEvent.agent_id,
            func.sum(CostEvent.cost_cents),
            func.sum(CostEvent.input_tokens),
            func.sum(CostEvent.output_tokens),
        )
        .where(
            CostEvent.company_id == company_id,
            CostEvent.occurred_at >= since,
        )
        .group_by(CostEvent.agent_id)
    )).all()

    tool_map = {r[0]: r for r in tool_rows}
    cost_map = {r[0]: r for r in cost_rows}

    profiles = []
    for agent in agents:
        t = tool_map.get(agent.id)
        c = cost_map.get(agent.id)

        calls = int(t[1]) if t else 0
        success = int(t[4]) if t else 0
        avg_duration = float(t[2] or 0) if t else 0.0
        tool_cost = int(t[3] or 0) if t else 0
        llm_cost = int(c[1] or 0) if c else 0
        tokens_in = int(c[2] or 0) if c else 0
        tokens_out = int(c[3] or 0) if c else 0

        profiles.append({
            "agent_id": str(agent.id),
            "name": agent.name,
            "role": agent.role or "",
            "status": agent.status or "",
            "calls": calls,
            "success_rate": (success / calls) if calls else None,
            "avg_duration_ms": round(avg_duration, 1),
            "tool_cost_cents": tool_cost,
            "llm_cost_cents": llm_cost,
            "total_cost_cents": tool_cost + llm_cost,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        })

    profiles.sort(key=lambda p: -(p["total_cost_cents"] or 0))

    return {
        "days": days,
        "agents": profiles,
        "company_totals": {
            "total_cost_cents": sum(p["total_cost_cents"] for p in profiles),
            "total_calls": sum(p["calls"] for p in profiles),
            "total_tokens": sum(p["total_tokens"] for p in profiles),
        },
    }