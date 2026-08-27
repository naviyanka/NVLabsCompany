"""Phase 0.4a — the Temporal activity layer.

Covers the three invariants ADR 0001 puts on this layer:

1. Every activity and workflow carries a real SDK definition, so the worker can
   register them (a missing decorator used to fail only at worker startup).
2. The same activity functions run in-process when not inside a workflow — the
   fallback runner is one code path, two runners.
3. A billed activity runs once only. A retried workflow shows one billed call,
   not two.

Plus the phase acceptance test: killing the worker mid-run resumes the run.
"""

import uuid

import pytest

from nexus.temporal._sdk import HAS_SDK, ONCE_ONLY, RETRY_SAFE, execute_activity
from nexus.temporal.activities import (
    ALL_ACTIVITIES,
    ExecuteTaskInput,
    LLMCallInput,
    execute_task_activity,
)
from nexus.temporal.workflows import (
    ALL_WORKFLOWS,
    PipelineExecutionInput,
    PipelineExecutionOutput,
    PipelineExecutionWorkflow,
)

pytestmark = pytest.mark.skipif(not HAS_SDK, reason="temporalio not installed")

TASK_QUEUE = "nexus-test"


# ---------------------------------------------------------------------------
# 1. Definitions are registrable
# ---------------------------------------------------------------------------


def test_every_activity_has_a_definition():
    from temporalio.activity import _Definition

    names = [_Definition.must_from_callable(a).name for a in ALL_ACTIVITIES]
    assert "execute_task_activity" in names
    assert len(names) == len(set(names)), "duplicate activity names collide on the worker"


def test_every_workflow_has_a_definition_with_typed_args():
    from temporalio.workflow import _Definition

    for wf in ALL_WORKFLOWS:
        defn = _Definition.must_from_class(wf)
        # Untyped args silently skip payload conversion, so assert they resolved.
        assert defn.arg_types, f"{defn.name} has no resolved argument type"
        assert defn.ret_type is not None, f"{defn.name} has no resolved return type"


# ---------------------------------------------------------------------------
# 2. Fallback runner — activities run in-process outside a workflow
# ---------------------------------------------------------------------------


async def test_execute_activity_runs_in_process_outside_a_workflow():
    calls: list[int] = []

    async def fake_activity(arg: int) -> int:
        calls.append(arg)
        return arg * 2

    result = await execute_activity(fake_activity, 21)

    assert result == 42
    assert calls == [21], "activity should have been awaited directly, not dispatched"


async def test_execute_task_activity_simulates_without_a_registered_adapter():
    task_id = str(uuid.uuid4())
    out = await execute_task_activity(
        ExecuteTaskInput(task_id=task_id, agent_id="agent-1", adapter_type="not-registered")
    )

    assert out.success is True
    assert out.task_id == task_id
    assert out.status == "success"


async def test_task_flow_execution_goes_through_the_activity(monkeypatch):
    """The façade must dispatch through the activity, not re-implement adapter I/O."""
    from nexus.workflows.task_flow import TaskFlow, TaskStatus

    seen: list[ExecuteTaskInput] = []

    async def fake_execute(fn, arg, **kwargs):
        seen.append(arg)
        from nexus.temporal.activities import ExecuteTaskOutput

        return ExecuteTaskOutput(
            task_id=arg.task_id, success=True, output="done", status="success", cost_cents=7
        )

    monkeypatch.setattr("nexus.temporal._sdk.execute_activity", fake_execute)

    # A non-None registry is what selects the activity path.
    flow = TaskFlow(company_id=str(uuid.uuid4()), adapter_registry=object())
    flow.register_agent("agent-1", capabilities=["code"], adapter_type="claude_code")

    execution = await flow.execute_task(task_id="t-1", payload={"x": 1})

    assert execution.status == TaskStatus.COMPLETED
    assert len(seen) == 1
    assert seen[0].adapter_type == "claude_code"
    assert seen[0].payload == {"x": 1}


# ---------------------------------------------------------------------------
# 3 + acceptance. Needs a real Temporal test server.
# ---------------------------------------------------------------------------


@pytest.fixture
async def temporal_env():
    """A local time-skipping Temporal server, or skip when it cannot start.

    The SDK downloads a test-server binary on first use, which is not available
    in every sandbox, so an unreachable server skips rather than fails.
    """
    from temporalio.testing import WorkflowEnvironment

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as e:  # pragma: no cover — environment-dependent
        pytest.skip(f"Temporal test server unavailable: {e}")
    try:
        yield env
    finally:
        await env.shutdown()


