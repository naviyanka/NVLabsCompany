"""The legacy workflow engines never report work that did not happen.

CompanyWorkflow and TaskFlow used to turn a missing registry, an unregistered
adapter or an adapter exception into ``completed`` with an invented
``"Completed: <description>"`` / ``"Executed task ..."`` output. Each case here
must end in a terminal non-success status with a reason, and no fabricated
deliverable. Adapters are in-memory fakes; nothing calls a provider.
"""

import asyncio
import types
import uuid

import pytest

from nexus.temporal.activities import ExecuteTaskInput, execute_task_activity
from nexus.workflows.company_flow import CompanyWorkflow, WorkflowStatus
from nexus.workflows.task_flow import TaskFlow, TaskStatus

COMPANY_ID = str(uuid.uuid4())
SECRET = "sk-live-THIS-MUST-NOT-LEAK"


class _Adapter:
    def __init__(self, success=True, output="real output", cost_cents=5, raises=None):
        self.success, self.output = success, output
        self.cost_cents, self.raises = cost_cents, raises
        self.terminated = 0

    async def create_session(self, agent_id, config):
        return types.SimpleNamespace(context=None)

    async def execute_task(self, session, task_id, payload):
        if self.raises is not None:
            raise self.raises
        return types.SimpleNamespace(
            success=self.success, output=self.output, cost_cents=self.cost_cents
        )

    async def terminate(self, session):
        self.terminated += 1


class _Registry:
    def __init__(self, adapter=None, registered=True):
        self.adapter, self.registered = adapter or _Adapter(), registered

    def is_registered(self, adapter_type):
        return self.registered

    def create_adapter(self, adapter_type, config):
        return self.adapter


def _engineer_steps(trace):
    return [s for s in trace.steps if s.agent_role == "engineer"]


def _assert_nothing_fabricated(trace):
    assert trace.status != WorkflowStatus.COMPLETED
    assert trace.completed_at is not None
    assert not [s for s in trace.steps if s.agent_role == "qa" and s.status == "completed"]
    for step in _engineer_steps(trace):
        assert step.status != "completed"
        assert not (step.output_data.get("output") or "").startswith("Completed:")
        assert step.error


# --- CompanyWorkflow -------------------------------------------------------


@pytest.mark.asyncio
async def test_company_flow_without_registry_is_blocked():
    trace = await CompanyWorkflow(company_id=COMPANY_ID).execute("Build it")
    _assert_nothing_fabricated(trace)
    assert trace.status == WorkflowStatus.BLOCKED
    assert "Adapter unavailable" in _engineer_steps(trace)[0].error
    assert trace.total_cost_cents == 0


@pytest.mark.asyncio
async def test_company_flow_unregistered_adapter_is_blocked():
    flow = CompanyWorkflow(company_id=COMPANY_ID, adapter_registry=_Registry(registered=False))
    trace = await flow.execute("Build it")
    _assert_nothing_fabricated(trace)
    assert trace.status == WorkflowStatus.BLOCKED


@pytest.mark.asyncio
async def test_company_flow_adapter_exception_fails_without_leaking():
    adapter = _Adapter(raises=RuntimeError(f"401 from provider, key={SECRET}"))
    flow = CompanyWorkflow(company_id=COMPANY_ID, adapter_registry=_Registry(adapter))
    trace = await flow.execute("Build it")
    _assert_nothing_fabricated(trace)
    assert trace.status == WorkflowStatus.FAILED
    step = _engineer_steps(trace)[0]
    assert step.error == "Adapter execution failed: RuntimeError"
    assert SECRET not in repr(trace)
    assert adapter.terminated >= 1


@pytest.mark.asyncio
async def test_company_flow_timeout_is_failed_not_success():
    adapter = _Adapter(raises=TimeoutError())
    flow = CompanyWorkflow(company_id=COMPANY_ID, adapter_registry=_Registry(adapter))
    trace = await flow.execute("Build it")
    _assert_nothing_fabricated(trace)
    assert trace.status == WorkflowStatus.FAILED
    assert _engineer_steps(trace)[0].error == "Adapter execution failed: TimeoutError"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter, reason",
    [
        (_Adapter(success=False, output="partial"), "Adapter reported failure"),
        (_Adapter(success=True, output=""), "Adapter returned no output"),
    ],
)
async def test_company_flow_failed_or_empty_run_is_failed(adapter, reason):
    flow = CompanyWorkflow(company_id=COMPANY_ID, adapter_registry=_Registry(adapter))
    trace = await flow.execute("Build it")
    _assert_nothing_fabricated(trace)
    assert trace.status == WorkflowStatus.FAILED
    assert _engineer_steps(trace)[0].error == reason


