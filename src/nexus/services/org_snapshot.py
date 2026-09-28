"""Organization Snapshot v1: a deterministic, precomputed picture of one company.

A snapshot is built from persisted rows only (agents, tasks and their newest
attempts, approvals, budgets, incidents) with no model or CLI call, serialized
as canonical JSON (sorted keys, no whitespace) and stored as an immutable,
versioned ``organization_snapshots`` row with the payload's SHA-256. Readers
get the latest stored version; they never trigger aggregation.

Refresh model:

- **Dirty marking.** :func:`start_listener` subscribes to the realtime bus
  (:mod:`nexus.realtime.event_bus`) and marks a company dirty when it sees
  ``task.attempt``, ``agent.manager_changed``, ``delegation.created`` or
  ``organization.changed``. The last one is published after a commit that
  wrote a tracked table (agents, tasks, task attempts, approvals, policies,
  tool policies, budget policies, incidents, companies), from session hooks
  installed by the listener.
- **Debounced regeneration.** The scheduler tick (``runtime/scheduler.py``)
  calls :func:`tick`, which regenerates a dirty company once it has been quiet
  for ``DEBOUNCE`` (or dirty for ``MAX_WAIT``).
- **Reconciliation.** The same tick regenerates any company not attempted for
  ``RECONCILE_EVERY``. An unchanged payload creates no new version; it only
  records that the latest version was verified. This also catches changes no
  event reported.
- **Explicit refresh** is :func:`generate`, called by the refresh endpoint.

One generation runs per company at a time: it holds a lease on the company's
``organization_snapshot_state`` row, taken by a conditional UPDATE. The read
runs in its own transaction (REPEATABLE READ on PostgreSQL), which is closed
before the short write transaction. ``(company_id, version)`` and
``(company_id, generation_key)`` are unique, so racing writers cannot create
duplicate versions. A failure records ``last_error`` and leaves every stored
version untouched.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from itertools import chain
from typing import Any

from sqlalchemy import event, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, BindParameter

from nexus.models.agent import Agent
from nexus.models.budget import BudgetPolicy
from nexus.models.company import Company
from nexus.models.governance import Approval
from nexus.models.incident import Incident
from nexus.models.organization_snapshot import OrganizationSnapshot, OrganizationSnapshotState
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt
from nexus.services import manager_service as ms

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TOOL = "organization_get_snapshot"

DEBOUNCE = timedelta(seconds=30)
MAX_WAIT = timedelta(minutes=5)
RECONCILE_EVERY = timedelta(minutes=15)
# A snapshot not confirmed for this long is reported stale even with no event.
STALE_AFTER = timedelta(minutes=30)
LEASE = timedelta(minutes=2)
HISTORY_MAX = 50
LIST_LIMIT = 25
RESULTS_LIMIT = 10
# ponytail: one company per tick at most this many; add a work queue if tenants outgrow it.
MAX_PER_TICK = 20
# ponytail: newest tasks only; aggregate in SQL if a company outgrows it.
MAX_TASKS = 5000

ORG_CHANNEL = "organization"
CHANGED = "organization.changed"
DIRTY_EVENTS = (
    "organization.changed", "task.attempt", "agent.manager_changed", "delegation.created",
)
TRACKED_TABLES = frozenset({
    "agents", "tasks", "task_attempts", "approvals", "policies", "tool_policies",
    "budget_policies", "incidents", "companies",
})
BUCKETS = ("active", "queued", "stale", "completed", "failed", "blocked")
FRESH, STALE, REBUILDING, FAILED_REFRESH = "fresh", "stale", "rebuilding", "failed_refresh"
RESOLVED_INCIDENT = ("resolved", "closed")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _id(value: uuid.UUID | None) -> str | None:
    return str(value) if value else None


def canonical(payload: dict[str, Any]) -> str:
    """The one serialization that is hashed: sorted keys, no whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


# --- build ------------------------------------------------------------------


def _backend(agent: Agent) -> str:
    return str((agent.adapter_config or {}).get("backend") or agent.adapter_type or "unknown")


