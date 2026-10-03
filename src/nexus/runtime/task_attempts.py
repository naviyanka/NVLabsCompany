"""Employee work execution: durable task attempts, from start to verified completion.

A work task (a ``Task`` with a ``work_spec``) is done by its assigned employee
in a ``TaskAttempt``. The flow, all of it on the production path:

1. ``start_attempt`` (``POST /tasks/{id}/attempts``) validates the task, the
   employee and the assignment and stores a ``queued`` attempt. A repeated
   idempotency key, or a start while an attempt is active, returns that
   attempt instead of making a second one.
2. The attempt worker claims it with one conditional UPDATE and a lease, like
   chat turns. The task becomes ``in_progress``.
3. Preparation binds an agent session and an isolated git worktree to the
   attempt: the session's held worktree is reused, otherwise one is created
   through ``WorktreeService`` and activated. There is no fallback to the
   repository's own checkout: the chat execution path refuses to run a
   session whose worktree is unusable (``session_workspace``).
4. The employee runs as one durable chat turn of that session, with a bounded
   prompt and the server-chosen work mode (write or read-only). No database
   transaction is open while the CLI runs; the attempt's lease is renewed in
   short transactions and the turn has its own lease.
5. Progress: in write mode the employee keeps ``.nexus/report.json`` updated.
   Each report carries a ``seq``; an update is stored only if its ``seq`` is
   higher than the stored one, so an older report never replaces a newer one.
6. When the turn ends, the deterministic verifier decides. The CLI must have
   exited 0, the final structured report must be present and valid, every
   deliverable must be a regular file inside the worktree, every verification
   command must pass, every acceptance criterion must hold and no blocker may
   remain. A non-empty reply alone never completes a work task. No evaluator
   model runs, so nothing can override a failed deterministic check.
7. ``_finish`` is the one place an attempt and its task reach a terminal
   status.

Side effects a retry or a recovered worker could repeat go through the
``WorkEffect`` ledger under deterministic keys:

- ``evidence:<attempt>`` (file_write_batch): verification logs, the artifact
  manifest and the verification record. Reused on recovery, never rerun
  once recorded.
- ``commit:<attempt>`` (git_commit): the attempt's commit, found again by the
  ``Nexus-Effect`` trailer if the worker died after committing.
- ``notify:<attempt>`` (notification): the notification for a failed or
  blocked attempt, written in the finishing transaction.
- ``pr_create`` and ``tool_invocation`` keys are not used here: this flow
  opens no pull requests, and the CLI's own tool calls happen inside the CLI.

Retry rule: a retry is a new attempt with the next number. While the task's
earlier attempt ended failed, blocked, cancelled or expired, its session and
worktree stay open and the retry reuses them, so the employee continues from
the work already there. The earlier attempt's row, reports, manifest and logs
are never rewritten. A completed attempt ends its session and hands the
worktree to review (``release_session_worktree``).

A cancelled or expired attempt returns its task to ``pending``; the attempt
itself keeps the reason.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
import weakref
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError

from nexus.models.task_attempt import (
    ACTIVE_ATTEMPT_STATUSES,
    LEASED_ATTEMPT_STATUSES,
    TERMINAL_ATTEMPT_STATUSES,
    TaskAttempt,
    WorkEffect,
)

logger = logging.getLogger(__name__)

from nexus.runtime import work_hints  # noqa: E402
from nexus.runtime.chat_turns import WORKER_ID  # noqa: E402 -- one identity per process

STATS: Counter[str] = Counter()

# Directories the server and the CLIs keep in a worktree; never deliverables,
# never committed as the employee's work.
EXCLUDED_DIRS = (".nexus", ".claude")
# Caches that running Python or pytest leaves anywhere in the tree. They are
# never work: not artifacts, not a read-only violation, never committed.
GENERATED_DIRS = ("__pycache__", ".pytest_cache")
REPORT_FILE = ".nexus/report.json"
SYSTEM_ACTOR = "system:task-attempts"
MAX_ARTIFACTS = 200
MAX_REPORT_BYTES = 64_000
MAX_DIFF_CHARS = 20_000
MAX_DELIVERABLE_CHARS = 4000
DEFAULT_MAX_ATTEMPTS = 2  # a text task: the first try and one retry
MAX_SEQ = 1_000_000
_SWEEP_EVERY_SECONDS = 15.0
_BATCH = 50
_PYTEST_CONFIGS = ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
_PYTEST_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)")
_FINAL_STATES = ("completed", "blocked", "failed")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017


def _settings() -> Any:
    from nexus.config import settings

    return settings


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# ---------------------------------------------------------------------------
# Work spec and report contract
# ---------------------------------------------------------------------------


def _is_work(path: str) -> bool:
    """Whether a changed path is the employee's work, not server state or a cache."""
    parts = PurePosixPath(path).parts
    return parts[0] not in EXCLUDED_DIRS and not any(p in GENERATED_DIRS for p in parts)


def _relative(path: str, excluded: tuple[str, ...] = EXCLUDED_DIRS) -> str:
    """A worktree-relative POSIX path; never absolute, never ``..``, never an option."""
    text = path.replace("\\", "/")
    rel = PurePosixPath(text)
    if (
        not path
        or len(path) > 300
        or rel.is_absolute()
        or PureWindowsPath(path).anchor
        or ".." in rel.parts
        or path.startswith("-")
        or any(ch in path for ch in "\0\r\n")
        or rel.parts[0] in excluded
    ):
        raise ValueError(f"not a safe relative path: {path!r}")
    return rel.as_posix()


RelPath = Annotated[str, AfterValidator(_relative)]


class VerificationStep(BaseModel):
    """One command from the server's catalog. The spec never names an executable."""

    model_config = ConfigDict(extra="forbid")

    command: Literal["pytest", "py_compile"]
    paths: list[RelPath] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _paths_for_compile(self) -> VerificationStep:
        if self.command == "py_compile" and not self.paths:
            raise ValueError("py_compile needs at least one path")
        return self


class Criterion(BaseModel):
    """An acceptance criterion the verifier can check without a model."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["file_exists", "command_passes", "pattern_count", "report_contains"]
    path: RelPath | None = None
    command: Literal["pytest", "py_compile"] | None = None
    pattern: str | None = Field(default=None, min_length=1, max_length=200)
    min_count: int = Field(default=1, ge=1, le=1000)
    text: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _required(self) -> Criterion:
        need = {
            "file_exists": ("path",),
            "command_passes": ("command",),
            "pattern_count": ("path", "pattern"),
            "report_contains": ("text",),
        }[self.kind]
        missing = [name for name in need if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.kind} needs {', '.join(missing)}")
        return self

    def label(self) -> str:
        if self.kind == "file_exists":
            return f"{self.path} exists"
        if self.kind == "command_passes":
            return f"{self.command} passes"
        if self.kind == "pattern_count":
            return f"{self.path} contains {self.pattern!r} at least {self.min_count} times"
        return f"report mentions {self.text!r}"


class WorkSpec(BaseModel):
    """What a work task asks for and how the server checks it."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["write", "read_only", "text"] = "write"
    # Required for write/read_only; a text task has no repository.
    repository_id: uuid.UUID | None = None
    base_ref: str = Field(default="HEAD", min_length=1, max_length=200)
    # Text mode only: what the manager expects back, and the attempt/size caps.
    expected_deliverable: str | None = Field(default=None, max_length=500)
    max_deliverable_chars: int | None = Field(default=None, ge=100, le=MAX_DELIVERABLE_CHARS)
    max_attempts: int | None = Field(default=None, ge=1, le=5)
    review_of_task_id: uuid.UUID | None = None
    objective: str | None = Field(default=None, max_length=4000)
    deliverables: list[RelPath] = Field(default_factory=list, max_length=50)
    verification: list[VerificationStep] = Field(default_factory=list, max_length=10)
    acceptance_criteria: list[Criterion] = Field(default_factory=list, max_length=30)
    # The CLI adapter's own limit (600 s by default) applies as well.
    timeout_seconds: int = Field(default=600, ge=30, le=3600)

    @model_validator(mode="after")
    def _consistent(self) -> WorkSpec:
        if self.base_ref.startswith("-") or any(c.isspace() for c in self.base_ref):
            raise ValueError("base_ref is not a ref")
        if self.mode == "text":
            if not self.objective:
                raise ValueError("a text task needs an objective")
            if self.repository_id is not None or self.deliverables or self.verification:
                raise ValueError("a text task has no repository, deliverable paths or checks")
            if self.review_of_task_id is not None:
                raise ValueError("review_of_task_id is for read_only tasks")
            return self
        if self.repository_id is None:
            raise ValueError("a write or read_only task needs a repository_id")
        if self.expected_deliverable or self.max_deliverable_chars or self.max_attempts:
            raise ValueError("expected_deliverable and the caps are for text tasks")
        if self.mode == "write":
            if not self.deliverables:
                raise ValueError("a write task needs at least one deliverable")
            if not self.verification:
                raise ValueError("a write task needs at least one verification step")
            if self.review_of_task_id is not None:
                raise ValueError("review_of_task_id is for read_only tasks")
        elif self.deliverables:
            raise ValueError("a read_only task cannot have deliverables")
        commands = {step.command for step in self.verification}
        for criterion in self.acceptance_criteria:
            if criterion.kind == "command_passes" and criterion.command not in commands:
                raise ValueError(f"{criterion.command} is not a verification step")
        return self


WORK_ORDER_KIND = "work_order"


