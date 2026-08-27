"""Temporal Workflows — durable execution orchestration.

Each workflow defines a long-running process that survives crashes.
Temporal automatically checkpoints state between activity calls.

Workflow bodies hold orchestration logic only; every LLM call, DB read, and
adapter session goes through an activity (ADR 0001). Activities are invoked via
``_sdk.execute_activity`` so the same body also runs in-process when Temporal is
unreachable. LLM calls pass ``ONCE_ONLY`` because a retry would bill twice.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from nexus.temporal._sdk import (
    LLM_TIMEOUT,
    ONCE_ONLY,
    execute_activity,
    imports_passed_through,
    workflow_defn,
    workflow_run,
)

with imports_passed_through():
    from nexus.temporal.activities import (
        DecomposeTaskInput,
        LLMCallInput,
        RouteTaskInput,
        call_llm_activity,
        decompose_task_activity,
        route_task_activity,
    )

logger = logging.getLogger(__name__)


@dataclass
class GoalPursuitInput:
    """Input for the GoalPursuitWorkflow."""
    goal_id: str
    company_id: str
    title: str
    description: str
    owner_agent_id: str | None = None
    max_iterations: int = 10


@dataclass
class GoalPursuitOutput:
    """Output from the GoalPursuitWorkflow."""
    goal_id: str
    status: str  # completed, failed, blocked
    iterations: int
    subtasks_completed: int
    total_tokens: int


@dataclass
class PipelineExecutionInput:
    """Input for the PipelineExecutionWorkflow."""
    pipeline_id: str
    run_id: str
    company_id: str
    stages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PipelineExecutionOutput:
    """Output from the PipelineExecutionWorkflow."""
    run_id: str
    status: str
    stages_completed: int
    total_stages: int
    results: list[dict[str, Any]] = field(default_factory=list)


@workflow_defn(name="GoalPursuitWorkflow")
class GoalPursuitWorkflow:
    """Durable workflow: pursues a goal through decomposition, routing, and execution.

    This is the Temporal version of _drive_goal() from orchestrator.py.
    Unlike the background task version, this survives server crashes and
    resumes from the last successful activity call.

    Flow:
    1. Decompose goal into subtasks (Activity)
    2. Route each subtask to best agent (Activity)
    3. Execute each subtask via LLM (Activity)
    4. Evaluate if goal is complete
    5. Repeat if needed (up to max_iterations)
    """

    @workflow_run
    async def run(self, input: GoalPursuitInput) -> GoalPursuitOutput:
        total_tokens = 0
        subtasks_completed = 0

        for iteration in range(1, input.max_iterations + 1):
            # Step 1: Decompose
            subtasks = await execute_activity(
                decompose_task_activity,
                DecomposeTaskInput(
                    task_id=input.goal_id,
                    description=f"{input.title}\n{input.description}",
                    max_subtasks=5,
                ),
            )

            if not subtasks:
                return GoalPursuitOutput(
                    goal_id=input.goal_id, status="completed",
                    iterations=iteration, subtasks_completed=subtasks_completed,
                    total_tokens=total_tokens,
                )

            # Step 2 & 3: Route + Execute each subtask
            for st in subtasks:
                agent_id = await execute_activity(
                    route_task_activity,
                    RouteTaskInput(
                        company_id=input.company_id,
                        task_description=st["description"],
                        required_skills=[],
                    ),
                )

                if not agent_id:
                    continue

                result = await execute_activity(
                    call_llm_activity,
                    LLMCallInput(
                        agent_id=agent_id,
                        company_id=input.company_id,
                        prompt=f"Execute: {st['description']}",
                    ),
                    timeout=LLM_TIMEOUT,
                    maximum_attempts=ONCE_ONLY,
                )

                if result.success:
                    subtasks_completed += 1
                    total_tokens += result.tokens_used

            # Step 4: Simple completion check (can be enhanced with GoalJudge)
            if subtasks_completed >= len(subtasks):
                return GoalPursuitOutput(
                    goal_id=input.goal_id, status="completed",
                    iterations=iteration, subtasks_completed=subtasks_completed,
                    total_tokens=total_tokens,
                )

        return GoalPursuitOutput(
            goal_id=input.goal_id, status="max_iterations",
            iterations=input.max_iterations, subtasks_completed=subtasks_completed,
            total_tokens=total_tokens,
        )


@workflow_defn(name="PipelineExecutionWorkflow")
class PipelineExecutionWorkflow:
    """Durable workflow: executes pipeline stages sequentially with checkpointing.

    This is the Temporal version of _execute_pipeline_bg() from pipelines.py.
    Each stage is an activity call — if the worker crashes between stages,
    Temporal resumes from the last completed stage.
    """

    @workflow_run
    async def run(self, input: PipelineExecutionInput) -> PipelineExecutionOutput:
        results: list[dict[str, Any]] = []
        previous_output = ""

        for i, stage in enumerate(input.stages):
            stage_name = stage.get("name", f"Stage-{i+1}")
            stage_prompt = stage.get("prompt", "")

            # Inject previous stage output
            if previous_output and i > 0:
                full_prompt = (
                    f"Previous output:\n{previous_output}\n\nCurrent task:\n{stage_prompt}"
                )
            else:
                full_prompt = stage_prompt

            # Execute via LLM activity
            agent_id = stage.get("agent_id", input.company_id)  # Fallback
            result = await execute_activity(
                call_llm_activity,
                LLMCallInput(
                    agent_id=agent_id,
                    company_id=input.company_id,
                    prompt=full_prompt,
                ),
                timeout=LLM_TIMEOUT,
                maximum_attempts=ONCE_ONLY,
            )

            if result.success:
                previous_output = result.response_text
                results.append({
                    "stage": stage_name, "status": "success",
                    "tokens": result.tokens_used, "output": result.response_text[:2000],
                })
            else:
                # Check for on_fail branching
                on_fail = stage.get("on_fail")
                if on_fail is not None:
                    results.append(
                        {"stage": stage_name, "status": "branched", "error": result.error}
                    )
                    continue
                results.append({"stage": stage_name, "status": "failed", "error": result.error})
                return PipelineExecutionOutput(
                    run_id=input.run_id, status="failed",
                    stages_completed=i, total_stages=len(input.stages), results=results,
                )

        return PipelineExecutionOutput(
            run_id=input.run_id, status="completed",
            stages_completed=len(input.stages), total_stages=len(input.stages), results=results,
        )


# The workflows were module-level async functions before Phase 0.4a; the SDK
# requires classes. These aliases keep the old import names working.
goal_pursuit_workflow = GoalPursuitWorkflow
pipeline_execution_workflow = PipelineExecutionWorkflow

# Single registration list so the worker cannot drift out of sync with this file.
ALL_WORKFLOWS = [GoalPursuitWorkflow, PipelineExecutionWorkflow]
