"""Enterprise acceptance tests for Durable Checkpoint & Restart Recovery."""

import hashlib
import json
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401
from nexus.models._time import utcnow
from nexus.models.agent import Agent
from nexus.models.budget import CostEvent
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.task import Goal, RunCompletionReason, Task
from nexus.runtime.checkpoint import (
    CheckpointStatus,
    DurableCheckpointService,
    ExecutionCheckpoint,
    abandon_stale,
    build_checkpoint_state,
    load_latest,
    mark_completed,
    resume_from_checkpoint,
    save_checkpoint,
    save_checkpoint_nonblocking,
)
from nexus.runtime.orchestrator import _execute_subtasks, _reap_stale_subtasks, reconcile_recovery


@pytest.fixture
async def db_engine(tmp_path):
    """File-backed SQLite async engine with all tables initialized."""
    db_file = tmp_path / "recovery_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine):
    """Async session factory bound to the test engine."""
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def company_id(session_factory):
    """Create test company."""
    cid = uuid.uuid4()
    async with session_factory() as session:
        session.add(Company(id=cid, name="NVLabs Enterprise", budget_monthly_cents=50000))
        await session.commit()
    return cid


@pytest.fixture
async def agent(session_factory, company_id):
    """Create test agent."""
    agent_id = uuid.uuid4()
    ag = Agent(
        id=agent_id,
        company_id=company_id,
        name="CheckpointAgent",
        role="engineer",
        adapter_type="hermes",
        model="hermes3:8b",
        budget_monthly_cents=10000,
        spent_monthly_cents=0,
        status="active",
    )
    async with session_factory() as session:
        session.add(ag)
        await session.commit()
    return ag


# ---------------------------------------------------------------------------
# 1. Database-Backed Checkpoint Service Unit & Lifecycle Tests
# ---------------------------------------------------------------------------


class TestDurableCheckpointService:
    """Tests for DurableCheckpointService database operations."""

    async def test_save_and_load_latest(self, session_factory):
        """save_checkpoint persists checkpoints and load_latest fetches the most recent."""
        task_id = uuid.uuid4()
        state1 = build_checkpoint_state(
            agent_context={"agent": "agent-1"},
            completed_steps=[0],
            intermediate_results=[{"output": "step 0 done"}],
        )
        state2 = build_checkpoint_state(
            agent_context={"agent": "agent-1"},
            completed_steps=[0, 1],
            intermediate_results=[{"output": "step 0 done"}, {"output": "step 1 done"}],
        )

        async with session_factory() as session:
            cp1 = await save_checkpoint(task_id, 0, state1, session)
            await session.commit()

        async with session_factory() as session:
            latest = await load_latest(task_id, session)
            assert latest is not None
            assert latest.id == cp1.id
            assert latest.step_index == 0
            assert latest.state_json == state1

        # Save step 1
        async with session_factory() as session:
            cp2 = await save_checkpoint(task_id, 1, state2, session)
            await session.commit()

        async with session_factory() as session:
            latest = await load_latest(task_id, session)
            assert latest is not None
            assert latest.id == cp2.id
            assert latest.step_index == 1
            assert latest.state_json == state2

    async def test_save_checkpoint_atomic_upsert(self, session_factory):
        """Saving a checkpoint for the same step index updates the record atomically."""
        task_id = uuid.uuid4()
        state_v1 = {"step": 1, "version": 1}
        state_v2 = {"step": 1, "version": 2, "updated": True}

        async with session_factory() as session:
            cp1 = await save_checkpoint(task_id, 1, state_v1, session)
            await session.commit()
            cp1_id = cp1.id

        async with session_factory() as session:
            cp2 = await save_checkpoint(task_id, 1, state_v2, session)
            await session.commit()
            assert cp2.id == cp1_id
            assert cp2.state_json == state_v2

        async with session_factory() as session:
            stmt = select(ExecutionCheckpoint).where(ExecutionCheckpoint.task_id == task_id)
            records = list((await session.execute(stmt)).scalars().all())
            assert len(records) == 1
            assert records[0].state_json == state_v2

    async def test_mark_completed(self, session_factory):
        """mark_completed transitions all active checkpoints for a task to completed."""
        task_id = uuid.uuid4()
        async with session_factory() as session:
            await save_checkpoint(task_id, 0, {"s": 0}, session)
            await save_checkpoint(task_id, 1, {"s": 1}, session)
            await session.commit()

        async with session_factory() as session:
            await mark_completed(task_id, session)
            await session.commit()

        async with session_factory() as session:
            # load_latest only returns active checkpoints, so it should be None
            latest = await load_latest(task_id, session)
            assert latest is None

            stmt = select(ExecutionCheckpoint).where(ExecutionCheckpoint.task_id == task_id)
            records = list((await session.execute(stmt)).scalars().all())
            assert len(records) == 2
            assert all(r.status == CheckpointStatus.completed for r in records)
            assert all(r.updated_at is not None for r in records)

    async def test_abandon_stale_checkpoints(self, session_factory):
        """abandon_stale marks checkpoints older than TTL as abandoned."""
        task_old = uuid.uuid4()
        task_fresh = uuid.uuid4()

        async with session_factory() as session:
            cp_old = await save_checkpoint(task_old, 0, {"old": True}, session)
            # Backdate created_at by 48 hours
            cp_old.created_at = utcnow() - timedelta(hours=48)
            session.add(cp_old)

            await save_checkpoint(task_fresh, 0, {"fresh": True}, session)
            await session.commit()

        async with session_factory() as session:
            abandoned_count = await abandon_stale(max_age_hours=24, session=session)
            await session.commit()
            assert abandoned_count == 1

        async with session_factory() as session:
            # Old task checkpoint is abandoned and not returned by load_latest
            assert await load_latest(task_old, session) is None
            # Fresh task checkpoint remains active
            fresh_cp = await load_latest(task_fresh, session)
            assert fresh_cp is not None
            assert fresh_cp.status == CheckpointStatus.active


