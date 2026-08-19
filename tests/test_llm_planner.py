"""Tests for the LLM-enhanced Task Planner module.

Validates LLMTaskPlanner decomposition using mocked LLM callables,
including fallback behavior, max_subtasks limits, and DAG validation.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from nexus.orchestration.llm_planner import LLMTaskPlanner
from nexus.orchestration.planner import SubTask


@pytest.fixture
def task_id():
    """Provide a fixed task UUID for tests."""
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


class TestLLMTaskPlannerDecomposition:
    """Tests for LLMTaskPlanner.decompose_task() with mocked LLM."""

    async def test_successful_decomposition(self, task_id):
        """Test successful decomposition with valid LLM JSON response."""
        llm_response = json.dumps([
            {"description": "Research requirements", "dependencies": []},
            {"description": "Design solution", "dependencies": [0]},
            {"description": "Implement solution", "dependencies": [1]},
            {"description": "Write tests", "dependencies": [2]},
        ])
        mock_llm = AsyncMock(return_value=llm_response)

        planner = LLMTaskPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(
            task_id, "Build a web application", {"framework": "FastAPI"}
        )

        assert len(subtasks) == 4
        assert subtasks[0].description == "Research requirements"
        assert subtasks[1].description == "Design solution"
        assert subtasks[2].description == "Implement solution"
        assert subtasks[3].description == "Write tests"

        # Verify dependencies are properly mapped
        assert subtasks[0].dependencies == []
        assert subtasks[1].dependencies == [subtasks[0].id]
        assert subtasks[2].dependencies == [subtasks[1].id]
        assert subtasks[3].dependencies == [subtasks[2].id]

        # Verify all subtasks have UUIDs
        for st in subtasks:
            assert isinstance(st.id, uuid.UUID)

        # Verify LLM was called
        mock_llm.assert_called_once()

    async def test_fallback_on_invalid_json(self, task_id):
        """Test fallback to default decomposition when LLM returns invalid JSON."""
        mock_llm = AsyncMock(return_value="This is not valid JSON at all")

        planner = LLMTaskPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(
            task_id, "Build a web application"
        )

        # Should fall back to default single-subtask decomposition
        assert len(subtasks) == 1
        assert subtasks[0].description == "Build a web application"

    async def test_fallback_on_exception(self, task_id):
        """Test fallback when LLM callable raises an exception."""
        mock_llm = AsyncMock(side_effect=RuntimeError("LLM service unavailable"))

        planner = LLMTaskPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(
            task_id, "Build a web application"
        )

        # Should fall back to default single-subtask decomposition
        assert len(subtasks) == 1
        assert subtasks[0].description == "Build a web application"

    async def test_max_subtasks_limit(self, task_id):
        """Test that max_subtasks limit is respected."""
        # Generate 15 subtasks in the LLM response
        llm_data = [
            {"description": f"Step {i}", "dependencies": []}
            for i in range(15)
        ]
        mock_llm = AsyncMock(return_value=json.dumps(llm_data))

        planner = LLMTaskPlanner(llm_callable=mock_llm, max_subtasks=5)
        subtasks = await planner.decompose_task(
            task_id, "Complex task with many steps"
        )

        assert len(subtasks) <= 5

    async def test_fallback_on_cyclic_dependencies(self, task_id):
        """Test fallback when LLM output has cyclic dependencies."""
        # Create a cycle: 0 depends on 2, 1 depends on 0, 2 depends on 1
        llm_response = json.dumps([
            {"description": "Step A", "dependencies": [2]},
            {"description": "Step B", "dependencies": [0]},
            {"description": "Step C", "dependencies": [1]},
        ])
        mock_llm = AsyncMock(return_value=llm_response)

        planner = LLMTaskPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(
            task_id, "Task with circular dependencies"
        )

        # Should fall back to default decomposition due to cycle
        assert len(subtasks) == 1
        assert subtasks[0].description == "Task with circular dependencies"

    async def test_custom_prompt_template(self, task_id):
        """Test that a custom prompt template is used."""
        custom_template = "Custom: {task_description} | Context: {context}"
        llm_response = json.dumps([
            {"description": "Only step", "dependencies": []}
        ])
        mock_llm = AsyncMock(return_value=llm_response)

        planner = LLMTaskPlanner(
            llm_callable=mock_llm, prompt_template=custom_template
        )
        await planner.decompose_task(
            task_id, "Test task", {"key": "value"}
        )

        # Verify the custom template was used
        call_args = mock_llm.call_args[0][0]
        assert call_args.startswith("Custom: Test task")
        assert '"key": "value"' in call_args

    async def test_fallback_on_empty_array(self, task_id):
        """Test fallback when LLM returns an empty array."""
        mock_llm = AsyncMock(return_value="[]")

        planner = LLMTaskPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(
            task_id, "Some task"
        )

        # Should fall back to default decomposition
        assert len(subtasks) == 1
        assert subtasks[0].description == "Some task"

    async def test_fallback_on_non_array_json(self, task_id):
        """Test fallback when LLM returns valid JSON but not an array."""
        mock_llm = AsyncMock(return_value='{"description": "not an array"}')

        planner = LLMTaskPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(
            task_id, "Some task"
        )

        # Should fall back to default decomposition
        assert len(subtasks) == 1
        assert subtasks[0].description == "Some task"

    async def test_multiple_dependencies(self, task_id):
        """Test subtask with multiple dependencies."""
        llm_response = json.dumps([
            {"description": "Step A", "dependencies": []},
            {"description": "Step B", "dependencies": []},
            {"description": "Step C", "dependencies": [0, 1]},
        ])
        mock_llm = AsyncMock(return_value=llm_response)

        planner = LLMTaskPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(
            task_id, "Parallel then merge"
        )

        assert len(subtasks) == 3
        assert subtasks[2].dependencies == [subtasks[0].id, subtasks[1].id]

    async def test_metadata_contains_parent_task_id(self, task_id):
        """Test that subtask metadata includes the parent task_id."""
        llm_response = json.dumps([
            {"description": "A step", "dependencies": []}
        ])
        mock_llm = AsyncMock(return_value=llm_response)

        planner = LLMTaskPlanner(llm_callable=mock_llm)
        subtasks = await planner.decompose_task(task_id, "Test task")

        assert subtasks[0].metadata["parent_task_id"] == str(task_id)
