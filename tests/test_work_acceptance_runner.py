"""The acceptance runner cleans up after itself and never leaks its database password.

A fake ``docker`` and a fake pytest stand in for the real ones, so nothing here needs Docker,
a network or a database. ``scripts/work_acceptance.py`` documents the safety properties and why
SIGKILL is out of reach.
"""

from __future__ import annotations

import importlib.util
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "work_acceptance.py"
spec = importlib.util.spec_from_file_location("work_acceptance", SCRIPT)
runner = importlib.util.module_from_spec(spec)
sys.modules["work_acceptance"] = runner
spec.loader.exec_module(runner)

JUNIT = (
    '<testsuite><testcase classname="tests.test_x.TestA" name="one"/>'
    '<testcase classname="tests.test_x.TestA" name="two">{}</testcase></testsuite>'
)


class FakeDocker:
    def __init__(self) -> None:
        self.containers: dict[str, str] = {}  # id -> run token (its label value)
        self.removed: list[str] = []
        self.argvs: list[list[str]] = []
        self.password = ""
        self.docker_missing = False
        self.start_error: str | None = None  # docker run exits 125 with this stderr
        self.leave_created_on_error = False
        self.foreign: dict[str, str] = {"deadbeef0001": "someone-else"}
        self.run_returns_foreign: str | None = None
        self.ps_includes_foreign = False
        self.pytest_result = "pass"  # pass | fail | signal:<NAME> | none
        self.pytest_text = ""
        self.password_in_pytest_output = False
        self.pytest_env: dict[str, str] = {}
        self.seen_tmp_files: list[str] = []

    def label_of(self, ident: str) -> str | None:
        return self.containers.get(ident, self.foreign.get(ident))

    def __call__(self, argv, **kw):
        self.argvs.append(list(argv))
        if argv[0] != "docker":
            return self._pytest(argv, kw)
        if self.docker_missing:
            raise FileNotFoundError("docker")
        verb, rest = argv[1], argv[2:]
        env = kw.get("env") or {}
        ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        if verb == "run":
            self.password = env.get("POSTGRES_PASSWORD", "")
            token = rest[rest.index("--label") + 1].split("=", 1)[1]
            if self.start_error is not None:
                if self.leave_created_on_error:
                    self.containers["created0001"] = token
                return SimpleNamespace(
                    returncode=125,
                    stdout="",
                    stderr=self.start_error.replace("{pw}", self.password),
                )
            if self.run_returns_foreign:
                ok.stdout = self.run_returns_foreign + "\n"
                return ok
            self.containers["abc123def456"] = token
            ok.stdout = "abc123def456\n"
        elif verb == "inspect":
            found = self.label_of(rest[-1])
            if found is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="no such object")
            ok.stdout = found + "\n"
        elif verb == "ps":
            token = rest[rest.index("--filter") + 1].split("=", 2)[2]
            ids = [i for i, tok in self.containers.items() if tok == token]
            if self.ps_includes_foreign:
                ids += list(self.foreign)
            ok.stdout = "\n".join(ids)
        elif verb == "port":
            ok.stdout = "127.0.0.1:54321\n"
        elif verb == "exec":
            pass
        elif verb == "rm":
            for ident in rest[2:] if rest[:2] == ["-f", "-v"] else rest:
                self.removed.append(ident)
                self.containers.pop(ident, None)
                self.foreign.pop(ident, None)
        return ok

    def _pytest(self, argv, kw):
        self.pytest_env = dict(kw["env"])
        junit = Path(next(a for a in argv if a.startswith("--junitxml="))[len("--junitxml=") :])
        self.seen_tmp_files = [str(p) for p in junit.parent.rglob("*")]
        result = self.pytest_result
        if result.startswith("signal:"):
            number = getattr(signal, result.split(":", 1)[1])
            signal.getsignal(number)(number, None)  # what delivery of the signal does
        if result != "none":
            junit.write_text(JUNIT.format("<failure/>" if result == "fail" else ""))
        text = f"{self.password} collected" if self.password_in_pytest_output else "ok"
        return SimpleNamespace(returncode=1 if result == "fail" else 0, stdout=text, stderr=text)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    docker = FakeDocker()
    monkeypatch.setattr(subprocess, "run", docker)
    monkeypatch.setattr(runner.time, "sleep", lambda _s: None)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return docker


def _main(capsys):
    """(exit code, message, stdout, stderr). A string SystemExit is the message and means 1."""
    try:
        code, message = runner.main(), ""
    except SystemExit as stop:
        code, message = (1, stop.code) if isinstance(stop.code, str) else (stop.code, "")
    out = capsys.readouterr()
    return code, message, out.out, out.err


def _clean(fake, tmp_path):
    assert fake.containers == {}, "a container of this run was left behind"
    assert list(tmp_path.glob("work-acceptance-*")) == []
    if fake.password:
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert fake.password not in path.read_text(errors="ignore"), path


def _silent(fake, *streams):
    assert fake.password, "the fake never saw the password"
    for text in streams:
        assert fake.password not in text


