"""MCP server - exposes selected internal tools to external MCP clients over stdio.

The mirror image of :mod:`nexus.tools.mcp_stdio`, which is the client side of the
same wire protocol: newline-delimited JSON-RPC on stdin/stdout, with
``initialize``, ``tools/list`` and ``tools/call``.

The tools exposed are the executable entries of the workflow node library, so
there is one definition of what a tool is and one code path that runs it
(:func:`nexus.nodes.executor.execute_node`). Nothing new is registered here.

Every call is authorized twice, and ``tools/list`` applies the same first check
so a client is never shown a tool it may not call:

* :class:`nexus.tools.policy_engine.ToolPolicyEngine` against the ``ToolPolicy``
  rows of the calling key's company -- this is also the per-company scoping.
* :func:`nexus.tools.factory.guard_tool_call`, the same guardrail screen the
  adapter tool loops use.

The caller authenticates with a company-scoped API key in ``NEXUS_API_KEY``;
the key's company decides which policies apply. There is no unauthenticated
mode: without a resolvable key the server refuses to start.

Run it as::

    NEXUS_API_KEY=nv_... python -m nexus.tools.mcp_server
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from typing import Any

from nexus.nodes.executor import execute_node, get_default_registry
from nexus.nodes.registry import NodeCategory, NodeDefinition, NodeRegistry
from nexus.tools.factory import guard_tool_call
from nexus.tools.policy_engine import PolicyRule, ToolPolicyEngine

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "nexus"

# JSON-RPC error codes we return (spec-defined values).
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603

# A node in one of these categories reaches something outside this process --
# sending a message, writing a row, issuing a request -- so it is a "write" for
# policy purposes. Everything else (parsing, summarizing) is a "read".
# ponytail: per-category, so a genuine reader like db-redis-get is called a
# write and needs an explicit policy. Errs closed; move to a per-node risk
# field on NodeDefinition if that coarseness starts costing real access.
_WRITE_CATEGORIES = frozenset(
    {
        NodeCategory.COMMUNICATION,
        NodeCategory.DATABASE,
        NodeCategory.DEVOPS,
        NodeCategory.EMAIL,
        NodeCategory.HTTP,
        NodeCategory.IOT,
        NodeCategory.MESSAGING,
        NodeCategory.SOCIAL,
        NodeCategory.STORAGE,
    }
)


def risk_level_for(node: NodeDefinition) -> str:
    """Classify a node as ``read`` or ``write`` for policy evaluation."""
    return "write" if node.category in _WRITE_CATEGORIES else "read"


def exposed_nodes() -> dict[str, NodeDefinition]:
    """The node definitions that have an executor bound, keyed by node id.

    A browse-only node has no executor, so exposing it would advertise a tool
    that cannot run.
    """
    catalog = NodeRegistry()
    nodes = {}
    for node_id in get_default_registry().executable_node_ids:
        node = catalog.get(node_id)
        if node is not None:
            nodes[node_id] = node
    return nodes


def input_schema_for(node: NodeDefinition) -> dict[str, Any]:
    """Build a JSON Schema for a node's inputs, as MCP's ``inputSchema``."""
    type_map = {
        "string": "string",
        "number": "number",
        "boolean": "boolean",
        "json": "object",
        "file": "string",
        "credential": "string",
    }
    properties = {
        i.name: {
            "type": type_map.get(i.type, "string"),
            "description": i.description,
        }
        for i in node.inputs
    }
    return {
        "type": "object",
        "properties": properties,
        "required": [i.name for i in node.inputs if i.required],
    }


async def load_policy_engine(company_id: uuid.UUID) -> ToolPolicyEngine:
    """Load one company's active tool policies into an engine.

    The default effect is ``deny``: this is an external surface, so a tool is
    exposed only where a policy says so. :func:`default_read_policy` supplies
    the read-only baseline when a company has written no policies of its own.
    """
    from sqlmodel import select

    from nexus.database import async_session_factory
    from nexus.models.tool import ToolPolicy

    engine = ToolPolicyEngine(default_effect="deny")

    async with async_session_factory() as db:
        stmt = select(ToolPolicy).where(
            ToolPolicy.company_id == company_id,
            ToolPolicy.is_active == True,  # noqa: E712
        )
        rows = list((await db.execute(stmt)).scalars().all())

    rules = [
        PolicyRule(
            id=row.id,
            company_id=row.company_id,
            name=row.name,
            priority=row.priority,
            effect=row.effect,
            conditions=row.conditions or {},
            is_active=row.is_active,
        )
        for row in rows
    ]
    engine.load_policies(rules or [default_read_policy(company_id)])
    return engine


def default_read_policy(company_id: uuid.UUID) -> PolicyRule:
    """The baseline for a company with no tool policies: read-risk tools only.

    Write-risk tools stay denied until someone writes a policy allowing them,
    so turning the server on cannot by itself hand an external client the
    ability to send mail or write rows.
    """
    return PolicyRule(
        company_id=company_id,
        name="default: read-only tools",
        priority=1000,
        effect="allow",
        conditions={"risk_level": ["read"]},
    )


class MCPServer:
    """Serves the exposed node tools over one stdio session."""

    def __init__(
        self,
        company_id: uuid.UUID,
        principal_id: uuid.UUID,
        policy_engine: ToolPolicyEngine,
    ) -> None:
        """Bind the server to one company and its policies.

        Args:
            company_id: Company the calling key belongs to; scopes every call.
            principal_id: Stable id for the caller, so ``agent_id`` policy
                conditions can name it.
            policy_engine: Engine preloaded with that company's policies.
        """
        self._company_id = company_id
        self._principal_id = principal_id
        self._policies = policy_engine
        self._nodes = exposed_nodes()

    def _allowed(self, node: NodeDefinition) -> tuple[bool, str]:
        """Whether policy permits this node, and the reason either way."""
        decision = self._policies.evaluate(
            agent_id=self._principal_id,
            tool_name=node.id,
            risk_level=risk_level_for(node),
            context={"company_id": str(self._company_id)},
        )
        return decision.allowed, decision.reason

    def list_tools(self) -> list[dict[str, Any]]:
        """The tools this company's policies allow, in MCP ``tools/list`` shape."""
        return [
            {
                "name": node.id,
                "description": node.description,
                "inputSchema": input_schema_for(node),
            }
            for node in self._nodes.values()
            if self._allowed(node)[0]
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Authorize and run one tool call, in MCP ``tools/call`` result shape.

        A refusal comes back as an ``isError`` result rather than a JSON-RPC
        error: the client asked a well-formed question and deserves to see why
        the answer is no.
        """
        node = self._nodes.get(name)
        if node is None:
            return _tool_error(f"Unknown tool '{name}'")

        allowed, reason = self._allowed(node)
        if not allowed:
            logger.warning("Policy denied tool %s: %s", name, reason)
            return _tool_error(f"Denied by policy: {reason}")

        blocked = await guard_tool_call(name, arguments)
        if blocked is not None:
            return _tool_error(blocked["error"])

        result = await execute_node(name, arguments)
        if not result.success:
            return _tool_error(result.error or "Execution failed")

        return {
            "content": [{"type": "text", "text": json.dumps(result.outputs, default=str)}],
            "isError": False,
        }

    async def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch one JSON-RPC request, or None for a notification.

        A notification (no ``id``) gets no response, per JSON-RPC.
        """
        method = request.get("method", "")
        request_id = request.get("id")

        if request_id is None:
            return None

        if method == "initialize":
            return _result(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
                },
            )

        if method == "tools/list":
            return _result(request_id, {"tools": self.list_tools()})

        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            if not isinstance(name, str) or not name:
                return _error(request_id, _INVALID_PARAMS, "Missing tool name")
            # Not `or {}`: an empty list is falsy, and coercing it to {} would
            # accept a wrongly-typed argument set instead of rejecting it.
            arguments = params.get("arguments")
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                return _error(request_id, _INVALID_PARAMS, "arguments must be an object")
            try:
                return _result(request_id, await self.call_tool(name, arguments))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Tool %s raised", name)
                return _error(request_id, _INTERNAL_ERROR, str(exc))

        if method == "ping":
            return _result(request_id, {})

        return _error(request_id, _METHOD_NOT_FOUND, f"Unknown method '{method}'")


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Wrap a successful result as a JSON-RPC response."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    """Wrap a failure as a JSON-RPC error response."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_error(message: str) -> dict[str, Any]:
    """A tools/call result that reports failure to the model."""
    return {"content": [{"type": "text", "text": message}], "isError": True}


