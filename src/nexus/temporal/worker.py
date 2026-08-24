"""Temporal Worker — polls Temporal server for workflow/activity tasks.

Run as a separate process: python -m nexus.temporal.worker

Connects to the Temporal server and processes GoalPursuit and Pipeline
workflows. Automatically retries activities on failure.
"""

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = "nexus-main"


async def run_worker():
    """Start the Temporal worker."""
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker
        from nexus.temporal.activities import (
            call_llm_activity, route_task_activity, decompose_task_activity,
        )
        from nexus.temporal.workflows import (
            goal_pursuit_workflow, pipeline_execution_workflow,
        )

        logger.info("Connecting to Temporal at %s (namespace: %s)", TEMPORAL_HOST, TEMPORAL_NAMESPACE)
        client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)

        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[goal_pursuit_workflow, pipeline_execution_workflow],
            activities=[call_llm_activity, route_task_activity, decompose_task_activity],
        )

        logger.info("Temporal worker started on queue '%s'", TASK_QUEUE)
        await worker.run()

    except ImportError:
        logger.error("temporalio package not installed. Run: pip install temporalio")
        sys.exit(1)
    except Exception as e:
        logger.error("Temporal worker failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Ensure src is in path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    asyncio.run(run_worker())
