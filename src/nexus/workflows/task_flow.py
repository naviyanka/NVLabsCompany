"""Single Task Execution Flow - accept, execute, validate, and report.

Implements the complete lifecycle for executing a single task:
1. Accept task with metadata
2. Select appropriate agent (based on capabilities)
3. Select adapter (from agent configuration)
4. Configure session parameters
5. Execute via adapter
6. Validate result (post-execution evaluation)
7. Report outcome (persist and notify)

Integrates with governance at pre-execution:
- BudgetEnforcer: check_can_spend before committing resources
- ApprovalEngine: submit_for_approval for gated operations
- Kill switch: abort if system kill switch is active

Post-execution:
- Critic evaluation (success/failure determination)
- Result persistence (in-memory store)
- Notification via EventBus
- Error handling with retry/escalation
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol


class TaskStatus(str, Enum):
    """Lifecycle states for task execution.

    Values:
        PENDING: Task accepted but not started.
        SELECTING_AGENT: Finding appropriate agent.
        SELECTING_ADAPTER: Choosing execution adapter.
        CONFIGURING: Setting up session parameters.
        EXECUTING: Actively running.
        VALIDATING: Post-execution evaluation.
        COMPLETED: Successfully finished.
        FAILED: Failed after retries exhausted.
        ESCALATED: Reassigned to senior agent.
        BLOCKED: Waiting for approval or budget.
    """

    PENDING = "pending"
    SELECTING_AGENT = "selecting_agent"
    SELECTING_ADAPTER = "selecting_adapter"
    CONFIGURING = "configuring"
    EXECUTING = "executing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


@dataclass
class TaskExecution:
    """Record of a single task execution attempt.

    Attributes:
        execution_id: Unique identifier for this execution attempt.
        task_id: The task being executed.
        agent_id: Agent assigned to execute.
        adapter_type: Adapter used for execution.
        status: Current execution status.
        payload: Task payload/input data.
        result: Execution result data.
        cost_cents: Cost incurred.
        attempt: Retry attempt number (1-based).
        max_attempts: Maximum allowed attempts.
        started_at: When execution began.
        completed_at: When execution finished.
        error: Error message if failed.
        governance_checks: Record of pre-execution governance checks.
    """

    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    agent_id: str = ""
    adapter_type: str = ""
    status: TaskStatus = TaskStatus.PENDING
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    cost_cents: int = 0
    attempt: int = 1
    max_attempts: int = 3
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    governance_checks: dict[str, Any] = field(default_factory=dict)


class EventBusProtocol(Protocol):
    """Protocol for EventBus dependency."""

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


class AdapterRegistryProtocol(Protocol):
    """Protocol for AdapterRegistry dependency."""

    def create_adapter(
        self,
        adapter_type: str,
        config: dict[str, Any] | None = None,
    ) -> Any: ...

    def is_registered(self, adapter_type: str) -> bool: ...


class TaskFlow:
    """Manages single task execution with governance integration.

    Handles the complete task lifecycle from acceptance through execution
    to reporting. Integrates with budget, approval, and event systems
    to ensure governed, observable, and auditable execution.

    When an adapter_registry is provided, execution is wired through the
    registry to create real adapter instances. Without a registry, execution
    falls back to simulated results for demo/testing purposes.

    Features:
    - Agent selection based on required capabilities
    - Adapter selection from agent configuration
    - Pre-execution governance checks (budget, approval, kill switch)
    - Post-execution evaluation (critic)
    - Retry with escalation on repeated failures
    - Result persistence and notification

    Example usage:
        flow = TaskFlow(
            company_id="company-123",
            event_bus=event_bus,
            budget_enforcer=budget_enforcer,
            approval_engine=approval_engine,
            adapter_registry=registry,
        )
        execution = await flow.execute_task(
            task_id="task-1",
            payload={"objective": "Write unit tests"},
            required_capabilities=["code_generation"],
            estimated_cost_cents=50,
        )
    """

    def __init__(
        self,
        company_id: str,
        event_bus: EventBusProtocol | None = None,
        budget_enforcer: BudgetEnforcerProtocol | None = None,
        approval_engine: ApprovalEngineProtocol | None = None,
        kill_switch_active: bool = False,
        adapter_registry: AdapterRegistryProtocol | None = None,
    ) -> None:
        """Initialize the task flow manager.

        Args:
            company_id: Company scope for governance checks.
            event_bus: Optional EventBus for publishing events.
            budget_enforcer: Optional BudgetEnforcer for cost checking.
            approval_engine: Optional ApprovalEngine for approval gates.
            kill_switch_active: Whether the kill switch is engaged.
            adapter_registry: Optional AdapterRegistry for real adapter execution.
                If None, execution is simulated.
        """
        self.company_id = company_id
        self._event_bus = event_bus
        self._budget_enforcer = budget_enforcer
        self._approval_engine = approval_engine
        self._kill_switch_active = kill_switch_active
        self._adapter_registry = adapter_registry
        # In-memory stores
        self._executions: dict[str, TaskExecution] = {}
        self._results: dict[str, dict[str, Any]] = {}
        # Agent registry: agent_id -> {capabilities, adapter_type, config}
        self._agents: dict[str, dict[str, Any]] = {}

    def register_agent(
        self,
        agent_id: str,
        capabilities: list[str],
        adapter_type: str,
        config: dict[str, Any] | None = None,
        is_senior: bool = False,
    ) -> None:
        """Register an agent available for task execution.

        Args:
            agent_id: Unique agent identifier.
            capabilities: List of capabilities this agent provides.
            adapter_type: The adapter type to use for this agent.
            config: Optional adapter configuration.
            is_senior: Whether this is a senior agent (for escalation).
        """
        self._agents[agent_id] = {
            "agent_id": agent_id,
            "capabilities": capabilities,
            "adapter_type": adapter_type,
            "config": config or {},
            "is_senior": is_senior,
        }

    def set_kill_switch(self, active: bool) -> None:
        """Set the kill switch state.

        Args:
            active: Whether to activate (True) or deactivate (False) the kill switch.
        """
        self._kill_switch_active = active

    async def execute_task(
        self,
        task_id: str,
        payload: dict[str, Any],
        required_capabilities: list[str] | None = None,
        estimated_cost_cents: int = 0,
        approval_type: str | None = None,
        max_attempts: int = 3,
    ) -> TaskExecution:
        """Execute a task through the full lifecycle.

        Performs governance checks, selects an agent, executes via adapter,
        validates the result, and reports the outcome.

        Args:
            task_id: Unique task identifier.
            payload: Task input data.
            required_capabilities: Capabilities needed for this task.
            estimated_cost_cents: Estimated cost for budget checking.
            approval_type: If set, requires approval before execution.
            max_attempts: Maximum retry attempts before escalation.

        Returns:
            A TaskExecution record with the complete execution history.
        """
        execution = TaskExecution(
            task_id=task_id,
            payload=payload,
            max_attempts=max_attempts,
            started_at=datetime.now(timezone.utc),
        )
        self._executions[execution.execution_id] = execution

        # Pre-execution governance checks
        governance_result = await self._pre_execution_checks(
            execution, estimated_cost_cents, approval_type
        )
        if not governance_result:
            return execution

        # Select agent
        execution.status = TaskStatus.SELECTING_AGENT
        agent = self._select_agent(required_capabilities or [])
        if agent is None:
            execution.status = TaskStatus.FAILED
            execution.error = "No suitable agent found for required capabilities"
            execution.completed_at = datetime.now(timezone.utc)
            await self._emit_event(
                "agent_error",
                {
                    "task_id": task_id,
                    "error": execution.error,
                    "execution_id": execution.execution_id,
                },
            )
            return execution

        execution.agent_id = agent["agent_id"]
        execution.adapter_type = agent["adapter_type"]

        # Execute with retry
        for attempt in range(1, max_attempts + 1):
            execution.attempt = attempt
            execution.status = TaskStatus.EXECUTING

            await self._emit_event(
                "task_executing",
                {
                    "task_id": task_id,
                    "agent_id": execution.agent_id,
                    "adapter_type": execution.adapter_type,
                    "attempt": attempt,
                    "execution_id": execution.execution_id,
                },
            )

            # Execute (in real implementation, this calls the adapter)
            success, result = await self._do_execute(execution, agent)

            if success:
                # Validate result
                execution.status = TaskStatus.VALIDATING
                is_valid = self._validate_result(result)

                if is_valid:
                    execution.status = TaskStatus.COMPLETED
                    execution.result = result
                    execution.cost_cents = estimated_cost_cents
                    execution.completed_at = datetime.now(timezone.utc)

                    # Record cost
                    if self._budget_enforcer is not None and estimated_cost_cents > 0:
                        self._budget_enforcer.on_cost_event(
                            "company",
                            self._get_company_uuid(),
                            estimated_cost_cents,
                            f"Task {task_id} execution",
                        )

                    # Persist result
                    self._results[task_id] = result

                    # Notify
                    await self._emit_event(
                        "task_completed",
                        {
                            "task_id": task_id,
                            "execution_id": execution.execution_id,
                            "agent_id": execution.agent_id,
                            "cost_cents": estimated_cost_cents,
                        },
                    )
                    return execution
                else:
                    execution.error = "Result validation failed"
            else:
                execution.error = result.get("error", "Execution failed")

            # If not last attempt, continue to retry
            if attempt < max_attempts:
                await self._emit_event(
                    "task_retrying",
                    {
                        "task_id": task_id,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "error": execution.error,
                    },
                )

        # All retries exhausted - escalate
        execution.status = TaskStatus.ESCALATED
        execution.completed_at = datetime.now(timezone.utc)
        escalated_to = self._escalate(execution, required_capabilities or [])

        await self._emit_event(
            "task_escalated",
            {
                "task_id": task_id,
                "execution_id": execution.execution_id,
                "escalated_to": escalated_to,
                "attempts_exhausted": max_attempts,
                "last_error": execution.error,
            },
        )

        return execution

    async def _pre_execution_checks(
        self,
        execution: TaskExecution,
        estimated_cost_cents: int,
        approval_type: str | None,
    ) -> bool:
        """Run pre-execution governance checks.

        Args:
            execution: The execution record to update.
            estimated_cost_cents: Estimated cost for budget check.
            approval_type: Optional approval type to gate execution.

        Returns:
            True if all checks pass, False if blocked.
        """
        checks: dict[str, Any] = {}

        # Kill switch check
        if self._kill_switch_active:
            execution.status = TaskStatus.BLOCKED
            execution.error = "Kill switch is active - all execution halted"
            execution.completed_at = datetime.now(timezone.utc)
            checks["kill_switch"] = {"passed": False, "reason": "active"}
            execution.governance_checks = checks
            await self._emit_event(
                "agent_error",
                {
                    "task_id": execution.task_id,
                    "error": "Kill switch active",
                    "execution_id": execution.execution_id,
                },
            )
            return False
        checks["kill_switch"] = {"passed": True}

        # Budget check
        if self._budget_enforcer is not None and estimated_cost_cents > 0:
            budget_result = self._budget_enforcer.check_can_spend(
                "company",
                self._get_company_uuid(),
                estimated_cost_cents,
            )
            decision = getattr(budget_result, "decision", None)
            if decision is not None:
                decision_value = (
                    decision.value if hasattr(decision, "value") else str(decision)
                )
                if decision_value == "denied":
                    execution.status = TaskStatus.BLOCKED
                    execution.error = "Budget check failed - insufficient funds"
                    execution.completed_at = datetime.now(timezone.utc)
                    checks["budget"] = {
                        "passed": False,
                        "decision": decision_value,
                    }
                    execution.governance_checks = checks
                    await self._emit_event(
                        "budget_warning",
                        {
                            "task_id": execution.task_id,
                            "estimated_cost": estimated_cost_cents,
                            "decision": decision_value,
                        },
                    )
                    return False
                checks["budget"] = {"passed": True, "decision": decision_value}
            else:
                checks["budget"] = {"passed": True, "decision": "no_budget_set"}
        else:
            checks["budget"] = {"passed": True, "decision": "skipped"}

        # Approval check
        if self._approval_engine is not None and approval_type is not None:
            approval = await self._approval_engine.submit_for_approval(
                company_id=self._get_company_uuid(),
                approval_type=approval_type,
                requested_by_agent_id=uuid.uuid4(),
                payload={
                    "task_id": execution.task_id,
                    "estimated_cost_cents": estimated_cost_cents,
                },
            )
            approval_status = getattr(approval, "status", "pending")
            if approval_status == "denied":
                execution.status = TaskStatus.BLOCKED
                execution.error = "Approval denied"
                execution.completed_at = datetime.now(timezone.utc)
                checks["approval"] = {
                    "passed": False,
                    "status": approval_status,
                }
                execution.governance_checks = checks
                return False
            checks["approval"] = {"passed": True, "status": approval_status}
        else:
            checks["approval"] = {"passed": True, "status": "not_required"}

        execution.governance_checks = checks
        return True

    def _select_agent(
        self, required_capabilities: list[str]
    ) -> dict[str, Any] | None:
        """Select the best agent for the task based on capabilities.

        Args:
            required_capabilities: List of required capability strings.

        Returns:
            Agent configuration dict, or None if no match found.
        """
        if not self._agents:
            return None

        # If no capabilities required, return the first available agent
        if not required_capabilities:
            return next(iter(self._agents.values()))

        # Find agent that matches all required capabilities
        best_match: dict[str, Any] | None = None
        best_score = 0

        for agent in self._agents.values():
            agent_capabilities = set(agent.get("capabilities", []))
            required_set = set(required_capabilities)
            matched = len(agent_capabilities & required_set)
            if matched > best_score:
                best_score = matched
                best_match = agent

        return best_match

    async def _do_execute(
        self, execution: TaskExecution, agent: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        """Execute the task via the selected adapter.

        If an adapter_registry is available, creates a real adapter instance,
        establishes a session, and executes the task through it. Otherwise,
        falls back to simulated results for demo/testing purposes.

        Args:
            execution: The current execution record.
            agent: The selected agent configuration.

        Returns:
            Tuple of (success: bool, result: dict).
        """
        from nexus.temporal._sdk import LLM_TIMEOUT, ONCE_ONLY, execute_activity
        from nexus.temporal.activities import ExecuteTaskInput, execute_task_activity

        adapter_type = agent["adapter_type"]

        # No registry injected — keep the simulated result the façade always
        # returned for demo/testing, without paying for an activity dispatch.
        if self._adapter_registry is None:
            return True, {
                "task_id": execution.task_id,
                "agent_id": agent["agent_id"],
                "adapter_type": adapter_type,
                "output": f"Executed task {execution.task_id}",
                "status": "success",
            }

        # An adapter run bills, so it is dispatched once only.
        output = await execute_activity(
            execute_task_activity,
            ExecuteTaskInput(
                task_id=execution.task_id,
                agent_id=agent["agent_id"],
                adapter_type=adapter_type,
                payload=execution.payload,
                config=agent.get("config", {}),
            ),
            timeout=LLM_TIMEOUT,
            maximum_attempts=ONCE_ONLY,
        )

        result: dict[str, Any] = {
            "task_id": output.task_id,
            "agent_id": agent["agent_id"],
            "adapter_type": adapter_type,
            "output": output.output,
            "status": output.status,
            "cost_cents": output.cost_cents,
            "input_tokens": output.input_tokens,
            "output_tokens": output.output_tokens,
            "error": output.error,
        }
        return output.success, result

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

    def _validate_result(self, result: dict[str, Any]) -> bool:
        """Post-execution critic - validate the execution result.

        Performs basic validation that the result is well-formed
        and indicates success.

        Args:
            result: The execution result to validate.

        Returns:
            True if the result passes validation.
        """
        if not result:
            return False
        status = result.get("status", "")
        if status in ("success", "completed"):
            return True
        if result.get("output"):
            return True
        return False

    def _escalate(
        self, execution: TaskExecution, required_capabilities: list[str]
    ) -> str | None:
        """Escalate a failed task to a senior agent.

        Finds a senior agent with matching capabilities and reassigns.

        Args:
            execution: The failed execution record.
            required_capabilities: Capabilities needed.

        Returns:
            The senior agent_id if found, None otherwise.
        """
        for agent in self._agents.values():
            if not agent.get("is_senior"):
                continue
            if agent["agent_id"] == execution.agent_id:
                continue
            # Check capability overlap
            agent_caps = set(agent.get("capabilities", []))
            if not required_capabilities or agent_caps & set(required_capabilities):
                return agent["agent_id"]
        return None

    def _get_company_uuid(self) -> uuid.UUID:
        """Get the company ID as a UUID.

        Returns:
            The company_id as UUID, or a generated UUID if invalid.
        """
        try:
            return uuid.UUID(self.company_id)
        except (ValueError, AttributeError):
            return uuid.uuid4()

    async def _emit_event(
        self, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Emit an event via the EventBus if available.

        Args:
            event_type: Type of event to publish.
            payload: Event payload data.
        """
        if self._event_bus is not None:
            await self._event_bus.publish(
                event_type=event_type,
                payload=payload,
                source_agent_id=uuid.uuid4(),
                company_id=self._get_company_uuid(),
            )

    def get_execution(self, execution_id: str) -> TaskExecution | None:
        """Retrieve a task execution record.

        Args:
            execution_id: The execution identifier.

        Returns:
            The TaskExecution if found, None otherwise.
        """
        return self._executions.get(execution_id)

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve a persisted task result.

        Args:
            task_id: The task identifier.

        Returns:
            The result dictionary if found, None otherwise.
        """
        return self._results.get(task_id)

    def list_executions(
        self, status: TaskStatus | None = None
    ) -> list[TaskExecution]:
        """List all task executions with optional status filter.

        Args:
            status: Optional status filter.

        Returns:
            List of matching TaskExecution records.
        """
        results: list[TaskExecution] = []
        for execution in self._executions.values():
            if status is not None and execution.status != status:
                continue
            results.append(execution)
        return results
