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

import logging
import uuid
from typing import Any

from nexus.config import settings

logger = logging.getLogger(__name__)

# Read through Settings, so a value in .env works for local development and a
# docker-compose environment variable still overrides it.
TEMPORAL_HOST = settings.temporal_host
TEMPORAL_NAMESPACE = settings.temporal_namespace
TASK_QUEUE = "nexus-main"

_client: Any = None
_enabled: bool | None = None


def is_temporal_enabled() -> bool:
    """Whether Temporal-backed durable execution is switched on.

    Cached after the first call, so flipping the setting needs a restart. That
    matches how every other Settings value behaves here.
    """
    global _enabled
    if _enabled is not None:
        return _enabled
    _enabled = bool(settings.use_temporal)
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

    from nexus.temporal.workflows import GoalPursuitInput, GoalPursuitWorkflow

    try:
        workflow_input = GoalPursuitInput(
            goal_id=goal_id,
            company_id=company_id,
            title=title,
            description=description,
            owner_agent_id=owner_agent_id,
        )
        handle = await client.start_workflow(
            GoalPursuitWorkflow.run,
            workflow_input,
            id=f"goal-{goal_id}",
            task_queue=TASK_QUEUE,
        )
        logger.info("Started Temporal GoalPursuitWorkflow: %s", handle.id)
        return handle.id
    except Exception as e:
        logger.error("Failed to start goal workflow: %s", e)
        return None


class ObsidianIndexAlreadyRunningError(Exception):
    """An index workflow is already in flight for this company."""


