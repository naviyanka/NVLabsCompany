"""Nodes API — workflow node registry listing and search."""

from typing import Any

from fastapi import APIRouter, Query

from nexus.nodes.registry import NodeRegistry, NodeCategory

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])

# Singleton registry instance
_registry = NodeRegistry()


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
