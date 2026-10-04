"""MCP server - exposes selected internal tools to external MCP clients over stdio.

The mirror image of :mod:`nexus.tools.mcp_stdio`, which is the client side of the
same wire protocol: newline-delimited JSON-RPC on stdin/stdout, with
``initialize``, ``tools/list`` and ``tools/call``.

The tools exposed are the executable entries of the workflow node library, so
there is one definition of what a tool is and one code path that runs it
(:func:`nexus.nodes.executor.execute_node`). The one addition is the manager
tools (:mod:`nexus.tools.manager_tools`), offered only to an agent that has
direct reports and scoped to them.

Every call crosses the same boundary as an adapter's outbound tool call,
:func:`nexus.tools.factory.guarded_call`: identity, MCP binding, RBAC,
ToolPolicy/ToolProfile, autonomy, guardrails, then execution and the
``tool_invocations``/audit record. The tools are governed as the company's
``nexus_builtin`` ToolConnection (:data:`nexus.tools.access.BUILTIN_ENDPOINT`),
so bindings and the catalog apply to them like to any other connection. The
policy default is deny: without a policy of its own a company exposes only
read-risk tools. ``tools/list`` hides only the tools that call would deny
outright.

Identity comes from the credential, never from a request:

* ``NEXUS_RUN_TOKEN`` (preferred): a run JWT. Company and agent are the
  token's, the role is ``agent``.
* ``NEXUS_API_KEY``: a company API key. Company and role are the key's; there
  is no agent, so under enforcement the calls are refused.

``NEXUS_SESSION_ID`` optionally names the agent session; it is a claim that
access control checks against the agent and company. There is no
unauthenticated mode: without a valid credential the server refuses to start.

Run it as::

    NEXUS_RUN_TOKEN=... python -m nexus.tools.mcp_server
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
from nexus.tools import manager_tools
from nexus.tools.access import BUILTIN_ENDPOINT, DENIED, check_tool_access
from nexus.tools.ceo_tools import CEO_TOOLS
from nexus.tools.context import INBOUND_MCP, ExecutionContext
from nexus.tools.effects import (
    BridgeSlotError,
    EffectClass,
    EffectKeyError,
    EffectNotStarted,
    ToolSlot,
    reserve_bridge_slot,
    resolve_effect,
)
from nexus.tools.factory import _access_session, guarded_call

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


# What a rerun of an interrupted call does, declared per exposed node (never derived from the
# name or the category above). A node missing here runs as a non-idempotent write, and a test
# fails when an executable node has no entry.
NODE_EFFECTS: dict[str, EffectClass] = {
    "ai-chat": EffectClass.READ_ONLY,
    "ai-sentiment": EffectClass.READ_ONLY,
    "ai-summarize": EffectClass.READ_ONLY,
    "ai-translate": EffectClass.READ_ONLY,
    "db-redis-get": EffectClass.READ_ONLY,
    # Not idempotent: with a relative ``ttl`` a retry restarts the clock and so extends the key's
    # life, and a SET with no ttl is not provably the same state if another writer ran between.
    "db-redis-set": EffectClass.NON_IDEMPOTENT_WRITE,
    "db-sqlite-query": EffectClass.NON_IDEMPOTENT_WRITE,
    "file-csv-parse": EffectClass.READ_ONLY,
    "file-json-parse": EffectClass.READ_ONLY,
    "http-request": EffectClass.NON_IDEMPOTENT_WRITE,
    "msg-discord-send": EffectClass.NON_IDEMPOTENT_WRITE,
    "msg-slack-send": EffectClass.NON_IDEMPOTENT_WRITE,
    "msg-telegram-send": EffectClass.NON_IDEMPOTENT_WRITE,
    "msg-webhook-notify": EffectClass.NON_IDEMPOTENT_WRITE,
}


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


class MCPServer:
    """Serves the exposed node tools over one stdio session."""

    def __init__(
        self,
        ctx: ExecutionContext,
        *,
        node_tools: bool = True,
        idempotency_key: str | None = None,
    ) -> None:
        """Bind the server to one authenticated caller.

        Args:
            ctx: Built from the credential by :func:`authenticate`; scopes
                every call to its company, principal, role and agent.
            node_tools: False serves only the manager tools (the manager
                bridge, :mod:`nexus.tools.manager_bridge`).
            idempotency_key: The bridge request's ``Idempotency-Key``. A write that arrives
                without a caller-supplied slot is identified by it (see ``_slot_for``).
        """
        self._ctx = ctx
        self._nodes = exposed_nodes() if node_tools else {}
        self._idempotency_key = idempotency_key

    async def _slot_for(
        self, effect: Any, slot: ToolSlot | None, name: str, arguments: dict[str, Any]
    ) -> ToolSlot | None:
        """The caller's slot, or the durable slot this request's key maps to.

        A read-only call needs none. A write with no slot is identified by the request's
        idempotency key through a durable record (:func:`reserve_bridge_slot`), never by this
        object: the bridge builds a new server per request, so nothing held here survives
        a retry. A call with no turn is not ledgered and gets none.

        Raises:
            BridgeSlotError: The write has no usable key, or the key names another call.
        """
        if (
            slot is not None
            or resolve_effect(effect) is EffectClass.READ_ONLY
            or self._ctx.turn_id is None
        ):
            return slot
        return await reserve_bridge_slot(
            self._ctx.company_id, self._ctx.turn_id, self._idempotency_key, name, arguments
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        """The tools this caller may be offered, in MCP ``tools/list`` shape."""
        tools = []
        async with _access_session(self._ctx.company_id) as db:
            for node in self._nodes.values():
                decision = await check_tool_access(
                    db,
                    self._ctx,
                    tool_name=node.id,
                    endpoint_url=BUILTIN_ENDPOINT,
                    default_risk=risk_level_for(node),
                )
                if decision.outcome != DENIED:
                    tools.append(
                        {
                            "name": node.id,
                            "description": node.description,
                            "inputSchema": input_schema_for(node),
                        }
                    )
            # Manager and CEO tools: only the agent's catalog (manager_tools.catalog).
            for name, tool in (await manager_tools.catalog(self._ctx)).items():
                decision = await check_tool_access(
                    db, self._ctx, tool_name=name, default_risk=tool.risk
                )
                if decision.outcome != DENIED:
                    tools.append(
                        {
                            "name": name,
                            "description": tool.description,
                            "inputSchema": manager_tools.input_schema(tool),
                        }
                    )
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any], slot: ToolSlot | None = None
    ) -> dict[str, Any]:
        """Authorize and run one tool call, in MCP ``tools/call`` result shape.

        A refusal comes back as an ``isError`` result rather than a JSON-RPC
        error: the client asked a well-formed question and deserves to see why
        the answer is no.

        ``slot`` is the call's durable position in the turn (model round and position in
        that round) when the caller has one; otherwise a write is identified by the request's
        idempotency key, and refused before dispatch when there is none.
        """
        if name in manager_tools.MANAGER_TOOLS or name in CEO_TOOLS:
            return await self._call_manager_tool(name, arguments, slot)
        node = self._nodes.get(name)
        if node is None:
            return _tool_error(f"Unknown tool '{name}'")
        try:
            slot = await self._slot_for(NODE_EFFECTS.get(name), slot, name, arguments)
        except (BridgeSlotError, EffectKeyError) as exc:
            return _tool_error(str(exc))
        except Exception as exc:  # noqa: BLE001 - no durable identity, no write: fail closed
            logger.error("Bridge slot unavailable for %s: %s", name, exc)
            return _tool_error("effect_ledger_unavailable: the write was not run")

        outcome = await guarded_call(
            self._ctx,
            name,
            arguments,
            lambda: execute_node(name, arguments),
            source=INBOUND_MCP,
            endpoint_url=BUILTIN_ENDPOINT,
            default_risk=risk_level_for(node),
            effect=NODE_EFFECTS.get(name),
            slot=slot,
        )
        if outcome["status"] != "success":
            logger.warning("Refused tool %s: %s", name, outcome["error"])
            return _tool_error(outcome["error"])

        result = outcome["result"]
        if not result.success:
            return _tool_error(result.error or "Execution failed")

        return {
            "content": [{"type": "text", "text": json.dumps(result.outputs, default=str)}],
            "isError": False,
        }

    async def _call_manager_tool(
        self, name: str, arguments: dict[str, Any], slot: ToolSlot | None = None
    ) -> dict[str, Any]:
        """Run a manager or CEO tool through the same guarded boundary as a node tool.

        The access policy is checked (and audited) first; then only a tool of
        the agent's current catalog runs: a tool it is not offered (not, or no
        longer, a manager or the CEO) is refused.
        """
        from fastapi import HTTPException

        async def run() -> Any:
            if name not in await manager_tools.catalog(self._ctx):
                # Proven pre-effect: the catalog check runs before anything is dispatched.
                raise EffectNotStarted(f"TOOL_NOT_OFFERED: '{name}' is not available to this agent")
            return await manager_tools.call(self._ctx, name, arguments)

        tool = {**manager_tools.MANAGER_TOOLS, **CEO_TOOLS}[name]
        try:
            slot = await self._slot_for(tool.effect, slot, name, arguments)
        except (BridgeSlotError, EffectKeyError) as exc:
            return _tool_error(str(exc))
        except Exception as exc:  # noqa: BLE001 - no durable identity, no write: fail closed
            logger.error("Bridge slot unavailable for %s: %s", name, exc)
            return _tool_error("effect_ledger_unavailable: the write was not run")
        try:
            outcome = await guarded_call(
                self._ctx,
                name,
                arguments,
                run,
                source=INBOUND_MCP,
                default_risk=tool.risk,
                effect=tool.effect,
                slot=slot,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}
            return _tool_error(f"{detail.get('code', exc.status_code)}: {detail.get('message')}")
        except ValueError as exc:
            return _tool_error(str(exc))
        if outcome["status"] != "success":
            logger.warning("Refused tool %s: %s", name, outcome["error"])
            return _tool_error(outcome["error"])
        return {
            "content": [{"type": "text", "text": json.dumps(outcome["result"], default=str)}],
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
            return _result(request_id, {"tools": await self.list_tools()})

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


async def authenticate(
    *,
    run_token: str = "",
    api_key: str = "",
    session_id: str = "",
) -> ExecutionContext:
    """Resolve the process credential to the server-side execution context.

    The run token wins when both are set. Its role is fixed at ``agent``, as
    in the HTTP middleware: a credential never names its own role.

    Raises:
        RuntimeError: If no credential is given, or it does not verify.
    """
    from nexus.auth.principal import Principal

    if run_token:
        from nexus.auth.run_tokens import RunTokenError, verify_run_token

        try:
            run_id, agent_id, company_id = verify_run_token(run_token)
        except RunTokenError as exc:
            raise RuntimeError(f"NEXUS_RUN_TOKEN is not valid: {exc}") from exc
        principal = Principal(
            kind="run", company_id=company_id, role="agent", run_id=run_id, agent_id=agent_id
        )
    elif api_key:
        from nexus.auth.api_keys import resolve_api_key, touch_api_key
        from nexus.database import async_session_factory
        from nexus.models.auth import normalize_role

        async with async_session_factory() as db:
            key = await resolve_api_key(db, api_key)
            if key is None:
                raise RuntimeError("NEXUS_API_KEY is not a valid, active API key")
            await touch_api_key(db, key.id)
            await db.commit()
        principal = Principal(
            kind="service",
            company_id=key.company_id,
            role=normalize_role(key.role),
            api_key_id=key.id,
        )
    else:
        raise RuntimeError("NEXUS_RUN_TOKEN or NEXUS_API_KEY is required")

    try:
        session = uuid.UUID(session_id) if session_id else None
    except ValueError as exc:
        raise RuntimeError("NEXUS_SESSION_ID is not a UUID") from exc
    return ExecutionContext.for_principal(principal, source=INBOUND_MCP, session_id=session)


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
    """Entry point: authenticate, then serve stdio until EOF."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    try:
        ctx = await authenticate(
            run_token=os.environ.get("NEXUS_RUN_TOKEN", ""),
            api_key=os.environ.get("NEXUS_API_KEY", ""),
            session_id=os.environ.get("NEXUS_SESSION_ID", ""),
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    server = MCPServer(ctx)
    await serve(server, StdinReader(), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
