"""Durable tool-effect ledger: a recovered chat turn never repeats a write.

Every test that proves the execute-once guarantee drives ``guarded_call`` against a real
SQLite database and counts how many times the tool body ran. Removing the ledger claim from
``guarded_call`` makes the replay, ambiguity and concurrency tests fail.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.config import settings
from nexus.models._time import utcnow
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.tool_effect import ToolEffect
from nexus.models.tool_invocation import ToolInvocation
from nexus.nodes.executor import ExecutorResult
from nexus.tools import effects
from nexus.tools.context import ExecutionContext
from nexus.tools.effects import EffectClass, EffectNotStarted, ToolSlot
from nexus.tools.factory import guarded_call
from nexus.tools.mcp_client import MCPResult

IDEM = EffectClass.IDEMPOTENT_WRITE
NON_IDEM = EffectClass.NON_IDEMPOTENT_WRITE
SLOT = ToolSlot(0, 0)


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'effects.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", maker)
    monkeypatch.setattr(settings, "tool_binding_enforcement", "audit")
    yield maker
    await engine.dispose()


@pytest.fixture
async def world(factory):
    async with factory() as db:
        acme, other = Company(name="Acme"), Company(name="Other")
        db.add_all([acme, other])
        await db.flush()
        agent = Agent(company_id=acme.id, name="A", role="engineer")
        db.add(agent)
        await db.commit()
    ctx = ExecutionContext.for_agent(agent, source="hermes")
    return {"acme": acme.id, "other": other.id, "agent": agent, "ctx": ctx, "turn": uuid.uuid4()}


def turn_ctx(world, turn=None, attempt=None) -> ExecutionContext:
    """A context for the turn's execution number ``attempt`` (default: the world's current one).

    The epoch is what the runtime would have captured when it claimed the turn; tests that move
    the turn on build a stale context by passing the old ``attempt`` explicitly.
    """
    return replace(
        world["ctx"],
        turn_id=turn or world["turn"],
        turn_attempt=attempt or world.get("attempt", 1),
    )


class Tool:
    """A tool body that counts its runs and can be told how to end."""

    def __init__(self, result=None, raises=None, gate=None):
        self.runs = 0
        self.result = {"ok": True} if result is None else result
        self.raises = raises
        self.gate = gate

    async def __call__(self):
        self.runs += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.raises is not None:
            raise self.raises
        return self.result


async def go(world, tool, *, effect=NON_IDEM, ctx=None, name="send-it", args=None, slot=SLOT):
    return await guarded_call(
        ctx if ctx is not None else turn_ctx(world),
        name,
        {"to": "a", "n": 1} if args is None else args,
        tool,
        source="test",
        effect=effect.value if effect is not None else None,
        slot=slot,
    )


async def rows(factory) -> list[ToolEffect]:
    async with factory() as db:
        return list((await db.execute(select(ToolEffect))).scalars().all())


async def expire_lease(factory, effect_id) -> None:
    async with factory() as db:
        row = await db.get(ToolEffect, effect_id)
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
        await db.commit()


# --- classification --------------------------------------------------------------------------


@pytest.mark.parametrize("declared", [None, "", "mystery", "WRITE", "readonly"])
def test_undeclared_or_unknown_class_is_non_idempotent(declared):
    assert effects.resolve_effect(declared) is NON_IDEM


def test_declared_classes_are_honoured():
    assert effects.resolve_effect("read_only") is EffectClass.READ_ONLY
    assert effects.resolve_effect(EffectClass.IDEMPOTENT_WRITE) is IDEM


@pytest.mark.parametrize("name", ["get-status", "read_file", "list-items", "search", "is_safe"])
def test_safety_is_never_inferred_from_the_tool_name(name):
    assert effects.resolve_effect(None) is NON_IDEM
    assert name  # the resolver takes no name: there is nothing to infer from


# --- key derivation and canonical arguments --------------------------------------------------


def test_canonical_arguments_are_order_independent_and_compact():
    assert effects.canonical_arguments({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == (
        '{"a":[1,{"c":3,"d":2}],"b":1}'
    )
    assert effects.canonical_arguments({"é": "ü"}) == '{"\\u00e9":"\\u00fc"}'


@pytest.mark.parametrize("bad", [{"x": float("nan")}, {"x": float("inf")}, {"x": object()},
                                 {"x": {1, 2}}, {"x": b"raw"}])
def test_non_canonical_arguments_have_no_digest(bad):
    with pytest.raises(effects.EffectKeyError):
        effects.arguments_digest(bad)


def test_key_is_scoped_by_tenant_turn_round_and_position_only():
    c, t = uuid.uuid4(), uuid.uuid4()
    key = effects.invocation_key(c, t, ToolSlot(1, 2))
    assert key == effects.invocation_key(c, t, ToolSlot(1, 2))
    assert len(key) == 64
    others = [
        effects.invocation_key(uuid.uuid4(), t, ToolSlot(1, 2)),
        effects.invocation_key(c, uuid.uuid4(), ToolSlot(1, 2)),
        effects.invocation_key(c, t, ToolSlot(2, 2)),
        effects.invocation_key(c, t, ToolSlot(1, 3)),
    ]
    assert key not in others and len(set(others)) == 4


def test_key_derivation_is_pinned():
    """The documented derivation. Changing it orphans every stored key: bump KEY_VERSION."""
    c = uuid.UUID("12345678-1234-1234-1234-123456789abc")
    t = uuid.UUID("99999999-9999-9999-9999-999999999999")
    key = effects.invocation_key(c, t, ToolSlot(3, 4))
    import hashlib

    parts = ["nexus.tool-effect.v2", str(c), str(t), 3, 4]
    assert key == hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()
    assert effects.arguments_digest({"a": 1}) == hashlib.sha256(b'{"a":1}').hexdigest()


def test_the_key_does_not_depend_on_the_call_content_or_a_provider_id():
    """Tool, arguments and provider call ids are not inputs: only the durable slot is."""
    import inspect

    assert list(inspect.signature(effects.invocation_key).parameters) == [
        "company_id", "turn_id", "slot",
    ]


@pytest.mark.parametrize("bad", [(-2, 0), (0, -1), ("0", 0), (0, 1.5), (True, 0)])
def test_a_slot_must_be_a_real_position(bad):
    with pytest.raises((ValueError, TypeError)):
        ToolSlot(*bad)


# --- bounded, scrubbed results ---------------------------------------------------------------


def test_result_codecs_round_trip():
    ex = ExecutorResult(success=True, outputs={"n": 1})
    got = effects.decode_result(effects.seal_result(ex))
    assert isinstance(got, ExecutorResult) and got.outputs == {"n": 1} and got.success

    mcp = MCPResult(content={"x": [1, 2]}, is_error=False, metadata={"m": 1})
    got = effects.decode_result(effects.seal_result(mcp))
    assert isinstance(got, MCPResult) and got.content == {"x": [1, 2]} and got.metadata == {"m": 1}

    assert effects.decode_result(effects.seal_result({"a": [1]})) == {"a": [1]}


def test_result_secrets_are_masked_before_storage():
    stored = effects.seal_result({"api_key": "sk-live-123", "password": "hunter2", "ok": 1})
    blob = json.dumps(stored)
    assert "sk-live-123" not in blob and "hunter2" not in blob
    assert effects.decode_result(stored)["ok"] == 1


def test_error_text_is_bounded_and_redacted():
    out = effects.redact_text("boom " + "y" * 5000)
    assert len(out) == effects.MAX_TEXT_CHARS
    assert "sk-abcdefghijklmnopqrstuvwx" not in effects.redact_text(
        "failed with key sk-abcdefghijklmnopqrstuvwx"
    )


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (ExecutorResult(success=True, outputs={}), "succeeded"),
        (ExecutorResult(success=False, error="bad input", effect_rejected=True), "failed"),
        (ExecutorResult(success=False, error="bad input"), "ambiguous"),
        (ExecutorResult(success=False, error="timed out", effect_unknown=True), "ambiguous"),
        (MCPResult(content="x", is_error=True), "ambiguous"),
        (MCPResult(content="x", is_error=True, effect_unknown=True), "ambiguous"),
        ({"a": 1}, "succeeded"),
        ("text", "succeeded"),
    ],
)
def test_outcome_of(result, expected):
    assert effects.outcome_of(result)[0] == expected


class _HttpError(Exception):
    def __init__(self, code):
        self.status_code = code


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (EffectNotStarted("refused before dispatch"), "failed"),
        (ValueError("bad"), "ambiguous"),
        (json.JSONDecodeError("bad json", "", 0), "ambiguous"),
        (_HttpError(422), "ambiguous"),
        (_HttpError(503), "ambiguous"),
        (RuntimeError("?"), "ambiguous"),
        (TimeoutError(), "ambiguous"),
        (asyncio.CancelledError(), "ambiguous"),
    ],
)
def test_outcome_of_exception(exc, expected):
    assert effects.outcome_of_exception(exc) == expected


# --- executor / client report an unknown outcome ---------------------------------------------


class _Exec:
    node_ids = ["probe"]

    def __init__(self, behaviour):
        self.behaviour = behaviour

    async def run(self, params):
        return await self.behaviour()


async def _execute(behaviour, timeout=5.0):
    from nexus.nodes.executor import ExecutorRegistry, execute_node

    registry = ExecutorRegistry()
    registry.register(_Exec(behaviour))
    return await execute_node("probe", {}, registry=registry, timeout_seconds=timeout)


async def test_executor_timeout_and_crash_mark_the_effect_unknown():
    async def slow():
        await asyncio.sleep(10)

    async def crash():
        raise RuntimeError("kaput")

    async def late_value_error():
        raise ValueError("bad input")

    async def typed_refusal():
        raise EffectNotStarted("bad input")

    async def fine():
        return {"ok": 1}

    assert (await _execute(slow, timeout=0.05)).effect_unknown is True
    assert (await _execute(crash)).effect_unknown is True
    unknown = await _execute(late_value_error)
    assert unknown.effect_unknown is True and unknown.effect_rejected is False
    refused = await _execute(typed_refusal)
    assert refused.effect_rejected is True and refused.effect_unknown is False
    ok = await _execute(fine)
    assert ok.success and ok.effect_unknown is False and ok.effect_rejected is False


def test_mcp_result_defaults_to_known_outcome():
    assert MCPResult(content="x").effect_unknown is False


# --- the ledger through guarded_call ---------------------------------------------------------


async def test_first_call_runs_and_is_recorded_before_it_finishes(factory, world):
    seen = []

    async def body():
        seen.extend(await rows(factory))  # observed while the tool is running
        return {"ok": 1}

    out = await go(world, body)
    assert out == {"status": "success", "result": {"ok": 1}}
    assert [r.status for r in seen] == ["executing"]
    assert seen[0].claim_token and seen[0].lease_expires_at
    (row,) = await rows(factory)
    assert row.status == "succeeded" and row.claim_token is None and row.attempt_count == 1
    assert row.company_id == world["acme"] and row.turn_id == world["turn"]
    assert row.result == {"kind": "json", "value": {"ok": 1}}


@pytest.mark.parametrize("effect", [IDEM, NON_IDEM])
async def test_recovered_turn_replays_instead_of_rerunning(factory, world, effect):
    tool = Tool(result={"sent": "m1"})
    first = await go(world, tool, effect=effect)
    again = await go(world, tool, effect=effect)  # the requeued turn asks again
    assert tool.runs == 1
    assert again["replayed"] is True and again["result"] == first["result"] == {"sent": "m1"}
    assert len(await rows(factory)) == 1


async def test_replay_returns_the_typed_result(factory, world):
    tool = Tool(result=ExecutorResult(success=True, outputs={"id": 7}))
    await go(world, tool)
    again = await go(world, tool)
    assert tool.runs == 1
    assert isinstance(again["result"], ExecutorResult) and again["result"].outputs == {"id": 7}


async def test_different_slots_or_turns_are_different_calls(factory, world):
    tool = Tool()
    await go(world, tool, args={"to": "a"}, slot=ToolSlot(0, 0))
    await go(world, tool, args={"to": "b"}, slot=ToolSlot(0, 1))
    await go(world, tool, args={"to": "a"}, slot=ToolSlot(0, 0), ctx=turn_ctx(world, uuid.uuid4()))
    assert tool.runs == 3
    assert len(await rows(factory)) == 3


async def test_argument_key_order_does_not_make_a_new_call(factory, world):
    tool = Tool()
    await go(world, tool, args={"a": 1, "b": 2})
    await go(world, tool, args={"b": 2, "a": 1})
    assert tool.runs == 1


async def test_read_only_tools_are_never_ledgered(factory, world):
    tool = Tool()
    await go(world, tool, effect=EffectClass.READ_ONLY)
    await go(world, tool, effect=EffectClass.READ_ONLY)
    assert tool.runs == 2 and await rows(factory) == []


async def test_calls_without_a_turn_are_not_ledgered(factory, world):
    tool = Tool()
    await go(world, tool, ctx=world["ctx"])
    await go(world, tool, ctx=world["ctx"])
    assert tool.runs == 2 and await rows(factory) == []


async def test_missing_classification_fails_closed(factory, world):
    """No declared class on a write-capable tool: an interrupted run is never repeated."""
    tool = Tool(raises=RuntimeError("connection reset"))
    with pytest.raises(RuntimeError):
        await go(world, tool, effect=None)
    again = Tool()
    out = await go(world, again, effect=None)
    assert again.runs == 0 and out["status"] == "effect_recovery_required"
    (row,) = await rows(factory)
    assert row.effect_class == "non_idempotent_write"


async def test_ambiguous_non_idempotent_never_reruns_and_needs_a_person(factory, world):
    boom = Tool(raises=RuntimeError("socket closed mid-write"))
    with pytest.raises(RuntimeError):
        await go(world, boom)
    (row,) = await rows(factory)
    assert row.status == "ambiguous" and row.claim_token is None

    for _ in range(3):  # every recovery attempt is refused
        retry = Tool()
        out = await go(world, retry)
        assert retry.runs == 0 and out["status"] == "effect_recovery_required"
    (row,) = await rows(factory)
    assert row.status == "manual_recovery_required" and row.attempt_count == 1


async def test_ambiguous_idempotent_is_retried_once_per_claim(factory, world):
    with pytest.raises(RuntimeError):
        await go(world, Tool(raises=RuntimeError("reset")), effect=IDEM)
    retry = Tool(result={"ok": 2})
    out = await go(world, retry, effect=IDEM)
    assert retry.runs == 1 and out["result"] == {"ok": 2} and "replayed" not in out
    (row,) = await rows(factory)
    assert row.status == "succeeded" and row.attempt_count == 2
    again = Tool()
    assert (await go(world, again, effect=IDEM))["replayed"] is True and again.runs == 0


async def test_typed_pre_effect_refusal_is_retryable_for_both_classes(factory, world):
    for position, effect in enumerate((IDEM, NON_IDEM)):
        slot = ToolSlot(0, position)
        with pytest.raises(EffectNotStarted):
            await go(world, Tool(raises=EffectNotStarted("bad input")), effect=effect, slot=slot)
        retry = Tool()
        out = await go(world, retry, effect=effect, slot=slot)
        assert retry.runs == 1 and out["status"] == "success"


async def test_tool_reported_rejection_is_failed_and_retryable(factory, world):
    bad = Tool(result=ExecutorResult(success=False, error="validation: missing field",
                                     effect_rejected=True))
    await go(world, bad)
    (row,) = await rows(factory)
    assert row.status == "failed" and "missing field" in row.error
    good = Tool(result=ExecutorResult(success=True, outputs={}))
    await go(world, good)
    assert good.runs == 1


async def test_timeout_reported_by_the_tool_is_ambiguous(factory, world):
    await go(world, Tool(result=ExecutorResult(success=False, error="timed out",
                                               effect_unknown=True)))
    (row,) = await rows(factory)
    assert row.status == "ambiguous"
    retry = Tool()
    assert (await go(world, retry))["status"] == "effect_recovery_required"
    assert retry.runs == 0


async def test_cancellation_leaves_an_ambiguous_effect(factory, world):
    gate = asyncio.Event()
    tool = Tool(gate=gate)
    task = asyncio.create_task(go(world, tool))
    for _ in range(200):
        if tool.runs:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (row,) = await rows(factory)
    assert row.status == "ambiguous" and row.claim_token is None
    retry = Tool()
    assert (await go(world, retry))["status"] == "effect_recovery_required"
    assert retry.runs == 0


async def test_crash_mid_call_expired_lease_never_reruns_non_idempotent(factory, world):
    """A worker dies while executing: the row stays 'executing' with a live lease."""
    gate = asyncio.Event()
    tool = Tool(gate=gate)
    task = asyncio.create_task(go(world, tool))
    for _ in range(200):
        if tool.runs:
            break
        await asyncio.sleep(0.01)
    (row,) = await rows(factory)
    assert row.status == "executing"

    retry = Tool()
    assert (await go(world, retry))["status"] == "effect_in_progress"  # lease still live
    assert retry.runs == 0

    await expire_lease(factory, row.id)  # the holder is presumed dead
    out = await go(world, retry)
    assert retry.runs == 0 and out["status"] == "effect_recovery_required"
    (row,) = await rows(factory)
    assert row.status == "manual_recovery_required"

    gate.set()  # the zombie finishes late: it must not overwrite the ledger
    await task
    (row,) = await rows(factory)
    assert row.status == "manual_recovery_required" and row.result is None


async def test_expired_lease_idempotent_is_retaken_and_zombie_cannot_settle(factory, world):
    gate = asyncio.Event()
    slow = Tool(gate=gate, result={"who": "zombie"})
    task = asyncio.create_task(go(world, slow, effect=IDEM))
    for _ in range(200):
        if slow.runs:
            break
        await asyncio.sleep(0.01)
    (row,) = await rows(factory)
    await expire_lease(factory, row.id)

    fresh = Tool(result={"who": "retake"})
    assert (await go(world, fresh, effect=IDEM))["result"] == {"who": "retake"}
    gate.set()
    await task  # the zombie's late settle is a no-op
    (row,) = await rows(factory)
    assert row.status == "succeeded" and row.result["value"] == {"who": "retake"}
    assert row.attempt_count == 2


async def test_concurrent_claims_have_exactly_one_winner(factory, world):
    gate = asyncio.Event()
    tool = Tool(gate=gate)
    callers = [asyncio.create_task(go(world, tool)) for _ in range(6)]
    for _ in range(300):
        if tool.runs >= 1 and sum(t.done() for t in callers) >= 5:
            break
        await asyncio.sleep(0.01)
    gate.set()
    outs = await asyncio.gather(*callers)
    assert tool.runs == 1
    statuses = sorted(o["status"] for o in outs)
    assert statuses.count("success") == 1
    assert all(s in ("success", "effect_in_progress") for s in statuses)
    assert len(await rows(factory)) == 1


async def test_ledger_failure_refuses_the_write(factory, world, monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(effects, "claim", broken)
    tool = Tool()
    out = await go(world, tool)
    assert tool.runs == 0 and out["status"] == "effect_ledger_unavailable"


async def test_non_canonical_arguments_refuse_the_write(factory, world):
    tool = Tool()
    out = await go(world, tool, args={"x": object()})
    assert tool.runs == 0 and out["status"] == "effect_ledger_unavailable"


async def test_failed_settle_leaves_the_row_executing_so_recovery_stays_safe(
    factory, world, monkeypatch
):
    async def no_settle(*a, **k):
        return False

    tool = Tool()
    with monkeypatch.context() as patched:
        patched.setattr(effects, "settle", no_settle)
        await go(world, tool)
    (row,) = await rows(factory)
    assert row.status == "executing"
    await expire_lease(factory, row.id)
    retry = Tool()
    assert (await go(world, retry))["status"] == "effect_recovery_required"
    assert retry.runs == 0


async def test_tenants_do_not_share_keys(factory, world):
    other_agent = None
    async with factory() as db:
        other_agent = Agent(company_id=world["other"], name="O", role="engineer")
        db.add(other_agent)
        await db.commit()
    other_ctx = replace(
        ExecutionContext.for_agent(other_agent, source="hermes"),
        turn_id=world["turn"], turn_attempt=1,
    )
    a, b = Tool(), Tool()
    await go(world, a)
    await go(world, b, ctx=other_ctx)
    assert a.runs == 1 and b.runs == 1
    assert {r.company_id for r in await rows(factory)} == {world["acme"], world["other"]}


async def test_access_and_policy_refusals_still_apply_before_the_ledger(factory, world):
    ctx = replace(world["ctx"], company_id=world["other"], turn_id=world["turn"])
    tool = Tool()
    await guarded_call(ctx, "send-it", {}, tool, source="test", effect="non_idempotent_write")
    # The agent belongs to another company, so the access check denies (audit mode keeps
    # going, but a write that the ledger tracks must still be attributed to the caller's
    # tenant only).
    assert all(r.company_id == world["other"] for r in await rows(factory))


# --- audit -----------------------------------------------------------------------------------


async def audit_rows(factory) -> list[AuditLog]:
    async with factory() as db:
        return list((await db.execute(
            select(AuditLog).where(AuditLog.action.like("tool_effect.%"))
        )).scalars().all())


async def test_audit_events_carry_no_secrets_or_arguments(factory, world):
    secret = "sk-live-SUPERSECRETVALUE"
    args = {"api_key": secret, "body": "hello there"}
    with pytest.raises(RuntimeError):
        await go(world, Tool(raises=RuntimeError(f"failed {secret}")), args=args)
    await go(world, Tool(), args=args)  # manual_recovery_required transition
    events = await audit_rows(factory)
    assert {e.action for e in events} >= {"tool_effect.ambiguous",
                                          "tool_effect.manual_recovery_required"}
    dump = json.dumps([e.details for e in events], default=str)
    assert secret not in dump and "hello there" not in dump
    for e in events:
        assert e.resource_type == "tool_effect" and e.company_id == world["acme"]
    (row,) = await rows(factory)
    assert secret not in (row.error or "")


async def test_replay_is_audited(factory, world):
    await go(world, Tool())
    await go(world, Tool())
    assert "tool_effect.replayed" in {e.action for e in await audit_rows(factory)}


async def test_invocation_rows_record_replays(factory, world):
    await go(world, Tool())
    await go(world, Tool())
    async with factory() as db:
        statuses = [i.status for i in (await db.execute(select(ToolInvocation))).scalars()]
    assert sorted(statuses) == ["replayed", "success"]


# --- manual recovery -------------------------------------------------------------------------


async def stuck(factory, world, effect=NON_IDEM):
    with pytest.raises(RuntimeError):
        await go(world, Tool(raises=RuntimeError("reset")), effect=effect)
    (row,) = await rows(factory)
    return row


async def test_manual_resolution_applied_replays_the_operator_note(factory, world):
    row = await stuck(factory, world)
    out = await effects.resolve_manual_recovery(
        world["acme"], row.id, "applied", actor="ops@acme.test",
        reason="confirmed in provider console", note="message m-9 delivered",
    )
    assert out["status"] == "succeeded"
    tool = Tool()
    again = await go(world, tool)
    assert tool.runs == 0 and again["replayed"] is True
    assert again["result"]["manual_recovery"] == "applied"
    (row,) = await rows(factory)
    assert row.resolved_by == "ops@acme.test" and row.resolved_at is not None
    events = [e for e in await audit_rows(factory)
              if e.action == "tool_effect.manual_recovery_resolved"]
    assert len(events) == 1 and events[0].actor_type == "user"
    assert events[0].actor_id == "ops@acme.test" and events[0].details["outcome"] == "applied"


async def test_manual_resolution_not_applied_allows_one_new_run(factory, world):
    row = await stuck(factory, world)
    await go(world, Tool())  # drives it to manual_recovery_required
    await effects.resolve_manual_recovery(
        world["acme"], row.id, "not_applied", actor="ops", reason="provider has no record"
    )
    tool = Tool(result={"ok": 3})
    assert (await go(world, tool))["result"] == {"ok": 3}
    assert tool.runs == 1
    again = Tool()
    assert (await go(world, again))["replayed"] is True and again.runs == 0


async def test_manual_resolution_is_guarded(factory, world):
    row = await stuck(factory, world)
    with pytest.raises(ValueError):
        await effects.resolve_manual_recovery(world["acme"], row.id, "applied", actor=" ",
                                              reason="r")
    with pytest.raises(ValueError):
        await effects.resolve_manual_recovery(world["acme"], row.id, "applied", actor="a",
                                              reason="")
    with pytest.raises(ValueError):
        await effects.resolve_manual_recovery(world["acme"], row.id, "maybe", actor="a",
                                              reason="r")
    with pytest.raises(LookupError):  # another tenant cannot see or resolve it
        await effects.resolve_manual_recovery(world["other"], row.id, "applied", actor="a",
                                              reason="r")
    await effects.resolve_manual_recovery(world["acme"], row.id, "not_applied", actor="a",
                                          reason="r")
    with pytest.raises(effects.EffectStateError):  # already resolved
        await effects.resolve_manual_recovery(world["acme"], row.id, "applied", actor="a",
                                              reason="r")


async def test_manual_resolution_refuses_an_executing_row(factory, world):
    gate = asyncio.Event()
    tool = Tool(gate=gate)
    task = asyncio.create_task(go(world, tool))
    for _ in range(200):
        if tool.runs:
            break
        await asyncio.sleep(0.01)
    (row,) = await rows(factory)
    with pytest.raises(effects.EffectStateError):
        await effects.resolve_manual_recovery(world["acme"], row.id, "applied", actor="a",
                                              reason="r")
    gate.set()
    await task


async def test_list_open_is_tenant_scoped_and_holds_no_payload(factory, world):
    row = await stuck(factory, world)
    page = await effects.list_open(world["acme"])
    assert [r["id"] for r in page["items"]] == [str(row.id)] and page["next_cursor"] is None
    assert set(page["items"][0]) == {"id", "turn_id", "round_index", "invocation_index",
                                     "tool_name", "effect_class", "status", "attempt_count",
                                     "arguments_digest", "created_at"}
    assert await effects.list_open(world["other"]) == {"items": [], "next_cursor": None}


# --- wiring ----------------------------------------------------------------------------------


async def test_call_llm_binds_the_chat_turn_id_to_the_execution_context():
    import inspect

    from nexus.api.routes import chat

    src = inspect.getsource(chat._call_llm)
    assert "replace(execution_context, turn_id=turn_id)" in src


def test_node_effects_cover_every_exposed_node_and_classify_writes():
    from nexus.tools import mcp_server

    exposed = set(mcp_server.exposed_nodes())
    assert exposed, "no executable nodes found"
    assert exposed <= set(mcp_server.NODE_EFFECTS), exposed - set(mcp_server.NODE_EFFECTS)
    assert mcp_server.NODE_EFFECTS["http-request"] is NON_IDEM
    assert mcp_server.NODE_EFFECTS["msg-slack-send"] is NON_IDEM
    assert mcp_server.NODE_EFFECTS["db-sqlite-query"] is NON_IDEM
    assert mcp_server.NODE_EFFECTS["db-redis-set"] is NON_IDEM
    assert mcp_server.NODE_EFFECTS["file-json-parse"] is EffectClass.READ_ONLY


def test_every_manager_and_ceo_tool_declares_its_class():
    from nexus.tools import ceo_tools, manager_tools

    expected = {
        "manager_delegate_task": IDEM,
        "manager_request_hire": IDEM,
        "ceo_delegate_task_to_manager": IDEM,
        "ceo_create_goal_or_work_order": IDEM,
        "ceo_request_hire": IDEM,
        "ceo_record_decision": NON_IDEM,
    }
    tools = {**manager_tools.MANAGER_TOOLS, **ceo_tools.CEO_TOOLS}
    assert set(expected) <= set(tools)
    for name, tool in tools.items():
        assert isinstance(tool.effect, EffectClass), name
        assert tool.effect is expected.get(name, EffectClass.READ_ONLY), name
        # a tool that writes (by its own risk label) is never declared read-only
        if tool.risk != "read":
            assert tool.effect is not EffectClass.READ_ONLY, name


def test_manager_tool_effect_is_required():
    from nexus.tools.manager_tools import ManagerTool

    with pytest.raises(TypeError):
        ManagerTool(description="d", risk="read", params=(), run=None)  # type: ignore[call-arg]
