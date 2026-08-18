"""Task Planner - decomposes complex tasks into ordered subtasks with dependencies."""

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubTask:
    """A decomposed unit of work derived from a parent task.

    Attributes:
        id: Unique identifier for this subtask.
        description: Human-readable description of the work.
        dependencies: IDs of subtasks that must complete before this one.
        assigned_agent_id: The agent assigned to execute this subtask, if any.
        status: Current status (pending, running, completed, failed).
        metadata: Additional context or parameters for the subtask.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    description: str = ""
    dependencies: list[uuid.UUID] = field(default_factory=list)
    assigned_agent_id: uuid.UUID | None = None
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskPlanner:
    """Decomposes complex tasks into ordered subtasks with dependency tracking.

    The planner analyzes a task description and produces a directed acyclic
    graph of subtasks. Each subtask specifies its dependencies so the
    orchestration layer can determine execution order.
    """

    def __init__(self, max_subtasks: int = 20) -> None:
        """Initialize the planner.

        Args:
            max_subtasks: Maximum number of subtasks to generate per decomposition.
        """
        self._max_subtasks = max_subtasks

    async def decompose_task(
        self,
        task_id: uuid.UUID,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> list[SubTask]:
        """Break a complex task into ordered subtasks with dependencies.

        This method analyzes the task description and context to produce
        a list of subtasks in topological order. Dependencies between
        subtasks are explicitly declared.

        Args:
            task_id: The parent task identifier.
            description: Full description of the task to decompose.
            context: Optional additional context (e.g., available skills, history).

        Returns:
            List of SubTask instances in execution order.
        """
        context = context or {}

        # Default decomposition produces a single subtask matching the input.
        # In a full implementation, this would call an LLM to plan steps.
        subtasks = self._default_decomposition(task_id, description, context)
        return subtasks[: self._max_subtasks]

    def _default_decomposition(
        self,
        task_id: uuid.UUID,
        description: str,
        context: dict[str, Any],
    ) -> list[SubTask]:
        """Produce a simple linear decomposition as a fallback.

        Args:
            task_id: The parent task identifier.
            description: Task description.
            context: Additional context for planning.

        Returns:
            A single-subtask list wrapping the original task.
        """
        subtask = SubTask(
            description=description,
            metadata={"parent_task_id": str(task_id), "context": context},
        )
        return [subtask]

    def validate_dependencies(self, subtasks: list[SubTask]) -> bool:
        """Check that subtask dependencies form a valid DAG.

        Args:
            subtasks: The list of subtasks to validate.

        Returns:
            True if the dependency graph is acyclic and all references are valid.
        """
        ids = {st.id for st in subtasks}
        # Check all referenced dependencies exist
        for st in subtasks:
            for dep_id in st.dependencies:
                if dep_id not in ids:
                    return False

        # Topological sort check for cycles
        visited: set[uuid.UUID] = set()
        in_progress: set[uuid.UUID] = set()
        id_to_subtask = {st.id: st for st in subtasks}

        def has_cycle(node_id: uuid.UUID) -> bool:
            if node_id in in_progress:
                return True
            if node_id in visited:
                return False
            in_progress.add(node_id)
            for dep_id in id_to_subtask[node_id].dependencies:
                if has_cycle(dep_id):
                    return True
            in_progress.discard(node_id)
            visited.add(node_id)
            return False

        for subtask in subtasks:
            if has_cycle(subtask.id):
                return False
        return True

    def get_ready_subtasks(self, subtasks: list[SubTask]) -> list[SubTask]:
        """Return subtasks whose dependencies are all completed.

        Args:
            subtasks: The full list of subtasks.

        Returns:
            Subtasks that are pending and have all dependencies satisfied.
        """
        completed_ids = {st.id for st in subtasks if st.status == "completed"}
        ready = []
        for st in subtasks:
            if st.status != "pending":
                continue
            if all(dep_id in completed_ids for dep_id in st.dependencies):
                ready.append(st)
        return ready
