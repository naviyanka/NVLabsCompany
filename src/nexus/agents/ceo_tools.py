"""CEO Agent Tools — direct API access for the Navi CEO agent.

These tools allow the CEO agent to query its own platform's API endpoints
using a service account API key. This gives Navi real-time access to all
platform data without bypassing auth or using internal DB queries.

The API key is stored in the config and used for Bearer auth on every call.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default API base (same host, the CEO talks to itself)
DEFAULT_API_BASE = "http://localhost:8000"


class CeoApiClient:
    """HTTP client the CEO uses to query its own platform."""

    def __init__(self, api_key: str, api_base: str = DEFAULT_API_BASE) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def get(self, path: str) -> dict[str, Any] | list[Any]:
        """GET an API endpoint."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{self.api_base}{path}", headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST to an API endpoint."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{self.api_base}{path}", headers=self.headers, json=body or {})
            r.raise_for_status()
            return r.json()


async def ceo_query_api(
    api_key: str,
    endpoint: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    api_base: str = DEFAULT_API_BASE,
) -> dict[str, Any]:
    """Execute an API call on behalf of the CEO agent.

    Args:
        api_key: The service account API key (nv_...).
        endpoint: The API path (e.g. /api/v1/companies/{id}/agents).
        method: HTTP method (GET or POST).
        body: Optional JSON body for POST requests.
        api_base: Base URL of the NEXUS API.

    Returns:
        The JSON response from the API.
    """
    client = CeoApiClient(api_key, api_base)
    try:
        if method.upper() == "POST":
            result = await client.post(endpoint, body)
        else:
            result = await client.get(endpoint)
        return {"success": True, "data": result}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Pre-built tool functions the CEO can call
COMPANY_ID = "00000000-0000-4000-8000-000000000001"


async def list_agents(api_key: str) -> str:
    """List all agents in the company."""
    result = await ceo_query_api(api_key, f"/api/v1/companies/{COMPANY_ID}/agents")
    if not result["success"]:
        return f"Error: {result['error']}"
    agents = result["data"]
    if not agents:
        return "No agents found."
    lines = [f"Total agents: {len(agents)}"]
    for a in agents:
        lines.append(f"- {a['name']} [{a['role']}] adapter={a['adapter_type']} model={a.get('model','')} status={a['status']}")
    return "\n".join(lines)


async def list_tasks(api_key: str) -> str:
    """List all tasks with their status."""
    result = await ceo_query_api(api_key, f"/api/v1/companies/{COMPANY_ID}/tasks")
    if not result["success"]:
        return f"Error: {result['error']}"
    tasks = result["data"] if isinstance(result["data"], list) else result["data"].get("items", [])
    if not tasks:
        return "No tasks found."
    lines = [f"Total tasks: {len(tasks)}"]
    for t in tasks[:20]:
        lines.append(f"- [{t.get('status','?')}] {t.get('title','Untitled')} (assigned: {t.get('assignee_id','unassigned')})")
    return "\n".join(lines)


async def list_goals(api_key: str) -> str:
    """List strategic goals."""
    result = await ceo_query_api(api_key, f"/api/v1/companies/{COMPANY_ID}/goals")
    if not result["success"]:
        return f"Error: {result['error']}"
    goals = result["data"] if isinstance(result["data"], list) else result["data"].get("items", [])
    if not goals:
        return "No goals found."
    lines = [f"Total goals: {len(goals)}"]
    for g in goals:
        lines.append(f"- [{g.get('status','?')}] {g.get('title','Untitled')}")
    return "\n".join(lines)


async def get_dashboard(api_key: str) -> str:
    """Get dashboard overview stats."""
    result = await ceo_query_api(api_key, f"/api/v1/companies/{COMPANY_ID}/dashboard/stats")
    if not result["success"]:
        return f"Error: {result['error']}"
    d = result["data"]
    return (
        f"Dashboard Stats:\n"
        f"- Agents: {d.get('agents_count', '?')}\n"
        f"- Tasks: {d.get('tasks_count', '?')}\n"
        f"- Pipelines: {d.get('pipelines_count', '?')}\n"
        f"- Active goals: {d.get('goals_active', '?')}"
    )


async def get_budget(api_key: str) -> str:
    """Get budget status."""
    result = await ceo_query_api(api_key, f"/api/v1/companies/{COMPANY_ID}/budgets")
    if not result["success"]:
        return f"Error: {result['error']}"
    return f"Budget data: {result['data']}"


async def query_any_endpoint(api_key: str, endpoint: str, method: str = "GET") -> str:
    """Query any API endpoint directly."""
    result = await ceo_query_api(api_key, endpoint, method)
    if not result["success"]:
        return f"Error: {result['error']}"
    import json
    data = result["data"]
    if isinstance(data, list):
        return f"Results ({len(data)} items):\n{json.dumps(data[:10], indent=2, default=str)}"
    return json.dumps(data, indent=2, default=str)