def is_work_order_spec(raw: Any) -> bool:
    """The one place that reads the work-order marker (``{"kind": "work_order"}``).

    A ``WorkSpec`` forbids the ``kind`` key, so only the work service can write it. Anything
    else, an unknown kind or a non-dict included, is not a work order.
    """
    return isinstance(raw, dict) and raw.get("kind") == WORK_ORDER_KIND


def parse_work_spec(raw: Any) -> WorkSpec:
    """Validate a stored or submitted work spec (422 INVALID_WORK_SPEC)."""
    try:
        return WorkSpec.model_validate(raw)
    except ValidationError as exc:
        errors = [
            {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg")}
            for e in exc.errors()[:10]
        ]
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_WORK_SPEC", "message": "Invalid work spec", "errors": errors},
        ) from None


def _clip(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, list):
        return [str(v)[:500] for v in value[:50]]
    return value


class EmployeeReport(BaseModel):
    """The structured report contract. Chat prose is never a substitute."""

    model_config = ConfigDict(extra="ignore")

    state: Literal["working", "blocked", "verifying", "completed", "failed"]
    summary: str = ""
    progress_percent: int = Field(default=0, ge=0, le=100)
    current_step: str = ""
    completed_steps: list[str] = Field(default_factory=list)
    next_step: str = ""
    blockers: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    tests_run: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_help: bool = False
    eta: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _bounded(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = {k: _clip(v, 2000) for k, v in data.items()}
        for key in ("progress_percent", "confidence"):
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                top = 100 if key == "progress_percent" else 1.0
                data[key] = min(max(value, 0), top)
                if key == "progress_percent":
                    data[key] = int(data[key])
        if data.get("eta") is not None:
            data["eta"] = str(data["eta"])[:100]
        return data

    @model_validator(mode="after")
    def _evidence(self) -> EmployeeReport:
        if self.state == "blocked" and not self.blockers:
            raise ValueError("a blocked report needs a reason in blockers")
        if self.state == "completed" and not (self.artifacts or self.tests_run):
            raise ValueError("a completed report needs artifacts or tests_run")
        return self


def find_final_report(text: str) -> dict[str, Any] | None:
    """The last top-level JSON object with a ``state`` key in the reply, if any."""
    tail = text[-50_000:]
    decoder = json.JSONDecoder()
    found = None
    i = tail.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(tail, i)
        except ValueError:
            i = tail.find("{", i + 1)
            continue
        if isinstance(obj, dict) and "state" in obj:
            found = obj
        i = tail.find("{", end)
    return found


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def evidence_root(company_id: uuid.UUID) -> Path:
    template = _settings().task_attempt_evidence_root
    if "{company_id}" not in template:
        raise RuntimeError("task_attempt_evidence_root must contain {company_id}")
    return Path(template.replace("{company_id}", str(company_id))).expanduser().resolve()


def inside(root: Path, rel: str, excluded: tuple[str, ...] = EXCLUDED_DIRS) -> Path | None:
    """``root/rel`` if it stays inside ``root`` without passing through a link.

    Paths under ``excluded`` are refused; only the server passes ``()`` to reach
    its own progress file.
    """
    from nexus.governance.fs_roots import is_link

    try:
        rel = _relative(rel, excluded)
    except ValueError:
        return None
    root = root.resolve()
    path = root
    for part in PurePosixPath(rel).parts:
        path = path / part
        if is_link(path):
            return None
    if not path.resolve().is_relative_to(root):
        return None
    return path


def _redact(text: str, root: Path) -> str:
    from nexus.adapters.cli_registry import _redact_home

    for form in {str(root), root.as_posix()}:
        text = text.replace(form, "<worktree>")
    return _redact_home(text)


def _kind(rel: str) -> str:
    name = PurePosixPath(rel).name
    if rel.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if name.endswith((".md", ".rst", ".txt")):
        return "doc"
    if name.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java", ".c", ".h", ".cpp")):
        return "source"
    return "other"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Views and small helpers
# ---------------------------------------------------------------------------


SUMMARY_VIEW_CHARS = 500


def bounded_summary(text: str | None) -> str | None:
    """A stored deliverable cut to a summary: what a model or tool may be shown."""
    return text[:SUMMARY_VIEW_CHARS] if text else text


def attempt_view(a: TaskAttempt, *, full: bool = False) -> dict[str, Any]:
    """The API shape of an attempt. No absolute paths, no environment.

    ``output_summary`` is cut to :data:`SUMMARY_VIEW_CHARS` unless ``full``: only a route that
    has checked ``work_service.can_view_work_deliverable`` passes it, never a model tool.
    """

    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    def sid(value: uuid.UUID | None) -> str | None:
        return str(value) if value else None

    return {
        "id": str(a.id),
        "company_id": str(a.company_id),
        "task_id": str(a.task_id),
        "agent_id": str(a.agent_id),
        "session_id": sid(a.session_id),
        "chat_turn_id": sid(a.chat_turn_id),
        "attempt_number": a.attempt_number,
        "idempotency_key": a.idempotency_key,
        "status": a.status,
        "active": a.status in ACTIVE_ATTEMPT_STATUSES,
        "execution_id": a.execution_id,
        "workspace_id": sid(a.workspace_id),
        "repository_id": sid(a.repository_id),
        "worktree_id": sid(a.worktree_id),
        "claimed_by": a.claimed_by,
        "lease_expires_at": iso(a.lease_expires_at),
        "recoveries": a.recoveries,
        "cancel_requested": a.cancel_requested_at is not None,
        "cancelled_by": a.cancelled_by,
        "created_by": a.created_by,
        "queued_at": iso(a.queued_at),
        "started_at": iso(a.started_at),
        "completed_at": iso(a.completed_at),
        "updated_at": iso(a.updated_at),
        "output_summary": a.output_summary if full else bounded_summary(a.output_summary),
        "completion_reason": a.completion_reason,
        "error_code": a.error_code,
        "error": a.error,
        "report": a.report,
        "report_seq": a.report_seq,
        "artifacts": a.artifacts or [],
        "verification": a.verification,
        "usage": a.usage,
    }


def _scoped(attempt_id: uuid.UUID, company_id: uuid.UUID) -> Any:
    return and_(TaskAttempt.id == attempt_id, TaskAttempt.company_id == company_id)


async def _get(db: Any, company_id: uuid.UUID, attempt_id: uuid.UUID) -> TaskAttempt | None:
    return (
        await db.execute(select(TaskAttempt).where(_scoped(attempt_id, company_id)))
    ).scalar_one_or_none()


async def get_attempt(company_id: uuid.UUID, attempt_id: uuid.UUID) -> TaskAttempt | None:
    from nexus.database import tenant_session

    async with tenant_session(company_id) as db:
        return await _get(db, company_id, attempt_id)


async def _audit(
    db: Any, a: TaskAttempt, action: str, actor_type: str = "system", **details: Any
) -> None:
    from nexus.governance.audit_service import record_audit

    await record_audit(
        a.company_id,
        action,
        actor_type=actor_type,
        actor_id=details.pop("actor", None) or SYSTEM_ACTOR,
        resource_type="task_attempt",
        resource_id=str(a.id),
        details={
            "task_id": str(a.task_id),
            "agent_id": str(a.agent_id),
            "attempt_number": a.attempt_number,
            "execution_id": a.execution_id,
            **details,
        },
        db=db,
    )


async def _publish(a: TaskAttempt, **extra: Any) -> None:
    from nexus.services.session_service import publish_session_event

    await publish_session_event(
        "task.attempt",
        a.company_id,
        {
            "task_id": str(a.task_id),
            "attempt_id": str(a.id),
            "agent_id": str(a.agent_id),
            "session_id": str(a.session_id) if a.session_id else None,
            "attempt_status": a.status,
            "execution_id": a.execution_id,
            "report_seq": a.report_seq,
            **extra,
        },
    )


def _system_principal(company_id: uuid.UUID) -> Any:
    from nexus.auth.principal import Principal

    # Least privilege that can create and activate worktrees.
    return Principal(kind="service", company_id=company_id, role="manager", label=SYSTEM_ACTOR)


def check_employee(agent: Any, mode: str) -> None:
    """The employee must be a CLI employee whose backend can do this kind of work.

    A text task needs no CLI: any active company employee can write the answer.
    """
    from nexus.adapters.cli_registry import get_cli_registry

    if mode == "text":
        if agent.status in ("terminated", "archived", "paused"):
            raise _error(422, "EMPLOYEE_UNAVAILABLE", "The employee cannot take work")
        return

    backend_id = (agent.adapter_config or {}).get("backend")
    info = get_cli_registry().get_backend(backend_id) if backend_id else None
    if agent.adapter_type != "cli" or info is None or not info.execution_supported:
        raise _error(422, "EMPLOYEE_NOT_CLI", "Work tasks run on a CLI employee that can execute")
    try:
        info.work_mode_args(mode)
    except ValueError:
        raise _error(
            422, "EMPLOYEE_NOT_CLI", f"The {backend_id} backend has no {mode} work mode"
        ) from None


# ---------------------------------------------------------------------------
# Start, cancel, retry
# ---------------------------------------------------------------------------


async def _load_task(db: Any, company_id: uuid.UUID, task_id: uuid.UUID) -> Any:
    from nexus.models.task import Task

    task = (
        await db.execute(select(Task).where(Task.id == task_id, Task.company_id == company_id))
    ).scalar_one_or_none()
    if task is None:
        raise _error(404, "TASK_NOT_FOUND", f"Task {task_id} not found")
    return task


async def _by_key(db: Any, company_id: uuid.UUID, task_id: uuid.UUID, key: str) -> Any:
    return (
        await db.execute(
            select(TaskAttempt).where(
                TaskAttempt.company_id == company_id,
                TaskAttempt.task_id == task_id,
                TaskAttempt.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()


async def _active(db: Any, company_id: uuid.UUID, task_id: uuid.UUID) -> Any:
    return (
        await db.execute(
            select(TaskAttempt).where(
                TaskAttempt.company_id == company_id,
                TaskAttempt.task_id == task_id,
                TaskAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
            )
        )
    ).scalar_one_or_none()


async def start_attempt(
    db: Any,
    company_id: uuid.UUID,
    task_id: uuid.UUID,
    principal: Any,
    *,
    agent_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    audit_details: dict[str, Any] | None = None,
) -> tuple[TaskAttempt, bool]:
    """Queue an attempt, or return the one this start already made or attaches to.

    ``audit_details`` are added to the ``task.attempt_queued`` row, so a caller
    records why it started the attempt without a second audit write.
    Returns ``(attempt, created)``. Commits.
    """
    from nexus.models.agent import Agent

    task = await _load_task(db, company_id, task_id)
    if not task.work_spec:
        raise _error(422, "TASK_NOT_WORK", "The task has no work spec")
    if is_work_order_spec(task.work_spec):
        raise _error(409, "WORK_ORDER_NOT_EXECUTABLE", "A work order is delegated, not executed")
    spec = parse_work_spec(task.work_spec)
    if idempotency_key:
        existing = await _by_key(db, company_id, task_id, idempotency_key)
        if existing is not None:
            return existing, False
    active = await _active(db, company_id, task_id)
    if active is not None:
        if agent_id is not None and agent_id != active.agent_id:
            raise _error(409, "ATTEMPT_ACTIVE", "Another employee's attempt is active")
        return active, False
    if task.status == "completed":
        raise _error(409, "TASK_ALREADY_COMPLETED", "The task is already completed")
    if task.assigned_agent_id is None:
        raise _error(409, "TASK_NOT_ASSIGNED", "Assign the task to an employee first")
    agent_id = agent_id or task.assigned_agent_id
    if agent_id != task.assigned_agent_id:
        raise _error(
            409,
            "EMPLOYEE_NOT_ASSIGNED",
            "Only the assigned employee works on the task; reassign it first",
        )
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    ).scalar_one_or_none()
    if agent is None:
        raise _error(404, "AGENT_NOT_FOUND", f"Agent {agent_id} not found")
    check_employee(agent, spec.mode)

    number = (
        await db.execute(
            select(func.max(TaskAttempt.attempt_number)).where(
                TaskAttempt.company_id == company_id, TaskAttempt.task_id == task_id
            )
        )
    ).scalar() or 0
    if spec.mode == "text" and number >= (spec.max_attempts or DEFAULT_MAX_ATTEMPTS):
        raise _error(409, "ATTEMPTS_EXHAUSTED", f"The task has used its {number} attempts")
    attempt = TaskAttempt(
        company_id=company_id,
        task_id=task_id,
        agent_id=agent_id,
        attempt_number=number + 1,
        idempotency_key=idempotency_key or uuid.uuid4().hex,
        repository_id=spec.repository_id,
        created_by=principal.display_name,
        context_snapshot={
            "title": task.title[:500],
            "description": (task.description or "")[:4000],
            "work_spec": spec.model_dump(mode="json"),
        },
    )
    try:
        async with db.begin_nested():
            db.add(attempt)
    except IntegrityError:
        # A concurrent start won: same key, same number, or already active.
        found = (
            await _by_key(db, company_id, task_id, idempotency_key) if idempotency_key else None
        ) or await _active(db, company_id, task_id)
        if found is None:
            raise _error(409, "ATTEMPT_CONFLICT", "A concurrent start conflicted; retry") from None
        return found, False
    await _audit(
        db,
        attempt,
        "task.attempt_queued",
        actor_type=principal.kind,
        actor=principal.display_name,
        **(audit_details or {}),
    )
    await db.commit()
    STATS["queued"] += 1
    await _publish(attempt)
    get_worker().wake(company_id)
    return attempt, True


async def cancel_attempt(
    db: Any, company_id: uuid.UUID, task_id: uuid.UUID, attempt_id: uuid.UUID, principal: Any
) -> TaskAttempt:
    """Cancel this attempt only. Idempotent; a finished attempt is returned unchanged."""
    from nexus.runtime import chat_turns

    attempt = await _get(db, company_id, attempt_id)
    if attempt is None or attempt.task_id != task_id:
        raise _error(404, "ATTEMPT_NOT_FOUND", f"Attempt {attempt_id} not found")
    if attempt.status in TERMINAL_ATTEMPT_STATUSES:
        return attempt
    by = principal.display_name
    now = _now()
    if attempt.status == "queued" or (attempt.status == "verifying" and attempt.claimed_by is None):
        # Queued, or a submitted deliverable no worker holds: nothing will finish it later.
        done = await _finish_in(
            db,
            attempt,
            "cancelled",
            "cancelled",
            None,
            TaskAttempt.status == attempt.status,
            TaskAttempt.claimed_by.is_(None),
            cancel_requested_at=now,
            cancelled_by=by,
            error_code="CANCELLED",
        )
        if done:
            await db.commit()
            await db.refresh(attempt)
            await _publish(attempt)
            return attempt
    await db.execute(
        update(TaskAttempt)
        .where(
            _scoped(attempt_id, company_id),
            TaskAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
            TaskAttempt.cancel_requested_at.is_(None),
        )
        .values(cancel_requested_at=now, cancelled_by=by, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(attempt)
    await _audit(db, attempt, "task.attempt_cancel_requested", actor_type=principal.kind, actor=by)
    await db.commit()
    if attempt.chat_turn_id is not None and attempt.session_id is not None:
        with contextlib.suppress(HTTPException):
            await chat_turns.request_cancel(
                db, company_id, attempt.session_id, attempt.chat_turn_id, by
            )
    get_worker().poke(attempt.id)
    await _publish(attempt)
    return attempt


async def retry_attempt(
    db: Any,
    company_id: uuid.UUID,
    task_id: uuid.UUID,
    attempt_id: uuid.UUID,
    principal: Any,
    *,
    idempotency_key: str | None = None,
) -> tuple[TaskAttempt, bool]:
    """Start the next attempt after a failed, blocked, cancelled or expired one."""
    attempt = await _get(db, company_id, attempt_id)
    if attempt is None or attempt.task_id != task_id:
        raise _error(404, "ATTEMPT_NOT_FOUND", f"Attempt {attempt_id} not found")
    latest = (
        await db.execute(
            select(func.max(TaskAttempt.attempt_number)).where(
                TaskAttempt.company_id == company_id, TaskAttempt.task_id == task_id
            )
        )
    ).scalar()
    key = idempotency_key or f"retry:{attempt.id}"
    if attempt.attempt_number != latest:
        # The retry this key made is the latest; hand it back.
        existing = await _by_key(db, company_id, task_id, key)
        if existing is not None:
            return existing, False
        raise _error(409, "ATTEMPT_NOT_LATEST", "Only the latest attempt can be retried")
    if attempt.status in ACTIVE_ATTEMPT_STATUSES:
        raise _error(409, "ATTEMPT_ACTIVE", "The attempt is still active")
    if attempt.status not in ("failed", "blocked", "cancelled", "expired"):
        raise _error(409, "ATTEMPT_NOT_RETRYABLE", f"A {attempt.status} attempt is not retried")
    return await start_attempt(
        db, company_id, task_id, principal, agent_id=None, idempotency_key=key
    )


# ---------------------------------------------------------------------------
# Claim, lease, finish
# ---------------------------------------------------------------------------


async def claim(
    attempt_id: uuid.UUID, company_id: uuid.UUID, worker_id: str = WORKER_ID
) -> TaskAttempt | None:
    """Claim a queued attempt; None if it is not claimable. Starts the task."""
    from nexus.database import tenant_session
    from nexus.models.task import Task

    now = _now()
    async with tenant_session(company_id) as db:
        res = await db.execute(
            update(TaskAttempt)
            .where(
                _scoped(attempt_id, company_id),
                TaskAttempt.status == "queued",
                TaskAttempt.cancel_requested_at.is_(None),
            )
            .values(
                status="claimed",
                claimed_by=worker_id,
                lease_expires_at=now + timedelta(seconds=_settings().task_attempt_lease_seconds),
                started_at=func.coalesce(TaskAttempt.started_at, now),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            await db.rollback()
            return None
        attempt = await _get(db, company_id, attempt_id)
        await db.execute(
            update(Task)
            .where(
                Task.id == attempt.task_id,
                Task.company_id == company_id,
                Task.status.not_in(("completed", "cancelled")),
            )
            .values(
                status="in_progress",
                started_at=func.coalesce(Task.started_at, now),
                completion_reason=None,
                error=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        await _audit(db, attempt, "task.attempt_claimed", worker=worker_id)
        await db.commit()
    STATS["claimed"] += 1
    await _publish(attempt)
    return attempt


async def renew(attempt: TaskAttempt, worker_id: str) -> str:
    """Extend the lease. Returns ``ok``, ``cancelled`` or ``lost``."""
    from nexus.database import tenant_session

    now = _now()
    async with tenant_session(attempt.company_id) as db:
        res = await db.execute(
            update(TaskAttempt)
            .where(
                _scoped(attempt.id, attempt.company_id),
                TaskAttempt.claimed_by == worker_id,
                TaskAttempt.status.in_(LEASED_ATTEMPT_STATUSES),
            )
            .values(
                lease_expires_at=now + timedelta(seconds=_settings().task_attempt_lease_seconds),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        cancel_at = (
            await db.execute(
                select(TaskAttempt.cancel_requested_at).where(
                    _scoped(attempt.id, attempt.company_id)
                )
            )
        ).scalar_one_or_none()
        await db.commit()
    if res.rowcount != 1:
        return "lost"
    return "cancelled" if cancel_at is not None else "ok"


async def _safe_renew(attempt: TaskAttempt, worker_id: str) -> str:
    try:
        return await renew(attempt, worker_id)
    except Exception:  # noqa: BLE001 -- if the lease lapses, recovery decides
        logger.warning("lease renewal failed for task attempt %s", attempt.id, exc_info=True)
        return "ok"


async def _update_held(attempt: TaskAttempt, worker_id: str, **values: Any) -> bool:
    """Write ``values`` while this worker still holds the attempt."""
    from nexus.database import tenant_session

    async with tenant_session(attempt.company_id) as db:
        res = await db.execute(
            update(TaskAttempt)
            .where(
                _scoped(attempt.id, attempt.company_id),
                TaskAttempt.claimed_by == worker_id,
                TaskAttempt.status.in_(LEASED_ATTEMPT_STATUSES),
            )
            .values(updated_at=_now(), **values)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    if res.rowcount == 1:
        for key, value in values.items():
            setattr(attempt, key, value)
        return True
    return False


_TASK_OUTCOME = {
    "completed": "completed",
    "failed": "failed",
    "blocked": "blocked",
    "cancelled": "pending",
    "expired": "pending",
}


async def _finish_in(
    db: Any,
    attempt: TaskAttempt,
    attempt_status: str,
    reason: str | None,
    worker_id: str | None,
    *conditions: Any,
    **values: Any,
) -> bool:
    """Move an active attempt and its task to their terminal state. Does not commit.

    The one path every terminal transition takes. ``worker_id`` limits it to
    the holder of the lease; recovery passes None and its own conditions.
    """
    from nexus.models.notification import Notification
    from nexus.models.task import Task

    now = _now()
    where = [
        _scoped(attempt.id, attempt.company_id),
        TaskAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
    ]
    if worker_id is not None:
        where.append(TaskAttempt.claimed_by == worker_id)
    res = await db.execute(
        update(TaskAttempt)
        .where(*where, *conditions)
        .values(
            status=attempt_status,
            completion_reason=reason,
            completed_at=now,
            updated_at=now,
            lease_expires_at=None,
            **values,
        )
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        await db.rollback()
        return False
    fresh = await _get(db, attempt.company_id, attempt.id)
    await db.refresh(fresh)

    task_values: dict[str, Any] = {"status": _TASK_OUTCOME[attempt_status], "updated_at": now}
    if attempt_status == "completed":
        task_values.update(
            completion_reason="goal",
            completed_at=now,
            error=None,
            result=(fresh.output_summary or "")[:4000] or None,
        )
    elif attempt_status in ("failed", "blocked"):
        task_values.update(
            completion_reason=reason, completed_at=None, error=(fresh.error or "")[:4000] or None
        )
    else:
        task_values.update(completion_reason=None, completed_at=None)
    await db.execute(
        update(Task)
        .where(
            Task.id == fresh.task_id,
            Task.company_id == fresh.company_id,
            Task.status.not_in(("completed", "cancelled")),
        )
        .values(**task_values)
        .execution_options(synchronize_session=False)
    )
    await _audit(
        db,
        fresh,
        f"task.attempt_{attempt_status}",
        actor_type="agent" if attempt_status == "completed" else "system",
        completion_reason=reason,
        error_code=fresh.error_code,
    )
    if attempt_status in ("failed", "blocked"):
        key = f"notify:{fresh.id}"
        try:
            async with db.begin_nested():
                db.add(
                    WorkEffect(
                        company_id=fresh.company_id,
                        task_id=fresh.task_id,
                        attempt_id=fresh.id,
                        kind="notification",
                        effect_key=key,
                        status="done",
                    )
                )
                db.add(
                    Notification(
                        company_id=fresh.company_id,
                        agent_id=fresh.agent_id,
                        title=f"Employee task attempt {attempt_status}",
                        description=(fresh.error or reason or attempt_status)[:500],
                        notification_type="error" if attempt_status == "failed" else "warning",
                        module="tasks",
                        priority="high",
                        notification_metadata={
                            "task_id": str(fresh.task_id),
                            "attempt_id": str(fresh.id),
                            "error_code": fresh.error_code,
                            "completion_reason": reason,
                        },
                    )
                )
        except IntegrityError:
            pass  # already notified for this attempt
    if attempt_status == "completed" and fresh.session_id is not None:
        from nexus.models.agent_session import AgentSessionRecord
        from nexus.services import session_service
        from nexus.services.worktree_service import release_session_worktree

        record = (
            await db.execute(
                select(AgentSessionRecord).where(
                    AgentSessionRecord.id == fresh.session_id,
                    AgentSessionRecord.company_id == fresh.company_id,
                )
            )
        ).scalar_one_or_none()
        if record is not None and record.status in session_service.OPEN_STATUSES:
            session_service.transition(record, "completed")
            await release_session_worktree(db, record)
    if (fresh.context_snapshot or {}).get("work_spec", {}).get("mode") == "text":
        from nexus.services import work_service

        await work_service.after_terminal(db, fresh)
    attempt.status = attempt_status
    return True


async def _finish(
    attempt: TaskAttempt,
    worker_id: str | None,
    attempt_status: str,
    reason: str | None,
    *conditions: Any,
    **values: Any,
) -> bool:
    from nexus.database import tenant_session

    async with tenant_session(attempt.company_id) as db:
        done = await _finish_in(
            db, attempt, attempt_status, reason, worker_id, *conditions, **values
        )
        if not done:
            return False
        await db.commit()
        fresh = await _get(db, attempt.company_id, attempt.id)
    STATS[attempt_status] += 1
    await _publish(fresh)
    return True


async def release(attempt: TaskAttempt, worker_id: str, reason: str) -> bool:
    """Hand an attempt this worker holds back to the queue (graceful shutdown)."""
    from nexus.database import tenant_session

    async with tenant_session(attempt.company_id) as db:
        res = await db.execute(
            update(TaskAttempt)
            .where(
                _scoped(attempt.id, attempt.company_id),
                TaskAttempt.claimed_by == worker_id,
                TaskAttempt.status.in_(LEASED_ATTEMPT_STATUSES),
            )
            .values(status="queued", claimed_by=None, lease_expires_at=None, updated_at=_now())
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            await db.rollback()
            return False
        await _audit(db, attempt, "task.attempt_recovered", reason=reason, worker=worker_id)
        await db.commit()
    return True


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


async def _recover(attempt: TaskAttempt, now: datetime) -> str:
    """Resolve one leased attempt whose lease expired."""
    from nexus.database import tenant_session

    lapsed = TaskAttempt.lease_expires_at < now
    if attempt.cancel_requested_at is not None:
        done = await _finish(
            attempt, None, "cancelled", "cancelled", lapsed, error_code="CANCELLED"
        )
        return "cancelled" if done else "skipped"
    if attempt.recoveries >= _settings().task_attempt_max_recoveries:
        done = await _finish(
            attempt,
            None,
            "failed",
            "error",
            lapsed,
            error_code="ATTEMPTS_EXHAUSTED",
            error=f"The worker stopped responding {attempt.recoveries + 1} times",
        )
        return "failed" if done else "skipped"
    previous = attempt.claimed_by
    async with tenant_session(attempt.company_id) as db:
        res = await db.execute(
            update(TaskAttempt)
            .where(
                _scoped(attempt.id, attempt.company_id),
                TaskAttempt.status.in_(LEASED_ATTEMPT_STATUSES),
                lapsed,
            )
            .values(
                status="queued",
                claimed_by=None,
                lease_expires_at=None,
                recoveries=TaskAttempt.recoveries + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            await db.rollback()
            return "skipped"
        attempt = await _get(db, attempt.company_id, attempt.id)
        await _audit(
            db, attempt, "task.attempt_recovered", reason="lease_expired", previous_worker=previous
        )
        await db.commit()
    STATS["recovered"] += 1
    await _publish(attempt)
    return "recovered"


async def recover_company(company_id: uuid.UUID, now: datetime | None = None) -> Counter[str]:
    """One recovery pass over a single tenant, inside that tenant's RLS context.

    The privileged system runtime finds which companies need this
    (``task_attempt_recovery``); the recovery itself runs on the tenant-bound role.
    """
    from nexus.database import tenant_session

    now = now or _now()
    ttl = timedelta(seconds=_settings().task_attempt_queue_ttl_seconds)
    outcome: Counter[str] = Counter()
    async with tenant_session(company_id) as db:
        expired = list(
            (
                await db.execute(
                    select(TaskAttempt)
                    .where(
                        TaskAttempt.company_id == company_id,
                        TaskAttempt.status.in_(LEASED_ATTEMPT_STATUSES),
                        TaskAttempt.lease_expires_at < now,
                    )
                    .limit(_BATCH)
                )
            ).scalars()
        )
        stale = list(
            (
                await db.execute(
                    select(TaskAttempt)
                    .where(
                        TaskAttempt.company_id == company_id,
                        TaskAttempt.status == "queued",
                        TaskAttempt.queued_at < now - ttl,
                    )
                    .limit(_BATCH)
                )
            ).scalars()
        )
    for attempt in expired:
        outcome[await _recover(attempt, now)] += 1
    for attempt in stale:
        done = await _finish(
            attempt,
            None,
            "expired",
            "cancelled",
            TaskAttempt.status == "queued",
            error_code="QUEUE_TTL_EXPIRED",
        )
        outcome["expired" if done else "skipped"] += 1
    return outcome


# ---------------------------------------------------------------------------
# Effects ledger
# ---------------------------------------------------------------------------


async def _effect(attempt: TaskAttempt, kind: str, key: str) -> WorkEffect:
    """The ledger row for ``key``, created pending if it does not exist yet."""
    from nexus.database import tenant_session

    def find() -> Any:
        return select(WorkEffect).where(
            WorkEffect.company_id == attempt.company_id, WorkEffect.effect_key == key
        )

    async with tenant_session(attempt.company_id) as db:
        row = (await db.execute(find())).scalar_one_or_none()
        if row is None:
            row = WorkEffect(
                company_id=attempt.company_id,
                task_id=attempt.task_id,
                attempt_id=attempt.id,
                kind=kind,
                effect_key=key,
            )
            try:
                async with db.begin_nested():
                    db.add(row)
            except IntegrityError:
                row = (await db.execute(find())).scalar_one()
            await db.commit()
        return row


async def _effect_done(effect: WorkEffect, result: dict[str, Any]) -> None:
    from nexus.database import tenant_session

    async with tenant_session(effect.company_id) as db:
        await db.execute(
            update(WorkEffect)
            .where(WorkEffect.id == effect.id, WorkEffect.company_id == effect.company_id)
            .values(status="done", result=result, updated_at=_now())
            .execution_options(synchronize_session=False)
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Preparation: session, worktree, prompt, turn
# ---------------------------------------------------------------------------


class RefusedError(Exception):
    """A deterministic reason the attempt cannot run; retrying would not help."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def _session_for(db: Any, attempt: TaskAttempt, agent: Any, task: Any) -> Any:
    from nexus.models.agent_session import AgentSessionRecord
    from nexus.services import session_service

    async def load(session_id: uuid.UUID) -> Any:
        return (
            await db.execute(
                select(AgentSessionRecord).where(
                    AgentSessionRecord.id == session_id,
                    AgentSessionRecord.company_id == attempt.company_id,
                )
            )
        ).scalar_one_or_none()

    if attempt.session_id is not None:
        record = await load(attempt.session_id)
        if record is None or record.status not in session_service.OPEN_STATUSES:
            raise RefusedError("SESSION_UNAVAILABLE", "The attempt's session has ended")
        return record
    # Retry rule: continue in the open session of this task's previous attempt.
    previous = (
        await db.execute(
            select(TaskAttempt.session_id)
            .where(
                TaskAttempt.company_id == attempt.company_id,
                TaskAttempt.task_id == attempt.task_id,
                TaskAttempt.agent_id == attempt.agent_id,
                TaskAttempt.id != attempt.id,
                TaskAttempt.session_id.is_not(None),
            )
            .order_by(TaskAttempt.attempt_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if previous is not None:
        record = await load(previous)
        if record is not None and record.status in session_service.OPEN_STATUSES:
            return record
    record = session_service.new_session_for(
        agent, created_by=SYSTEM_ACTOR, title=f"Task: {task.title}"[:200]
    )
    db.add(record)
    await db.flush()
    return record


async def _reviewed_worktree(db: Any, company_id: uuid.UUID, task_id: uuid.UUID) -> Any:
    """The worktree of the reviewed task's latest completed attempt."""
    from nexus.models.agent_worktree import AgentWorktree

    worktree_id = (
        await db.execute(
            select(TaskAttempt.worktree_id)
            .where(
                TaskAttempt.company_id == company_id,
                TaskAttempt.task_id == task_id,
                TaskAttempt.status == "completed",
            )
            .order_by(TaskAttempt.attempt_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    row = None
    if worktree_id is not None:
        row = (
            await db.execute(
                select(AgentWorktree).where(
                    AgentWorktree.id == worktree_id, AgentWorktree.company_id == company_id
                )
            )
        ).scalar_one_or_none()
    if row is None or not row.head_commit:
        raise RefusedError(
            "REVIEW_TARGET_MISSING", "The reviewed task has no completed work to review"
        )
    return row


async def _prepare(attempt: TaskAttempt, worker_id: str) -> tuple[Any, Any, Any] | None:
    """Bind session and worktree, then queue the turn. Returns (spec, turn id, worktree)."""
    from nexus.api.routes import chat
    from nexus.database import tenant_session
    from nexus.runtime import chat_turns
    from nexus.runtime.git_runner import GitError
    from nexus.services.worktree_service import (
        WorktreeError,
        WorktreeService,
        _repository_git,
        held_worktree,
        worktree_path,
    )

    company_id = attempt.company_id
    try:
        async with tenant_session(company_id) as db:
            task = await _load_task(db, company_id, attempt.task_id)
            spec = parse_work_spec(
                (attempt.context_snapshot or {}).get("work_spec") or task.work_spec
            )
            agent = await chat._load_agent(db, attempt.agent_id, company_id)
            check_employee(agent, spec.mode)
            record = await _session_for(db, attempt, agent, task)
            session_id = record.id
            await db.commit()
        if not await _update_held(
            attempt, worker_id, session_id=session_id, workspace_id=record.workspace_id
        ):
            return None

        if spec.mode == "text":
            turn_id = attempt.chat_turn_id
            if turn_id is None:
                async with tenant_session(company_id) as db:
                    failed = await _failed_checks(db, attempt) if attempt.attempt_number > 1 else []
                    record = await _session_for(db, attempt, agent, task)
                    agent = await chat._load_agent(db, attempt.agent_id, company_id)
                    enqueued = await chat_turns.create_turn(
                        db,
                        record,
                        agent,
                        build_text_prompt(attempt, task, spec, failed),
                        idempotency_key=f"attempt:{attempt.id}",
                    )
                turn_id = enqueued.turn.id
            if not await _update_held(attempt, worker_id, chat_turn_id=turn_id, status="running"):
                return None
            chat_turns.get_worker().wake(company_id)
            await _publish(attempt)
            return spec, turn_id, None

        async with tenant_session(company_id) as db:
            service = WorktreeService(db, _system_principal(company_id))
            row = await held_worktree(db, company_id, session_id)
            reviewed = None
            if spec.review_of_task_id is not None:
                reviewed = await _reviewed_worktree(db, company_id, spec.review_of_task_id)
            if row is None:
                if attempt.worktree_id is not None:
                    raise RefusedError(
                        "WORKTREE_UNAVAILABLE",
                        "The attempt's worktree is no longer held by its session",
                    )
                base_ref = reviewed.head_commit if reviewed is not None else spec.base_ref
                row = await service.create(
                    repository_id=spec.repository_id,
                    agent_id=attempt.agent_id,
                    base_ref=base_ref,
                    session_id=session_id,
                    task_id=attempt.task_id,
                )
                await db.commit()
            if row.agent_id != attempt.agent_id or row.repository_id != spec.repository_id:
                raise RefusedError("WORKTREE_MISMATCH", "The session holds another worktree")
            if row.status == "created":
                await service.transition(row.id, "active")
                await db.commit()
            if row.status != "active":
                raise RefusedError("WORKTREE_UNAVAILABLE", f"The worktree is {row.status}")
            diff = ""
            if reviewed is not None:
                git = await _repository_git(db, reviewed)
                diff = await git.diff(reviewed.base_commit, reviewed.head_commit)
            worktree_id = row.id
            branch = row.branch
            root = worktree_path(company_id, row.relative_path)
        if not await _update_held(attempt, worker_id, worktree_id=worktree_id):
            return None

        turn_id = attempt.chat_turn_id
        if turn_id is None:
            # A retry reuses the session's worktree: the previous attempt's
            # progress file would otherwise be read as this attempt's report.
            _drop_progress_file(root)
            failed: list[str] = []
            if attempt.attempt_number > 1:
                async with tenant_session(company_id) as db:
                    failed = await _failed_checks(db, attempt)
            prompt = build_prompt(attempt, task, spec, branch, reviewed, diff, failed)
            async with tenant_session(company_id) as db:
                record = await _session_for(db, attempt, agent, task)
                agent = await chat._load_agent(db, attempt.agent_id, company_id)
                enqueued = await chat_turns.create_turn(
                    db,
                    record,
                    agent,
                    prompt,
                    idempotency_key=f"attempt:{attempt.id}",
                    work_mode=spec.mode,
                )
            turn_id = enqueued.turn.id
        if not await _update_held(attempt, worker_id, chat_turn_id=turn_id, status="running"):
            return None
        chat_turns.get_worker().wake(company_id)
        await _publish(attempt)
        return spec, turn_id, worktree_id
    except RefusedError:
        raise
    except WorktreeError as exc:
        raise RefusedError(f"WORKTREE_{exc.reason.upper()}", str(exc.detail)) from exc
    except GitError as exc:
        raise RefusedError("GIT_FAILED", f"git {exc.kind}") from exc
    except HTTPException as exc:
        detail = exc.detail
        code = detail.get("code") if isinstance(detail, dict) else None
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        raise RefusedError(code or f"HTTP_{exc.status_code}", str(message)[:500]) from exc


async def _failed_checks(db: Any, attempt: TaskAttempt) -> list[str]:
    """The server checks the task's previous attempt failed, for the retry prompt."""
    verification = (
        await db.execute(
            select(TaskAttempt.verification).where(
                TaskAttempt.company_id == attempt.company_id,
                TaskAttempt.task_id == attempt.task_id,
                TaskAttempt.attempt_number == attempt.attempt_number - 1,
            )
        )
    ).scalar_one_or_none() or {}
    return [
        f"{c.get('check')}: {c.get('detail') or 'failed'}"[:300]
        for c in verification.get("checks") or []
        if isinstance(c, dict) and not c.get("passed")
    ][:20]


def build_text_prompt(
    attempt: TaskAttempt, task: Any, spec: WorkSpec, failed_checks: list[str] | None = None
) -> str:
    """Bounded instructions for a text task. The reply itself is the deliverable."""
    limit = spec.max_deliverable_chars or MAX_DELIVERABLE_CHARS
    lines = [
        f'You are working on the task "{task.title[:200]}" (attempt {attempt.attempt_number}).',
        "",
        "Objective:",
        (spec.objective or task.title)[:4000],
        "",
    ]
    if spec.expected_deliverable:
        lines += ["Expected deliverable:", spec.expected_deliverable[:500], ""]
    if failed_checks:
        lines += [
            "Your manager rejected the previous attempt:",
            *[f"- {item}" for item in failed_checks],
            "Address this in your new answer.",
            "",
        ]
    lines.append(
        f"Reply with the deliverable only, in at most {limit} characters. "
        "Your manager reviews it before the task counts as done."
    )
    return "\n".join(lines)


def build_prompt(
    attempt: TaskAttempt,
    task: Any,
    spec: WorkSpec,
    branch: str,
    reviewed: Any,
    diff: str,
    failed_checks: list[str] | None = None,
) -> str:
    """The bounded instructions the employee gets. Paths are relative to its workspace."""
    objective = spec.objective or task.description or task.title
    lines = [
        f'You are working on the task "{task.title[:200]}" (attempt {attempt.attempt_number}).',
        "",
        "Objective:",
        objective[:4000],
        "",
    ]
    if spec.acceptance_criteria:
        lines += ["Acceptance criteria:", *[f"- {c.label()}" for c in spec.acceptance_criteria], ""]
    if failed_checks:
        lines += [
            "The previous attempt did not pass the server's checks. It failed:",
            *[f"- {item}" for item in failed_checks],
            "Fix these in the workspace before you report completion.",
            "",
        ]
    lines += [
        f"Workspace: your current directory is an isolated git worktree on branch {branch}.",
        "Work only inside it and refer to files by paths relative to it. Do not read or change",
        "anything outside it, do not commit, and do not touch the .nexus directory except as",
        "described below.",
    ]
    commands = []
    for step in spec.verification:
        if step.command == "pytest":
            commands.append(" ".join(["python -m pytest -q", *step.paths]))
        else:
            commands.append(" ".join(["python -m py_compile", *step.paths]))
    if spec.mode == "write":
        lines += [
            "Mode: write. Create or edit files in the workspace.",
            "Deliverables (relative paths): " + ", ".join(spec.deliverables),
            "The only shell commands you may run are the tests: " + "; ".join(commands),
            "",
            "Progress: whenever you finish a step, write the report object described below,",
            f'plus an integer "seq" that grows by one with every update, to {REPORT_FILE}.',
        ]
    else:
        lines += [
            "Mode: read-only. Do not create, edit or delete any file. Review and report only.",
        ]
    if commands:
        lines += ["", "After you finish, the server itself runs: " + "; ".join(commands)]
    if reviewed is not None:
        lines += [
            "",
            f"Review the change from commit {reviewed.base_commit[:12]}"
            f" to {reviewed.head_commit[:12]}.",
            "The workspace is checked out at the reviewed commit. The diff:",
            "```diff",
            diff[:MAX_DIFF_CHARS] + ("\n[diff truncated]" if len(diff) > MAX_DIFF_CHARS else ""),
            "```",
        ]
    lines += [
        "",
        "Final answer: end your reply with exactly one JSON object of this shape:",
        '{"state": "completed|blocked|failed", "summary": "...", "progress_percent": 100,'
        ' "current_step": "...", "completed_steps": ["..."], "next_step": "",'
        ' "blockers": [], "artifacts": ["relative/path"], "tests_run": ["command: result"],'
        ' "confidence": 0.9, "needs_help": false, "eta": null}',
        'Use "blocked" with at least one entry in "blockers" when you cannot continue.',
        '"completed" must list the files you produced in "artifacts" or the tests you ran in',
        '"tests_run". The task is complete only after the server\'s own checks pass.',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


def read_progress(root: Path) -> tuple[int, dict[str, Any]] | None:
    """The progress report the employee wrote, if it is present and valid."""
    path = inside(root, REPORT_FILE, excluded=())
    if path is None or not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_REPORT_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        seq = data.get("seq") if isinstance(data, dict) else None
        if not isinstance(seq, int) or isinstance(seq, bool) or not 1 <= seq <= MAX_SEQ:
            return None
        report = EmployeeReport.model_validate(data)
    except (OSError, ValueError):
        return None
    return seq, report.model_dump(mode="json")


async def store_report(attempt: TaskAttempt, seq: int, report: dict[str, Any], source: str) -> bool:
    """Store a report only if its seq is newer than the stored one."""
    from nexus.database import tenant_session

    async with tenant_session(attempt.company_id) as db:
        res = await db.execute(
            update(TaskAttempt)
            .where(
                _scoped(attempt.id, attempt.company_id),
                TaskAttempt.report_seq < seq,
                TaskAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
            )
            .values(
                report={**report, "seq": seq, "source": source, "received_at": _now().isoformat()},
                report_seq=seq,
                updated_at=_now(),
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    if res.rowcount != 1:
        return False
    attempt.report_seq = seq
    STATS["report_stored"] += 1
    await _publish(attempt, progress_percent=report.get("progress_percent"))
    return True


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _check_env() -> dict[str, str]:
    from nexus.adapters.cli_adapter import _filter_env

    env = _filter_env(dict(os.environ), [])
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONSTARTUP"):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


async def run_check(
    step: VerificationStep, index: int, root: Path, evidence: Path, timeout: float
) -> dict[str, Any]:
    """Run one catalog command in the worktree: no shell, bounded output, whole tree killed."""
    from nexus.adapters.cli_adapter import _contain, _read_bounded, _release_job, _terminate_tree

    shown = ["python", "-m", step.command]
    argv = [sys.executable, "-m", step.command]
    if step.command == "pytest":
        flags = ["-q", "-p", "no:cacheprovider"]
        if not any((root / name).is_file() for name in _PYTEST_CONFIGS):
            # Without its own config, pytest would climb out of the worktree
            # looking for one. An empty one next to the logs stops it; the
            # worktree stays the root and its conftest files still load.
            ini = evidence / "pytest.ini"
            ini.write_text("[pytest]\n", encoding="utf-8")
            shown += [
                *flags,
                "-c",
                "<evidence>/pytest.ini",
                "--rootdir=<worktree>",
                "--confcutdir=<worktree>",
            ]
            flags += ["-c", str(ini), f"--rootdir={root}", f"--confcutdir={root}"]
        else:
            shown += flags
        argv += flags
    argv += step.paths
    shown += step.paths
    limit = _settings().task_attempt_log_bytes
    started = _now()
    timed_out = False
    out = err = b""
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(root),
        env=_check_env(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name != "nt",
    )
    _contain(process)
    try:
        out, err, _ = await asyncio.wait_for(
            asyncio.gather(
                _read_bounded(process.stdout, limit),
                _read_bounded(process.stderr, limit),
                process.wait(),
            ),
            timeout,
        )
    except TimeoutError:
        timed_out = True
        await _terminate_tree(process)
    finally:
        _release_job(process)
    ended = _now()
    refs = {}
    for name, data in (("stdout", out), ("stderr", err)):
        text = _redact(data.decode("utf-8", errors="replace"), root)
        ref = f"verify-{index}-{step.command}.{name}.log"
        (evidence / ref).write_text(text, encoding="utf-8")
        refs[name] = {"ref": ref, "bytes": len(data), "truncated": len(data) >= limit}
    stdout_text = out.decode("utf-8", errors="replace")
    counts: dict[str, int] = {}
    for number, word in _PYTEST_COUNT.findall(stdout_text[-4000:]):
        counts[word.rstrip("s") if word.startswith("error") else word] = int(number)
    return {
        "id": f"{index}:{step.command}",
        "command": step.command,
        "argv": shown,
        "cwd": "<worktree>",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "exit_code": None if timed_out else process.returncode,
        "timed_out": timed_out,
        "stdout": refs["stdout"],
        "stderr": refs["stderr"],
        "tail": _redact(stdout_text[-1500:], root),
        "tests": counts or None,
        "passed": not timed_out and process.returncode == 0,
    }


def _criterion(c: Criterion, root: Path, commands: list[dict], report: dict | None) -> dict:
    passed = False
    detail = ""
    if c.kind == "file_exists":
        path = inside(root, c.path)
        passed = path is not None and path.is_file()
    elif c.kind == "command_passes":
        runs = [r for r in commands if r["command"] == c.command]
        passed = bool(runs) and all(r["passed"] for r in runs)
    elif c.kind == "pattern_count":
        path = inside(root, c.path)
        count = 0
        if path is not None and path.is_file():
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                count = fh.read(1_000_000).count(c.pattern)
        passed = count >= c.min_count
        detail = f"found {count}"
    else:
        haystack = json.dumps(report or {}).lower()
        passed = c.text.lower() in haystack
    return {"kind": c.kind, "criterion": c.label(), "passed": passed, "detail": detail}


async def manifest(
    root: Path, spec: WorkSpec, attempt: TaskAttempt, worktree_id: uuid.UUID, passed: bool
) -> list[dict[str, Any]]:
    """Hashes and sizes of what the attempt changed, by worktree-relative path."""
    from nexus.runtime.git_runner import GitRunner

    changed = await GitRunner(root).changed_paths()
    paths = list(dict.fromkeys([*spec.deliverables, *changed]))
    entries = []
    for rel in paths:
        if not _is_work(rel):
            continue
        if len(entries) >= MAX_ARTIFACTS:
            break
        path = inside(root, rel)
        entry: dict[str, Any] = {
            "path": rel,
            "type": _kind(rel),
            "size": None,
            "sha256": None,
            "modified_at": None,
            "execution_id": attempt.execution_id,
            "worktree_id": str(worktree_id),
            "commit": None,
            "deliverable": rel in spec.deliverables,
            "validation": "missing",
        }
        if path is not None and path.is_file():
            stat_ = path.stat()
            entry.update(
                size=stat_.st_size,
                sha256=await asyncio.to_thread(_sha256, path),
                modified_at=datetime.fromtimestamp(stat_.st_mtime, timezone.utc)  # noqa: UP017
                .replace(tzinfo=None)
                .isoformat(),
                validation="verified" if passed and rel in spec.deliverables else "unverified",
            )
        entries.append(entry)
    return entries


async def verify(attempt: TaskAttempt, spec: WorkSpec, turn: Any, worktree: Any) -> dict[str, Any]:
    """The deterministic gate. Returns the outcome and the evidence behind it."""
    from nexus.database import tenant_session
    from nexus.models.chat import ChatMessage
    from nexus.runtime.git_runner import GitRunner
    from nexus.services.worktree_service import worktree_path

    root = worktree_path(worktree.company_id, worktree.relative_path)
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> bool:
        checks.append({"check": name, "passed": passed, "detail": detail})
        return passed

    reply = None
    if turn.response_message_id is not None:
        async with tenant_session(attempt.company_id) as db:
            reply = (
                await db.execute(
                    select(ChatMessage).where(
                        ChatMessage.id == turn.response_message_id,
                        ChatMessage.company_id == attempt.company_id,
                    )
                )
            ).scalar_one_or_none()
    execution = ((reply.payload or {}) if reply else {}).get("execution") or {}
    cli = execution.get("cli") or {}
    exit_code = cli.get("exit_code")
    usage = {
        "backend": execution.get("backend") or cli.get("backend"),
        "model": turn.model_used or cli.get("model"),
        "tokens": (turn.result or {}).get("tokens_used"),
        "duration_ms": cli.get("duration_ms"),
        "cli_version": cli.get("version"),
    }

    outcome: tuple[str, str, str | None] = ("completed", "goal", None)
    report: dict[str, Any] | None = None
    commands: list[dict[str, Any]] = []
    criteria: list[dict[str, Any]] = []

    if not check("cli_exit_code", exit_code == 0, f"exit_code={exit_code}"):
        outcome = ("failed", "error", "CLI_EXIT_NONZERO")
    raw = find_final_report(reply.text) if reply else None
    if raw is None:
        check("final_report", False, "no structured report in the reply")
        if outcome[0] == "completed":
            outcome = ("failed", "verification_failed", "REPORT_MISSING")
    else:
        try:
            report = EmployeeReport.model_validate(raw).model_dump(mode="json")
            check("final_report", True, report["state"])
        except ValidationError as exc:
            check("final_report", False, str(exc.errors()[0].get("msg"))[:300])
            if outcome[0] == "completed":
                outcome = ("failed", "verification_failed", "REPORT_INVALID")
    if report is not None and outcome[0] == "completed":
        if report["state"] == "blocked":
            outcome = ("blocked", "needs_help", "EMPLOYEE_BLOCKED")
        elif report["state"] == "failed":
            outcome = ("failed", "error", "EMPLOYEE_REPORTED_FAILURE")
        elif report["state"] != "completed":
            outcome = ("failed", "verification_failed", "REPORT_NOT_FINAL")
        if report["blockers"] and outcome[0] == "completed":
            outcome = ("blocked", "needs_help", "EMPLOYEE_BLOCKED")

    evidence = evidence_root(attempt.company_id) / str(attempt.id)
    evidence.mkdir(parents=True, exist_ok=True)
    if outcome[0] == "completed":
        for rel in spec.deliverables:
            path = inside(root, rel)
            check(f"deliverable:{rel}", path is not None and path.is_file())
        for index, step in enumerate(spec.verification):
            run = await run_check(step, index, root, evidence, float(spec.timeout_seconds))
            commands.append(run)
            check(f"command:{run['id']}", run["passed"], f"exit_code={run['exit_code']}")
        criteria = [_criterion(c, root, commands, report) for c in spec.acceptance_criteria]
        for item in criteria:
            check(f"criterion:{item['criterion']}", item["passed"], item["detail"])
        if spec.mode == "read_only":
            changed = [p for p in await GitRunner(root).changed_paths() if _is_work(p)]
            check("read_only_worktree_clean", not changed, f"{len(changed)} changed paths")
            if spec.review_of_task_id is not None:
                async with tenant_session(attempt.company_id) as db:
                    reviewed = await _reviewed_worktree(
                        db, attempt.company_id, spec.review_of_task_id
                    )
                reviewed_root = worktree_path(reviewed.company_id, reviewed.relative_path)
                git = GitRunner(reviewed_root)
                head = await git.resolve_commit("HEAD")
                dirty = [p for p in await git.changed_paths() if _is_work(p)]
                check(
                    "reviewed_worktree_unchanged",
                    head == reviewed.head_commit and not dirty,
                    f"head {'unchanged' if head == reviewed.head_commit else 'moved'},"
                    f" {len(dirty)} changed paths",
                )
        if not all(c["passed"] for c in checks):
            outcome = ("failed", "verification_failed", "VERIFICATION_FAILED")

    passed = outcome[0] == "completed"
    artifacts = (
        await manifest(root, spec, attempt, worktree.id, passed) if spec.mode == "write" else []
    )
    record = {
        "passed": passed,
        "outcome": outcome[0],
        "completion_reason": outcome[1],
        "error_code": outcome[2],
        "checks": checks,
        "commands": commands,
        "criteria": criteria,
        "evidence_ref": f"task_evidence/{attempt.id}",
        "evaluator": "not run: completion is decided by the deterministic checks only",
        "verified_at": _now().isoformat(),
    }
    (evidence / "verification.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"record": record, "artifacts": artifacts, "report": report, "usage": usage}


async def commit_work(attempt: TaskAttempt, worktree: Any) -> str | None:
    """Commit the attempt's work on the worktree branch exactly once."""
    from nexus.runtime.git_runner import GitRunner
    from nexus.services.worktree_service import GIT_AUTHOR, worktree_path

    key = f"commit:{attempt.id}"
    effect = await _effect(attempt, "git_commit", key)
    if effect.status == "done":
        return (effect.result or {}).get("commit")
    root = worktree_path(worktree.company_id, worktree.relative_path)
    git = GitRunner(root)
    trailer = f"Nexus-Effect: {key}"
    sha = await git.find_commit_with(trailer)
    if sha is None:
        changed = [p for p in await git.changed_paths() if _is_work(p)]
        if changed:
            await git.stage_all_except(EXCLUDED_DIRS, anywhere=GENERATED_DIRS)
            sha = await git.commit(
                f"Task attempt {attempt.attempt_number} for task {attempt.task_id}\n\n{trailer}",
                author=GIT_AUTHOR,
            )
    await _effect_done(effect, {"commit": sha})
    return sha


def _drop_progress_file(root: Path) -> None:
    """Remove the server's own progress file so it is never committed as work."""
    from nexus.governance.fs_roots import is_link

    path = inside(root, REPORT_FILE, excluded=())
    if path is not None and path.is_file() and not is_link(path):
        path.unlink()
    folder = root / ".nexus"
    with contextlib.suppress(OSError):
        if folder.is_dir() and not is_link(folder) and not any(folder.iterdir()):
            folder.rmdir()


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class TaskAttemptWorker:
    """Claims queued attempts and drives each through to a terminal state.

    Started by the application lifespan (persistent: polls and sweeps). A
    start request also wakes it, which runs it on demand when no lifespan
    started it (tests, embedded apps).
    """

    def __init__(self, worker_id: str = WORKER_ID, *, persistent: bool = False) -> None:
        self.worker_id = worker_id
        self.persistent = persistent
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._running: dict[uuid.UUID, asyncio.Task] = {}
        self._pokes: dict[uuid.UUID, asyncio.Event] = {}
        self._companies: set[uuid.UUID] = set()
        self._last_sweep = float("-inf")

    def wake(self, company_id: uuid.UUID | None = None) -> None:
        if company_id is not None:
            self._companies.add(company_id)
        self._wake.set()
        if not self._stopping and (self._task is None or self._task.done()):
            self._task = asyncio.get_running_loop().create_task(
                self._loop(), name="task-attempt-worker", context=contextvars.Context()
            )

    def poke(self, attempt_id: uuid.UUID) -> None:
        event = self._pokes.get(attempt_id)
        if event is not None:
            event.set()

    async def _loop(self) -> None:
        while not self._stopping:
            self._wake.clear()
            try:
                if self.persistent and time.monotonic() - self._last_sweep >= _SWEEP_EVERY_SECONDS:
                    self._last_sweep = time.monotonic()
                    # Companies with queued attempts come from the system runtime's hints;
                    # this worker never looks across tenants itself.
                    self._companies.update(await work_hints.claim("task_attempts"))
                await self._dispatch()
            except Exception:  # noqa: BLE001 -- keep the worker alive; the next pass retries
                logger.exception("task attempt worker pass failed")
            if not (self.persistent or self._running or self._wake.is_set()):
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), _settings().task_attempt_poll_seconds)

    async def _dispatch(self) -> None:
        from nexus.database import tenant_session

        for company_id in list(self._companies):
            async with tenant_session(company_id) as db:
                ids = list(
                    (
                        await db.execute(
                            select(TaskAttempt.id)
                            .where(
                                TaskAttempt.company_id == company_id,
                                TaskAttempt.status == "queued",
                                TaskAttempt.cancel_requested_at.is_(None),
                            )
                            .order_by(TaskAttempt.queued_at)
                            .limit(_BATCH)
                        )
                    ).scalars()
                )
            for attempt_id in ids:
                if self._stopping or attempt_id in self._running:
                    continue
                attempt = await claim(attempt_id, company_id, self.worker_id)
                if attempt is None:
                    continue
                self._pokes[attempt_id] = asyncio.Event()
                self._running[attempt_id] = asyncio.get_running_loop().create_task(
                    self._run(attempt), name=f"task-attempt-{attempt_id}"
                )

    async def _run(self, attempt: TaskAttempt) -> None:
        import anyio

        try:
            await self._drive(attempt)
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                with contextlib.suppress(Exception):
                    await release(attempt, self.worker_id, "worker_shutdown")
            raise
        except Exception:  # noqa: BLE001 -- the lease expires and recovery takes over
            logger.exception("task attempt %s failed outside its own error handling", attempt.id)
        finally:
            self._running.pop(attempt.id, None)
            self._pokes.pop(attempt.id, None)
            self.wake()

    async def _drive(self, attempt: TaskAttempt) -> None:
        from nexus.database import tenant_session
        from nexus.models.agent_worktree import AgentWorktree
        from nexus.models.chat_turn import TERMINAL_STATUSES as TURN_DONE
        from nexus.runtime import chat_turns

        me = self.worker_id
        try:
            prepared = await _prepare(attempt, me)
        except RefusedError as exc:
            await _finish(attempt, me, "failed", "error", error_code=exc.code, error=exc.message)
            return
        if prepared is None:
            return
        spec, turn_id, worktree_id = prepared
        worktree = root = None
        if worktree_id is not None:
            async with tenant_session(attempt.company_id) as db:
                worktree = (
                    await db.execute(
                        select(AgentWorktree).where(
                            AgentWorktree.id == worktree_id,
                            AgentWorktree.company_id == attempt.company_id,
                        )
                    )
                ).scalar_one()
            from nexus.services.worktree_service import worktree_path

            root = worktree_path(worktree.company_id, worktree.relative_path)
        from nexus.runtime.git_runner import GitRunner

        interval = max(0.5, min(_settings().task_attempt_lease_seconds / 3, 5.0))
        deadline = (attempt.started_at or _now()) + timedelta(seconds=spec.timeout_seconds)
        poke = self._pokes.setdefault(attempt.id, asyncio.Event())
        cancel_sent = timed_out = False
        while True:
            state = await _safe_renew(attempt, me)
            if state == "lost":
                return
            turn = await chat_turns.get_turn(attempt.company_id, turn_id)
            if turn is None:
                await _finish(attempt, me, "failed", "error", error_code="TURN_MISSING")
                return
            if turn.execution_id and turn.execution_id != attempt.execution_id:
                await _update_held(attempt, me, execution_id=turn.execution_id)
            if spec.mode == "write":
                progress = read_progress(root)
                if progress is not None and progress[0] > attempt.report_seq:
                    await store_report(attempt, progress[0], progress[1], "progress")
            if turn.status in TURN_DONE:
                break
            if not cancel_sent and (state == "cancelled" or _now() >= deadline):
                timed_out = state != "cancelled"
                by = SYSTEM_ACTOR + (":timeout" if timed_out else "")
                if timed_out:
                    await _update_held(attempt, me, error_code="TIMEOUT")
                else:
                    fresh = await get_attempt(attempt.company_id, attempt.id)
                    by = (fresh.cancelled_by if fresh else None) or by
                async with tenant_session(attempt.company_id) as db:
                    with contextlib.suppress(HTTPException):
                        await chat_turns.request_cancel(
                            db, attempt.company_id, turn.session_id, turn.id, by
                        )
                cancel_sent = True
            changed = chat_turns.get_worker().change_event()
            waits = {asyncio.ensure_future(changed.wait()), asyncio.ensure_future(poke.wait())}
            await asyncio.wait(waits, timeout=interval, return_when=asyncio.FIRST_COMPLETED)
            for fut in waits:
                fut.cancel()
            poke.clear()

        fresh = await get_attempt(attempt.company_id, attempt.id)
        if fresh is not None and fresh.cancel_requested_at is not None:
            await _finish(attempt, me, "cancelled", "cancelled", error_code="CANCELLED")
            return
        if timed_out:
            await _finish(
                attempt,
                me,
                "failed",
                "timeout",
                error_code="TIMEOUT",
                error=f"No result within {spec.timeout_seconds} seconds",
            )
            return
        if turn.status != "completed":
            await _finish(
                attempt,
                me,
                "failed",
                "error",
                error_code=turn.error_code or f"TURN_{turn.status.upper()}",
                error=(turn.error_message or f"The employee's turn {turn.status}")[:2000],
            )
            return

        if spec.mode == "text":
            # Submission is not completion: the manager verifies in a separate step.
            from nexus.services import work_service

            await work_service.submit_from_turn(attempt, me, spec, turn)
            return

        if not await _update_held(attempt, me, status="verifying"):
            return
        await _publish(attempt)
        effect = await _effect(attempt, "file_write_batch", f"evidence:{attempt.id}")
        if effect.status == "done":
            result = effect.result or {}
        else:
            result = await self._leased(attempt, verify(attempt, spec, turn, worktree))
            await _effect_done(effect, result)
        record, report = result["record"], result.get("report")
        if report is not None:
            await store_report(attempt, attempt.report_seq + 1, report, "final")
        # Caches left by running the tests, and server files a killed run
        # could not clean up (its CLI instruction file), would otherwise be
        # committed with whatever the session leaves behind when it ends.
        await GitRunner(root).remove_untracked(GENERATED_DIRS, top=EXCLUDED_DIRS)
        commit = None
        if record["passed"] and spec.mode == "write":
            _drop_progress_file(root)
            commit = await commit_work(attempt, worktree)
        artifacts = [{**a, "commit": commit} if a["sha256"] else a for a in result["artifacts"]]
        failed_checks = [c["check"] for c in record["checks"] if not c["passed"]]
        values = {
            "verification": record,
            "artifacts": artifacts,
            "usage": result.get("usage"),
            "output_summary": ((report or {}).get("summary") or "")[:4000] or None,
            "error_code": record["error_code"],
            "error": (
                None
                if record["passed"]
                else "; ".join([*failed_checks, *((report or {}).get("blockers") or [])])[:2000]
                or record["error_code"]
            ),
        }
        await _finish(attempt, me, record["outcome"], record["completion_reason"], **values)

    async def _leased(self, attempt: TaskAttempt, work: Any) -> Any:
        """Await ``work``, renewing the attempt's lease each time a third of it passes."""
        interval = max(0.5, _settings().task_attempt_lease_seconds / 3)
        task = asyncio.ensure_future(work)
        try:
            while not (await asyncio.wait({task}, timeout=interval))[0]:
                await _safe_renew(attempt, self.worker_id)
            return task.result()
        finally:
            task.cancel()


_workers: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, TaskAttemptWorker] = (
    weakref.WeakKeyDictionary()
)


def get_worker() -> TaskAttemptWorker:
    """This event loop's worker."""
    loop = asyncio.get_running_loop()
    worker = _workers.get(loop)
    if worker is None:
        worker = _workers[loop] = TaskAttemptWorker()
    return worker


async def start_worker() -> TaskAttemptWorker:
    worker = get_worker()
    worker.persistent = True
    worker._stopping = False
    worker.wake()
    return worker


async def stop_worker(drain_seconds: float = 30.0) -> None:
    """Stop claiming, let running attempts finish, then hand the rest back."""
    worker = get_worker()
    worker._stopping = True
    worker._wake.set()
    if worker._task is not None:
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await worker._task
    running = list(worker._running.values())
    if running:
        _, left = await asyncio.wait(running, timeout=drain_seconds)
        for task in left:
            task.cancel()
        if left:
            await asyncio.wait(left)


async def drain() -> None:
    """Wait until this loop's worker has nothing running (tests, shutdown)."""
    worker = get_worker()
    while worker._task is not None and not worker._task.done():
        await asyncio.wait({worker._task})
