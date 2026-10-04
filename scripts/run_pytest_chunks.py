#!/usr/bin/env python3
"""Deterministic, sequential, memory-bounded pytest chunk runner (local tool).

Runs selected pytest files as a series of chunks -- one fresh pytest subprocess
per chunk, strictly one at a time -- so a machine where the monolithic test
process hits memory pressure can still verify changes locally. It is a local
verification aid, not a CI orchestrator: CI (`.github/workflows/test.yml`)
remains the authority, and this script never talks to Docker, PostgreSQL,
Azure, or any other service.

Design constraints that are easy to regress and therefore pinned here:

- One child process at a time; the parent waits for each child to exit before
  starting the next. No xdist, no background test processes, no concurrency.
- Child commands are built as argument arrays and never through a shell.
  Arguments that could introduce parallel execution (-n/--numprocesses, xdist
  options, pytest-forked, addopts overrides carrying them) are rejected, and
  the same rules are applied fail-closed to PYTEST_ADDOPTS and to the
  addopts configured in pyproject.toml / pytest.ini / setup.cfg / tox.ini
  (values inspected, never modified; their contents never logged or stored).
- pytest's stdout is streamed through to the caller line by line; only the
  final summary line is parsed. Large output is never buffered whole.
- A failed chunk does not hide later chunks: continuation is the default,
  stop-on-failure is explicit, and every chunk's command/exit code/duration
  and parsed counts land in the completion summary and optional JSON file.
- The suite rewrites data/okrs_database.json. Tracked paths that become dirty
  during the run are reported and named, but never restored: discarding a
  user's uncommitted work automatically is worse than asking them to look.
- PostgreSQL-marked tests (pytestmark = pytest.mark.postgres) are excluded by
  default, using the same derivation as tests/test_ci_postgres_split.py, so
  this runner and the CI split cannot drift apart.

Usage
-----
    python scripts/run_pytest_chunks.py [options] [filters...] [-- pytest args]

    --chunk-size N          files per chunk (default 25)
    --chunks 1,3,7          run only these chunks (1-based, from the partition)
    --include-postgres      include PostgreSQL-marked files in the run
    --postgres-only         run only PostgreSQL-marked files (needs a database;
                            the runner never starts one)
    --stop-on-failure       stop after the first chunk that exits nonzero
    --fail-on-new-dirty     stop when tests newly modify tracked files
    --json PATH             write a JSON summary (refuses to overwrite an
                            existing file unless --overwrite-json)
    --overwrite-json        allow the JSON summary to overwrite its exact path
    --manifest PATH         write a resume manifest (refuses to overwrite an
                            existing one; pass --resume to continue it)
    --resume                resume the manifest at PATH after an interruption
    --rerun-failed          on resume, also rerun chunks that previously failed
    --list                  print the discovery/selection/chunk plan and exit
    --                      everything after this is passed to pytest verbatim

Exit codes follow pytest: 0 when every executed chunk passed, the highest
executed chunk exit code otherwise, and 128+signal when the run was
interrupted (130 on Ctrl+C).
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_CHUNK_SIZE = 25
# Manifests and summaries hold paths and small counters, never test output.
# Anything larger means something went wrong, so refuse to read or write it.
OUTPUT_MAX_BYTES = 32 * 1024 * 1024
# Same derivation as tests/test_ci_postgres_split.py::_postgres_files(). That
# guard proves every file matching this pattern is --ignore'd by the CI backend
# job and run by the postgres job; reusing the pattern is what keeps the local
# runner and CI from drifting apart.
POSTGRES_MARKER_RE = re.compile(r"^pytestmark\s*=.*pytest\.mark\.postgres", re.M)
SUMMARY_LINE_RE = re.compile(r"^(?P<body>.+?)\s+in\s+\d[\d.]*s(?:\s+\([^)]*\))?$")
COUNT_ITEM_RE = re.compile(
    r"(\d+)\s+(passed|failed|skipped|error|errors|warning|warnings|xfailed|xpassed|deselected)"
)
COUNT_ALIASES = {"error": "error", "errors": "error", "warning": "warnings", "warnings": "warnings"}
# Long options that put pytest into parallel/forked/looping modes, by name
# with the leading dashes stripped. "-n" is handled separately below because
# its value may be attached ("-n4").
PARALLEL_OPTION_NAMES = {
    "numprocesses",
    "dist",
    "maxprocesses",
    "maxworkerrestart",
    "max-worker-restart",
    "rsyncdir",
    "rsyncdirs",
    "xdist-rsyncdir",
    "looponfail",
    "forked",
    "fork",
    "workers",
    "tests-per-worker",
}
# pytest merges addopts from the environment and from its configuration
# files, so a parallel mode can arrive without ever touching the command
# line. Both sources are validated with the same deny rules as argv, and
# the raw values are never logged, stored, or echoed -- errors name the
# variable or file, never their contents.
PYTEST_ADDOPTS_ENV_VAR = "PYTEST_ADDOPTS"
PYTEST_ADDOPTS_PARALLEL_ERROR = (
    "PYTEST_ADDOPTS enables or contains a pytest option that introduces "
    "parallel execution (-n/--numprocesses, xdist plugin loading, or an "
    "addopts override); refusing to run"
)
PYTEST_CONFIG_SOURCES = (
    # (file name, kind): pyproject uses [tool.pytest.ini_options]; the ini
    # files use the [pytest] / [tool:pytest] sections pytest actually reads.
    ("pyproject.toml", "pyproject"),
    ("pytest.ini", "pytest"),
    ("setup.cfg", "tool:pytest"),
    ("tox.ini", "pytest"),
)


class RunnerError(Exception):
    """A user-facing configuration or environment problem."""


class SignalInterruptError(Exception):
    """Raised by signal handlers; carries the signal that fired."""

    def __init__(self, signum: int) -> None:
        super().__init__(f"interrupted by signal {signum}")
        self.signum = signum


# --- small validation helpers ------------------------------------------------


def _reject_control_bytes(raw: str, what: str) -> None:
    for ch in ("\x00", "\n", "\r"):
        if ch in raw:
            raise RunnerError(f"{what} contains a forbidden control character (newline or NUL)")


def resolve_inside_repo(root: Path, raw: str, what: str) -> Path:
    """Resolve a requested path and refuse anything that leaves the repository.

    ``Path.resolve()`` follows symlinks, so a link pointing outside the
    repository resolves outside and is refused here.
    """
    _reject_control_bytes(raw, what)
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (ValueError, OSError) as exc:
        raise RunnerError(f"{what} {raw!r} is not inside the repository ({exc})") from exc
    if not resolved.exists():
        raise RunnerError(f"{what} {raw!r} does not exist")
    return resolved


# --- discovery and selection --------------------------------------------------


def discover_test_files(root: Path) -> list[str]:
    """Test files pytest would collect under tests/, lexically sorted.

    Mirrors pytest's default ``test_*.py`` / ``*_test.py`` patterns so a file
    pytest would run is never quietly left out of the plan.
    """
    tests_dir = root / "tests"
    found: set[str] = set()
    for path in tests_dir.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        name = path.name
        if not (name.startswith("test_") or name.endswith("_test.py")):
            continue
        try:
            path.resolve().relative_to(root)
        except (ValueError, OSError):
            continue  # a symlink pointing outside the repo is not a test we can own
        found.add(path.relative_to(root).as_posix())
    return sorted(found)


def postgres_test_files(root: Path, files: list[str]) -> list[str]:
    """The subset of ``files`` carrying the PostgreSQL marker.

    Reads one file at a time and keeps only the boolean result, so memory use
    is bounded by a single file however large the suite grows. An unreadable
    file is fatal: silently treating it as unmarked could let a PostgreSQL
    test into the default run.
    """
    marked = []
    for rel in files:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RunnerError(f"cannot read {rel} to check the PostgreSQL marker: {exc}") from exc
        if POSTGRES_MARKER_RE.search(text):
            marked.append(rel)
    return sorted(marked)


@dataclass
class Selection:
    included: list[str]
    excluded_postgres: list[str]
    discovered_count: int
    postgres_files: list[str]


def select_files(root: Path, filters: list[str], mode: str) -> Selection:
    """Discover, filter, and apply the PostgreSQL selection mode.

    A request that names a file the mode would drop fails loudly instead of
    silently omitting it: an explicitly requested test must either run or stop
    the runner with an explanation.
    """
    discovered = discover_test_files(root)
    pg_files = postgres_test_files(root, discovered)
    pg_set = set(pg_files)

    if not filters:
        # The default run: everything pytest would collect, minus the mode's
        # exclusions. The loudly-refuse checks below only apply to files the
        # user explicitly asked for.
        requested: set[str] = set(discovered)
        explicit = False
    else:
        requested = set()
        for pattern in filters:
            requested.update(_filter_matches(root, discovered, pattern))
        explicit = True

    if mode == "only":
        selected = requested & pg_set
        dropped = sorted(requested - pg_set)
        if explicit and dropped:
            raise RunnerError(
                "--postgres-only was requested but these files are not PostgreSQL-marked: "
                + ", ".join(dropped)
            )
    elif mode == "exclude":
        selected = requested - pg_set
        dropped = sorted(requested & pg_set)
        if explicit and dropped:
            raise RunnerError(
                "these requested files are PostgreSQL-marked and excluded from the default "
                "run; use --include-postgres or --postgres-only to run them: " + ", ".join(dropped)
            )
    else:  # include
        selected = set(requested)

    if explicit:
        missing = sorted(requested - set(discovered))
        if missing:
            raise RunnerError(
                "requested paths are not discoverable test files under tests/: "
                + ", ".join(missing)
            )

    return Selection(
        included=sorted(selected),
        excluded_postgres=sorted(pg_set - selected),
        discovered_count=len(discovered),
        postgres_files=pg_files,
    )


def _filter_matches(root: Path, discovered: list[str], pattern: str) -> set[str]:
    """Resolve one filter (path, directory, or glob) to discovered test files."""
    _reject_control_bytes(pattern, "filter")
    if any(ch in pattern for ch in "*?["):
        glob_pattern = pattern.replace("\\", "/")
        matches = sorted(root.glob(glob_pattern))
        if not matches:
            raise RunnerError(f"filter {pattern!r} matched no files")
        rels = []
        for match in matches:
            if not match.is_file():
                raise RunnerError(f"filter {pattern!r} matched non-file path {match}")
            try:
                resolved_rel = match.resolve().relative_to(root).as_posix()
            except (ValueError, OSError) as exc:
                raise RunnerError(
                    f"filter {pattern!r} matched a symlink escaping the repository: {match}"
                ) from exc
            rels.append(resolved_rel)
        known = set(discovered)
        unknown = [rel for rel in rels if rel not in known]
        if unknown:
            raise RunnerError(
                f"filter {pattern!r} matched files pytest would not collect: {', '.join(unknown)}"
            )
        return set(rels)

    resolved = resolve_inside_repo(root, pattern, "filter")
    if resolved.is_dir():
        prefix = resolved.relative_to(root).as_posix()
        hits = {rel for rel in discovered if rel.startswith(prefix + "/") or rel == prefix}
        if not hits:
            raise RunnerError(f"filter {pattern!r} contains no discoverable test files")
        return hits
    rel = resolved.relative_to(root).as_posix()
    if rel not in set(discovered):
        raise RunnerError(f"filter {pattern!r} is not a discoverable test file under tests/")
    return {rel}


# --- chunking -----------------------------------------------------------------


def partition(files: list[str], chunk_size: int) -> list[list[str]]:
    """Split the sorted file list into exact, non-overlapping chunks."""
    if chunk_size < 1:
        raise RunnerError("--chunk-size must be at least 1")
    return [files[i : i + chunk_size] for i in range(0, len(files), chunk_size)]


def parse_chunk_selection(spec: str, chunk_count: int) -> list[int]:
    """Parse a 1-based chunk list like "2,7"; duplicates are refused."""
    chosen: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part.isdigit():
            raise RunnerError(f"--chunks expects comma-separated integers, got {spec!r}")
        index = int(part)
        if not 1 <= index <= chunk_count:
            raise RunnerError(f"chunk {index} is outside 1..{chunk_count}")
        if index in chosen:
            raise RunnerError(f"chunk {index} selected twice in --chunks")
        chosen.append(index)
    return sorted(chosen)


# --- pytest argument safety ---------------------------------------------------


def _reject_ini_override(token: str, value: str) -> None:
    """Refuse -o/--override-ini values that smuggle parallel execution in."""
    lowered = value.lower()
    smuggled = "xdist" in lowered or "numprocesses" in lowered
    if smuggled or re.search(r"(^|[\s=])-n([\s=]|$)", lowered):
        raise RunnerError(f"parallel execution argument rejected: {token} {value!r}")


def validate_extra_args(args: list[str]) -> None:
    """Reject pytest arguments that would break sequential execution.

    Everything is treated as a literal argument; nothing is evaluated. The
    deny list covers xdist (--dist, -n/--numprocesses, --maxprocesses, ...),
    pytest-forked, pytest-parallel, loop-on-fail, and addopts/ini overrides
    that try to smuggle the same in. "-p no:xdist" is rejected too -- turning
    a plugin off is not worth the risk of "-p xdist" passing the same check.
    """
    for position, token in enumerate(args):
        _reject_control_bytes(token, "pytest argument")
        lowered = token.lower()
        if "xdist" in lowered:
            raise RunnerError(f"parallel execution argument rejected: {token!r}")
        if token.startswith("-n") and not token.startswith("--"):
            raise RunnerError(
                f"parallel execution argument rejected: {token!r} (-n/--numprocesses)"
            )
        if token.startswith("-"):
            body = token.lstrip("-")
            name, eq, value = body.partition("=")
            if name.lower() in PARALLEL_OPTION_NAMES:
                raise RunnerError(f"parallel execution argument rejected: {token!r}")
            # -p/-o may carry their value as the next argv entry (-p xdist,
            # -o addopts=-n 4); the deny check must look at that value too.
            if not eq and name.lower() == "p" and position + 1 < len(args):
                if "xdist" in args[position + 1].lower():
                    raise RunnerError(
                        f"parallel execution argument rejected: {token} {args[position + 1]!r}"
                    )
            if not eq and name.lower() in ("o", "override-ini") and position + 1 < len(args):
                _reject_ini_override(token, args[position + 1])
            if eq and name.lower() in ("o", "override-ini"):
                _reject_ini_override(token, value)


def build_command(interpreter: str, files: list[str], extra_args: list[str]) -> list[str]:
    """The chunk's pytest invocation as an argument array (never a shell string)."""
    return [interpreter, "-m", "pytest", *files, *extra_args]


