"""LLM-enhanced Task Planner - uses LLM for intelligent task decomposition."""

import json
import uuid
from typing import Any, Callable, Awaitable

from nexus.orchestration.planner import TaskPlanner, SubTask


DEFAULT_DECOMPOSITION_PROMPT = """You are a task planner. Decompose the following task into concrete subtasks.

Task description: {task_description}

Context: {context}

Output a JSON array where each element has:
- "description": a clear description of the subtask
- "dependencies": a list of integer indices (0-based) of subtasks that must complete before this one

Rules:
- Each subtask should be a single, actionable unit of work.
- Dependencies reference other subtasks by their index in the array.
- The dependency graph must be acyclic (no circular dependencies).
- Output ONLY the JSON array, no additional text.

Example output:
[
  {{"description": "Research requirements", "dependencies": []}},
  {{"description": "Design solution", "dependencies": [0]}},
  {{"description": "Implement solution", "dependencies": [1]}},
  {{"description": "Write tests", "dependencies": [2]}}
]
"""


class LLMTaskPlanner:
    """Task planner that uses an LLM for intelligent decomposition.

    Uses a configurable LLM callable to decompose tasks into subtasks.
    Falls back gracefully to the existing heuristic-based TaskPlanner
    when the LLM call fails, returns unparseable output, or produces
    an invalid dependency graph.

    Attributes:
        llm_callable: Async function that takes a prompt string and returns a response string.
        max_subtasks: Maximum number of subtasks to generate.
        prompt_template: Template string with {task_description} and {context} placeholders.
    """

    def __init__(
        self,
        llm_callable: Callable[[str], Awaitable[str]],
        max_subtasks: int = 10,
        prompt_template: str | None = None,
    ) -> None:
        """Initialize the LLM-enhanced task planner.

        Args:
            llm_callable: Async function that accepts a prompt string and returns a response string.
            max_subtasks: Maximum number of subtasks to produce (default 10).
            prompt_template: Optional custom prompt template with {task_description} and {context} placeholders.
        """
        self._llm_callable = llm_callable
        self._max_subtasks = max_subtasks
        self._prompt_template = prompt_template or DEFAULT_DECOMPOSITION_PROMPT
        self._fallback_planner = TaskPlanner(max_subtasks=max_subtasks)

    async def decompose_task(
        self,
        task_id: uuid.UUID,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> list[SubTask]:
        """Decompose a task into subtasks using the LLM.

        Sends the task description and context to the LLM with a structured
        prompt, parses the JSON response into SubTask objects, and validates
        the dependency DAG. Falls back to the default decomposition if any
        step fails.

        Args:
            task_id: The parent task identifier.
            description: Full description of the task to decompose.
            context: Optional additional context for planning.

        Returns:
            List of SubTask instances in execution order.
        """
        context = context or {}

        try:
            prompt = self._prompt_template.format(
                task_description=description,
                context=json.dumps(context, default=str),
            )
            response = await self._llm_callable(prompt)
            subtasks = self._parse_llm_response(response, task_id, context)

            if len(subtasks) > self._max_subtasks:
                subtasks = subtasks[: self._max_subtasks]

            # Validate the dependency graph
            if not self._fallback_planner.validate_dependencies(subtasks):
                return self._fallback_planner._default_decomposition(
                    task_id, description, context
                )

            return subtasks

        except Exception:
            return self._fallback_planner._default_decomposition(
                task_id, description, context
            )

    def _parse_llm_response(
        self,
        response: str,
        task_id: uuid.UUID,
        context: dict[str, Any],
    ) -> list[SubTask]:
        """Parse the LLM JSON response into SubTask objects.

        Args:
            response: Raw LLM response string (expected to be a JSON array).
            task_id: The parent task identifier.
            context: Additional context for metadata.

        Returns:
            List of SubTask instances with proper UUIDs and dependencies.

        Raises:
            ValueError: If the response cannot be parsed into valid subtasks.
            json.JSONDecodeError: If the response is not valid JSON.
        """
        data = json.loads(response)

        if not isinstance(data, list) or len(data) == 0:
            raise ValueError("LLM response must be a non-empty JSON array")

        # Generate UUIDs for all subtasks first so we can map index-based dependencies
        subtask_ids = [uuid.uuid4() for _ in data]
        subtasks: list[SubTask] = []

        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"Subtask at index {i} is not a dictionary")

            description = item.get("description", "")
            if not description:
                raise ValueError(f"Subtask at index {i} has no description")

            # Map index-based dependencies to UUIDs
            raw_deps = item.get("dependencies", [])
            if not isinstance(raw_deps, list):
                raise ValueError(f"Subtask at index {i} has invalid dependencies")

            dep_uuids: list[uuid.UUID] = []
            for dep_idx in raw_deps:
                if not isinstance(dep_idx, int) or dep_idx < 0 or dep_idx >= len(data):
                    raise ValueError(
                        f"Subtask at index {i} has invalid dependency index: {dep_idx}"
                    )
                dep_uuids.append(subtask_ids[dep_idx])

            subtasks.append(
                SubTask(
                    id=subtask_ids[i],
                    description=description,
                    dependencies=dep_uuids,
                    metadata={"parent_task_id": str(task_id), "context": context},
                )
            )

        return subtasks
