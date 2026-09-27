"""The CLI instruction file NEXUS writes is removed however the execution ends.

Plain chat, streamed chat and task attempts all run through
``CLIAdapter.execute_task`` and so through one finalizer in ``_do_execute``.
A worker killed outright never reaches it; its file names a dead pid and is
recovered at the next write, at session termination and before the
session-end worktree snapshot. A file the user owns is never touched.
"""

# The shared fixtures are imported, so every test that takes one "redefines" it.
# ruff: noqa: F811

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.adapters import cli_adapter
from nexus.adapters.cli_adapter import (
    _INSTRUCTION_MARK,
    recover_instruction_files,
    release_all_instruction_files,
    release_instruction_file,
)
from tests.test_p6_5_git_worktrees import (  # noqa: F401  (sessions, world are fixtures)
    _active,
    _end,
    _fake_process,
    _git,
    sessions,
    world,
)
from tests.test_p6_5_hardening import _Backend, _cli_session

pytestmark = [pytest.mark.employee_work, pytest.mark.core_employee]

CLAUDE_MD = Path(".claude") / "CLAUDE.md"


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def _leftover(workspace: Path, pid: int) -> Path:
    """An instruction file as a NEXUS process ``pid`` writes it."""
    path = workspace / CLAUDE_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{_INSTRUCTION_MARK}{pid} -->\n# Agent\n\nold\n", encoding="utf-8")
    return path


async def _run(tmp_path, monkeypatch, process_factory, **payload):
    """Execute once in a fresh workspace; return (workspace, file seen during run, result)."""
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    seen: dict = {}

    async def spawn(*cmd, cwd=None, **kw):
        seen["during"] = (Path(cwd) / CLAUDE_MD).exists()
        return process_factory()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(cli_adapter, "_terminate_tree", AsyncMock())
    adapter, session = await _cli_session(workspace)
    result = await adapter.execute_task(
        session, uuid.uuid4(), {"prompt": "go", "system_prompt": "be good", **payload}
    )
    return workspace, seen, result


def _failing_process():
    process = _fake_process()
    process.returncode = 1
    process.wait = AsyncMock(return_value=1)
    return process


async def _forever(*args):
    await asyncio.Event().wait()


def _hanging_process():
    process = MagicMock(pid=None, returncode=None, stdin=None)
    process.stdout.read = process.stderr.read = process.wait = _forever
    return process


@pytest.mark.parametrize(
    "factory, succeeds",
    [(_fake_process, True), (_failing_process, False), (_hanging_process, False)],
    ids=["success", "failure", "timeout"],
)
async def test_file_is_removed_after_the_execution_ends(tmp_path, monkeypatch, factory, succeeds):
    workspace, seen, result = await _run(tmp_path, monkeypatch, factory, timeout=0.05)
    assert seen["during"] is True
    assert result.success is succeeds
    assert not (workspace / ".claude").exists()
    assert not cli_adapter._live_instruction_files


