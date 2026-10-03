"""The legacy executor and checkpoint recovery never touch marked work.

A work order and its children belong to ``work_service`` and ``task_attempts``. These tests run
the real ``TaskExecutor`` escalations and the real stale/checkpoint recovery passes against a
marked order, a marked child and an awaiting-review attempt, next to ordinary legacy tasks that
must behave exactly as before. The model and the adapter are fakes, time is a fake clock, and
nothing sleeps or leaves the process.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from nexus.models._time import utcnow
from nexus.models.agent import Agent
from nexus.models.governance import AuditLog
from nexus.models.task import RunCompletionReason, Task
from nexus.models.task_attempt import TaskAttempt
from nexus.runtime import orchestrator
from nexus.runtime import task_attempts as ta
from nexus.runtime.adapter import AgentSession, TaskResult
from nexus.runtime.checkpoint import DurableCheckpointService
from nexus.runtime.executor import TaskExecutionError, TaskExecutor
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_work_service import (  # noqa: F401 -- fixtures and helpers
    _assign,
    _delegate,
    _get,
    _order,
    _review,
    _submitted,
    co,
)

pytestmark = pytest.mark.employee_work

NOW = utcnow().replace(microsecond=0)
STALE = timedelta(seconds=orchestrator.STALE_SUBTASK_SECONDS + 1)


class FailingAdapter:
    """Every call fails; ``errors`` is cycled so a test picks the escalation it wants."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        self.calls = 0

    async def execute_task(self, session, task_id, payload) -> TaskResult:
        error = self.errors[self.calls % len(self.errors)]
        self.calls += 1
        return TaskResult(task_id=task_id, agent_id=session.agent_id, success=False, error=error)


# Three different errors: REASSIGN. "too large": DECOMPOSE.
REASSIGN_ERRORS = ["boom one", "bang two", "crash three"]
DECOMPOSE_ERRORS = ["input is too large"]


def _session(agent_id) -> AgentSession:
    return AgentSession(session_id=str(uuid.uuid4()), agent_id=agent_id, adapter_type="fake")


async def _candidates(co):
    """Make every agent, in both companies, a valid reassignment candidate.

    Without this the router finds nobody and a REASSIGN would be a no-op, so a test that
    expects 'nothing moved' would pass vacuously.
    """
    async with co["db"]() as s:
        for agent in await _rows(co["db"], Agent):
            row = await s.get(Agent, agent.id)
            row.status, row.budget_monthly_cents = "ready", 10_000
        await s.commit()


async def _run(co, task_id, agent_id, errors, retries=2) -> tuple[FailingAdapter, str]:
    """Run the real executor; returns the adapter and the final error text."""
    adapter = FailingAdapter(errors)
    async with co["db"]() as s:
        task = await s.get(Task, task_id)
        with pytest.raises(TaskExecutionError) as caught:
            await TaskExecutor(s, adapter, max_retries=retries).execute(task, _session(agent_id))
        await s.commit()
    return adapter, caught.value.last_error


async def _ordinary(co, agent="acme_eve", status="pending", company="acme"):
    async with co["db"]() as s:
        task = Task(
            company_id=co[company],
            title="Plain legacy task",
            assigned_agent_id=co[f"{company}_{agent.split('_')[-1]}"],
            status=status,
        )
        s.add(task)
        await s.commit()
        return task.id


async def _marked(co, key="k1"):
    """A delegated, assigned work order (root, child, attempt), run to its first attempt."""
    work = await _order(co, key)
    await _delegate(co, work)
    child, attempt, _ = await _assign(co, work, key=f"a-{key}")
    await ta.drain()
    return work, child.id, attempt.id


async def _fingerprint(co, *task_ids):
    rows = []
    for task_id in task_ids:
        t = await _get(co, Task, task_id)
        rows.append(
            (t.status, t.assigned_agent_id, t.parent_task_id, t.result, t.error, t.started_at)
        )
    attempts = await _rows(co["db"], TaskAttempt)
    attempt_state = sorted((str(a.id), a.status, a.attempt_number) for a in attempts)
    return rows, len(await _rows(co["db"], Task)), attempt_state


async def _audit(co):
    return sorted(r.action for r in await _rows(co["db"], AuditLog))


