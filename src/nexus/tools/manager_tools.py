"""Manager tools: what a manager agent may ask about, and do to, its direct reports.

Served by the inbound MCP server (:mod:`nexus.tools.mcp_server`) through
:func:`nexus.tools.factory.guarded_call`, like every other governed tool. The
caller's identity is the server-built context's agent (from the run token),
never an argument: each tool acts as that manager, inside its company, and
only on agents whose ``manager_id`` is that manager. There is no org-wide or
free-form query. ``manager_delegate_task`` is write-risk, so under the inbound
default policy it stays denied until the company allows it.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from nexus.runtime.task_attempts import attempt_view
from nexus.services import manager_service as ms


@dataclass(frozen=True)
class ManagerTool:
    description: str
    risk: str
    params: tuple[str, ...]
    run: Callable[[Any, uuid.UUID, uuid.UUID, dict[str, uuid.UUID], str], Awaitable[Any]]


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


MANAGER_TOOLS: dict[str, ManagerTool] = {
    "manager_list_reports": ManagerTool(
        "List your direct reports.", "read", (), _list_reports
    ),
    "manager_employee_status": ManagerTool(
        "Current state, active task, progress, evidence, last success and latest failure "
        "of one direct report.",
        "read",
        ("employee_id",),
        _employee_status,
    ),
    "manager_delegate_task": ManagerTool(
        "Delegate an existing task to one of your direct reports. Idempotent.",
        "write",
        ("task_id", "employee_id"),
        _delegate,
    ),
    "manager_task_evidence": ManagerTool(
        "Attempts, results and evidence of a task held by one of your direct reports.",
        "read",
        ("task_id",),
        _evidence,
    ),
    "manager_rollup": ManagerTool(
        "Your team roll-up: active, queued, completed, failed/blocked and stale work.",
        "read",
        (),
        _rollup,
    ),
}


def input_schema(tool: ManagerTool) -> dict[str, Any]:
    """MCP ``inputSchema`` for a manager tool: its UUID parameters, all required."""
    return {
        "type": "object",
        "properties": {p: {"type": "string", "format": "uuid"} for p in tool.params},
        "required": list(tool.params),
        "additionalProperties": False,
    }


async def call(ctx: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Run manager tool ``name`` as the context's agent, in the context's company.

    Raises:
        ValueError: No agent identity, or a missing or malformed argument.
        fastapi.HTTPException: The service refused (not found, not a report).
    """
    from nexus.database import tenant_session

    if ctx.agent_id is None:
        raise ValueError("manager tools need an agent identity")
    tool = MANAGER_TOOLS[name]
    extra = set(arguments) - set(tool.params)
    if extra:
        raise ValueError(f"unexpected arguments: {sorted(extra)}")
    try:
        args = {p: uuid.UUID(str(arguments[p])) for p in tool.params}
    except (KeyError, ValueError) as exc:
        raise ValueError(f"expected UUID arguments {list(tool.params)}") from exc
    async with tenant_session(ctx.company_id) as db:
        return await tool.run(db, ctx.company_id, ctx.agent_id, args, f"agent:{ctx.agent_id}")


async def is_manager(ctx: Any) -> bool:
    """Whether the context's agent has at least one direct report."""
    from nexus.database import tenant_session

    if ctx.agent_id is None:
        return False
    async with tenant_session(ctx.company_id) as db:
        return bool(await ms.direct_reports(db, ctx.company_id, ctx.agent_id))
