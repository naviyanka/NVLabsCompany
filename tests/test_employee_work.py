"""Employee work execution and evidence (nexus.runtime.task_attempts).

Every test runs the production path against a file SQLite database with
foreign keys on, real git repositories and worktrees under ``tmp_path``, and
the real verifier (it runs pytest in the worktree). Only the model call is
faked: the fake writes files into the worktree the chat path resolved for the
session, and returns a reply, exactly as a CLI employee would. Waiting is done
on events and on the attempt worker's own drain, never on sleeps.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table
from nexus.adapters import cli_adapter
from nexus.api.routes import chat as chat_routes
from nexus.api.routes import task_attempts as attempt_routes
from nexus.api.routes import tasks as task_routes
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.agent_worktree import AgentWorktree
from nexus.models.company import Company
from nexus.models.notification import Notification
from nexus.models.repository import Repository
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt, WorkEffect
from nexus.runtime import chat_turns
from nexus.runtime import task_attempts as ta
from nexus.services.worktree_service import WorktreeError, session_workspace, worktree_path

pytestmark = pytest.mark.employee_work

LATER = timedelta(minutes=5)

CALC = "def add(a, b):\n    return a + b\n"
BUGGY = "def add(a, b):\n    return a - b\n"
CALC_TESTS = (
    "import sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
    "from calculator import add\n\n\n"
    "def test_add():\n"
    "    assert add(1, 2) == 3\n"
    "    assert add(-1, 1) == 0\n"
    "    assert add(2.5, 2.5) == 5.0\n"
)
SPEC = {
    "mode": "write",
    "objective": "Create src/calculator.py with add(a, b) and tests for it.",
    "deliverables": ["src/calculator.py", "tests/test_calculator.py"],
    "verification": [{"command": "pytest", "paths": ["tests/test_calculator.py"]}],
    "acceptance_criteria": [
        {"kind": "file_exists", "path": "src/calculator.py"},
        {"kind": "pattern_count", "path": "tests/test_calculator.py", "pattern": "assert ",
         "min_count": 3},
        {"kind": "command_passes", "command": "pytest"},
    ],
}


def report(state="completed", **extra):
    body = {
        "state": state,
        "summary": "Added add() with tests",
        "progress_percent": 100,
        "completed_steps": ["write add", "write tests", "run tests"],
        "artifacts": ["src/calculator.py", "tests/test_calculator.py"],
        "tests_run": ["pytest tests/test_calculator.py: 1 passed"],
        "confidence": 0.9,
        **extra,
    }
    return "All done.\n```json\n" + json.dumps(body) + "\n```"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("demo\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


class Employee:
    """The fake model call. ``behave(root, prompt)`` returns (reply, exit code)."""

    def __init__(self, factory) -> None:
        self.factory = factory
        self.calls: list[dict] = []
        self.started = asyncio.Event()
        self.gate: asyncio.Event | None = None
        self.during = None
        self.behave = self.calculator

    async def calculator(self, root, prompt):
        _write(root, {"src/calculator.py": CALC, "tests/test_calculator.py": CALC_TESTS})
        return report(), 0

    async def __call__(self, agent, system_prompt, prompt, history, *, session_id=None,
                       context=None, execution=None, **kw):
        async with self.factory() as s:
            root = await session_workspace(s, agent.company_id, agent.id, session_id)
        self.calls.append({"agent": agent.id, "root": root, "prompt": prompt,
                           "mode": getattr(context, "work_mode", None)})
        self.started.set()
        if self.during is not None:
            await self.during(root)
        if self.gate is not None:
            await self.gate.wait()
        text, code = await self.behave(root, prompt)
        if execution is not None:
            execution.update(adapter="cli", backend="claude", cli={
                "type": "cli_execution", "adapter": "cli", "backend": "claude",
                "exit_code": code, "duration_ms": 5, "version": "fake",
            })
        return text, "fake-model", 11


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'work.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    monkeypatch.setattr(database, "_system_session_factory", factory)
    # tenant_session() picks its dialect from the URL, not from this factory.
    monkeypatch.setattr(settings, "database_url", str(engine.url))
    monkeypatch.setattr(settings, "repository_roots", str(tmp_path / "repos" / "{company_id}"))
    monkeypatch.setattr(settings, "worktree_root", str(tmp_path / "wt" / "{company_id}"))
    monkeypatch.setattr(
        settings, "task_attempt_evidence_root", str(tmp_path / "evidence" / "{company_id}")
    )

    async def fake_prompt(db, agent, company_id, prompt):
        return "system"

    employee = Employee(factory)
    monkeypatch.setattr(chat_routes, "_build_chat_prompt", fake_prompt)
    monkeypatch.setattr(chat_routes, "_call_llm", employee)
    factory.employee = factory.emp = employee
    factory.engine = engine
    yield factory
    await ta.drain()
    await chat_turns.drain()
    await engine.dispose()


@pytest.fixture
async def w(db, tmp_path):
    """Two companies; the first has a repo, a Claude and an Agy employee and a work task."""
    ids = {}
    async with db() as s:
        for key in ("acme", "other"):
            company = Company(name=key)
            s.add(company)
            await s.flush()
            clone = _make_repo(tmp_path / "repos" / str(company.id) / "demo")
            repo = Repository(company_id=company.id, name="demo", url="u", local_path=str(clone))
            claude = Agent(company_id=company.id, name="claude", role="engineer",
                           adapter_type="cli", adapter_config={"backend": "claude"}, model="")
            agy = Agent(company_id=company.id, name="agy", role="reviewer",
                        adapter_type="cli", adapter_config={"backend": "agy"}, model="")
            api = Agent(company_id=company.id, name="api", role="engineer",
                        adapter_type="openai", model="gpt-x")
            s.add_all([repo, claude, agy, api])
            await s.flush()
            ids[key] = company.id
            ids[f"{key}_clone"], ids[f"{key}_repo"] = clone, repo.id
            ids[f"{key}_claude"], ids[f"{key}_agy"], ids[f"{key}_api"] = claude.id, agy.id, api.id
        await s.commit()
    ids["task"] = await _task(db, ids["acme"], ids["acme_claude"], ids["acme_repo"])
    return ids


def _me(company_id, role="admin"):
    return Principal(kind="user", company_id=company_id, role=role, user_id=uuid.uuid4(),
                     email="lead@example.test")


async def _task(db, company_id, agent_id, repo_id, spec=None, title="Calculator"):
    async with db() as s:
        task = Task(company_id=company_id, title=title, assigned_agent_id=agent_id,
                    work_spec={**(spec or SPEC), "repository_id": str(repo_id)})
        s.add(task)
        await s.commit()
    return task.id


async def _start(db, company_id, task_id, **kw):
    async with db() as s:
        return await ta.start_attempt(s, company_id, task_id, _me(company_id), **kw)


async def _run(db, company_id, task_id, **kw):
    attempt, _ = await _start(db, company_id, task_id, **kw)
    await ta.drain()
    return await _attempt(db, company_id, attempt.id)


async def _attempt(db, company_id, attempt_id):
    async with db() as s:
        return await ta._get(s, company_id, attempt_id)


async def _rows(db, model, *where):
    async with db() as s:
        return list((await s.execute(select(model).where(*where))).scalars())


async def _worktree(db, attempt):
    row = (await _rows(db, AgentWorktree, AgentWorktree.id == attempt.worktree_id))[0]
    return row, worktree_path(row.company_id, row.relative_path)


def _commits_with(root: Path, text: str) -> list[str]:
    return [c for c in _git(root, "log", "--all", "--format=%H", f"--grep={text}",
                            "--fixed-strings").splitlines() if c]


# ---------------------------------------------------------------------------
# Completion requires evidence
# ---------------------------------------------------------------------------


class TestCompletion:
    async def test_verified_work_completes_the_task_with_evidence(self, db, w, tmp_path):
        main_head = _git(w["acme_clone"], "rev-parse", "HEAD")

        async def with_caches(root, prompt):
            # Running Python leaves caches behind; they are never work. Nor is
            # a CLI instruction file a killed earlier run could not remove.
            _write(root, {"src/__pycache__/calculator.cpython-314.pyc": "x",
                          ".pytest_cache/v/cache/nodeids": "[]",
                          ".claude/CLAUDE.md": "# Stale instructions"})
            return await db.emp.calculator(root, prompt)

        db.emp.behave = with_caches
        attempt = await _run(db, w["acme"], w["task"])

        assert (attempt.status, attempt.completion_reason) == ("completed", "goal")
        task = (await _rows(db, Task, Task.id == w["task"]))[0]
        assert (task.status, task.completion_reason) == ("completed", "goal")
        assert task.result == "Added add() with tests"

        # Ran in an isolated worktree; the clone's checkout never changed.
        call = db.emp.calls[0]
        assert call["mode"] == "write" and call["root"] != w["acme_clone"]
        row, root = await _worktree(db, attempt)
        assert call["root"] == root and row.task_id == w["task"]
        assert _git(w["acme_clone"], "rev-parse", "HEAD") == main_head
        assert not (w["acme_clone"] / "src").exists()
        assert _git(w["acme_clone"], "status", "--porcelain") == ""
        assert row.status == "review" and row.session_id is None

        # Manifest: relative paths and real hashes, tied to the commit.
        by_path = {a["path"]: a for a in attempt.artifacts}
        assert set(by_path) == {"src/calculator.py", "tests/test_calculator.py"}
        import hashlib

        for rel, entry in by_path.items():
            data = (root / rel).read_bytes()
            assert entry["sha256"] == hashlib.sha256(data).hexdigest()
            assert entry["size"] == len(data) and entry["validation"] == "verified"
            assert entry["commit"] and not Path(rel).is_absolute()
            assert entry["execution_id"] == attempt.execution_id
        assert by_path["tests/test_calculator.py"]["type"] == "test"

        # Verification: the server ran pytest itself.
        record = attempt.verification
        assert record["passed"] and record["evaluator"].startswith("not run")
        (command,) = record["commands"]
        assert command["exit_code"] == 0 and command["tests"] == {"passed": 1}
        assert command["argv"][:3] == ["python", "-m", "pytest"]
        assert all(c["passed"] for c in record["criteria"]) and len(record["criteria"]) == 3

        # One commit on the worktree branch, none on main; the progress file is not in it.
        assert len(_commits_with(root, f"Nexus-Effect: commit:{attempt.id}")) == 1
        assert _git(root, "rev-parse", "HEAD") == by_path["src/calculator.py"]["commit"]
        committed = _git(root, "show", "--name-only", "--format=", "HEAD").split()
        assert sorted(committed) == ["src/calculator.py", "tests/test_calculator.py"]

        # Evidence: bounded, redacted logs; nothing absolute is stored.
        evidence = tmp_path / "evidence" / str(w["acme"]) / str(attempt.id)
        log = (evidence / command["stdout"]["ref"]).read_text()
        assert "1 passed" in log
        stored = json.dumps([attempt.artifacts, attempt.verification, attempt.report])
        assert str(tmp_path) not in stored and tmp_path.as_posix() not in stored
        assert attempt.report["state"] == "completed" and attempt.report["source"] == "final"

    async def test_prose_without_a_report_never_completes(self, db, w):
        async def prose(root, prompt):
            _write(root, {"src/calculator.py": CALC, "tests/test_calculator.py": CALC_TESTS})
            return "I have finished the task and everything works perfectly.", 0

        db.emp.behave = prose
        attempt = await _run(db, w["acme"], w["task"])
        assert (attempt.status, attempt.completion_reason) == ("failed", "verification_failed")
        assert attempt.error_code == "REPORT_MISSING"
        task = (await _rows(db, Task, Task.id == w["task"]))[0]
        assert task.status == "failed" and task.completion_reason == "verification_failed"
        assert not _commits_with((await _worktree(db, attempt))[1], "Nexus-Effect")

    async def test_completed_report_without_evidence_is_invalid(self, db, w):
        async def empty(root, prompt):
            _write(root, {"src/calculator.py": CALC, "tests/test_calculator.py": CALC_TESTS})
            return report(artifacts=[], tests_run=[]), 0

        db.emp.behave = empty
        attempt = await _run(db, w["acme"], w["task"])
        assert (attempt.status, attempt.error_code) == ("failed", "REPORT_INVALID")

    async def test_failing_tests_block_completion(self, db, w):
        async def buggy(root, prompt):
            _write(root, {"src/calculator.py": BUGGY, "tests/test_calculator.py": CALC_TESTS})
            return report(), 0

        db.emp.behave = buggy
        attempt = await _run(db, w["acme"], w["task"])
        assert (attempt.status, attempt.completion_reason) == ("failed", "verification_failed")
        assert attempt.error_code == "VERIFICATION_FAILED"
        (command,) = attempt.verification["commands"]
        assert command["exit_code"] == 1 and command["tests"] == {"failed": 1}
        # The employee's claim is kept, but the task is not completed.
        assert attempt.report["state"] == "completed"
        task = (await _rows(db, Task, Task.id == w["task"]))[0]
        assert task.status == "failed"
        assert {a["validation"] for a in attempt.artifacts} == {"unverified"}

    async def test_missing_deliverable_fails(self, db, w):
        async def half(root, prompt):
            _write(root, {"tests/test_calculator.py": CALC_TESTS})
            return report(), 0

        db.emp.behave = half
        attempt = await _run(db, w["acme"], w["task"])
        failed = [c["check"] for c in attempt.verification["checks"] if not c["passed"]]
        assert "deliverable:src/calculator.py" in failed and attempt.status == "failed"

    async def test_nonzero_cli_exit_fails(self, db, w):
        async def crashed(root, prompt):
            _write(root, {"src/calculator.py": CALC, "tests/test_calculator.py": CALC_TESTS})
            return report(), 2

        db.emp.behave = crashed
        attempt = await _run(db, w["acme"], w["task"])
        assert (attempt.status, attempt.error_code) == ("failed", "CLI_EXIT_NONZERO")
        assert attempt.verification["commands"] == []  # nothing else was run

    async def test_blocked_report_blocks_and_notifies_once(self, db, w):
        async def stuck(root, prompt):
            return report("blocked", blockers=["No write access to src/"], artifacts=[]), 0

        db.emp.behave = stuck
        attempt = await _run(db, w["acme"], w["task"])
        assert (attempt.status, attempt.completion_reason) == ("blocked", "needs_help")
        assert "No write access to src/" in attempt.error
        task = (await _rows(db, Task, Task.id == w["task"]))[0]
        assert (task.status, task.completion_reason) == ("blocked", "needs_help")
        notes = await _rows(db, Notification, Notification.company_id == w["acme"])
        assert len(notes) == 1 and notes[0].notification_metadata["attempt_id"] == str(attempt.id)

    async def test_status_route_cannot_complete_a_work_task(self, db, w):
        async with db() as s:
            with pytest.raises(HTTPException) as exc:
                await task_routes.update_task_status(
                    w["task"], task_routes.TaskStatusUpdate(status="completed"), s, w["acme"]
                )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "WORK_TASK_REQUIRES_VERIFIED_ATTEMPT"


# ---------------------------------------------------------------------------
# Start, claim, idempotency
# ---------------------------------------------------------------------------


class TestStart:
    async def test_same_key_returns_the_same_attempt(self, db, w):
        first, created = await _start(db, w["acme"], w["task"], idempotency_key="k1")
        again, created_again = await _start(db, w["acme"], w["task"], idempotency_key="k1")
        assert created and not created_again and again.id == first.id
        await ta.drain()
        assert len(db.emp.calls) == 1

    async def test_start_while_active_attaches(self, db, w):
        db.emp.gate = asyncio.Event()
        first, _ = await _start(db, w["acme"], w["task"])
        await asyncio.wait_for(db.emp.started.wait(), 30)
        second, created = await _start(db, w["acme"], w["task"])
        assert second.id == first.id and not created
        db.emp.gate.set()
        await ta.drain()
        assert len(await _rows(db, TaskAttempt)) == 1 and len(db.emp.calls) == 1

    async def test_concurrent_starts_leave_one_active_attempt(self, db, w):
        results = await asyncio.gather(
            *(_start(db, w["acme"], w["task"]) for _ in range(5)), return_exceptions=True
        )
        attempts = [r[0] for r in results if not isinstance(r, BaseException)]
        errors = [r for r in results if isinstance(r, BaseException)]
        assert all(isinstance(e, HTTPException) and e.status_code == 409 for e in errors)
        assert len({a.id for a in attempts}) == 1
        await ta.drain()
        assert len(await _rows(db, TaskAttempt)) == 1 and len(db.emp.calls) == 1

    async def test_racing_claims_have_one_winner(self, db, w):
        async with db() as s:
            s.add(TaskAttempt(company_id=w["acme"], task_id=w["task"], agent_id=w["acme_claude"],
                              attempt_number=1, idempotency_key="x"))
            await s.commit()
        (row,) = await _rows(db, TaskAttempt)
        won = await asyncio.gather(*(ta.claim(row.id, w["acme"], f"w{i}") for i in range(5)))
        assert len([x for x in won if x is not None]) == 1
        task = (await _rows(db, Task, Task.id == w["task"]))[0]
        assert task.status == "in_progress"

    @pytest.mark.parametrize(
        ("change", "status_code", "code"),
        [
            ({"agent": "acme_agy"}, 409, "EMPLOYEE_NOT_ASSIGNED"),
            ({"assign": "acme_api"}, 422, "EMPLOYEE_NOT_CLI"),
            ({"assign": None}, 409, "TASK_NOT_ASSIGNED"),
            ({"spec": None}, 422, "TASK_NOT_WORK"),
            ({"spec": {"mode": "write"}}, 422, "INVALID_WORK_SPEC"),
            ({"status": "completed"}, 409, "TASK_ALREADY_COMPLETED"),
        ],
    )
    async def test_refusals(self, db, w, change, status_code, code):
        values = {}
        if "assign" in change:
            values["assigned_agent_id"] = w[change["assign"]] if change["assign"] else None
        if "spec" in change:
            values["work_spec"] = change["spec"]
        if "status" in change:
            values["status"] = change["status"]
        if values:
            async with db() as s:
                await s.execute(update(Task).where(Task.id == w["task"]).values(**values))
                await s.commit()
        agent = w[change["agent"]] if "agent" in change else None
        with pytest.raises(HTTPException) as exc:
            await _start(db, w["acme"], w["task"], agent_id=agent)
        assert (exc.value.status_code, exc.value.detail["code"]) == (status_code, code)
        assert await _rows(db, TaskAttempt) == []

    async def test_other_tenant_sees_nothing(self, db, w):
        attempt = await _run(db, w["acme"], w["task"])
        with pytest.raises(HTTPException) as exc:
            await _start(db, w["other"], w["task"])
        assert exc.value.status_code == 404
        async with db() as s:
            for coro in (
                attempt_routes.get_attempt(w["task"], attempt.id, s, w["other"], _me(w["other"])),
                attempt_routes.list_attempts(w["task"], s, w["other"], _me(w["other"])),
                attempt_routes.cancel_attempt(
                    w["task"], attempt.id, s, w["other"], _me(w["other"])
                ),
            ):
                with pytest.raises(HTTPException) as exc:
                    await coro
                assert exc.value.status_code == 404

    async def test_reassign_while_working_is_refused(self, db, w):
        db.emp.gate = asyncio.Event()
        await _start(db, w["acme"], w["task"])
        await asyncio.wait_for(db.emp.started.wait(), 30)
        async with db() as s:
            with pytest.raises(HTTPException) as exc:
                await task_routes.reassign_task(
                    w["task"], task_routes.TaskAssign(agent_id=w["acme_agy"]), s, w["acme"]
                )
        assert exc.value.detail["code"] == "ATTEMPT_ACTIVE"
        db.emp.gate.set()

    def test_work_spec_refuses_unsafe_paths_and_commands(self):
        base = {**SPEC, "repository_id": str(uuid.uuid4())}
        for bad in ("../x.py", "/etc/passwd", "C:\\x.py", "\\\\srv\\share\\x", ".nexus/r.json",
                    "-rf", "a/../../b", ".claude/settings.json", ""):
            with pytest.raises(ValidationError):
                ta.WorkSpec.model_validate({**base, "deliverables": [bad]})
        for bad_step in ({"command": "bash", "paths": []}, {"command": "pytest", "argv": ["x"]}):
            with pytest.raises(ValidationError):
                ta.WorkSpec.model_validate({**base, "verification": [bad_step]})
        with pytest.raises(ValidationError):
            ta.WorkSpec.model_validate({**base, "base_ref": "--upload-pack=x"})
        with pytest.raises(ValidationError):
            ta.WorkSpec.model_validate({**base, "mode": "read_only"})  # read-only with deliverables
        assert ta.WorkSpec.model_validate({**base, "deliverables": ["src\\a.py"]}).deliverables == [
            "src/a.py"
        ]


# ---------------------------------------------------------------------------
# Progress reports
# ---------------------------------------------------------------------------


class TestProgress:
    async def test_progress_file_is_stored_while_the_employee_works(self, db, w, monkeypatch):
        stored = asyncio.Event()
        real = ta.store_report

        async def spy(attempt, seq, body, source):
            ok = await real(attempt, seq, body, source)
            if source == "progress" and ok:
                stored.set()
            return ok

        monkeypatch.setattr(ta, "store_report", spy)

        async def during(root):
            _write(root, {".nexus/report.json": json.dumps(
                {"seq": 1, "state": "working", "summary": "writing add",
                 "progress_percent": 40, "current_step": "src/calculator.py"})})
            ta.get_worker().poke(next(iter(ta.get_worker()._running)))
            await asyncio.wait_for(stored.wait(), 30)

        db.emp.during = during
        attempt, _ = await _start(db, w["acme"], w["task"])
        await ta.drain()
        final = await _attempt(db, w["acme"], attempt.id)
        assert final.status == "completed", (final.error_code, final.error, final.verification)
        assert final.report_seq == 2
        assert final.report["source"] == "final"

    async def test_reports_only_move_forward(self, db, w):
        attempt, _ = await _start(db, w["acme"], w["task"])
        await ta.drain()
        async with db() as s:
            await s.execute(update(TaskAttempt).where(TaskAttempt.id == attempt.id)
                            .values(status="running", report_seq=0))
            await s.commit()
        body = {"state": "working", "summary": "s"}
        assert await ta.store_report(attempt, 5, body, "progress")
        assert not await ta.store_report(attempt, 3, {**body, "summary": "old"}, "progress")
        assert not await ta.store_report(attempt, 5, {**body, "summary": "dup"}, "progress")
        row = await _attempt(db, w["acme"], attempt.id)
        assert row.report_seq == 5 and row.report["summary"] == "s"

    def test_progress_file_bounds(self, tmp_path):
        (tmp_path / ".nexus").mkdir()
        target = tmp_path / ".nexus" / "report.json"
        target.write_text(json.dumps({"seq": 1, "state": "working", "pad": "x" * 70_000}))
        assert ta.read_progress(tmp_path) is None  # too big
        for seq in (0, True, "2", 2_000_000):
            target.write_text(json.dumps({"seq": seq, "state": "working"}))
            assert ta.read_progress(tmp_path) is None
        target.write_text(json.dumps({"seq": 2, "state": "blocked"}))
        assert ta.read_progress(tmp_path) is None  # blocked without a reason
        target.write_text(json.dumps({"seq": 2, "state": "working", "summary": "y" * 5000}))
        seq, body = ta.read_progress(tmp_path)
        assert seq == 2 and len(body["summary"]) == 2000

    def test_final_report_is_the_last_json_object(self):
        text = 'draft {"state": "working"} then {"x": 1} and finally {"state": "completed"} bye'
        assert ta.find_final_report(text) == {"state": "completed"}
        assert ta.find_final_report("no json at all") is None


# ---------------------------------------------------------------------------
# Workspace safety
# ---------------------------------------------------------------------------


def _link(link: Path, target: Path) -> None:
    """A symlink, or on Windows without symlink rights a junction."""
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
        return
    except (OSError, NotImplementedError):
        if not target.is_dir():
            raise
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


class TestWorkspace:
    def test_paths_stay_inside_the_root(self, tmp_path):
        root = tmp_path / "root"
        (root / "src").mkdir(parents=True)
        (root / "src" / "a.py").write_text("x")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("s")
        _link(root / "escape", outside)
        assert ta.inside(root, "src/a.py") == root / "src" / "a.py"
        for rel in ("../outside/secret.txt", "escape/secret.txt", str(outside / "secret.txt"),
                    "src/../../outside"):
            assert ta.inside(root, rel) is None

    async def test_linked_deliverable_fails_verification(self, db, w, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "calculator.py").write_text(CALC)

        async def linked(root, prompt):
            _write(root, {"tests/test_calculator.py": CALC_TESTS})
            _link(root / "src", outside)
            return report(), 0

        db.emp.behave = linked
        attempt = await _run(db, w["acme"], w["task"])
        failed = [c["check"] for c in attempt.verification["checks"] if not c["passed"]]
        assert "deliverable:src/calculator.py" in failed and attempt.status == "failed"

    async def test_no_fallback_when_the_worktree_is_gone(self, db, w):
        """A recovered attempt whose worktree was archived fails; it never runs elsewhere."""
        attempt, _ = await _start_without_worker(db, w)
        claimed = await ta.claim(attempt.id, w["acme"], "dead-worker")
        await ta._prepare(claimed, "dead-worker")
        await chat_turns.drain()
        calls = len(db.emp.calls)
        row = await _attempt(db, w["acme"], attempt.id)
        async with db() as s:
            await s.execute(update(AgentWorktree).where(AgentWorktree.id == row.worktree_id)
                            .values(status="archived"))
            await s.execute(update(TaskAttempt).where(TaskAttempt.id == attempt.id)
                            .values(chat_turn_id=None))
            await s.commit()
        await ta.sweep(ta._now() + LATER)
        ta.get_worker().wake(w["acme"])
        await ta.drain()
        final = await _attempt(db, w["acme"], attempt.id)
        assert (final.status, final.error_code) == ("failed", "WORKTREE_UNAVAILABLE")
        assert len(db.emp.calls) == calls

    async def test_chat_path_refuses_an_unusable_worktree(self, db, w):
        attempt = await _run(db, w["acme"], w["task"])
        row, _ = await _worktree(db, attempt)
        async with db() as s:
            await s.execute(update(AgentWorktree).where(AgentWorktree.id == row.id)
                            .values(status="created", session_id=attempt.session_id))
            await s.commit()
            with pytest.raises(WorktreeError):  # refused, never the main checkout
                await session_workspace(s, w["acme"], w["acme_claude"], attempt.session_id)

    async def test_read_only_review_leaves_the_reviewed_work_alone(self, db, w):
        done = await _run(db, w["acme"], w["task"])
        reviewed, reviewed_root = await _worktree(db, done)
        review = await _task(db, w["acme"], w["acme_agy"], w["acme_repo"], title="Review", spec={
            "mode": "read_only", "review_of_task_id": str(w["task"]),
            "objective": "Review the calculator change.",
            "acceptance_criteria": [{"kind": "report_contains", "text": "add"}],
        })

        async def look(root, prompt):
            assert (root / "src" / "calculator.py").read_text() == CALC
            # Running the tests leaves caches; that is not writing.
            _write(root, {"tests/__pycache__/test_calculator.cpython-314.pyc": "x"})
            return report(summary="Reviewed add(): correct", artifacts=[],
                          tests_run=["read tests/test_calculator.py"]), 0

        db.emp.behave = look
        attempt = await _run(db, w["acme"], review)
        assert attempt.status == "completed", attempt.verification
        call = db.emp.calls[-1]
        assert call["mode"] == "read_only" and call["root"] != reviewed_root
        assert "+def add(a, b):" in call["prompt"]
        assert _git(reviewed_root, "rev-parse", "HEAD") == reviewed.head_commit
        assert attempt.artifacts == []

    async def test_read_only_review_that_writes_fails(self, db, w):
        await _run(db, w["acme"], w["task"])
        review = await _task(db, w["acme"], w["acme_agy"], w["acme_repo"], title="Review", spec={
            "mode": "read_only", "review_of_task_id": str(w["task"]),
        })

        async def meddle(root, prompt):
            _write(root, {"src/calculator.py": BUGGY})
            return report(artifacts=[], tests_run=["looked"]), 0

        db.emp.behave = meddle
        attempt = await _run(db, w["acme"], review)
        failed = [c["check"] for c in attempt.verification["checks"] if not c["passed"]]
        assert failed == ["read_only_worktree_clean"] and attempt.status == "failed"


async def _start_without_worker(db, w, task_id=None):
    """Queue an attempt without waking the attempt worker."""
    worker = ta.get_worker()
    wake = worker.wake
    worker.wake = lambda company_id=None: None
    try:
        return await _start(db, w["acme"], task_id or w["task"])
    finally:
        worker.wake = wake


# ---------------------------------------------------------------------------
# Recovery, retry and cancellation
# ---------------------------------------------------------------------------


class TestRecovery:
    async def test_dead_worker_is_recovered_without_rerunning_the_employee(self, db, w):
        attempt, _ = await _start_without_worker(db, w)
        claimed = await ta.claim(attempt.id, w["acme"], "dead-worker")
        await ta._prepare(claimed, "dead-worker")
        await chat_turns.drain()  # the employee finished; the worker "died" before verifying
        before = await _attempt(db, w["acme"], attempt.id)
        assert before.status == "running" and len(db.emp.calls) == 1

        outcome = await ta.sweep(ta._now() + LATER)
        assert outcome["recovered"] == 1
        queued = await _attempt(db, w["acme"], attempt.id)
        assert (queued.status, queued.recoveries, queued.claimed_by) == ("queued", 1, None)
        assert queued.worktree_id == before.worktree_id

        ta.get_worker().wake(w["acme"])
        await ta.drain()
        final = await _attempt(db, w["acme"], attempt.id)
        assert final.status == "completed" and len(db.emp.calls) == 1
        assert final.worktree_id == before.worktree_id
        _, root = await _worktree(db, final)
        assert len(_commits_with(root, "Nexus-Effect")) == 1

    async def test_recoveries_are_bounded(self, db, w, monkeypatch):
        monkeypatch.setattr(settings, "task_attempt_max_recoveries", 0)
        attempt, _ = await _start_without_worker(db, w)
        await ta.claim(attempt.id, w["acme"], "dead-worker")
        await ta.sweep(ta._now() + LATER)
        final = await _attempt(db, w["acme"], attempt.id)
        assert (final.status, final.error_code) == ("failed", "ATTEMPTS_EXHAUSTED")

    async def test_stale_queue_entries_expire(self, db, w):
        attempt, _ = await _start_without_worker(db, w)
        await ta.sweep(ta._now() + timedelta(seconds=settings.task_attempt_queue_ttl_seconds + 60))
        final = await _attempt(db, w["acme"], attempt.id)
        assert final.status == "expired"
        assert (await _rows(db, Task, Task.id == w["task"]))[0].status == "pending"

    async def test_commit_happens_once_even_if_the_ledger_write_was_lost(self, db, w):
        attempt = await _run(db, w["acme"], w["task"])
        row, root = await _worktree(db, attempt)
        (effect,) = await _rows(db, WorkEffect, WorkEffect.effect_key == f"commit:{attempt.id}")
        sha = effect.result["commit"]
        # Crash between the commit and the ledger update: the retry finds the trailer.
        async with db() as s:
            await s.execute(update(WorkEffect).where(WorkEffect.id == effect.id)
                            .values(status="pending", result=None))
            await s.commit()
        (root / "extra.txt").write_text("later")
        assert await ta.commit_work(attempt, row) == sha
        assert await ta.commit_work(attempt, row) == sha
        assert len(_commits_with(root, f"commit:{attempt.id}")) == 1

    async def test_retry_fixes_failed_verification_and_keeps_the_first_evidence(
        self, db, w, tmp_path
    ):
        async def buggy(root, prompt):
            _write(root, {"src/calculator.py": BUGGY, "tests/test_calculator.py": CALC_TESTS,
                          ".nexus/report.json": json.dumps(
                              {"seq": 1, "state": "working", "current_step": "first try"})})
            return report(), 0

        stale: list[bool] = []

        async def fix(root, prompt):
            stale.append((root / ".nexus" / "report.json").exists())
            return await db.emp.calculator(root, prompt)

        db.emp.behave = buggy
        first = await _run(db, w["acme"], w["task"])
        assert first.completion_reason == "verification_failed"
        first_log = (tmp_path / "evidence" / str(w["acme"]) / str(first.id) /
                     first.verification["commands"][0]["stdout"]["ref"]).read_text()

        db.emp.behave = fix
        async with db() as s:
            second, created = await ta.retry_attempt(s, w["acme"], w["task"], first.id,
                                                     _me(w["acme"]))
        again = None
        async with db() as s:
            again, created_again = await ta.retry_attempt(s, w["acme"], w["task"], first.id,
                                                          _me(w["acme"]))
        assert created and not created_again and again.id == second.id
        await ta.drain()
        second = await _attempt(db, w["acme"], second.id)
        assert (second.status, second.attempt_number) == ("completed", 2)
        # Same session and worktree: the retry continued the work.
        assert (second.session_id, second.worktree_id) == (first.session_id, first.worktree_id)
        # The retry prompt names the server checks the first attempt failed.
        retry_prompt = db.emp.calls[-1]["prompt"]
        assert "The previous attempt did not pass the server's checks" in retry_prompt
        assert "command:0:pytest: exit_code=1" in retry_prompt
        assert "previous attempt" not in db.emp.calls[0]["prompt"]
        # The first attempt's progress file is gone before the retry starts,
        # so it is never read as the retry's report.
        assert stale == [False]

        kept = await _attempt(db, w["acme"], first.id)
        assert kept.status == "failed" and kept.verification == first.verification
        assert kept.artifacts == first.artifacts
        assert (tmp_path / "evidence" / str(w["acme"]) / str(first.id) /
                first.verification["commands"][0]["stdout"]["ref"]).read_text() == first_log
        _, root = await _worktree(db, second)
        assert len(_commits_with(root, "Nexus-Effect")) == 1
        keys = [e.effect_key for e in await _rows(db, WorkEffect)]
        assert len(keys) == len(set(keys))
        assert (await _rows(db, Task, Task.id == w["task"]))[0].status == "completed"

        async with db() as s:
            with pytest.raises(HTTPException) as exc:
                await ta.retry_attempt(s, w["acme"], w["task"], second.id, _me(w["acme"]))
        assert exc.value.detail["code"] == "ATTEMPT_NOT_RETRYABLE"

    async def test_cancel_stops_only_that_attempt(self, db, w):
        other_task = await _task(db, w["acme"], w["acme_agy"], w["acme_repo"], title="Other")
        db.emp.gate = asyncio.Event()
        attempt, _ = await _start(db, w["acme"], w["task"])
        await asyncio.wait_for(db.emp.started.wait(), 30)
        async with db() as s:
            await ta.cancel_attempt(s, w["acme"], w["task"], attempt.id, _me(w["acme"]))
        db.emp.gate.set()
        await ta.drain()
        final = await _attempt(db, w["acme"], attempt.id)
        assert (final.status, final.completion_reason) == ("cancelled", "cancelled")
        assert final.cancelled_by == "lead@example.test"
        assert (await _rows(db, Task, Task.id == w["task"]))[0].status == "pending"
        assert (await _rows(db, Task, Task.id == other_task))[0].status == "pending"

    async def test_cancel_by_service_principal_names_it(self, db, w):
        attempt, _ = await _start_without_worker(db, w)
        service = Principal(kind="service", company_id=w["acme"], role="admin")
        async with db() as s:
            final = await ta.cancel_attempt(s, w["acme"], w["task"], attempt.id, service)
        assert final.status == "cancelled"
        assert final.cancelled_by == "service:auth-disabled" and "None" not in final.cancelled_by

    async def test_timeout_fails_the_attempt(self, db, w, monkeypatch):
        db.emp.gate = asyncio.Event()
        attempt, _ = await _start(db, w["acme"], w["task"])
        await asyncio.wait_for(db.emp.started.wait(), 30)
        real = ta._now
        monkeypatch.setattr(ta, "_now", lambda: real() + timedelta(hours=2))
        ta.get_worker().poke(attempt.id)
        await ta.drain()
        db.emp.gate.set()
        final = await _attempt(db, w["acme"], attempt.id)
        assert (final.status, final.completion_reason, final.error_code) == (
            "failed", "timeout", "TIMEOUT"
        )

    async def test_no_transaction_is_held_while_the_employee_works(self, db, w, tmp_path):
        writer = create_async_engine(
            f"sqlite+aiosqlite:///{(tmp_path / 'work.db').as_posix()}",
            connect_args={"timeout": 0.2},
        )

        async def during(root):
            async with writer.begin() as conn:  # "database is locked" if anyone holds a write
                await conn.execute(update(Task).where(Task.id == w["task"]).values(priority=7))

        db.emp.during = during
        try:
            attempt = await _run(db, w["acme"], w["task"])
        finally:
            await writer.dispose()
        assert attempt.status == "completed"


# ---------------------------------------------------------------------------
# Verification commands and processes
# ---------------------------------------------------------------------------


class TestVerificationRunner:
    async def test_logs_are_bounded_and_redacted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "task_attempt_log_bytes", 2000)
        root = tmp_path / "wt"
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "test_noisy.py").write_text(
            "import os\n\ndef test_noisy():\n"
            "    print(os.getcwd() * 400)\n"
            "    assert False\n"
        )
        evidence = tmp_path / "ev"
        evidence.mkdir()
        step = ta.VerificationStep(command="pytest", paths=["tests/test_noisy.py"])
        run = await ta.run_check(step, 0, root, evidence, 60)
        assert not run["passed"] and run["exit_code"] == 1
        assert run["stdout"]["truncated"] and run["stdout"]["bytes"] <= 2000
        log = (evidence / run["stdout"]["ref"]).read_text()
        assert str(root) not in log and "<worktree>" in log
        assert all(str(tmp_path) not in part for part in run["argv"])

    async def test_hung_check_is_killed(self, tmp_path):
        root = tmp_path / "wt"
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "test_hang.py").write_text(
            "import time\n\ndef test_hang():\n    time.sleep(120)\n"
        )
        evidence = tmp_path / "ev"
        evidence.mkdir()
        step = ta.VerificationStep(command="pytest", paths=["tests/test_hang.py"])
        run = await ta.run_check(step, 0, root, evidence, 5)
        assert run["timed_out"] and not run["passed"] and run["exit_code"] is None

    @pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects only exist on Windows")
    async def test_windows_job_kills_the_whole_tree(self):
        child = (
            "import subprocess, sys, time\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print(p.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", child, stdout=asyncio.subprocess.PIPE
        )
        cli_adapter._contain(proc)
        assert proc in cli_adapter._jobs
        grandchild = int((await proc.stdout.readline()).decode())
        await cli_adapter._terminate_tree(proc)
        assert proc not in cli_adapter._jobs
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x00100000, False, grandchild)  # SYNCHRONIZE
        if handle:  # still openable: it must be exiting, never left running
            try:
                assert kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 5000) == 0
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(handle))


# ---------------------------------------------------------------------------
# Hardening: audit identity and cataloged permission flags
# ---------------------------------------------------------------------------


class TestHardening:
    async def test_audit_rows_name_real_resources(self, db, w):
        from nexus.models.governance import AuditLog

        attempt = await _run(db, w["acme"], w["task"])
        rows = await _rows(db, AuditLog, AuditLog.company_id == w["acme"])
        (reply,) = [r for r in rows if r.action == "chat.response_generated"]
        assert (reply.resource_type, reply.resource_id) == ("chat", str(attempt.session_id))
        assert all(r.resource_id not in (None, "None") for r in rows
                   if r.action.startswith(("chat.", "task.attempt")))
        assert all("None" not in (r.actor_id or "") for r in rows)

    def test_work_modes_map_only_to_cataloged_flags(self):
        from nexus.adapters.cli_registry import get_cli_registry

        registry = get_cli_registry()
        claude, agy = registry.get_backend("claude"), registry.get_backend("agy")
        write = claude.build_args("do it", work_mode="write")
        assert write[1:4] == ["-p", "--permission-mode", "acceptEdits"]
        assert write[-1] == "do it" and "--dangerously-skip-permissions" not in write
        assert "plan" in claude.build_args("look", work_mode="read_only")
        assert agy.work_mode_args("read_only") == ("--mode", "plan")
        assert claude.build_args("chat") == [claude.command, "-p", "chat"]
        with pytest.raises(ValueError):
            claude.build_args("x", work_mode="yolo")
