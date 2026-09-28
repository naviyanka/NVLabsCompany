"""P5.2: a Temporal pipeline run keeps the caller who started it.

The caller authorized to execute the pipeline is carried, as an
``ExecutionContext.to_dict()``, from ``run_pipeline`` through
``start_pipeline_workflow`` and the workflow input into each stage's
``call_llm_activity``. There it is rebuilt and bound to that stage's agent, so
a governed tool call in the stage is authorized and recorded as the caller
acting through the stage agent, not as the agent acting on its own.

The caller's role is copied when the run starts and stays fixed for the run.
Stages started without a context (a run from before this field existed) still
act autonomously as their agent.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import chat, pipelines
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.company import Company, CompanyMembership
from nexus.models.mcp_binding import McpBinding
from nexus.models.pipeline import Pipeline, PipelineRun
from nexus.models.tool import ToolCatalogEntry, ToolConnection
from nexus.models.tool_invocation import ToolInvocation
from nexus.runtime.adapter import AgentSession
from nexus.temporal import client as temporal_client
from nexus.temporal._sdk import HAS_SDK
from nexus.temporal.activities import LLMCallInput, call_llm_activity
from nexus.temporal.workflows import (
    PipelineExecutionInput,
    PipelineExecutionOutput,
    PipelineExecutionWorkflow,
)
from nexus.tools.access import ALLOWED, BUILTIN_ENDPOINT, BUILTIN_TRANSPORT
from nexus.tools.context import ExecutionContext
from nexus.tools.factory import guarded_call

TOOL = "file-json-parse"  # a read-risk builtin node


class FakeAdapter:
    """Makes one governed tool call per task with the session's context."""

    async def create_session(self, agent_id, config):
        return AgentSession(session_id="s", agent_id=agent_id, adapter_type="fake")

    async def execute_task(self, session, task_id, payload):
        async def run() -> dict:
            return {"parsed": {}}

        await guarded_call(session.context, TOOL, {"text": "{}"}, run, source="mcp")
        return SimpleNamespace(success=True, output="done", input_tokens=0, output_tokens=0,
                               cost_cents=0, error=None)

    async def terminate(self, session):
        pass


class FakeRegistry:
    def create_adapter(self, name, config=None):
        return FakeAdapter()


class FakeTemporal:
    """Records the workflows it is asked to start."""

    def __init__(self) -> None:
        self.started: list[tuple[Any, PipelineExecutionInput, str]] = []

    async def start_workflow(self, fn, arg, *, id, task_queue):
        self.started.append((fn, arg, id))
        return SimpleNamespace(id=id)


@pytest.fixture
async def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pipeline_ctx.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.adapters.registry as registry_module
    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    monkeypatch.setattr(settings, "tool_binding_enforcement", "enforce")
    monkeypatch.setattr(registry_module, "AdapterRegistry", FakeRegistry)
    monkeypatch.setattr(chat, "_resolve_adapter_type", lambda agent, conn=None: ("fake", {"model": "m"}))

    async def no_budget(*args, **kwargs):
        return None

    async def no_memory(*args, **kwargs):
        return 0

    monkeypatch.setattr(chat, "_reserve_budget", no_budget)
    monkeypatch.setattr(chat, "_remember_response", no_memory)

    acme, other = Company(name="Acme"), Company(name="Other")
    manager_id = uuid.uuid4()
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        a = Agent(company_id=acme.id, name="Writer", role="engineer")
        b = Agent(company_id=acme.id, name="Reviewer", role="engineer")
        builtin = ToolConnection(company_id=acme.id, name="nexus", transport_type=BUILTIN_TRANSPORT,
                                 endpoint_url=BUILTIN_ENDPOINT)
        db.add_all([a, b, builtin])
        await db.flush()
        stages = [
            {"name": "write", "prompt": "Draft it", "agent_id": str(a.id)},
            {"name": "review", "prompt": "Check it", "agent_id": str(b.id)},
        ]
        pipeline = Pipeline(company_id=acme.id, name="Release", stages=stages)
        db.add_all([
            ToolCatalogEntry(company_id=acme.id, connection_id=builtin.id, tool_name=TOOL,
                             risk_level="read"),
            *(McpBinding(company_id=acme.id, connection_id=builtin.id, target_type="agent",
                         agent_id=agent_id) for agent_id in (a.id, b.id)),
            CompanyMembership(company_id=acme.id, user_id=manager_id, role="manager"),
            pipeline,
        ])
        await db.commit()

    principals = {
        "manager": Principal(kind="user", company_id=acme.id, role="manager", user_id=manager_id),
        "viewer": Principal(kind="user", company_id=acme.id, role="viewer", user_id=uuid.uuid4()),
        "outsider": Principal(kind="user", company_id=other.id, role="admin", user_id=uuid.uuid4()),
    }
    app = FastAPI()
    app.include_router(pipelines.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers["x-test-principal"]]
        return await call_next(request)

    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    monkeypatch.setattr(temporal_client, "is_temporal_enabled", lambda: True)
    yield SimpleNamespace(
        http=http, factory=factory, acme=acme.id, other=other.id, a=a.id, b=b.id,
        pipeline=pipeline.id, stages=stages, principals=principals, manager_id=manager_id,
    )
    await http.aclose()
    await engine.dispose()


