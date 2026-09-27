"""P6.1: the hardened git runner.

Covers option injection through refs and paths, the timeout, hooks, the
filesystem monitor, external diff and textconv drivers, inherited GIT_*
environment, worktree creation and removal, the merge primitives
(merge-tree, commit-tree, compare-and-swap update-ref), and root confinement.

The "mutation" tests remove one safety option and show the attack it stops
then succeeds, so each option is proven necessary rather than decorative.
"""

import asyncio
import inspect
import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from nexus.runtime import git_runner
from nexus.runtime.git_runner import GitError, GitRunner
from nexus.runtime.worktree import WorktreeManager

SRC = Path(__file__).resolve().parents[1] / "src" / "nexus"


def git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Plain git for test setup and for control experiments; not the runner."""
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
        env={**os.environ, **(env or {})},
    )
    return done.stdout.strip()


def commit_file(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "core.autocrlf", "false")
    commit_file(path, "a.txt", "one\n", "c1")
    commit_file(path, "a.txt", "two\n", "c2")
    return path


def sh_append(marker: Path, word: str) -> str:
    """A shell snippet git will run that appends to ``marker``."""
    return f"echo {word} >> '{marker.as_posix()}'"


def install_hook(repo: Path, name: str, marker: Path) -> None:
    hook = repo / ".git" / "hooks" / name
    hook.write_text(f"#!/bin/sh\n{sh_append(marker, name)}\n")
    hook.chmod(0o755)


def head(repo: Path, ref: str = "main") -> str:
    return git(repo, "rev-parse", ref)


# -- option injection ------------------------------------------------------


@pytest.mark.parametrize("ref", ["--output=pwned", "-p", "--exec=touch pwned", "-"])
async def test_ref_starting_with_dash_is_refused(repo: Path, ref: str) -> None:
    runner = GitRunner(repo)
    with pytest.raises(GitError) as err:
        await runner.resolve_commit(ref)
    assert err.value.kind == "invalid_ref"
    with pytest.raises(GitError):
        await runner.diff(ref, "HEAD")
    with pytest.raises(GitError):
        await runner.diff("HEAD", ref)
    assert not list(repo.rglob("pwned*"))


@pytest.mark.parametrize(
    "ref", ["HEAD\n--output=x", "a b", "a\tb", "a\x00b", "a\x7fb", "x" * 300, ""]
)
async def test_ref_with_whitespace_control_or_excess_length_is_refused(repo: Path, ref: str) -> None:
    with pytest.raises(GitError) as err:
        await GitRunner(repo).resolve_commit(ref)
    assert err.value.kind == "invalid_ref"


async def test_end_of_options_alone_still_blocks_injection(repo: Path, monkeypatch) -> None:
    """Mutation: drop the leading-dash check; --end-of-options must still hold."""
    monkeypatch.setattr(git_runner, "check_ref_text", lambda ref: ref)
    out = repo.parent / "pwned-eoo"
    with pytest.raises(GitError) as err:
        await GitRunner(repo).resolve_commit(f"--output={out}")
    assert err.value.kind == "invalid_ref"
    assert not out.exists()


async def test_diff_passes_only_resolved_shas(repo: Path, monkeypatch) -> None:
    seen: list[tuple[str, ...]] = []
    real = GitRunner._run

    async def spy(self, *args, **kw):
        seen.append(args)
        return await real(self, *args, **kw)

    monkeypatch.setattr(GitRunner, "_run", spy)
    await GitRunner(repo).diff("HEAD~1", "main")
    diff_args = next(a for a in seen if a[0] == "diff")
    tail = diff_args[diff_args.index("--end-of-options") + 1:]
    assert re.fullmatch(r"[0-9a-f]{40}", tail[0]) and re.fullmatch(r"[0-9a-f]{40}", tail[1])
    assert tail[2] == "--"


@pytest.mark.parametrize(
    "name",
    ["-D", "--force", "a..b", "x.lock", "a b", "a~1", "a^", "a:b", "a?", "a*", "a[b",
     "@{-1}", "HEAD", "/abs", "trailing/", "a//b", "a\\b", "", "x" * 300, "a\x7f"],
)
async def test_malicious_branch_names_are_refused(repo: Path, name: str) -> None:
    before = git(repo, "for-each-ref", "--format=%(refname)")
    with pytest.raises(GitError) as err:
        await GitRunner(repo).create_branch(name)
    assert err.value.kind == "invalid_ref"
    assert git(repo, "for-each-ref", "--format=%(refname)") == before


async def test_shell_metacharacters_in_a_branch_name_are_never_interpreted(repo: Path) -> None:
    runner = GitRunner(repo)
    for name in ["x$(touch${IFS}pwned)", "y;touch${IFS}pwned", "z`touch${IFS}pwned`"]:
        try:
            await runner.create_branch(name)
        except GitError as err:
            assert err.kind == "invalid_ref"
    assert not list(repo.parent.rglob("pwned*"))


async def test_paths_starting_with_dash_are_refused(repo: Path) -> None:
    with pytest.raises(GitError) as err:
        GitRunner(Path("-repo"))
    assert err.value.kind == "invalid_path"
    runner = GitRunner(repo)
    await runner.create_branch("wt")
    for path in [Path("--force"), Path("-x"), Path("relative/dir")]:
        with pytest.raises(GitError) as err:
            await runner.add_worktree(path, "wt")
        assert err.value.kind == "invalid_path"
        with pytest.raises(GitError) as err:
            await runner.remove_worktree(path, force=True)
        assert err.value.kind == "invalid_path"


def test_repository_path_must_be_an_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(GitError) as err:
        GitRunner(tmp_path / "missing")
    assert err.value.kind == "invalid_path"


# -- timeout ---------------------------------------------------------------


async def test_timeout_kills_the_process(repo: Path, monkeypatch) -> None:
    killed: list[bool] = []

    class Hung:
        returncode = None

        async def communicate(self, _input=None):
            await asyncio.sleep(30)

        def kill(self):
            killed.append(True)

        async def wait(self):
            return -9

    async def fake_exec(*args, **kw):
        return Hung()

    monkeypatch.setattr(git_runner.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(GitError) as err:
        await GitRunner(repo, timeout=0.05).status_porcelain()
    assert err.value.kind == "timeout"
    assert killed == [True]


async def test_every_call_is_bounded_by_the_timeout(repo: Path) -> None:
    with pytest.raises(GitError) as err:
        await GitRunner(repo, timeout=1e-6).resolve_commit("HEAD")
    assert err.value.kind == "timeout"


async def test_missing_git_binary_is_a_structured_error(repo: Path, monkeypatch) -> None:
    async def no_git(*args, **kw):
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_runner.asyncio, "create_subprocess_exec", no_git)
    with pytest.raises(GitError) as err:
        await GitRunner(repo).status_porcelain()
    assert err.value.kind == "unavailable"


# -- hooks, fsmonitor, diff drivers ---------------------------------------


async def test_hooks_do_not_run(repo: Path, tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "hook-ran"
    for name in ("reference-transaction", "post-checkout", "pre-commit", "commit-msg", "post-commit"):
        install_hook(repo, name, marker)

    # Control: plain git runs the hook, so the hook itself works.
    git(repo, "update-ref", "refs/heads/control", "HEAD")
    assert marker.exists()
    marker.unlink()

    runner = GitRunner(repo)
    await runner.create_branch("feature")
    await runner.add_worktree(tmp_path / "wt", "feature")
    wt = GitRunner(tmp_path / "wt")
    (tmp_path / "wt" / "b.txt").write_text("b\n")
    await wt.stage_all()
    await wt.commit("from the runner")
    assert not marker.exists()

    # Mutation: without the hardening options the same call runs the hook.
    monkeypatch.setattr(git_runner, "_hardening", lambda: ())
    await runner.create_branch("feature2")
    assert marker.exists()


async def test_fsmonitor_does_not_run(repo: Path, tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "fsmonitor-ran"
    git(repo, "config", "core.fsmonitor", f"{sh_append(marker, 'fsm')}; :")

    assert await GitRunner(repo).status_porcelain() == ""
    assert not marker.exists()

    monkeypatch.setattr(git_runner, "_hardening", lambda: ())
    await GitRunner(repo).status_porcelain()
    assert marker.exists()


async def test_external_diff_driver_does_not_run(repo: Path, tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "ext-diff-ran"
    git(repo, "config", "diff.external", f"{sh_append(marker, 'ext')}; :")

    out = await GitRunner(repo).diff("HEAD~1", "HEAD")
    assert "-one" in out and "+two" in out
    assert not marker.exists()

    monkeypatch.setattr(git_runner, "DIFF_SAFETY", ())
    await GitRunner(repo).diff("HEAD~1", "HEAD")
    assert marker.exists()


async def test_textconv_driver_does_not_run(repo: Path, tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "textconv-ran"
    (repo / ".gitattributes").write_text("*.txt diff=conv\n")
    git(repo, "config", "diff.conv.textconv", f"{sh_append(marker, 'tc')}; cat")

    out = await GitRunner(repo).diff("HEAD~1", "HEAD")
    assert "+two" in out
    assert not marker.exists()

    monkeypatch.setattr(git_runner, "DIFF_SAFETY", ())
    await GitRunner(repo).diff("HEAD~1", "HEAD")
    assert marker.exists()


async def test_inherited_git_environment_is_ignored(repo: Path, tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    git(other, "-c", "user.name=o", "-c", "user.email=o@x", "commit", "-q", "--allow-empty", "-m", "other")
    other_head = head(other)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    # Control: plain git in the repo obeys GIT_DIR and reads the other repository.
    assert git(repo, "rev-parse", "HEAD") == other_head
    assert await GitRunner(repo).resolve_commit("HEAD") != other_head


# -- repository discovery ----------------------------------------------------
#
# Git searches the working directory and then its parents for a repository.
# The runner caps that search at the repository path, so a directory that is
# not a repository never runs against one that encloses it.


def init_repo(path: Path, message: str) -> str:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "core.autocrlf", "false")
    return commit_file(path, "f.txt", f"{message}\n", message)


@pytest.fixture
def enclosing(tmp_path: Path) -> tuple[Path, str]:
    """A repository standing in for the NEXUS checkout that encloses the roots."""
    outer = tmp_path / "outer"
    return outer, init_repo(outer, "outer")


async def test_valid_repository_still_resolves_refs(repo: Path) -> None:
    runner = GitRunner(repo)
    assert await runner.resolve_commit("HEAD") == head(repo)
    assert await runner.resolve_commit("main~1") == head(repo, "main~1")


async def test_nested_repository_resolves_its_own_refs(enclosing) -> None:
    outer, outer_head = enclosing
    inner = outer / "data" / "repos" / "inner"
    inner_head = init_repo(inner, "inner")

    runner = GitRunner(inner)
    assert await runner.resolve_commit("HEAD") == inner_head != outer_head
    assert "inner" in await runner.log(5, "%s")


async def test_linked_worktree_still_works(repo: Path, tmp_path: Path) -> None:
    runner = GitRunner(repo)
    await runner.create_branch("agent/ceiling")
    wt = tmp_path / "worktrees" / "ceiling"
    await runner.add_worktree(wt, "agent/ceiling")
    assert await GitRunner(wt).resolve_commit("HEAD") == head(repo)


async def test_directory_without_git_does_not_resolve_the_parent_repository(enclosing) -> None:
    outer, outer_head = enclosing
    plain = outer / "data" / "repos" / "plain"
    plain.mkdir(parents=True)

    # Control: plain git in the directory walks up and finds the outer repository.
    assert git(plain, "rev-parse", "HEAD") == outer_head
    with pytest.raises(GitError):
        await GitRunner(plain).resolve_commit("HEAD")


async def test_in_roots_directory_without_git_does_not_resolve_the_parent(enclosing) -> None:
    outer, _ = enclosing
    company = uuid.uuid4()
    (outer / "repos" / str(company) / "plain").mkdir(parents=True)
    roots = f"{outer.as_posix()}/repos/{{company_id}}"

    runner = GitRunner.in_roots(str(outer / "repos" / str(company) / "plain"), roots, company)
    with pytest.raises(GitError):
        await runner.resolve_commit("HEAD")


async def test_diff_commit_and_log_do_not_escape_into_the_parent(enclosing) -> None:
    outer, outer_head = enclosing
    plain = outer / "plain"
    plain.mkdir()
    (plain / "new.txt").write_text("agent output\n")
    runner = GitRunner(plain)

    with pytest.raises(GitError):
        await runner.stage_all()
    with pytest.raises(GitError):
        await runner.commit("escaped")
    with pytest.raises(GitError):
        await runner.log(5, "%H")
    with pytest.raises(GitError):
        await runner.status_porcelain()
    with pytest.raises(GitError):
        await runner.diff(outer_head, outer_head)
    with pytest.raises(GitError):
        await runner.create_branch("escaped")

    assert head(outer) == outer_head
    assert git(outer, "diff", "--cached", "--name-only") == ""
    assert git(outer, "branch", "--list", "escaped") == ""


async def test_ceiling_cannot_be_overridden_by_extra_env(enclosing) -> None:
    outer, _ = enclosing
    plain = outer / "plain"
    plain.mkdir()
    result = await GitRunner(plain)._run("rev-parse", "HEAD", env={"GIT_CEILING_DIRECTORIES": ""})
    assert result.returncode != 0


async def test_without_the_ceiling_the_parent_is_used(enclosing) -> None:
    """Mutation: drop the ceiling and the runner resolves the enclosing repository."""
    outer, outer_head = enclosing
    plain = outer / "plain"
    plain.mkdir()
    runner = GitRunner(plain)
    runner._ceiling = ""
    assert await runner.resolve_commit("HEAD") == outer_head


# -- structured results ----------------------------------------------------


async def test_failures_are_structured_and_do_not_embed_stderr(repo: Path) -> None:
    with pytest.raises(GitError) as err:
        await GitRunner(repo).delete_branch("no-such-branch", force=True)
    assert err.value.kind == "failed"
    assert err.value.stderr
    assert err.value.stderr not in str(err.value)
    assert isinstance(err.value, RuntimeError)


def test_runner_exposes_named_operations_only() -> None:
    """The runner takes git operations with structured arguments, not command strings."""
    for name, member in inspect.getmembers(GitRunner, inspect.isfunction):
        if name.startswith("_"):
            continue
        params = inspect.signature(member).parameters.values()
        assert not any(p.kind is p.VAR_POSITIONAL for p in params), name


def test_no_other_server_side_git_subprocess() -> None:
    """Server git goes through the runner. The Obsidian vault keeps its own
    bounded runner: it only reads status and HEAD of a server-owned vault."""
    call = re.compile(
        r"(create_subprocess_exec|subprocess\.(run|Popen|call|check_call|check_output))\(\s*\[?\s*[\"']git[\"']"
    )
    allowed = {SRC / "runtime" / "git_runner.py", SRC / "obsidian" / "vault_git.py"}
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if path not in allowed and call.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# -- worktrees -------------------------------------------------------------


async def test_worktree_create_and_remove(repo: Path, tmp_path: Path) -> None:
    runner = GitRunner(repo)
    await runner.create_branch("agent/w")
    wt = tmp_path / "worktrees" / "w"
    await runner.add_worktree(wt, "agent/w")
    assert (wt / "a.txt").read_text() == "two\n"
    assert wt.resolve().as_posix() in git(repo, "worktree", "list")

    await runner.remove_worktree(wt, force=True)
    await runner.delete_branch("agent/w", force=True)
    assert not wt.exists()
    assert "agent/w" not in git(repo, "branch", "--list")


async def test_create_branch_refuses_to_overwrite(repo: Path) -> None:
    runner = GitRunner(repo)
    await runner.create_branch("taken", "HEAD~1")
    with pytest.raises(GitError):
        await runner.create_branch("taken", "HEAD")
    assert head(repo, "taken") == head(repo, "HEAD~1")


async def test_worktree_manager_confines_agent_names(repo: Path) -> None:
    info = await WorktreeManager().create_worktree(str(repo), uuid.UUID(int=1), "../../evil name")
    path = Path(info.worktree_path)
    assert path.parent == repo.parent / "worktrees"
    assert info.branch == f"agent/evil-name-{str(uuid.UUID(int=1))[:8]}"
    assert info.agent_name == "../../evil name"


async def test_legacy_merge_conflict_leaves_main_checkout_untouched(repo: Path) -> None:
    manager = WorktreeManager()
    info = await manager.create_worktree(str(repo), uuid.uuid4(), "dev")
    commit_file(repo, "a.txt", "main\n", "main side")
    wt = Path(info.worktree_path)
    (wt / "a.txt").write_text("agent\n")
    await manager.commit_all(str(wt), "agent side")
    main_before = head(repo)

    result = await manager.merge_worktree(str(repo), str(wt), info.branch)

    assert result.success is False and result.conflicts == ["a.txt"]
    assert head(repo) == main_before
    assert not (repo / ".git" / "MERGE_HEAD").exists()
    assert git(repo, "status", "--porcelain") == ""


# -- merge primitives ------------------------------------------------------


@pytest.fixture
def diverged(repo: Path) -> tuple[Path, str, str]:
    """main and feature diverge on different files, so they merge cleanly."""
    git(repo, "branch", "feature")
    main = commit_file(repo, "m.txt", "m\n", "main work")
    git(repo, "checkout", "-q", "feature")
    feature = commit_file(repo, "f.txt", "f\n", "feature work")
    git(repo, "checkout", "-q", "main")
    return repo, main, feature


async def test_merge_tree_clean(diverged) -> None:
    repo, main, feature = diverged
    result = await GitRunner(repo).merge_tree(main, feature)
    assert result.clean
    names = git(repo, "ls-tree", "--name-only", result.tree).split()
    assert sorted(names) == ["a.txt", "f.txt", "m.txt"]


async def test_merge_tree_conflict(repo: Path) -> None:
    git(repo, "branch", "side")
    ours = commit_file(repo, "a.txt", "ours\n", "ours")
    git(repo, "checkout", "-q", "side")
    theirs = commit_file(repo, "a.txt", "theirs\n", "theirs")
    git(repo, "checkout", "-q", "main")
    result = await GitRunner(repo).merge_tree(ours, theirs)
    assert not result.clean and result.conflicts == ["a.txt"]


async def test_merge_primitives_refuse_non_oids(repo: Path) -> None:
    runner = GitRunner(repo)
    for bad in ["HEAD", "--output=x", "main", "abc"]:
        with pytest.raises(GitError):
            await runner.merge_tree(bad, head(repo))
        with pytest.raises(GitError):
            await runner.commit_tree(bad, [], "m")
        with pytest.raises(GitError):
            await runner.update_branch("main", bad, head(repo))


async def test_commit_tree_writes_a_commit_without_moving_refs(diverged) -> None:
    repo, main, feature = diverged
    runner = GitRunner(repo)
    tree = (await runner.merge_tree(main, feature)).tree
    sha = await runner.commit_tree(tree, [main, feature], "--not-an-option\n", author=("NEXUS", "nexus@local"))

    body = git(repo, "cat-file", "-p", sha)
    assert f"tree {tree}" in body
    assert f"parent {main}" in body and f"parent {feature}" in body
    assert "author NEXUS <nexus@local>" in body
    assert body.endswith("--not-an-option")
    assert head(repo) == main


async def test_update_branch_cas_success(diverged) -> None:
    repo, main, feature = diverged
    await GitRunner(repo).update_branch("feature", main, feature)
    assert head(repo, "feature") == main


async def test_update_branch_cas_fails_when_branch_moved(diverged) -> None:
    repo, main, feature = diverged
    with pytest.raises(GitError) as err:
        await GitRunner(repo).update_branch("feature", main, main)  # stale expectation
    assert err.value.kind == "stale_ref"
    assert head(repo, "feature") == feature


async def test_merge_into_success_does_not_touch_the_checkout(diverged) -> None:
    repo, main, feature = diverged
    outcome = await GitRunner(repo).merge_into("main", feature, main, "Merge feature")

    assert outcome.status == "merged"
    assert head(repo) == outcome.commit
    assert git(repo, "rev-parse", f"{outcome.commit}^1") == main
    assert git(repo, "rev-parse", f"{outcome.commit}^2") == feature
    assert not (repo / "f.txt").exists()  # the working tree was never written


async def test_merge_into_fails_cleanly_when_default_branch_moved(diverged) -> None:
    repo, main, feature = diverged
    moved = commit_file(repo, "late.txt", "late\n", "someone else landed first")

    with pytest.raises(GitError) as err:
        await GitRunner(repo).merge_into("main", feature, main, "Merge feature")

    assert err.value.kind == "stale_ref"
    assert head(repo) == moved
    assert "late.txt" in git(repo, "ls-tree", "--name-only", "main")


async def test_merge_into_conflict_changes_nothing(repo: Path) -> None:
    git(repo, "branch", "side")
    main = commit_file(repo, "a.txt", "ours\n", "ours")
    git(repo, "checkout", "-q", "side")
    side = commit_file(repo, "a.txt", "theirs\n", "theirs")
    git(repo, "checkout", "-q", "main")

    outcome = await GitRunner(repo).merge_into("main", side, main, "Merge side")
    assert outcome.status == "conflict" and outcome.conflicts == ["a.txt"]
    assert head(repo) == main


async def test_merge_into_up_to_date(diverged) -> None:
    repo, main, _ = diverged
    outcome = await GitRunner(repo).merge_into("main", head(repo, "main~1"), main, "noop")
    assert outcome.status == "up_to_date" and head(repo) == main


async def test_merge_into_up_to_date_still_checks_expected_head(diverged) -> None:
    repo, main, _ = diverged
    commit_file(repo, "late.txt", "late\n", "late")
    with pytest.raises(GitError) as err:
        await GitRunner(repo).merge_into("main", head(repo, "main~2"), main, "noop")
    assert err.value.kind == "stale_ref"


# -- root confinement ------------------------------------------------------


def _symlink(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False


def _junction(link: Path, target: Path) -> bool:
    if os.name != "nt":
        return False
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    return done.returncode == 0


def test_in_roots_accepts_a_repository_inside_the_root(repo: Path) -> None:
    runner = GitRunner.in_roots(str(repo), str(repo.parent), uuid.uuid4())
    assert runner.path == repo.resolve()


def test_in_roots_refuses_a_repository_outside_the_root(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "roots" / "{company_id}"
    for raw in [str(repo), str(root).replace("{company_id}", "x") + "/../../../repo"]:
        with pytest.raises(GitError) as err:
            GitRunner.in_roots(raw, str(root), uuid.uuid4())
        assert err.value.kind == "outside_roots"


@pytest.mark.parametrize("make", [_symlink, _junction], ids=["symlink", "junction"])
def test_in_roots_refuses_a_link_that_escapes_the_root(repo: Path, tmp_path: Path, make) -> None:
    company = uuid.uuid4()
    root = tmp_path / "roots" / str(company)
    root.mkdir(parents=True)
    link = root / "looks-inside"
    if not make(link, repo):
        pytest.skip(f"cannot create a {make.__name__.strip('_')} here")
    with pytest.raises(GitError) as err:
        GitRunner.in_roots(str(link), str(tmp_path / "roots" / "{company_id}"), company)
    assert err.value.kind == "outside_roots"
