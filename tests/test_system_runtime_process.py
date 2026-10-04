"""The system runtime process: refusals, catalogue, failure behaviour and credential hygiene.

None of this needs PostgreSQL. Role attributes against a real server are covered in
``test_postgres_integration.py``; here the process-level contract is checked: what the
entry point refuses, what an operation may be, how a failing tenant, a hung operation, a
duplicate leader, a cancellation or a broken audit subscriber behave, and that no secret
reaches output.
"""

from __future__ import annotations

import ast
import asyncio
import re
import uuid
from pathlib import Path

import pytest

from nexus.config_validator import ConfigurationError, enforce_no_system_credential
from nexus.system_runtime import __main__ as entry
from nexus.system_runtime import audit, db, status
from nexus.system_runtime.ops import OPERATIONS, Operation, OpResult, _per_company
from nexus.system_runtime.runner import SystemRuntime

SRC = Path(__file__).resolve().parents[1] / "src" / "nexus"
SECRET = "s3cr3t-pw-do-not-print"
SYSTEM_URL = f"postgresql+asyncpg://nexus_system:{SECRET}@127.0.0.1:1/nexus"
APP_URL = f"postgresql+asyncpg://nexus_app:{SECRET}x@127.0.0.1:1/nexus"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("SYSTEM_DATABASE_URL", "MIGRATION_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    audit.clear_subscribers()
    db._engine = None
    yield
    audit.clear_subscribers()
    db._engine = None


def _events():
    seen: list[dict] = []
    audit.subscribe(seen.append)
    return seen


# -- entry point refusals --------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "code"),
    [
        ({"DATABASE_URL": APP_URL}, "SYSTEM_CREDENTIAL_MISSING"),
        ({"SYSTEM_DATABASE_URL": SYSTEM_URL}, "APP_CREDENTIAL_MISSING"),
        (
            {"SYSTEM_DATABASE_URL": APP_URL, "DATABASE_URL": APP_URL},
            "SYSTEM_URL_EQUALS_DATABASE_URL",
        ),
        (
            {"SYSTEM_DATABASE_URL": "sqlite+aiosqlite:///x.db", "DATABASE_URL": APP_URL},
            "POSTGRES_REQUIRED",
        ),
        (
            {"SYSTEM_DATABASE_URL": SYSTEM_URL, "DATABASE_URL": "sqlite+aiosqlite:///:memory:"},
            "POSTGRES_REQUIRED",
        ),
        (
            {
                "SYSTEM_DATABASE_URL": SYSTEM_URL,
                "DATABASE_URL": APP_URL,
                "MIGRATION_DATABASE_URL": "postgresql+asyncpg://nexus_migrator:x@h/d",
            },
            "MIGRATION_CREDENTIAL_IN_RUNTIME",
        ),
    ],
)
def test_the_runtime_refuses_a_bad_environment_with_a_stable_code(monkeypatch, capsys, env, code):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    seen = _events()

    assert entry.main(["run"]) == 2

    out = capsys.readouterr()
    assert out.err.startswith(f"{code}:")
    assert SECRET not in out.out + out.err
    assert {"event": "runtime_refused", "code": code} in seen


def test_an_unreachable_database_refuses_without_echoing_the_driver_message(monkeypatch, capsys):
    # Both URLs are well formed and different, so the refusal comes from the role check.
    # The driver error would carry the DSN; the refusal names the exception class only.
    monkeypatch.setenv("SYSTEM_DATABASE_URL", SYSTEM_URL)
    monkeypatch.setenv("DATABASE_URL", APP_URL)

    assert entry.main(["run"]) == 2

    out = capsys.readouterr()
    assert out.err.startswith("ROLE_VALIDATION_UNAVAILABLE:")
    assert SECRET not in out.out + out.err
    assert db._engine is None, "the engine must be disposed after a failed role check"


def test_an_unknown_command_is_refused(capsys):
    assert entry.main(["psql"]) == 64


