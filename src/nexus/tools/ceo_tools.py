"""CEO tools: the governed tools of the company's current CEO.

Served beside the manager tools by the inbound MCP server, through
:func:`nexus.tools.factory.guarded_call`. Every call first re-reads the CEO
designation in its own transaction (:func:`ceo_service.require_ceo`), so a
replaced or removed CEO is refused at once, whatever it was offered earlier.
The tools reuse the existing services and records: the organization
snapshot, :func:`manager_service.delegate` (a TaskAttempt), ``Goal`` and
``Task`` rows, :func:`hiring_service.submit`, and executive memory.

Write tools are in :data:`nexus.tools.access.EXPLICIT_ALLOW_ONLY`: only an
active allow ToolPolicy that names the tool literally permits them; the
inbound default read policy never does. There is deliberately no tool to
approve anything, change a policy, permission or designation, read a secret,
or create an agent: a hire is a request that the hiring policy and a human
decide.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nexus.models.task import Goal, Task
from nexus.runtime.task_attempts import WorkSpec, attempt_view
from nexus.services import ceo_service, hiring_service, org_snapshot
from nexus.services import manager_service as ms
from nexus.tools.effects import EffectClass
from nexus.tools.manager_tools import ManagerTool

_NAMESPACE = uuid.UUID("5d0b8f3e-6c1a-4f53-9a57-3e1f0c2b7a90")


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ManagerRef(_Args):
    manager_id: uuid.UUID


class SearchMemory(_Args):
    query: str | None = Field(default=None, max_length=200)
    type: ceo_service.MemoryType | None = None
    limit: int = Field(default=10, ge=1, le=ceo_service.SEARCH_MAX)


class Delegate(_Args):
    manager_id: uuid.UUID
    task_id: uuid.UUID


class GoalOrWorkOrder(_Args):
    kind: Literal["goal", "work_order"]
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    owner_agent_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None
    priority: int = Field(default=0, ge=0, le=10)
    work_spec: WorkSpec | None = None


class Decision(_Args):
    type: Literal["decision", "commitment", "risk", "outcome"] = "decision"
    content: str = Field(min_length=1, max_length=ceo_service.CONTENT_MAX)
    refs: dict[str, uuid.UUID] = Field(default_factory=dict, max_length=8)
    supersedes: uuid.UUID | None = None
    resolves: uuid.UUID | None = None


def _source(ctx: Any) -> dict[str, Any]:
    return {"turn_id": ctx.turn_id, "session_id": ctx.session_id}


async def _snapshot(db, company_id, ceo_id, args, actor, ctx):
    return await org_snapshot.read_as_agent(db, company_id, ceo_id, actor, ctx)


async def _managers(db, company_id, ceo_id, args, actor, ctx):
    snap = await org_snapshot.read(db, company_id)
    payload = snap["snapshot"] or {"hierarchy": {"managers": []}}
    return {"version": snap["version"], "freshness": snap["freshness"],
            "managers": payload["hierarchy"]["managers"]}


async def _manager_status(db, company_id, ceo_id, args, actor, ctx):
    await ms.get_agent(db, company_id, args.manager_id)
    snap = await org_snapshot.read(db, company_id, "manager", args.manager_id)
    return {k: snap[k] for k in ("version", "generated_at", "freshness", "snapshot")}


async def _approvals(db, company_id, ceo_id, args, actor, ctx):
    snap = await org_snapshot.read(db, company_id)
    return {"version": snap["version"], "freshness": snap["freshness"],
            "approvals": (snap["snapshot"] or {}).get("approvals")}


async def _search(db, company_id, ceo_id, args, actor, ctx):
    rows = await ceo_service.recall(db, company_id, query=args.query, type=args.type,
                                    limit=args.limit)
    return [ceo_service.entry_view(r) for r in rows]


async def _delegate(db, company_id, ceo_id, args, actor, ctx):
    principal = SimpleNamespace(kind="agent", display_name=actor)
    attempt, created = await ms.delegate(
        db, company_id, ceo_id, args.manager_id, args.task_id, principal
    )
    if created:
        await ceo_service.remember(
            db, company_id,
            ceo_service.MemoryEntry(
                type="delegation", content=f"Delegated task {args.task_id} to {args.manager_id}",
                refs={"task_id": args.task_id, "manager_id": args.manager_id},
            ),
            recorded_by=actor, origin="tool", source={**_source(ctx), "attempt_id": attempt.id},
        )
        await db.commit()
    return {"created": created, "attempt": attempt_view(attempt)}


async def _create(db, company_id, ceo_id, args, actor, ctx):
    new_id = uuid.uuid5(_NAMESPACE, f"{company_id}:{ceo_id}:{args.kind}:{args.idempotency_key}")
    model = Goal if args.kind == "goal" else Task
    existing = await db.get(model, new_id)
    if existing is not None:
        if existing.title != args.title:
            raise ms._error(409, "IDEMPOTENCY_KEY_REUSED",
                            "This idempotency key was used for a different request")
        return {"created": False, "kind": args.kind, "id": str(new_id)}
    if args.owner_agent_id is not None:
        await ms.get_agent(db, company_id, args.owner_agent_id)
    if args.goal_id is not None:
        goal = await db.get(Goal, args.goal_id)
        if goal is None or goal.company_id != company_id:
            raise ms._error(404, "GOAL_NOT_FOUND", f"Goal {args.goal_id} not found")
    if args.kind == "goal":
        db.add(Goal(id=new_id, company_id=company_id, title=args.title,
                    description=args.description, level="company", parent_id=args.goal_id,
                    owner_agent_id=args.owner_agent_id))
    else:
        db.add(Task(id=new_id, company_id=company_id, title=args.title,
                    description=args.description, priority=args.priority, goal_id=args.goal_id,
                    work_spec=args.work_spec and args.work_spec.model_dump(mode="json")))
    await db.flush()
    await ms.audit(db, company_id, f"ceo.{args.kind}_created", actor,
                   "goal" if args.kind == "goal" else "task", new_id, ceo_id=ceo_id,
                   idempotency_key=args.idempotency_key)
    await ceo_service.remember(
        db, company_id,
        ceo_service.MemoryEntry(
            type="commitment", content=f"Created {args.kind.replace('_', ' ')}: {args.title}",
            refs={"goal_id" if args.kind == "goal" else "task_id": new_id},
        ),
        recorded_by=actor, origin="tool", source=_source(ctx),
    )
    await db.commit()
    return {"created": True, "kind": args.kind, "id": str(new_id)}


async def _decide(db, company_id, ceo_id, args, actor, ctx):
    record = await ceo_service.remember(
        db, company_id, ceo_service.MemoryEntry(**args.model_dump()),
        recorded_by=actor, origin="tool", source=_source(ctx),
    )
    await db.commit()
    return ceo_service.entry_view(record)


async def _hire(db, company_id, ceo_id, args, actor, ctx):
    approval, created = await hiring_service.submit(db, company_id, ceo_id, args, actor)
    view = await hiring_service.view(db, approval)
    if created:
        await ceo_service.remember(
            db, company_id,
            ceo_service.MemoryEntry(
                type="hiring", content=f"Requested hire: {args.title} ({args.role})",
                refs={"hiring_request_id": approval.id},
            ),
            recorded_by=actor, origin="tool", source=_source(ctx),
        )
        await db.commit()
    return {"created": created, **view}


CEO_TOOLS: dict[str, ManagerTool] = {
    "ceo_get_organization_snapshot": ManagerTool(
        "The latest precomputed organization snapshot, its version, hash and freshness. "
        "Takes no arguments: call it with an empty object.",
        "read", (), _snapshot,
        effect=EffectClass.READ_ONLY,
    ),
    "ceo_list_managers": ManagerTool(
        "Managers with their direct reports and work states, from the latest snapshot.",
        "read", (), _managers,
        effect=EffectClass.READ_ONLY,
    ),
    "ceo_get_manager_status": ManagerTool(
        "One manager's team projection from the latest snapshot.",
        "read", (), _manager_status, ManagerRef,
        effect=EffectClass.READ_ONLY,
    ),
    "ceo_list_pending_approvals": ManagerTool(
        "Approvals awaiting a human, from the latest snapshot. Read-only: the CEO "
        "cannot approve anything.",
        "read", (), _approvals,
        effect=EffectClass.READ_ONLY,
    ),
    "ceo_search_executive_memory": ManagerTool(
        "Search active executive memory (directives, decisions, commitments, delegations, "
        "hires, risks, outcomes), newest first. Only active memory is searched: candidate, "
        "archived, superseded and rejected entries are never returned. Memory is not "
        "status: the snapshot is.",
        "read", (), _search, SearchMemory,
        effect=EffectClass.READ_ONLY,
    ),
    "ceo_delegate_task_to_manager": ManagerTool(
        "Delegate an existing work task to a manager who reports to you. Queues a task "
        "attempt; idempotent.",
        "write", (), _delegate, Delegate,
        effect=EffectClass.IDEMPOTENT_WRITE,
    ),
    "ceo_create_goal_or_work_order": ManagerTool(
        "Create a company goal or a work order (task). Idempotent per idempotency_key.",
        "write", (), _create, GoalOrWorkOrder,
        effect=EffectClass.IDEMPOTENT_WRITE,
    ),
    "ceo_record_decision": ManagerTool(
        "Record a decision, commitment, risk or outcome in executive memory. May supersede "
        "or resolve an earlier entry.",
        "write", (), _decide, Decision,
        effect=EffectClass.NON_IDEMPOTENT_WRITE,
    ),
    "ceo_request_hire": ManagerTool(
        "Request a new direct report through the hiring workflow. The hiring policy and "
        "a human decide; you cannot approve it.",
        "write", (), _hire, hiring_service.HireRequest,
        effect=EffectClass.IDEMPOTENT_WRITE,
    ),
}
WRITE_TOOLS = frozenset(n for n, t in CEO_TOOLS.items() if t.risk != "read")


async def run(ctx: Any, name: str, args: Any) -> Any:
    """Run CEO tool ``name`` as the context's agent, only while it is the CEO."""
    from nexus.database import tenant_session

    tool = CEO_TOOLS[name]
    actor = f"agent:{ctx.agent_id}"
    async with tenant_session(ctx.company_id) as db:
        await ceo_service.require_ceo(db, ctx.company_id, ctx.agent_id)
        return await tool.run(db, ctx.company_id, ctx.agent_id, args, actor, ctx)
