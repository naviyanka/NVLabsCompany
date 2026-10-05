"""Manager tools: what a manager agent may ask about, and do to, its direct reports.

Served by the inbound MCP server (:mod:`nexus.tools.mcp_server`) through
:func:`nexus.tools.factory.guarded_call`, like every other governed tool. The
caller's identity is the server-built context's agent (from the run token),
never an argument: each tool acts as that manager, inside its company, and
only on agents whose ``manager_id`` is that manager. There is no free-form
query; the one org-wide read, ``organization_get_snapshot``, returns the
precomputed snapshot and needs an explicit policy for more than the team.
``manager_delegate_task`` and ``manager_request_hire`` are write-risk, so under
the inbound default policy they stay denied until the company allows them. A
manager cannot create an agent directly: it can only file a hiring request,
which the hiring policy and a human decide.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nexus.runtime.task_attempts import MAX_DELIVERABLE_CHARS, attempt_view
from nexus.services import hiring_service, org_snapshot, work_service
from nexus.services import manager_service as ms
from nexus.tools.effects import (
    BRIDGE_KEY_HINT,
    BRIDGE_KEY_PATTERN,
    EffectClass,
    EffectNotStarted,
    bridge_key_field,
    downstream_key,
    resolve_effect,
)


@dataclass(frozen=True)
class ManagerTool:
    description: str
    risk: str
    params: tuple[str, ...]
    run: Callable[[Any, uuid.UUID, uuid.UUID, Any, str], Awaitable[Any]]
    # Arguments other than UUIDs: validated by this model, which forbids extras.
    model: type[BaseModel] | None = None
    # Required, with no default: a tool cannot be defined without saying whether a rerun of
    # an interrupted call is safe (see nexus.tools.effects).
    effect: EffectClass = field(kw_only=True)


async def _list_reports(db, company_id, manager_id, args, actor):
    return [ms.agent_ref(a) for a in await ms.direct_reports(db, company_id, manager_id)]


async def _employee_status(db, company_id, manager_id, args, actor):
    employee = await ms.require_report(db, company_id, manager_id, args["employee_id"])
    result = await ms.employee_status(db, employee)
    await ms.audit(
        db, company_id, "manager.status_inspected", actor, "agent", employee.id,
        manager_id=manager_id, state=result["state"],
    )
    await db.commit()
    return result


async def _delegate(db, company_id, manager_id, args, actor):
    principal = SimpleNamespace(kind="agent", display_name=actor)
    attempt, created = await ms.delegate(
        db, company_id, manager_id, args["employee_id"], args["task_id"], principal
    )
    return {"created": created, "attempt": attempt_view(attempt)}


class AssignWork(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    work_id: uuid.UUID
    employee_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    objective: str = Field(min_length=1, max_length=4000)
    expected_deliverable: str | None = Field(default=None, max_length=500)
    max_deliverable_chars: int | None = Field(default=None, ge=100, le=MAX_DELIVERABLE_CHARS)
    max_attempts: int | None = Field(default=None, ge=1, le=5)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ReviewWork(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    attempt_id: uuid.UUID
    decision: Literal["verify", "reject"]
    reason: str | None = Field(default=None, max_length=1000)
    retry: bool = False


async def _assign_work(db, company_id, manager_id, args, actor):
    principal = SimpleNamespace(kind="agent", display_name=actor)
    task, attempt, created = await work_service.assign_task(
        db, company_id, manager_id, args.work_id, args.employee_id,
        title=args.title, objective=args.objective, idempotency_key=args.idempotency_key,
        expected_deliverable=args.expected_deliverable,
        max_deliverable_chars=args.max_deliverable_chars,
        attempts_cap=args.max_attempts, principal=principal,
    )
    return {"created": created, "task_id": str(task.id), "attempt": attempt_view(attempt)}


async def _review_work(db, company_id, manager_id, args, actor):
    attempt, changed = await work_service.review(
        db, company_id, args.attempt_id, decision=args.decision, reason=args.reason,
        actor=actor, reviewer_agent_id=manager_id, retry=args.retry,
    )
    return {"changed": changed, "attempt": attempt_view(attempt)}


async def _evidence(db, company_id, manager_id, args, actor):
    result = await ms.task_evidence(db, company_id, manager_id, args["task_id"])
    await ms.audit(
        db, company_id, "manager.evidence_inspected", actor, "task", args["task_id"],
        manager_id=manager_id,
    )
    await db.commit()
    return result


async def _rollup(db, company_id, manager_id, args, actor):
    result = await ms.rollup(db, company_id, manager_id)
    await ms.audit(
        db, company_id, "manager.report_generated", actor, "agent", manager_id,
        counts=result["counts"],
    )
    await db.commit()
    return result


async def _request_hire(db, company_id, manager_id, args, actor):
    approval, created = await hiring_service.submit(db, company_id, manager_id, args, actor)
    return {"created": created, **await hiring_service.view(db, approval)}


async def _list_hires(db, company_id, manager_id, args, actor):
    rows = await hiring_service.list_requests(db, company_id, manager_id)
    return [await hiring_service.view(db, a) for a in rows]


async def _get_hire(db, company_id, manager_id, args, actor):
    approval = await hiring_service.get_request(db, company_id, args["request_id"], manager_id)
    return await hiring_service.view(db, approval)


async def _org_snapshot(db, company_id, manager_id, args, actor):
    return await org_snapshot.read_as_agent(db, company_id, manager_id, actor)


MANAGER_TOOLS: dict[str, ManagerTool] = {
    "manager_list_reports": ManagerTool(
        "List your direct reports.", "read", (), _list_reports,
        effect=EffectClass.READ_ONLY,
    ),
    "manager_employee_status": ManagerTool(
        "Current state, active task, progress, evidence, last success and latest failure "
        "of one direct report.",
        "read",
        ("employee_id",),
        _employee_status,
        effect=EffectClass.READ_ONLY,
    ),
    "manager_delegate_task": ManagerTool(
        "Delegate an existing task to one of your direct reports. Idempotent.",
        "write",
        ("task_id", "employee_id"),
        _delegate,
        effect=EffectClass.IDEMPOTENT_WRITE,
    ),
    "manager_assign_work": ManagerTool(
        "Create one task under a work order delegated to you and assign it to a direct "
        "report, with the deliverable you expect. Idempotent per idempotency_key.",
        "write",
        (),
        _assign_work,
        AssignWork,
        effect=EffectClass.IDEMPOTENT_WRITE,
    ),
    "manager_review_work": ManagerTool(
        "Verify or reject a deliverable submitted by a direct report. Rejection needs a "
        "reason and may request one bounded retry. You cannot review your own work.",
        "write",
        (),
        _review_work,
        ReviewWork,
        effect=EffectClass.IDEMPOTENT_WRITE,
    ),
    "manager_task_evidence": ManagerTool(
        "Attempts, results and evidence of a task held by one of your direct reports.",
        "read",
        ("task_id",),
        _evidence,
        effect=EffectClass.READ_ONLY,
    ),
    "manager_rollup": ManagerTool(
        "Your team roll-up: active, queued, completed, failed/blocked and stale work.",
        "read",
        (),
        _rollup,
        effect=EffectClass.READ_ONLY,
    ),
    "manager_request_hire": ManagerTool(
        "Request a new direct report. The company's hiring policy decides: auto-approved "
        "within explicit limits, otherwise a human approves or rejects it. Idempotent per "
        "idempotency_key. Backends come from the server's CLI registry.",
        "write",
        (),
        _request_hire,
        hiring_service.HireRequest,
        effect=EffectClass.IDEMPOTENT_WRITE,
    ),
    "manager_list_hiring_requests": ManagerTool(
        "Your hiring requests: status, policy decision, costs and the hired employee.",
        "read",
        (),
        _list_hires,
        effect=EffectClass.READ_ONLY,
    ),
    "manager_get_hiring_request": ManagerTool(
        "One of your hiring requests.",
        "read",
        ("request_id",),
        _get_hire,
        effect=EffectClass.READ_ONLY,
    ),
    org_snapshot.TOOL: ManagerTool(
        "The latest precomputed organization snapshot and its freshness: your team's "
        "projection, or the whole organization when a policy explicitly allows you "
        "org-wide reporting. Read-only. Takes no arguments: call it with an empty object.",
        "read",
        (),
        _org_snapshot,
        effect=EffectClass.READ_ONLY,
    ),
}


def input_schema(tool: ManagerTool) -> dict[str, Any]:
    """MCP ``inputSchema`` for a manager tool: its model's, or its UUID parameters."""
    if tool.model is not None:
        return tool.model.model_json_schema()
    return {
        "type": "object",
        "properties": {p: {"type": "string", "format": "uuid"} for p in tool.params},
        "required": list(tool.params),
        "additionalProperties": False,
    }