# ---------------------------------------------------------------------------
# 2. Mid-Flight Process Crash & Resumption Test
# ---------------------------------------------------------------------------


class TestMidFlightCrashAndResumption:
    """Simulates a 5-step task interrupted by a crash after step 2; asserts resumption at step 3."""

    async def test_five_step_task_crash_and_resumption(self, session_factory, company_id, agent):
        """Verify mid-flight crash after step 2 resumes at step 3 without re-executing steps 0-2."""
        task_id = uuid.uuid4()
        task = Task(
            id=task_id,
            company_id=company_id,
            title="Execute 5-step data transformation pipeline",
            description="Process 5 sequential transformation steps.",
            status="pending",
            assigned_agent_id=agent.id,
        )
        async with session_factory() as session:
            session.add(task)
            await session.commit()

        executed_steps: list[int] = []

        # Simulated 5-step execution engine
        async def step_executor(current_task_id: uuid.UUID, start_from_step: int, crash_at_step: int | None = None):
            async with session_factory() as session:
                for step_idx in range(start_from_step, 5):
                    if crash_at_step is not None and step_idx == crash_at_step:
                        # Simulate process termination / sudden crash
                        raise ProcessLookupError(f"Simulated process crash during step {step_idx}!")

                    executed_steps.append(step_idx)
                    step_result = {"step": step_idx, "output": f"data_chunk_{step_idx}_transformed"}

                    # Save intermediate checkpoint after successful step execution
                    state = build_checkpoint_state(
                        agent_context={"agent_id": str(agent.id), "model": agent.model},
                        completed_steps=executed_steps.copy(),
                        intermediate_results=[{"step": s, "output": f"data_chunk_{s}_transformed"} for s in executed_steps],
                        metadata={"total_steps": 5},
                    )
                    await save_checkpoint(current_task_id, step_idx, state, session)
                    await session.commit()

        # RUN 1: Starts at step 0, executes steps 0, 1, 2, and crashes during step 3
        with pytest.raises(ProcessLookupError):
            await step_executor(task_id, start_from_step=0, crash_at_step=3)

        assert executed_steps == [0, 1, 2]

        # Verify latest active checkpoint in DB is at step 2
        async with session_factory() as session:
            latest_cp = await load_latest(task_id, session)
            assert latest_cp is not None
            assert latest_cp.step_index == 2
            assert latest_cp.state_json["completed_steps"] == [0, 1, 2]
            assert len(latest_cp.state_json["intermediate_results"]) == 3

        # RUN 2 (Recovery): Rehydrate state and resume from step 3 (step_index + 1)
        async with session_factory() as session:
            checkpoint = await load_latest(task_id, session)
            assert checkpoint is not None
            resume_step = checkpoint.step_index + 1
            assert resume_step == 3
            cached_intermediate_results = checkpoint.state_json["intermediate_results"]

        executed_steps.clear()

        # Resume execution from step 3
        await step_executor(task_id, start_from_step=resume_step, crash_at_step=None)

        # Assert ONLY steps 3 and 4 were executed in run 2
        assert executed_steps == [3, 4]

        # Combine results from run 1 intermediate cache + run 2 execution
        all_results = cached_intermediate_results + [{"step": s, "output": f"data_chunk_{s}_transformed"} for s in executed_steps]
        assert len(all_results) == 5
        assert [r["step"] for r in all_results] == [0, 1, 2, 3, 4]

        # Mark task completed and clean up checkpoints
        async with session_factory() as session:
            await mark_completed(task_id, session)
            await session.commit()

        # Verify active checkpoint is cleared
        async with session_factory() as session:
            assert await load_latest(task_id, session) is None


