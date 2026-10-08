"""Each of the eight system-runtime operations, run against real rows.

The catalogue is an allow-list, so every entry gets the same guarantees checked the same
way (``OPS`` below seeds each operation's trigger rows):

* a fixed name and function, with a bounded batch and a timeout;
* at most ``batch_size`` companies per run, however many have work;
* a second run changes nothing (idempotent);
* one company failing neither stops another nor touches its rows, and a retry finishes it;
* a company with nothing due is left exactly as it was;
* the audit stream, the log and the result carry counts and codes, never row content;
* a hung operation times out, and a cancelled one releases its lease, with no sleeps;
* nothing in the pass reaches a model, a tool or a prompt.

Seed rows hold ``SECRET`` in every free-text column so a leak anywhere shows up.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 - registers every table
from nexus import database
from nexus.models.agent import Agent
from nexus.models.budget import BudgetPolicy, CostEvent
from nexus.models.chat_turn import ChatTurn
from nexus.models.company import Company
from nexus.models.governance import Decision
from nexus.models.heartbeat_run import HeartbeatRun
from nexus.models.organization_snapshot import OrganizationSnapshot, OrganizationSnapshotState
from nexus.models.task import Goal, Task
from nexus.models.task_attempt import TaskAttempt
from nexus.models.tool_effect import ToolEffect
from nexus.runtime import watchdog_service, work_hints
from nexus.system_runtime import audit, status
from nexus.system_runtime.ops import OPERATIONS
from nexus.system_runtime.runner import SystemRuntime

SECRET = "SECRET-tenant-content-7f3a"
OLD = timedelta(days=10)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# -- seeds: one "due" and one "nothing due" shape per operation ---------------------------


async def _seed_budget(s, cid, due):
    policy = BudgetPolicy(
        company_id=cid, scope_type="company", scope_id=cid, metric="cost_cents",
        window_kind="monthly", amount=1000, reserved_cents=100,
    )
    s.add(policy)
    await s.flush()
    expires = _now() - timedelta(hours=1) if due else _now() + timedelta(hours=1)
    s.add(CostEvent(
        company_id=cid, policy_id=policy.id, provider="p", model=SECRET, cost_cents=100,
        status="reserved", expires_at=expires,
    ))


async def _probe_budget(s, cid):
    event = (await s.execute(select(CostEvent.status).where(CostEvent.company_id == cid))).scalar()
    held = (
        await s.execute(
            select(BudgetPolicy.reserved_cents).where(BudgetPolicy.company_id == cid)
        )
    ).scalar()
    return event, held


async def _seed_tasks(s, cid, due):
    s.add(Task(
        company_id=cid, title=SECRET, description=SECRET, status="in_progress",
        started_at=_now() - OLD if due else _now(),
    ))
    s.add(Goal(
        company_id=cid, title=SECRET, status="in_progress",
        updated_at=_now() - OLD if due else _now(),
    ))


async def _probe_tasks(s, cid):
    task = (await s.execute(select(Task.status).where(Task.company_id == cid))).scalar()
    goal = (await s.execute(select(Goal.status).where(Goal.company_id == cid))).scalar()
    return task, goal


async def _seed_goal_hint(s, cid, due):
    if due:
        s.add(Goal(company_id=cid, title=SECRET, status="active", owner_agent_id=uuid.uuid4()))


async def _probe_goal_hint(s, cid):
    return None  # the observable effect is the hint set; see ``_World.probe``


async def _seed_chat(s, cid, due):
    s.add(ChatTurn(
        company_id=cid, agent_id=uuid.uuid4(), session_id=uuid.uuid4(),
        idempotency_key=uuid.uuid4().hex, turn_seq=1, status="queued",
        queued_at=_now() - OLD if due else _now(), execution_context={"prompt": SECRET},
    ))


async def _probe_chat(s, cid):
    row = (
        await s.execute(
            select(ChatTurn.status, ChatTurn.error_code).where(ChatTurn.company_id == cid)
        )
    ).one()
    return tuple(row)


async def _seed_attempt(s, cid, due):
    s.add(TaskAttempt(
        company_id=cid, task_id=uuid.uuid4(), agent_id=uuid.uuid4(), attempt_number=1,
        idempotency_key=uuid.uuid4().hex, status="queued",
        queued_at=_now() - OLD if due else _now(), context_snapshot={"prompt": SECRET},
    ))


async def _probe_attempt(s, cid):
    row = (
        await s.execute(
            select(TaskAttempt.status, TaskAttempt.error_code).where(TaskAttempt.company_id == cid)
        )
    ).one()
    return tuple(row)


async def _seed_effect(s, cid, due):
    lease = _now() - timedelta(hours=1) if due else _now() + timedelta(hours=1)
    s.add(ToolEffect(
        company_id=cid, turn_id=uuid.uuid4(), round_index=0, invocation_index=0,
        tool_name="t", effect_class="non_idempotent_write", invocation_key=uuid.uuid4().hex,
        arguments_digest="d", claim_token="c", lease_expires_at=lease, result={"x": SECRET},
    ))


async def _probe_effect(s, cid):
    return (
        await s.execute(select(ToolEffect.status).where(ToolEffect.company_id == cid))
    ).scalar()


async def _seed_watchdog(s, cid, due):
    agent = Agent(company_id=cid, name="w", role="r", model="m")
    s.add(agent)
    await s.flush()
    silent = timedelta(hours=5) if due else timedelta(seconds=1)
    s.add(HeartbeatRun(
        agent_id=agent.id, started_at=_now() - timedelta(hours=6),
        last_output_at=_now() - silent, stdout_excerpt=SECRET,
        context_snapshot={"prompt": SECRET},
    ))


async def _probe_watchdog(s, cid):
    agent_ids = select(Agent.id).where(Agent.company_id == cid)
    closed = (
        await s.execute(
            select(func.count()).select_from(HeartbeatRun).where(
                HeartbeatRun.agent_id.in_(agent_ids), HeartbeatRun.finished_at.is_not(None)
            )
        )
    ).scalar()
    decisions = (
        await s.execute(
            select(func.count()).select_from(Decision).where(Decision.company_id == cid)
        )
    ).scalar()
    return closed, decisions


async def _seed_org(s, cid, due):
    if not due:
        s.add(OrganizationSnapshotState(company_id=cid, attempted_at=_now()))


async def _probe_org(s, cid):
    versions = (
        await s.execute(
            select(func.count()).select_from(OrganizationSnapshot).where(
                OrganizationSnapshot.company_id == cid
            )
        )
    ).scalar()
    return versions


@dataclasses.dataclass(frozen=True)
class Case:
    seed: object
    probe: object
    passes: int = 1  # runs needed before the result settles (the watchdog flags on the second)
    tenant_sessions: bool = True  # False: the operation only publishes company ids


CASES = {
    "budget_reservation_reap": Case(_seed_budget, _probe_budget),
    "task_recovery": Case(_seed_tasks, _probe_tasks),
    "goal_discovery": Case(_seed_goal_hint, _probe_goal_hint, tenant_sessions=False),
    "chat_turn_recovery": Case(_seed_chat, _probe_chat),
    "task_attempt_recovery": Case(_seed_attempt, _probe_attempt),
    "watchdog_patrol": Case(_seed_watchdog, _probe_watchdog, passes=3),
    "org_snapshot_refresh": Case(_seed_org, _probe_org),
    "tool_effect_lease_expiry": Case(_seed_effect, _probe_effect),
}


def test_every_operation_in_the_catalogue_has_a_case():
    assert set(CASES) == set(OPERATIONS)


# -- the world ----------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self):
        self.sets: dict[str, set[str]] = {}

    async def sadd(self, key, *members):
        self.sets.setdefault(key, set()).update(members)

    async def expire(self, key, ttl):
        return True

    async def set(self, key, value, ex=None):
        return True

    async def get(self, key):
        return None


class _World:
    def __init__(self, factory):
        self.factory = factory
        self.redis = _FakeRedis()
        self.fail_for: dict[uuid.UUID, BaseException] = {}
        self.opened: list[uuid.UUID] = []
        self.companies: list[uuid.UUID] = []

    async def add_companies(self, case: Case, n: int, due: bool = True) -> list[uuid.UUID]:
        ids = []
        async with self.factory() as s:
            for i in range(n):
                company = Company(name=f"c{len(self.companies) + i}")
                s.add(company)
                await s.flush()
                await case.seed(s, company.id, due)
                ids.append(company.id)
            await s.commit()
        self.companies += ids
        return ids

    async def probe(self, name: str, ids) -> dict:
        case = CASES[name]
        if name == "goal_discovery":
            hinted = self.redis.sets.get("nexus:hints:goals", set())
            return {cid: str(cid) in hinted for cid in ids}
        async with self.factory() as s:
            return {cid: await case.probe(s, cid) for cid in ids}

    def discovery(self):
        return self.factory()

    async def run(self, name: str, times: int | None = None):
        op = OPERATIONS[name]
        result = None
        for _ in range(times or CASES[name].passes):
            result = await op.run(self.discovery, _now())
        return result


@pytest.fixture
async def world(tmp_path, monkeypatch):
    watchdog_service._reset_for_tests()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ops.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", factory)
    w = _World(factory)

    real = database.tenant_session

    @asynccontextmanager
    async def guarded(company_id):
        w.opened.append(company_id)
        if company_id in w.fail_for:
            raise w.fail_for[company_id]
        async with real(company_id) as session:
            yield session

    monkeypatch.setattr(database, "tenant_session", guarded)

    async def get_redis():
        return w.redis

    monkeypatch.setattr(work_hints, "get_redis", get_redis)
    monkeypatch.setattr(status, "get_redis", get_redis)
    audit.clear_subscribers()
    yield w
    audit.clear_subscribers()
    watchdog_service._reset_for_tests()
    await engine.dispose()


names = pytest.mark.parametrize("name", sorted(OPERATIONS))


# -- a fixed operation ---------------------------------------------------------------------


@names
def test_the_name_the_function_and_the_catalogue_key_are_one_fixed_string(name):
    op = OPERATIONS[name]
    assert op.name == name and op.run.__name__ == name


# -- bounded batch -------------------------------------------------------------------------


@names
async def test_a_run_handles_at_most_one_batch_of_companies(world, name):
    op = OPERATIONS[name]
    ids = await world.add_companies(CASES[name], op.batch_size + 5)
    before = await world.probe(name, ids)

    result = await op.run(world.discovery, _now())

    assert 0 < result.seen <= op.batch_size, "one run never looks at more than a batch"
    assert result.processed + result.failed <= op.batch_size
    if CASES[name].passes == 1:
        after = await world.probe(name, ids)
        changed = [c for c in ids if before[c] != after[c]]
        assert 0 < len(changed) <= op.batch_size


@names
async def test_nothing_runs_when_no_company_has_work(world, name):
    await world.add_companies(CASES[name], 3, due=False)
    before = await world.probe(name, world.companies)
    result = await world.run(name)
    assert result.failed == 0
    assert await world.probe(name, world.companies) == before


# -- idempotent ----------------------------------------------------------------------------


@names
async def test_a_second_execution_changes_nothing(world, name):
    ids = await world.add_companies(CASES[name], 3)
    first = await world.run(name)
    assert first.failed == 0
    settled = await world.probe(name, ids)

    again = await world.run(name, times=1)

    assert again.failed == 0
    assert await world.probe(name, ids) == settled
    if name not in ("goal_discovery", "watchdog_patrol"):
        # Recovery has nothing left to find, so it no longer even visits the companies.
        assert again.seen == 0


@names
async def test_the_work_actually_happens_for_a_due_company(world, name):
    """Guards the other tests: the seeded 'due' rows really are what the operation acts on."""
    due = await world.add_companies(CASES[name], 1)
    quiet = await world.add_companies(CASES[name], 1, due=False)
    before = await world.probe(name, due + quiet)
    await world.run(name)
    after = await world.probe(name, due + quiet)
    assert after[due[0]] != before[due[0]]
    assert after[quiet[0]] == before[quiet[0]], "a company with nothing due is not touched"


# -- failure, retry, isolation ---------------------------------------------------------------

TENANT_OPS = sorted(n for n, c in CASES.items() if c.tenant_sessions)


@pytest.mark.parametrize("name", TENANT_OPS)
async def test_one_failing_company_neither_stops_another_nor_leaks_content(
    world, name, caplog
):
    caplog.set_level(logging.DEBUG, logger="nexus")
    ids = sorted(await world.add_companies(CASES[name], 4), key=str)
    # The first and last by id: whichever order a run walks them, a failure that aborted
    # the run would starve the companies behind it.
    bad = [ids[0], ids[-1]]
    healthy = ids[1:-1]
    before = await world.probe(name, ids)
    for cid in bad:
        world.fail_for[cid] = RuntimeError(f"row for {cid} held {SECRET}")

    await world.run(name)
    after = await world.probe(name, ids)

    for cid in bad:
        assert after[cid] == before[cid], "a failed company's rows are unchanged"
    for cid in healthy:
        assert after[cid] != before[cid], "the other companies were still processed"
    assert SECRET not in caplog.text, "only the exception class is logged"


@pytest.mark.parametrize("name", TENANT_OPS)
async def test_a_failed_company_is_finished_by_the_next_run(world, name):
    ids = await world.add_companies(CASES[name], 2)
    bad = sorted(ids, key=str)[0]
    pristine = (await world.probe(name, [bad]))[bad]
    world.fail_for[bad] = RuntimeError("transient")

    await world.run(name)
    assert (await world.probe(name, [bad]))[bad] == pristine

    world.fail_for.clear()
    await world.run(name)
    assert (await world.probe(name, [bad]))[bad] != pristine


async def test_a_failed_publish_is_retried_and_never_fails_the_run(world, monkeypatch):
    ids = await world.add_companies(CASES["goal_discovery"], 2)
    real = world.redis.sadd

    async def broken(key, *members):
        raise ConnectionError(f"down {SECRET}")

    world.redis.sadd = broken
    result = await world.run("goal_discovery")
    assert result.processed == 0 and result.failed == 0
    assert not world.redis.sets

    world.redis.sadd = real
    result = await world.run("goal_discovery")
    assert result.processed == 2
    assert world.redis.sets["nexus:hints:goals"] == {str(c) for c in ids}


# -- no cross-tenant writes --------------------------------------------------------------


@pytest.mark.parametrize("name", TENANT_OPS)
async def test_work_for_a_company_opens_only_that_companys_session(world, name):
    due = await world.add_companies(CASES[name], 2)
    quiet = await world.add_companies(CASES[name], 2, due=False)
    await world.run(name)
    # A tenant session is opened for a company only if discovery found work for it.
    assert set(world.opened) <= set(due) | set(quiet)
    assert set(due) <= set(world.opened)


async def test_goal_discovery_publishes_ids_and_nothing_else(world):
    ids = await world.add_companies(CASES["goal_discovery"], 3)
    await world.run("goal_discovery")
    published = world.redis.sets
    assert set(published) == {"nexus:hints:goals"}
    assert published["nexus:hints:goals"] == {str(c) for c in ids}
    assert SECRET not in repr(published)
    assert world.opened == [], "no tenant session at all: ids only"


# -- content-free audit, metrics and logs --------------------------------------------------


@pytest.fixture
def runtime_for(world):
    class Lease:
        async def acquire(self, *_):
            return True

        async def release(self, *_):
            return None

        async def held(self, *_):
            return True

    def make(name, op=None):
        return SystemRuntime(
            lambda _name: world.discovery,
            operations={name: op or OPERATIONS[name]},
            lease=Lease(),
            instance_id="ops-test",
        )

    return make


@names
async def test_the_audit_stream_and_metrics_hold_counts_and_codes_only(
    world, runtime_for, name, caplog, monkeypatch
):
    from nexus.observability import metrics

    seen: list[dict] = []
    audit.subscribe(seen.append)
    recorded: list[tuple] = []
    monkeypatch.setattr(
        "nexus.system_runtime.runner.record_system_runtime_op",
        lambda *a, **k: recorded.append((a, k)),
    )
    caplog.set_level(logging.DEBUG, logger="nexus")
    await world.add_companies(CASES[name], 3)

    await runtime_for(name).run_operation(OPERATIONS[name])

    assert [e["event"] for e in seen] == ["op_started", "op_completed"]
    done = seen[-1]
    assert set(done) <= {
        "event", "operation", "companies_seen", "companies_processed", "companies_failed",
        "batches", "duration_ms",
    }
    assert done["operation"] == name
    ((args, kwargs),) = recorded
    assert args[0] == name and all(isinstance(v, (int, float, bool)) for v in kwargs.values())
    assert SECRET not in repr(seen) + repr(recorded) + caplog.text
    assert metrics  # the real counters exist; the spy above kept the test off their registry


# -- timeout, cancellation, shutdown --------------------------------------------------------


class _Hang:
    """A discovery session that never answers."""

    def __call__(self):
        return self

    async def __aenter__(self):
        await asyncio.Event().wait()

    async def __aexit__(self, *exc):
        return False


@names
async def test_a_hung_operation_times_out_with_a_stable_code_and_releases_its_lease(
    world, name
):
    events: list[dict] = []
    audit.subscribe(events.append)
    released: list[str] = []

    class Lease:
        async def acquire(self, *_):
            return True

        async def release(self, lease, token):
            released.append(lease)

        async def held(self, *_):
            return True

    op = dataclasses.replace(OPERATIONS[name], timeout_seconds=0.05)
    runtime = SystemRuntime(
        lambda _n: _Hang(), operations={name: op}, lease=Lease(), instance_id="t"
    )
    await runtime.run_operation(op)

    assert [(e["event"], e.get("code")) for e in events] == [
        ("op_started", None),
        ("op_failed", "OP_TIMEOUT"),
    ]
    assert released == [f"system_runtime:{name}"]
    assert name not in runtime.last_success


@names
async def test_shutdown_mid_operation_cancels_cleanly_and_releases_the_lease(world, name):
    released: list[str] = []
    entered = asyncio.Event()

    class Lease:
        async def acquire(self, *_):
            return True

        async def release(self, lease, token):
            released.append(lease)

        async def held(self, *_):
            return True

    class Blocked(_Hang):
        async def __aenter__(self):
            entered.set()
            await asyncio.Event().wait()

    runtime = SystemRuntime(
        lambda _n: Blocked(),
        operations={name: OPERATIONS[name]},
        lease=Lease(),
        instance_id="t",
    )
    task = asyncio.ensure_future(runtime.run_operation(OPERATIONS[name]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released == [f"system_runtime:{name}"]
    assert name not in runtime.last_success


# -- no model, tool or prompt ----------------------------------------------------------------


@names
async def test_no_operation_reaches_a_model_a_tool_or_a_prompt(world, name, monkeypatch):
    """Every surface that could run an agent is made to fail loudly; no operation touches one."""
    import socket

    from nexus.adapters import base as adapters_base
    from nexus.tools.registry import ToolRegistry

    def refuse(*_a, **_k):
        raise AssertionError("an operation reached a model, a tool or the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for cls in _subclasses(adapters_base.BaseAdapter):
        for method in ("execute", "stream", "run"):
            if method in vars(cls):
                monkeypatch.setattr(cls, method, refuse)
    for method in ("execute", "execute_tool", "call"):
        if hasattr(ToolRegistry, method):
            monkeypatch.setattr(ToolRegistry, method, refuse)

    await world.add_companies(CASES[name], 3)
    result = await world.run(name)
    assert result.failed == 0


def _subclasses(cls):
    out = [cls]
    for sub in cls.__subclasses__():
        out += _subclasses(sub)
    return out


# -- the one unbounded read, documented ------------------------------------------------------


async def test_org_snapshot_discovery_reads_ids_and_timestamps_for_every_company(world):
    """``org_snapshot.tick`` lists every company's id and state timestamps, then caps the work.

    Known and accepted: it cannot be bounded in SQL without a second index, and a row is two
    ids and four timestamps. Generation is capped by ``MAX_PER_TICK``, which equals the
    catalogue's batch size, so a large fleet is walked over several runs, oldest attempt first.
    """
    from nexus.services import org_snapshot

    assert org_snapshot.MAX_PER_TICK == OPERATIONS["org_snapshot_refresh"].batch_size
    ids = await world.add_companies(CASES["org_snapshot_refresh"], org_snapshot.MAX_PER_TICK + 5)
    first = await world.run("org_snapshot_refresh")
    assert first.processed == org_snapshot.MAX_PER_TICK
    second = await world.run("org_snapshot_refresh")
    assert second.processed == 5, "the companies left over go next, not the same twenty again"
    third = await world.run("org_snapshot_refresh")
    assert third.processed == 0
    probe = await world.probe("org_snapshot_refresh", ids)
    assert all(count == 1 for count in probe.values())
