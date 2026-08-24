"""Task Executor - orchestrates task execution with budget checks and retry logic."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.budget import CostEvent
from nexus.models.task import Task
from nexus.runtime.adapter import AgentAdapter, AgentSession, TaskResult

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when a task execution would exceed budget limits."""

    def __init__(self, agent_id: uuid.UUID, required: int, available: int) -> None:
        self.agent_id = agent_id
        self.required = required
        self.available = available
        super().__init__(
            f"Agent {agent_id} budget exceeded: "
            f"required={required}, available={available}"
        )


class TaskExecutionError(Exception):
    """Raised when task execution fails after all retries."""

    def __init__(
        self, task_id: uuid.UUID, attempts: int, last_error: str
    ) -> None:
        self.task_id = task_id
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Task {task_id} failed after {attempts} attempts: {last_error}"
        )


class TaskExecutor:
    """Executes tasks through agent adapters with budget enforcement and retries.

    Responsibilities:
    - Check budget before execution
    - Validate agent permissions
    - Run task through the adapter
    - Record cost events
    - Update task status
    - Retry on transient failures
    """

    def __init__(
        self,
        db: AsyncSession,
        adapter: AgentAdapter,
        max_retries: int = 3,
    ) -> None:
        self._db = db
        self._adapter = adapter
        self._max_retries = max_retries

    async def _check_budget(
        self, agent_id: uuid.UUID, company_id: uuid.UUID
    ) -> bool:
        """Check if the agent has remaining budget for execution.

        Args:
            agent_id: The agent whose budget to check.
            company_id: The company for budget policy lookup.

        Returns:
            True if budget is available.

        Raises:
            BudgetExceededError: If budget would be exceeded.
        """
        from nexus.models.agent import Agent

        stmt = select(Agent).where(Agent.id == agent_id)
        result = await self._db.execute(stmt)
        agent = result.scalar_one_or_none()

        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")

        # Check agent-level budget
        if agent.budget_monthly_cents > 0:
            available = agent.budget_monthly_cents - agent.spent_monthly_cents
            if available <= 0:
                raise BudgetExceededError(agent_id, 1, available)

        return True

    async def _validate_permissions(
        self, agent_id: uuid.UUID, task: Task
    ) -> bool:
        """Validate that the agent has permission to execute this task.

        Args:
            agent_id: The agent attempting execution.
            task: The task to execute.

        Returns:
            True if the agent is permitted.
        """
        # Basic validation: agent must be assigned to the task
        if task.assigned_agent_id and task.assigned_agent_id != agent_id:
            return False
        return True

    async def _record_cost(
        self,
        result: TaskResult,
        company_id: uuid.UUID,
        task: Task,
    ) -> None:
        """Record the cost event from task execution.

        Args:
            result: The task execution result containing cost info.
            company_id: The company to charge.
            task: The task that was executed.
        """
        if result.cost_cents > 0:
            cost_event = CostEvent(
                company_id=company_id,
                agent_id=result.agent_id,
                task_id=result.task_id,
                project_id=task.project_id,
                provider="adapter",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_cents=result.cost_cents,
                billing_type="task_execution",
                occurred_at=datetime.now(timezone.utc),
            )
            self._db.add(cost_event)

            # Update agent spent amount
            from nexus.models.agent import Agent

            stmt = (
                update(Agent)
                .where(Agent.id == result.agent_id)
                .values(
                    spent_monthly_cents=Agent.spent_monthly_cents + result.cost_cents
                )
            )
            await self._db.execute(stmt)

    async def _update_task_status(
        self,
        task_id: uuid.UUID,
        status: str,
        result_text: str | None = None,
        error_text: str | None = None,
    ) -> None:
        """Update task status in the database.

        Args:
            task_id: The task to update.
            status: New status value.
            result_text: Optional result text on success.
            error_text: Optional error text on failure.
        """
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if status == "running":
            values["started_at"] = datetime.now(timezone.utc)
        elif status == "completed":
            values["completed_at"] = datetime.now(timezone.utc)
            values["result"] = result_text
        elif status == "failed":
            values["completed_at"] = datetime.now(timezone.utc)
            values["error"] = error_text

        stmt = update(Task).where(Task.id == task_id).values(**values)
        await self._db.execute(stmt)

    async def execute(
        self,
        task: Task,
        session: AgentSession,
        payload: dict[str, Any] | None = None,
    ) -> TaskResult:
        """Execute a task through the agent adapter with full lifecycle management.

        Performs budget check, permission validation, execution with retries,
        cost recording, and status updates.

        Args:
            task: The Task model to execute.
            session: The active AgentSession.
            payload: Optional additional execution parameters.

        Returns:
            The TaskResult from the adapter.

        Raises:
            BudgetExceededError: If the agent has no remaining budget.
            TaskExecutionError: If all retry attempts fail.
        """
        agent_id = session.agent_id

        # 1. Check budget
        await self._check_budget(agent_id, task.company_id)

        # 2. Validate permissions
        if not await self._validate_permissions(agent_id, task):
            raise PermissionError(
                f"Agent {agent_id} is not permitted to execute task {task.id}"
            )

        # 3. Update task to running
        await self._update_task_status(task.id, "running")

        # 4. Git Worktree Isolation (if isolation is enabled)
        worktree_info = None
        if payload and payload.get("isolate", False):
            try:
                from nexus.runtime.worktree import WorktreeManager
                wt_mgr = WorktreeManager()
                worktree_info = await wt_mgr.create_worktree(
                    repo_path=payload.get("repo_path", "."),
                    agent_id=agent_id,
                    agent_name=payload.get("agent_name", "agent"),
                )
                if payload:
                    payload["worktree_path"] = worktree_info.worktree_path
                    payload["branch"] = worktree_info.branch
            except Exception as wt_err:
                # Log worktree creation warning and proceed in default workspace
                pass

        # 5. Execute with smart retry and escalation
        from nexus.orchestration.smart_retry import SmartRetryWithEscalation, EscalationAction

        smart_retry = SmartRetryWithEscalation(
            max_retries=self._max_retries,
            budget_limit_cents=1000,
        )

        task_payload = payload or {
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
        }

        async def _execute_fn() -> tuple[Any, int]:
            """Wrapped execution function for SmartRetry."""
            result = await self._adapter.execute_task(session, task.id, task_payload)
            if result.success:
                return result, result.cost_cents
            raise RuntimeError(result.error or "Task execution failed")

        retry_result = await smart_retry.execute_with_smart_retry(
            task_id=task.id,
            execute_fn=_execute_fn,
            estimated_cost_per_attempt_cents=50,
        )

        if retry_result.success:
            # Extract the TaskResult from the output
            result = retry_result.final_output
            # 6. Record cost
            await self._record_cost(result, task.company_id, task)
            # 7. Update task status
            await self._update_task_status(
                task.id, "completed", result_text=str(result.output)
            )
            return result

        # Smart retry exhausted — handle escalation
        escalation = retry_result.escalation_action
        diagnosis = retry_result.diagnosis
        last_error = diagnosis.diagnosis_detail if diagnosis else "Unknown error after retries"

        # Act on escalation (not just log)
        if escalation == EscalationAction.REASSIGN:
            # Re-route to a different agent
            try:
                from nexus.orchestration.router import AgentCandidate, AgentRouter
                from nexus.models.agent import Agent as AgentModel

                agents_stmt = select(AgentModel).where(
                    AgentModel.company_id == task.company_id,
                    AgentModel.status.in_(["active", "ready"]),
                    AgentModel.id != agent_id,  # Exclude current agent
                )
                agents_result = await self._db.execute(agents_stmt)
                other_agents = list(agents_result.scalars().all())

                if other_agents:
                    candidates = [
                        AgentCandidate(
                            agent_id=a.id, name=a.name, skills=a.capabilities or [],
                            current_workload=0, max_concurrent=5,
                            budget_remaining_cents=a.budget_monthly_cents - a.spent_monthly_cents,
                            performance_score=(a.performance_score or 50) / 100.0, status=a.status,
                        )
                        for a in other_agents
                    ]
                    router = AgentRouter()
                    decision = await router.route_task(
                        task_description=task.title,
                        required_skills=[], estimated_cost_cents=100,
                        available_agents=candidates,
                    )
                    if decision:
                        from sqlalchemy import update as sa_update
                        await self._db.execute(
                            sa_update(Task).where(Task.id == task.id)
                            .values(assigned_agent_id=decision.agent_id, status="pending",
                                    updated_at=datetime.now(timezone.utc))
                        )
                        last_error = f"[REASSIGNED to {decision.agent_id}] {last_error}"
                        logger.info("Task %s reassigned to agent %s", task.id, decision.agent_id)
            except Exception as re_err:
                last_error = f"[REASSIGN FAILED: {re_err}] {last_error}"

        elif escalation == EscalationAction.DECOMPOSE:
            # Break the task into smaller pieces
            try:
                from nexus.orchestration.planner import TaskPlanner
                planner = TaskPlanner(max_subtasks=3)
                subtasks = await planner.decompose_task(
                    task_id=task.id,
                    description=f"{task.title}\n{task.description or ''}",
                )
                for st in subtasks:
                    sub = Task(
                        company_id=task.company_id,
                        title=st.description[:500],
                        description=f"Decomposed from failed task: {task.title}",
                        priority=task.priority,
                        parent_id=task.id,
                        status="pending",
                    )
                    self._db.add(sub)
                await self._db.flush()
                last_error = f"[DECOMPOSED into {len(subtasks)} subtasks] {last_error}"
                logger.info("Task %s decomposed into %d subtasks", task.id, len(subtasks))
            except Exception as dec_err:
                last_error = f"[DECOMPOSE FAILED: {dec_err}] {last_error}"

        elif escalation == EscalationAction.REPORT_BLOCKER:
            last_error = f"[BLOCKER] {last_error}"

        # All retries exhausted
        await self._update_task_status(task.id, "failed", error_text=last_error)
        raise TaskExecutionError(task.id, self._max_retries, last_error)