async def test_billed_activity_is_attempted_once_only(temporal_env, monkeypatch):
    """A retried workflow shows one billed LLM call, not two."""
    from temporalio.worker import Worker

    from nexus.temporal import activities as acts

    attempts: list[str] = []

    @acts.activity_defn(name="call_llm_activity")
    async def failing_llm(input: LLMCallInput) -> acts.LLMCallOutput:
        attempts.append(input.prompt)
        raise RuntimeError("provider exploded")

    async with Worker(
        temporal_env.client,
        task_queue=TASK_QUEUE,
        workflows=ALL_WORKFLOWS,
        activities=[failing_llm],
    ):
        with pytest.raises(Exception):
            await temporal_env.client.execute_workflow(
                PipelineExecutionWorkflow.run,
                PipelineExecutionInput(
                    pipeline_id="p1",
                    run_id="r1",
                    company_id=str(uuid.uuid4()),
                    stages=[{"name": "one", "prompt": "hello"}],
                ),
                id=f"once-only-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

    assert len(attempts) == 1, f"billed activity retried {len(attempts)} times"


async def test_run_resumes_after_the_worker_dies(temporal_env):
    """Acceptance: the worker dies mid-run and a fresh worker resumes the run.

    The run is started against a worker that can host the workflow but cannot
    execute activities, so the first stage is pending when that worker is shut
    down. A second worker picks the same run up and drives it to completion.
    Each stage executes exactly once across both workers — resumption comes from
    Temporal's event history, not from re-running completed work.
    """
    from temporalio.worker import Worker

    from nexus.temporal import activities as acts

    executed: list[str] = []

    @acts.activity_defn(name="call_llm_activity")
    async def counting_llm(input: LLMCallInput) -> acts.LLMCallOutput:
        executed.append(input.prompt)
        return acts.LLMCallOutput(
            response_text="ok", model_used="test", tokens_used=1, success=True
        )

    workflow_id = f"resume-{uuid.uuid4()}"
    stages = [
        {"name": "one", "prompt": "first"},
        {"name": "two", "prompt": "second"},
    ]

    # Worker 1: hosts the workflow, has no activity workers. Then it dies.
    async with Worker(temporal_env.client, task_queue=TASK_QUEUE, workflows=ALL_WORKFLOWS):
        await temporal_env.client.start_workflow(
            PipelineExecutionWorkflow.run,
            PipelineExecutionInput(
                pipeline_id="p1", run_id="r1", company_id=str(uuid.uuid4()), stages=stages
            ),
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )

    assert executed == [], "no stage should have run before the worker died"

    # Worker 2 resumes the same run and finishes it.
    async with Worker(
        temporal_env.client,
        task_queue=TASK_QUEUE,
        workflows=ALL_WORKFLOWS,
        activities=[counting_llm],
    ):
        # Without result_type the handle decodes the payload as a plain dict.
        handle = temporal_env.client.get_workflow_handle(
            workflow_id, result_type=PipelineExecutionOutput
        )
        result = await handle.result()

    assert result.status == "completed"
    assert result.stages_completed == 2
    assert executed == ["first", "Previous output:\nok\n\nCurrent task:\nsecond"]


async def test_mid_activity_crash_does_not_silently_rebill(temporal_env):
    """A billed activity killed in flight fails the run rather than re-charging.

    This is the flip side of ONCE_ONLY: resumption granularity is *between*
    activities. An LLM call interrupted mid-flight is not retried, so the run
    surfaces a failure instead of quietly billing a second time.
    """
    from temporalio.worker import Worker

    from nexus.temporal import activities as acts

    attempts: list[str] = []

    @acts.activity_defn(name="call_llm_activity")
    async def dying_llm(input: LLMCallInput) -> acts.LLMCallOutput:
        attempts.append(input.prompt)
        raise RuntimeError("worker died mid-call")

    async with Worker(
        temporal_env.client,
        task_queue=TASK_QUEUE,
        workflows=ALL_WORKFLOWS,
        activities=[dying_llm],
    ):
        with pytest.raises(Exception):
            await temporal_env.client.execute_workflow(
                PipelineExecutionWorkflow.run,
                PipelineExecutionInput(
                    pipeline_id="p1",
                    run_id="r1",
                    company_id=str(uuid.uuid4()),
                    stages=[{"name": "one", "prompt": "hello"}],
                ),
                id=f"mid-crash-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

    assert len(attempts) == 1


def test_retry_ceilings_are_distinct():
    """A billed call and a retry-safe call must not share a retry ceiling."""
    assert ONCE_ONLY == 1
    assert RETRY_SAFE > ONCE_ONLY