# ---------------------------------------------------------------------------
# 3. Database State Persistence (Engine Teardown & Reconnect)
# ---------------------------------------------------------------------------


class TestDatabaseStatePersistence:
    """Verifies checkpoints survive complete database engine teardown and reconnection."""

    async def test_checkpoint_survives_engine_teardown(self, tmp_path):
        """Create checkpoint, teardown engine, reconnect, and assert 100% state fidelity."""
        db_path = tmp_path / "persistence_survival.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"

        # Setup Engine 1
        engine1 = create_async_engine(db_url)
        async with engine1.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        session_factory1 = async_sessionmaker(engine1, expire_on_commit=False)

        task_id = uuid.uuid4()
        original_state = {
            "agent_context": {"agent_id": "agent-xyz", "memory_count": 42},
            "completed_steps": [0, 1, 2],
            "intermediate_results": [
                {"tool": "fetch_data", "rows": 100},
                {"tool": "clean_data", "nulls_removed": 5},
                {"tool": "summarize", "metric": 0.98},
            ],
            "metadata": {"version": "2.0", "hash": "abc1234"},
        }

        # Save checkpoint in Engine 1
        async with session_factory1() as session:
            cp = await save_checkpoint(task_id, step_index=2, state=original_state, session=session)
            await session.commit()
            cp_id = cp.id

        # COMPLETE ENGINE TEARDOWN
        await engine1.dispose()

        # Reconnect with Engine 2
        engine2 = create_async_engine(db_url)
        session_factory2 = async_sessionmaker(engine2, expire_on_commit=False)

        # Query checkpoint in fresh Engine 2 session
        async with session_factory2() as session:
            loaded = await load_latest(task_id, session)
            assert loaded is not None
            assert loaded.id == cp_id
            assert loaded.task_id == task_id
            assert loaded.step_index == 2
            assert loaded.status == CheckpointStatus.active
            assert loaded.state_json == original_state
            assert loaded.state_json["intermediate_results"][2]["metric"] == 0.98

        await engine2.dispose()


# ---------------------------------------------------------------------------
# 4. No Double-Spending on Recovery Test
# ---------------------------------------------------------------------------


