"""Every code path that writes a Task row is a known one.

A work order and its children belong to ``work_service`` and ``task_attempts``. This guard lists
the modules allowed to insert, update or delete Task rows and what keeps each one off marked
work. A new module that writes Tasks fails here until it is added with that reason, so a direct
mutation cannot slip around the canonical services unseen.
"""

from __future__ import annotations

import re
from pathlib import Path

from nexus.services import task_service

SRC = Path(__file__).resolve().parent.parent / "src" / "nexus"

# module -> why it may write Task rows, and what keeps it off work orders / work children
ALLOWED = {
    "services/work_service.py": "canonical work lifecycle (orders, children, review, cancel)",
    "runtime/task_attempts.py": "canonical attempt lifecycle (task status follows its attempt)",
    "services/task_service.py": "canonical ordinary-task creator: validates parent and agent",
    "services/manager_service.py": "delegate(): require_work_owner() before any write",
    "api/routes/tasks.py": "generic routes: write:task, PathCompanyId, _refuse_work_owned()",
    "api/routes/agents.py": "delete_agent(): write:agent, only terminal tasks lose their owner",
    "runtime/orchestrator.py": "legacy goal loop: _without_work_owned() / work_spec filters",
    "runtime/executor.py": "legacy executor: work-owned tasks never re-routed or decomposed",
    "demo/seed.py": "demo data for a fresh company, not a request path",
}

WRITES = re.compile(
    r"(?:\bsa_update|\bupdate|\bsa_delete|\bdelete)\(\s*Task\s*\)"  # bulk UPDATE / DELETE
    r"|(?<![\w.])Task\("  # a new Task row
    r"|\b(?:task|child|subtask|parent)\.(?:assigned_agent_id|status)\s*=(?!=)"  # ORM field write
)


def _writers() -> dict[str, int]:
    found = {}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("models/"):
            continue
        hits = len(WRITES.findall(path.read_text(encoding="utf-8")))
        if hits:
            found[rel] = hits
    return found


def test_only_known_modules_write_task_rows():
    unknown = sorted(set(_writers()) - set(ALLOWED))
    assert not unknown, (
        f"{unknown} write Task rows. Route the change through work_service / task_attempts / "
        "TaskService, or add the module to ALLOWED with the guard that keeps it off work."
    )


def test_the_allowlist_has_no_stale_entries():
    assert sorted(set(ALLOWED) - set(_writers())) == []


def test_task_service_has_no_unscoped_mutators():
    """Its old assign/status/complete/fail helpers took a bare task id with no company and no
    work guard. Nothing called them; they are gone so nothing can start to."""
    for name in ("assign_task", "update_status", "complete_task", "fail_task"):
        assert not hasattr(task_service.TaskService, name), name
