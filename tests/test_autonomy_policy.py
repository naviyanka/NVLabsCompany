"""Tests for Phase 3.4 - per-agent, per-action autonomy policy."""

import uuid
from typing import Any

from nexus.tools.autonomy import (
    ACTION_DELETE,
    ACTION_EXECUTE_CODE,
    ACTION_READ,
    ACTION_SEND_EXTERNAL_MESSAGE,
    ACTION_SPEND,
    ACTION_WRITE_FILE,
    AutonomyGate,
    classify_action,
    correlation_id,
)
from nexus.tools.executor import ToolExecutor


class FakeApproval:
    """Minimal stand-in for the Approval row."""

    def __init__(self, approval_id: uuid.UUID, payload: dict[str, Any] | None) -> None:
        self.id = approval_id
        self.status = "pending"
        self.payload = payload


class FakeApprovals:
    """In-memory approval store keyed by correlation ID."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, FakeApproval] = {}
        self.request_count = 0

    async def get(self, approval_id: uuid.UUID) -> FakeApproval | None:
        return self.rows.get(approval_id)

    async def request_approval(
        self,
        company_id: uuid.UUID | None = None,
        approval_type: str = "",
        requested_by_agent_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
        approval_id: uuid.UUID | None = None,
    ) -> FakeApproval:
        assert approval_id is not None, "gate must pass the correlation ID"
        self.request_count += 1
        row = FakeApproval(approval_id, payload)
        self.rows[approval_id] = row
        return row


def make_gate(
    policy: dict[str, Any] | None,
    approvals: Any | None = None,
    notices: list[dict[str, Any]] | None = None,
) -> AutonomyGate:
    """Build a gate over a static policy."""

    async def loader(_agent_id: uuid.UUID) -> dict[str, Any] | None:
        return policy

    async def notifier(payload: dict[str, Any]) -> None:
        if notices is not None:
            notices.append(payload)

    return AutonomyGate(loader, approvals=approvals, notifier=notifier)


class TestClassifyAction:
    """Tool name -> action-type mapping."""

    def test_delete_wins_over_write(self) -> None:
        assert classify_action("delete_file") == ACTION_DELETE

    def test_execute_code(self) -> None:
        assert classify_action("run_shell_command") == ACTION_EXECUTE_CODE

    def test_external_message(self) -> None:
        assert classify_action("send_email") == ACTION_SEND_EXTERNAL_MESSAGE

    def test_write_file(self) -> None:
        assert classify_action("write_file") == ACTION_WRITE_FILE

    def test_unknown_is_read(self) -> None:
        assert classify_action("list_repositories") == ACTION_READ

    def test_spend_above_threshold(self) -> None:
        action = classify_action(
            "purchase_credits", {"amount_cents": 5000}, spend_threshold_cents=1000
        )
        assert action == ACTION_SPEND

    def test_spend_at_or_below_threshold_is_not_spend(self) -> None:
        action = classify_action(
            "purchase_credits", {"amount_cents": 500}, spend_threshold_cents=1000
        )
        assert action != ACTION_SPEND


class TestCorrelationId:
    """Deterministic correlation IDs."""

    def test_same_call_same_id(self) -> None:
        agent, tool = uuid.uuid4(), uuid.uuid4()
        a = correlation_id(agent, tool, {"b": 2, "a": 1})
        b = correlation_id(agent, tool, {"a": 1, "b": 2})
        assert a == b

    def test_different_arguments_different_id(self) -> None:
        agent, tool = uuid.uuid4(), uuid.uuid4()
        assert correlation_id(agent, tool, {"a": 1}) != correlation_id(
            agent, tool, {"a": 2}
        )


class TestGateLevels:
    """L1 runs, L2 runs + notifies, L3 blocks."""

    async def test_level_1_allows_silently(self) -> None:
        notices: list[dict[str, Any]] = []
        gate = make_gate({ACTION_WRITE_FILE: 1}, notices=notices)
        d = await gate.check(uuid.uuid4(), uuid.uuid4(), "write_file", {})
        assert d.allowed is True
        assert d.notified is False
        assert notices == []

    async def test_unlisted_action_defaults_to_level_1(self) -> None:
        gate = make_gate({ACTION_DELETE: 3})
        d = await gate.check(uuid.uuid4(), uuid.uuid4(), "list_repositories", {})
        assert d.allowed is True
        assert d.level == 1

    async def test_level_2_allows_and_notifies(self) -> None:
        notices: list[dict[str, Any]] = []
        gate = make_gate({ACTION_WRITE_FILE: 2}, notices=notices)
        d = await gate.check(uuid.uuid4(), uuid.uuid4(), "write_file", {"path": "x"})
        assert d.allowed is True
        assert d.notified is True
        assert len(notices) == 1
        assert notices[0]["action_type"] == ACTION_WRITE_FILE

    async def test_level_3_blocks_files_approval_and_notifies(self) -> None:
        notices: list[dict[str, Any]] = []
        approvals = FakeApprovals()
        gate = make_gate({ACTION_DELETE: 3}, approvals=approvals, notices=notices)
        agent, tool = uuid.uuid4(), uuid.uuid4()

        d = await gate.check(agent, tool, "delete_file", {"path": "x"})

        assert d.allowed is False
        assert d.approval_id == d.correlation_id
        assert approvals.request_count == 1
        assert len(notices) == 1

    async def test_level_3_resumes_after_approval(self) -> None:
        approvals = FakeApprovals()
        gate = make_gate({ACTION_DELETE: 3}, approvals=approvals)
        agent, tool, args = uuid.uuid4(), uuid.uuid4(), {"path": "x"}

        first = await gate.check(agent, tool, "delete_file", args)
        assert first.allowed is False

        approvals.rows[first.correlation_id].status = "approved"

        second = await gate.check(agent, tool, "delete_file", args)
        assert second.allowed is True
        assert second.correlation_id == first.correlation_id
        # Resuming must not file a second approval.
        assert approvals.request_count == 1

    async def test_level_3_retry_reuses_pending_approval(self) -> None:
        approvals = FakeApprovals()
        gate = make_gate({ACTION_DELETE: 3}, approvals=approvals)
        agent, tool, args = uuid.uuid4(), uuid.uuid4(), {"path": "x"}

        await gate.check(agent, tool, "delete_file", args)
        again = await gate.check(agent, tool, "delete_file", args)

        assert again.allowed is False
        assert approvals.request_count == 1

    async def test_level_3_rejected_stays_blocked(self) -> None:
        approvals = FakeApprovals()
        gate = make_gate({ACTION_DELETE: 3}, approvals=approvals)
        agent, tool, args = uuid.uuid4(), uuid.uuid4(), {"path": "x"}

        first = await gate.check(agent, tool, "delete_file", args)
        approvals.rows[first.correlation_id].status = "rejected"

        second = await gate.check(agent, tool, "delete_file", args)
        assert second.allowed is False
        assert "rejected" in (second.reason or "")

    async def test_level_3_without_approval_store_fails_closed(self) -> None:
        gate = make_gate({ACTION_DELETE: 3})
        d = await gate.check(uuid.uuid4(), uuid.uuid4(), "delete_file", {})
        assert d.allowed is False

    async def test_junk_level_falls_back_to_default(self) -> None:
        gate = make_gate({ACTION_DELETE: "very high"})
        d = await gate.check(uuid.uuid4(), uuid.uuid4(), "delete_file", {})
        assert d.allowed is True
        assert d.level == 1

    async def test_spend_threshold_from_policy(self) -> None:
        approvals = FakeApprovals()
        gate = make_gate(
            {ACTION_SPEND: 3, "spend_above_cents": 10_000}, approvals=approvals
        )
        agent, tool = uuid.uuid4(), uuid.uuid4()

        small = await gate.check(agent, tool, "charge_card", {"amount_cents": 500})
        assert small.allowed is True

        big = await gate.check(agent, tool, "charge_card", {"amount_cents": 50_000})
        assert big.allowed is False
        assert big.action_type == ACTION_SPEND


class TestExecutorEnforcement:
    """The executor blocks a level-3 call and runs it after approval."""

    async def test_l3_blocks_then_resumes(self) -> None:
        approvals = FakeApprovals()
        gate = make_gate({ACTION_DELETE: 3}, approvals=approvals)
        executor = ToolExecutor(timeout_seconds=1.0, autonomy_gate=gate)
        agent, tool, args = uuid.uuid4(), uuid.uuid4(), {"path": "/tmp/x"}
        calls: list[dict[str, Any]] = []

        async def run(a: dict[str, Any]) -> str:
            calls.append(a)
            return "deleted"

        blocked = await executor.execute(
            agent, tool, args, run, tool_name="delete_file"
        )
        assert blocked.success is False
        assert calls == [], "tool must not run while awaiting approval"
        assert blocked.approval_id == blocked.correlation_id

        approvals.rows[blocked.correlation_id].status = "approved"

        resumed = await executor.execute(
            agent, tool, args, run, tool_name="delete_file"
        )
        assert resumed.success is True
        assert resumed.output == "deleted"
        assert len(calls) == 1
        assert resumed.correlation_id == blocked.correlation_id

    async def test_l1_runs_without_gating(self) -> None:
        gate = make_gate({ACTION_DELETE: 3})
        executor = ToolExecutor(timeout_seconds=1.0, autonomy_gate=gate)

        async def run(_a: dict[str, Any]) -> str:
            return "ok"

        result = await executor.execute(
            uuid.uuid4(), uuid.uuid4(), {}, run, tool_name="list_repositories"
        )
        assert result.success is True

    async def test_blocked_call_is_audited(self) -> None:
        approvals = FakeApprovals()
        gate = make_gate({ACTION_EXECUTE_CODE: 3}, approvals=approvals)
        executor = ToolExecutor(timeout_seconds=1.0, autonomy_gate=gate)

        async def run(_a: dict[str, Any]) -> str:
            return "ok"

        await executor.execute(
            uuid.uuid4(), uuid.uuid4(), {"cmd": "rm -rf /"}, run, tool_name="run_shell"
        )
        log = executor.get_audit_log()
        assert log[-1]["outcome"] == "approval_required"
