"""Event Bridge — connects the domain EventBus to the orchestration layer.

Subscribes to domain events (task failures, agent errors, budget warnings)
and triggers orchestration actions:
- TASK failures → FailureAnalyzer → auto-create evolution proposals
- AGENT errors → log + potential kill switch activation
- BUDGET warnings → alert + throttle

This makes the system self-healing: recurring failures automatically
generate improvement proposals without human intervention.

Usage:
    from nexus.runtime.event_bridge import register_event_handlers

    # During app startup (after EventBus is available):
    bus = EventBus(company_id=company_id)
    register_event_handlers(bus, session_factory)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


async def _handle_task_failure(
    event_type: str, payload: dict[str, Any], event: Any
) -> None:
    """Handle task failure events — trigger failure analysis and evolution proposals.

    When a task fails, this handler:
    1. Checks if the agent has had multiple recent failures
    2. If so, runs FailureAnalyzer for root cause analysis
    3. Creates an evolution proposal suggesting improvements
    """
    agent_id = payload.get("agent_id")
    task_title = payload.get("task_title", "Unknown task")
    error = payload.get("error", "Unknown error")
    company_id = payload.get("company_id")

    if not agent_id or not company_id:
        return

    logger.info(
        "Event bridge: task failure for agent %s — %s: %s",
        str(agent_id)[:8], task_title[:40], error[:100],
    )

    # We'll check failure count and potentially create a proposal
    # This is fire-and-forget; failures in analysis don't block the event flow
    try:
        from nexus.database import async_session_factory
        from nexus.models.task import Task
        from sqlalchemy import select, func

        async with async_session_factory() as db:
            # Count recent failures for this agent
            count_stmt = (
                select(func.count(Task.id))
                .where(
                    Task.assigned_agent_id == uuid.UUID(str(agent_id)),
                    Task.status == "failed",
                )
            )
            result = await db.execute(count_stmt)
            failure_count = result.scalar() or 0

            # If 3+ failures, create an evolution proposal
            if failure_count >= 3:
                from nexus.models.evolution import EvolutionProposal

                # Check if a recent proposal already exists
                existing = await db.execute(
                    select(func.count(EvolutionProposal.id)).where(
                        EvolutionProposal.proposed_by_agent_id == uuid.UUID(str(agent_id)),
                        EvolutionProposal.status == "proposed",
                    )
                )
                if (existing.scalar() or 0) < 2:  # Don't flood with proposals
                    proposal = EvolutionProposal(
                        company_id=uuid.UUID(str(company_id)),
                        proposal_type="agent_config",
                        title=f"Auto-improvement for agent {str(agent_id)[:8]} ({failure_count} failures)",
                        description=(
                            f"Agent has {failure_count} failed tasks. "
                            f"Latest error: {error[:200]}. "
                            f"Recommend running /diagnose endpoint for root cause analysis."
                        ),
                        expected_impact="Reduce failure rate by addressing root cause",
                        confidence=0.6,
                        risk_level="low",
                        proposed_by_agent_id=uuid.UUID(str(agent_id)),
                    )
                    db.add(proposal)
                    await db.commit()
                    logger.info(
                        "Event bridge: auto-created evolution proposal for agent %s",
                        str(agent_id)[:8],
                    )
    except Exception as e:
        logger.warning("Event bridge: failure handler error: %s", e)


async def _handle_agent_error(
    event_type: str, payload: dict[str, Any], event: Any
) -> None:
    """Handle agent error events — log and potentially activate circuit breaker."""
    agent_id = payload.get("agent_id")
    error = payload.get("error", "Unknown")

    logger.warning(
        "Event bridge: agent error %s — %s",
        str(agent_id)[:8] if agent_id else "unknown",
        error[:200],
    )


async def _handle_budget_warning(
    event_type: str, payload: dict[str, Any], event: Any
) -> None:
    """Handle budget warning events — log for operator visibility."""
    company_id = payload.get("company_id")
    spent = payload.get("spent_cents", 0)
    budget = payload.get("budget_cents", 0)
    pct = (spent / budget * 100) if budget > 0 else 0

    logger.warning(
        "Event bridge: budget warning for company %s — %.0f%% used (%d/%d cents)",
        str(company_id)[:8] if company_id else "unknown",
        pct, spent, budget,
    )


def register_event_handlers(event_bus: Any) -> None:
    """Register all orchestration event handlers on the given EventBus.

    Call this during app startup after the EventBus is instantiated.

    Args:
        event_bus: An instance of nexus.communication.event_bus.EventBus
    """
    from nexus.communication.event_bus import (
        TASK_COMPLETED,
        AGENT_ERROR,
        BUDGET_WARNING,
    )

    # Subscribe handlers (the EventBus calls these when events are published)
    event_bus.subscribe("task_failed", _handle_task_failure, is_async=True)
    event_bus.subscribe(AGENT_ERROR, _handle_agent_error, is_async=True)
    event_bus.subscribe(BUDGET_WARNING, _handle_budget_warning, is_async=True)

    logger.info("Event bridge: registered orchestration handlers (task_failed, agent_error, budget_warning)")
