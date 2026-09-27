"""Hardened git execution boundary.

Every server-side git call goes through ``GitRunner``. It exposes named
operations with structured arguments, never a command string, and each one
runs git:

* as an argument list (``create_subprocess_exec``), never through a shell;
* with hooks disabled (``core.hooksPath`` points at an empty directory) and
  the filesystem monitor off (``core.fsmonitor=false``). Both are passed with
  ``-c``, which outranks the repository's own config, so a repository cannot
  turn either back on;
* without inherited ``GIT_*`` environment variables, which could otherwise
  redirect the call to another repository (``GIT_DIR``) or inject config
  (``GIT_CONFIG_PARAMETERS``), and with terminal prompts disabled;
* with ``GIT_CEILING_DIRECTORIES`` set to the parent of the repository path,
  so a directory that is not itself a repository fails instead of silently
  resolving to a repository further up the tree;
* under a timeout, after which the process is killed.

Refs that come from outside are checked, resolved to commit SHAs, and only
reach git after ``--end-of-options``, so none can be read as an option. Diffs
pass ``--no-ext-diff`` and ``--no-textconv``. The repository is an explicit,
absolute, server-controlled path; ``GitRunner.in_roots`` confines a stored
path to the configured roots before any git runs there.

Filter and merge drivers are commands a ``.gitattributes`` file selects and
git config defines; git runs them while it reads or writes file contents
(checkout, ``worktree add``, ``add``, ``status``, ``commit``, ``merge``,
``merge-tree``, ``revert``). Before any of those, the runner reads the driver
definitions git would see and refuses to run if one comes from the
repository's own config (``.git/config``, ``config.worktree``, or a file they
include) unless the system or global config defines the same command. Drivers
the server's own git installation or user configures, such as Git LFS, still
run. This is a check made just before the command, not a lock: a process that
can write the repository's ``.git`` directory in between can still slip one
in. Keeping agents from writing a repository's ``.git`` directory is the job
of process sandboxing.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nexus.governance.fs_roots import resolve_in_roots

GIT_TIMEOUT_SECONDS = 30.0
MAX_REF_LENGTH = 256
DIFF_SAFETY = ("--no-ext-diff", "--no-textconv")

_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_hooks_dir: str | None = None

# Subcommands that read or write file contents through a working tree or the
# index, and so can start a filter or merge driver.
_CONTENT_COMMANDS = frozenset({"add", "commit", "merge", "merge-tree", "revert", "status"})
_CONTENT_WORKTREE_COMMANDS = frozenset({"add", "remove"})
# Config git reads from outside the repository: the installation's, the
# server user's, and the runner's own ``-c`` overrides.
_TRUSTED_SCOPES = frozenset({"system", "global", "command"})
_DRIVER_KEY = re.compile(r"filter\..+\.(clean|smudge|process)|merge\..+\.driver")


def _hardening() -> tuple[str, ...]:
    """Config overrides placed before every subcommand."""
    global _hooks_dir
    if _hooks_dir is None:
        # An empty directory works the same on every platform. If it is ever
        # deleted, git finds no hooks at the missing path either.
        _hooks_dir = tempfile.mkdtemp(prefix="nexus-git-no-hooks-")
    return ("-c", f"core.hooksPath={_hooks_dir}", "-c", "core.fsmonitor=false")


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    if extra:
        env.update(extra)
    return env


GitErrorKind = Literal[
    "invalid_ref", "invalid_path", "outside_roots", "timeout",
    "unavailable", "failed", "conflict", "stale_ref", "unsafe_config",
]


class GitError(RuntimeError):
    """A git operation was refused or failed.

    ``kind`` is stable for callers to branch on. ``stderr`` is kept for logs;
    it can contain server paths, so callers should not echo it to clients.
    """

    def __init__(self, kind: GitErrorKind, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.stderr = stderr


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class MergeTreeResult:
    """Outcome of ``merge-tree --write-tree``: the merged tree and any conflicted paths."""

    tree: str
    conflicts: list[str]

    @property
    def clean(self) -> bool:
        return not self.conflicts


@dataclass(frozen=True)
class MergeOutcome:
    """Outcome of ``GitRunner.merge_into``.

    ``merged``: the branch now points at ``commit``. ``up_to_date``: the source
    was already contained, nothing changed. ``conflict``: nothing changed,
    ``conflicts`` lists the paths.
    """

    status: Literal["merged", "up_to_date", "conflict"]
    commit: str | None
    conflicts: list[str]


@dataclass(frozen=True)
class WorktreeEntry:
    """One entry of ``git worktree list``, as the repository itself records it.

    ``branch`` is the full ref (``refs/heads/...``), or None when the worktree
    is detached. ``prunable`` means git found the directory missing.
    """

    path: Path
    head: str | None
    branch: str | None
    prunable: bool


def _author_env(author: tuple[str, str] | None) -> dict[str, str] | None:
    if not author:
        return None
    name, email = author
    return {
        "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
    }


def check_ref_text(ref: str) -> str:
    """Refuse ref text that could be read as an option or smuggle whitespace."""
    if (
        not ref
        or len(ref) > MAX_REF_LENGTH
        or ref.startswith("-")
        or any(ch.isspace() or not ch.isprintable() for ch in ref)
    ):
        raise GitError("invalid_ref", f"Invalid ref: {ref!r}")
    return ref


def _check_oid(oid: str) -> str:
    if not _OID.fullmatch(oid):
        raise GitError("invalid_ref", f"Not an object id: {oid!r}")
    return oid


def _check_abs_path(path: Path) -> str:
    """Paths handed to git as arguments must be absolute, so none starts with '-'."""
    if not Path(path).is_absolute():
        raise GitError("invalid_path", f"Path must be absolute: {str(path)!r}")
    return str(path)


class GitRunner:
    """Runs git operations inside one server-controlled repository or worktree."""

    def __init__(self, repo_path: Path, *, timeout: float = GIT_TIMEOUT_SECONDS) -> None:
        path = Path(repo_path)
        if not path.is_absolute():
            raise GitError("invalid_path", f"Repository path must be absolute: {str(path)!r}")
        path = path.resolve()
        if not path.is_dir():
            raise GitError("invalid_path", f"Repository path is not a directory: {path}")
        self.path = path
        self.timeout = timeout
        # Git looks for a repository in the working directory and then walks
        # up through its parents. A directory with no .git of its own would
        # otherwise run against whatever repository encloses it -- under the
        # default roots, the NEXUS checkout itself. The ceiling is the parent,
        # so git may check this directory and never climb out of it. A linked
        # worktree still works: its .git file sits in this directory.
        self._ceiling = path.parent.as_posix()

    @classmethod
    def in_roots(
        cls, raw: str, roots: str, company_id: uuid.UUID, *, timeout: float = GIT_TIMEOUT_SECONDS
    ) -> GitRunner:
        """Build a runner for ``raw`` only if it resolves inside one of ``roots``.

        Resolution follows symlinks and junctions, so a link inside a root
        that points outside it is refused.
        """
        path = resolve_in_roots(raw, roots, company_id)
        if path is None:
            raise GitError("outside_roots", "Repository path is outside the allowed roots")
        return cls(path, timeout=timeout)

    async def _run(
        self, *args: str, stdin: str | None = None, env: dict[str, str] | None = None
    ) -> GitResult:
        if args[0] in _CONTENT_COMMANDS or (
            args[0] == "worktree" and args[1] in _CONTENT_WORKTREE_COMMANDS
        ):
            await self._refuse_repository_drivers()
        return await self._exec(*args, stdin=stdin, env=env)

    async def _refuse_repository_drivers(self) -> None:
        """Refuse when the repository's own config defines a filter or merge driver.

        A driver the system or global config defines with the same command is
        allowed: the repository adds nothing the server does not already run.
        """
        result = await self._exec(
            "config", "--show-scope", "-z", "--get-regexp", r"^(filter|merge)\."
        )
        if result.returncode not in (0, 1):  # 1: no matching keys
            raise GitError("failed", "git config failed", stderr=result.stderr)
        # -z prints "scope NUL key NEWLINE value NUL" for every entry.
        items = result.stdout.split("\0")
        entries = [
            (scope, *items[i + 1].partition("\n")[::2])
            for i, scope in enumerate(items[:-1])
            if i % 2 == 0
        ]
        trusted = {(key, value) for scope, key, value in entries if scope in _TRUSTED_SCOPES}
        for scope, key, value in entries:
            if (
                value
                and scope not in _TRUSTED_SCOPES
                and _DRIVER_KEY.fullmatch(key)
                and (key, value) not in trusted
            ):
                raise GitError(
                    "unsafe_config",
                    f"Repository config defines {key}; refusing to run a repository-defined driver",
                )

    async def _exec(
        self, *args: str, stdin: str | None = None, env: dict[str, str] | None = None
    ) -> GitResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *_hardening(), *args,
                cwd=self.path,
                # Set last so no caller's extra env can replace it.
                env=_env({**(env or {}), "GIT_CEILING_DIRECTORIES": self._ceiling}),
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise GitError("unavailable", "git is not installed") from exc
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin is not None else None), self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise GitError("timeout", f"git {args[0]} timed out after {self.timeout}s") from None
        return GitResult(
            proc.returncode or 0,
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
        )

    async def _ok(
        self, *args: str, stdin: str | None = None, env: dict[str, str] | None = None
    ) -> str:
        result = await self._run(*args, stdin=stdin, env=env)
        if result.returncode != 0:
            raise GitError("failed", f"git {args[0]} failed (rc={result.returncode})", stderr=result.stderr)
        return result.stdout

    # -- refs --------------------------------------------------------------

    async def resolve_commit(self, ref: str) -> str:
        """Resolve an externally supplied ref to a commit SHA."""
        check_ref_text(ref)
        result = await self._run("rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
        sha = result.stdout.strip()
        if result.returncode != 0 or not _OID.fullmatch(sha):
            raise GitError("invalid_ref", f"Unknown ref: {ref!r}")
        return sha

    async def check_branch_name(self, name: str) -> str:
        check_ref_text(name)
        if name == "HEAD" or (await self._run("check-ref-format", f"refs/heads/{name}")).returncode != 0:
            raise GitError("invalid_ref", f"Invalid branch name: {name!r}")
        return name

    async def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        result = await self._run(
            "merge-base", "--is-ancestor", "--end-of-options", _check_oid(ancestor), _check_oid(descendant)
        )
        if result.returncode not in (0, 1):
            raise GitError("failed", "git merge-base failed", stderr=result.stderr)
        return result.returncode == 0

    async def create_branch(self, name: str, start: str = "HEAD") -> str:
        """Create ``name`` at ``start``; fails if the branch already exists."""
        await self.check_branch_name(name)
        sha = await self.resolve_commit(start)
        # An empty old value makes update-ref create-only.
        await self._ok("update-ref", "-m", "nexus: create branch", f"refs/heads/{name}", sha, "")
        return sha

    async def delete_branch(self, name: str, *, force: bool = False) -> None:
        await self.check_branch_name(name)
        await self._ok("branch", "-D" if force else "-d", "--end-of-options", name)

    async def update_branch(self, name: str, new: str, expected_old: str) -> None:
        """Compare-and-swap ``name`` from ``expected_old`` to ``new``.

        Raises ``GitError("stale_ref")`` when the branch no longer points at
        ``expected_old``; the branch is left untouched.
        """
        await self.check_branch_name(name)
        ref = f"refs/heads/{name}"
        result = await self._run(
            "update-ref", "-m", "nexus: merge", ref, _check_oid(new), _check_oid(expected_old)
        )
        if result.returncode == 0:
            return
        current = await self._run("rev-parse", "--verify", "--quiet", ref)
        if current.stdout.strip() != expected_old:
            raise GitError("stale_ref", f"{name} moved from {expected_old[:12]}", stderr=result.stderr)
        raise GitError("failed", f"git update-ref {name} failed", stderr=result.stderr)

    # -- reading -----------------------------------------------------------

    async def log(self, max_count: int, fmt: str) -> str:
        """``git log`` of HEAD. ``fmt`` is a server-side pretty format, never caller input."""
        return await self._ok("log", f"--max-count={int(max_count)}", f"--pretty=format:{fmt}")

    async def diff(self, base: str, target: str, *, stat: bool = False) -> str:
        """Diff two refs. Both are resolved to SHAs first; external drivers never run."""
        base_sha = await self.resolve_commit(base)
        target_sha = await self.resolve_commit(target)
        extra = ("--stat",) if stat else ()
        return await self._ok("diff", *DIFF_SAFETY, *extra, "--end-of-options", base_sha, target_sha, "--")

    async def status_porcelain(self) -> str:
        return await self._ok("status", "--porcelain")

    async def current_branch(self) -> str | None:
        """The full ref HEAD points at, or None when HEAD is detached."""
        return await self.symbolic_ref("HEAD")

    async def symbolic_ref(self, name: str) -> str | None:
        """The branch ref the symbolic ref ``name`` points at, or None if it points at no branch."""
        result = await self._run("symbolic-ref", "--quiet", check_ref_text(name))
        ref = result.stdout.strip()
        return ref if result.returncode == 0 and ref.startswith("refs/heads/") else None

    async def set_symbolic_ref(self, name: str, branch: str) -> None:
        """Point the symbolic ref ``name`` at branch ``branch``."""
        await self.check_branch_name(branch)
        await self._ok(
            "symbolic-ref",
            "-m",
            "nexus: record branch",
            check_ref_text(name),
            f"refs/heads/{branch}",
        )

    async def detach_head(self, expected: str) -> None:
        """Detach HEAD at ``expected``, the commit it is on now.

        Only HEAD changes: no file and not the index, so the checkout stays
        exactly what it was, now on a detached HEAD at the commit it matches.
        Raises ``GitError("stale_ref")`` if HEAD is no longer at ``expected``.
        """
        oid = _check_oid(expected)
        result = await self._run(
            "update-ref", "--no-deref", "-m", "nexus: detach", "HEAD", oid, oid
        )
        if result.returncode != 0:
            raise GitError("stale_ref", f"HEAD moved from {oid[:12]}", stderr=result.stderr)

    async def common_dir(self) -> Path:
        """The repository directory shared by all of this repository's worktrees."""
        out = await self._ok("rev-parse", "--path-format=absolute", "--git-common-dir")
        return Path(out.strip())

    # -- worktrees ---------------------------------------------------------

    async def add_worktree(self, path: Path, branch: str) -> None:
        await self.check_branch_name(branch)
        await self._ok("worktree", "add", "--end-of-options", _check_abs_path(path), branch)

    async def list_worktrees(self) -> list[WorktreeEntry]:
        """The worktrees this repository has registered, main checkout first.

        Read from the repository's own administrative files, not from the
        ``.git`` file inside each worktree, which whoever works there can edit.
        """
        out = await self._ok("worktree", "list", "--porcelain", "-z")
        entries: list[WorktreeEntry] = []
        fields: dict[str, str] = {}
        # -z ends every attribute with NUL and every entry with one more.
        for item in out.split("\0"):
            if item:
                key, _, value = item.partition(" ")
                fields[key] = value
            elif fields:
                head = fields.get("HEAD")
                entries.append(
                    WorktreeEntry(
                        path=Path(fields.get("worktree", "")),
                        head=head if head and _OID.fullmatch(head) else None,
                        branch=fields.get("branch"),
                        prunable="prunable" in fields,
                    )
                )
                fields = {}
        return entries

    async def remove_worktree(self, path: Path, *, force: bool = False) -> None:
        flags = ("--force",) if force else ()
        await self._ok("worktree", "remove", *flags, "--end-of-options", _check_abs_path(path))

    async def stage_all(self) -> None:
        await self._ok("add", "--all")

    async def changed_paths(self) -> list[str]:
        """Worktree-relative paths that differ from HEAD, untracked files included.

        ``-z`` keeps names verbatim: no quoting, no escaping of odd characters.
        A rename entry is followed by its source path, which is skipped.
        """
        out = await self._ok("status", "--porcelain", "-z", "--untracked-files=all")
        fields = out.split("\0")
        paths: list[str] = []
        i = 0
        while i < len(fields):
            entry = fields[i]
            i += 1
            if len(entry) < 4:
                continue
            paths.append(entry[3:])
            if entry[0] in "RC":
                i += 1
        return paths

    async def stage_all_except(
        self, excluded: tuple[str, ...], anywhere: tuple[str, ...] = ()
    ) -> None:
        """``add --all`` minus the given top-level directories (pathspec excludes)
        and the ``anywhere`` directories at any depth."""
        specs = [f":(exclude){check_ref_text(name)}" for name in excluded]
        specs += [f":(exclude,glob)**/{check_ref_text(name)}/**" for name in anywhere]
        await self._ok("add", "--all", "--", ".", *specs)

    async def remove_untracked(self, anywhere: tuple[str, ...]) -> None:
        """Delete untracked files under the ``anywhere`` directories at any depth.

        ``clean`` never touches tracked or ignored files and removes a link
        itself, never what it points to.
        """
        specs = [f":(glob)**/{check_ref_text(name)}/**" for name in anywhere]
        await self._ok("clean", "--force", "-d", "--", *specs)

    async def find_commit_with(self, text: str) -> str | None:
        """SHA of the newest commit on HEAD whose message contains ``text`` literally."""
        result = await self._run(
            "log", "--max-count=1", "--fixed-strings", f"--grep={text}", "--pretty=format:%H"
        )
        sha = result.stdout.strip()
        return sha if result.returncode == 0 and sha else None

    async def commit(self, message: str, *, author: tuple[str, str] | None = None) -> str:
        """Commit the index. Signing is off, so no configured signing program runs."""
        await self._ok(
            "commit", "--no-verify", "--no-gpg-sign", f"--message={message}",
            env=_author_env(author),
        )
        return (await self._ok("rev-parse", "HEAD")).strip()

    async def merge(self, ref: str) -> None:
        """Merge ``ref`` into the checked-out branch; aborts and raises on conflict."""
        sha = await self.resolve_commit(ref)
        result = await self._run("merge", "--no-edit", "--end-of-options", sha)
        if result.returncode != 0:
            await self._run("merge", "--abort")
            raise GitError("conflict", f"merge of {ref!r} failed", stderr=result.stderr)

    async def fast_forward(self, sha: str) -> None:
        """Move the checked-out branch and its files forward to ``sha``; never merges."""
        await self._ok("merge", "--ff-only", "--end-of-options", _check_oid(sha))

    async def revert_head(self) -> None:
        result = await self._run("revert", "--no-edit", "HEAD")
        if result.returncode != 0:
            await self._run("revert", "--abort")
            raise GitError("failed", "git revert failed", stderr=result.stderr)

    # -- merge primitives (no working tree involved) -----------------------

    async def merge_tree(self, ours: str, theirs: str) -> MergeTreeResult:
        result = await self._run(
            "merge-tree", "--write-tree", "--name-only", "--no-messages", "-z",
            "--end-of-options", _check_oid(ours), _check_oid(theirs),
        )
        if result.returncode not in (0, 1):
            raise GitError("failed", "git merge-tree failed", stderr=result.stderr)
        tree, *paths = result.stdout.split("\0")
        conflicts = list(dict.fromkeys(p for p in paths if p))
        return MergeTreeResult(_check_oid(tree.strip()), conflicts)

    async def commit_tree(
        self, tree: str, parents: list[str], message: str, *, author: tuple[str, str] | None = None
    ) -> str:
        """Write a commit object for ``tree``. No ref moves; the message goes in on stdin."""
        args = ["commit-tree", "--no-gpg-sign", _check_oid(tree)]
        for parent in parents:
            args += ["-p", _check_oid(parent)]
        return _check_oid((await self._ok(*args, stdin=message, env=_author_env(author))).strip())

    async def merge_into(
        self,
        branch: str,
        source: str,
        expected_head: str,
        message: str,
        *,
        author: tuple[str, str] | None = None,
    ) -> MergeOutcome:
        """Merge ``source`` into ``branch`` without touching any working tree.

        merge-tree --write-tree, then commit-tree, then a compare-and-swap
        update-ref from ``expected_head``. If ``branch`` has moved since the
        caller read ``expected_head``, raises ``GitError("stale_ref")`` and
        nothing changes; the caller decides whether to retry.
        """
        await self.check_branch_name(branch)
        _check_oid(source)
        _check_oid(expected_head)
        if await self.is_ancestor(source, expected_head):
            current = await self.resolve_commit(f"refs/heads/{branch}")
            if current != expected_head:
                raise GitError("stale_ref", f"{branch} moved from {expected_head[:12]}")
            return MergeOutcome("up_to_date", expected_head, [])
        merged = await self.merge_tree(expected_head, source)
        if not merged.clean:
            return MergeOutcome("conflict", None, merged.conflicts)
        commit = await self.commit_tree(merged.tree, [expected_head, source], message, author=author)
        await self.update_branch(branch, commit, expected_head)
        return MergeOutcome("merged", commit, [])