def is_write(tool: ManagerTool) -> bool:
    """Whether the tool's declared effect class is anything but read-only (undeclared = write)."""
    return resolve_effect(tool.effect) is not EffectClass.READ_ONLY


def key_field(tool: ManagerTool) -> str:
    """The argument a bridge write to ``tool`` takes its identity from."""
    return bridge_key_field(tool.model.model_fields if tool.model is not None else ())


def bridge_input_schema(tool: ManagerTool) -> dict[str, Any]:
    """The ``inputSchema`` the HTTP bridge advertises: a write also requires its identity.

    A client that cannot attach a per-call header (stock Claude Code) still sends the arguments
    the schema declares, so the identity is declared here as a required argument. A read-only
    tool is unchanged.
    """
    schema = input_schema(tool)
    if not is_write(tool):
        return schema
    field = key_field(tool)
    properties = dict(schema.get("properties", {}))
    properties[field] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 128,
        "pattern": BRIDGE_KEY_PATTERN.pattern,
        "description": BRIDGE_KEY_HINT,
    }
    required = list(schema.get("required", []))
    if field not in required:
        required.append(field)
    return {**schema, "properties": properties, "required": required}


def bridge_description(tool: ManagerTool) -> str:
    """The tool description with the instruction to generate a key per intentional call."""
    if not is_write(tool):
        return tool.description
    return (
        f"{tool.description} Set `{key_field(tool)}` to a NEW unique value on every "
        "intentional call; reuse a value only to retry a call whose outcome you did not see."
    )