def validate_pytest_addopts_env(env_value: str | None) -> None:
    """Fail closed on a PYTEST_ADDOPTS that could enable parallel execution.

    pytest merges this environment variable into every run's arguments, so
    ``PYTEST_ADDOPTS="-n auto"`` would silently start a parallel run even
    though the command line is clean. The value is parsed with
    ``shlex.split`` -- the exact parsing pytest itself applies -- and then
    checked with the same rules as argv. Quoting errors are refused rather
    than guessed at. The raw value is never logged, stored, or echoed:
    errors name the variable, never its contents.
    """
    if env_value is None or not env_value.strip():
        return
    try:
        tokens = shlex.split(env_value)
    except ValueError:
        raise RunnerError(
            f"{PYTEST_ADDOPTS_ENV_VAR} is malformed (unbalanced quoting or an "
            "incomplete escape); refusing to run. Fix or unset it and retry."
        ) from None
    try:
        validate_extra_args(tokens)
    except RunnerError:
        raise RunnerError(PYTEST_ADDOPTS_PARALLEL_ERROR) from None


def configured_pytest_addopts(root: Path) -> list[tuple[str, str]]:
    """addopts values from the repository's pytest configuration sources.

    Read-only: the files are inspected, never modified, and children keep
    receiving their settings -- a safe addopts continues to apply. Sources
    that pytest does not read (or that do not exist) are skipped. A source
    that cannot be parsed is refused, since an unparseable configuration
    cannot be proven safe.
    """
    found: list[tuple[str, str]] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
            raise RunnerError(
                "pyproject.toml cannot be parsed to validate its pytest addopts; "
                "refusing to run"
            ) from None
        value = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("addopts")
        if isinstance(value, list):
            # TOML array form: validate every entry by joining conservatively.
            value = " ".join(str(item) for item in value)
        elif value is not None:
            value = str(value)
        if value:
            found.append(("pyproject.toml", value))
    for name, section in PYTEST_CONFIG_SOURCES[1:]:
        path = root / name
        if not path.is_file():
            continue
        parser = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            parser.read(path, encoding="utf-8-sig")
        except configparser.Error:
            raise RunnerError(
                f"{name} cannot be parsed to validate its pytest addopts; refusing to run"
            ) from None
        if parser.has_option(section, "addopts"):
            found.append((name, parser.get(section, "addopts")))
    return found


