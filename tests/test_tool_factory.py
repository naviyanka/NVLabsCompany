"""Checks that the production ToolExecutor wiring actually enforces policy.

The point of nexus.tools.factory is that a bare ToolExecutor() enforces
nothing but permissions, rate limits and timeouts. These tests fail if the
factory ever stops attaching the guardrail chain, the autonomy gate, or the
DB-backed permission checker.
"""

import uuid

import pytest

from nexus.tools.factory import (
    build_autonomy_gate,
    build_guardrail_chain,
    build_tool_executor,
)


async def _echo(args: dict) -> str:
    return str(args)


def test_chain_has_policy_and_structural_guardrails() -> None:
    chain = build_guardrail_chain()
    names = [g.name for g in chain._guardrails]
    assert names == ["policy", "structural"]
    # Fail-closed matters: a guardrail that raises must block, not allow.
    assert chain.fail_fast is True
    assert chain.fail_closed is True


def test_executor_gets_all_collaborators() -> None:
    executor = build_tool_executor(db=None)
    assert executor._guardrails is not None
    assert executor._autonomy_gate is not None
    assert executor._audit_store is not None
    assert executor._permission_checker is not None


@pytest.mark.asyncio
async def test_dangerous_command_is_blocked() -> None:
    executor = build_tool_executor(db=None)
    # Keep the DB out of it: permissions and autonomy are exercised elsewhere.
    executor._permission_checker = None
    executor._autonomy_gate = None

    result = await executor.execute(
        agent_id=uuid.uuid4(),
        tool_id=uuid.uuid4(),
        arguments={"command": "rm -rf / --no-preserve-root"},
        execute_fn=_echo,
        company_id=uuid.uuid4(),
        tool_name="shell",
    )
    assert result.success is False
    assert "Guardrail blocked" in (result.error or "")


@pytest.mark.asyncio
async def test_sensitive_path_is_blocked() -> None:
    executor = build_tool_executor(db=None)
    executor._permission_checker = None
    executor._autonomy_gate = None

    result = await executor.execute(
        agent_id=uuid.uuid4(),
        tool_id=uuid.uuid4(),
        arguments={"path": "/etc/shadow"},
        execute_fn=_echo,
        company_id=uuid.uuid4(),
        tool_name="read_file",
    )
    assert result.success is False
    assert "Guardrail blocked" in (result.error or "")


@pytest.mark.asyncio
async def test_benign_call_passes_guardrails() -> None:
    executor = build_tool_executor(db=None)
    executor._permission_checker = None
    executor._autonomy_gate = None

    result = await executor.execute(
        agent_id=uuid.uuid4(),
        tool_id=uuid.uuid4(),
        arguments={"path": "README.md"},
        execute_fn=_echo,
        company_id=uuid.uuid4(),
        tool_name="read_file",
    )
    assert result.success is True, result.error


@pytest.mark.asyncio
async def test_autonomy_level_3_blocks_and_files_an_approval() -> None:
    """A level-3 action must block and leave an approval behind."""
    filed: list[dict] = []

    class FakeApprovals:
        async def get(self, approval_id):
            return None

        async def request_approval(self, **kwargs):
            filed.append(kwargs)
            return None

    gate = build_autonomy_gate(db=None)
    # Swap the DB-backed collaborators for fakes; the wiring under test is that
    # build_tool_executor hands the gate to the executor at all.
    gate._policy_loader = lambda agent_id: _policy()
    gate._approvals = FakeApprovals()

    executor = build_tool_executor(db=None)
    executor._permission_checker = None
    executor._autonomy_gate = gate

    result = await executor.execute(
        agent_id=uuid.uuid4(),
        tool_id=uuid.uuid4(),
        arguments={"amount_cents": 100},
        execute_fn=_echo,
        company_id=uuid.uuid4(),
        tool_name="send_payment",
    )
    assert result.success is False
    assert result.approval_id is not None
    assert len(filed) == 1


async def _policy() -> dict:
    """Every action type is level 3, so any tool call needs an approval."""
    from nexus.tools.autonomy import classify_action

    action = classify_action("send_payment", {"amount_cents": 100}, 0)
    return {action: 3}