async def call(ctx: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Run manager or CEO tool ``name`` as the context's agent, in its company.

    A tool that carries an ``idempotency_key`` has it replaced, inside a ledgered call, by the
    call's ledger key. The model invents a fresh key on every rerun, so trusting its own would
    let a recovered turn file a second hire or work order; the ledger key is the same for the
    same logical call, so the service's own dedupe collapses the rerun.

    Raises:
        EffectNotStarted: No agent identity, or a missing or malformed argument. A ValueError,
            and proven pre-effect: nothing was dispatched.
        fastapi.HTTPException: The service refused (not found, not a report).
    """
    from nexus.database import tenant_session
    from nexus.tools.ceo_tools import CEO_TOOLS
    from nexus.tools.ceo_tools import run as run_ceo_tool

    if ctx.agent_id is None:
        raise EffectNotStarted("manager tools need an agent identity")
    tool = MANAGER_TOOLS.get(name) or CEO_TOOLS[name]
    args: Any
    if tool.model is not None:
        try:
            args = tool.model.model_validate(arguments)
        except ValidationError as exc:
            raise EffectNotStarted(f"invalid arguments: {exc.errors(include_url=False)}") from exc
        if hasattr(args, "idempotency_key"):
            args = args.model_copy(
                update={"idempotency_key": downstream_key(args.idempotency_key)}
            )
    else:
        extra = set(arguments) - set(tool.params)
        if extra:
            raise EffectNotStarted(f"unexpected arguments: {sorted(extra)}")
        try:
            args = {p: uuid.UUID(str(arguments[p])) for p in tool.params}
        except (KeyError, ValueError) as exc:
            raise EffectNotStarted(f"expected UUID arguments {list(tool.params)}") from exc
    if name not in MANAGER_TOOLS:
        return await run_ceo_tool(ctx, name, args)
    async with tenant_session(ctx.company_id) as db:
        if name == org_snapshot.TOOL:
            return await org_snapshot.read_as_agent(
                db, ctx.company_id, ctx.agent_id, f"agent:{ctx.agent_id}", ctx
            )
        return await tool.run(db, ctx.company_id, ctx.agent_id, args, f"agent:{ctx.agent_id}")


async def catalog(ctx: Any) -> dict[str, ManagerTool]:
    """The governed tools the context's agent is offered, least privilege first.

    * The company's current CEO: the CEO tools.
    * An agent with at least one direct report: the manager tools.
    * An agent with none yet, pinned (``agent_id``) by an active allow
      ToolPolicy of its company that names a manager tool, access to which is
      not denied: the manager tools, which is how a new manager hires its
      first report; or only :data:`org_snapshot.TOOL` when that is the one
      tool so named.
    * Anyone else: nothing.

    Role, title and prompt text never count, and being offered a tool never
    authorizes a call: every call still passes ``guarded_call``.
    """
    from sqlalchemy import select

    from nexus.database import tenant_session
    from nexus.models.tool import ToolPolicy
    from nexus.services import ceo_service
    from nexus.tools.access import DENIED, check_tool_access, names_tool
    from nexus.tools.ceo_tools import CEO_TOOLS

    # A task attempt is work, not management: it is offered no governed tool.
    if ctx.agent_id is None or ctx.work_mode is not None:
        return {}
    async with tenant_session(ctx.company_id) as db:
        if await ceo_service.is_ceo(db, ctx.company_id, ctx.agent_id):
            return dict(CEO_TOOLS)
        if await ms.direct_reports(db, ctx.company_id, ctx.agent_id):
            return dict(MANAGER_TOOLS)
        rows = (
            await db.execute(
                select(ToolPolicy).where(
                    ToolPolicy.company_id == ctx.company_id,
                    ToolPolicy.is_active == True,  # noqa: E712
                    ToolPolicy.effect == "allow",
                )
            )
        ).scalars().all()
        named = {
            name
            for r in rows
            if str(ctx.agent_id) in _agent_ids(r.conditions)
            for name in MANAGER_TOOLS
            if names_tool(r.conditions, name)
        }
        allowed = set()
        for name in sorted(named):
            decision = await check_tool_access(
                db, ctx, tool_name=name, default_risk=MANAGER_TOOLS[name].risk
            )
            if decision.outcome != DENIED:
                allowed.add(name)
    if allowed - {org_snapshot.TOOL}:
        return dict(MANAGER_TOOLS)
    return {name: MANAGER_TOOLS[name] for name in allowed}


def _agent_ids(conditions: dict[str, Any] | None) -> list[str]:
    ids = (conditions or {}).get("agent_id")
    return [ids] if isinstance(ids, str) else list(ids or [])