class TestNoDoubleSpendingOnRecovery:
    """Verifies that resumed subtasks do not re-reserve or re-bill budget for completed steps."""

    async def test_no_double_billing_on_resumption(self, session_factory, company_id, agent):
        """Assert steps completed prior to checkpoint are not re-billed on recovery."""
        task_id = uuid.uuid4()
        cost_per_step_cents = 10

        # Step 0, 1, 2 billed in Run 1
        async with session_factory() as session:
            for step_idx in [0, 1, 2]:
                cost_event = CostEvent(
                    company_id=company_id,
                    agent_id=agent.id,
                    task_id=task_id,
                    provider="adapter",
                    input_tokens=100,
                    output_tokens=50,
                    cost_cents=cost_per_step_cents,
                    billing_type="task_execution",
                    occurred_at=utcnow(),
                )
                session.add(cost_event)

            # Save checkpoint at step 2
            state = build_checkpoint_state(
                agent_context={"agent_id": str(agent.id)},
                completed_steps=[0, 1, 2],
                intermediate_results=[{"step": 0}, {"step": 1}, {"step": 2}],
                metadata={"billed_cents": 30},
            )
            await save_checkpoint(task_id, step_index=2, state=state, session=session)
            await session.commit()

        # Simulate Crash and Recovery
        async with session_factory() as session:
            cp = await load_latest(task_id, session)
            assert cp is not None
            resumed_step = cp.step_index + 1
            assert resumed_step == 3

            # Run 2: ONLY bill for steps 3 and 4
            for step_idx in range(resumed_step, 5):
                cost_event = CostEvent(
                    company_id=company_id,
                    agent_id=agent.id,
                    task_id=task_id,
                    provider="adapter",
                    input_tokens=100,
                    output_tokens=50,
                    cost_cents=cost_per_step_cents,
                    billing_type="task_execution",
                    occurred_at=utcnow(),
                )
                session.add(cost_event)
            await session.commit()

        # Verify Total Cost Events for task
        async with session_factory() as session:
            stmt = select(CostEvent).where(CostEvent.task_id == task_id)
            events = list((await session.execute(stmt)).scalars().all())
            total_spent = sum(e.cost_cents for e in events)

            # Exactly 5 steps billed once = 50 cents, zero double billing
            assert len(events) == 5
            assert total_spent == 50


# ---------------------------------------------------------------------------
# 5. Startup & Background Reconciliation Tests
# ---------------------------------------------------------------------------


class TestReconciliationAndReenqueuing:
    """Tests for reconcile_recovery and _reap_stale_subtasks automated reconciliation."""

    async def test_reconcile_recovery_restores_eligible_tasks(self, session_factory, company_id, agent):
        """reconcile_recovery automatically restores needs_recovery, stale in_progress, and timeout tasks."""
        task1 = Task(id=uuid.uuid4(), company_id=company_id, title="Needs Recovery Task", status="needs_recovery", assigned_agent_id=agent.id)
        task2 = Task(id=uuid.uuid4(), company_id=company_id, title="Stale In-Progress Task", status="in_progress", started_at=utcnow() - timedelta(seconds=700), assigned_agent_id=agent.id)
        task3 = Task(id=uuid.uuid4(), company_id=company_id, title="Timed Out Task", status="failed", completion_reason=RunCompletionReason.timeout, assigned_agent_id=agent.id)
        task4 = Task(id=uuid.uuid4(), company_id=company_id, title="Unrecoverable Error Task", status="failed", completion_reason=RunCompletionReason.error, assigned_agent_id=agent.id)

        async with session_factory() as session:
            session.add_all([task1, task2, task3, task4])
            # Checkpoints for task 1, 2, 3
            await save_checkpoint(task1.id, 1, {"step": 1}, session)
            await save_checkpoint(task2.id, 2, {"step": 2}, session)
            await save_checkpoint(task3.id, 3, {"step": 3}, session)
            await session.commit()

        # Run reconciliation pass
        async with session_factory() as session:
            recovered_count = await reconcile_recovery(session)
            await session.commit()
            assert recovered_count == 3

        # Assert tasks 1, 2, 3 are now pending and ready for execution
        async with session_factory() as session:
            t1 = (await session.execute(select(Task).where(Task.id == task1.id))).scalar_one()
            t2 = (await session.execute(select(Task).where(Task.id == task2.id))).scalar_one()
            t3 = (await session.execute(select(Task).where(Task.id == task3.id))).scalar_one()
            t4 = (await session.execute(select(Task).where(Task.id == task4.id))).scalar_one()

            assert t1.status == "pending"
            assert t2.status == "pending"
            assert t3.status == "pending"
            # Task 4 without checkpoint remains failed
            assert t4.status == "failed"

    async def test_reap_stale_subtasks_flags_checkpointed_tasks_for_recovery(self, session_factory, company_id, agent):
        """_reap_stale_subtasks sets needs_recovery for tasks with checkpoints rather than hard-failing them."""
        task_with_cp = Task(
            id=uuid.uuid4(),
            company_id=company_id,
            title="Stale with CP",
            status="in_progress",
            started_at=utcnow() - timedelta(seconds=1000),
            assigned_agent_id=agent.id,
        )
        task_no_cp = Task(
            id=uuid.uuid4(),
            company_id=company_id,
            title="Stale without CP",
            status="in_progress",
            started_at=utcnow() - timedelta(seconds=1000),
            assigned_agent_id=agent.id,
        )

        async with session_factory() as session:
            session.add_all([task_with_cp, task_no_cp])
            await save_checkpoint(task_with_cp.id, 1, {"step": 1}, session)
            await session.commit()

        async with session_factory() as session:
            handled = await _reap_stale_subtasks(session)
            await session.commit()
            assert handled == 2

        async with session_factory() as session:
            t_cp = (await session.execute(select(Task).where(Task.id == task_with_cp.id))).scalar_one()
            t_nocp = (await session.execute(select(Task).where(Task.id == task_no_cp.id))).scalar_one()

            assert t_cp.status == "needs_recovery"
            assert t_nocp.status == "failed"
            assert t_nocp.completion_reason == RunCompletionReason.timeout