def use_temporal(monkeypatch, client) -> None:
    async def get_client():
        return client

    monkeypatch.setattr(temporal_client, "_get_client", get_client)


async def start(w, who: str) -> httpx.Response:
    return await w.http.post(f"/api/v1/pipelines/{w.pipeline}/run",
                             headers={"x-test-principal": who})


def manager_context(w) -> dict[str, Any]:
    return ExecutionContext.for_principal(w.principals["manager"], source="pipeline").to_dict()


async def tool_calls(w) -> list[tuple]:
    """Who each governed tool call acted as: agent, principal, role, source, outcome."""
    async with w.factory() as db:
        rows = (await db.execute(select(ToolInvocation).order_by(ToolInvocation.created_at))).scalars()
        return [
            (r.agent_id, r.authorization_detail["principal_id"],
             r.authorization_detail["principal_role"], r.authorization_detail["request_source"],
             r.authorization)
            for r in rows
        ]


def as_manager_through(w, *agents: uuid.UUID) -> list[tuple]:
    return [(agent, f"user:{w.manager_id}", "manager", "pipeline", ALLOWED) for agent in agents]


async def runs(w) -> list[tuple]:
    async with w.factory() as db:
        return [(r.company_id, r.status) for r in (await db.execute(select(PipelineRun))).scalars()]


# --- Starting a run --------------------------------------------------------------


async def test_a_manager_run_hands_temporal_the_managers_context(world, monkeypatch) -> None:
    temporal = FakeTemporal()
    use_temporal(monkeypatch, temporal)

    started = await start(world, "manager")

    assert started.status_code == 201
    [(fn, workflow_input, workflow_id)] = temporal.started
    assert fn == PipelineExecutionWorkflow.run
    assert workflow_id == f"pipeline-{started.json()['id']}"
    assert workflow_input.stages == world.stages
    assert workflow_input.context == manager_context(world)
    # The caller, not an agent: no stage agent is chosen yet.
    context = ExecutionContext.from_dict(workflow_input.context)
    assert (context.principal_id, context.principal_role, context.source, context.agent_id) == (
        f"user:{world.manager_id}", "manager", "pipeline", None)


async def test_the_run_is_committed_before_its_workflow_starts(world, monkeypatch) -> None:
    """A stage may run before the request ends; it must see the run, not wait on its lock."""
    seen: list[list[tuple]] = []

    class Watching(FakeTemporal):
        async def start_workflow(self, fn, arg, *, id, task_queue):
            seen.append(await runs(world))
            return await super().start_workflow(fn, arg, id=id, task_queue=task_queue)

    use_temporal(monkeypatch, Watching())

    assert (await start(world, "manager")).status_code == 201
    assert seen == [[(world.acme, "running")]]


