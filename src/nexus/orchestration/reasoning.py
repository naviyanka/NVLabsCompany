"""Tree-of-Thought (ToT) Reasoning Engine.

Implements a tree-based reasoning approach for complex task decomposition.
Uses LLM callables to expand thought nodes, evaluate paths, and select
optimal strategies. Falls back to linear planning when tree exploration fails.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from nexus.orchestration.planner import SubTask, TaskPlanner


@dataclass
class ThoughtNode:
    """A single node in the reasoning tree.

    Each node represents a thought or reasoning step, with scoring
    to evaluate its quality and links to parent/child nodes for
    tree traversal.

    Attributes:
        id: Unique identifier for this node.
        content: The textual content of this thought.
        parent_id: UUID of the parent node, or None for root.
        children: List of child ThoughtNode instances.
        score: Quality score assigned during evaluation (0.0 to 1.0).
        depth: Depth level in the tree (root = 0).
        metadata: Additional context or annotations for this node.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    content: str = ""
    parent_id: uuid.UUID | None = None
    children: list["ThoughtNode"] = field(default_factory=list)
    score: float = 0.0
    depth: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ThoughtTree:
    """A tree structure for organizing and evaluating reasoning paths.

    The ThoughtTree manages a hierarchy of ThoughtNode instances,
    supporting expansion (generating child thoughts), evaluation
    (scoring nodes), path selection (finding the best root-to-leaf
    path), and pruning (removing low-quality branches).

    Attributes:
        root: The root ThoughtNode of the tree.
    """

    def __init__(self, root: ThoughtNode) -> None:
        """Initialize the thought tree with a root node.

        Args:
            root: The root ThoughtNode representing the initial problem/task.
        """
        self.root = root

    async def expand(
        self,
        node: ThoughtNode,
        llm_callable: Callable[[str], Awaitable[str]],
        branching_factor: int = 3,
    ) -> list[ThoughtNode]:
        """Generate child thoughts for a given node using the LLM.

        Sends a prompt to the LLM asking for multiple alternative
        continuations of the current thought, then creates child nodes.

        Args:
            node: The parent node to expand.
            llm_callable: Async function that takes a prompt and returns a response.
            branching_factor: Number of child thoughts to generate.

        Returns:
            List of newly created child ThoughtNode instances.

        Raises:
            ValueError: If the LLM response cannot be parsed.
        """
        prompt = (
            f"Given the following thought or problem:\n\n"
            f"\"{node.content}\"\n\n"
            f"Generate exactly {branching_factor} distinct alternative "
            f"next steps or approaches to explore. "
            f"Output a JSON array of strings, each being one approach.\n"
            f"Example: [\"approach 1\", \"approach 2\", \"approach 3\"]"
        )

        response = await llm_callable(prompt)
        thoughts = json.loads(response)

        if not isinstance(thoughts, list):
            raise ValueError("LLM response must be a JSON array of strings")

        children: list[ThoughtNode] = []
        for thought_content in thoughts[:branching_factor]:
            child = ThoughtNode(
                content=str(thought_content),
                parent_id=node.id,
                depth=node.depth + 1,
                metadata={"expanded_from": str(node.id)},
            )
            children.append(child)

        node.children.extend(children)
        return children

    async def evaluate(
        self,
        node: ThoughtNode,
        llm_callable: Callable[[str], Awaitable[str]],
    ) -> float:
        """Score a node using the LLM to assess its quality.

        Asks the LLM to evaluate how promising a particular thought
        or approach is on a scale of 0.0 to 1.0.

        Args:
            node: The node to evaluate.
            llm_callable: Async function that takes a prompt and returns a response.

        Returns:
            Float score between 0.0 and 1.0.
        """
        prompt = (
            f"Evaluate the following thought or approach on a scale from "
            f"0.0 (completely unhelpful) to 1.0 (excellent):\n\n"
            f"\"{node.content}\"\n\n"
            f"Output ONLY a single decimal number between 0.0 and 1.0."
        )

        response = await llm_callable(prompt)
        score = float(response.strip())
        score = max(0.0, min(1.0, score))
        node.score = score
        return score

    def select_best_path(self) -> list[ThoughtNode]:
        """Find the highest-scoring path from root to a leaf node.

        Traverses the tree and identifies the path with the highest
        cumulative score. If multiple paths exist, selects the one
        with the greatest sum of node scores.

        Returns:
            List of ThoughtNode instances from root to the best leaf.
            Returns [root] if the tree has no children.
        """
        best_path: list[ThoughtNode] = []
        best_score = -1.0

        def _traverse(node: ThoughtNode, path: list[ThoughtNode], cumulative: float) -> None:
            nonlocal best_path, best_score
            current_path = path + [node]
            current_score = cumulative + node.score

            if not node.children:
                # Leaf node - check if this is the best path
                if current_score > best_score:
                    best_score = current_score
                    best_path = current_path
            else:
                for child in node.children:
                    _traverse(child, current_path, current_score)

        _traverse(self.root, [], 0.0)
        return best_path if best_path else [self.root]

    def prune(self, threshold: float) -> int:
        """Remove branches with scores below the given threshold.

        Recursively removes child nodes whose scores fall below
        the threshold. A node is pruned only if it has been scored
        (score > 0 check is skipped - all nodes below threshold are pruned).

        Args:
            threshold: Minimum score to keep a node (0.0 to 1.0).

        Returns:
            Number of nodes pruned.
        """
        pruned_count = 0

        def _prune_node(node: ThoughtNode) -> int:
            nonlocal pruned_count
            surviving_children: list[ThoughtNode] = []

            for child in node.children:
                if child.score < threshold:
                    # Count this child and all its descendants
                    pruned_count += _count_nodes(child)
                else:
                    _prune_node(child)
                    surviving_children.append(child)

            node.children = surviving_children
            return pruned_count

        def _count_nodes(node: ThoughtNode) -> int:
            """Count a node and all its descendants."""
            count = 1
            for child in node.children:
                count += _count_nodes(child)
            return count

        _prune_node(self.root)
        return pruned_count


