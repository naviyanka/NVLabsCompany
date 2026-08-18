"""Company Workflow Orchestrator - full delegation chain from objective to delivery.

Implements the CEO -> CTO -> Engineers -> QA delegation pattern:
1. CEO receives a high-level objective and creates a strategy
2. CTO breaks the strategy into technical tasks
3. Engineers execute tasks via appropriate adapters
4. QA reviews and validates results

The workflow integrates with:
- ApprovalEngine: gates for high-risk actions (deployments, large spend)
- BudgetEnforcer: cost checking at each delegation step
- EventBus: event emission at each state transition
- AuditLogger: recording all workflow actions
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol


class WorkflowStatus(str, Enum):
    """Lifecycle states for workflow execution.

    Values:
        PENDING: Workflow created but not started.
        RUNNING: Actively executing steps.
        DELEGATING: Waiting on sub-task delegation.
        REVIEWING: In QA review phase.
        COMPLETED: Successfully finished.
        FAILED: Failed with errors.
        BLOCKED: Waiting for approval or budget.
    """

    PENDING = "pending"
    RUNNING = "running"
    DELEGATING = "delegating"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class WorkflowStep:
    """A single step in the delegation chain.

    Records who did what, when, and at what cost within the workflow.

    Attributes:
        step_id: Unique identifier for this step.
        agent_role: Role of the agent performing this step.
        action: Description of the action taken.
        status: Current step status.
        input_data: Data provided to this step.
        output_data: Data produced by this step.
        started_at: When execution began.
        completed_at: When execution finished.
        cost_cents: Cost incurred during this step.
        error: Error message if the step failed.
    """

    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_role: str = ""
    action: str = ""
    status: str = "pending"
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cost_cents: int = 0
    error: str | None = None


@dataclass
class WorkflowTrace:
    """Complete execution trace for a workflow.

    Captures the full delegation chain with all steps, timing,
    cost accumulation, and final status.

    Attributes:
        workflow_id: Unique identifier for this workflow execution.
        objective: The original high-level objective.
        steps: Ordered list of workflow steps.
        status: Current overall workflow status.
        total_cost_cents: Accumulated cost across all steps.
        started_at: When the workflow began.
        completed_at: When the workflow finished.
        company_id: Company scope for this workflow.
        metadata: Additional workflow metadata.
    """

    workflow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    objective: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.PENDING
    total_cost_cents: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    company_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class EventBusProtocol(Protocol):
    """Protocol for EventBus dependency (avoids hard import of sqlmodel-based code)."""

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        source_agent_id: Any = None,
        company_id: Any = None,
    ) -> Any: ...


class ApprovalEngineProtocol(Protocol):
    """Protocol for ApprovalEngine dependency."""

    async def submit_for_approval(
        self,
        company_id: Any,
        approval_type: str,
        requested_by_agent_id: Any,
        payload: dict[str, Any],
    ) -> Any: ...


class BudgetEnforcerProtocol(Protocol):
    """Protocol for BudgetEnforcer dependency."""

    def check_can_spend(
        self,
        scope_type: str,
        scope_id: Any,
        amount_cents: int,
    ) -> Any: ...

    def on_cost_event(
        self,
        scope_type: str,
        scope_id: Any,
        amount_cents: int,
        description: str,
    ) -> Any: ...


class CompanyWorkflow:
    """Orchestrates the full CEO -> CTO -> Engineers -> QA delegation chain.

    Given a high-level objective, the workflow:
    1. CEO creates a strategy (breaks objective into goals)
    2. CTO decomposes goals into technical tasks
    3. Engineers execute tasks using appropriate adapters
    4. QA reviews and validates all outputs

    Integrates with governance systems at each step:
    - Budget checks before committing resources
    - Approval gates for deployments and high-risk actions
    - Event emission for observability
    - Audit logging for accountability

    Example usage:
        workflow = CompanyWorkflow(
            company_id="company-123",
            event_bus=event_bus,
            approval_engine=approval_engine,
            budget_enforcer=budget_enforcer,
        )
        trace = await workflow.execute("Build a user authentication system")
    """

    def __init__(
        self,
        company_id: str,
        event_bus: EventBusProtocol | None = None,
        approval_engine: ApprovalEngineProtocol | None = None,
        budget_enforcer: BudgetEnforcerProtocol | None = None,
    ) -> None:
        """Initialize the company workflow orchestrator.

        Args:
            company_id: Company scope for this workflow.
            event_bus: Optional EventBus for publishing state transitions.
            approval_engine: Optional ApprovalEngine for gating high-risk actions.
            budget_enforcer: Optional BudgetEnforcer for cost checking.
        """
        self.company_id = company_id
        self._event_bus = event_bus
        self._approval_engine = approval_engine
        self._budget_enforcer = budget_enforcer
        self._traces: dict[str, WorkflowTrace] = {}

    async def execute(
        self,
        objective: str,
        estimated_cost_cents: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowTrace:
        """Execute the full delegation workflow for an objective.

        Runs through the CEO -> CTO -> Engineer -> QA pipeline,
        checking budgets and approvals at each transition.

        Args:
            objective: High-level objective to accomplish.
            estimated_cost_cents: Estimated total cost for budget checking.
            metadata: Optional metadata to attach to the trace.

        Returns:
            A WorkflowTrace capturing the complete execution history.
        """
        trace = WorkflowTrace(
            objective=objective,
            company_id=self.company_id,
            started_at=datetime.now(timezone.utc),
            status=WorkflowStatus.RUNNING,
            metadata=metadata or {},
        )
        self._traces[trace.workflow_id] = trace

        # Emit workflow started event
        await self._emit_event(
            "workflow_started",
            {"workflow_id": trace.workflow_id, "objective": objective},
        )

        try:
            # Step 1: CEO creates strategy
            strategy = await self._ceo_strategize(trace, objective)
            if trace.status == WorkflowStatus.FAILED:
                return trace

            # Step 2: CTO breaks strategy into tasks
            tasks = await self._cto_decompose(trace, strategy)
            if trace.status == WorkflowStatus.FAILED:
                return trace

            # Step 3: Engineers execute tasks
            results = await self._engineers_execute(
                trace, tasks, estimated_cost_cents
            )
            if trace.status == WorkflowStatus.FAILED:
                return trace

            # Step 4: QA reviews results
            await self._qa_review(trace, results)

            # Mark completed if QA passed
            if trace.status != WorkflowStatus.FAILED:
                trace.status = WorkflowStatus.COMPLETED
                trace.completed_at = datetime.now(timezone.utc)

            await self._emit_event(
                "workflow_completed",
                {
                    "workflow_id": trace.workflow_id,
                    "status": trace.status.value,
                    "total_cost_cents": trace.total_cost_cents,
                },
            )

        except Exception as exc:
            trace.status = WorkflowStatus.FAILED
            trace.completed_at = datetime.now(timezone.utc)
            await self._emit_event(
                "workflow_failed",
                {
                    "workflow_id": trace.workflow_id,
                    "error": str(exc),
                },
            )

        return trace

    async def _ceo_strategize(
        self, trace: WorkflowTrace, objective: str
    ) -> dict[str, Any]:
        """CEO phase: create strategy from objective.

        Args:
            trace: The workflow trace to update.
            objective: The high-level objective.

        Returns:
            Strategy dictionary with goals and priorities.
        """
        step = WorkflowStep(
            agent_role="ceo",
            action="create_strategy",
            status="running",
            input_data={"objective": objective},
            started_at=datetime.now(timezone.utc),
        )
        trace.steps.append(step)
        trace.status = WorkflowStatus.RUNNING

        await self._emit_event(
            "delegation_step",
            {
                "workflow_id": trace.workflow_id,
                "step_id": step.step_id,
                "role": "ceo",
                "action": "create_strategy",
            },
        )

        # CEO produces a strategy (in real execution, this would call an adapter)
        strategy = {
            "objective": objective,
            "goals": [
                {"id": "goal_1", "description": f"Implement core: {objective}"},
                {"id": "goal_2", "description": f"Test and validate: {objective}"},
            ],
            "priority": "high",
            "approach": "incremental",
        }

        step.output_data = strategy
        step.status = "completed"
        step.completed_at = datetime.now(timezone.utc)

        return strategy

    async def _cto_decompose(
        self, trace: WorkflowTrace, strategy: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """CTO phase: break strategy into technical tasks.

        Args:
            trace: The workflow trace to update.
            strategy: Strategy from the CEO phase.

        Returns:
            List of technical task specifications.
        """
        step = WorkflowStep(
            agent_role="cto",
            action="decompose_tasks",
            status="running",
            input_data={"strategy": strategy},
            started_at=datetime.now(timezone.utc),
        )
        trace.steps.append(step)
        trace.status = WorkflowStatus.DELEGATING

        await self._emit_event(
            "delegation_step",
            {
                "workflow_id": trace.workflow_id,
                "step_id": step.step_id,
                "role": "cto",
                "action": "decompose_tasks",
            },
        )

        # CTO decomposes goals into technical tasks
        tasks: list[dict[str, Any]] = []
        for goal in strategy.get("goals", []):
            task = {
                "task_id": str(uuid.uuid4()),
                "goal_id": goal.get("id", ""),
                "description": goal.get("description", ""),
                "required_capabilities": ["code_generation"],
                "estimated_cost_cents": 100,
                "priority": strategy.get("priority", "normal"),
            }
            tasks.append(task)

        step.output_data = {"tasks": tasks, "count": len(tasks)}
        step.status = "completed"
        step.completed_at = datetime.now(timezone.utc)

        return tasks

    async def _engineers_execute(
        self,
        trace: WorkflowTrace,
        tasks: list[dict[str, Any]],
        total_estimated_cost: int,
    ) -> list[dict[str, Any]]:
        """Engineer phase: execute technical tasks.

        Checks budget before each task and records costs.

        Args:
            trace: The workflow trace to update.
            tasks: List of task specifications from CTO.
            total_estimated_cost: Total estimated cost for budget check.

        Returns:
            List of execution results.
        """
        results: list[dict[str, Any]] = []

        for task in tasks:
            task_cost = task.get("estimated_cost_cents", 0)

            # Budget check before execution
            if self._budget_enforcer is not None:
                budget_result = self._budget_enforcer.check_can_spend(
                    "company",
                    uuid.UUID(self.company_id) if self._is_valid_uuid(self.company_id) else uuid.uuid4(),
                    task_cost,
                )
                # Check if denied (duck-type the decision field)
                decision = getattr(budget_result, "decision", None)
                if decision is not None:
                    decision_value = decision.value if hasattr(decision, "value") else str(decision)
                    if decision_value == "denied":
                        step = WorkflowStep(
                            agent_role="engineer",
                            action="execute_task",
                            status="failed",
                            input_data=task,
                            error="Budget denied",
                            started_at=datetime.now(timezone.utc),
                            completed_at=datetime.now(timezone.utc),
                        )
                        trace.steps.append(step)
                        trace.status = WorkflowStatus.BLOCKED
                        await self._emit_event(
                            "budget_warning",
                            {
                                "workflow_id": trace.workflow_id,
                                "task_id": task.get("task_id"),
                                "reason": "budget_denied",
                            },
                        )
                        return results

            # Approval check for deployment tasks
            if self._approval_engine is not None:
                task_desc = task.get("description", "").lower()
                if "deploy" in task_desc or task_cost > 1000:
                    approval = await self._approval_engine.submit_for_approval(
                        company_id=uuid.UUID(self.company_id) if self._is_valid_uuid(self.company_id) else uuid.uuid4(),
                        approval_type="deployment",
                        requested_by_agent_id=uuid.uuid4(),
                        payload={
                            "task_id": task.get("task_id"),
                            "description": task.get("description"),
                            "cost_cents": task_cost,
                        },
                    )
                    approval_status = getattr(approval, "status", "pending")
                    if approval_status == "denied":
                        step = WorkflowStep(
                            agent_role="engineer",
                            action="execute_task",
                            status="failed",
                            input_data=task,
                            error="Approval denied",
                            started_at=datetime.now(timezone.utc),
                            completed_at=datetime.now(timezone.utc),
                        )
                        trace.steps.append(step)
                        trace.status = WorkflowStatus.BLOCKED
                        return results

            # Execute the task
            step = WorkflowStep(
                agent_role="engineer",
                action="execute_task",
                status="running",
                input_data=task,
                started_at=datetime.now(timezone.utc),
            )
            trace.steps.append(step)

            await self._emit_event(
                "delegation_step",
                {
                    "workflow_id": trace.workflow_id,
                    "step_id": step.step_id,
                    "role": "engineer",
                    "action": "execute_task",
                    "task_id": task.get("task_id"),
                },
            )

            # Simulate execution result
            result = {
                "task_id": task.get("task_id"),
                "status": "completed",
                "output": f"Completed: {task.get('description', '')}",
                "cost_cents": task_cost,
            }
            results.append(result)

            step.output_data = result
            step.status = "completed"
            step.cost_cents = task_cost
            step.completed_at = datetime.now(timezone.utc)
            trace.total_cost_cents += task_cost

            # Record cost event
            if self._budget_enforcer is not None:
                self._budget_enforcer.on_cost_event(
                    "company",
                    uuid.UUID(self.company_id) if self._is_valid_uuid(self.company_id) else uuid.uuid4(),
                    task_cost,
                    f"Task execution: {task.get('task_id', '')}",
                )

        return results

    async def _qa_review(
        self, trace: WorkflowTrace, results: list[dict[str, Any]]
    ) -> None:
        """QA phase: review and validate execution results.

        Args:
            trace: The workflow trace to update.
            results: List of execution results to review.
        """
        step = WorkflowStep(
            agent_role="qa",
            action="review_results",
            status="running",
            input_data={"results": results, "count": len(results)},
            started_at=datetime.now(timezone.utc),
        )
        trace.steps.append(step)
        trace.status = WorkflowStatus.REVIEWING

        await self._emit_event(
            "delegation_step",
            {
                "workflow_id": trace.workflow_id,
                "step_id": step.step_id,
                "role": "qa",
                "action": "review_results",
            },
        )

        # QA validates results - check for failures
        failed_tasks = [r for r in results if r.get("status") != "completed"]

        if failed_tasks:
            step.status = "failed"
            step.error = f"{len(failed_tasks)} tasks failed review"
            step.output_data = {"passed": False, "failed_count": len(failed_tasks)}
            trace.status = WorkflowStatus.FAILED
        else:
            step.status = "completed"
            step.output_data = {
                "passed": True,
                "reviewed_count": len(results),
                "verdict": "All tasks completed successfully",
            }

        step.completed_at = datetime.now(timezone.utc)

    async def _emit_event(
        self, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Emit an event via the EventBus if available.

        Args:
            event_type: Type of event to publish.
            payload: Event payload data.
        """
        if self._event_bus is not None:
            company_uuid = (
                uuid.UUID(self.company_id)
                if self._is_valid_uuid(self.company_id)
                else uuid.uuid4()
            )
            await self._event_bus.publish(
                event_type=event_type,
                payload=payload,
                source_agent_id=uuid.uuid4(),
                company_id=company_uuid,
            )

    @staticmethod
    def _is_valid_uuid(value: str) -> bool:
        """Check if a string is a valid UUID.

        Args:
            value: String to validate.

        Returns:
            True if the string is a valid UUID.
        """
        try:
            uuid.UUID(value)
            return True
        except (ValueError, AttributeError):
            return False

    def get_trace(self, workflow_id: str) -> WorkflowTrace | None:
        """Retrieve a workflow trace by ID.

        Args:
            workflow_id: The workflow identifier.

        Returns:
            The WorkflowTrace if found, None otherwise.
        """
        return self._traces.get(workflow_id)

    def list_traces(self) -> list[WorkflowTrace]:
        """List all workflow traces for this company.

        Returns:
            List of WorkflowTrace objects.
        """
        return list(self._traces.values())