async def authenticate(credential: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Resolve an API key to the company it scopes and a stable principal id.

    Raises:
        RuntimeError: If the key is unknown, revoked or expired.
    """
    from nexus.auth.api_keys import resolve_api_key, touch_api_key
    from nexus.database import async_session_factory

    async with async_session_factory() as db:
        key = await resolve_api_key(db, credential)
        if key is None:
            raise RuntimeError("NEXUS_API_KEY is not a valid, active API key")
        await touch_api_key(db, key.id)
        await db.commit()
        return key.company_id, uuid.uuid5(uuid.NAMESPACE_URL, f"apikey:{key.id}")


class StdinReader:
    """Awaitable ``readline`` over real stdin, on every platform.

    ``loop.connect_read_pipe`` cannot take stdin on the Windows event loops, so
    the read goes to a worker thread instead. One blocking readline at a time is
    all a stdio session needs, and it keeps the loop free to run the tool.
    """

    async def readline(self) -> bytes:
        """Read one line from stdin, or b"" at EOF."""
        return await asyncio.to_thread(sys.stdin.buffer.readline)


async def serve(server: MCPServer, reader: Any, writer: Any) -> None:
    """Read newline-delimited JSON-RPC from ``reader`` until EOF, writing replies.

    A malformed line is skipped rather than fatal: one bad frame from a client
    should not take down a session that is otherwise healthy.
    """
    while True:
        line = await reader.readline()
        if not line:
            return

        raw = line.decode().strip()
        if not raw:
            continue

        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed JSON-RPC line")
            continue

        if not isinstance(request, dict):
            continue

        response = await server.handle(request)
        if response is None:
            continue

        writer.write(json.dumps(response) + "\n")
        writer.flush()


async def main() -> int:
    """Entry point: authenticate, load policies, then serve stdio until EOF."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    credential = os.environ.get("NEXUS_API_KEY", "")
    if not credential:
        print("NEXUS_API_KEY is required", file=sys.stderr)
        return 1

    try:
        company_id, principal_id = await authenticate(credential)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    server = MCPServer(company_id, principal_id, await load_policy_engine(company_id))
    await serve(server, StdinReader(), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