def test_healthcheck_follows_the_heartbeat_file(monkeypatch, tmp_path):
    beat = tmp_path / "alive"
    monkeypatch.setenv("SYSTEM_RUNTIME_HEARTBEAT_FILE", str(beat))
    assert entry.main(["healthcheck"]) == 1, "no heartbeat yet"
    beat.write_text(str(__import__("time").time()))
    assert entry.main(["healthcheck"]) == 0
    beat.write_text(str(__import__("time").time() - entry.HEARTBEAT_MAX_AGE_SECONDS - 5))
    assert entry.main(["healthcheck"]) == 1, "a stalled runtime fails its probe"
    beat.write_text("not a number")
    assert entry.main(["healthcheck"]) == 1


# -- API and worker refuse the system credential ----------------------------------------


def test_a_public_or_ordinary_process_refuses_the_system_credential(monkeypatch):
    enforce_no_system_credential()  # unset: fine
    monkeypatch.setenv("SYSTEM_DATABASE_URL", SYSTEM_URL)
    with pytest.raises(ConfigurationError) as caught:
        enforce_no_system_credential()
    assert caught.value.code == "SYSTEM_CREDENTIAL_IN_RUNTIME"
    assert SECRET not in str(caught.value)


async def test_the_temporal_worker_refuses_the_system_credential(monkeypatch):
    from nexus.temporal.worker import run_worker

    monkeypatch.setenv("SYSTEM_DATABASE_URL", SYSTEM_URL)
    with pytest.raises(ConfigurationError) as caught:
        await run_worker()
    assert caught.value.code == "SYSTEM_CREDENTIAL_IN_RUNTIME"


def test_the_api_lifespan_enforces_the_check_before_touching_the_database():
    source = (SRC / "main.py").read_text(encoding="utf-8")
    lifespan = source[source.index("async def lifespan") :]
    assert "enforce_no_system_credential()" in lifespan
    assert lifespan.index("enforce_no_system_credential()") < lifespan.index(
        "async_session_factory"
    )


# -- no process but the system runtime can reach the privileged engine ------------------


async def test_discovery_session_is_refused_in_a_process_that_did_not_bootstrap():
    with pytest.raises(db.SystemRuntimeError) as caught:
        async with db.discovery_session("watchdog_patrol"):
            pass
    assert caught.value.code == "SYSTEM_RUNTIME_NOT_BOOTSTRAPPED"


