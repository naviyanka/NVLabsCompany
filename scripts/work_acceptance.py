#!/usr/bin/env python3
"""One command: run the company-work acceptance scenario on a throwaway PostgreSQL.

Starts an isolated pgvector container on a random local port, runs the acceptance suite
(``tests/test_work_execution_postgres.py``: migrate, seed two companies, sign in, create,
delegate, assign, execute, verify, restart, isolation, audit, failure scenarios) against it
with a fake model, prints a sanitized PASS/FAIL report (scenario names and results only: no
ids, prompts, deliverables or credentials), then removes the container. Nothing is left
behind: no container, volume, DB file or process. Needs Docker; makes no network calls
beyond pulling the image if it is missing.

    python scripts/work_acceptance.py

Exit code 0 means every scenario passed.

Safety properties (pinned by ``tests/test_work_acceptance_runner.py``):

* The container gets no name, so it cannot collide with anyone else's. It carries a per-run
  label, and its id is captured when it starts.
* Cleanup removes only containers that are this run's: the captured id plus whatever carries
  this run's label, and each is re-checked by inspecting its label before ``rm``. A container
  that is not provably this run's is reported and left alone, never removed.
* The database password never reaches a command line, a file or any output: docker reads it from
  this process's environment (``-e POSTGRES_PASSWORD`` with no value), and every message that
  could carry docker's or pytest's text is scrubbed of it first.
* SIGINT, SIGTERM and (on Windows) SIGBREAK run the same cleanup as a normal exit.
* SIGKILL, ``taskkill /F`` and a power loss cannot be handled by any process. A run killed that
  way leaves its labelled ``--rm`` container running until it is stopped; find it with
  ``docker ps -a --filter label=nexus-work-acceptance`` and remove it by id.
"""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITE = "tests/test_work_execution_postgres.py"
IMAGE = "pgvector/pgvector:pg16"


LABEL_KEY = "nexus-work-acceptance"
SECRET_ENV = "POSTGRES_PASSWORD"


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


def _docker(
    *args: str, secret: str = "", check: bool = True, env: dict[str, str] | None = None
) -> str:
    """Run docker. A failure exits with docker's stderr only (scrubbed of ``secret``):
    ``check=True`` would put the whole command line into a traceback."""
    try:
        done = subprocess.run(["docker", *args], capture_output=True, text=True, env=env)
    except OSError:
        raise SystemExit("FAIL: docker is not available") from None
    if check and done.returncode:
        detail = _scrub(done.stderr.strip()[-300:], secret)
        raise SystemExit(f"FAIL: docker {args[0]} failed: {detail}")
    return done.stdout.strip()


def _label_of(container: str) -> str:
    """The container's run token, or "" when it is gone or unlabelled."""
    return _docker(
        "inspect", "-f", '{{index .Config.Labels "' + LABEL_KEY + '"}}', container, check=False
    )


def _cleanup(token: str, captured: set[str]) -> None:
    """Remove this run's containers, by id, and only those provably this run's."""
    label = f"{LABEL_KEY}={token}"
    ids = captured | set(_docker("ps", "-aq", "--filter", f"label={label}", check=False).split())
    for container in sorted(ids):
        found = _label_of(container)
        if found == token:
            _docker("rm", "-f", "-v", container, check=False)
        elif found:
            print("WARNING: refusing to remove a container this run does not own")
        # An empty label is a container that is already gone (``--rm``): nothing to do.


def _install_signal_handlers() -> list[tuple[int, object]]:
    """Turn a termination signal into SystemExit so ``finally`` runs the cleanup."""

    def stop(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    previous = []
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is not None:
            previous.append((number, signal.signal(number, stop)))
    return previous


def _wait_ready(name: str, seconds: int = 60) -> None:
    """``name`` is the container id."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        probe = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", "postgres", "-h", "127.0.0.1"],
            capture_output=True,
        )
        if probe.returncode == 0:
            # The image restarts once after its init scripts; ask twice.
            time.sleep(1)
            again = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "postgres", "-h", "127.0.0.1"],
                capture_output=True,
            )
            if again.returncode == 0:
                return
        time.sleep(0.5)
    raise SystemExit("FAIL: the database container did not become ready")


def _report(junit: Path) -> int:
    rows = []
    for case in ET.parse(junit).getroot().iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            result = "FAIL"
        elif case.find("skipped") is not None:
            result = "SKIP"
        else:
            result = "PASS"
        rows.append((case.get("classname", "").rsplit(".", 1)[-1], case.get("name", ""), result))
    print("Company work acceptance (PostgreSQL, fake model, no network)")
    for group, name, result in rows:
        print(f"  {result:4}  {group}.{name}")
    failed = [r for r in rows if r[2] != "PASS"]
    verdict = "PASS" if rows and not failed else "FAIL"
    print(f"{verdict}: {len(rows) - len(failed)}/{len(rows)} scenarios passed")
    return 0 if verdict == "PASS" else 1


def main() -> int:
    # A per-run label is the ownership proof; the captured id is what gets removed.
    token = uuid.uuid4().hex
    password = secrets.token_hex(12)
    captured: set[str] = set()
    previous = _install_signal_handlers()
    try:
        name = _docker(
            "run", "-d", "--rm", "--label", f"{LABEL_KEY}={token}", "-e", SECRET_ENV,
            "-p", "127.0.0.1::5432", IMAGE,
            secret=password, env={**os.environ, SECRET_ENV: password},
        )  # fmt: skip
        captured.add(name)
        if _label_of(name) != token:
            captured.discard(name)  # not provably ours: never touch it
            raise SystemExit("FAIL: the started container is not this run's; refusing to use it")
        port = _docker("port", name, "5432/tcp").splitlines()[0].rsplit(":", 1)[1]
        _wait_ready(name)
        with tempfile.TemporaryDirectory(prefix="work-acceptance-") as tmp:
            junit = Path(tmp) / "result.xml"
            env = {
                **os.environ,
                "TEST_DATABASE_URL": f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres",
                "PYTHONPATH": str(ROOT / "src"),
            }
            run = subprocess.run(
                [sys.executable, "-m", "pytest", SUITE, "-q", "-p", "no:cacheprovider",
                 f"--junitxml={junit}", "--tb=no", "--basetemp", str(Path(tmp) / "pytest")],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )  # fmt: skip
            if not junit.exists():
                print("FAIL: the suite did not run")
                return 1
            code = _report(junit)
            return code or (1 if run.returncode else 0)
    except SystemExit as stop:
        if isinstance(stop.code, str):
            raise SystemExit(_scrub(stop.code, password)) from None
        raise
    except Exception as exc:  # no traceback: a locals-bearing frame could name the password
        raise SystemExit(f"FAIL: {type(exc).__name__}: {_scrub(str(exc), password)}") from None
    finally:
        _cleanup(token, captured)
        for number, handler in previous:
            signal.signal(number, handler)  # type: ignore[arg-type]


if __name__ == "__main__":
    raise SystemExit(main())