@pytest.mark.asyncio
async def test_company_flow_cancellation_is_terminal_not_success():
    started = asyncio.Event()

    class _Hanging(_Adapter):
        async def execute_task(self, session, task_id, payload):
            started.set()
            await asyncio.sleep(3600)

    adapter = _Hanging()
    flow = CompanyWorkflow(company_id=COMPANY_ID, adapter_registry=_Registry(adapter))
    task = asyncio.ensure_future(flow.execute("Build it"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (trace,) = flow._traces.values()
    assert trace.status == WorkflowStatus.FAILED
    assert trace.completed_at is not None
    assert adapter.terminated == 1


@pytest.mark.asyncio
async def test_company_flow_charges_actual_adapter_cost_only():
    enforcer = types.SimpleNamespace(events=[])
    enforcer.check_can_spend = lambda *a, **k: types.SimpleNamespace(
        decision=types.SimpleNamespace(value="allowed")
    )
    enforcer.on_cost_event = lambda *a, **k: enforcer.events.append(a)

    flow = CompanyWorkflow(
        company_id=COMPANY_ID,
        budget_enforcer=enforcer,
        adapter_registry=_Registry(_Adapter(cost_cents=3)),
    )
    trace = await flow.execute("Build it", estimated_cost_cents=10_000)
    assert trace.status == WorkflowStatus.COMPLETED
    engineers = _engineer_steps(trace)
    assert all(s.cost_cents == 3 for s in engineers)
    assert [e[2] for e in enforcer.events] == [3] * len(engineers)


# --- TaskFlow --------------------------------------------------------------


def _task_flow(**kwargs) -> TaskFlow:
    flow = TaskFlow(company_id=COMPANY_ID, **kwargs)
    flow.register_agent("agent-1", capabilities=["code"], adapter_type="not-registered")
    return flow


@pytest.mark.asyncio
async def test_task_flow_without_registry_is_blocked():
    flow = _task_flow()
    execution = await flow.execute_task("t1", {"objective": "x"})
    assert execution.status == TaskStatus.BLOCKED
    assert execution.error == "Adapter registry unavailable - task not executed"
    assert not execution.result
    assert flow.get_result("t1") is None


@pytest.mark.asyncio
async def test_task_flow_unregistered_adapter_is_blocked_end_to_end():
    """Through the real activity: its own registry has no such adapter type."""
    flow = _task_flow(adapter_registry=_Registry())
    execution = await flow.execute_task("t1", {"objective": "x"}, max_attempts=3)
    assert execution.status == TaskStatus.BLOCKED
    assert execution.error == "Adapter unavailable: not-registered"
    assert execution.attempt == 1
    assert flow.get_result("t1") is None


@pytest.mark.asyncio
async def test_task_flow_exception_is_not_success_and_does_not_leak():
    flow = _task_flow(adapter_registry=_Registry())

    async def boom(execution, agent):
        raise TimeoutError(SECRET)

    flow._do_execute = boom  # type: ignore[method-assign]
    execution = await flow.execute_task("t1", {"objective": "x"}, max_attempts=2)
    assert execution.status == TaskStatus.ESCALATED
    assert execution.error == "Execution failed: TimeoutError"
    assert SECRET not in repr(execution)
    assert flow.get_result("t1") is None


@pytest.mark.asyncio
async def test_task_flow_cancellation_is_terminal_not_success():
    flow = _task_flow(adapter_registry=_Registry())

    async def cancelled(execution, agent):
        raise asyncio.CancelledError

    flow._do_execute = cancelled  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await flow.execute_task("t1", {"objective": "x"})
    (execution,) = flow.list_executions()
    assert execution.status == TaskStatus.FAILED
    assert execution.error == "Execution cancelled"
    assert execution.completed_at is not None


def test_task_flow_validation_rejects_success_without_output():
    flow = _task_flow()
    assert flow._validate_result({"status": "success", "output": ""}) is False
    assert flow._validate_result({"status": "failed", "output": "something"}) is False
    assert flow._validate_result({"status": "success", "output": "done"}) is True


# --- execute_task_activity -------------------------------------------------


@pytest.mark.asyncio
async def test_activity_unregistered_adapter_is_blocked():
    out = await execute_task_activity(
        ExecuteTaskInput(task_id="t1", agent_id="a1", adapter_type="not-registered")
    )
    assert (out.success, out.status, out.output) == (False, "blocked", "")
    assert out.error == "Adapter unavailable: not-registered"


@pytest.mark.asyncio
async def test_activity_adapter_exception_reports_type_only(monkeypatch, caplog):
    import nexus.adapters.registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "AdapterRegistry",
        lambda: _Registry(_Adapter(raises=RuntimeError(SECRET))),
    )
    out = await execute_task_activity(
        ExecuteTaskInput(task_id="t1", agent_id="a1", adapter_type="fake")
    )
    assert out.success is False
    assert out.status == "failed"
    assert out.error == "Adapter execution failed: RuntimeError"
    assert SECRET not in repr(out)
    assert SECRET not in caplog.text