def validate_pytest_config_sources(root: Path) -> None:
    """Refuse runs whose repository pytest configuration enables parallel mode.

    Same deny rules as the command line and the environment, applied to every
    configured addopts value. Errors name the file, never the value.
    """
    for source, value in configured_pytest_addopts(root):
        try:
            validate_extra_args(shlex.split(value))
        except (ValueError, RunnerError):
            raise RunnerError(
                f"{source} configures pytest addopts that enable parallel execution "
                "(-n/--numprocesses, xdist plugin loading, or an addopts override); "
                "refusing to run"
            ) from None


def display_command(cmd: list[str]) -> str:
    """A printable form of the command with the machine-local interpreter path
    replaced by a fixed name, so summaries stay free of absolute paths."""
    shown = ["python" if i == 0 else part for i, part in enumerate(cmd)]
    return json.dumps(shown)


# --- output parsing -----------------------------------------------------------


def parse_summary_line(line: str) -> dict[str, int] | None:
    """Parse pytest's final '= N passed, ... in Xs =' line, or return None.

    Handles both the wrapped default form and the bare ``-q`` form; the last
    matching line in the output wins, which is pytest's summary.
    """
    text = line.strip().strip("=").strip()
    match = SUMMARY_LINE_RE.match(text)
    if match is None:
        return None
    body = match.group("body")
    if body.startswith("no tests"):
        return {}
    counts: dict[str, int] = {}
    for number, word in COUNT_ITEM_RE.findall(body):
        counts[COUNT_ALIASES.get(word, word)] = int(number)
    return counts