async def test_file_is_removed_when_spawning_fails(tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("spawn failed")

    workspace, _, result = await _run(tmp_path, monkeypatch, boom)
    assert not result.success
    assert not (workspace / ".claude").exists()


async def test_file_is_removed_when_the_execution_is_cancelled(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    started = asyncio.Event()

    async def spawn(*cmd, cwd=None, **kw):
        started.set()
        return _hanging_process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(cli_adapter, "_terminate_tree", AsyncMock())
    adapter, session = await _cli_session(workspace)
    run = asyncio.ensure_future(
        adapter.execute_task(session, uuid.uuid4(), {"prompt": "go", "system_prompt": "be good"})
    )
    await started.wait()
    assert (workspace / CLAUDE_MD).exists()
    run.cancel()  # what a client disconnect, a Cancel or shutdown delivers
    with pytest.raises(asyncio.CancelledError):
        await run
    assert not (workspace / ".claude").exists()


async def test_a_killed_workers_file_is_recovered_and_replaced(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _leftover(workspace, _dead_pid())
    prompts = []
    adapter, session = await _cli_session(workspace)
    real_build = adapter._build_args
    monkeypatch.setattr(
        adapter, "_build_args", lambda b, prompt, *a, **k: prompts.append(prompt) or real_build(b, prompt, *a, **k)
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=_fake_process()))
    await adapter.execute_task(session, uuid.uuid4(), {"prompt": "go", "system_prompt": "be good"})
    # The leftover did not block the write: the prompt went by file, not inline.
    assert prompts == ["go"]
    assert not (workspace / ".claude").exists()


async def test_recovery_removes_only_a_dead_writers_file(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    live = _leftover(workspace, os.getppid())  # another NEXUS process, still running
    recover_instruction_files(workspace)
    assert live.exists()
    _leftover(workspace, _dead_pid())
    recover_instruction_files(workspace)
    assert not (workspace / ".claude").exists()


async def test_session_termination_recovers_a_leftover(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    adapter, session = await _cli_session(workspace)
    _leftover(workspace, _dead_pid())
    await adapter.terminate(session)
    assert not (workspace / ".claude").exists()


async def test_a_user_file_is_preserved_and_the_prompt_goes_inline(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    user_file = workspace / CLAUDE_MD
    user_file.parent.mkdir(parents=True)
    user_file.write_text("# my own rules\n", encoding="utf-8")
    before = user_file.stat()
    prompts = []
    adapter, session = await _cli_session(workspace)
    real_build = adapter._build_args
    monkeypatch.setattr(
        adapter, "_build_args", lambda b, prompt, *a, **k: prompts.append(prompt) or real_build(b, prompt, *a, **k)
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=_fake_process()))
    await adapter.execute_task(session, uuid.uuid4(), {"prompt": "go", "system_prompt": "be good"})
    # Nothing was replaced, so there is nothing to restore: content and mtime are the user's.
    assert user_file.read_text(encoding="utf-8") == "# my own rules\n"
    assert user_file.stat().st_mtime_ns == before.st_mtime_ns
    assert prompts == ["be good\n\n---\n\ngo"]
    recover_instruction_files(workspace)
    release_instruction_file(workspace, user_file)
    assert user_file.read_text(encoding="utf-8") == "# my own rules\n"


async def test_cleanup_never_leaves_the_workspace(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = _leftover(tmp_path / "outside", _dead_pid())
    release_instruction_file(workspace, outside)
    release_instruction_file(workspace, workspace / ".." / "outside" / CLAUDE_MD)
    assert outside.exists()


async def test_repeated_cleanup_is_harmless(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    adapter, session = await _cli_session(workspace)
    written = adapter._write_instruction_file(
        str(workspace), _Backend(".claude/CLAUDE.md"), "be good", session
    )
    assert Path(written).read_text(encoding="utf-8").startswith(_INSTRUCTION_MARK)
    for _ in range(3):
        adapter._cleanup_instruction_file(written, str(workspace))
        release_all_instruction_files()
        recover_instruction_files(workspace)
    assert not (workspace / ".claude").exists()


async def test_shutdown_releases_files_still_held(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    adapter, session = await _cli_session(workspace)
    adapter._write_instruction_file(str(workspace), _Backend("AGENTS.md"), "be good", session)
    assert (workspace / "AGENTS.md").exists()
    release_all_instruction_files()
    assert not (workspace / "AGENTS.md").exists()


async def test_worktree_stays_clean_and_the_session_end_commit_excludes_leftovers(
    sessions, world, monkeypatch
):
    ids = world["a"]
    wt, path = await _active(sessions, ids, session_id=ids["session"])
    real_spawn = asyncio.create_subprocess_exec

    async def spawn(*cmd, cwd=None, **kw):
        Path(cwd, "work.txt").write_text("real work\n")
        return _fake_process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    adapter, session = await _cli_session(path)
    session.worktree_path = str(path)
    await adapter.execute_task(session, uuid.uuid4(), {"prompt": "go", "system_prompt": "be good"})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", real_spawn)
    assert _git(path, "status", "--porcelain", "--untracked-files=all") == "?? work.txt"

    # A worker killed mid-run leaves its file; the session-end snapshot skips it.
    _leftover(path, _dead_pid())
    await _end(sessions, ids)
    committed = _git(path, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert committed == ["work.txt"]
    assert not (path / ".claude").exists()
