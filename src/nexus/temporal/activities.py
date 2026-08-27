"""Temporal Activities — the actual work units (retryable, timeout-safe).

Every operation that touches an LLM, the database, a socket, or a subprocess
lives here rather than in a workflow body (ADR 0001). Activities take and return
dataclasses so they are serializable across the worker boundary, and they are
decorated with ``@activity_defn`` so the worker can register them.

The same functions are the in-process fallback runner: ``_sdk.execute_activity``
dispatches through Temporal only when actually inside a workflow, so callers on
the façade path (``workflows/task_flow.py``) run identical code.
"""

import uuid
import logging
from dataclasses import dataclass, field
from typing import Any

from nexus.temporal._sdk import activity_defn

logger = logging.getLogger(__name__)


@dataclass
class LLMCallInput:
    """Input for the call_llm activity."""
    agent_id: str
    company_id: str
    prompt: str
    system_prompt: str = ""


@dataclass
class LLMCallOutput:
    """Output from the call_llm activity."""
    response_text: str
    model_used: str
    tokens_used: int
    success: bool
    error: str | None = None


@dataclass
class RouteTaskInput:
    """Input for the route_task activity."""
    company_id: str
    task_description: str
    required_skills: list[str]


@dataclass
class DecomposeTaskInput:
    """Input for the decompose_task activity."""
    task_id: str
    description: str
    max_subtasks: int = 5


@dataclass
class ExecuteTaskInput:
    """Input for the execute_task activity.

    Carries the resolved agent and adapter rather than an object reference, so
    the activity is self-contained across the worker boundary.
    """
    task_id: str
    agent_id: str
    adapter_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecuteTaskOutput:
    """Output from the execute_task activity."""
    task_id: str
    success: bool
    output: str = ""
    status: str = "failed"
    cost_cents: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


@activity_defn
async def call_llm_activity(input: LLMCallInput) -> LLMCallOutput:
    """Activity: Call an LLM adapter for an agent.

    This wraps the existing _call_llm function from chat.py.
    Temporal will automatically retry this on rate limits or transient failures.
    """
    from nexus.database import async_session_factory
    from nexus.models.agent import Agent
    from nexus.api.routes.chat import _build_system_prompt, _call_llm, _fetch_agent_memories
    from sqlalchemy import select

    try:
        async with async_session_factory() as db:
            agent_uuid = uuid.UUID(input.agent_id)
            company_uuid = uuid.UUID(input.company_id)

            stmt = select(Agent).where(Agent.id == agent_uuid)
            result = await db.execute(stmt)
            agent = result.scalar_one_or_none()

            if not agent:
                return LLMCallOutput(response_text="", model_used="", tokens_used=0, success=False, error="Agent not found")

            if not input.system_prompt:
                memories = await _fetch_agent_memories(db, agent_uuid, company_uuid, limit=5)
                system_prompt = _build_system_prompt(agent, memories=memories)
            else:
                system_prompt = input.system_prompt

            response_text, model_used, tokens_used = await _call_llm(
                agent, system_prompt, input.prompt, []
            )

            return LLMCallOutput(
                response_text=response_text,
                model_used=model_used,
                tokens_used=tokens_used,
                success=True,
            )
    except Exception as e:
        logger.error("LLM activity failed: %s", e)
        return LLMCallOutput(response_text="", model_used="", tokens_used=0, success=False, error=str(e))


@activity_defn
async def route_task_activity(input: RouteTaskInput) -> str | None:
    """Activity: Route a task to the best available agent.

    Returns the agent_id of the selected agent, or None if no agent available.
    """
    from nexus.database import async_session_factory
    from nexus.models.agent import Agent
    from nexus.orchestration.router import AgentCandidate, AgentRouter
    from sqlalchemy import select

    try:
        async with async_session_factory() as db:
            company_uuid = uuid.UUID(input.company_id)
            stmt = select(Agent).where(Agent.company_id == company_uuid, Agent.status.in_(["active", "ready"]))
            result = await db.execute(stmt)
            agents = list(result.scalars().all())

            if not agents:
                return None

            candidates = [
                AgentCandidate(
                    agent_id=a.id, name=a.name, skills=a.capabilities or [],
                    current_workload=0, max_concurrent=5,
                    budget_remaining_cents=a.budget_monthly_cents - a.spent_monthly_cents,
                    performance_score=(a.performance_score or 50) / 100.0, status=a.status,
                )
                for a in agents
            ]

            router = AgentRouter()
            decision = await router.route_task(
                task_description=input.task_description,
                required_skills=input.required_skills,
                estimated_cost_cents=100,
                available_agents=candidates,
            )
            return str(decision.agent_id) if decision else None
    except Exception as e:
        logger.error("Route task activity failed: %s", e)
        return None


@activity_defn
async def decompose_task_activity(input: DecomposeTaskInput) -> list[dict[str, Any]]:
    """Activity: Decompose a task into subtasks using TaskPlanner."""
    from nexus.orchestration.planner import TaskPlanner

    planner = TaskPlanner(max_subtasks=input.max_subtasks)
    subtasks = await planner.decompose_task(
        task_id=uuid.UUID(input.task_id),
        description=input.description,
    )
    return [{"description": st.description, "dependencies": [str(d) for d in st.dependencies]} for st in subtasks]


def _coerce_uuid(value: str) -> uuid.UUID:
    """Parse a UUID, falling back to a fresh one for non-UUID demo identifiers."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return uuid.uuid4()


@activity_defn
async def execute_task_activity(input: ExecuteTaskInput) -> ExecuteTaskOutput:
    """Activity: run one task through its adapter.

    This is ``TaskFlow._do_execute`` lifted out of the façade. The adapter
    session is created and terminated inside the activity so a crash cannot
    leak it across a workflow replay. When the adapter type is not registered,
    the simulated result is returned — the same demo/testing behaviour the
    façade had.
    """
    from nexus.adapters.registry import AdapterRegistry

    try:
        registry = AdapterRegistry()
    except Exception as e:  # pragma: no cover — registry construction is trivial
        logger.error("Adapter registry unavailable: %s", e)
        registry = None

    if registry is not None and registry.is_registered(input.adapter_type):
        try:
            adapter = registry.create_adapter(input.adapter_type, input.config)
            session = await adapter.create_session(_coerce_uuid(input.agent_id), input.config)
            try:
                result = await adapter.execute_task(
                    session, _coerce_uuid(input.task_id), input.payload
                )
            finally:
                await adapter.terminate(session)

            return ExecuteTaskOutput(
                task_id=input.task_id,
                success=result.success,
                output=result.output or "",
                status="success" if result.success else "failed",
                cost_cents=result.cost_cents,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                error=result.error,
            )
        except Exception as e:
            logger.error("Execute task activity failed: %s", e)
            return ExecuteTaskOutput(
                task_id=input.task_id,
                success=False,
                error=f"Adapter execution failed: {type(e).__name__}: {e}",
            )

    # No registered adapter — simulated execution for demo/testing.
    return ExecuteTaskOutput(
        task_id=input.task_id,
        success=True,
        output=f"Executed task {input.task_id}",
        status="success",
    )


# Single registration list so the worker cannot drift out of sync with this file.
ALL_ACTIVITIES = [
    call_llm_activity,
    route_task_activity,
    decompose_task_activity,
    execute_task_activity,
]
