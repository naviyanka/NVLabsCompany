"""Tests for NEXUS Workflow Integration - delegation chain logic, task flow.

Tests cover:
- CompanyWorkflow creation and execution
- Full delegation chain (CEO -> CTO -> Engineer -> QA)
- WorkflowTrace recording of all steps
- Event emission at state transitions
- Budget checking at each step
- TaskFlow acceptance and execution
- Agent selection by capability
- Governance pre-checks (budget denied, kill switch, approval)
- Retry on failure with escalation
- Result persistence and event notification
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.workflows.company_flow import (
    CompanyWorkflow,
    WorkflowStatus,
    WorkflowStep,
    WorkflowTrace,
)
from nexus.workflows.task_flow import (
    TaskFlow,
    TaskExecution,
    TaskStatus,
)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class TestCompanyWorkflow:
    """Test CompanyWorkflow delegation chain and trace recording."""

    @pytest.fixture
    def company_id(self):
        """Valid company UUID string."""
        return str(uuid.UUID("12345678-1234-1234-1234-123456789abc"))

    @pytest.fixture
    def event_bus(self):
        """Mock event bus that records published events."""
        bus = MagicMock()
        bus.published_events = []

        async def capture_publish(event_type, payload=None, source_agent_id=None, company_id=None):
            bus.published_events.append({
                "event_type": event_type,
                "payload": payload,
            })

        bus.publish = capture_publish
        return bus

    @pytest.fixture
    def budget_enforcer(self):
        """Mock budget enforcer that allows spending."""
        enforcer = MagicMock()
        result = MagicMock()
        result.decision = MagicMock()
        result.decision.value = "allowed"
        enforcer.check_can_spend = MagicMock(return_value=result)
        enforcer.on_cost_event = MagicMock()
        return enforcer

    def test_workflow_creation_with_objective(self, company_id):
        """CompanyWorkflow initializes with company_id."""
        workflow = CompanyWorkflow(company_id=company_id)

        assert workflow.company_id == company_id

    def test_full_delegation_chain(self, company_id, event_bus):
        """execute runs CEO -> CTO -> Engineer -> QA and completes."""
        workflow = CompanyWorkflow(
            company_id=company_id,
            event_bus=event_bus,
        )

        trace = _run(workflow.execute("Build a user auth system"))

        assert isinstance(trace, WorkflowTrace)
        assert trace.status == WorkflowStatus.COMPLETED
        assert trace.objective == "Build a user auth system"
        assert trace.completed_at is not None
        assert trace.started_at is not None

    def test_strategy_step_for_ceo(self, company_id):
        """First step in trace is CEO creating strategy."""
        workflow = CompanyWorkflow(company_id=company_id)

        trace = _run(workflow.execute("Design a system"))

        ceo_steps = [s for s in trace.steps if s.agent_role == "ceo"]
        assert len(ceo_steps) >= 1
        assert ceo_steps[0].action == "create_strategy"
        assert ceo_steps[0].status == "completed"
        assert "objective" in ceo_steps[0].input_data

    def test_task_breakdown_for_cto(self, company_id):
        """Second step in trace is CTO decomposing tasks."""
        workflow = CompanyWorkflow(company_id=company_id)

        trace = _run(workflow.execute("Implement feature"))

        cto_steps = [s for s in trace.steps if s.agent_role == "cto"]
        assert len(cto_steps) >= 1
        assert cto_steps[0].action == "decompose_tasks"
        assert cto_steps[0].status == "completed"
        assert "tasks" in cto_steps[0].output_data

    def test_execution_delegation_to_engineer(self, company_id):
        """Engineer steps execute tasks from CTO decomposition."""
        workflow = CompanyWorkflow(company_id=company_id)

        trace = _run(workflow.execute("Build module"))

        engineer_steps = [s for s in trace.steps if s.agent_role == "engineer"]
        assert len(engineer_steps) >= 1
        for step in engineer_steps:
            assert step.action == "execute_task"
            assert step.status == "completed"

    def test_qa_review_step(self, company_id):
        """QA step reviews execution results."""
        workflow = CompanyWorkflow(company_id=company_id)

        trace = _run(workflow.execute("Complete feature"))

        qa_steps = [s for s in trace.steps if s.agent_role == "qa"]
        assert len(qa_steps) == 1
        assert qa_steps[0].action == "review_results"
        assert qa_steps[0].status == "completed"
        assert qa_steps[0].output_data.get("passed") is True

    def test_full_trace_recording(self, company_id):
        """WorkflowTrace records all steps with timing and cost."""
        workflow = CompanyWorkflow(company_id=company_id)

        trace = _run(workflow.execute("Full test", estimated_cost_cents=200))

        # Should have CEO + CTO + engineer(s) + QA steps
        assert len(trace.steps) >= 4
        roles_seen = {s.agent_role for s in trace.steps}
        assert "ceo" in roles_seen
        assert "cto" in roles_seen
        assert "engineer" in roles_seen
        assert "qa" in roles_seen
        assert trace.total_cost_cents >= 0

    def test_budget_check_at_each_step(self, company_id, budget_enforcer):
        """Budget enforcer is called during engineer execution."""
        workflow = CompanyWorkflow(
            company_id=company_id,
            budget_enforcer=budget_enforcer,
        )

        trace = _run(workflow.execute("Test budget", estimated_cost_cents=100))

        assert trace.status == WorkflowStatus.COMPLETED
        # Budget enforcer should be called for each engineer task
        assert budget_enforcer.check_can_spend.called

    def test_budget_denied_blocks_engineer_step(self, company_id):
        """Budget denied causes engineer step to fail and records the denial."""
        denied_enforcer = MagicMock()
        result = MagicMock()
        result.decision = MagicMock()
        result.decision.value = "denied"
        denied_enforcer.check_can_spend = MagicMock(return_value=result)
        denied_enforcer.on_cost_event = MagicMock()

        workflow = CompanyWorkflow(
            company_id=company_id,
            budget_enforcer=denied_enforcer,
        )

        trace = _run(workflow.execute("Expensive task", estimated_cost_cents=50000))

        # Budget denied creates a failed engineer step
        engineer_steps = [s for s in trace.steps if s.agent_role == "engineer"]
        assert len(engineer_steps) >= 1
        denied_step = [s for s in engineer_steps if s.status == "failed"]
        assert len(denied_step) >= 1
        assert "Budget denied" in (denied_step[0].error or "")
        # No cost should be accumulated for denied tasks
        assert trace.total_cost_cents == 0

    def test_event_emission_at_state_transitions(self, company_id, event_bus):
        """Events are emitted at workflow start, steps, and completion."""
        workflow = CompanyWorkflow(
            company_id=company_id,
            event_bus=event_bus,
        )

        _run(workflow.execute("Observable task"))

        # Should have workflow_started, delegation_step(s), workflow_completed
        event_types = [e["event_type"] for e in event_bus.published_events]
        assert "workflow_started" in event_types
        assert "delegation_step" in event_types
        assert "workflow_completed" in event_types

    def test_workflow_trace_stored(self, company_id):
        """Executed workflow trace is retrievable via get_trace."""
        workflow = CompanyWorkflow(company_id=company_id)

        trace = _run(workflow.execute("Stored workflow"))

        retrieved = workflow.get_trace(trace.workflow_id)
        assert retrieved is not None
        assert retrieved.workflow_id == trace.workflow_id

    def test_metadata_attached_to_trace(self, company_id):
        """Custom metadata is attached to the WorkflowTrace."""
        workflow = CompanyWorkflow(company_id=company_id)

        trace = _run(workflow.execute(
            "Meta test",
            metadata={"custom_key": "custom_value"},
        ))

        assert trace.metadata.get("custom_key") == "custom_value"


class TestTaskFlow:
    """Test TaskFlow single task execution with governance."""

    @pytest.fixture
    def company_id(self):
        """Valid company UUID string."""
        return str(uuid.UUID("12345678-1234-1234-1234-123456789abc"))

    @pytest.fixture
    def event_bus(self):
        """Mock event bus."""
        bus = MagicMock()
        bus.published_events = []

        async def capture_publish(event_type, payload=None, source_agent_id=None, company_id=None):
            bus.published_events.append({
                "event_type": event_type,
                "payload": payload,
            })

        bus.publish = capture_publish
        return bus

    @pytest.fixture
    def task_flow(self, company_id, event_bus):
        """Create a TaskFlow with a registered agent."""
        flow = TaskFlow(
            company_id=company_id,
            event_bus=event_bus,
        )
        flow.register_agent(
            agent_id="engineer-1",
            capabilities=["code_generation", "testing"],
            adapter_type="openai",
            config={"api_key": "test", "model": "gpt-4o"},
        )
        return flow

    def test_task_acceptance(self, task_flow):
        """execute_task creates a TaskExecution record."""
        execution = _run(task_flow.execute_task(
            task_id="task-1",
            payload={"objective": "Write tests"},
        ))

        assert isinstance(execution, TaskExecution)
        assert execution.task_id == "task-1"
        assert execution.started_at is not None

    def test_agent_selection(self, task_flow):
        """TaskFlow selects an agent matching required capabilities."""
        execution = _run(task_flow.execute_task(
            task_id="task-2",
            payload={"objective": "Generate code"},
            required_capabilities=["code_generation"],
        ))

        assert execution.agent_id == "engineer-1"
        assert execution.adapter_type == "openai"

    def test_no_agent_available(self, company_id, event_bus):
        """TaskFlow fails if no agent matches capabilities."""
        flow = TaskFlow(company_id=company_id, event_bus=event_bus)
        # No agents registered

        execution = _run(flow.execute_task(
            task_id="task-no-agent",
            payload={"objective": "Do impossible thing"},
            required_capabilities=["nonexistent_capability"],
        ))

        assert execution.status == TaskStatus.FAILED
        assert "No suitable agent" in (execution.error or "")

    def test_successful_execution_completes(self, task_flow):
        """Successful execution sets status to COMPLETED."""
        execution = _run(task_flow.execute_task(
            task_id="task-success",
            payload={"objective": "Simple task"},
        ))

        assert execution.status == TaskStatus.COMPLETED
        assert execution.completed_at is not None

    def test_budget_denied_blocks_execution(self, company_id, event_bus):
        """Budget denied blocks task execution."""
        denied_enforcer = MagicMock()
        result = MagicMock()
        result.decision = MagicMock()
        result.decision.value = "denied"
        denied_enforcer.check_can_spend = MagicMock(return_value=result)
        denied_enforcer.on_cost_event = MagicMock()

        flow = TaskFlow(
            company_id=company_id,
            event_bus=event_bus,
            budget_enforcer=denied_enforcer,
        )
        flow.register_agent(
            agent_id="engineer-1",
            capabilities=["code_generation"],
            adapter_type="openai",
        )

        execution = _run(flow.execute_task(
            task_id="task-denied",
            payload={"objective": "Expensive task"},
            estimated_cost_cents=50000,
        ))

        assert execution.status == TaskStatus.BLOCKED
        assert "Budget" in (execution.error or "")

    def test_kill_switch_stops_execution(self, company_id, event_bus):
        """Active kill switch prevents task execution."""
        flow = TaskFlow(
            company_id=company_id,
            event_bus=event_bus,
            kill_switch_active=True,
        )
        flow.register_agent(
            agent_id="engineer-1",
            capabilities=["code_generation"],
            adapter_type="openai",
        )

        execution = _run(flow.execute_task(
            task_id="task-killed",
            payload={"objective": "Halted task"},
        ))

        assert execution.status == TaskStatus.BLOCKED
        assert "Kill switch" in (execution.error or "")

    def test_approval_denied_blocks(self, company_id, event_bus):
        """Denied approval blocks task execution."""
        approval_engine = MagicMock()
        approval_result = MagicMock()
        approval_result.status = "denied"

        async def mock_submit(*args, **kwargs):
            return approval_result

        approval_engine.submit_for_approval = mock_submit

        flow = TaskFlow(
            company_id=company_id,
            event_bus=event_bus,
            approval_engine=approval_engine,
        )
        flow.register_agent(
            agent_id="engineer-1",
            capabilities=["code_generation"],
            adapter_type="openai",
        )

        execution = _run(flow.execute_task(
            task_id="task-approval",
            payload={"objective": "Needs approval"},
            approval_type="deployment",
        ))

        assert execution.status == TaskStatus.BLOCKED
        assert "Approval denied" in (execution.error or "")

    def test_result_persistence(self, task_flow):
        """Successful task result is persisted for retrieval."""
        _run(task_flow.execute_task(
            task_id="task-persist",
            payload={"objective": "Persist me"},
        ))

        result = task_flow.get_result("task-persist")
        assert result is not None
        assert result["status"] == "success"

    def test_event_notification_on_completion(self, task_flow, event_bus):
        """Events are emitted during task execution lifecycle."""
        _run(task_flow.execute_task(
            task_id="task-events",
            payload={"objective": "Emit events"},
        ))

        event_types = [e["event_type"] for e in event_bus.published_events]
        assert "task_executing" in event_types
        assert "task_completed" in event_types

    def test_escalation_after_max_retries(self, company_id, event_bus):
        """Task is escalated after max retries are exhausted."""
        flow = TaskFlow(company_id=company_id, event_bus=event_bus)
        flow.register_agent(
            agent_id="junior-1",
            capabilities=["code_generation"],
            adapter_type="openai",
            is_senior=False,
        )
        flow.register_agent(
            agent_id="senior-1",
            capabilities=["code_generation"],
            adapter_type="anthropic",
            is_senior=True,
        )

        # Override _do_execute to always fail
        async def always_fail(execution, agent):
            return False, {"error": "simulated failure", "status": "failed"}

        flow._do_execute = always_fail  # type: ignore

        execution = _run(flow.execute_task(
            task_id="task-escalate",
            payload={"objective": "Failing task"},
            required_capabilities=["code_generation"],
            max_attempts=2,
        ))

        assert execution.status == TaskStatus.ESCALATED
        # Event for escalation should be emitted
        event_types = [e["event_type"] for e in event_bus.published_events]
        assert "task_escalated" in event_types

    def test_retry_on_failure(self, company_id, event_bus):
        """Task retries up to max_attempts before escalation."""
        flow = TaskFlow(company_id=company_id, event_bus=event_bus)
        flow.register_agent(
            agent_id="agent-retry",
            capabilities=["code_generation"],
            adapter_type="openai",
        )

        call_count = {"n": 0}

        async def fail_then_succeed(execution, agent):
            call_count["n"] += 1
            if call_count["n"] < 3:
                return False, {"error": "temporary failure", "status": "failed"}
            return True, {
                "task_id": execution.task_id,
                "agent_id": agent["agent_id"],
                "adapter_type": agent["adapter_type"],
                "output": "Success on retry",
                "status": "success",
            }

        flow._do_execute = fail_then_succeed  # type: ignore

        execution = _run(flow.execute_task(
            task_id="task-retry",
            payload={"objective": "Retry me"},
            max_attempts=3,
        ))

        assert execution.status == TaskStatus.COMPLETED
        assert call_count["n"] == 3

    def test_governance_checks_recorded(self, task_flow):
        """Governance check results are recorded in execution."""
        execution = _run(task_flow.execute_task(
            task_id="task-gov",
            payload={"objective": "Governed task"},
        ))

        checks = execution.governance_checks
        assert "kill_switch" in checks
        assert checks["kill_switch"]["passed"] is True

    def test_set_kill_switch(self, company_id, event_bus):
        """set_kill_switch dynamically controls execution blocking."""
        flow = TaskFlow(company_id=company_id, event_bus=event_bus)
        flow.register_agent(
            agent_id="agent-1",
            capabilities=["code_generation"],
            adapter_type="openai",
        )

        # Initially not active
        execution1 = _run(flow.execute_task(
            task_id="task-before-kill",
            payload={"objective": "Before kill"},
        ))
        assert execution1.status == TaskStatus.COMPLETED

        # Activate kill switch
        flow.set_kill_switch(True)
        execution2 = _run(flow.execute_task(
            task_id="task-after-kill",
            payload={"objective": "After kill"},
        ))
        assert execution2.status == TaskStatus.BLOCKED

    def test_list_executions(self, task_flow):
        """list_executions returns all recorded executions."""
        _run(task_flow.execute_task(task_id="t1", payload={"obj": "one"}))
        _run(task_flow.execute_task(task_id="t2", payload={"obj": "two"}))

        executions = task_flow.list_executions()
        assert len(executions) == 2

    def test_list_executions_filter_by_status(self, task_flow):
        """list_executions can filter by status."""
        _run(task_flow.execute_task(task_id="t-filter", payload={"obj": "test"}))

        completed = task_flow.list_executions(status=TaskStatus.COMPLETED)
        failed = task_flow.list_executions(status=TaskStatus.FAILED)

        assert len(completed) >= 1
        assert len(failed) == 0