@pytest.mark.parametrize(("who", "status"), [("viewer", 403), ("outsider", 404)])
async def test_a_refused_caller_starts_no_workflow(world, monkeypatch, who, status) -> None:
    temporal = FakeTemporal()
    use_temporal(monkeypatch, temporal)

    assert (await start(world, who)).status_code == status
    assert temporal.started == []
    assert await runs(world) == []


# --- Running a stage -------------------------------------------------------------


async def test_the_activity_acts_for_the_caller_through_the_stage_agent(world) -> None:
    out = await call_llm_activity(LLMCallInput(
        agent_id=str(world.b), company_id=str(world.acme), prompt="Check it",
        context=manager_context(world)))

    assert out.success, out.error
    assert await tool_calls(world) == as_manager_through(world, world.b)


async def test_each_stage_binds_the_callers_context_to_its_own_agent(world) -> None:
    result = await PipelineExecutionWorkflow().run(PipelineExecutionInput(
        pipeline_id=str(world.pipeline), run_id=str(uuid.uuid4()), company_id=str(world.acme),
        stages=world.stages, context=manager_context(world)))

    assert result.status == "completed"
    # The caller stays the principal and each stage keeps its own agent:
    # neither replaces the other.
    assert await tool_calls(world) == as_manager_through(world, world.a, world.b)


async def test_the_role_is_the_one_the_caller_had_when_the_run_started(world) -> None:
    context = manager_context(world)
    async with world.factory() as db:
        membership = (await db.execute(select(CompanyMembership))).scalar_one()
        membership.role = "viewer"
        await db.commit()

    await call_llm_activity(LLMCallInput(
        agent_id=str(world.a), company_id=str(world.acme), prompt="Draft it", context=context))

    # Documented behaviour, not a new rule: the run keeps the starting role.
    assert await tool_calls(world) == as_manager_through(world, world.a)


async def test_a_stage_without_a_context_still_acts_as_its_agent(world) -> None:
    out = await call_llm_activity(LLMCallInput(
        agent_id=str(world.a), company_id=str(world.acme), prompt="Draft it"))

    assert out.success, out.error
    assert await tool_calls(world) == [
        (world.a, f"agent:{world.a}", "agent", "background", ALLOWED)]


def other_company(w, context: dict) -> dict:
    return {**context, "company_id": str(w.other)}


def other_agent(w, context: dict) -> dict:
    return {**context, "agent_id": str(w.b)}


@pytest.mark.parametrize("tamper", [other_company, other_agent])
async def test_a_context_for_another_company_or_agent_is_refused(world, tamper) -> None:
    out = await call_llm_activity(LLMCallInput(
        agent_id=str(world.a), company_id=str(world.acme), prompt="Draft it",
        context=tamper(world, manager_context(world))))

    assert not out.success
    assert "different company or agent" in out.error
    assert await tool_calls(world) == []


# --- Through a real Temporal server ----------------------------------------------


@pytest.fixture
async def temporal_env():
    if not HAS_SDK:
        pytest.skip("temporalio not installed")
    from temporalio.testing import WorkflowEnvironment

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as e:  # pragma: no cover -- environment-dependent
        pytest.skip(f"Temporal test server unavailable: {e}")
    try:
        yield env
    finally:
        await env.shutdown()


async def test_the_callers_context_survives_a_real_temporal_run(world, monkeypatch, temporal_env) -> None:
    from temporalio.worker import Worker

    from nexus.temporal.activities import ALL_ACTIVITIES
    from nexus.temporal.workflows import ALL_WORKFLOWS

    use_temporal(monkeypatch, temporal_env.client)
    async with Worker(temporal_env.client, task_queue=temporal_client.TASK_QUEUE,
                      workflows=ALL_WORKFLOWS, activities=ALL_ACTIVITIES):
        started = await start(world, "manager")
        assert started.status_code == 201
        handle = temporal_env.client.get_workflow_handle(
            f"pipeline-{started.json()['id']}", result_type=PipelineExecutionOutput)
        result = await handle.result()

    assert result.status == "completed", result.results
    assert await tool_calls(world) == as_manager_through(world, world.a, world.b)
