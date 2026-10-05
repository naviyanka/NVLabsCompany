"""Every tool the ledger may rerun has a proven way to make the rerun harmless.

A tool is declared idempotent only when one of two things is true: it carries the ledger's
invocation key downstream as its idempotency key (``ledger-key``), or the operation is
intrinsically a no-op the second time (``intrinsic``, each with a test below). Anything else is
non-idempotent, and a recovered turn never reruns it. The table is complete by construction:
a test fails when a tool exists that it does not classify, and the mutation tests show that
removing key propagation or misclassifying a tool makes the guard fail.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name, as elsewhere in the suite

from __future__ import annotations

import dataclasses
import inspect
import itertools
import re
import uuid
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from nexus.models._time import utcnow
from nexus.models.agent import Agent
from nexus.models.chat_turn import ChatTurn
from nexus.models.governance import Approval
from nexus.models.obsidian import ObsidianDocument
from nexus.models.task import Goal
from nexus.models.task_attempt import TaskAttempt
from nexus.models.tool_effect import ToolEffect
from nexus.obsidian import ObsidianWriter, VaultWriteAuthorizer, WriteActor, WriteConflictError
from nexus.obsidian.provider import content_hash
from nexus.services.session_service import get_or_create_default_session
from nexus.tools import ceo_tools, effects, manager_tools
from nexus.tools.effects import EffectClass, ToolSlot
from nexus.tools.mcp_server import NODE_EFFECTS, MCPServer
from nexus.tools.registry import ToolRegistry
from tests.test_ceo_control_plane import _allow, _appoint, c  # noqa: F401 -- fixtures
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_manager_core import _ctx, _payload, _staffed, team  # noqa: F401 -- fixtures
from tests.test_obsidian_writer import (  # noqa: F401 -- fixtures
    AGENT,
    COMPANY,
    TOOL,
    db_factory,
    vault,
)

READ = EffectClass.READ_ONLY
IDEM = EffectClass.IDEMPOTENT_WRITE
NON_IDEM = EffectClass.NON_IDEMPOTENT_WRITE

LEDGER_KEY = "ledger-key"
INTRINSIC = "intrinsic"
NONE = "none"  # not idempotent: a recovered turn never reruns it


@dataclass(frozen=True)
class Proof:
    effect: EffectClass
    mechanism: str
    why: str


# The complete classification: every node, manager and CEO tool the server can dispatch.
TABLE: dict[str, Proof] = {
    "ai-chat": Proof(READ, NONE, "reads only"),
    "ai-sentiment": Proof(READ, NONE, "reads only"),
    "ai-summarize": Proof(READ, NONE, "reads only"),
    "ai-translate": Proof(READ, NONE, "reads only"),
    "db-redis-get": Proof(READ, NONE, "reads only"),
    "file-csv-parse": Proof(READ, NONE, "reads only"),
    "file-json-parse": Proof(READ, NONE, "reads only"),
    "db-redis-set": Proof(NON_IDEM, NONE, "a relative TTL restarts on every retry"),
    "db-sqlite-query": Proof(NON_IDEM, NONE, "arbitrary SQL"),
    "http-request": Proof(NON_IDEM, NONE, "arbitrary request"),
    "msg-discord-send": Proof(NON_IDEM, NONE, "a message is sent each time"),
    "msg-slack-send": Proof(NON_IDEM, NONE, "a message is sent each time"),
    "msg-telegram-send": Proof(NON_IDEM, NONE, "a message is sent each time"),
    "msg-webhook-notify": Proof(NON_IDEM, NONE, "a webhook fires each time"),
    "manager_delegate_task": Proof(IDEM, INTRINSIC, "one task attempt per manager/employee key"),
    "manager_request_hire": Proof(IDEM, LEDGER_KEY, "hiring dedupes on the ledger key"),
    "manager_assign_work": Proof(IDEM, LEDGER_KEY, "child task id derives from the ledger key"),
    "manager_review_work": Proof(IDEM, INTRINSIC, "one conditional update decides"),
    "ceo_delegate_task_to_manager": Proof(IDEM, INTRINSIC, "one task attempt per key"),
    "ceo_create_goal_or_work_order": Proof(IDEM, LEDGER_KEY, "id derives from the ledger key"),
    "ceo_request_hire": Proof(IDEM, LEDGER_KEY, "hiring dedupes on the ledger key"),
    "ceo_record_decision": Proof(NON_IDEM, NONE, "appends a memory entry each time"),
    **{
        name: Proof(READ, NONE, "reads only")
        for name in (
            "manager_list_reports", "manager_employee_status", "manager_task_evidence",
            "manager_rollup", "manager_list_hiring_requests", "manager_get_hiring_request",
            "ceo_get_organization_snapshot", "ceo_list_managers", "ceo_get_manager_status",
            "ceo_list_pending_approvals", "ceo_search_executive_memory",
            "ceo_get_work_status", "organization_get_snapshot",
        )
    },
}
# Tools registered by other paths, each declared where it is registered.
DYNAMIC = {
    "hermes register_tool without effect": NON_IDEM,
    "tool connection call": NON_IDEM,
    "obsidian.note_replace": IDEM,  # compare-and-set on the hash the caller read
}


def _model_keyed(tool) -> bool:
    return tool.model is not None and "idempotency_key" in tool.model.model_fields


def check_classification(node_effects, tools, table=None) -> None:
    """Assert the table and the registered declarations agree, and every rerun is justified."""
    table = TABLE if table is None else table
    declared = {**node_effects, **{n: t.effect for n, t in tools.items()}}
    assert set(declared) == set(table), (
        f"unclassified: {sorted(set(declared) - set(table))}, "
        f"stale: {sorted(set(table) - set(declared))}"
    )
    for name, effect in declared.items():
        proof = table[name]
        assert effect is proof.effect, f"{name} is declared {effect} but classified {proof.effect}"
        if effect is IDEM:
            assert proof.mechanism in (LEDGER_KEY, INTRINSIC), f"{name} has no idempotency proof"
        else:
            assert proof.mechanism == NONE, f"{name} claims a mechanism it does not need"
        if proof.mechanism == LEDGER_KEY:
            assert name in tools and _model_keyed(tools[name]), f"{name} has no key to bind"
    for name, tool in tools.items():
        if _model_keyed(tool):
            assert table[name].mechanism == LEDGER_KEY, f"{name} takes a key the ledger must own"
        if tool.risk != "read":
            assert tool.effect is not READ, f"{name} writes but is declared read-only"


def _all_tools():
    return {**manager_tools.MANAGER_TOOLS, **ceo_tools.CEO_TOOLS}


def test_the_classification_table_is_complete_and_consistent():
    check_classification(NODE_EFFECTS, _all_tools())


def test_every_bridged_write_tool_requires_its_invocation_argument_and_no_read_does():
    """The contract a new write tool (for example PR #69's) must meet to be callable by Claude.

    Each tool declares its ``EffectClass`` (a required field, so omitting it cannot construct),
    a write tool's bridge schema requires the invocation argument, a read tool's never does, and
    a tool with its own ``idempotency_key`` reuses that field instead of adding a second one.
    """
    for name, tool in _all_tools().items():
        schema = manager_tools.bridge_input_schema(tool)
        field = manager_tools.key_field(tool)
        assert isinstance(tool.effect, EffectClass), name
        if tool.effect is EffectClass.READ_ONLY:
            assert field not in schema.get("required", []), name
            assert effects.BRIDGE_KEY_ARG not in schema.get("properties", {}), name
            continue
        assert field in schema["required"] and field in schema["properties"], name
        assert field == ("idempotency_key" if _model_keyed(tool) else effects.BRIDGE_KEY_ARG), name
        assert "NEW unique value" in manager_tools.bridge_description(tool), name


def test_a_new_unclassified_tool_fails_the_guard():
    tools = {**_all_tools(), "manager_new_thing": _all_tools()["manager_list_reports"]}
    assert "manager_new_thing" not in TABLE
    with pytest.raises(AssertionError, match="unclassified"):
        check_classification(NODE_EFFECTS, tools)
    with pytest.raises(AssertionError, match="unclassified"):
        check_classification({**NODE_EFFECTS, "msg-new-send": NON_IDEM}, _all_tools())


@pytest.mark.parametrize(
    "name", ["manager_request_hire", "ceo_create_goal_or_work_order", "ceo_request_hire"]
)
def test_declaring_a_keyed_tool_read_only_or_the_wrong_class_fails_the_guard(name):
    tools = _all_tools()
    for wrong in (READ, NON_IDEM):
        broken = {**tools, name: dataclasses.replace(tools[name], effect=wrong)}
        with pytest.raises(AssertionError):
            check_classification(NODE_EFFECTS, broken)


def test_declaring_a_write_idempotent_without_a_proof_fails_the_guard():
    tools = _all_tools()
    # A non-idempotent tool relabelled idempotent without a mechanism in the table.
    broken = {**tools, "ceo_record_decision": dataclasses.replace(tools["ceo_record_decision"],
                                                                     effect=IDEM)}
    with pytest.raises(AssertionError):
        check_classification(NODE_EFFECTS, broken)
    with pytest.raises(AssertionError):
        check_classification({**NODE_EFFECTS, "http-request": IDEM}, tools)


def test_a_tool_with_a_model_key_must_be_bound_to_the_ledger():
    tools = _all_tools()
    table = {**TABLE, "ceo_create_goal_or_work_order": Proof(IDEM, INTRINSIC, "claimed")}
    with pytest.raises(AssertionError, match="takes a key the ledger must own"):
        check_classification(NODE_EFFECTS, tools, table)


def test_dynamic_registrations_default_to_non_idempotent_and_obsidian_is_declared():
    from nexus.api.routes import chat

    assert DYNAMIC["hermes register_tool without effect"] is NON_IDEM
    assert effects.resolve_effect(None) is NON_IDEM
    assert effects.resolve_effect("typo") is NON_IDEM
    source = inspect.getsource(chat)
    # The only registration in the chat path is Obsidian's, declared with its own class.
    assert source.count("adapter.register_tool(") == 1
    block = source[source.index("adapter.register_tool("):]
    block = block[: block.index("# Tool calls act under the server-built context")]
    assert "OBSIDIAN_NOTE_REPLACE_NAME" in block
    assert re.search(r"effect=EffectClass\.IDEMPOTENT_WRITE", block)


# --- the ledger key reaches the downstream service ---------------------------------------------


KEYED = [n for n, p in TABLE.items() if p.mechanism == LEDGER_KEY]
MODEL_ARGS = {
    "manager_request_hire": {
        "role": "engineer", "title": "Engineer", "reason": "r", "backend": "claude",
        "responsibilities": "x", "estimated_monthly_cents": 1, "estimated_one_time_cents": 1,
        "urgency": "low", "idempotency_key": "model-chosen",
    },
    "ceo_request_hire": {
        "role": "engineer", "title": "Engineer", "reason": "r", "backend": "claude",
        "responsibilities": "x", "estimated_monthly_cents": 1, "estimated_one_time_cents": 1,
        "urgency": "low", "idempotency_key": "model-chosen",
    },
    "ceo_create_goal_or_work_order": {
        "kind": "goal", "title": "t", "idempotency_key": "model-chosen",
    },
    "manager_assign_work": {
        "work_id": str(uuid.uuid4()), "employee_id": str(uuid.uuid4()), "title": "t",
        "objective": "o", "idempotency_key": "model-chosen",
    },
}


async def _key_seen_downstream(monkeypatch, name, bound):
    """The idempotency key a keyed tool hands to its service when called with ``bound``."""
    seen = []
    ctx = SimpleNamespace(agent_id=uuid.uuid4(), company_id=uuid.uuid4())

    async def capture_manager(db, company_id, manager_id, args, actor):
        seen.append(args.idempotency_key)
        return {}

    async def capture_ceo(ctx_, tool_name, args):
        seen.append(args.idempotency_key)
        return {}

    if name in manager_tools.MANAGER_TOOLS:
        monkeypatch.setitem(
            manager_tools.MANAGER_TOOLS, name,
            replace(manager_tools.MANAGER_TOOLS[name], run=capture_manager),
        )
    else:
        monkeypatch.setattr(ceo_tools, "run", capture_ceo)
    with effects.bind_invocation(bound):
        await manager_tools.call(ctx, name, dict(MODEL_ARGS[name]))
    return seen


@pytest.mark.parametrize("name", KEYED)
async def test_a_keyed_tool_hands_the_ledger_key_downstream_not_the_model_key(
    db, monkeypatch, name  # noqa: F811
):
    assert await _key_seen_downstream(monkeypatch, name, "LEDGER") == ["LEDGER"]
    # With no ledger bound (a path that is not ledgered) the caller's own key stands.
    assert await _key_seen_downstream(monkeypatch, name, None) == ["model-chosen"]


@pytest.mark.parametrize("name", KEYED)
async def test_removing_key_propagation_is_detected(db, monkeypatch, name):  # noqa: F811
    monkeypatch.setattr(manager_tools, "downstream_key", lambda model_key: model_key)
    with pytest.raises(AssertionError):
        assert await _key_seen_downstream(monkeypatch, name, "LEDGER") == ["LEDGER"]


# --- end to end: the rerun of an idempotent tool changes nothing -------------------------------


_SEQ = itertools.count(5000)


async def _turn(db, agent_id) -> uuid.UUID:  # noqa: F811
    """A real chat turn: the CEO tools cite it as the source of the memory they record."""
    async with db() as s:
        agent = await s.get(Agent, agent_id)
        record = await get_or_create_default_session(s, agent)
        turn = ChatTurn(
            company_id=agent.company_id, agent_id=agent.id, session_id=record.id,
            idempotency_key=uuid.uuid4().hex, turn_seq=next(_SEQ), status="running",
            execution_id=str(uuid.uuid4()),
        )
        s.add(turn)
        await s.commit()
        return turn.id


def _server(c, turn, who="chief"):  # noqa: F811
    return MCPServer(
        replace(_ctx(c["acme"], c[who]), turn_id=turn, turn_attempt=1), node_tools=False
    )


HIRE = {
    "role": "engineer", "title": "Backend Engineer", "reason": "Ship the API", "backend": "claude",
    "responsibilities": "Own the API service", "estimated_monthly_cents": 700,
    "estimated_one_time_cents": 500, "urgency": "high", "idempotency_key": "same-model-key",
}
GOAL = {"kind": "goal", "title": "Grow revenue", "idempotency_key": "same-model-key"}


async def _chief(db, c, *tools):  # noqa: F811
    await _appoint(c, c["chief"])
    await _allow(db, c["acme"], *tools)


async def _drop_settlement(monkeypatch):
    """The process dies after the effect but before it is recorded: the row stays executing."""

    async def lost(*args, **kwargs):
        return False

    monkeypatch.setattr(effects, "settle", lost)


async def _expire(db, company):  # noqa: F811
    async with db() as s:
        for row in (await s.execute(select(ToolEffect))).scalars():
            row.lease_expires_at = utcnow() - timedelta(seconds=1)
        await s.commit()


async def test_a_goal_rerun_after_a_crash_creates_one_goal(db, c, monkeypatch):  # noqa: F811
    await _chief(db, c, "ceo_create_goal_or_work_order")
    turn = await _turn(db, c["chief"])
    real = effects.settle
    await _drop_settlement(monkeypatch)
    first = _payload(await _server(c, turn).call_tool(
        "ceo_create_goal_or_work_order", GOAL, slot=ToolSlot(0, 0)))
    monkeypatch.setattr(effects, "settle", real)
    await _expire(db, c["acme"])
    again = _payload(await _server(c, turn).call_tool(
        "ceo_create_goal_or_work_order", GOAL, slot=ToolSlot(0, 0)))
    assert (first["created"], again["created"]) == (True, False) and first["id"] == again["id"]
    assert len(await _rows(db, Goal, Goal.company_id == c["acme"])) == 1
    [row] = await _rows(db, ToolEffect)
    assert row.status == "succeeded" and row.attempt_count == 2


async def test_a_regenerated_model_key_at_the_same_slot_is_refused_not_duplicated(
    db, c, monkeypatch  # noqa: F811
):
    await _chief(db, c, "ceo_create_goal_or_work_order")
    turn = await _turn(db, c["chief"])
    await _server(c, turn).call_tool("ceo_create_goal_or_work_order", GOAL, slot=ToolSlot(0, 0))
    regenerated = {**GOAL, "idempotency_key": "a-fresh-model-key"}
    out = await _server(c, turn).call_tool(
        "ceo_create_goal_or_work_order", regenerated, slot=ToolSlot(0, 0))
    assert out["isError"] is True
    assert len(await _rows(db, Goal, Goal.company_id == c["acme"])) == 1


async def _two_goals_with_one_model_key(db, c):  # noqa: F811
    turn = await _turn(db, c["chief"])
    one = await _server(c, turn).call_tool(
        "ceo_create_goal_or_work_order", GOAL, slot=ToolSlot(0, 0))
    two = await _server(c, turn).call_tool(
        "ceo_create_goal_or_work_order", {**GOAL, "title": "Cut costs"}, slot=ToolSlot(0, 1))
    return one, two, len(await _rows(db, Goal, Goal.company_id == c["acme"]))


async def test_two_positions_are_two_goals_even_when_the_model_reuses_a_key(db, c):  # noqa: F811
    await _chief(db, c, "ceo_create_goal_or_work_order")
    one, two, goals = await _two_goals_with_one_model_key(db, c)
    assert one["isError"] is False and two["isError"] is False and goals == 2


async def test_without_key_propagation_a_reused_model_key_collides(db, c, monkeypatch):  # noqa: F811
    """The mutation: the end-to-end test above fails if the ledger key is not handed down."""
    await _chief(db, c, "ceo_create_goal_or_work_order")
    monkeypatch.setattr(manager_tools, "downstream_key", lambda model_key: model_key)
    _, two, goals = await _two_goals_with_one_model_key(db, c)
    assert two["isError"] is True and goals == 1  # i.e. test_two_positions_... would fail


async def test_a_hire_rerun_after_a_crash_files_one_request(db, c, monkeypatch):  # noqa: F811
    await _chief(db, c, "ceo_request_hire", "manager_request_hire")
    turn = await _turn(db, c["chief"])
    real = effects.settle
    await _drop_settlement(monkeypatch)
    first = _payload(
        await _server(c, turn).call_tool("ceo_request_hire", HIRE, slot=ToolSlot(0, 0)))
    monkeypatch.setattr(effects, "settle", real)
    await _expire(db, c["acme"])
    again = _payload(
        await _server(c, turn).call_tool("ceo_request_hire", HIRE, slot=ToolSlot(0, 0)))
    assert (first["created"], again["created"]) == (True, False)
    assert len(await _rows(db, Approval, Approval.company_id == c["acme"])) == 1


async def _two_hires_with_one_model_key(db, c):  # noqa: F811
    turn = await _turn(db, c["chief"])
    await _server(c, turn).call_tool("ceo_request_hire", HIRE, slot=ToolSlot(0, 0))
    await _server(c, turn).call_tool("ceo_request_hire", HIRE, slot=ToolSlot(0, 1))
    return len(await _rows(db, Approval, Approval.company_id == c["acme"]))


async def test_two_hires_at_two_positions_are_two_requests(db, c):  # noqa: F811
    await _chief(db, c, "ceo_request_hire", "manager_request_hire")
    assert await _two_hires_with_one_model_key(db, c) == 2


async def test_without_key_propagation_the_second_hire_is_swallowed(db, c, monkeypatch):  # noqa: F811
    await _chief(db, c, "ceo_request_hire", "manager_request_hire")
    monkeypatch.setattr(manager_tools, "downstream_key", lambda model_key: model_key)
    assert await _two_hires_with_one_model_key(db, c) == 1


async def test_a_manager_hire_rerun_is_one_request_too(db, c, monkeypatch):  # noqa: F811
    await _staffed(c)
    await _allow(db, c["acme"], "manager_request_hire")
    turn = await _turn(db, c["lead"])
    manager = MCPServer(
        replace(_ctx(c["acme"], c["lead"]), turn_id=turn, turn_attempt=1), node_tools=False
    )
    real = effects.settle
    await _drop_settlement(monkeypatch)
    first = _payload(await manager.call_tool("manager_request_hire", HIRE, slot=ToolSlot(0, 0)))
    monkeypatch.setattr(effects, "settle", real)
    await _expire(db, c["acme"])
    again = _payload(await MCPServer(
        replace(_ctx(c["acme"], c["lead"]), turn_id=turn, turn_attempt=1), node_tools=False
    ).call_tool("manager_request_hire", HIRE, slot=ToolSlot(0, 0)))
    assert (first["created"], again["created"]) == (True, False)
    assert len(await _rows(db, Approval, Approval.company_id == c["acme"])) == 1


@pytest.mark.parametrize("who", ["lead", "chief"])
async def test_a_delegation_rerun_after_a_crash_is_one_attempt(db, c, monkeypatch, who):  # noqa: F811
    await _staffed(c)
    await _appoint(c, c["chief"])
    tool = "manager_delegate_task" if who == "lead" else "ceo_delegate_task_to_manager"
    await _allow(db, c["acme"], tool)
    args = (
        {"task_id": str(c["task2"]), "employee_id": str(c["acme_claude"])}
        if who == "lead"
        else {"manager_id": str(c["lead"]), "task_id": str(c["task2"])}
    )
    turn = await _turn(db, c[who])

    def server():
        return MCPServer(
            replace(_ctx(c["acme"], c[who]), turn_id=turn, turn_attempt=1), node_tools=False
        )

    real = effects.settle
    await _drop_settlement(monkeypatch)
    first = _payload(await server().call_tool(tool, args, slot=ToolSlot(0, 0)))
    monkeypatch.setattr(effects, "settle", real)
    await _expire(db, c["acme"])
    again = _payload(await server().call_tool(tool, args, slot=ToolSlot(0, 0)))
    assert first["attempt"]["id"] == again["attempt"]["id"] and again["created"] is False
    assert len(await _rows(db, TaskAttempt, TaskAttempt.task_id == c["task2"])) == 1


class _FakeRedis:
    """Records the arguments of every SET, including the expiration, like a server would see."""

    def __init__(self):
        self.sets: list[tuple[str, str, dict]] = []

    async def set(self, key, value, **kwargs):
        self.sets.append((key, value, kwargs))

    async def aclose(self):
        pass


@pytest.mark.parametrize(
    ("params", "expiration"),
    [
        ({"key": "k", "value": "v"}, {}),
        ({"key": "k", "value": "v", "ttl": 0}, {}),
        ({"key": "k", "value": "v", "ttl": 90}, {"ex": 90}),
        ({"key": "k", "value": "v", "ttl": "90"}, {"ex": 90}),
    ],
)
async def test_a_redis_set_passes_its_expiration_through_unchanged(monkeypatch, params, expiration):
    import redis.asyncio as aioredis

    from nexus.nodes.executor import _run_redis_set

    client = _FakeRedis()
    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: client)
    await _run_redis_set(dict(params))
    assert client.sets == [("k", "v", expiration)]


def test_every_redis_set_is_non_idempotent_so_a_ttl_retry_can_never_run():
    assert NODE_EFFECTS["db-redis-set"] is NON_IDEM and TABLE["db-redis-set"].effect is NON_IDEM
    with pytest.raises(AssertionError):
        check_classification({**NODE_EFFECTS, "db-redis-set": IDEM}, _all_tools())


def _runbook_classes() -> dict[str, str]:
    """Tool name to the class column of the runbook's classification table."""
    text = (Path(__file__).parents[1] / "docs" / "runbooks" / "tool-effect-recovery.md").read_text(
        encoding="utf-8"
    )
    classes: dict[str, str] = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] in ("Manager", "CEO", "Node", "Obsidian"):
            for name in re.findall(r"`([^`]+)`", cells[1]):
                classes[name] = cells[2]
    return classes


