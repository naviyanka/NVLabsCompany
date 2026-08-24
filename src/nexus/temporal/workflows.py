"""Temporal Workflows — durable execution orchestration.

Each workflow defines a long-running process that survives crashes.
Temporal automatically checkpoints state between activity calls.
"""

import uuid
import logging
from dataclasses import dataclass, field
from typing import Any

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


async def goal_pursuit_workflow(input: GoalPursuitInput) -> GoalPursuitOutput:
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
    from nexus.temporal.activities import (
        call_llm_activity, route_task_activity, decompose_task_activity,
        LLMCallInput, RouteTaskInput, DecomposeTaskInput,
    )

    total_tokens = 0
    subtasks_completed = 0

    for iteration in range(1, input.max_iterations + 1):
        # Step 1: Decompose
        decompose_input = DecomposeTaskInput(
            task_id=input.goal_id,
            description=f"{input.title}\n{input.description}",
            max_subtasks=5,
        )
        subtasks = await decompose_task_activity(decompose_input)

        if not subtasks:
            return GoalPursuitOutput(
                goal_id=input.goal_id, status="completed",
                iterations=iteration, subtasks_completed=subtasks_completed,
                total_tokens=total_tokens,
            )

        # Step 2 & 3: Route + Execute each subtask
        for st in subtasks:
            # Route
            route_input = RouteTaskInput(
                company_id=input.company_id,
                task_description=st["description"],
                required_skills=[],
            )
            agent_id = await route_task_activity(route_input)

            if not agent_id:
                continue

            # Execute
            llm_input = LLMCallInput(
                agent_id=agent_id,
                company_id=input.company_id,
                prompt=f"Execute: {st['description']}",
            )
            result = await call_llm_activity(llm_input)

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


async def pipeline_execution_workflow(input: PipelineExecutionInput) -> PipelineExecutionOutput:
    """Durable workflow: executes pipeline stages sequentially with checkpointing.

    This is the Temporal version of _execute_pipeline_bg() from pipelines.py.
    Each stage is an activity call — if the worker crashes between stages,
    Temporal resumes from the last completed stage.
    """
    from nexus.temporal.activities import call_llm_activity, LLMCallInput

    results: list[dict[str, Any]] = []
    previous_output = ""

    for i, stage in enumerate(input.stages):
        stage_name = stage.get("name", f"Stage-{i+1}")
        stage_prompt = stage.get("prompt", "")

        # Inject previous stage output
        if previous_output and i > 0:
            full_prompt = f"Previous output:\n{previous_output}\n\nCurrent task:\n{stage_prompt}"
        else:
            full_prompt = stage_prompt

        # Execute via LLM activity
        agent_id = stage.get("agent_id", input.company_id)  # Fallback
        llm_input = LLMCallInput(
            agent_id=agent_id,
            company_id=input.company_id,
            prompt=full_prompt,
        )
        result = await call_llm_activity(llm_input)

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
                results.append({"stage": stage_name, "status": "branched", "error": result.error})
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
