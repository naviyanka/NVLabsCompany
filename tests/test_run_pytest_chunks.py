"""Tests for the local pytest chunk runner (scripts/run_pytest_chunks.py).

The runner exists so a machine where one monolithic pytest process hits memory
pressure can still verify changes. Its dangerous edges are pinned here with a
fake repository tree and an injected launcher, so no test in this file runs the
real suite, starts PostgreSQL, or needs any external service:

- discovery and partitioning are exact (no file lost, none duplicated);
- the PostgreSQL exclusion agrees with the CI workflow split;
- parallel-execution pytest arguments are refused;
- children run strictly sequentially through argument arrays (never a shell);
- a failed chunk neither hides later chunks nor becomes a passing summary;
- interruption leaves a resumable manifest, and resume refuses silently
  changed inputs (commit, file list, pytest arguments);
- tracked files the tests modify are reported and never restored;
- summaries and manifests cannot clobber repository source files.

One guard parses the real CI workflow read-only to prove the runner and CI
agree; everything else works inside ``tmp_path``.
"""

import ast
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "run_pytest_chunks.py"
FAKE_COMMIT = "a" * 40

JSON_KEYS = {
    "schema_version",
    "tool",
    "repo_commit",
    "python_version",
    "pytest_version",
    "postgres_mode",
    "filters",
    "chunk_size",
    "pytest_args",
    "discovered_file_count",
    "included_files",
    "excluded_postgres_files",
    "started_clean",
    "dirty_before_paths",
    "dirty_after_paths",
    "newly_dirtied_paths",
    "chunks",
    "totals",
    "exit_code",
    "state",
}
MANIFEST_KEYS = {
    "schema_version",
    "repo_commit",
    "postgres_mode",
    "filters",
    "chunk_size",
    "pytest_args",
    "files",
    "chunks",
    "selected_chunks",
    "state",
    "starting_dirty_paths",
}
CHUNK_RECORD_KEYS = {
    "index",
    "files",
    "status",
    "exit_code",
    "duration_seconds",
    "counts",
    "interrupted_by_signal",
    "error",
    "rerun",
}


def _load_runner():
    """Import scripts/run_pytest_chunks.py by path (scripts/ is not a package).

    The module must be registered in sys.modules before exec_module: its
    dataclass annotations are strings under `from __future__ import
    annotations`, and dataclasses resolves them through sys.modules.
    """
    spec = importlib.util.spec_from_file_location("run_pytest_chunks", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_pytest_chunks"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rc():
    return _load_runner()


# --- helpers -----------------------------------------------------------------


def make_repo(tmp_path, plain=(), marked=(), extra_files=None):
    """A fake repository: tests/ with plain and PostgreSQL-marked test files."""
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    for name in plain:
        path = root / "tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    for name in marked:
        path = root / "tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "import pytest\n\npytestmark = pytest.mark.postgres\n\n\ndef test_pg():\n"
            "    assert True\n",
            encoding="utf-8",
        )
    for rel, content in (extra_files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def init_git_repo(root):
    """Make the fake root a real (tiny) git repo so tracked-file guards work.

    Only tests/ is tracked: a manifest or summary in the repo root stays
    untracked, which is how a real user's runner output files look.
    """
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "tests"], cwd=root, check=True)
    return root


def make_plan(rc, root, files, **overrides):
    chunk_size = overrides.pop("chunk_size", 1)
    defaults = dict(
        root=root,
        commit=FAKE_COMMIT,
        files=files,
        postgres_mode="exclude",
        filters=[],
        chunk_size=chunk_size,
        pytest_args=[],
        chunks=rc.partition(files, chunk_size),
        selected=None,
        stop_on_failure=False,
        fail_on_new_dirty=False,
        rerun_failed=False,
        resuming=False,
    )
    defaults.update(overrides)
    return rc.Plan(**defaults)


def fresh_records(rc, plan):
    return [rc.ChunkRecord(index=i, files=files) for i, files in enumerate(plan.chunks, start=1)]


def ok(rc, exit_code=0, counts=None):
    return rc.ChunkResult(
        exit_code=exit_code,
        duration_seconds=0.01,
        counts=counts if counts is not None else {"passed": 2, "skipped": 1},
    )


def interrupted(rc, signum):
    """The ChunkResult run_one_chunk returns when a signal hits the child."""
    return rc.ChunkResult(
        exit_code=None, duration_seconds=0.5, counts=None, interrupted_by_signal=signum
    )


class FakeLaunch:
    """Injectable launcher: records commands, replays canned results.

    Results are ChunkResult objects; an Exception result is raised instead,
    which simulates a signal arriving between chunks (main() catches that).
    """

    def __init__(self, *results):
        self.calls = []
        self.results = list(results)

    def __call__(self, cmd, root):
        self.calls.append(list(cmd))
        if not self.results:
            raise AssertionError("unexpected extra chunk launch")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def run_cli(monkeypatch, rc, root, argv, launch, dirty=None, commit=FAKE_COMMIT):
    """Run rc.main() against a fake repository with fake git answers."""
    init_git_repo(root)
    monkeypatch.setattr(rc, "git_toplevel", lambda hint: root)
    monkeypatch.setattr(rc, "git_head_commit", lambda repo_root: commit)
    monkeypatch.setattr(
        rc, "git_dirty_paths", dirty if dirty is not None else (lambda repo_root: [])
    )
    monkeypatch.setattr(rc, "pytest_version_string", lambda: "pytest 9.0.0 (fake)")
    monkeypatch.setattr(rc, "run_one_chunk", launch)
    return rc.main(argv)


def read_manifest(root):
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


# --- discovery ---------------------------------------------------------------


