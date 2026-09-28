"""Manager API: delegate to direct reports and read their status and roll-up.

Thin shells over :mod:`nexus.services.manager_service`. The reporting line
itself is set by ``PUT /api/v1/agents/{agent_id}/manager``. A caller acting
as an agent (a run token) may act only as its own manager identity. Every
read here is audited, since it exposes another agent's work.

Also the manager bridge's MCP endpoint (:mod:`nexus.tools.manager_bridge`),
which a CLI manager calls during its own chat turn.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession, require_permission
from nexus.runtime.task_attempts import attempt_view
from nexus.services import manager_service
from nexus.tools import manager_bridge

router = APIRouter(tags=["managers"])

READ = [require_permission("read", "task")]
WRITE = [require_permission("write", "task")]


class DelegationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    employee_id: uuid.UUID


def _as_manager(principal: Any, manager_id: uuid.UUID) -> None:
    if principal.agent_id is not None and principal.agent_id != manager_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "NOT_THIS_MANAGER", "message": "An agent may act only as itself"},
        )


@router.post("/api/v1/agents/{manager_id}/delegations", dependencies=WRITE)
async def delegate_task(
    manager_id: uuid.UUID,
    body: DelegationRequest,
    response: Response,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Delegate an existing task to a direct report; 201 when a new attempt is queued."""
    _as_manager(principal, manager_id)
    attempt, created = await manager_service.delegate(
        db, company_id, manager_id, body.employee_id, body.task_id, principal
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return attempt_view(attempt)


@router.get("/api/v1/agents/{manager_id}/reports/{employee_id}/status", dependencies=READ)
async def employee_status(
    manager_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Structured status of one direct report."""
    _as_manager(principal, manager_id)
    employee = await manager_service.require_report(db, company_id, manager_id, employee_id)
    result = await manager_service.employee_status(db, employee)
    await manager_service.audit(
        db, company_id, "manager.status_inspected", principal.display_name, "agent", employee_id,
        manager_id=manager_id, state=result["state"],
    )
    await db.commit()
    return result


@router.get("/api/v1/agents/{manager_id}/tasks/{task_id}/evidence", dependencies=READ)
async def task_evidence(
    manager_id: uuid.UUID,
    task_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Attempts, results and evidence of a task held by a direct report."""
    _as_manager(principal, manager_id)
    result = await manager_service.task_evidence(db, company_id, manager_id, task_id)
    await manager_service.audit(
        db, company_id, "manager.evidence_inspected", principal.display_name, "task", task_id,
        manager_id=manager_id,
    )
    await db.commit()
    return result


@router.get("/api/v1/agents/{manager_id}/rollup", dependencies=READ)
async def rollup(
    manager_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """The manager's direct-report roll-up, built from persisted work only."""
    _as_manager(principal, manager_id)
    result = await manager_service.rollup(db, company_id, manager_id)
    await manager_service.audit(
        db, company_id, "manager.report_generated", principal.display_name, "agent", manager_id,
        counts=result["counts"],
    )
    await db.commit()
    return result


# JSON-RPC messages to the bridge are small; anything larger is refused unread.
BRIDGE_MAX_BODY = 64 * 1024


def _rpc_error(status_code: int, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}},
    )


@router.post(manager_bridge.PATH, include_in_schema=False)
async def manager_bridge_rpc(request: Request) -> Response:
    """MCP (streamable HTTP, JSON responses) for one manager chat execution.

    Public to the auth middleware: the bearer here is the bridge's own
    execution-scoped credential, checked against the running turn on every
    request. Serves only the manager tools, through ``MCPServer`` and
    ``guarded_call``. Refusals never echo the credential.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    try:
        if scheme.lower() != "bearer" or not token:
            raise manager_bridge.BridgeDeniedError("missing bridge credential")
        ctx = await manager_bridge.authenticate(token.strip())
    except manager_bridge.BridgeDeniedError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid or expired bridge credential", "code": "BRIDGE_DENIED"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        return _rpc_error(415, -32600, "Content-Type must be application/json")
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > BRIDGE_MAX_BODY):
        return _rpc_error(413, -32600, "Request too large")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > BRIDGE_MAX_BODY:
            return _rpc_error(413, -32600, "Request too large")
    try:
        body = json.loads(raw)
    except ValueError:
        return _rpc_error(400, -32700, "Parse error")
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return _rpc_error(400, -32600, "Invalid request")
    from nexus.tools.mcp_server import MCPServer

    reply = await MCPServer(ctx, node_tools=False).handle(body)
    if reply is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(reply)