async def test_discovery_session_refuses_an_operation_outside_the_catalogue(monkeypatch):
    monkeypatch.setenv("SYSTEM_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    db.bootstrap()
    with pytest.raises(db.SystemRuntimeError) as caught:
        async with db.discovery_session("read_everything"):
            pass
    assert caught.value.code == "OPERATION_NOT_ALLOWED"
    await db.dispose()


def test_bootstrap_has_no_fallback_to_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", APP_URL)
    with pytest.raises(db.SystemRuntimeError) as caught:
        db.bootstrap()
    assert caught.value.code == "SYSTEM_CREDENTIAL_MISSING"
    assert SECRET not in str(caught.value)


def test_only_the_system_runtime_reads_the_system_credential_or_creates_its_engine():
    """Static guard: the credential variable and ``bootstrap`` appear in a short list of files."""
    reads, bootstraps = set(), set()
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        if "SYSTEM_DATABASE_URL" in text or "system_database_url" in text:
            reads.add(rel)
        if re.search(r"\bdb\.bootstrap\(|\bbootstrap\(\)", text) and rel.startswith(
            ("system_runtime/__main__", "api/", "runtime/", "services/", "temporal/", "main")
        ):
            bootstraps.add(rel)
    assert bootstraps == {"system_runtime/__main__.py"}
    assert reads <= {
        "config_validator.py",  # names the variable in the refusal for API and workers
        "system_runtime/__main__.py",
        "system_runtime/db.py",
    }, reads


def test_no_module_defines_or_calls_a_public_system_session():
    """Static caller guard: the old public cross-tenant entry points are gone for good.

    ``system_session`` and its factories used to be importable by any module, falling back
    to the application engine when no system URL was set. A new caller of any of these names,
    or of ``nexus.system_runtime.db`` from outside the package, fails here. The allowed set is
    empty on purpose: privileged work belongs in a catalogued operation (system_runtime/ops.py).
    """
    names = {
        "system_session",
        "system_session_factory",
        "get_system_session_factory",
        "_system_engine",
    }
    allowed: set[str] = set()
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            used = (
                (isinstance(node, ast.Name) and node.id in names)
                or (isinstance(node, ast.Attribute) and node.attr in names)
                or (isinstance(node, ast.alias) and node.name in names)
            )
            if used and rel not in allowed:
                offenders.append(f"{rel}:{node.lineno}")
            if rel.startswith("system_runtime/"):
                continue
            imported = (
                isinstance(node, ast.ImportFrom)
                and (
                    node.module == "nexus.system_runtime.db"
                    or (
                        node.module == "nexus.system_runtime"
                        and any(a.name == "db" for a in node.names)
                    )
                )
            ) or (
                isinstance(node, ast.Import)
                and any(a.name == "nexus.system_runtime.db" for a in node.names)
            )
            if imported:
                offenders.append(f"{rel}:{node.lineno} imports nexus.system_runtime.db")
    assert not offenders, offenders


# -- the operation catalogue -------------------------------------------------------------


def test_the_catalogue_is_the_expected_allow_list():
    assert set(OPERATIONS) == {
        "budget_reservation_reap",
        "task_recovery",
        "goal_discovery",
        "chat_turn_recovery",
        "task_attempt_recovery",
        "watchdog_patrol",
        "org_snapshot_refresh",
    }


@pytest.mark.parametrize("op", OPERATIONS.values(), ids=lambda op: op.name)
def test_every_operation_is_named_bounded_and_takes_no_caller_input(op):
    import inspect

    assert re.fullmatch(r"[a-z_]+", op.name)
    assert 0 < op.batch_size <= 100
    assert 0 < op.timeout_seconds <= 300
    assert op.interval_seconds >= 10
    # (discovery, now): nothing a caller could use to steer a table, a query or a prompt.
    assert list(inspect.signature(op.run).parameters) == ["discovery", "now"]


def test_operations_contain_no_dynamic_sql_and_no_content_logging():
    source = (SRC / "system_runtime" / "ops.py").read_text(encoding="utf-8")
    for needle in (
        "text(",
        "exec_driver_sql",
        "execute(f",
        'f"SELECT',
        "f'SELECT",
        "literal_column",
    ):
        assert needle not in source, needle
    # Log lines in the catalogue name an exception class or a count, never a row.
    for line in source.splitlines():
        if "logger." in line:
            assert "type(exc).__name__" in line or "%d" in line, line


def test_no_agent_or_model_entry_point_can_start_an_operation():
    """Nothing outside ``system_runtime`` imports the catalogue or the runner."""
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("system_runtime/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                names = [f"{node.module}.{a.name}" for a in node.names] + [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                continue
            for name in names:
                assert not name.startswith(
                    ("nexus.system_runtime.ops", "nexus.system_runtime.runner")
                ), f"{rel} imports {name}"


# -- failure behaviour ------------------------------------------------------------------


def _runtime(ops, *, acquire=None, release=None, clock=None):
    async def always(*_a):
        return True

    async def noop(*_a):
        return None

    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    return SystemRuntime(
        lambda name: None,
        operations={op.name: op for op in ops},
        acquire=acquire or always,
        release=release or noop,
        instance_id="test",
        **kwargs,
    )


def _op(name, run, timeout=5.0, interval=60.0):
    return Operation(name, interval, 10, timeout, run)


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    async def none():
        return None

    monkeypatch.setattr(status, "get_redis", none)


async def test_a_failing_operation_is_isolated_and_audited_with_a_code_only(caplog):
    ran = []

    async def boom(discovery, now):
        raise RuntimeError(f"connection to {SYSTEM_URL} failed")

    async def fine(discovery, now):
        ran.append("fine")
        return OpResult(seen=1, processed=1, batches=1)

    seen = _events()
    runtime = _runtime([_op("task_recovery", boom), _op("goal_discovery", fine)])
    await runtime.tick()

    assert ran == ["fine"], "one failing operation must not stop the next"
    failed = [e for e in seen if e["event"] == "op_failed"]
    assert failed == [
        {
            "event": "op_failed",
            "operation": "task_recovery",
            "code": "OP_FAILED",
            "duration_ms": failed[0]["duration_ms"],
        }
    ]
    assert "task_recovery" not in runtime.last_success and "goal_discovery" in runtime.last_success
    assert SECRET not in caplog.text + repr(seen)


async def test_a_hung_operation_times_out_and_releases_its_lease():
    released = []

    async def hang(discovery, now):
        await asyncio.sleep(60)

    async def release(lease, instance):
        released.append(lease)

    seen = _events()
    runtime = _runtime([_op("watchdog_patrol", hang, timeout=0.05)], release=release)
    await runtime.tick()

    assert released == ["system_runtime:watchdog_patrol"]
    assert any(e["event"] == "op_failed" and e["code"] == "OP_TIMEOUT" for e in seen)


async def test_a_second_leader_skips_the_operation():
    calls = []

    async def work(discovery, now):
        calls.append(1)
        return OpResult()

    async def held(*_a):
        return False

    seen = _events()
    runtime = _runtime([_op("goal_discovery", work)], acquire=held)
    await runtime.tick()

    assert calls == []
    assert any(e["event"] == "op_skipped_not_leader" for e in seen)


async def test_cancellation_propagates_and_the_lease_is_released():
    released = []
    started = asyncio.Event()

    async def hang(discovery, now):
        started.set()
        await asyncio.sleep(60)

    async def release(lease, instance):
        released.append(lease)

    runtime = _runtime([_op("goal_discovery", hang)], release=release)
    task = asyncio.create_task(runtime.tick())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released == ["system_runtime:goal_discovery"]


async def test_a_failing_audit_subscriber_does_not_fail_the_operation():
    def broken(entry_):
        raise RuntimeError("siem down")

    async def work(discovery, now):
        return OpResult(seen=1, processed=1)

    audit.subscribe(broken)
    runtime = _runtime([_op("goal_discovery", work)])
    await runtime.tick()
    assert "goal_discovery" in runtime.last_success


async def test_an_operation_runs_again_only_after_its_interval():
    calls = []
    now = [100.0]

    async def work(discovery, now_):
        calls.append(1)
        return OpResult()

    runtime = _runtime([_op("goal_discovery", work, interval=60)], clock=lambda: now[0])
    await runtime.tick()
    now[0] += 30
    await runtime.tick()
    assert len(calls) == 1
    now[0] += 31
    await runtime.tick()
    assert len(calls) == 2


async def test_a_company_that_fails_midway_does_not_stop_the_rest(caplog):
    ids = [uuid.uuid4() for _ in range(25)]
    bad = {ids[3], ids[12]}
    done = []

    async def work(company_id):
        if company_id in bad:
            raise RuntimeError(f"row for {company_id} had secret text {SECRET}")
        done.append(company_id)

    result = OpResult()
    await _per_company(result, ids, work)

    assert (result.seen, result.processed, result.failed) == (25, 23, 2)
    assert result.batches == 3, "25 companies run in chunks of 10"
    assert set(done) == set(ids) - bad
    assert SECRET not in caplog.text, "only the exception class is logged"


async def test_cancellation_inside_a_company_pass_is_not_swallowed():
    async def work(company_id):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _per_company(OpResult(), [uuid.uuid4()], work)


# -- audit and status -------------------------------------------------------------------


def test_audit_drops_unknown_fields_and_content_like_values():
    entry_ = audit.emit(
        "op_completed",
        operation="goal_discovery",
        companies_seen=3,
        prompt="summarise the board memo",
        code="has spaces and a password: hunter2",
        database_url=SYSTEM_URL,
    )
    assert entry_ == {"event": "op_completed", "operation": "goal_discovery", "companies_seen": 3}


def test_audit_refuses_an_unknown_event():
    with pytest.raises(ValueError):
        audit.emit("raw_sql")


class _FakeRedis:
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def set(self, key, value, ex=None):
        self.kv[key] = value

    async def get(self, key):
        return self.kv.get(key)

    async def sadd(self, key, *members):
        self.sets.setdefault(key, set()).update(members)

    async def expire(self, key, ttl):
        return True

    async def spop(self, key, count=1):
        bag = self.sets.setdefault(key, set())
        out = [bag.pop() for _ in range(min(count, len(bag)))]
        return out


@pytest.fixture
def fake_redis(monkeypatch):
    from nexus.runtime import work_hints

    fake = _FakeRedis()

    async def get():
        return fake

    monkeypatch.setattr(status, "get_redis", get)
    monkeypatch.setattr(work_hints, "get_redis", get)
    return fake


async def test_status_reads_unavailable_without_redis_and_without_a_record():
    assert await status.read() == {"available": False, "reason": "STATUS_STORE_UNAVAILABLE"}


async def test_status_reads_unavailable_when_the_runtime_is_not_reporting(fake_redis):
    assert await status.read() == {"available": False, "reason": "SYSTEM_RUNTIME_NOT_REPORTING"}


async def test_status_roundtrip_and_failed_role_validation(fake_redis):
    await status.publish(ops_enabled=["b", "a"], role_validation="ok", last_success={"a": 1.0})
    record = await status.read()
    assert record["available"] is True
    assert record["ops_enabled"] == ["a", "b"]
    assert "url" not in repr(record).lower()

    await status.publish(ops_enabled=[], role_validation="failed", last_success={})
    record = await status.read()
    assert record["available"] is False and record["reason"] == "ROLE_VALIDATION_FAILED"


async def test_the_status_command_prints_without_any_database(monkeypatch, fake_redis, capsys):
    assert await entry.status() == 0
    assert "SYSTEM_RUNTIME_NOT_REPORTING" in capsys.readouterr().out
    assert db._engine is None


async def test_readiness_reports_the_runtime_as_unavailable_but_stays_ready(monkeypatch):
    from nexus.api.routes import health

    async def connected():
        return {"status": "connected"}

    async def disabled():
        return {"status": "disabled"}

    monkeypatch.setattr(health, "_check_db_health", connected)
    monkeypatch.setattr(health, "_check_redis_health", connected)
    monkeypatch.setattr(health, "_check_temporal_health", disabled)

    response = await health.readiness()

    import json

    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["components"]["system_runtime"]["available"] is False
    assert db._engine is None, "the API reading status must not create a system connection"


# -- work hints ------------------------------------------------------------------------


async def test_work_hints_carry_company_ids_and_each_goes_to_one_claimer(fake_redis):
    from nexus.runtime import work_hints

    ids = [uuid.uuid4() for _ in range(5)]
    assert await work_hints.publish("goals", ids) == 5
    stored = [m for bag in fake_redis.sets.values() for m in bag]
    assert sorted(stored) == sorted(str(i) for i in ids), "a hint is a company id and nothing else"
    first = await work_hints.claim("goals", limit=3)
    second = await work_hints.claim("goals", limit=10)

    assert len(first) == 3 and len(second) == 2
    assert set(first) | set(second) == set(ids) and not set(first) & set(second)


async def test_work_hints_refuse_an_unknown_kind_and_degrade_without_redis(fake_redis, monkeypatch):
    from nexus.runtime import work_hints

    with pytest.raises(ValueError):
        await work_hints.publish("../secrets", [uuid.uuid4()])
    with pytest.raises(ValueError):
        await work_hints.claim("anything")

    async def none():
        return None

    monkeypatch.setattr(work_hints, "get_redis", none)
    assert await work_hints.publish("goals", [uuid.uuid4()]) == 0
    assert await work_hints.claim("goals") == []


async def test_a_redis_failure_is_not_fatal_to_hints(monkeypatch):
    from nexus.runtime import work_hints

    class Broken:
        async def sadd(self, *a):
            raise ConnectionError(SYSTEM_URL)

        async def spop(self, *a):
            raise ConnectionError(SYSTEM_URL)

    async def get():
        return Broken()

    monkeypatch.setattr(work_hints, "get_redis", get)
    assert await work_hints.publish("goals", [uuid.uuid4()]) == 0
    assert await work_hints.claim("goals") == []