def format_counts(counts: dict[str, int] | None) -> str:
    if counts is None:
        return "no summary line parsed"
    parts = [
        f"{counts.get(key, 0)} {label}"
        for key, label in (
            ("passed", "passed"),
            ("failed", "failed"),
            ("error", "errors"),
            ("skipped", "skipped"),
        )
    ]
    for key in ("xfailed", "xpassed", "warnings", "deselected"):
        if counts.get(key):
            parts.append(f"{counts[key]} {key}")
    return ", ".join(parts)


# --- git helpers (read-only; the runner never resets, cleans, or restores) ----


def git_toplevel(root_hint: Path) -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root_hint,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RunnerError("run_pytest_chunks must run inside a git repository checkout")
    return Path(proc.stdout.strip()).resolve()


def git_head_commit(root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def git_dirty_paths(root: Path) -> list[str]:
    """Tracked paths with index or worktree changes, repo-relative, sorted.

    Untracked files are deliberately excluded: the runner reports tests
    rewriting tracked files, not the user's scratch files.
    """
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    records = proc.stdout.split(b"\x00")
    paths: set[str] = set()
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4:
            continue
        status, path = record[:2], record[3:]
        paths.add(path.decode("utf-8", "replace"))
        if status[:1] in (b"R", b"C") and index < len(records):
            paths.add(records[index].decode("utf-8", "replace"))
            index += 1
    return sorted(paths)


def pytest_version_string() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    first = proc.stdout.splitlines()[0].strip() if proc.stdout.splitlines() else ""
    return first or "unknown"


# --- output files --------------------------------------------------------------


def resolve_output_path(root: Path, raw: str, what: str) -> Path:
    """Validate a summary/manifest path without requiring it to exist yet."""
    _reject_control_bytes(raw, what)
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    nominal = Path(os.path.normpath(str(path)))
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise RunnerError(f"{what} {raw!r} cannot be resolved ({exc})") from exc
    nominal_inside = _is_at_or_under(root, nominal)
    if nominal_inside and not _is_at_or_under(root, resolved):
        raise RunnerError(f"{what} {raw!r} is a symlink escaping the repository")
    if resolved.is_dir():
        raise RunnerError(f"{what} {raw!r} points at a directory")
    if resolved.parent != resolved and not resolved.parent.exists():
        raise RunnerError(f"{what} {raw!r} has a nonexistent parent directory")
    return resolved


def _is_at_or_under(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def guard_against_repo_file(root: Path, resolved: Path, what: str, overwrite: bool) -> None:
    """Refuse to point a summary or manifest at repository content.

    Without this, a mistyped ``--json tests/test_budget.py`` would silently
    destroy a test file. Any ``.py`` file inside the repository is refused
    outright (tracked or not -- an untracked file may be someone's work in
    progress), as is any tracked file of any kind. Overwriting needs the
    explicit overwrite option and then only ever touches that one exact path.
    """
    if not _is_at_or_under(root, resolved):
        return
    rel = resolved.relative_to(root).as_posix()
    if resolved.suffix == ".py" and not overwrite:
        raise RunnerError(
            f"{what} {rel} is a Python file inside the repository; pass the explicit "
            "overwrite option to replace it"
        )
    proc = subprocess.run(
        ["git", "ls-files", "--", rel],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    if proc.stdout.strip() and not overwrite:
        raise RunnerError(
            f"{what} {rel} is a tracked repository file; pass the explicit overwrite "
            "option to replace it"
        )


def exclusive_write(path: Path, payload: str, overwrite: bool, max_bytes: int) -> None:
    """Create the output file exclusively unless overwriting was requested."""
    data = payload.encode("utf-8")
    if len(data) > max_bytes:
        raise RunnerError(f"refusing to write {path}: payload exceeds {max_bytes} bytes")
    if overwrite:
        # Truncate exactly this file; no cleanup command ever runs first.
        with open(path, "wb") as handle:
            handle.write(data)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        handle = os.open(path, flags)
    except FileExistsError as exc:
        raise RunnerError(
            f"{path} already exists; pass the explicit overwrite option to replace it"
        ) from exc
    with os.fdopen(handle, "wb") as opened:
        opened.write(data)


def atomic_write(path: Path, payload: str, max_bytes: int) -> None:
    """Replace the manifest via a temp file in the same directory + rename."""
    data = payload.encode("utf-8")
    if len(data) > max_bytes:
        raise RunnerError(f"refusing to write {path}: payload exceeds {max_bytes} bytes")
    handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as opened:
            opened.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_json_file(path: Path, what: str) -> dict:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise RunnerError(f"{what} {path.name} cannot be read: {exc}") from exc
    if size > OUTPUT_MAX_BYTES:
        raise RunnerError(f"{what} {path.name} is too large to be a runner file ({size} bytes)")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RunnerError(f"{what} {path.name} is not valid JSON: {exc}") from exc


# --- chunk execution -----------------------------------------------------------


@dataclass
class ChunkResult:
    exit_code: int | None
    duration_seconds: float
    counts: dict[str, int] | None = None
    interrupted_by_signal: int | None = None
    error: str | None = None


@dataclass
class ChunkRecord:
    index: int
    files: list[str]
    status: str = "pending"  # pending|completed|interrupted|not-run|not-selected
    exit_code: int | None = None
    duration_seconds: float | None = None
    counts: dict[str, int] | None = None
    interrupted_by_signal: int | None = None
    error: str | None = None
    rerun: bool = False

    def to_json(self) -> dict:
        return {
            "index": self.index,
            "files": list(self.files),
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "counts": self.counts,
            "interrupted_by_signal": self.interrupted_by_signal,
            "error": self.error,
            "rerun": self.rerun,
        }

    @classmethod
    def from_json(cls, data: dict) -> ChunkRecord:
        try:
            return cls(
                index=int(data["index"]),
                files=[str(f) for f in data["files"]],
                status=str(data["status"]),
                exit_code=data["exit_code"],
                duration_seconds=data["duration_seconds"],
                counts=data["counts"],
                interrupted_by_signal=data["interrupted_by_signal"],
                error=data["error"],
                rerun=bool(data.get("rerun", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RunnerError(f"manifest chunk entry is malformed: {exc}") from exc


def forward_termination(proc: subprocess.Popen) -> None:
    """Terminate the active child and wait for it; nothing else is touched."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def run_one_chunk(cmd: list[str], root: Path) -> ChunkResult:
    """Run one chunk as a child pytest, streaming its output line by line.

    Only the current line is held in memory; every line is written straight
    through and the final summary line is parsed in place, so the parent never
    accumulates the child's output just to parse it.
    """
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ChunkResult(
            exit_code=3, duration_seconds=time.monotonic() - started, error="launch-failed"
        )
    counts: dict[str, int] | None = None
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            parsed = parse_summary_line(line)
            if parsed is not None:
                counts = parsed
        exit_code = proc.wait()
    except (SignalInterruptError, KeyboardInterrupt) as exc:
        forward_termination(proc)
        signum = exc.signum if isinstance(exc, SignalInterruptError) else signal.SIGINT
        return ChunkResult(
            exit_code=proc.returncode,
            duration_seconds=time.monotonic() - started,
            counts=counts,
            interrupted_by_signal=signum,
        )
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
    return ChunkResult(
        exit_code=exit_code, duration_seconds=time.monotonic() - started, counts=counts
    )


# --- manifest -------------------------------------------------------------------


def manifest_payload(
    *, commit: str, postgres_mode: str, filters: list[str], chunk_size: int,
    pytest_args: list[str], files: list[str], chunks: list[ChunkRecord],
    selected: list[int] | None, state: str, starting_dirty: list[str],
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "repo_commit": commit,
        "postgres_mode": postgres_mode,
        "filters": list(filters),
        "chunk_size": chunk_size,
        "pytest_args": list(pytest_args),
        "files": list(files),
        "chunks": [record.to_json() for record in chunks],
        "selected_chunks": selected,
        "state": state,
        "starting_dirty_paths": list(starting_dirty),
    }


def save_manifest(path: Path, payload: dict) -> None:
    atomic_write(path, json.dumps(payload, indent=2) + "\n", OUTPUT_MAX_BYTES)


# --- the run --------------------------------------------------------------------


@dataclass
class Plan:
    root: Path
    commit: str
    files: list[str]
    postgres_mode: str
    filters: list[str]
    chunk_size: int
    pytest_args: list[str]
    chunks: list[list[str]]
    selected: list[int] | None  # 1-based chunk numbers, ascending; None = all
    stop_on_failure: bool
    fail_on_new_dirty: bool
    rerun_failed: bool
    resuming: bool


@dataclass
class RunOutcome:
    records: list[ChunkRecord]
    interrupted_signum: int | None = None
    stopped_on_failure_at: int | None = None
    new_dirty_paths: list[str] = field(default_factory=list)
    dirty_before: list[str] = field(default_factory=list)
    dirty_after: list[str] = field(default_factory=list)


def execute_plan(
    plan: Plan, records: list[ChunkRecord], launch, dirty_snapshot, on_progress=None
) -> RunOutcome:
    """Run the selected chunks strictly one at a time.

    ``launch(cmd, root)`` and ``dirty_snapshot()`` are injectable so the unit
    tests never spawn real pytest processes. ``dirty_snapshot`` is called after
    every chunk to catch tests that rewrite tracked files; ``on_progress`` is
    called after every record change so the manifest on disk always reflects
    the latest completed chunk.
    """
    outcome = RunOutcome(records=records, dirty_before=dirty_snapshot())
    total = len(plan.chunks)
    selected = plan.selected or list(range(1, total + 1))
    dirty_seen: set[str] = set(outcome.dirty_before)
    stopped = False

    def touch(record: ChunkRecord) -> None:
        if on_progress is not None:
            on_progress(records, outcome)

    for record in records:
        if record.index not in selected:
            if record.status == "pending":
                record.status = "not-selected"
                touch(record)
            continue
        if plan.resuming:
            if record.status == "completed" and (record.exit_code or 0) == 0:
                continue  # resume never repeats a passing chunk
            if (
                record.status == "completed"
                and (record.exit_code or 0) != 0
                and not plan.rerun_failed
            ):
                # A previously failed chunk counts as completed only when the
                # user explicitly chose not to rerun failed chunks.
                continue
            if record.status == "not-selected":
                continue
            if record.status == "completed":
                record.rerun = True
        if stopped:
            record.status = "not-run"
            touch(record)
            continue

        ordinal = f"{record.index:02d}/{total:02d}"
        print(f"Chunk {ordinal}: {len(record.files)} files")
        command = build_command(sys.executable, record.files, plan.pytest_args)
        print(f"Command: {display_command(command)}")
        result = launch(command, plan.root)
        record.exit_code = result.exit_code
        record.duration_seconds = result.duration_seconds
        record.counts = result.counts
        record.error = result.error

        newly_dirty = [p for p in dirty_snapshot() if p not in dirty_seen]
        dirty_seen.update(newly_dirty)
        if newly_dirty:
            print(f"Newly modified tracked paths after chunk {record.index}:")
            for path in newly_dirty:
                print(f"  {path}")
            outcome.new_dirty_paths.extend(newly_dirty)

        if result.interrupted_by_signal is not None:
            record.status = "interrupted"
            record.interrupted_by_signal = result.interrupted_by_signal
            outcome.interrupted_signum = result.interrupted_by_signal
            touch(record)
            return outcome

        record.status = "completed"
        touch(record)

        if (result.exit_code or 0) != 0 and plan.stop_on_failure:
            outcome.stopped_on_failure_at = record.index
            stopped = True
        elif plan.fail_on_new_dirty and newly_dirty:
            outcome.stopped_on_failure_at = record.index
            stopped = True

    outcome.dirty_after = sorted(dirty_seen)
    return outcome


def summarize(records: list[ChunkRecord]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in records:
        for key, value in (record.counts or {}).items():
            totals[key] = totals.get(key, 0) + value
    return totals


def final_exit_code(outcome: RunOutcome) -> int:
    if outcome.interrupted_signum is not None:
        return 128 + outcome.interrupted_signum
    codes = [record.exit_code for record in outcome.records if record.status == "completed"]
    nonzero = [code for code in codes if code]
    if nonzero:
        return max(nonzero)
    if outcome.stopped_on_failure_at is not None:
        return 1
    return 0


def print_completion_summary(
    plan: Plan, selection: Selection, outcome: RunOutcome, exit_code: int
) -> None:
    total = len(plan.chunks)
    executed = [r for r in outcome.records if r.status in ("completed", "interrupted")]
    interrupted = [r for r in outcome.records if r.status == "interrupted"]
    not_run = [r for r in outcome.records if r.status in ("not-run", "not-selected")]
    print("\n=== pytest chunk run summary ===")
    print(f"Commit: {plan.commit}")
    state_label = "clean" if not outcome.dirty_before else "dirty (tracked changes present)"
    print(f"Starting state: {state_label}")
    print(f"Discovered test files: {selection.discovered_count}")
    print(f"Included: {len(selection.included)}")
    print(f"Excluded PostgreSQL files: {len(selection.excluded_postgres)}")
    for path in selection.excluded_postgres:
        print(f"  excluded: {path}")
    print(f"Chunks: {total}")
    for record in outcome.records:
        print(f"Chunk {record.index:02d}: {', '.join(record.files)}")
    for record in executed:
        command = build_command(sys.executable, record.files, plan.pytest_args)
        print(
            f"Chunk {record.index:02d}: exit={record.exit_code} in {record.duration_seconds:.2f}s"
        )
        print(f"  command: {display_command(command)}")
        print(f"  result: {format_counts(record.counts)}")
    totals = summarize(outcome.records)
    print(f"Totals: {format_counts(totals)}")
    for record in interrupted:
        print(f"Interrupted: chunk {record.index:02d} (signal {record.interrupted_by_signal})")
    if outcome.stopped_on_failure_at is not None:
        print(
            f"Stopped at chunk {outcome.stopped_on_failure_at:02d} (stop-on-failure or new-dirty)"
        )
    if not_run:
        print("Chunks not run: " + ", ".join(f"{r.index:02d}" for r in not_run))
    if outcome.dirty_before:
        print("Dirty before the run (distinguished from test-made changes; not touched):")
        for path in outcome.dirty_before:
            print(f"  pre-existing: {path}")
    if outcome.new_dirty_paths:
        print("Tracked paths newly modified during the run (never restored automatically):")
        for path in outcome.new_dirty_paths:
            print(f"  new: {path}")
    else:
        print("Tracked paths newly modified during the run: none")
    if outcome.interrupted_signum is not None:
        print(f"Overall: interrupted by signal {outcome.interrupted_signum} (exit {exit_code})")
    elif exit_code == 0:
        print("Overall: passed")
    else:
        print(f"Overall: failed (exit {exit_code})")


def build_json_summary(
    plan: Plan, selection: Selection, outcome: RunOutcome, exit_code: int
) -> dict:
    totals = summarize(outcome.records)
    state = "interrupted" if outcome.interrupted_signum is not None else "completed"
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "run_pytest_chunks",
        "repo_commit": plan.commit,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "pytest_version": pytest_version_string(),
        "postgres_mode": plan.postgres_mode,
        "filters": list(plan.filters),
        "chunk_size": plan.chunk_size,
        "pytest_args": list(plan.pytest_args),
        "discovered_file_count": selection.discovered_count,
        "included_files": list(selection.included),
        "excluded_postgres_files": list(selection.excluded_postgres),
        "started_clean": not outcome.dirty_before,
        "dirty_before_paths": list(outcome.dirty_before),
        "dirty_after_paths": list(outcome.dirty_after),
        "newly_dirtied_paths": list(outcome.new_dirty_paths),
        "chunks": [record.to_json() for record in outcome.records],
        "totals": totals,
        "exit_code": exit_code,
        "state": state,
    }


# --- resume validation -----------------------------------------------------------


def load_manifest_for_resume(
    path: Path, plan: Plan, selection: Selection
) -> list[ChunkRecord]:
    data = read_json_file(path, "manifest")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RunnerError(
            f"manifest schema version {data.get('schema_version')!r} is not supported "
            f"(expected {SCHEMA_VERSION})"
        )

    def mismatch(field: str) -> RunnerError:
        return RunnerError(f"resume refused: manifest {field} does not match this run")

    if data.get("repo_commit") != plan.commit:
        raise mismatch("repository commit")
    if data.get("postgres_mode") != plan.postgres_mode:
        raise mismatch("PostgreSQL selection mode")
    if data.get("filters") != list(plan.filters):
        raise mismatch("filters")
    if data.get("chunk_size") != plan.chunk_size:
        raise mismatch("chunk size")
    if data.get("pytest_args") != list(plan.pytest_args):
        raise mismatch("pytest arguments")
    if data.get("selected_chunks") != plan.selected:
        raise mismatch("selected chunks")
    if data.get("files") != list(selection.included):
        raise mismatch("selected file list")
    stored = [ChunkRecord.from_json(entry) for entry in data.get("chunks", [])]
    if [record.files for record in stored] != plan.chunks:
        raise mismatch("chunk membership")
    return stored


# --- CLI -------------------------------------------------------------------------


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    if "--" in argv:
        split = argv.index("--")
        argv, extra_args = argv[:split], argv[split + 1 :]
    else:
        extra_args = []
    parser = argparse.ArgumentParser(
        prog="run_pytest_chunks.py",
        description="Run selected pytest files in deterministic, memory-bounded chunks.",
    )
    parser.add_argument("filters", nargs="*", help="paths, directories, or globs under tests/")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunks", type=str, default=None, help="1-based chunk numbers, e.g. 2,7")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--include-postgres", action="store_true")
    mode.add_argument("--postgres-only", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--fail-on-new-dirty", action="store_true")
    parser.add_argument("--json", type=str, default=None)
    parser.add_argument("--overwrite-json", action="store_true")
    parser.add_argument("--manifest", type=str, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rerun-failed", action="store_true")
    parser.add_argument("--list", action="store_true", help="print the plan and exit")
    args = parser.parse_args(argv)
    if args.resume and not args.manifest:
        raise RunnerError("--resume requires --manifest PATH")
    if args.chunk_size < 1:
        raise RunnerError("--chunk-size must be at least 1")
    return args, extra_args


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args, extra_args = parse_args(argv)
        validate_extra_args(extra_args)
        # Environment and repository configuration are checked before anything
        # runs: a parallel mode arriving through either would defeat the
        # one-process-at-a-time guarantee without ever appearing on argv.
        validate_pytest_addopts_env(os.environ.get(PYTEST_ADDOPTS_ENV_VAR))
        script_root = Path(__file__).resolve().parent.parent
        root = git_toplevel(script_root)
        commit = git_head_commit(root)
        validate_pytest_config_sources(root)
        mode = "only" if args.postgres_only else ("include" if args.include_postgres else "exclude")
        selection = select_files(root, args.filters, mode)
        chunks = partition(selection.included, args.chunk_size)
        selected = parse_chunk_selection(args.chunks, len(chunks)) if args.chunks else None

        json_path = manifest_path = None
        if args.json:
            json_path = resolve_output_path(root, args.json, "JSON summary path")
            guard_against_repo_file(root, json_path, "JSON summary path", args.overwrite_json)
            if json_path.exists() and not args.overwrite_json:
                raise RunnerError(
                    f"{json_path} already exists; pass --overwrite-json to replace it"
                )
        if args.manifest:
            manifest_path = resolve_output_path(root, args.manifest, "manifest path")
            guard_against_repo_file(root, manifest_path, "manifest path", False)
            if manifest_path.exists() and not args.resume:
                raise RunnerError(f"{manifest_path} already exists; pass --resume to continue it")
            if args.resume and not manifest_path.exists():
                raise RunnerError(f"cannot resume: {manifest_path} does not exist")

        plan = Plan(
            root=root,
            commit=commit,
            files=selection.included,
            postgres_mode=mode,
            filters=args.filters,
            chunk_size=args.chunk_size,
            pytest_args=extra_args,
            chunks=chunks,
            selected=selected,
            stop_on_failure=args.stop_on_failure,
            fail_on_new_dirty=args.fail_on_new_dirty,
            rerun_failed=args.rerun_failed,
            resuming=args.resume,
        )

        if args.list:
            print_plan(plan, selection)
            return 0

        if not selection.included:
            raise RunnerError("no test files selected; nothing to run")

        print(f"Repository commit: {commit}")
        print(f"Discovered {selection.discovered_count} test files under tests/")
        print(
            f"Included {len(selection.included)} file(s); "
            f"PostgreSQL-marked in the suite: {len(selection.postgres_files)}"
        )
        print(f"Excluded from this run: {len(selection.excluded_postgres)}")
        for path in selection.excluded_postgres:
            print(f"  excluded: {path}")
        if mode == "only":
            print(
                "PostgreSQL-only mode: these tests need an external PostgreSQL database; "
                "the runner never starts one."
            )

        if args.resume:
            records = load_manifest_for_resume(manifest_path, plan, selection)
        else:
            records = [
                ChunkRecord(index=number, files=files)
                for number, files in enumerate(chunks, start=1)
            ]
            if manifest_path is not None:
                save_manifest(
                    manifest_path,
                    manifest_payload(
                        commit=commit,
                        postgres_mode=mode,
                        filters=args.filters,
                        chunk_size=args.chunk_size,
                        pytest_args=extra_args,
                        files=selection.included,
                        chunks=records,
                        selected=selected,
                        state="running",
                        starting_dirty=git_dirty_paths(root),
                    ),
                )
    except RunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    def dirty_snapshot() -> list[str]:
        return git_dirty_paths(root)

    def manifest_progress(records_now: list[ChunkRecord], _outcome: RunOutcome) -> None:
        # After every chunk the manifest on disk reflects the run so far, so an
        # interruption anywhere leaves a resumable record.
        if manifest_path is None:
            return
        save_manifest(
            manifest_path,
            manifest_payload(
                commit=commit,
                postgres_mode=mode,
                filters=args.filters,
                chunk_size=args.chunk_size,
                pytest_args=extra_args,
                files=selection.included,
                chunks=records_now,
                selected=selected,
                state="running",
                starting_dirty=starting_dirty,
            ),
        )

    handlers = _install_signal_handlers()
    try:
        starting_dirty = git_dirty_paths(root)
        try:
            outcome = execute_plan(plan, records, run_one_chunk, dirty_snapshot, manifest_progress)
        except (SignalInterruptError, KeyboardInterrupt) as exc:
            signum = exc.signum if isinstance(exc, SignalInterruptError) else signal.SIGINT
            outcome = RunOutcome(
                records=records,
                interrupted_signum=signum,
                dirty_before=starting_dirty,
                dirty_after=git_dirty_paths(root),
            )
    finally:
        _restore_signal_handlers(handlers)

    outcome.dirty_before = starting_dirty
    exit_code = final_exit_code(outcome)
    print_completion_summary(plan, selection, outcome, exit_code)
    if manifest_path is not None:
        state = "interrupted" if outcome.interrupted_signum else "completed"
        payload = manifest_payload(
            commit=commit,
            postgres_mode=mode,
            filters=args.filters,
            chunk_size=args.chunk_size,
            pytest_args=extra_args,
            files=selection.included,
            chunks=records,
            selected=selected,
            state=state,
            starting_dirty=starting_dirty,
        )
        save_manifest(manifest_path, payload)
    if json_path is not None:
        summary = build_json_summary(plan, selection, outcome, exit_code)
        exclusive_write(
            json_path,
            json.dumps(summary, indent=2) + "\n",
            args.overwrite_json,
            OUTPUT_MAX_BYTES,
        )
    return exit_code


def print_plan(plan: Plan, selection: Selection) -> None:
    total = len(plan.chunks)
    print(
        f"Discovered {selection.discovered_count} test files; "
        f"PostgreSQL-marked: {len(selection.postgres_files)}"
    )
    print(
        f"Included {len(selection.included)}; "
        f"excluded PostgreSQL files: {len(selection.excluded_postgres)}"
    )
    for path in selection.excluded_postgres:
        print(f"  excluded: {path}")
    selected = plan.selected or list(range(1, total + 1))
    print(f"Chunks to run: {len(selected)} of {total}")
    for number, files in enumerate(plan.chunks, start=1):
        marker = "*" if number in selected else " "
        print(f"{marker} chunk {number:02d}: {', '.join(files)}")


def _install_signal_handlers() -> dict:
    handlers: dict = {}
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue

        def raise_interrupt(signum, frame, _sig=sig):
            raise SignalInterruptError(_sig)

        try:
            previous = signal.signal(sig, raise_interrupt)
            handlers[sig] = previous
        except (ValueError, OSError):
            continue
    return handlers


def _restore_signal_handlers(handlers: dict) -> None:
    for sig, previous in handlers.items():
        try:
            signal.signal(sig, previous)
        except (ValueError, OSError):
            pass


if __name__ == "__main__":
    sys.exit(main())
