"""The SQLite backend job and the PostgreSQL job must not overlap.

A PostgreSQL-marked file that is not ignored by the backend job runs there too (CI has
Docker, so testcontainers starts), after thousands of unrelated tests in one process. Its
fixtures then run Alembic in-process and can leak state into later tests.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")


def _pytest_line(*needles: str) -> str:
    lines = [ln for ln in WORKFLOW.splitlines() if "pytest" in ln and all(n in ln for n in needles)]
    assert len(lines) == 1, lines
    return lines[0]


def _postgres_files() -> list[str]:
    return sorted(
        f"tests/{p.name}"
        for p in (ROOT / "tests").glob("test_*.py")
        if re.search(r"^pytestmark\s*=.*pytest\.mark\.postgres", p.read_text("utf-8"), re.M)
    )


def test_every_postgres_file_is_skipped_by_backend_and_run_by_postgres_job():
    backend = _pytest_line("tests/ ", "--ignore")
    postgres_job = _pytest_line("-v", "test_postgres_integration")
    files = _postgres_files()
    assert files, "no PostgreSQL test files found"
    for f in files:
        assert f"--ignore={f}" in backend, f"backend job would also run {f}"
        assert re.search(rf"(?<![\w/]){re.escape(f)}(?!\w)", postgres_job), f"{f} not run in CI"
