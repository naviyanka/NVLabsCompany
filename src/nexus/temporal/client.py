"""Temporal Client — starts workflows from API routes.

Feature-flagged: if USE_TEMPORAL=true and Temporal is reachable, uses durable
workflows. Otherwise falls back to existing BackgroundTasks implementation.

Usage:
    from nexus.temporal.client import start_goal_workflow, is_temporal_enabled

    if is_temporal_enabled():
        await start_goal_workflow(goal_id, company_id, title, description)
    else:
        # Use existing BackgroundTasks
        background_tasks.add_task(_drive_goal, ...)
"""

import os
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = "nexus-main"

_client: Any = None
_enabled: bool | None = None


def is_temporal_enabled() -> bool:
    """Check if Temporal integration is enabled and reachable."""
    global _enabled
    if _enabled is not None:
        return _enabled
    _enabled = os.environ.get("USE_TEMPORAL", "").lower() == "true"
    return _enabled


async def _get_client() -> Any:
    """Get or create the Temporal client (lazy singleton)."""
    global _client
    if _client is not None:
        return _client

    try:
        from temporalio.client import Client
        _client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)
        return _client
    except ImportError:
        logger.warning("temporalio not installed — Temporal features disabled")
        return None
    except Exception as e:
        logger.warning("Cannot connect to Temporal at %s: %s", TEMPORAL_HOST, e)
        return None


async def start_goal_workflow(
    goal_id: str, company_id: str, title: str, description: str,
    owner_agent_id: str | None = None,
) -> str | None:
    """Start a GoalPursuitWorkflow on Temporal.

    Returns the workflow run ID, or None if Temporal is unavailable.
    """
    if not is_temporal_enabled():
        return None

    client = await _get_client()
    if client is None:
        return None

    from nexus.temporal.workflows import goal_pursuit_workflow, GoalPursuitInput

    try:
        workflow_input = GoalPursuitInput(
            goal_id=goal_id,
            company_id=company_id,
            title=title,
            description=description,
            owner_agent_id=owner_agent_id,
        )
        handle = await client.start_workflow(
            goal_pursuit_workflow,
            workflow_input,
            id=f"goal-{goal_id}",
            task_queue=TASK_QUEUE,
        )
        logger.info("Started Temporal GoalPursuitWorkflow: %s", handle.id)
        return handle.id
    except Exception as e:
        logger.error("Failed to start goal workflow: %s", e)
        return None


async def start_pipeline_workflow(
    pipeline_id: str, run_id: str, company_id: str, stages: list[dict[str, Any]],
) -> str | None:
    """Start a PipelineExecutionWorkflow on Temporal.

    Returns the workflow run ID, or None if Temporal is unavailable.
    """
    if not is_temporal_enabled():
        return None

    client = await _get_client()
    if client is None:
        return None

    from nexus.temporal.workflows import pipeline_execution_workflow, PipelineExecutionInput

    try:
        workflow_input = PipelineExecutionInput(
            pipeline_id=pipeline_id,
            run_id=run_id,
            company_id=company_id,
            stages=stages,
        )
        handle = await client.start_workflow(
            pipeline_execution_workflow,
            workflow_input,
            id=f"pipeline-{run_id}",
            task_queue=TASK_QUEUE,
        )
        logger.info("Started Temporal PipelineExecutionWorkflow: %s", handle.id)
        return handle.id
    except Exception as e:
        logger.error("Failed to start pipeline workflow: %s", e)
        return None