async def start_obsidian_index_workflow(
    company_id: str, limit: int | None = None
) -> str | None:
    """Start an ObsidianIndexWorkflow, one at a time per company.

    The workflow id is derived from the company, and the conflict policy is FAIL,
    so Temporal itself rejects a second concurrent run. That is what replaces the
    in-process ``asyncio.Lock`` the synchronous path uses: a lock in the API
    process cannot serialize work against an activity running in the worker
    process, or against another API replica.

    Args:
        company_id: The company whose vault to index.
        limit: Optional cap on documents in this run.

    Returns:
        The workflow id, or None when Temporal is disabled or unreachable — the
        caller then falls back to the synchronous path.

    Raises:
        ObsidianIndexAlreadyRunningError: If a run is already in flight for this
            company.
    """
    if not is_temporal_enabled():
        return None

    client = await _get_client()
    if client is None:
        return None

    from temporalio.common import WorkflowIDConflictPolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError
    from temporalio.service import RPCError, RPCStatusCode

    from nexus.temporal.obsidian_workflow import ObsidianIndexInput, ObsidianIndexWorkflow

    try:
        handle = await client.start_workflow(
            ObsidianIndexWorkflow.run,
            ObsidianIndexInput(company_id=company_id, limit=limit),
            id=f"obsidian-index-{company_id}",
            task_queue=TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
        )
    except WorkflowAlreadyStartedError as exc:
        # The SDK raises this rather than a bare RPCError, and it derives from
        # FailureError, not RPCError — so catching RPCError alone would let a
        # duplicate fall through to the generic handler, return None, and send the
        # caller down the synchronous path while a workflow was already running.
        # Two writers on one company's documents is precisely what the conflict
        # policy exists to prevent.
        raise ObsidianIndexAlreadyRunningError(
            f"An Obsidian index run is already in flight for company {company_id}."
        ) from exc
    except RPCError as exc:
        if exc.status == RPCStatusCode.ALREADY_EXISTS:
            raise ObsidianIndexAlreadyRunningError(
                f"An Obsidian index run is already in flight for company {company_id}."
            ) from exc
        logger.error("Failed to start Obsidian index workflow: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 - fall back rather than fail the request
        logger.error("Failed to start Obsidian index workflow: %s", exc)
        return None

    logger.info("Started Temporal ObsidianIndexWorkflow: %s", handle.id)
    return handle.id


def obsidian_index_workflow_id(company_id: str) -> str:
    """The one workflow id this company's index runs use.

    Single source for the id, so the starter and the progress lookup cannot
    disagree about it — and so a caller's company is the *only* thing that decides
    which workflow they can address.
    """
    return f"obsidian-index-{company_id}"


def _execution_state(status: Any) -> str:
    """Temporal's execution status as a lowercase API string.

    Derived from the enum member name rather than a hand-written mapping, so a
    status this code has not seen (``timed_out``, ``terminated``,
    ``continued_as_new``) still reports honestly instead of collapsing to
    "unknown". ``CANCELED`` is spelled with two Ls on the way out, matching the
    rest of this API's British spelling.
    """
    name = getattr(status, "name", None)
    if not name:
        return "unknown"
    state = name.lower()
    return "cancelled" if state == "canceled" else state


class ObsidianIndexUnavailableError(Exception):
    """Temporal is disabled or unreachable, so progress cannot be read."""


class ObsidianIndexNotFoundError(Exception):
    """No such index run for this company."""


async def query_obsidian_index_progress(company_id: str, workflow_id: str) -> dict[str, Any]:
    """Progress of one company's index run, from Temporal.

    Tenant isolation is structural rather than checked after the fact: the id is
    rebuilt from the caller's authenticated company and the supplied one is only
    compared against it, so a workflow belonging to another company is never
    addressed — not queried and then filtered, which would leak its existence
    through timing and error shape.

    Execution state comes from ``describe()`` and the counts from the workflow's
    own query handler. A completed or failed run answers with state only: its
    handler is gone once the execution has closed, so there is nothing to query.

    Args:
        company_id: The authenticated caller's company.
        workflow_id: The id the caller is asking about.

    Returns:
        A dict with ``workflow_id``, ``state`` and, when the run is still going,
        the progress counts.

    Raises:
        ObsidianIndexUnavailableError: Temporal is off or unreachable.
        ObsidianIndexNotFoundError: No run exists under that id for this company.
    """
    if workflow_id != obsidian_index_workflow_id(company_id):
        raise ObsidianIndexNotFoundError(f"No index run {workflow_id} for this company.")

    if not is_temporal_enabled():
        raise ObsidianIndexUnavailableError("Durable indexing is not enabled.")

    client = await _get_client()
    if client is None:
        raise ObsidianIndexUnavailableError("Temporal is unreachable.")

    from temporalio.service import RPCError, RPCStatusCode

    handle = client.get_workflow_handle(workflow_id)
    try:
        description = await handle.describe()
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            raise ObsidianIndexNotFoundError(
                f"No index run {workflow_id} for this company."
            ) from exc
        raise ObsidianIndexUnavailableError(str(exc)) from exc

    state = _execution_state(description.status)
    result: dict[str, Any] = {"workflow_id": workflow_id, "state": state}
    if state != "running":
        # A closed execution has no query handler left to answer.
        return result

    from dataclasses import asdict

    try:
        progress = await handle.query("progress")
    except Exception as exc:  # noqa: BLE001 - the state above is still worth returning
        logger.warning("Could not query Obsidian index progress for %s: %s", workflow_id, exc)
        return result

    counts = progress if isinstance(progress, dict) else asdict(progress)
    result.update({k: v for k, v in counts.items() if k != "company_id"})
    return result


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

    from nexus.temporal.workflows import PipelineExecutionInput, PipelineExecutionWorkflow

    try:
        workflow_input = PipelineExecutionInput(
            pipeline_id=pipeline_id,
            run_id=run_id,
            company_id=company_id,
            stages=stages,
        )
        handle = await client.start_workflow(
            PipelineExecutionWorkflow.run,
            workflow_input,
            id=f"pipeline-{run_id}",
            task_queue=TASK_QUEUE,
        )
        logger.info("Started Temporal PipelineExecutionWorkflow: %s", handle.id)
        return handle.id
    except Exception as e:
        logger.error("Failed to start pipeline workflow: %s", e)
        return None