def test_discovery_is_lexically_sorted_and_complete(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_c.py", "test_a.py", "sub/test_b.py"])
    (root / "tests" / "helper.py").write_text("x = 1\n", encoding="utf-8")
    (root / "tests" / "conftest.py").write_text("x = 1\n", encoding="utf-8")
    (root / "tests" / "__pycache__").mkdir()
    (root / "tests" / "__pycache__" / "test_cached.py").write_text("x = 1\n", encoding="utf-8")
    (root / "tests" / "suite_test.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )

    found = rc.discover_test_files(root)
    assert found == sorted(
        [
            "tests/sub/test_b.py",
            "tests/suite_test.py",
            "tests/test_a.py",
            "tests/test_c.py",
        ]
    )
    assert found == sorted(found)
    assert len(found) == len(set(found))


def test_partition_is_exact_no_missing_no_duplicates(rc):
    files = [f"tests/test_{i:02d}.py" for i in range(7)]
    chunks = rc.partition(files, 3)
    assert [len(chunk) for chunk in chunks] == [3, 3, 1]
    flattened = [f for chunk in chunks for f in chunk]
    assert flattened == files  # order preserved, nothing missing
    assert len(flattened) == len(set(flattened))  # nothing duplicated


def test_partition_with_oversized_chunk_size(rc):
    files = ["tests/test_a.py", "tests/test_b.py"]
    assert rc.partition(files, 50) == [files]


# --- PostgreSQL selection ------------------------------------------------------


def test_default_mode_excludes_only_postgres_files(rc, tmp_path):
    root = make_repo(
        tmp_path,
        plain=["test_a.py", "test_b.py"],
        marked=["test_pg_one.py", "test_pg_two.py"],
    )
    selection = rc.select_files(root, [], "exclude")
    assert selection.included == ["tests/test_a.py", "tests/test_b.py"]
    assert selection.excluded_postgres == ["tests/test_pg_one.py", "tests/test_pg_two.py"]
    assert selection.postgres_files == selection.excluded_postgres
    assert selection.discovered_count == 4


def test_postgres_only_mode_contains_every_marked_file_exactly_once(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"], marked=["test_pg.py", "test_pg2.py"])
    selection = rc.select_files(root, [], "only")
    assert selection.included == ["tests/test_pg.py", "tests/test_pg2.py"]
    assert selection.excluded_postgres == []
    assert len(selection.included) == len(set(selection.included))


def test_include_postgres_mode_runs_the_whole_suite(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"], marked=["test_pg.py"])
    selection = rc.select_files(root, [], "include")
    assert selection.included == ["tests/test_a.py", "tests/test_pg.py"]
    assert selection.excluded_postgres == []


def test_real_suite_default_run_excludes_postgres_and_nothing_else(rc):
    """On the real tree: every marked file excluded, every other file kept."""
    discovered = rc.discover_test_files(REPO_ROOT)
    selection = rc.select_files(REPO_ROOT, [], "exclude")
    marked = set(rc.postgres_test_files(REPO_ROOT, discovered))
    assert len(selection.included) + len(selection.excluded_postgres) == len(discovered)
    assert not set(selection.included) & marked
    assert set(selection.excluded_postgres) == marked
    # PostgreSQL files can never enter the default run.
    assert "tests/test_postgres_integration.py" not in selection.included


def test_runner_postgres_split_agrees_with_ci_workflow(rc):
    """The runner's derivation must equal both sides of the CI split.

    The workflow is parsed read-only, with the same strictness as
    tests/test_ci_postgres_split.py: exactly one backend pytest line carrying
    the --ignore list, exactly one postgres-job line carrying the file list.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    backend_lines = [
        line for line in workflow.splitlines() if "pytest tests/" in line and "--ignore" in line
    ]
    job_lines = [
        line
        for line in workflow.splitlines()
        if "test_postgres_integration" in line and "-v" in line
    ]
    assert len(backend_lines) == 1, backend_lines
    assert len(job_lines) == 1, job_lines
    backend_ignores = set(re.findall(r"--ignore=(\S+)", backend_lines[0]))
    postgres_job_files = set(re.findall(r"tests/\S+\.py", job_lines[0]))
    derived = set(rc.postgres_test_files(REPO_ROOT, rc.discover_test_files(REPO_ROOT)))
    assert derived, "sanity: the real suite has PostgreSQL-marked files"
    assert backend_ignores == derived
    assert postgres_job_files == derived


# --- filters -------------------------------------------------------------------


def test_single_path_filter(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    selection = rc.select_files(root, ["tests/test_b.py"], "exclude")
    assert selection.included == ["tests/test_b.py"]


def test_multiple_filters_union_without_duplicates(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a1.py", "test_a2.py", "test_b.py"])
    selection = rc.select_files(root, ["tests/test_a*.py", "tests/test_a1.py"], "exclude")
    assert selection.included == ["tests/test_a1.py", "tests/test_a2.py"]


def test_directory_filter_selects_everything_under_it(rc, tmp_path):
    root = make_repo(tmp_path, plain=["sub/test_x.py", "sub/test_y.py", "test_top.py"])
    selection = rc.select_files(root, ["tests/sub"], "exclude")
    assert selection.included == ["tests/sub/test_x.py", "tests/sub/test_y.py"]


def test_nonexistent_filter_fails(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    with pytest.raises(rc.RunnerError, match="does not exist"):
        rc.select_files(root, ["tests/test_missing.py"], "exclude")


def test_filter_outside_repository_fails(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    with pytest.raises(rc.RunnerError, match="not inside the repository"):
        rc.select_files(root, ["../elsewhere/test_a.py"], "exclude")


def test_filter_with_control_characters_fails(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    with pytest.raises(rc.RunnerError, match="control character"):
        rc.select_files(root, ["tests/test_a.py\n"], "exclude")
    with pytest.raises(rc.RunnerError, match="control character"):
        rc.select_files(root, ["tests/test_a.py\x00"], "exclude")


def test_glob_matching_no_files_fails(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    with pytest.raises(rc.RunnerError, match="matched no files"):
        rc.select_files(root, ["tests/test_zzz*.py"], "exclude")


def test_symlink_escape_is_refused(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    outside = tmp_path / "outside_test.py"
    outside.write_text("def test_outside():\n    assert True\n", encoding="utf-8")
    try:
        os.symlink(outside, root / "tests" / "test_link.py")
    except OSError:
        pytest.skip("symlink creation not permitted on this platform")
    discovered = rc.discover_test_files(root)
    assert "tests/test_link.py" not in discovered  # never silently discovered
    with pytest.raises(rc.RunnerError, match="not inside the repository"):
        rc.select_files(root, ["tests/test_link.py"], "exclude")


def test_output_path_symlink_escape_is_refused(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    outside = tmp_path / "outside_summary.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        os.symlink(outside, root / "summary.json")
    except OSError:
        pytest.skip("symlink creation not permitted on this platform")
    with pytest.raises(rc.RunnerError, match="escaping the repository"):
        rc.resolve_output_path(root, "summary.json", "JSON summary path")


# --- pytest argument safety ----------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["-n"],
        ["-n4"],
        ["--numprocesses"],
        ["--numprocesses=4"],
        ["--dist=loadfile"],
        ["--maxprocesses=4"],
        ["--max-worker-restart=3"],
        ["--forked"],
        ["--looponfail"],
        ["--xdist-rsyncdir=/tmp/x"],
        ["-p", "xdist"],
        ["-o", "addopts=-n 4"],
    ],
)
def test_parallel_execution_arguments_are_rejected(rc, argv):
    with pytest.raises(rc.RunnerError, match="parallel execution argument"):
        rc.validate_extra_args(argv)


def test_safe_pytest_arguments_pass_through(rc):
    safe = [
        "-q",
        "--tb=short",
        "-x",
        "--maxfail=2",
        "-k",
        "test_a and not test_b",
        "-p",
        "no:cacheprovider",
    ]
    rc.validate_extra_args(safe)  # must not raise
    assert safe == [
        "-q",
        "--tb=short",
        "-x",
        "--maxfail=2",
        "-k",
        "test_a and not test_b",
        "-p",
        "no:cacheprovider",
    ]


def test_chunk_command_is_an_argument_array_without_shell(rc):
    cmd = rc.build_command(sys.executable, ["tests/test_a.py"], ["-k", "one two"])
    assert cmd == [sys.executable, "-m", "pytest", "tests/test_a.py", "-k", "one two"]
    assert isinstance(cmd, list)


def test_display_command_hides_the_local_interpreter(rc):
    shown = rc.display_command(rc.build_command(sys.executable, ["tests/test_a.py"], []))
    assert sys.executable not in shown
    assert "python" in shown


# --- chunk selection and validation --------------------------------------------


def test_chunk_selection_runs_only_the_selected_chunks(rc, tmp_path):
    files = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
    plan = make_plan(rc, tmp_path, files, chunk_size=1, selected=[1, 3])
    launch = FakeLaunch(ok(rc), ok(rc))
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), launch, lambda: [])
    assert [record.status for record in outcome.records] == [
        "completed",
        "not-selected",
        "completed",
    ]
    launched_files = [record.files for record in outcome.records if record.status == "completed"]
    assert launched_files == [["tests/test_a.py"], ["tests/test_c.py"]]
    assert rc.final_exit_code(outcome) == 0


def test_chunk_selection_validation(rc):
    with pytest.raises(rc.RunnerError, match="outside 1..3"):
        rc.parse_chunk_selection("4", 3)
    with pytest.raises(rc.RunnerError, match="outside 1..3"):
        rc.parse_chunk_selection("0", 3)
    with pytest.raises(rc.RunnerError, match="twice"):
        rc.parse_chunk_selection("1,1", 3)
    with pytest.raises(rc.RunnerError, match="comma-separated"):
        rc.parse_chunk_selection("1;x", 3)
    assert rc.parse_chunk_selection("3,1", 3) == [1, 3]


def test_chunk_size_must_be_positive(rc):
    with pytest.raises(rc.RunnerError, match="at least 1"):
        rc.partition(["tests/test_a.py"], 0)


# --- chunk execution ------------------------------------------------------------


def test_continues_after_failed_chunk_by_default(rc, tmp_path):
    files = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
    plan = make_plan(rc, tmp_path, files)
    launch = FakeLaunch(ok(rc), ok(rc, 1, {"passed": 1, "failed": 1}), ok(rc))
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), launch, lambda: [])
    assert [record.status for record in outcome.records] == ["completed"] * 3
    assert [record.exit_code for record in outcome.records] == [0, 1, 0]
    assert outcome.stopped_on_failure_at is None
    assert rc.final_exit_code(outcome) == 1  # pytest semantics preserved


def test_stop_on_failure_is_explicit_and_marks_rest_not_run(rc, tmp_path):
    files = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
    plan = make_plan(rc, tmp_path, files, stop_on_failure=True)
    launch = FakeLaunch(ok(rc), ok(rc, 1, {"failed": 1}), ok(rc))
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), launch, lambda: [])
    assert [record.status for record in outcome.records] == [
        "completed",
        "completed",
        "not-run",
    ]
    assert outcome.stopped_on_failure_at == 2
    assert len(launch.calls) == 2  # chunk 3 never started
    assert rc.final_exit_code(outcome) == 1


def test_final_exit_code_rules(rc):
    records = [
        rc.ChunkRecord(index=i, files=[f"tests/test_{i}.py"]) for i in range(1, 4)
    ]
    for record, code in zip(records, [0, 1, 3]):
        record.status = "completed"
        record.exit_code = code
    outcome = rc.RunOutcome(records=records)
    assert rc.final_exit_code(outcome) == 3  # highest nonzero wins
    outcome.interrupted_signum = 2
    assert rc.final_exit_code(outcome) == 130
    outcome.interrupted_signum = 15
    assert rc.final_exit_code(outcome) == 143
    for record in records:
        record.exit_code = 0
    outcome.interrupted_signum = None
    outcome.stopped_on_failure_at = 1
    assert rc.final_exit_code(outcome) == 1


def test_children_run_strictly_sequentially_real_subprocess(rc, tmp_path, monkeypatch):
    """A real child per chunk: chunk N+1 starts only after chunk N exited."""
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    stub = tmp_path / "stub_pytest.py"
    stub.write_text(
        "import json, sys, time\n"
        "log_path, *rest = sys.argv[1:]\n"
        "with open(log_path, 'a', encoding='utf-8') as fh:\n"
        "    fh.write(json.dumps({'event': 'start', 't': time.time()}) + '\\n')\n"
        "    time.sleep(0.15)\n"
        "    fh.write(json.dumps({'event': 'end', 't': time.time()}) + '\\n')\n"
        "print('2 passed, 1 skipped in 0.01s')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    log = tmp_path / "children.log"
    plan = make_plan(rc, root, ["tests/test_a.py", "tests/test_b.py"], chunk_size=1)
    monkeypatch.setattr(
        rc,
        "build_command",
        lambda interp, chunk_files, extra: [sys.executable, str(stub), str(log), *chunk_files],
    )
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), rc.run_one_chunk, lambda: [])
    assert [record.exit_code for record in outcome.records] == [0, 0]
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == ["start", "end", "start", "end"]
    assert events[1]["t"] <= events[2]["t"]  # chunk 2 started after chunk 1 ended


def test_failed_chunk_in_a_real_subprocess_does_not_stop_the_run(rc, tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path, plain=["test_ok.py", "test_failflag.py", "test_after.py"])
    stub = tmp_path / "stub_pytest.py"
    stub.write_text(
        "import sys\n"
        "if any('failflag' in a for a in sys.argv[1:]):\n"
        "    print('1 failed in 0.01s')\n"
        "    sys.exit(1)\n"
        "print('2 passed, 1 skipped in 0.01s')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    plan = make_plan(
        rc, root, ["tests/test_ok.py", "tests/test_failflag.py", "tests/test_after.py"]
    )
    monkeypatch.setattr(
        rc,
        "build_command",
        lambda interp, chunk_files, extra: [sys.executable, str(stub), *chunk_files],
    )
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), rc.run_one_chunk, lambda: [])
    assert [record.exit_code for record in outcome.records] == [0, 1, 0]
    assert [record.status for record in outcome.records] == ["completed"] * 3
    assert outcome.records[1].counts == {"failed": 1}
    assert outcome.records[0].counts == {"passed": 2, "skipped": 1}
    assert rc.final_exit_code(outcome) == 1
    out = capsys.readouterr().out
    assert "2 passed, 1 skipped in 0.01s" in out  # streamed through, not swallowed


def test_arguments_with_spaces_pass_without_shell_interpretation(rc, tmp_path):
    stub = tmp_path / "stub_pytest.py"
    stub.write_text(
        "import json, sys\n"
        "log_path, *rest = sys.argv[1:]\n"
        "with open(log_path, 'a', encoding='utf-8') as fh:\n"
        "    fh.write(json.dumps(rest) + '\\n')\n"
        "print('1 passed in 0.01s')\n",
        encoding="utf-8",
    )
    log = tmp_path / "argv.log"
    cmd = [sys.executable, str(stub), str(log), "tests/weird name.py", "-k", "a b or c"]
    result = rc.run_one_chunk(cmd, tmp_path)
    assert result.exit_code == 0
    assert json.loads(log.read_text(encoding="utf-8")) == ["tests/weird name.py", "-k", "a b or c"]


def test_output_is_streamed_line_by_line_without_unbounded_capture(
    rc, tmp_path, monkeypatch, capsys
):
    lines = [f"progress line {i:04d}\n" for i in range(200)] + ["==== 5 passed in 0.10s ====\n"]

    class FakeStream:
        def __init__(self):
            self._iter = iter(lines)
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._iter)

        def read(self, *args):
            raise AssertionError("run_one_chunk must not slurp output with read()")

        def readlines(self):
            raise AssertionError("run_one_chunk must not slurp output with readlines()")

        def close(self):
            self.closed = True

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            FakePopen.last_kwargs = kwargs
            self.stdout = FakeStream()
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    fake_subprocess = types.SimpleNamespace(PIPE=1, STDOUT=2)
    fake_subprocess.Popen = FakePopen
    monkeypatch.setattr(rc, "subprocess", fake_subprocess)

    result = rc.run_one_chunk(["python", "-m", "pytest", "tests/test_a.py"], tmp_path)
    assert result.exit_code == 0
    assert result.counts == {"passed": 5}
    assert result.duration_seconds >= 0
    assert not FakePopen.last_kwargs.get("shell", False)
    assert FakePopen.last_kwargs["stdout"] == 1
    captured = capsys.readouterr().out
    assert "progress line 0000" in captured and "progress line 0199" in captured


# --- summary parsing ------------------------------------------------------------


def test_summary_line_parsing(rc):
    wrapped = "========== 1 failed, 5 passed, 1 skipped, 3 warnings in 0.21s =========="
    assert rc.parse_summary_line(wrapped) == {
        "failed": 1,
        "passed": 5,
        "skipped": 1,
        "warnings": 3,
    }
    assert rc.parse_summary_line("1 failed, 5 passed in 12.34s") == {"failed": 1, "passed": 5}
    assert rc.parse_summary_line("====== 567 passed, 2 skipped in 3.50s (0:00:03) ======") == {
        "passed": 567,
        "skipped": 2,
    }
    assert rc.parse_summary_line("====== no tests ran in 0.01s ======") == {}
    assert rc.parse_summary_line("2 errors in 1.00s") == {"error": 2}
    assert rc.parse_summary_line("short test summary info") is None
    assert rc.parse_summary_line("=========== warnings summary ===========") is None
    assert rc.parse_summary_line("tests/test_a.py s                                 [100%]") is None


def test_format_counts_matches_the_reported_shape(rc):
    assert rc.format_counts({"passed": 567, "skipped": 2}) == (
        "567 passed, 0 failed, 0 errors, 2 skipped"
    )
    assert rc.format_counts({}) == "0 passed, 0 failed, 0 errors, 0 skipped"
    assert rc.format_counts(None) == "no summary line parsed"
    assert rc.format_counts({"passed": 1, "failed": 2, "error": 3}) == (
        "1 passed, 2 failed, 3 errors, 0 skipped"
    )


# --- interruption ---------------------------------------------------------------


def test_interrupted_chunk_is_recorded_and_later_chunks_stay_pending(rc, tmp_path):
    files = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
    plan = make_plan(rc, tmp_path, files)
    launch = FakeLaunch(ok(rc), interrupted(rc, 2))
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), launch, lambda: [])
    assert outcome.interrupted_signum == 2
    assert [record.status for record in outcome.records] == ["completed", "interrupted", "pending"]
    assert len(launch.calls) == 2
    assert rc.final_exit_code(outcome) == 130


def test_sigterm_style_interruption_maps_to_143(rc, tmp_path):
    plan = make_plan(rc, tmp_path, ["tests/test_a.py"])
    launch = FakeLaunch(interrupted(rc, 15))
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), launch, lambda: [])
    assert rc.final_exit_code(outcome) == 143


def test_signal_handlers_raise_and_are_restored(rc):
    before = signal.getsignal(signal.SIGINT)
    handlers = rc._install_signal_handlers()
    try:
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        with pytest.raises(rc.SignalInterruptError) as excinfo:
            handler(signal.SIGINT, None)
        assert excinfo.value.signum == signal.SIGINT
        if hasattr(signal, "SIGTERM"):
            with pytest.raises(rc.SignalInterruptError) as excinfo:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            assert excinfo.value.signum == signal.SIGTERM
    finally:
        rc._restore_signal_handlers(handlers)
    assert signal.getsignal(signal.SIGINT) == before


def test_forward_termination_terminates_and_waits(rc):
    class FakeChild:
        def __init__(self):
            self.terminated = False
            self.killed = False
            self.waits = 0
            self.polled_alive = True

        def poll(self):
            return None if self.polled_alive else 0

        def terminate(self):
            self.terminated = True
            self.polled_alive = False

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            self.waits += 1
            return 0

    child = FakeChild()
    rc.forward_termination(child)
    assert child.terminated and not child.killed
    assert child.waits == 1


# --- dirty-file tracking ----------------------------------------------------------


def test_newly_dirtied_tracked_paths_are_detected(rc, tmp_path):
    plan = make_plan(rc, tmp_path, ["tests/test_a.py", "tests/test_b.py"])
    snapshots = iter([[], [], ["data/okrs_database.json"], ["data/okrs_database.json"]])
    launch = FakeLaunch(ok(rc), ok(rc))
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), launch, lambda: next(snapshots))
    assert outcome.new_dirty_paths == ["data/okrs_database.json"]
    assert outcome.dirty_after == ["data/okrs_database.json"]


def test_pre_existing_dirty_is_distinguished_from_new_dirty(rc, tmp_path, capsys):
    plan = make_plan(rc, tmp_path, ["tests/test_a.py"])
    dirty = ["data/okrs_database.json"]
    launch = FakeLaunch(ok(rc))
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), launch, lambda: dirty)
    assert outcome.new_dirty_paths == []  # already dirty before the run
    assert outcome.dirty_before == dirty
    rc.print_completion_summary(plan, rc.Selection([], [], 1, []), outcome, 0)
    out = capsys.readouterr().out
    assert "pre-existing: data/okrs_database.json" in out
    assert "  new: data/okrs_database.json" not in out


def test_fail_on_new_dirty_stops_the_run(rc, tmp_path):
    plan = make_plan(rc, tmp_path, ["tests/test_a.py", "tests/test_b.py"], fail_on_new_dirty=True)
    dirty = "data/okrs_database.json"
    snapshots = iter([[], [dirty], [dirty]])  # start, after chunk 1, after chunk 2
    launch = FakeLaunch(ok(rc), ok(rc))
    outcome = rc.execute_plan(plan, fresh_records(rc, plan), launch, lambda: next(snapshots))
    assert [record.status for record in outcome.records] == ["completed", "not-run"]
    assert outcome.stopped_on_failure_at == 1
    assert rc.final_exit_code(outcome) == 1


def test_dirty_files_are_never_restored(rc, tmp_path):
    """The runner reports rewritten files; it must not touch their contents."""
    root = make_repo(tmp_path, plain=["test_a.py"])
    data_file = root / "data" / "okrs_database.json"
    data_file.parent.mkdir(parents=True)
    data_file.write_text('{"modified": "by tests"}\n', encoding="utf-8")
    plan = make_plan(rc, root, ["tests/test_a.py"])
    launch = FakeLaunch(ok(rc))
    seen = {"calls": 0}

    def snapshot():
        seen["calls"] += 1
        return [] if seen["calls"] == 1 else ["data/okrs_database.json"]

    outcome = rc.execute_plan(plan, fresh_records(rc, plan), launch, snapshot)
    assert outcome.new_dirty_paths == ["data/okrs_database.json"]
    assert data_file.read_text(encoding="utf-8") == '{"modified": "by tests"}\n'


def test_runner_uses_only_readonly_git_commands(rc):
    """AST guard: every git invocation in the runner is a read-only query."""
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    git_commands = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in ("run", "Popen", "check_output")):
            continue
        if not (node.args and isinstance(node.args[0], ast.List)):
            continue
        elements = node.args[0].elts
        if len(elements) >= 2 and all(isinstance(el, ast.Constant) for el in elements[:2]):
            if elements[0].value == "git":
                git_commands.add(elements[1].value)
    assert git_commands, "sanity: the runner shells out to git"
    assert git_commands <= {"rev-parse", "status", "ls-files"}


# --- JSON summary ------------------------------------------------------------------


def test_json_summary_is_created_exclusively(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py"])
    json_path = root / "summary.json"
    assert run_cli(monkeypatch, rc, root, ["--json", "summary.json"], FakeLaunch(ok(rc))) == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["exit_code"] == 0
    assert payload["state"] == "completed"

    second = FakeLaunch(ok(rc))
    assert run_cli(monkeypatch, rc, root, ["--json", "summary.json"], second) == 2
    assert second.calls == []  # refused before any chunk ran
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_json_overwrite_replaces_exactly_that_file(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py"])
    json_path = root / "summary.json"
    json_path.write_text("keep me\n", encoding="utf-8")
    sibling = root / "sibling.txt"
    sibling.write_text("untouched\n", encoding="utf-8")
    argv = ["--json", "summary.json", "--overwrite-json"]
    assert run_cli(monkeypatch, rc, root, argv, FakeLaunch(ok(rc))) == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["tool"] == "run_pytest_chunks"
    assert sibling.read_text(encoding="utf-8") == "untouched\n"


def test_json_summary_schema_and_no_secrets_or_absolute_paths(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py"])
    monkeypatch.setenv("NEXUS_TEST_SECRET_TOKEN", "super-secret-value-123")
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@localhost/db")
    assert run_cli(monkeypatch, rc, root, ["--json", "summary.json"], FakeLaunch(ok(rc))) == 0
    text = (root / "summary.json").read_text(encoding="utf-8")
    assert "super-secret-value-123" not in text
    assert "postgres://user:pw@localhost/db" not in text
    assert str(root) not in text
    payload = json.loads(text)
    assert set(payload) == JSON_KEYS
    for record in payload["chunks"]:
        assert set(record) == CHUNK_RECORD_KEYS
        for value in record["files"]:
            assert not Path(value).is_absolute()
            assert not re.match(r"^[A-Za-z]:[\\/]", value)


def test_json_summary_reflects_counts_and_dirty_state(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"], marked=["test_pg.py"])
    dirty = "data/okrs_database.json"
    snapshots = iter([[], [], [dirty], [dirty]])  # start-of-main, plan start, per chunk
    launch = FakeLaunch(ok(rc, 0, {"passed": 3, "skipped": 1}), ok(rc, 0, {"passed": 2}))
    argv = ["--json", "summary.json", "--chunk-size", "1"]
    assert run_cli(monkeypatch, rc, root, argv, launch, dirty=lambda _root: next(snapshots)) == 0
    payload = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert payload["included_files"] == ["tests/test_a.py", "tests/test_b.py"]
    assert payload["excluded_postgres_files"] == ["tests/test_pg.py"]
    assert payload["discovered_file_count"] == 3
    assert payload["started_clean"] is True
    assert payload["totals"] == {"passed": 5, "skipped": 1}
    assert payload["chunks"][0]["counts"] == {"passed": 3, "skipped": 1}
    assert payload["newly_dirtied_paths"] == [dirty]
    assert payload["dirty_before_paths"] == []


def test_summary_output_prints_the_required_fields(rc, tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    assert run_cli(monkeypatch, rc, root, ["--chunk-size", "1"], FakeLaunch(ok(rc), ok(rc))) == 0
    out = capsys.readouterr().out
    assert f"Commit: {FAKE_COMMIT}" in out
    assert "Starting state: clean" in out
    assert "Discovered test files: 2" in out
    assert "Included: 2" in out
    assert "Excluded PostgreSQL files: 0" in out
    assert "Chunks: 2" in out
    assert "Chunk 01: tests/test_a.py" in out
    assert "Chunk 01: exit=0" in out
    assert "Overall: passed" in out


# --- output-path guards --------------------------------------------------------------


def test_summary_cannot_overwrite_a_tracked_test_file(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    init_git_repo(root)
    target = root / "tests" / "test_a.py"
    with pytest.raises(rc.RunnerError, match="Python file inside the repository"):
        rc.guard_against_repo_file(root, target, "JSON summary path", False)


def test_summary_cannot_overwrite_a_tracked_non_python_file(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    init_git_repo(root)
    target = root / "data" / "okrs_database.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "data"], cwd=root, check=True)
    with pytest.raises(rc.RunnerError, match="tracked repository file"):
        rc.guard_against_repo_file(root, target, "manifest path", False)


def test_summary_cannot_overwrite_any_python_file_even_untracked(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    target = root / "src" / "nexus" / "module.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")  # untracked work-in-progress
    with pytest.raises(rc.RunnerError, match="Python file inside the repository"):
        rc.guard_against_repo_file(root, target, "manifest path", False)


def test_explicit_overwrite_flag_allows_the_exact_target_only(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"])
    init_git_repo(root)
    rc.guard_against_repo_file(root, root / "tests" / "test_a.py", "JSON summary path", True)
    outside = tmp_path / "elsewhere.json"
    rc.guard_against_repo_file(root, outside, "JSON summary path", False)  # outside repo: fine


def test_cli_refuses_json_pointed_at_a_test_file(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py"])
    before = (root / "tests" / "test_a.py").read_text(encoding="utf-8")
    launch = FakeLaunch(ok(rc))
    assert run_cli(monkeypatch, rc, root, ["--json", "tests/test_a.py"], launch) == 2
    assert launch.calls == []
    assert (root / "tests" / "test_a.py").read_text(encoding="utf-8") == before


# --- manifest and resume --------------------------------------------------------------


def test_manifest_is_created_and_completed(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py", "test_c.py"])
    argv = ["--manifest", "manifest.json", "--chunk-size", "2"]
    assert run_cli(monkeypatch, rc, root, argv, FakeLaunch(ok(rc), ok(rc))) == 0
    manifest = read_manifest(root)
    assert set(manifest) == MANIFEST_KEYS
    assert manifest["schema_version"] == 1
    assert manifest["repo_commit"] == FAKE_COMMIT
    assert manifest["files"] == ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
    assert [chunk["files"] for chunk in manifest["chunks"]] == [
        ["tests/test_a.py", "tests/test_b.py"],
        ["tests/test_c.py"],
    ]
    assert [chunk["status"] for chunk in manifest["chunks"]] == ["completed", "completed"]
    assert manifest["state"] == "completed"


def test_manifest_refuses_to_clobber_an_existing_one(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py"])
    (root / "manifest.json").write_text("previous run\n", encoding="utf-8")
    launch = FakeLaunch(ok(rc))
    assert run_cli(monkeypatch, rc, root, ["--manifest", "manifest.json"], launch) == 2
    assert launch.calls == []
    assert (root / "manifest.json").read_text(encoding="utf-8") == "previous run\n"


def test_resume_after_completed_chunks_runs_only_the_rest(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py", "test_c.py"])
    argv = ["--manifest", "manifest.json", "--chunk-size", "1"]
    first = FakeLaunch(ok(rc), interrupted(rc, 2))
    assert run_cli(monkeypatch, rc, root, argv, first) == 130  # interrupted mid-run
    manifest = read_manifest(root)
    assert manifest["state"] == "interrupted"
    assert [chunk["status"] for chunk in manifest["chunks"]] == [
        "completed",
        "interrupted",
        "pending",
    ]

    second = FakeLaunch(ok(rc), ok(rc))
    assert run_cli(monkeypatch, rc, root, argv + ["--resume"], second) == 0
    launched = [call[3:] for call in second.calls]  # the pytest file arguments
    assert launched == [["tests/test_b.py"], ["tests/test_c.py"]]
    manifest = read_manifest(root)
    assert manifest["state"] == "completed"
    assert all(chunk["status"] == "completed" for chunk in manifest["chunks"])


def test_resume_reruns_interrupted_chunk_exactly_once(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    argv = ["--manifest", "manifest.json", "--chunk-size", "1"]
    assert run_cli(
        monkeypatch, rc, root, argv, FakeLaunch(ok(rc), interrupted(rc, 15))
    ) == 143
    second = FakeLaunch(ok(rc))
    assert run_cli(monkeypatch, rc, root, argv + ["--resume"], second) == 0
    assert len(second.calls) == 1
    assert second.calls[0][3:] == ["tests/test_b.py"]


def test_interrupt_between_chunks_is_handled_by_cli(rc, tmp_path, monkeypatch):
    """A signal arriving between chunks still records state and exits nonzero."""
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    argv = ["--manifest", "manifest.json", "--chunk-size", "1"]
    launch = FakeLaunch(ok(rc), rc.SignalInterruptError(15))
    assert run_cli(monkeypatch, rc, root, argv, launch) == 143
    manifest = read_manifest(root)
    assert manifest["state"] == "interrupted"
    assert [chunk["status"] for chunk in manifest["chunks"]] == ["completed", "pending"]


def test_resume_refuses_after_commit_change(rc, tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    argv = ["--manifest", "manifest.json", "--chunk-size", "1"]
    assert run_cli(
        monkeypatch, rc, root, argv, FakeLaunch(ok(rc), interrupted(rc, 2))
    ) == 130
    launch = FakeLaunch(ok(rc))
    assert (
        run_cli(monkeypatch, rc, root, argv + ["--resume"], launch, commit="b" * 40) == 2
    )
    assert launch.calls == []
    assert "commit" in capsys.readouterr().err


def test_resume_refuses_after_file_list_change(rc, tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    argv = ["--manifest", "manifest.json", "--chunk-size", "1"]
    assert run_cli(
        monkeypatch, rc, root, argv, FakeLaunch(ok(rc), interrupted(rc, 2))
    ) == 130
    (root / "tests" / "test_new.py").write_text(
        "def test_new():\n    assert True\n", encoding="utf-8"
    )
    launch = FakeLaunch(ok(rc))
    assert run_cli(monkeypatch, rc, root, argv + ["--resume"], launch) == 2
    assert launch.calls == []
    assert "file list" in capsys.readouterr().err


def test_resume_refuses_after_pytest_argument_change(rc, tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    argv = ["--manifest", "manifest.json", "--chunk-size", "1"]
    assert run_cli(
        monkeypatch, rc, root, argv, FakeLaunch(ok(rc), interrupted(rc, 2))
    ) == 130
    launch = FakeLaunch(ok(rc))
    assert run_cli(monkeypatch, rc, root, argv + ["--resume", "--", "-q"], launch) == 2
    assert launch.calls == []
    assert "pytest arguments" in capsys.readouterr().err


def test_failed_chunk_counts_as_completed_unless_rerun_is_requested(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    argv = ["--manifest", "manifest.json", "--chunk-size", "1"]
    assert run_cli(
        monkeypatch, rc, root, argv, FakeLaunch(ok(rc, 1, {"failed": 1}), ok(rc, 1, {"failed": 1}))
    ) == 1
    # Default resume: previously failed chunks are not rerun.
    resume = FakeLaunch()
    assert run_cli(monkeypatch, rc, root, argv + ["--resume"], resume) == 1
    assert resume.calls == []
    statuses = [chunk["status"] for chunk in read_manifest(root)["chunks"]]
    assert statuses == ["completed", "completed"]
    # Explicit --rerun-failed: they are rerun, and a pass flips the outcome.
    rerun = FakeLaunch(ok(rc, 0, {"passed": 2}), ok(rc, 0, {"passed": 2}))
    assert run_cli(monkeypatch, rc, root, argv + ["--resume", "--rerun-failed"], rerun) == 0
    assert len(rerun.calls) == 2
    manifest = read_manifest(root)
    assert all(
        chunk["status"] == "completed" and chunk["exit_code"] == 0 for chunk in manifest["chunks"]
    )
    assert all(chunk["rerun"] for chunk in manifest["chunks"])


def test_resume_refuses_mismatched_options_directly(rc, tmp_path):
    """Resume validates the manifest against the recomputed plan, field by field."""
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"])
    plan = make_plan(rc, root, ["tests/test_a.py", "tests/test_b.py"], chunk_size=1)
    manifest_path = root / "manifest.json"

    def write_manifest(**changes):
        payload = rc.manifest_payload(
            commit=FAKE_COMMIT,
            postgres_mode="exclude",
            filters=[],
            chunk_size=1,
            pytest_args=[],
            files=plan.files,
            chunks=fresh_records(rc, plan),
            selected=None,
            state="interrupted",
            starting_dirty=[],
        )
        payload.update(changes)
        rc.save_manifest(manifest_path, payload)

    write_manifest()
    selection = rc.select_files(root, [], "exclude")
    records = rc.load_manifest_for_resume(manifest_path, plan, selection)
    assert [record.index for record in records] == [1, 2]

    for field, value, expected in [
        ("repo_commit", "b" * 40, "resume refused"),
        ("files", ["tests/test_other.py"], "resume refused"),
        ("chunk_size", 2, "resume refused"),
        ("pytest_args", ["-q"], "resume refused"),
        ("postgres_mode", "only", "resume refused"),
        ("filters", ["tests/test_a.py"], "resume refused"),
        ("selected_chunks", [1], "resume refused"),
        ("schema_version", 99, "schema version"),
    ]:
        write_manifest(**{field: value})
        with pytest.raises(rc.RunnerError, match=expected):
            rc.load_manifest_for_resume(manifest_path, plan, selection)

    write_manifest(chunks=[dict(index=2, files=["tests/test_a.py"], status="pending")])
    with pytest.raises(rc.RunnerError, match="malformed"):
        rc.load_manifest_for_resume(manifest_path, plan, selection)

    # The untouched manifest still resumes.
    write_manifest()
    records = rc.load_manifest_for_resume(manifest_path, plan, selection)
    assert [record.index for record in records] == [1, 2]


def test_resume_requires_an_existing_manifest(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py"])
    launch = FakeLaunch(ok(rc))
    assert run_cli(monkeypatch, rc, root, ["--manifest", "manifest.json", "--resume"], launch) == 2
    assert launch.calls == []


# --- requested-file and CLI guards ------------------------------------------------------


def test_explicitly_requested_postgres_file_is_refused_not_silently_omitted(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"], marked=["test_pg.py"])
    with pytest.raises(rc.RunnerError, match="test_pg.py"):
        rc.select_files(root, ["tests/test_pg.py"], "exclude")
    # and a plain file is never silently included in postgres-only mode either
    with pytest.raises(rc.RunnerError, match="not PostgreSQL-marked"):
        rc.select_files(root, ["tests/test_a.py"], "only")


def test_non_discoverable_requested_file_is_refused(rc, tmp_path):
    root = make_repo(tmp_path, plain=["test_a.py"], extra_files={"tests/conftest.py": "x = 1\n"})
    with pytest.raises(rc.RunnerError, match="not a discoverable test file"):
        rc.select_files(root, ["tests/conftest.py"], "exclude")


def test_requested_file_always_appears_in_the_plan(rc, tmp_path, monkeypatch):
    """A requested file that survives validation is in exactly one chunk."""
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py", "test_c.py"])
    argv = ["tests/test_b.py", "--chunk-size", "1", "--json", "summary.json"]
    assert run_cli(monkeypatch, rc, root, argv, FakeLaunch(ok(rc))) == 0
    payload = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert payload["included_files"] == ["tests/test_b.py"]
    assert [chunk["files"] for chunk in payload["chunks"]] == [["tests/test_b.py"]]


def test_cli_refuses_unknown_flags(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py"])
    init_git_repo(root)
    monkeypatch.setattr(rc, "git_toplevel", lambda hint: root)
    with pytest.raises(SystemExit):
        rc.main(["--n", "4"])


def test_cli_refuses_parallel_arguments_after_separator(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py"])
    launch = FakeLaunch(ok(rc))
    assert run_cli(monkeypatch, rc, root, ["--", "-n", "4"], launch) == 2
    assert launch.calls == []


def test_list_mode_prints_the_plan_and_runs_nothing(rc, tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path, plain=["test_a.py", "test_b.py"], marked=["test_pg.py"])
    launch = FakeLaunch()
    assert run_cli(monkeypatch, rc, root, ["--list", "--chunk-size", "1"], launch) == 0
    out = capsys.readouterr().out
    assert "Discovered 3 test files" in out
    assert "excluded: tests/test_pg.py" in out
    assert "Chunks to run: 2 of 2" in out
    assert launch.calls == []


def test_empty_selection_is_a_clear_error(rc, tmp_path, monkeypatch):
    root = make_repo(tmp_path, plain=["test_a.py"])
    launch = FakeLaunch()
    assert run_cli(monkeypatch, rc, root, ["tests/test_pg.py"], launch) == 2
    assert launch.calls == []
