"""Tests for the Tree-of-Thought Reasoning Engine.

Validates ThoughtNode, ThoughtTree, and ToTPlanner classes including
tree expansion, evaluation, path selection, pruning, and fallback behavior.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from nexus.orchestration.reasoning import ThoughtNode, ThoughtTree, ToTPlanner
from nexus.orchestration.planner import SubTask


@pytest.fixture
def task_id():
    """Provide a fixed task UUID for tests."""
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def root_node():
    """Provide a root ThoughtNode for tree tests."""
    return ThoughtNode(
        content="Build a web application",
        depth=0,
        metadata={"context": "test"},
    )


@pytest.fixture
def tree(root_node):
    """Provide a ThoughtTree with a root node."""
    return ThoughtTree(root=root_node)


class TestThoughtNode:
    """Tests for ThoughtNode dataclass."""

    def test_creation_defaults(self):
        """Test that a ThoughtNode can be created with default values."""
        node = ThoughtNode()
        assert isinstance(node.id, uuid.UUID)
        assert node.content == ""
        assert node.parent_id is None
        assert node.children == []
        assert node.score == 0.0
        assert node.depth == 0
        assert node.metadata == {}

    def test_creation_with_values(self):
        """Test ThoughtNode creation with explicit values."""
        parent_id = uuid.uuid4()
        node = ThoughtNode(
            content="Test thought",
            parent_id=parent_id,
            score=0.85,
            depth=2,
            metadata={"key": "value"},
        )
        assert node.content == "Test thought"
        assert node.parent_id == parent_id
        assert node.score == 0.85
        assert node.depth == 2
        assert node.metadata == {"key": "value"}

    def test_children_list_independence(self):
        """Test that children lists are independent between instances."""
        node1 = ThoughtNode(content="Node 1")
        node2 = ThoughtNode(content="Node 2")
        child = ThoughtNode(content="Child")
        node1.children.append(child)
        assert len(node1.children) == 1
        assert len(node2.children) == 0

    def test_unique_ids(self):
        """Test that each ThoughtNode gets a unique ID."""
        nodes = [ThoughtNode() for _ in range(10)]
        ids = {n.id for n in nodes}
        assert len(ids) == 10


class TestThoughtTree:
    """Tests for ThoughtTree expansion, evaluation, and path selection."""

    async def test_expand_creates_children(self, tree, root_node):
        """Test that expand generates the expected number of child nodes."""
        llm_response = json.dumps(["Approach A", "Approach B", "Approach C"])
        mock_llm = AsyncMock(return_value=llm_response)

        children = await tree.expand(root_node, mock_llm, branching_factor=3)

        assert len(children) == 3
        assert children[0].content == "Approach A"
        assert children[1].content == "Approach B"
        assert children[2].content == "Approach C"
        assert all(c.parent_id == root_node.id for c in children)
        assert all(c.depth == 1 for c in children)
        assert len(root_node.children) == 3

    async def test_expand_respects_branching_factor(self, tree, root_node):
        """Test that expand limits children to the branching factor."""
        llm_response = json.dumps(["A", "B", "C", "D", "E"])
        mock_llm = AsyncMock(return_value=llm_response)

        children = await tree.expand(root_node, mock_llm, branching_factor=2)

        assert len(children) == 2
        assert children[0].content == "A"
        assert children[1].content == "B"

    async def test_expand_raises_on_invalid_response(self, tree, root_node):
        """Test that expand raises ValueError on non-array LLM output."""
        mock_llm = AsyncMock(return_value='"not an array"')

        with pytest.raises(ValueError, match="must be a JSON array"):
            await tree.expand(root_node, mock_llm)

    async def test_evaluate_scores_node(self, tree, root_node):
        """Test that evaluate assigns a score to the node."""
        mock_llm = AsyncMock(return_value="0.75")

        score = await tree.evaluate(root_node, mock_llm)

        assert score == 0.75
        assert root_node.score == 0.75

    async def test_evaluate_clamps_score(self, tree, root_node):
        """Test that evaluate clamps scores to [0.0, 1.0] range."""
        mock_llm = AsyncMock(return_value="1.5")
        score = await tree.evaluate(root_node, mock_llm)
        assert score == 1.0

        mock_llm_neg = AsyncMock(return_value="-0.3")
        score = await tree.evaluate(root_node, mock_llm_neg)
        assert score == 0.0

    def test_select_best_path_single_node(self, tree, root_node):
        """Test select_best_path with only a root node."""
        path = tree.select_best_path()
        assert path == [root_node]

    def test_select_best_path_with_children(self, root_node):
        """Test select_best_path selects highest-scoring path."""
        child_a = ThoughtNode(content="A", parent_id=root_node.id, depth=1, score=0.3)
        child_b = ThoughtNode(content="B", parent_id=root_node.id, depth=1, score=0.9)
        root_node.children = [child_a, child_b]
        root_node.score = 0.5

        tree = ThoughtTree(root=root_node)
        path = tree.select_best_path()

        assert len(path) == 2
        assert path[0] == root_node
        assert path[1] == child_b  # Higher score

    def test_select_best_path_deep_tree(self, root_node):
        """Test select_best_path navigates a multi-level tree."""
        root_node.score = 0.5

        child_a = ThoughtNode(content="A", parent_id=root_node.id, depth=1, score=0.8)
        child_b = ThoughtNode(content="B", parent_id=root_node.id, depth=1, score=0.3)

        grandchild_a1 = ThoughtNode(content="A1", parent_id=child_a.id, depth=2, score=0.9)
        grandchild_a2 = ThoughtNode(content="A2", parent_id=child_a.id, depth=2, score=0.1)

        child_a.children = [grandchild_a1, grandchild_a2]
        root_node.children = [child_a, child_b]

        tree = ThoughtTree(root=root_node)
        path = tree.select_best_path()

        # Best path: root (0.5) -> A (0.8) -> A1 (0.9) = 2.2 cumulative
        assert len(path) == 3
        assert path[0] == root_node
        assert path[1] == child_a
        assert path[2] == grandchild_a1

    def test_prune_removes_low_scoring_nodes(self, root_node):
        """Test that prune removes nodes below the threshold."""
        child_a = ThoughtNode(content="A", parent_id=root_node.id, depth=1, score=0.8)
        child_b = ThoughtNode(content="B", parent_id=root_node.id, depth=1, score=0.2)
        child_c = ThoughtNode(content="C", parent_id=root_node.id, depth=1, score=0.1)
        root_node.children = [child_a, child_b, child_c]

        tree = ThoughtTree(root=root_node)
        pruned = tree.prune(threshold=0.5)

        assert pruned == 2  # child_b and child_c removed
        assert len(root_node.children) == 1
        assert root_node.children[0] == child_a

    def test_prune_with_nested_children(self, root_node):
        """Test that prune counts nested children when removing branches."""
        child_a = ThoughtNode(content="A", parent_id=root_node.id, depth=1, score=0.2)
        grandchild = ThoughtNode(content="A1", parent_id=child_a.id, depth=2, score=0.9)
        child_a.children = [grandchild]
        root_node.children = [child_a]

        tree = ThoughtTree(root=root_node)
        pruned = tree.prune(threshold=0.5)

        # child_a (score 0.2) and its grandchild are both pruned
        assert pruned == 2
        assert len(root_node.children) == 0

    def test_prune_returns_zero_when_nothing_pruned(self, root_node):
        """Test prune returns 0 when all nodes are above threshold."""
        child = ThoughtNode(content="Good", parent_id=root_node.id, depth=1, score=0.9)
        root_node.children = [child]

        tree = ThoughtTree(root=root_node)
        pruned = tree.prune(threshold=0.1)
        assert pruned == 0
        assert len(root_node.children) == 1


class TestToTPlanner:
    """Tests for ToTPlanner task decomposition and fallback behavior."""

    async def test_successful_decomposition(self, task_id):
        """Test successful tree-based task decomposition."""
        expand_response = json.dumps(["Step 1: Research", "Step 2: Design", "Step 3: Implement"])
        eval_response = "0.8"

        call_count = {"n": 0}

        async def mock_llm(prompt: str) -> str:
            call_count["n"] += 1
            if "Generate exactly" in prompt:
                return expand_response
            if "Evaluate" in prompt:
                return eval_response
            return expand_response

        planner = ToTPlanner(
            llm_callable=mock_llm,
            branching_factor=3,
            max_depth=1,
            beam_width=2,
        )
        subtasks = await planner.decompose_task(task_id, "Build a web app")

        assert len(subtasks) > 0
        assert all(isinstance(st, SubTask) for st in subtasks)
        # Verify dependencies are linear
        for i, st in enumerate(subtasks):
            if i == 0:
                assert st.dependencies == []
            else:
                assert st.dependencies == [subtasks[i - 1].id]

    async def test_fallback_on_llm_failure(self, task_id):
        """Test fallback to linear planning when LLM raises exception."""
        mock_llm = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        planner = ToTPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(
            task_id, "A failing task", {"key": "val"}
        )

        # Should fall back to single-subtask default
        assert len(subtasks) == 1
        assert subtasks[0].description == "A failing task"

    async def test_fallback_on_invalid_json(self, task_id):
        """Test fallback when LLM returns invalid JSON during expansion."""
        mock_llm = AsyncMock(return_value="not valid json at all")

        planner = ToTPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(task_id, "Parse fail task")

        assert len(subtasks) == 1
        assert subtasks[0].description == "Parse fail task"

    def test_branching_factor_config(self):
        """Test that branching_factor is properly stored."""
        mock_llm = AsyncMock()
        planner = ToTPlanner(llm_callable=mock_llm, branching_factor=5)
        assert planner.branching_factor == 5

    def test_max_depth_config(self):
        """Test that max_depth is properly stored."""
        mock_llm = AsyncMock()
        planner = ToTPlanner(llm_callable=mock_llm, max_depth=7)
        assert planner.max_depth == 7

    def test_beam_width_config(self):
        """Test that beam_width is properly stored."""
        mock_llm = AsyncMock()
        planner = ToTPlanner(llm_callable=mock_llm, beam_width=4)
        assert planner.beam_width == 4

    def test_default_config(self):
        """Test default configuration values."""
        mock_llm = AsyncMock()
        planner = ToTPlanner(llm_callable=mock_llm)
        assert planner.branching_factor == 3
        assert planner.max_depth == 3
        assert planner.beam_width == 2

    async def test_decomposition_metadata(self, task_id):
        """Test that subtask metadata includes task_id and context."""
        expand_response = json.dumps(["Step A", "Step B"])
        eval_response = "0.7"

        async def mock_llm(prompt: str) -> str:
            if "Generate exactly" in prompt:
                return expand_response
            return eval_response

        planner = ToTPlanner(
            llm_callable=mock_llm,
            branching_factor=2,
            max_depth=1,
            beam_width=1,
        )
        subtasks = await planner.decompose_task(
            task_id, "Metadata test", {"env": "prod"}
        )

        assert len(subtasks) > 0
        for st in subtasks:
            assert "parent_task_id" in st.metadata
            assert st.metadata["parent_task_id"] == str(task_id)
            assert "thought_score" in st.metadata

    async def test_empty_tree_fallback(self, task_id):
        """Test fallback when tree expansion produces empty results."""
        # Return an empty array - should trigger fallback
        mock_llm = AsyncMock(return_value="[]")

        planner = ToTPlanner(llm_callable=mock_llm, max_depth=1)
        subtasks = await planner.decompose_task(task_id, "Empty tree task")

        # Fallback to linear planning
        assert len(subtasks) == 1
        assert subtasks[0].description == "Empty tree task"