class TestExecutorEscalation:
    @pytest.mark.parametrize("which", ["root", "child"])
    async def test_reassign_is_a_blocker_and_changes_nothing(self, which, co):
        work, child, _ = await _marked(co)
        await _candidates(co)
        target = work if which == "root" else child
        owner = (await _get(co, Task, target)).assigned_agent_id
        before = await _fingerprint(co, work, child)
        audit = await _audit(co)
        calls = co["model"].calls

        adapter, error = await _run(co, target, owner, REASSIGN_ERRORS)

        assert adapter.calls == 3  # first try and two retries
        assert error.startswith("[BLOCKER]")
        assert "REASSIGN" not in error and "DECOMPOSE" not in error
        assert await _fingerprint(co, work, child) == before
        assert await _audit(co) == audit
        assert co["model"].calls == calls

    @pytest.mark.parametrize("which", ["root", "child"])
    async def test_decompose_creates_no_generic_child(self, which, co):
        work, child, _ = await _marked(co)
        await _candidates(co)
        target = work if which == "root" else child
        owner = (await _get(co, Task, target)).assigned_agent_id
        before = await _fingerprint(co, work, child)
        audit = await _audit(co)

        _, error = await _run(co, target, owner, DECOMPOSE_ERRORS, retries=1)

        assert error.startswith("[BLOCKER]") and "DECOMPOSED" not in error
        assert await _fingerprint(co, work, child) == before  # same Task count, same rows
        assert await _audit(co) == audit

    async def test_an_unauthorized_agent_cannot_run_marked_work(self, co):
        work, child, _ = await _marked(co)
        before = await _fingerprint(co, work, child)
        adapter = FailingAdapter(REASSIGN_ERRORS)
        async with co["db"]() as s:
            task = await s.get(Task, child)
            with pytest.raises(PermissionError):
                await TaskExecutor(s, adapter).execute(task, _session(co["acme_zed"]))
        assert adapter.calls == 0
        assert await _fingerprint(co, work, child) == before

    async def test_a_foreign_company_agent_cannot_run_marked_work(self, co):
        work, child, _ = await _marked(co)
        before = await _fingerprint(co, work, child)
        adapter = FailingAdapter(REASSIGN_ERRORS)
        async with co["db"]() as s:
            task = await s.get(Task, child)
            with pytest.raises(ValueError, match="not found"):
                await TaskExecutor(s, adapter).execute(task, _session(co["other_eve"]))
        assert adapter.calls == 0
        assert await _fingerprint(co, work, child) == before

    async def test_the_result_never_names_the_task_as_reassigned(self, co):
        """The audit/error trail must not claim a mutation that was refused."""
        work, child, _ = await _marked(co)
        await _candidates(co)
        owner = (await _get(co, Task, child)).assigned_agent_id
        _, error = await _run(co, child, owner, REASSIGN_ERRORS)
        assert "[REASSIGNED" not in error and "[DECOMPOSED" not in error
        assert not [a for a in await _audit(co) if "reassign" in a or "decompos" in a]


class TestExecutorControls:
    """Ordinary legacy tasks keep their escalation behaviour."""

    async def test_an_ordinary_task_is_reassigned_within_its_company(self, co):
        task = await _ordinary(co)
        await _candidates(co)  # other company's agents are candidates too, and must not win
        _, error = await _run(co, task, co["acme_eve"], REASSIGN_ERRORS)
        row = await _get(co, Task, task)
        assert error.startswith("[REASSIGNED to ")
        assert row.assigned_agent_id != co["acme_eve"]
        chosen = await _get(co, Agent, row.assigned_agent_id)
        assert chosen.company_id == co["acme"]

    async def test_an_ordinary_task_is_decomposed(self, co):
        task = await _ordinary(co)
        _, error = await _run(co, task, co["acme_eve"], DECOMPOSE_ERRORS, retries=1)
        assert error.startswith("[DECOMPOSED into ")
        children = await _rows(co["db"], Task, Task.parent_task_id == task)
        assert children and {c.company_id for c in children} == {co["acme"]}
        assert (await _get(co, Task, task)).status == "failed"

    async def test_an_ordinary_task_is_marked_running_then_failed(self, co):
        task = await _ordinary(co)
        await _run(co, task, co["acme_eve"], ["same", "same", "same"], retries=2)
        row = await _get(co, Task, task)
        assert row.status == "failed" and row.error.startswith("[BLOCKER]")

    async def test_ordinary_variants_refuse_foreign_and_unauthorized_agents(self, co):
        task = await _ordinary(co)
        adapter = FailingAdapter(REASSIGN_ERRORS)
        for agent, error in ((co["acme_zed"], PermissionError), (co["other_eve"], ValueError)):
            async with co["db"]() as s:
                row = await s.get(Task, task)
                with pytest.raises(error):
                    await TaskExecutor(s, adapter).execute(row, _session(agent))
        assert adapter.calls == 0
        row = await _get(co, Task, task)
        assert (row.status, row.assigned_agent_id) == ("pending", co["acme_eve"])