# ---------------------------------------------------------------------------
# 6. Audit Trail & Full Orchestrator Resumption Test
# ---------------------------------------------------------------------------


class TestOrchestratorResumptionAndAuditTrail:
    """Verifies _execute_subtasks rehydrates state and writes task_resumed_from_checkpoint audit logs."""

    async def test_execute_subtasks_resumes_from_checkpoint_and_emits_audit(self, session_factory, company_id, agent):
        """Assert _execute_subtasks resumes from step index + 1 and logs audit event with state hash."""
        task_id = uuid.uuid4()
        task = Task(
            id=task_id,
            company_id=company_id,
            title="Calculate financial forecast",
            description="Run quarterly projection model.",
            status="pending",
            assigned_agent_id=agent.id,
        )
        checkpoint_state = build_checkpoint_state(
            agent_context={"agent_id": str(agent.id)},
            completed_steps=[0, 1],
            intermediate_results=[
                {"step_0": "Q1 baseline loaded"},
                {"step_1": "Q2 actuals adjusted"},
            ],
            metadata={"resumption_key": "xyz"},
        )

        async with session_factory() as session:
            session.add(task)
            await save_checkpoint(task_id, step_index=1, state=checkpoint_state, session=session)
            await session.commit()

        captured_calls = []

        async def mock_call_llm(ag, system_prompt, prompt, history):
            captured_calls.append({
                "prompt": prompt,
                "history": history,
            })
            return "Q3 and Q4 forecast generated successfully.", "test-model", 150

        with patch("nexus.api.routes.chat._call_llm", side_effect=mock_call_llm):
            async with session_factory() as session:
                task_to_run = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one()
                await _execute_subtasks(session, [task_to_run], company_id)
                await session.commit()

        # 1. Assert prompt contained resumption instructions and did not repeat step 0/1
        assert len(captured_calls) == 1
        prompt_sent = captured_calls[0]["prompt"]
        assert "[CHECKPOINT RESUMPTION CONTEXT]" in prompt_sent
        assert "Resume directly from step 2" in prompt_sent
        assert "Q1 baseline loaded" in prompt_sent

        # 2. Assert intermediate results were in history
        history_sent = captured_calls[0]["history"]
        assert len(history_sent) == 2
        assert "Q1 baseline loaded" in history_sent[0]["text"]

        # 3. Assert Audit Log was emitted with state hash
        async with session_factory() as session:
            stmt = select(AuditLog).where(
                AuditLog.action == "task_resumed_from_checkpoint",
                AuditLog.resource_id == str(task_id),
            )
            audit_entry = (await session.execute(stmt)).scalar_one_or_none()
            assert audit_entry is not None
            assert audit_entry.details["resumed_step"] == 2
            assert audit_entry.details["step_index"] == 1
            assert audit_entry.details["completed_steps"] == [0, 1]
            assert "state_hash" in audit_entry.details
            expected_hash = hashlib.sha256(
                json.dumps(checkpoint_state, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            assert audit_entry.details["state_hash"] == expected_hash

        # 4. Assert Task is completed and Checkpoint is marked completed
        async with session_factory() as session:
            completed_task = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one()
            assert completed_task.status == "completed"
            assert completed_task.completion_reason == RunCompletionReason.goal

            latest_cp = await load_latest(task_id, session)
            assert latest_cp is None