def _sort_by_time(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Newest first, ties broken by id: the same rows always give the same order."""
    items = sorted(items, key=lambda i: i["id"])
    return sorted(items, key=lambda i: i[key] or "", reverse=True)


async def _sources(db: Any, company_id: uuid.UUID, company: Company) -> dict[str, Any]:
    """Row count and newest change per source table: the snapshot's watermarks."""
    def stat(model: Any, stamp: Any) -> Any:
        return select(func.count(), func.max(stamp)).where(model.company_id == company_id)

    queries = {
        "agents": stat(Agent, Agent.updated_at),
        "tasks": stat(Task, Task.updated_at),
        "task_attempts": stat(TaskAttempt, TaskAttempt.updated_at),
        "approvals": stat(Approval, Approval.updated_at),
        "budget_policies": stat(BudgetPolicy, BudgetPolicy.updated_at),
        "incidents": stat(Incident, func.coalesce(Incident.resolved_at, Incident.created_at)),
    }
    out = {"companies": {"count": 1, "latest": _iso(company.updated_at)}}
    for name, query in queries.items():
        count, latest = (await db.execute(query)).one()
        out[name] = {"count": int(count), "latest": _iso(latest)}
    return out


async def build(db: Any, company_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    """The canonical payload for ``company_id`` as of ``now``. Deterministic, read-only."""
    from nexus.services import hiring_service

    company = (
        await db.execute(select(Company).where(Company.id == company_id))
    ).scalar_one_or_none()
    if company is None:
        raise LookupError("company not found")
    sources = await _sources(db, company_id, company)

    agents = (
        await db.execute(select(Agent).where(Agent.company_id == company_id).order_by(Agent.id))
    ).scalars().all()
    by_id = {a.id: a for a in agents}
    tasks = (
        await db.execute(
            select(Task.id, Task.title, Task.status, Task.assigned_agent_id, Task.updated_at)
            .where(Task.company_id == company_id)
            .order_by(Task.updated_at.desc(), Task.id)
            .limit(MAX_TASKS)
        )
    ).all()
    latest = await ms.latest_attempts(db, company_id, None)
    approvals = (
        await db.execute(
            select(Approval)
            .where(
                Approval.company_id == company_id,
                or_(Approval.status == "pending", Approval.type == hiring_service.HIRE),
            )
            .order_by(Approval.created_at.desc(), Approval.id)
        )
    ).scalars().all()
    policies = (
        await db.execute(
            select(BudgetPolicy).where(
                BudgetPolicy.company_id == company_id, BudgetPolicy.is_active == True  # noqa: E712
            )
        )
    ).scalars().all()
    incidents = (
        await db.execute(
            select(Incident)
            .where(Incident.company_id == company_id, Incident.status.notin_(RESOLVED_INCIDENT))
            .order_by(Incident.created_at.desc(), Incident.id)
        )
    ).scalars().all()

    # Work: each task in one bucket, from its newest attempt.
    per_agent: dict[uuid.UUID, Counter] = {a.id: Counter() for a in agents}
    counts: Counter = Counter()
    items: dict[str, list[dict[str, Any]]] = {b: [] for b in BUCKETS if b != "completed"}
    for task in tasks:
        attempt = latest.get(task.id)
        if "cancelled" in (task.status, attempt.status if attempt else None):
            counts["cancelled"] += 1
            continue
        bucket = ms.work_bucket(task, attempt, now)
        counts[bucket] += 1
        if task.assigned_agent_id in per_agent:
            per_agent[task.assigned_agent_id][bucket] += 1
        if bucket in items:
            items[bucket].append({
                "id": str(task.id),
                "title": task.title,
                "employee_id": _id(task.assigned_agent_id),
                "task_status": task.status,
                "attempt_id": _id(attempt.id) if attempt else None,
                "attempt_status": attempt.status if attempt else None,
                "error_code": attempt.error_code if attempt else None,
                "updated_at": _iso(attempt.updated_at if attempt else task.updated_at),
            })
    titles = {t.id: t.title for t in tasks}
    results = []
    for a in latest.values():
        if a.status not in ("completed", "failed", "blocked") or a.task_id not in titles:
            continue
        results.append({
            "id": str(a.id),
            "task_id": str(a.task_id),
            "task_title": titles[a.task_id],
            "employee_id": str(a.agent_id),
            "status": a.status,
            "summary": (a.output_summary or "")[:500] or None,
            "error_code": a.error_code,
            "verified": (a.verification or {}).get("passed"),
            "evidence": [
                {"path": e.get("path"), "sha256": e.get("sha256"), "commit": e.get("commit")}
                for e in (a.artifacts or [])[:5]
                if isinstance(e, dict)
            ],
            "completed_at": _iso(a.completed_at or a.updated_at),
        })
    results = _sort_by_time(results, "completed_at")[:RESULTS_LIMIT]

    # Hierarchy and workforce.
    reports: dict[uuid.UUID, list[Agent]] = {}
    for a in agents:
        if a.manager_id in by_id:
            reports.setdefault(a.manager_id, []).append(a)
    employees = [
        {
            "id": str(a.id),
            "name": a.name,
            "title": a.title,
            "role": a.role,
            "status": a.status,
            "backend": _backend(a),
            "manager_id": _id(a.manager_id) if a.manager_id in by_id else None,
            "direct_reports": len(reports.get(a.id, [])),
            "work": {b: per_agent[a.id][b] for b in BUCKETS},
        }
        for a in agents
    ]
    managers = []
    for manager_id, team in reports.items():
        work = Counter()
        for r in team:
            work.update(per_agent[r.id])
        managers.append({
            "id": str(manager_id),
            "name": by_id[manager_id].name,
            "direct_reports": len(team),
            "report_ids": sorted(str(r.id) for r in team),
            "report_status": dict(Counter(r.status for r in team)),
            "work": {b: work[b] for b in BUCKETS},
        })
    managers.sort(key=lambda m: m["id"])
    roots = sorted(str(a.id) for a in agents if a.manager_id not in by_id)
    depth, level, seen = 0, [a.id for a in agents if a.manager_id not in by_id], set()
    while level:
        seen.update(level)
        depth += 1
        level = [r.id for m in level for r in reports.get(m, []) if r.id not in seen]

    # Hiring and approvals.
    hires, pending = [], []
    for ap in approvals:
        payload = ap.payload or {}
        if ap.type == hiring_service.HIRE:
            request = payload.get("request") or {}
            state = {"pending": "pending", "rejected": "rejected"}.get(ap.status, ap.status)
            if ap.status == "approved":
                hired = hiring_service.employee_id_for(ap.id) in by_id
                state = "approved" if hired else "failed"
            hires.append({
                "id": str(ap.id),
                "state": state,
                "manager_id": _id(ap.requested_by_agent_id),
                "role": request.get("role"),
                "title": request.get("title"),
                "backend": request.get("backend"),
                "amount_cents": payload.get("amount_cents"),
                "monthly_cents": request.get("estimated_monthly_cents"),
                "policy_decision": (payload.get("policy") or {}).get("outcome"),
                "created_at": _iso(ap.created_at),
            })
        if ap.status == "pending":
            pending.append({
                "id": str(ap.id),
                "type": ap.type,
                "requested_by_agent_id": _id(ap.requested_by_agent_id),
                "required_signatures": ap.required_signatures,
                "amount_cents": payload.get("amount_cents"),
                "created_at": _iso(ap.created_at),
                "expires_at": _iso(ap.expires_at),
            })
    hire_counts = Counter(h["state"] for h in hires)

    def cents(states: tuple[str, ...], key: str) -> int:
        return sum(int(h[key] or 0) for h in hires if h["state"] in states)

    cost = [p for p in policies if p.metric == "cost_cents"]
    budget = {
        "company_monthly_cents": company.budget_monthly_cents,
        "company_spent_cents": company.spent_monthly_cents,
        "company_remaining_cents": company.budget_monthly_cents - company.spent_monthly_cents,
        "employees_monthly_cents": sum(a.budget_monthly_cents for a in agents),
        "policies": {
            "active": len(policies),
            "limit_cents": sum(p.amount for p in cost),
            "spent_cents": sum(p.spent_cents for p in cost),
            "reserved_cents": sum(p.reserved_cents for p in cost),
        },
        # Approved hires not yet materialized: capacity already committed.
        "hiring_reserved_cents": cents(("failed",), "amount_cents"),
        "hiring_reserved_monthly_cents": cents(("failed",), "monthly_cents"),
        "hiring_pending_cents": cents(("pending",), "amount_cents"),
        "hiring_pending_monthly_cents": cents(("pending",), "monthly_cents"),
    }

    open_incidents = [
        {"id": str(i.id), "title": i.title, "severity": i.severity, "status": i.status,
         "created_at": _iso(i.created_at)}
        for i in incidents
    ]
    names = {str(a.id): a.name for a in agents}
    attention = [
        f"{names.get(i['employee_id'], 'unassigned')}: {i['title']}"
        for i in _sort_by_time(
            items["blocked"] + items["failed"] + items["stale"], "updated_at"
        )[:5]
    ]
    summary = (
        f"{company.name}: {len(agents)} employee(s), {len(managers)} manager(s). "
        f"Work: {counts['active']} active, {counts['queued']} queued, {counts['stale']} stale, "
        f"{counts['completed']} completed, {counts['failed']} failed, {counts['blocked']} blocked. "
        f"Hiring: {hire_counts['pending']} pending, {hire_counts['approved']} hired, "
        f"{hire_counts['rejected']} rejected, {hire_counts['failed']} failed. "
        f"{len(pending)} approval(s) await a human. "
        f"Budget: {company.spent_monthly_cents} of {company.budget_monthly_cents} cents spent. "
        f"{len(open_incidents)} open incident(s)."
    )
    stamps = [s["latest"] for s in sources.values() if s["latest"]]

    return {
        "schema_version": SCHEMA_VERSION,
        "company": {"id": str(company.id), "name": company.name, "status": company.status},
        "data_as_of": max(stamps, default=None),
        "sources": sources,
        "hierarchy": {
            "ceo_id": next((str(a.id) for a in agents if a.is_ceo), None),
            "roots": roots,
            "depth": depth,
            "managers": managers,
        },
        "employees": {
            "total": len(agents),
            "by_status": dict(Counter(a.status for a in agents)),
            "by_role": dict(Counter(a.role for a in agents)),
            "by_backend": dict(Counter(_backend(a) for a in agents)),
            "list": employees,
        },
        "work": {
            "counts": {b: counts[b] for b in (*BUCKETS, "cancelled")},
            "truncated": len(tasks) >= MAX_TASKS,
            "items": {k: _sort_by_time(v, "updated_at")[:LIST_LIMIT] for k, v in items.items()},
            "latest_results": results,
        },
        "hiring": {
            "counts": {s: hire_counts[s] for s in ("pending", "approved", "rejected", "failed")},
            "requests": _sort_by_time(hires, "created_at")[:100],
        },
        "approvals": {
            "pending": len(pending),
            "by_type": dict(Counter(p["type"] for p in pending)),
            "items": _sort_by_time(pending, "created_at")[:LIST_LIMIT],
        },
        "budget": budget,
        "incidents": {
            "open": len(open_incidents),
            "by_severity": dict(Counter(i["severity"] for i in open_incidents)),
            "items": open_incidents[:LIST_LIMIT],
        },
        "summary": {"text": summary, "attention": attention},
    }


# --- generate ---------------------------------------------------------------


async def _latest(db: Any, company_id: uuid.UUID) -> OrganizationSnapshot | None:
    return (
        await db.execute(
            select(OrganizationSnapshot)
            .where(OrganizationSnapshot.company_id == company_id)
            .order_by(OrganizationSnapshot.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _ensure_state(db: Any, company_id: uuid.UUID) -> None:
    if await db.get(OrganizationSnapshotState, company_id) is None:
        db.add(OrganizationSnapshotState(company_id=company_id))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()


async def _claim(company_id: uuid.UUID, token: str, now: datetime) -> bool:
    """Take the company's generation lease; False while another holds it."""
    from nexus.database import tenant_session

    async with tenant_session(company_id) as db:
        await _ensure_state(db, company_id)
        result = await db.execute(
            update(OrganizationSnapshotState)
            .where(
                OrganizationSnapshotState.company_id == company_id,
                or_(
                    OrganizationSnapshotState.generating_until.is_(None),
                    OrganizationSnapshotState.generating_until < now,
                ),
            )
            .values(generating_until=now + LEASE, generating_by=token, attempted_at=now)
        )
        await db.commit()
        return result.rowcount == 1


async def _read(company_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    """Build in a read transaction of its own, consistent on PostgreSQL."""
    from nexus.database import tenant_session

    async with tenant_session(company_id) as db:
        if db.get_bind().dialect.name == "postgresql":
            await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        try:
            return await build(db, company_id, now)
        finally:
            await db.rollback()


async def generate(company_id: uuid.UUID, now: datetime | None = None) -> dict[str, Any]:
    """Regenerate ``company_id``'s snapshot if its content changed.

    Returns ``{"outcome": created|unchanged|in_progress|failed, "version": ...}``.
    Never raises for a build failure: the error is recorded on the state row
    and every stored version stays as it was.
    """
    from nexus.database import tenant_session

    now = now or _now()
    token = uuid.uuid4().hex
    if not await _claim(company_id, token, now):
        return {"outcome": "in_progress", "version": None}
    try:
        payload = await _read(company_id, now)
    except Exception as exc:  # noqa: BLE001 - recorded, previous snapshot kept
        logger.warning("Organization snapshot for %s failed: %s", company_id, exc)
        async with tenant_session(company_id) as db:
            await db.execute(
                update(OrganizationSnapshotState)
                .where(OrganizationSnapshotState.company_id == company_id,
                       OrganizationSnapshotState.generating_by == token)
                .values(generating_until=None, generating_by=None,
                        last_error=f"{type(exc).__name__}: {str(exc)[:500]}",
                        last_error_at=_now())
            )
            await db.commit()
        return {"outcome": "failed", "version": None}

    digest = payload_hash(payload)
    async with tenant_session(company_id) as db:
        latest = await _latest(db, company_id)
        outcome = "unchanged"
        if latest is None or latest.payload_hash != digest:
            previous = latest.version if latest else 0
            row = OrganizationSnapshot(
                company_id=company_id,
                version=previous + 1,
                schema_version=SCHEMA_VERSION,
                generation_key=f"{SCHEMA_VERSION}:{digest}:{previous}",
                payload_hash=digest,
                generated_at=now,
                data_as_of=datetime.fromisoformat(payload["data_as_of"])
                if payload["data_as_of"] else None,
                payload=payload,
            )
            db.add(row)
            try:
                await db.commit()
                latest, outcome = row, "created"
            except IntegrityError:  # a concurrent writer stored this version first
                await db.rollback()
                latest = await _latest(db, company_id)
        await db.execute(
            update(OrganizationSnapshotState)
            .where(OrganizationSnapshotState.company_id == company_id,
                   OrganizationSnapshotState.generating_by == token)
            .values(generating_until=None, generating_by=None, verified_at=now,
                    last_error=None, last_error_at=None)
        )
        # Only changes seen before this build began are covered by it.
        await db.execute(
            update(OrganizationSnapshotState)
            .where(OrganizationSnapshotState.company_id == company_id,
                   OrganizationSnapshotState.last_dirty_at <= now)
            .values(dirty_since=None, last_dirty_at=None)
        )
        await db.commit()
        return {"outcome": outcome, "version": latest.version if latest else None}


# --- read -------------------------------------------------------------------


def freshness(
    row: OrganizationSnapshot | None, state: OrganizationSnapshotState | None, now: datetime
) -> dict[str, Any]:
    confirmed = max(
        (t for t in (row.generated_at if row else None, state.verified_at if state else None) if t),
        default=None,
    )
    if state and state.generating_until and state.generating_until > now:
        status = REBUILDING
    elif state and state.last_error:  # a successful generation clears it
        status = FAILED_REFRESH
    elif row is None or (state and state.dirty_since) or now - confirmed > STALE_AFTER:
        status = STALE
    else:
        status = FRESH
    return {
        "status": status,
        "age_seconds": int((now - confirmed).total_seconds()) if confirmed else None,
        "verified_at": _iso(confirmed),
        "dirty_since": _iso(state.dirty_since) if state else None,
    }


def manager_view(payload: dict[str, Any], manager_id: uuid.UUID) -> dict[str, Any]:
    """A manager's projection: itself, its direct reports, their work and its hires."""
    mid = str(manager_id)
    everyone = payload["employees"]["list"]
    me = next((e for e in everyone if e["id"] == mid), None)
    team = [e for e in everyone if e["manager_id"] == mid]
    ids = {e["id"] for e in team}
    work = {b: sum(e["work"][b] for e in team) for b in BUCKETS}
    hires = [h for h in payload["hiring"]["requests"] if h["manager_id"] == mid]
    hire_counts = Counter(h["state"] for h in hires)
    name = me["name"] if me else mid
    return {
        "schema_version": payload["schema_version"],
        "company": {"id": payload["company"]["id"], "name": payload["company"]["name"]},
        "data_as_of": payload["data_as_of"],
        "manager": me,
        "employees": {"total": len(team), "list": team},
        "work": {
            "counts": work,
            "items": {
                k: [i for i in v if i["employee_id"] in ids]
                for k, v in payload["work"]["items"].items()
            },
            "latest_results": [
                r for r in payload["work"]["latest_results"] if r["employee_id"] in ids
            ],
        },
        "hiring": {
            "counts": {s: hire_counts[s] for s in ("pending", "approved", "rejected", "failed")},
            "requests": hires,
        },
        "summary": {
            "text": (
                f"{name} has {len(team)} direct report(s): {work['active']} active, "
                f"{work['queued']} queued, {work['stale']} stale, {work['completed']} completed, "
                f"{work['failed']} failed, {work['blocked']} blocked."
            ),
        },
    }


async def read(
    db: Any, company_id: uuid.UUID, scope: str = "organization", manager_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """The latest stored snapshot and its freshness: two indexed lookups, no aggregation."""
    row = await _latest(db, company_id)
    state = await db.get(OrganizationSnapshotState, company_id)
    snapshot = None
    if row is not None:
        snapshot = row.payload if scope == "organization" else manager_view(row.payload, manager_id)
    return {
        "company_id": str(company_id),
        "scope": scope,
        "snapshot": snapshot,
        "version": row.version if row else None,
        "schema_version": row.schema_version if row else SCHEMA_VERSION,
        "generated_at": _iso(row.generated_at) if row else None,
        "data_as_of": _iso(row.data_as_of) if row else None,
        "payload_hash": row.payload_hash if row else None,
        "sources": row.payload.get("sources") if row and scope == "organization" else None,
        "freshness": freshness(row, state, _now()),
        "last_refresh_error": (
            {"message": state.last_error, "at": _iso(state.last_error_at)}
            if state and state.last_error else None
        ),
    }


async def history(db: Any, company_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
    """Newest versions first, metadata only."""
    rows = await db.execute(
        select(
            OrganizationSnapshot.version, OrganizationSnapshot.schema_version,
            OrganizationSnapshot.generated_at, OrganizationSnapshot.data_as_of,
            OrganizationSnapshot.payload_hash,
        )
        .where(OrganizationSnapshot.company_id == company_id)
        .order_by(OrganizationSnapshot.version.desc())
        .limit(max(1, min(limit, HISTORY_MAX)))
    )
    return [
        {"version": r.version, "schema_version": r.schema_version,
         "generated_at": _iso(r.generated_at), "data_as_of": _iso(r.data_as_of),
         "payload_hash": r.payload_hash}
        for r in rows.all()
    ]


async def agent_scope(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
    """What an agent may read: ``organization``, ``manager`` or nothing.

    Organization-wide for the company's current CEO, or when an active allow
    ToolPolicy of the company names :data:`TOOL` literally and pins this agent,
    and access to the tool is not denied. Otherwise a manager (an agent with
    direct reports) gets its own projection, and anyone else nothing.
    """
    from nexus.models.tool import ToolPolicy
    from nexus.services import ceo_service
    from nexus.tools.access import DENIED, check_tool_access, names_tool
    from nexus.tools.context import INBOUND_MCP, ExecutionContext
    from nexus.tools.manager_tools import _agent_ids

    if await ceo_service.is_ceo(db, company_id, agent_id):
        return "organization"
    allows = (
        await db.execute(
            select(ToolPolicy).where(
                ToolPolicy.company_id == company_id,
                ToolPolicy.is_active == True,  # noqa: E712
                ToolPolicy.effect == "allow",
            )
        )
    ).scalars().all()
    if any(names_tool(p.conditions, TOOL) and str(agent_id) in _agent_ids(p.conditions)
           for p in allows):
        ctx = ExecutionContext(company_id=company_id, principal_id=f"agent:{agent_id}",
                               principal_role="agent", source=INBOUND_MCP, agent_id=agent_id)
        decision = await check_tool_access(db, ctx, tool_name=TOOL, default_risk="read")
        if decision.outcome != DENIED:
            return "organization"
    if await ms.direct_reports(db, company_id, agent_id):
        return "manager"
    return None


async def read_as_agent(
    db: Any, company_id: uuid.UUID, agent_id: uuid.UUID, actor: str
) -> dict[str, Any]:
    """An agent's read: its :func:`agent_scope`, audited; 403 for anyone else."""
    scope = await agent_scope(db, company_id, agent_id)
    if scope is None:
        raise ms._error(
            403, "SNAPSHOT_FORBIDDEN", "Only managers may read the organization snapshot"
        )
    result = await read(db, company_id, scope, agent_id)
    await ms.audit(
        db, company_id, "organization.snapshot_read", actor, "organization_snapshot", company_id,
        scope=scope, version=result["version"],
    )
    await db.commit()
    return result


# --- refresh model ----------------------------------------------------------


async def mark_dirty(company_ids: set[uuid.UUID], now: datetime | None = None) -> None:
    from nexus.database import tenant_session

    now = now or _now()
    for company_id in sorted(company_ids, key=str):
        try:
            async with tenant_session(company_id) as db:
                await _ensure_state(db, company_id)
                await db.execute(
                    update(OrganizationSnapshotState)
                    .where(OrganizationSnapshotState.company_id == company_id)
                    .values(
                        dirty_since=func.coalesce(OrganizationSnapshotState.dirty_since, now),
                        last_dirty_at=now,
                    )
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - reconciliation catches a missed mark
            logger.warning("Could not mark organization %s dirty: %s", company_id, exc)


def _due(state: Any, now: datetime) -> bool:
    if state.generating_until and state.generating_until > now:
        return False
    recently = state.attempted_at and now - state.attempted_at < DEBOUNCE
    if state.dirty_since and not recently and (
        state.last_dirty_at <= now - DEBOUNCE or state.dirty_since <= now - MAX_WAIT
    ):
        return True
    return state.attempted_at is None or now - state.attempted_at >= RECONCILE_EVERY


async def tick(now: datetime | None = None) -> list[uuid.UUID]:
    """Scheduler hook: regenerate debounced dirty companies and reconcile the rest."""
    from nexus.database import system_session

    now = now or _now()
    async with system_session("organization snapshot: due companies") as db:
        rows = (
            await db.execute(
                select(
                    Company.id,
                    OrganizationSnapshotState.dirty_since,
                    OrganizationSnapshotState.last_dirty_at,
                    OrganizationSnapshotState.generating_until,
                    OrganizationSnapshotState.attempted_at,
                ).outerjoin(
                    OrganizationSnapshotState,
                    OrganizationSnapshotState.company_id == Company.id,
                )
            )
        ).all()
    due = sorted(
        (r for r in rows if _due(r, now)),
        key=lambda r: (r.attempted_at or datetime.min, str(r.id)),
    )
    done = []
    for r in due[:MAX_PER_TICK]:
        await generate(r.id, now)
        done.append(r.id)
    return done


# Dirty marking from committed writes: session hooks collect the companies a
# transaction touched and, after commit, publish one event per company on the
# realtime bus. Bulk UPDATE/DELETE statements are attributed through their
# ``company_id = :value`` (or ``companies.id``) criterion; one without it is
# left to reconciliation.

_INFO_KEY = "org_snapshot_dirty"
_pending: set[asyncio.Task] = set()
_listener: asyncio.Task | None = None
_queue: asyncio.Queue | None = None


def _company_in(statement: Any, table: str) -> uuid.UUID | None:
    column = "id" if table == "companies" else "company_id"
    where = getattr(statement, "whereclause", None)
    if where is None:
        return None
    for node in visitors.iterate(where):
        if (
            isinstance(node, BinaryExpression)
            and node.operator is operators.eq
            and getattr(node.left, "key", None) == column
            and isinstance(node.right, BindParameter)
        ):
            value = node.right.effective_value
            if isinstance(value, uuid.UUID):
                return value
    return None


def _collect(session: Session, _flush_context: Any) -> None:
    touched = session.info.setdefault(_INFO_KEY, set())
    for obj in chain(session.new, session.dirty, session.deleted):
        table = getattr(obj, "__tablename__", None)
        if table in TRACKED_TABLES:
            company_id = obj.id if table == "companies" else getattr(obj, "company_id", None)
            if isinstance(company_id, uuid.UUID):
                touched.add(company_id)


def _collect_bulk(state: Any) -> None:
    if not (state.is_update or state.is_delete) or state.bind_mapper is None:
        return
    table = getattr(state.bind_mapper.persist_selectable, "name", None)
    if table in TRACKED_TABLES:
        company_id = _company_in(state.statement, table)
        if company_id is not None:
            state.session.info.setdefault(_INFO_KEY, set()).add(company_id)


def _publish(session: Session) -> None:
    from nexus.realtime.publish import publish_event

    touched = session.info.pop(_INFO_KEY, None)
    if not touched:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for company_id in touched:
        task = loop.create_task(publish_event(ORG_CHANNEL, CHANGED, company_id, {}))
        _pending.add(task)
        task.add_done_callback(_pending.discard)


def _forget(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)


_HOOKS = (
    ("after_flush", _collect),
    ("do_orm_execute", _collect_bulk),
    ("after_commit", _publish),
    ("after_rollback", _forget),
)


async def _listen(queue: asyncio.Queue) -> None:
    while True:
        batch = [await queue.get()]
        while not queue.empty():
            batch.append(queue.get_nowait())
        touched = {e.company_id for e in batch if e.company_id is not None}
        if touched:
            await mark_dirty(touched)


async def start_listener() -> None:
    """Install the dirty-marking hooks and subscribe to the realtime bus."""
    global _listener, _queue
    from nexus.api.routes.events import event_bus

    if _listener is not None:
        return
    for name, fn in _HOOKS:
        if not event.contains(Session, name, fn):
            event.listen(Session, name, fn)
    _queue = asyncio.Queue(maxsize=1024)
    for topic in DIRTY_EVENTS:
        event_bus.subscribe(topic, _queue)
    _listener = asyncio.create_task(_listen(_queue), name="org-snapshot-listener")


async def stop_listener() -> None:
    global _listener, _queue
    from nexus.api.routes.events import event_bus

    for name, fn in _HOOKS:
        if event.contains(Session, name, fn):
            event.remove(Session, name, fn)
    if _queue is not None:
        for topic in DIRTY_EVENTS:
            event_bus.unsubscribe(topic, _queue)
    if _listener is not None:
        _listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _listener
    _listener = _queue = None