class _Clock:
    def __call__(self):
        return NOW


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(orchestrator, "utcnow", _Clock())
    return NOW


async def _checkpoint(co, task_id):
    async with co["db"]() as s:
        await DurableCheckpointService.save_checkpoint(task_id, 2, {"step": "half-done"}, s)
        await s.commit()


async def _make_stale(co, task_id, status="in_progress", reason=None):
    async with co["db"]() as s:
        row = await s.get(Task, task_id)
        row.status = status
        row.started_at = NOW - STALE
        if reason:
            row.completion_reason = reason
        await s.commit()


async def _recover(co) -> tuple[int, int]:
    async with co["db"]() as s:
        reaped = await orchestrator._reap_stale_subtasks(s)
        await s.commit()
    async with co["db"]() as s:
        restored = await orchestrator.reconcile_recovery(s)
        await s.commit()
    return reaped, restored


class TestCheckpointRecovery:
    async def test_marked_root_and_child_are_skipped(self, co, clock):
        work, child, _ = await _marked(co)
        await _make_stale(co, work)
        await _make_stale(co, child)
        for task in (work, child):
            await _checkpoint(co, task)
        before = await _fingerprint(co, work, child)
        calls = co["model"].calls

        assert await _recover(co) == (0, 0)

        assert await _fingerprint(co, work, child) == before
        assert co["model"].calls == calls

    async def test_a_failed_marked_child_with_a_timeout_reason_is_skipped(self, co, clock):
        work, child, _ = await _marked(co)
        await _make_stale(co, child, "failed", RunCompletionReason.timeout)
        await _checkpoint(co, child)
        before = await _fingerprint(co, work, child)

        assert await _recover(co) == (0, 0)

        assert await _fingerprint(co, work, child) == before

    async def test_an_awaiting_review_attempt_stays_reviewable(self, co, clock):
        work, task, attempt = await _submitted(co)
        await _make_stale(co, work)
        await _checkpoint(co, work)
        await _checkpoint(co, task)
        before = await _fingerprint(co, work, task)
        calls = co["model"].calls

        assert await _recover(co) == (0, 0)

        assert await _fingerprint(co, work, task) == before
        assert co["model"].calls == calls
        assert (await _get(co, TaskAttempt, attempt)).status == "verifying"
        done, changed = await _review(co, attempt)
        assert changed and done.status == "completed"
        assert (await _get(co, Task, task)).status == "completed"

    async def test_an_ordinary_task_with_a_checkpoint_is_still_restored(self, co, clock):
        work, child, _ = await _marked(co)
        await _make_stale(co, work)
        await _checkpoint(co, work)
        plain = await _ordinary(co, status="in_progress")
        await _make_stale(co, plain)
        await _checkpoint(co, plain)

        # reap flags the plain claim for recovery; reconcile restores it. Only it, never work.
        assert await _recover(co) == (1, 1)

        row = await _get(co, Task, plain)
        assert (row.status, row.error, row.started_at) == ("pending", None, None)
        assert (await _get(co, Task, work)).status == "in_progress"

    async def test_an_ordinary_stale_claim_without_a_checkpoint_is_reaped(self, co, clock):
        plain = await _ordinary(co, status="in_progress")
        await _make_stale(co, plain)
        assert (await _recover(co))[0] == 1
        row = await _get(co, Task, plain)
        assert (row.status, row.completion_reason) == ("failed", RunCompletionReason.timeout)
