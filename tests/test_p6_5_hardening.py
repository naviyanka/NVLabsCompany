"""P6.5 hardening: repository drivers, directory swaps, instruction files, the clone after a merge.

* A filter or merge driver defined by the repository's own config never runs:
  git refuses the command before it starts. The same driver installed by the
  operator (system or global config) still runs.
* A worktree directory, or the company directory above it, that is or becomes
  a link is refused, and on Windows it cannot be swapped while git checks out.
* The CLI adapter's instruction file is never written or removed through a
  link the agent planted in its worktree.
* A merge into the branch the clone has checked out detaches the clone at the
  commit its files are from, so nothing left there can commit over the merge.
"""

# The shared fixtures are imported, so every test that takes one "redefines" it.
# ruff: noqa: F811

import os
import shutil
import uuid
from pathlib import Path

import pytest

from nexus.adapters.cli_adapter import CLIAdapter
from nexus.governance.fs_roots import pinned_directory
from nexus.runtime.git_runner import GitError, GitRunner
from nexus.services import worktree_service
from nexus.services.worktree_service import CLONE_BRANCH_REF
from tests.test_p6_5_git_worktrees import (  # noqa: F401  (sessions, world are fixtures)
    _active,
    _approval,
    _approved,
    _commit,
    _create,
    _fake_process,
    _git,
    _link_dir,
    _move,
    _path,
    _refused,
    _row,
    _worktrees,
    sessions,
    world,
)

# ── Repository-defined drivers ───────────────────────────────────────────


def _marker_cmd(marker: Path, tail: str) -> str:
    return f"echo ran >> '{marker.as_posix()}'; {tail}"


