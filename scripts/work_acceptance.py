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
"""

from __future__ import annotations

import os
import secrets
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


def _docker(*args: str, check: bool = True) -> str:
    done = subprocess.run(["docker", *args], capture_output=True, text=True, check=check)
    return done.stdout.strip()


def _wait_ready(name: str, seconds: int = 60) -> None:
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
    name = f"nexus-work-acceptance-{uuid.uuid4().hex[:8]}"
    password = secrets.token_hex(12)
    try:
        _docker(
            "run", "-d", "--rm", "--name", name, "-e", f"POSTGRES_PASSWORD={password}",
            "-p", "127.0.0.1::5432", IMAGE,
        )  # fmt: skip
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
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
