"""The system runtime's Redis leases: one executor, fail closed, fenced against a stale owner.

Everything runs against a fake Redis whose expiry follows a fake clock, so no test sleeps and
none needs a real Redis. The fake implements only the commands ``system_runtime.lease`` uses.
"""

import ast
import asyncio
from pathlib import Path

import pytest

from nexus.runtime import redis_utils
from nexus.system_runtime import audit, lease, status
from nexus.system_runtime.ops import OPERATIONS, Operation, OpResult
from nexus.system_runtime.runner import SystemRuntime

SRC = Path(__file__).resolve().parents[1] / "src" / "nexus"
KEY = lease.KEY_PREFIX + "system_runtime:goal_discovery"


class FakeRedis:
    """Strings with expiry on a fake clock, SET NX EX, GET and the release script."""

    def __init__(self):
        self.now = 0.0
        self.data: dict[str, tuple[str, float | None]] = {}
        self.down = False
        self.eval_down = False
        self.ttls: list[int] = []

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def _live(self, key):
        item = self.data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires <= self.now:
            del self.data[key]
            return None
        return value

    async def set(self, key, value, nx=False, ex=None):
        if self.down:
            raise ConnectionError("redis down")
        if nx and self._live(key) is not None:
            return None
        self.ttls.append(ex)
        self.data[key] = (value, None if ex is None else self.now + ex)
        return True

    async def get(self, key):
        if self.down:
            raise ConnectionError("redis down")
        return self._live(key)

    async def eval(self, script, numkeys, key, token):
        if self.down or self.eval_down:
            raise ConnectionError("redis down")
        assert script == lease.RELEASE_SCRIPT and numkeys == 1
        if self._live(key) == token:
            del self.data[key]
            return 1
        return 0


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()

    async def get():
        return fake

    monkeypatch.setattr(redis_utils, "get_redis", get)
    monkeypatch.setattr(status, "get_redis", get)
    return fake


@pytest.fixture
def events():
    seen: list[dict] = []
    audit.clear_subscribers()
    audit.subscribe(seen.append)
    yield seen
    audit.clear_subscribers()


def _runtime(*ops, instance="a", clock=None):
    kwargs = {"clock": clock} if clock else {}
    return SystemRuntime(
        lambda name: None,
        operations={op.name: op for op in ops},
        instance_id=instance,
        **kwargs,
    )


def _op(run, name="goal_discovery", timeout=5.0, interval=60.0):
    return Operation(name, interval, 10, timeout, run)


def _codes(events, event):
    return [e.get("code") for e in events if e["event"] == event]


async def _fine(discovery, now):
    return OpResult(seen=1, processed=1, batches=1)


# -- one executor ----------------------------------------------------------------------


async def test_two_runtimes_race_and_exactly_one_executes(redis, events):
    ran, gate = [], asyncio.Event()
    skipped = asyncio.Event()
    audit.subscribe(lambda e: skipped.set() if e["event"] == "op_skipped_not_leader" else None)

    async def work(discovery, now):
        ran.append(1)
        await gate.wait()  # hold the lease until the other runtime has tried and failed
        return OpResult(seen=1, processed=1)

    async def release_gate():
        await skipped.wait()
        gate.set()

    op = _op(work)
    a, b = _runtime(op, instance="a"), _runtime(op, instance="b")
    ra, rb, _ = await asyncio.gather(a.run_operation(op), b.run_operation(op), release_gate())

    assert len(ran) == 1
    assert sorted([ra is None, rb is None]) == [False, True]
    assert len([e for e in events if e["event"] == "op_completed"]) == 1
    assert KEY not in redis.data, "the winner releases its lease"


async def test_when_the_lease_is_held_by_another_the_operation_does_not_run(redis, events):
    redis.data[KEY] = ("someone-else", None)
    ran = []

    async def work(discovery, now):
        ran.append(1)
        return OpResult()

    op = _op(work)
    runtime = _runtime(op)
    assert await runtime.run_operation(op) is None

    assert ran == [] and runtime.lease_store == "ok"
    assert [e["event"] for e in events] == ["op_skipped_not_leader"]
    assert redis.data[KEY] == ("someone-else", None), "a refused runtime never touches the key"


async def test_the_lease_outlives_the_operation_timeout_for_every_operation(redis):
    for name, real in OPERATIONS.items():
        op = Operation(name, 1, 1, real.timeout_seconds, _fine)
        await _runtime(op).run_operation(op)
        assert redis.ttls[-1] > real.timeout_seconds


# -- Redis unavailable: fail closed ----------------------------------------------------


@pytest.mark.parametrize("how", ["unconfigured", "erroring"])
async def test_an_unavailable_lease_store_fails_closed_with_a_stable_status(
    redis, events, monkeypatch, how
):
    ran = []

    async def work(discovery, now):
        ran.append(1)
        return OpResult()

    if how == "erroring":
        redis.down = True
    else:

        async def none():
            return None

        monkeypatch.setattr(redis_utils, "get_redis", none)
        monkeypatch.setattr(redis_utils, "get_redis_url", lambda: None)

    op = _op(work)
    runtime = _runtime(op)
    assert await runtime.run_operation(op) is None

    assert ran == [], "no Redis must never mean 'run anyway'"
    assert runtime.lease_store == "unavailable"
    assert _codes(events, "op_skipped_lease_unavailable") == ["LEASE_STORE_UNAVAILABLE"]
    assert runtime.last_success == {}