def test_the_runbook_classification_table_matches_production():
    word = {READ: "read only", IDEM: "idempotent", NON_IDEM: "non-idempotent"}
    declared = {**NODE_EFFECTS, **{n: t.effect for n, t in _all_tools().items()}}
    documented = _runbook_classes()
    assert {n: documented.get(n) for n in declared} == {n: word[e] for n, e in declared.items()}


async def test_an_obsidian_replace_repeated_with_its_hash_is_refused_not_rewritten(
    vault, db_factory  # noqa: F811
):
    """Compare-and-set on the hash the caller read: the rerun finds the note already changed."""
    old, new = "old\n", "new\n"
    path = vault / str(COMPANY) / "Note.md"
    path.write_text(old, encoding="utf-8")
    async with db_factory() as db:
        db.add(ObsidianDocument(
            company_id=COMPANY, vault_path="Note.md", content_hash=content_hash(old),
            mtime=utcnow(),
        ))
        await db.commit()
        registry = ToolRegistry(db_factory)
        await registry.grant_access(COMPANY, AGENT, TOOL)
        authorizer = VaultWriteAuthorizer(registry, db_factory)
        await authorizer.grant_async(COMPANY, AGENT, TOOL, "*")
        writer = ObsidianWriter(db, authorizer=authorizer, approval_required=False)

        def replace():
            return writer.replace_note(
                COMPANY, "Note.md", new, WriteActor.agent(AGENT), tool_id=TOOL,
                expected_hash=content_hash(old),
            )

        await replace()
        with pytest.raises(WriteConflictError):
            await replace()
        assert path.read_text(encoding="utf-8") == new