class ToTPlanner:
    """Tree-of-Thought Task Planner.

    Uses tree-based exploration to decompose complex tasks into subtasks.
    Generates multiple alternative decomposition paths, evaluates them,
    and selects the best one. Falls back to linear planning (TaskPlanner)
    if tree exploration fails.

    Attributes:
        llm_callable: Async function for LLM interactions.
        branching_factor: Number of alternatives to generate at each level.
        max_depth: Maximum depth of the thought tree.
        beam_width: Number of top candidates to keep at each level.
    """

    def __init__(
        self,
        llm_callable: Callable[[str], Awaitable[str]],
        branching_factor: int = 3,
        max_depth: int = 3,
        beam_width: int = 2,
    ) -> None:
        """Initialize the ToT planner.

        Args:
            llm_callable: Async function that accepts a prompt and returns a response.
            branching_factor: Number of child thoughts per expansion (default 3).
            max_depth: Maximum tree depth to explore (default 3).
            beam_width: Number of top-scoring nodes to keep at each level (default 2).
        """
        self._llm_callable = llm_callable
        self._branching_factor = branching_factor
        self._max_depth = max_depth
        self._beam_width = beam_width
        self._fallback_planner = TaskPlanner()

    @property
    def branching_factor(self) -> int:
        """Return the configured branching factor."""
        return self._branching_factor

    @property
    def max_depth(self) -> int:
        """Return the configured maximum depth."""
        return self._max_depth

    @property
    def beam_width(self) -> int:
        """Return the configured beam width."""
        return self._beam_width

    async def decompose_task(
        self,
        task_id: uuid.UUID,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> list[SubTask]:
        """Decompose a task using tree-of-thought exploration.

        Builds a thought tree by iteratively expanding and evaluating
        nodes, then converts the best path into a sequence of SubTask
        objects. Falls back to linear planning if tree exploration fails.

        Args:
            task_id: The parent task identifier.
            description: Full description of the task to decompose.
            context: Optional additional context for planning.

        Returns:
            List of SubTask instances derived from the best reasoning path.
        """
        context = context or {}

        try:
            # Build the thought tree
            root = ThoughtNode(
                content=description,
                depth=0,
                metadata={"task_id": str(task_id), "context": context},
            )
            tree = ThoughtTree(root=root)

            # Iterative beam search expansion
            current_level_nodes = [root]

            for depth in range(self._max_depth):
                next_level_nodes: list[ThoughtNode] = []

                for node in current_level_nodes:
                    children = await tree.expand(
                        node, self._llm_callable, self._branching_factor
                    )
                    next_level_nodes.extend(children)

                # Evaluate all nodes at this level
                for node in next_level_nodes:
                    await tree.evaluate(node, self._llm_callable)

                # Beam search: keep only top beam_width nodes
                next_level_nodes.sort(key=lambda n: n.score, reverse=True)
                current_level_nodes = next_level_nodes[: self._beam_width]

                if not current_level_nodes:
                    break

            # Select best path and convert to subtasks
            best_path = tree.select_best_path()
            subtasks = self._path_to_subtasks(best_path, task_id, context)

            if not subtasks:
                return self._fallback_planner._default_decomposition(
                    task_id, description, context
                )

            return subtasks

        except Exception:
            # Fall back to linear planning on any failure
            return self._fallback_planner._default_decomposition(
                task_id, description, context
            )

    def _path_to_subtasks(
        self,
        path: list[ThoughtNode],
        task_id: uuid.UUID,
        context: dict[str, Any],
    ) -> list[SubTask]:
        """Convert a thought path into an ordered list of SubTasks.

        Each node in the path (except the root) becomes a SubTask.
        Dependencies are set linearly: each subtask depends on the previous one.

        Args:
            path: List of ThoughtNode instances from root to leaf.
            task_id: The parent task identifier.
            context: Additional context for metadata.

        Returns:
            List of SubTask instances with linear dependencies.
        """
        if len(path) <= 1:
            return []

        subtasks: list[SubTask] = []
        prev_id: uuid.UUID | None = None

        for node in path[1:]:  # Skip root node
            subtask = SubTask(
                description=node.content,
                dependencies=[prev_id] if prev_id else [],
                metadata={
                    "parent_task_id": str(task_id),
                    "context": context,
                    "thought_score": node.score,
                },
            )
            subtasks.append(subtask)
            prev_id = subtask.id

        return subtasks