class TestHappyPathAndPytestFailure:
    def test_pass_prints_scenarios_and_leaves_nothing(self, fake, capsys, tmp_path):
        code, message, out, err = _main(capsys)
        assert (code, message) == (0, "")
        assert "PASS: 2/2 scenarios passed" in out
        assert fake.removed == ["abc123def456"]
        _clean(fake, tmp_path)
        _silent(fake, out, err, message)

    def test_the_container_has_no_name_and_the_password_is_not_in_any_argv(self, fake, capsys):
        _main(capsys)
        for argv in fake.argvs:
            assert "--name" not in argv, "a fixed name could collide with someone else's container"
            assert not any(fake.password in part for part in argv), argv
        run = next(a for a in fake.argvs if a[:2] == ["docker", "run"])
        label = run[run.index("--label") + 1]
        assert label.startswith("nexus-work-acceptance=") and len(label) > 30
        assert "POSTGRES_PASSWORD" in run and "POSTGRES_PASSWORD=" not in " ".join(run)

    def test_the_suite_gets_the_password_only_through_its_environment(self, fake, capsys):
        _main(capsys)
        assert fake.password in fake.pytest_env["TEST_DATABASE_URL"]

    def test_a_failing_suite_exits_one_still_cleans_and_prints_no_password(
        self, fake, capsys, tmp_path
    ):
        fake.pytest_result = "fail"
        fake.password_in_pytest_output = True
        code, message, out, err = _main(capsys)
        assert code == 1 and "FAIL: 1/2 scenarios passed" in out
        _clean(fake, tmp_path)
        _silent(fake, out, err, message)

    def test_a_suite_that_never_ran_is_a_failure_and_cleans(self, fake, capsys, tmp_path):
        fake.pytest_result = "none"
        code, message, out, err = _main(capsys)
        assert code == 1 and "the suite did not run" in out
        _clean(fake, tmp_path)


class TestDockerProblems:
    def test_docker_missing_is_one_clear_line(self, fake, capsys, tmp_path):
        fake.docker_missing = True
        code, message, out, err = _main(capsys)
        assert (code, message) == (1, "FAIL: docker is not available")
        assert fake.containers == {} and list(tmp_path.glob("work-acceptance-*")) == []

    def test_start_failure_reports_docker_stderr_without_the_password(self, fake, capsys, tmp_path):
        fake.start_error = "Error response from daemon: bad env POSTGRES_PASSWORD={pw}"
        code, message, out, err = _main(capsys)
        assert code == 1 and message.startswith("FAIL: docker run failed: Error response")
        assert "***" in message
        _silent(fake, message, out, err)
        _clean(fake, tmp_path)

    def test_a_name_collision_error_is_reported_and_cannot_remove_the_other_container(
        self, fake, capsys, tmp_path
    ):
        fake.start_error = 'Conflict. The container name "/pg" is already in use'
        fake.foreign = {"deadbeef0001": "someone-else"}
        code, message, out, err = _main(capsys)
        assert code == 1 and "already in use" in message
        assert fake.removed == [] and fake.foreign == {"deadbeef0001": "someone-else"}
        _clean(fake, tmp_path)

    def test_a_container_created_before_a_failed_start_is_still_removed(
        self, fake, capsys, tmp_path
    ):
        fake.start_error = "cannot start"
        fake.leave_created_on_error = True
        code, message, out, err = _main(capsys)
        assert code == 1
        assert fake.removed == ["created0001"]
        _clean(fake, tmp_path)


class TestOwnership:
    def test_a_foreign_container_in_the_label_listing_is_never_removed(
        self, fake, capsys, tmp_path
    ):
        fake.ps_includes_foreign = True
        code, message, out, err = _main(capsys)
        assert code == 0
        assert "deadbeef0001" not in fake.removed and "deadbeef0001" in fake.foreign
        assert "refusing to remove a container this run does not own" in out
        assert "deadbeef0001" not in out, "no foreign id in the output"
        _clean(fake, tmp_path)

    def test_identity_mismatch_refuses_to_use_or_remove_the_container(self, fake, capsys):
        fake.run_returns_foreign = "deadbeef0001"
        code, message, out, err = _main(capsys)
        assert code == 1 and "not this run's" in message
        assert "deadbeef0001" not in message + out + err
        assert fake.removed == [] and "deadbeef0001" in fake.foreign
        assert not any(a[:2] == ["python", "-m"] or "pytest" in a for a in fake.argvs)

    def test_cleanup_is_by_captured_id_not_by_name(self, fake, capsys):
        _main(capsys)
        removes = [a for a in fake.argvs if a[:2] == ["docker", "rm"]]
        assert removes == [["docker", "rm", "-f", "-v", "abc123def456"]]


class TestSignals:
    @pytest.mark.parametrize(
        "name", [n for n in ("SIGINT", "SIGTERM", "SIGBREAK") if hasattr(signal, n)]
    )
    def test_a_supported_signal_exits_cleanly_and_cleans_up(self, name, fake, capsys, tmp_path):
        before = {n: signal.getsignal(getattr(signal, n)) for n in ("SIGINT", "SIGTERM")}
        fake.pytest_result = f"signal:{name}"
        fake.password_in_pytest_output = True
        code, message, out, err = _main(capsys)
        assert code == 128 + int(getattr(signal, name))
        assert fake.removed == ["abc123def456"]
        _clean(fake, tmp_path)
        _silent(fake, out, err, str(message))
        after = {n: signal.getsignal(getattr(signal, n)) for n in ("SIGINT", "SIGTERM")}
        assert after == before, "the caller's handlers are restored"

    def test_ctrl_c_during_the_suite_cleans_up(self, fake, capsys, tmp_path, monkeypatch):
        def interrupted(argv, **kw):
            if argv[0] != "docker":
                raise KeyboardInterrupt
            return fake(argv, **kw)

        monkeypatch.setattr(subprocess, "run", interrupted)
        with pytest.raises(KeyboardInterrupt):
            runner.main()
        assert fake.removed == ["abc123def456"]
        _clean(fake, tmp_path)


def test_sigkill_is_documented_as_unhandleable():
    doc = runner.__doc__
    assert "SIGKILL" in doc and "cannot be handled" in doc
    assert "docker ps -a --filter label=nexus-work-acceptance" in doc
