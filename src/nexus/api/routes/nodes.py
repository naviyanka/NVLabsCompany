"""Nodes API — workflow node registry listing, search, and execution."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal
from nexus.nodes.registry import NodeRegistry, NodeCategory

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])

# Singleton registry instance
_registry = NodeRegistry()


class NodeExecuteRequest(BaseModel):
    """Parameters for executing a node."""

    params: dict[str, Any] = {}


class NodeExecuteResponse(BaseModel):
    """Result of a node execution."""

    node_id: str
    success: bool
    outputs: dict[str, Any] = {}
    error: str | None = None


@router.get("")
async def list_nodes(
    category: str | None = Query(None, description="Filter by category"),
    q: str | None = Query(None, description="Search query"),
) -> dict[str, Any]:
    """List all available workflow nodes, optionally filtered."""
    if q:
        nodes = _registry.search(q)
    elif category:
        try:
            cat = NodeCategory(category)
            nodes = _registry.list_by_category(cat)
        except ValueError:
            nodes = []
    else:
        nodes = _registry.list_all()

    return {
        "items": [n.to_dict() for n in nodes],
        "total": len(nodes),
        "categories": _registry.categories,
    }


@router.get("/categories")
async def list_categories() -> dict[str, Any]:
    """List all node categories with counts."""
    all_nodes = _registry.list_all()
    counts: dict[str, int] = {}
    for node in all_nodes:
        cat = node.category.value
        counts[cat] = counts.get(cat, 0) + 1
    return {
        "categories": [
            {"name": cat, "count": count}
            for cat, count in sorted(counts.items())
        ],
        "total_nodes": _registry.count,
    }


@router.get("/{node_id}")
async def get_node(node_id: str) -> dict[str, Any]:
    """Get a specific node definition by ID."""
    node = _registry.get(node_id)
    if not node:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    return node.to_dict()


@router.post("/{node_id}/execute", response_model=NodeExecuteResponse)
async def execute_node_endpoint(
    node_id: str,
    body: NodeExecuteRequest,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> NodeExecuteResponse:
    """Execute a workflow node with the supplied parameters.

    Only nodes with a registered executor are executable; others answer 503 so
    clients can distinguish "exists, not executable yet" from "not found".

    The node is one of the tools inbound MCP exposes, so it crosses the same
    boundary (:func:`nexus.tools.factory.guarded_call`) as the caller's
    principal, against the company's builtin connection. A refusal is 403.
    """
    from nexus.nodes.executor import DEFAULT_TIMEOUT_SECONDS, get_default_registry

    node = _registry.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    registry = get_default_registry()
    if registry.get(node_id) is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Node '{node_id}' is defined but has no executor yet",
        )

    from nexus.nodes.executor import execute_node
    from nexus.tools.access import BUILTIN_ENDPOINT
    from nexus.tools.context import ExecutionContext
    from nexus.tools.factory import guarded_call
    from nexus.tools.mcp_server import risk_level_for

    source = "node_api"
    outcome = await guarded_call(
        ExecutionContext.for_principal(principal, source=source),
        node_id,
        body.params,
        lambda: execute_node(
            node_id, body.params, registry=registry, timeout_seconds=DEFAULT_TIMEOUT_SECONDS
        ),
        source=source,
        endpoint_url=BUILTIN_ENDPOINT,
        default_risk=risk_level_for(node),
    )
    if outcome["status"] != "success":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=outcome["error"])
    result = outcome["result"]

    from nexus.governance.audit_service import record_audit

    await record_audit(
        company_id,
        f"node_execute:{node_id}",
        actor_id=str(company_id),
        resource_type="node",
        resource_id=node_id,
        details={"success": result.success, "error": result.error},
    )

    return NodeExecuteResponse(
        node_id=node_id,
        success=result.success,
        outputs=result.outputs if result.success else {},
        error=result.error,
    )