def _filtered_repo(repo: Path, marker: Path, scope_args: tuple[str, ...] = ()) -> None:
    """Commit a file every checkout sends through filter ``evil``, defined in ``scope_args``."""
    (repo / ".gitattributes").write_text("*.txt filter=evil\n")
    _git(repo, "add", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attributes")
    _git(repo, "config", *scope_args, "filter.evil.smudge", _marker_cmd(marker, "cat"))
    _git(repo, "config", *scope_args, "filter.evil.clean", _marker_cmd(marker, "cat"))


@pytest.fixture
def clone(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _commit(path, "a.txt", "one\n", "init")
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A global config of the test's own, so the user's never leaks in."""
    path = tmp_path / "home"
    path.mkdir()
    for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(path))
    return path


def test_control_plain_git_runs_a_repository_filter_on_checkout(clone, tmp_path, home):
    marker = tmp_path / "marker"
    _filtered_repo(clone, marker)
    marker.unlink(missing_ok=True)
    _git(clone, "worktree", "add", "-q", str(tmp_path / "plain"), "-b", "plain")
    assert marker.exists()  # what the runner has to stop


@pytest.mark.parametrize("key", ["smudge", "clean", "process"])
async def test_runner_refuses_a_repository_filter(clone, tmp_path, home, key):
    marker = tmp_path / "marker"
    (clone / ".gitattributes").write_text("*.txt filter=evil\n")
    _git(clone, "config", f"filter.evil.{key}", _marker_cmd(marker, "cat"))
    git = GitRunner(clone)
    _git(clone, "branch", "wt")
    target = tmp_path / "wt"
    with pytest.raises(GitError) as err:
        await git.add_worktree(target, "wt")
    assert err.value.kind == "unsafe_config" and f"filter.evil.{key}" in str(err.value)
    for call in (git.stage_all(), git.status_porcelain()):
        with pytest.raises(GitError, match="filter.evil"):
            await call
    assert not marker.exists() and not target.exists()
    assert len(_worktrees(clone)) == 1


async def test_runner_refuses_a_repository_merge_driver(clone, tmp_path, home):
    marker = tmp_path / "marker"
    (clone / ".gitattributes").write_text("*.txt merge=evil\n")
    _git(clone, "add", ".gitattributes")
    base = _commit(clone, "a.txt", "base\n", "base")
    _git(clone, "config", "merge.evil.driver", _marker_cmd(marker, "false"))
    _git(clone, "checkout", "-q", "-b", "side")
    side = _commit(clone, "a.txt", "side\n", "side")
    _git(clone, "checkout", "-q", "main")
    main = _commit(clone, "a.txt", "main\n", "main")
    git = GitRunner(clone)
    with pytest.raises(GitError, match="merge.evil.driver"):
        await git.merge_tree(main, side)
    with pytest.raises(GitError, match="merge.evil.driver"):
        await git.merge_into("main", side, main, "m")
    assert not marker.exists()
    assert _git(clone, "rev-parse", "main") == main != base


async def test_a_filter_hidden_behind_an_include_is_refused(clone, tmp_path, home):
    marker = tmp_path / "marker"
    (clone / ".git" / "extra.cfg").write_text(
        f'[filter "evil"]\n\tsmudge = "{_marker_cmd(marker, "cat")}"\n'
    )
    _git(clone, "config", "include.path", "extra.cfg")
    _git(clone, "branch", "wt")
    with pytest.raises(GitError, match="unsafe_config|filter.evil") as err:
        await GitRunner(clone).add_worktree(tmp_path / "wt", "wt")
    assert err.value.kind == "unsafe_config"
    assert not marker.exists()


async def test_an_operator_installed_filter_still_runs(clone, tmp_path, home):
    marker = tmp_path / "marker"
    _filtered_repo(clone, marker, ("--global",))
    marker.unlink(missing_ok=True)
    _git(clone, "branch", "wt")
    await GitRunner(clone).add_worktree(tmp_path / "wt", "wt")
    assert marker.exists()


async def test_a_repository_copy_of_an_operator_filter_is_allowed(clone, tmp_path, home):
    # ``git lfs install --local`` writes the same filter the global install did.
    marker = tmp_path / "marker"
    _filtered_repo(clone, marker, ("--global",))
    _git(clone, "config", "filter.evil.smudge", _marker_cmd(marker, "cat"))
    _git(clone, "branch", "wt")
    await GitRunner(clone).add_worktree(tmp_path / "wt", "wt")
    # A different command under the same name is the repository's own.
    _git(clone, "config", "filter.evil.smudge", _marker_cmd(marker, "cat; true"))
    _git(clone, "branch", "wt2")
    with pytest.raises(GitError, match="filter.evil.smudge"):
        await GitRunner(clone).add_worktree(tmp_path / "wt2", "wt2")


async def test_reads_still_work_in_a_repository_with_a_driver(clone, tmp_path, home):
    marker = tmp_path / "marker"
    _filtered_repo(clone, marker)
    marker.unlink(missing_ok=True)
    git = GitRunner(clone)
    head = await git.resolve_commit("main")
    assert await git.current_branch() == "refs/heads/main"
    assert await git.diff(f"{head}~1", head)
    assert not marker.exists()


async def test_activation_in_a_repository_with_a_driver_is_refused(sessions, world, tmp_path, home):
    ids = world["a"]
    marker = tmp_path / "marker"
    wt = await _create(sessions, ids)
    _filtered_repo(ids["clone"], marker)
    marker.unlink(missing_ok=True)
    err = await _refused(_move(sessions, ids, wt.id, "active"), "invalid_repository")
    assert err.status_code == 422 and "filter.evil" in err.detail
    assert (await _row(sessions, wt.id)).status == "created"
    assert len(_worktrees(ids["clone"])) == 1
    assert not marker.exists()


async def test_merge_in_a_repository_with_a_merge_driver_is_refused(
    sessions, world, tmp_path, home
):
    ids = world["a"]
    clone = ids["clone"]
    marker = tmp_path / "marker"
    wt, _ = await _approved(sessions, ids, name="shared.txt", text="agent\n")
    main = _commit(clone, "unrelated.txt", "x\n")
    (clone / ".git" / "info" / "attributes").write_text("* merge=evil\n")
    _git(clone, "config", "merge.evil.driver", _marker_cmd(marker, "true"))
    await _refused(_move(sessions, ids, wt.id, "merged"), "invalid_repository")
    assert _git(clone, "rev-parse", "main") == main
    assert (await _row(sessions, wt.id)).status == "approved"
    assert not marker.exists()


# ── Directory swaps ──────────────────────────────────────────────────────


async def test_a_link_planted_at_the_worktree_path_is_refused(sessions, world, tmp_path):
    ids = world["a"]
    wt = await _create(sessions, ids)
    outside = tmp_path / "outside"
    outside.mkdir()
    path = _path(ids, wt)
    path.parent.mkdir(parents=True, exist_ok=True)
    _link_dir(path, outside)
    await _refused(_move(sessions, ids, wt.id, "active"), "invalid_path")
    assert not any(outside.iterdir())
    assert (await _row(sessions, wt.id)).status == "created"
    assert len(_worktrees(ids["clone"])) == 1


async def test_a_company_directory_replaced_by_a_link_is_refused(sessions, world, tmp_path):
    ids = world["a"]
    wt = await _create(sessions, ids)
    outside = tmp_path / "outside"
    outside.mkdir()
    company_dir = _path(ids, wt).parent
    company_dir.parent.mkdir(parents=True, exist_ok=True)
    _link_dir(company_dir, outside)
    await _refused(_move(sessions, ids, wt.id, "active"), "invalid_path")
    assert not any(outside.iterdir())
    assert len(_worktrees(ids["clone"])) == 1


async def test_an_empty_directory_left_by_a_failed_activation_is_reused(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    _path(ids, wt).mkdir(parents=True)
    wt = await _move(sessions, ids, wt.id, "active")
    assert (_path(ids, wt) / "shared.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="the swap is only blocked on Windows")
async def test_the_worktree_directory_cannot_be_swapped_during_checkout(
    sessions, world, tmp_path, monkeypatch
):
    ids = world["a"]
    wt = await _create(sessions, ids)
    path = _path(ids, wt)
    outside = tmp_path / "outside"
    outside.mkdir()
    real = GitRunner.add_worktree
    attempts: dict[str, int] = {}

    async def racing(self, target, branch):
        # The swap an attacker would make between the service's checks and git.
        for name, attempt in (
            ("rename", lambda: os.rename(target, tmp_path / "moved")),
            ("rmdir", lambda: os.rmdir(target)),
            ("rename_company", lambda: os.rename(target.parent, tmp_path / "moved_co")),
        ):
            try:
                attempt()
            except OSError as exc:
                attempts[name] = exc.winerror
        return await real(self, target, branch)

    monkeypatch.setattr(GitRunner, "add_worktree", racing)
    wt = await _move(sessions, ids, wt.id, "active")
    assert set(attempts) == {"rename", "rmdir", "rename_company"}, attempts
    assert (path / "shared.txt").exists() and not any(outside.iterdir())
    assert not (tmp_path / "moved").exists() and not (tmp_path / "moved_co").exists()


def test_pinned_directory_refuses_a_link(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _link_dir(link, target)
    with pytest.raises(OSError):
        with pinned_directory(link):
            pass


# ── Instruction files ────────────────────────────────────────────────────


class _Backend:
    def __init__(self, instruction_path: str) -> None:
        self.instruction_path = instruction_path


async def _cli_session(workspace: Path):
    adapter = CLIAdapter()
    session = await adapter.create_session(
        uuid.uuid4(), {"backend": "claude", "workspace": str(workspace)}
    )
    return adapter, session


async def test_instruction_file_is_written_and_removed(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    adapter, session = await _cli_session(workspace)
    written = adapter._write_instruction_file(
        str(workspace), _Backend(".claude/CLAUDE.md"), "be good", session
    )
    assert written and Path(written).read_text(encoding="utf-8").endswith("be good\n")
    adapter._cleanup_instruction_file(written)
    assert not (workspace / ".claude").exists()


async def test_instruction_file_is_not_written_through_a_linked_directory(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _link_dir(workspace / ".claude", outside)
    adapter, session = await _cli_session(workspace)
    written = adapter._write_instruction_file(
        str(workspace), _Backend(".claude/CLAUDE.md"), "be good", session
    )
    assert written is None and not any(outside.iterdir())


async def test_instruction_file_is_not_written_through_a_linked_file(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    victim = tmp_path / "victim.md"
    try:
        os.symlink(victim, workspace / "AGENTS.md")  # dangling: the write would create it
    except OSError:
        pytest.skip("file symlinks cannot be created here")
    adapter, session = await _cli_session(workspace)
    written = adapter._write_instruction_file(
        str(workspace), _Backend("AGENTS.md"), "be good", session
    )
    assert written is None and not victim.exists()


async def test_instruction_file_cleanup_does_not_follow_a_link(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    adapter, session = await _cli_session(workspace)
    written = adapter._write_instruction_file(
        str(workspace), _Backend(".claude/CLAUDE.md"), "be good", session
    )
    assert written
    # While the CLI ran, it moved the directory away and linked it elsewhere.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "CLAUDE.md").write_text("not ours\n")
    shutil.rmtree(workspace / ".claude")
    _link_dir(workspace / ".claude", outside)
    adapter._cleanup_instruction_file(written)
    assert (outside / "CLAUDE.md").read_text() == "not ours\n"


async def test_execution_in_a_worktree_with_a_linked_instruction_dir_writes_nothing_outside(
    sessions, world, tmp_path, monkeypatch
):
    import asyncio

    ids = world["a"]
    wt, path = await _active(sessions, ids)
    outside = tmp_path / "outside"
    outside.mkdir()
    _link_dir(path / ".claude", outside)

    async def spawn(*cmd, cwd=None, **kw):
        return _fake_process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    adapter, session = await _cli_session(tmp_path / "unused")
    session.worktree_path = str(path)
    result = await adapter.execute_task(
        session, uuid.uuid4(), {"prompt": "go", "system_prompt": "be good"}
    )
    assert result.success, result.error
    assert not any(outside.iterdir())


# ── The clone after a merge ──────────────────────────────────────────────


async def test_merge_detaches_the_clone_where_its_files_are(sessions, world):
    ids = world["a"]
    clone = ids["clone"]
    wt, _ = await _approved(sessions, ids)
    old_main = _git(clone, "rev-parse", "main")
    row = await _move(sessions, ids, wt.id, "merged")

    assert _git(clone, "rev-parse", "main") == row.merged_commit != old_main
    # HEAD is detached at the commit the clone's files and index match.
    assert _git(clone, "rev-parse", "HEAD") == old_main
    assert _git(clone, "status", "--porcelain") == ""
    assert not (clone / "work.txt").exists()
    assert _git(clone, "symbolic-ref", CLONE_BRANCH_REF) == "refs/heads/main"
    # A commit made in the clone now cannot move main back over the merge.
    _commit(clone, "late.txt", "late\n")
    assert _git(clone, "rev-parse", "main") == row.merged_commit


async def test_head_still_means_the_clone_branch_after_a_merge(sessions, world):
    ids = world["a"]
    clone = ids["clone"]
    first, _ = await _approved(sessions, ids)
    merged = (await _move(sessions, ids, first.id, "merged")).merged_commit
    second, _ = await _approved(sessions, ids, name="more.txt", text="more\n")
    assert second.base_ref == "HEAD" and second.base_commit == merged
    row = await _move(sessions, ids, second.id, "merged")
    parents = _git(clone, "rev-list", "--parents", "-n", "1", "main").split()[1:]
    assert parents == [merged, second.head_commit]
    assert _git(clone, "rev-parse", "main") == row.merged_commit
    assert _git(clone, "rev-parse", "HEAD") == ids["base"]
    assert _git(clone, "status", "--porcelain") == ""


async def test_merge_into_a_branch_checked_out_elsewhere_is_refused(sessions, world, tmp_path):
    ids = world["a"]
    clone = ids["clone"]
    _git(clone, "branch", "release")
    _git(clone, "worktree", "add", "-q", str(tmp_path / "human"), "release")
    wt, _ = await _approved(sessions, ids, base_ref="release")
    release = _git(clone, "rev-parse", "release")
    err = await _refused(_move(sessions, ids, wt.id, "merged"), "conflict")
    assert "another worktree" in err.detail
    assert _git(clone, "rev-parse", "release") == release
    assert (await _row(sessions, wt.id)).status == "approved"


async def test_merge_into_a_branch_the_clone_has_not_checked_out_leaves_it_attached(
    sessions, world
):
    ids = world["a"]
    clone = ids["clone"]
    _git(clone, "branch", "release")
    wt, _ = await _approved(sessions, ids, base_ref="release")
    await _move(sessions, ids, wt.id, "merged")
    assert _git(clone, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert _git(clone, "rev-parse", "main") == ids["base"]


async def test_a_clone_that_moved_before_the_detach_is_not_merged(sessions, world, monkeypatch):
    ids = world["a"]
    clone = ids["clone"]
    wt, _ = await _approved(sessions, ids)
    real = GitRunner.detach_head
    moved: list[str] = []

    async def racing(self, expected):
        moved.append(_commit(clone, "racer.txt", "racer\n"))
        return await real(self, expected)

    monkeypatch.setattr(GitRunner, "detach_head", racing)
    err = await _refused(_move(sessions, ids, wt.id, "merged"), "conflict")
    assert "moved during the merge" in err.detail
    assert _git(clone, "rev-parse", "main") == moved[0]
    assert _git(clone, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert (await _row(sessions, wt.id)).status == "approved"


def test_nothing_checks_out_a_branch_to_refresh_the_clone():
    from nexus.runtime import git_runner

    for module in (worktree_service, git_runner):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert '"checkout"' not in source and '"switch"' not in source


# ── Remaining P6 debt ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "arg",
    ["--add-dir", "--ADD-DIR=/", "--settings=x.json", "--include-directories", "--cd", "--sandbox"],
)
def test_task_payloads_cannot_widen_a_cli_agents_directories(arg):
    from nexus.tools.access import check_cli_args

    assert check_cli_args([arg, "/"]) is not None


@pytest.mark.parametrize("arg", ["-wother", "-W", "--WORKTREE=x"])
async def test_claude_code_catches_every_spelling_of_another_worktree(tmp_path, monkeypatch, arg):
    import asyncio

    from nexus.adapters.claude_code_adapter import ClaudeCodeAdapter

    async def spawn(*a, **kw):
        raise AssertionError("no process may start")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    adapter = ClaudeCodeAdapter()
    session = await adapter.create_session(uuid.uuid4(), {"workspace": str(tmp_path / "ws")})
    session.worktree_path = str(tmp_path)
    result = await adapter.execute_task(session, uuid.uuid4(), {"prompt": "go", "args": [arg]})
    assert not result.success


async def test_stored_adapter_config_cannot_choose_where_a_woken_agent_runs(tmp_path):
    from unittest.mock import AsyncMock

    from nexus.models.agent import Agent
    from nexus.runtime.lifecycle import AgentLifecycleManager

    agent = Agent(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        name="a",
        status="idle",
        adapter_config={"workspace": str(tmp_path), "use_worktree": True, "model": "m"},
    )
    adapter = AsyncMock()
    manager = AgentLifecycleManager(AsyncMock(), adapter)
    manager._get_agent = AsyncMock(return_value=agent)
    manager._update_status = AsyncMock()
    await manager.wake_agent(agent.id)
    assert adapter.create_session.await_args.kwargs["config"] == {"model": "m"}


async def test_a_worktree_with_no_commits_is_not_merged(sessions, world):
    ids = world["a"]
    wt, _ = await _active(sessions, ids)
    wt = await _move(sessions, ids, wt.id, "review")
    approval = await _approval(sessions, ids, wt.id, wt.head_commit)
    await _move(sessions, ids, wt.id, "approved", approval_id=approval)
    err = await _refused(_move(sessions, ids, wt.id, "merged"), "conflict")
    assert "no commits" in err.detail
    assert (await _row(sessions, wt.id)).status == "approved"


async def test_a_concurrent_loser_is_told_what_it_lost_to(sessions, world):
    ids = world["a"]
    wt = await _create(sessions, ids)
    async with sessions() as stale:
        row = await stale.get(worktree_service.AgentWorktree, wt.id)
        await _move(sessions, ids, wt.id, "archived")
        err = await _refused(
            worktree_service._cas(stale, row, "created", {"status": "active"}), "conflict"
        )
    assert err.detail == "Worktree is now archived; reload and retry"
