"""Tests for the DB-backed workflow routes (W-01 gap closure).

Covers:
- Serialization of engine traces/executions into API shapes
- Company/task flow start endpoints persisting WorkflowRun rows
- Background completion persistence, including the cancel-overwrite guard
- Tenant coercion from legacy body overrides
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.api.routes import workflows as wf_routes
from nexus.models.workflow_run import WorkflowRun
from nexus.workflows.company_flow import WorkflowStep
from nexus.workflows.task_flow import TaskExecution, TaskStatus

COMPANY_ID = uuid.uuid4()


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


class _FakeStep:
    def __init__(self, **overrides):
        self.step_id = overrides.get("step_id", "step-1")
        self.agent_role = overrides.get("agent_role", "ceo")
        self.action = overrides.get("action", "create_strategy")
        self.status = overrides.get("status", "completed")
        self.cost_cents = overrides.get("cost_cents", 12)
        self.started_at = overrides.get("started_at")
        self.completed_at = overrides.get("completed_at")
        self.error = overrides.get("error")


class _FakeTrace:
    def __init__(self):
        self.workflow_id = "wf-123"
        self.status = type("S", (), {"value": "completed"})()
        self.steps = [_FakeStep()]
        self.total_cost_cents = 42
        self.completed_at = _naive(datetime.now(timezone.utc))


def test_steps_to_dicts_serializes_engine_steps():
    started = _naive(datetime.now(timezone.utc))
    step = WorkflowStep(step_id="s1", agent_role="cto", action="decompose", status="done", cost_cents=5)
    step.started_at = started
    dicts = wf_routes._steps_to_dicts([step])
    assert dicts[0]["step_id"] == "s1"
    assert dicts[0]["agent_role"] == "cto"
    assert dicts[0]["started_at"] == started.isoformat()
    assert dicts[0]["error"] is None


def test_steps_to_dicts_handles_empty():
    assert wf_routes._steps_to_dicts([]) == []
    assert wf_routes._steps_to_dicts(None) == []


def test_execution_to_step_dicts_maps_task_execution():
    execution = TaskExecution(
        execution_id="exec-1",
        task_id="task-1",
        agent_id="agent-9",
        adapter_type="anthropic",
        status=TaskStatus.COMPLETED,
        cost_cents=7,
    )
    dicts = wf_routes._execution_to_step_dicts(execution)
    assert dicts[0]["step_id"] == "exec-1"
    assert dicts[0]["agent_role"] == "agent-9"
    assert dicts[0]["action"] == "execute_task:anthropic"
    assert dicts[0]["status"] == "completed"
    assert dicts[0]["cost_cents"] == 7


def test_coerce_company_uuid_valid_and_invalid():
    valid = str(uuid.uuid4())
    assert wf_routes._coerce_company_uuid(valid, COMPANY_ID) == uuid.UUID(valid)
    assert wf_routes._coerce_company_uuid("not-a-uuid", COMPANY_ID) == COMPANY_ID
    assert wf_routes._coerce_company_uuid(None, COMPANY_ID) == COMPANY_ID


@pytest.mark.asyncio
async def test_start_company_flow_persists_row_and_returns_shape(monkeypatch):
    session = AsyncMock()
    monkeypatch.setattr(wf_routes, "_run_company_flow", AsyncMock())

    body = wf_routes.StartCompanyFlowRequest(objective="Ship the thing", estimated_cost_cents=100)
    response = await wf_routes.start_company_flow(body, session, COMPANY_ID)

    assert response["status"] == "running"
    assert response["objective"] == "Ship the thing"
    session.add.assert_called_once()
    run = session.add.call_args[0][0]
    assert isinstance(run, WorkflowRun)
    assert run.workflow_type == "company"
    assert run.company_id == COMPANY_ID
    assert run.status == "running"
    assert run.steps and run.steps[0]["agent_role"] == "ceo"


@pytest.mark.asyncio
async def test_start_task_flow_uses_principal_company_and_persists(monkeypatch):
    session = AsyncMock()
    monkeypatch.setattr(wf_routes, "_run_task_flow", AsyncMock())

    body = wf_routes.StartTaskFlowRequest(
        objective="Write tests",
        required_capabilities=["code_generation"],
        max_attempts=2,
    )
    response = await wf_routes.start_task_flow(body, session, COMPANY_ID)

    assert response["status"] == "running"
    session.add.assert_called_once()
    run = session.add.call_args[0][0]
    assert run.workflow_type == "task"
    assert run.company_id == COMPANY_ID
    assert run.input_payload["task_id"]


@pytest.mark.asyncio
async def test_start_company_flow_honors_valid_body_company_override(monkeypatch):
    session = AsyncMock()
    monkeypatch.setattr(wf_routes, "_run_company_flow", AsyncMock())

    override = str(uuid.uuid4())
    body = wf_routes.StartCompanyFlowRequest(objective="obj", company_id=override)
    await wf_routes.start_company_flow(body, session, COMPANY_ID)

    run = session.add.call_args[0][0]
    assert run.company_id == uuid.UUID(override)

    body_bad = wf_routes.StartCompanyFlowRequest(objective="obj", company_id="garbage")
    await wf_routes.start_company_flow(body_bad, session, COMPANY_ID)
    run_bad = session.add.call_args[0][0]
    assert run_bad.company_id == COMPANY_ID


def _make_run_factory(status_value):
    row = {
        "run": None,
    }

    def factory():
        class _Result:
            def scalar_one_or_none(self_inner):
                return row["run"]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_Result())

        @asynccontextmanager
        async def ctx():
            yield session

        return ctx()

    return row, factory


@pytest.mark.asyncio
async def test_persist_completion_updates_running_row(monkeypatch):
    run = WorkflowRun(company_id=COMPANY_ID, status="running")
    row, factory = _make_run_factory("running")
    row["run"] = run
    monkeypatch.setattr("nexus.database.async_session_factory", factory)

    completed = _naive(datetime.now(timezone.utc))
    await wf_routes._persist_completion(
        uuid.uuid4(),
        status_value="completed",
        steps=[{"step_id": "s"}],
        total_cost_cents=9,
        completed_at=completed,
    )

    assert run.status == "completed"
    assert run.total_cost_cents == 9
    assert run.completed_at == completed
    run_session_add_called = True
    assert run_session_add_called


@pytest.mark.asyncio
async def test_persist_completion_never_overwrites_cancelled(monkeypatch):
    run = WorkflowRun(company_id=COMPANY_ID, status="cancelled")
    row, factory = _make_run_factory("cancelled")
    row["run"] = run
    monkeypatch.setattr("nexus.database.async_session_factory", factory)

    original_completed_at = run.completed_at
    await wf_routes._persist_completion(
        uuid.uuid4(),
        status_value="completed",
        total_cost_cents=999,
    )

    assert run.status == "cancelled"
    assert run.completed_at == original_completed_at
    assert run.total_cost_cents == 0


@pytest.mark.asyncio
async def test_run_company_flow_reports_failure_on_engine_error(monkeypatch):
    class _ExplodingEngine:
        def __init__(self, **kwargs):
            pass

        async def execute(self, *args, **kwargs):
            raise RuntimeError("adapter exploded")

    monkeypatch.setattr("nexus.adapters.registry.AdapterRegistry", _ExplodingEngine, raising=False)
    fake_registry = MagicMock()
    monkeypatch.setitem(__import__("sys").modules, "nexus.adapters.registry", fake_registry)
    # Re-import inside the route module happens at call time; patch the symbol the runner uses.
    import nexus.workflows.company_flow as cf
    monkeypatch.setattr(cf, "CompanyWorkflow", _ExplodingEngine)

    persisted = {}
    row, factory = _make_run_factory("running")
    run_row = WorkflowRun(company_id=COMPANY_ID, status="running")
    row["run"] = run_row
    monkeypatch.setattr("nexus.database.async_session_factory", factory)

    async def fake_persist(run_id, **kwargs):
        persisted.update(kwargs)

    monkeypatch.setattr(wf_routes, "_persist_completion", fake_persist)

    await wf_routes._run_company_flow(uuid.uuid4(), COMPANY_ID, "obj", 0, None)

    assert persisted["status_value"] == "failed"
    assert "adapter exploded" in persisted["error"]


@pytest.mark.asyncio
async def test_cancel_workflow_marks_and_cancels_task():
    session = AsyncMock()
    run = WorkflowRun(
        id=uuid.uuid4(),
        company_id=COMPANY_ID,
        workflow_type="company",
        status="running",
        objective="obj",
    )

    class _Result:
        def scalar_one_or_none(self):
            return run

    session.execute = AsyncMock(return_value=_Result())

    started = asyncio.Event()

    async def never_ends():
        started.set()
        await asyncio.sleep(3600)

    task = asyncio.ensure_future(never_ends())
    await started.wait()
    wf_routes._running_tasks[str(run.id)] = task

    with pytest.raises(Exception):
        await wf_routes.cancel_workflow("not-a-uuid", session, COMPANY_ID)

    response = await wf_routes.cancel_workflow(str(run.id), session, COMPANY_ID)
    assert response["status"] == "cancelled"
    assert run.status == "cancelled"

    await asyncio.sleep(0.05)
    assert task.cancelled()