async def test_a_down_store_skips_the_rest_of_the_tick_and_is_retried_on_the_next(redis, events):
    ran = []

    async def work(discovery, now):
        ran.append(1)
        return OpResult()

    ops = [_op(work, name) for name in ("goal_discovery", "task_recovery", "watchdog_patrol")]
    clock = [0.0]
    runtime = _runtime(*ops, clock=lambda: clock[0])
    redis.down = True
    await runtime.tick()
    assert ran == [] and len(_codes(events, "op_skipped_lease_unavailable")) == 1

    redis.down = False
    clock[0] += 1  # inside every interval; only the operation attempted last tick waits
    await runtime.tick()
    assert runtime.lease_store == "ok"
    assert len(ran) == len(ops) - 1


async def test_a_failed_first_connection_is_retried_rather_than_cached_forever(monkeypatch):
    forgotten = []

    async def none():
        return None

    monkeypatch.setattr(redis_utils, "get_redis", none)
    monkeypatch.setattr(redis_utils, "get_redis_url", lambda: "redis://down")
    monkeypatch.setattr(redis_utils, "forget_failed_connection", lambda: forgotten.append(1))

    with pytest.raises(lease.LeaseUnavailable):
        await lease.acquire("x", "t", 30)
    assert forgotten == [1]


async def test_the_unavailable_state_is_published_in_the_status_record(redis):
    op = _op(_fine)
    runtime = _runtime(op)
    redis.down = True
    await runtime.tick()
    assert runtime.lease_store == "unavailable"
    redis.down = False
    await status.publish(
        ops_enabled=["goal_discovery"],
        role_validation="ok",
        last_success={},
        lease_store=runtime.lease_store,
    )
    assert (await status.read())["lease_store"] == "unavailable"


# -- stale owner -------------------------------------------------------------------------


async def test_a_stale_owner_cannot_record_success_over_the_new_owner(redis, events):
    new_owner = {}

    async def slow(discovery, now):
        redis.advance(1000)  # the lease expires mid-operation (a paused process, say)
        new_owner["won"] = await lease.acquire("system_runtime:goal_discovery", "b-token", 35)
        return OpResult(seen=1, processed=1)

    op = _op(slow)
    stale = _runtime(op, instance="a")
    result = await stale.run_operation(op)

    assert new_owner["won"] is True
    assert result is not None
    assert "goal_discovery" not in stale.last_success
    assert _codes(events, "op_failed") == ["LEASE_LOST"]
    assert not [e for e in events if e["event"] == "op_completed"]
    assert redis.data[KEY][0] == "b-token", "the stale owner's release must not free the new lease"


async def test_ownership_that_cannot_be_confirmed_is_not_a_success(redis, events):
    async def flaky(discovery, now):
        redis.down = True  # the store drops between the work and the ownership check
        return OpResult(seen=1, processed=1)

    op = _op(flaky)
    runtime = _runtime(op)
    await runtime.run_operation(op)
    assert _codes(events, "op_failed") == ["LEASE_LOST"]
    assert runtime.last_success == {}


async def test_a_runtime_that_still_owns_its_lease_records_success(redis, events):
    op = _op(_fine)
    runtime = _runtime(op)
    await runtime.run_operation(op)
    assert "goal_discovery" in runtime.last_success
    assert [e["event"] for e in events] == ["op_started", "op_completed"]


async def test_release_is_owner_checked(redis):
    assert await lease.acquire("op", "mine", 30)
    await lease.release("op", "not-mine")
    assert redis.data[lease.KEY_PREFIX + "op"][0] == "mine"
    await lease.release("op", "mine")
    assert lease.KEY_PREFIX + "op" not in redis.data


# -- shutdown ------------------------------------------------------------------------------


async def _cancel_mid_operation(runtime):
    started = asyncio.Event()

    async def hang(discovery, now):
        started.set()
        await asyncio.Event().wait()

    op = _op(hang, timeout=5.0)
    task = asyncio.create_task(runtime.run_operation(op))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_shutdown_releases_the_lease(redis):
    runtime = _runtime(_op(_fine))
    await _cancel_mid_operation(runtime)
    assert KEY not in redis.data
    assert runtime.last_success == {}


async def test_shutdown_with_the_store_down_still_ends_and_the_lease_expires(redis):
    runtime = _runtime(_op(_fine))
    redis.eval_down = True  # the release cannot reach the store
    await _cancel_mid_operation(runtime)

    assert KEY in redis.data, "not released, so ownership must expire on its own"
    redis.advance(5 + 30 + 1)
    assert await lease.acquire("system_runtime:goal_discovery", "next", 35), "TTL freed it"


# -- no polling loop --------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["lease.py", "runner.py"])
def test_lease_and_runner_have_no_loop_of_their_own(module):
    tree = ast.parse((SRC / "system_runtime" / module).read_text(encoding="utf-8"))
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    sleeps = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "sleep"]
    assert not loops and not sleeps
