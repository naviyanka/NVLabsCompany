"""Provider-neutral governed streaming tool loop.

Shared by the Hermes-native and Azure OpenAI adapters. The model only produces
structured ``tool_calls``; this loop validates a whole response, then runs each
call through ``MCPServer.call_tool`` (catalog, ``guarded_call``, ``ToolPolicy``)
under the durable turn's identity (``manager_bridge.bind``). Nothing is parsed
from free text and there is no fallback provider.

A provider supplies a *transport*: an async iterator of OpenAI-style streamed
chat-completion chunks. It supplies an optional *meter* (budget reserve and
settle around every round) and an optional *callback* for :class:`Event`.

Callback contract: events carry no channel or audio concepts and never tool
arguments. Text deltas have two modes. A tool-free call (no tools offered) emits
each delta as it arrives, because nothing can invalidate it. A tool-capable round
holds its text, which a later native ``tool_call`` would discard, and releases it
only when the round ends with no tool call; that release is buffered, not token
streaming. A callback that raises is dropped; it never skips cancellation, budget
settlement or audit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio

logger = logging.getLogger(__name__)

# Text that looks like a tool call is never executed; a response carrying it fails.
TOOL_TEXT = re.compile(r"<\s*/?\s*tool_call|<\s*function_call|\"tool_calls\"\s*:", re.IGNORECASE)
# Progressive release re-checks this many trailing characters so a marker split across
# deltas is caught before the completing delta is released; the whole text is still
# checked when the round ends.
TOOL_TEXT_TAIL = 64

TEXT_DELTA = "text_delta"
TOOL_REQUESTED = "tool_requested"
TOOL_RUNNING = "tool_running"
TOOL_COMPLETED = "tool_completed"
USAGE_UPDATE = "usage_update"
COMPLETED = "completed"
CANCELLED = "cancelled"
ERROR = "error"


class ProviderError(Exception):
    """A turn that must fail; the message carries a stable code and no secret."""


@dataclass(frozen=True)
class Event:
    """One step of a governed turn. ``error`` is a stable code, never provider text."""

    type: str
    round: int = 0
    text: str = ""
    tool_call_id: str = ""
    name: str = ""
    is_error: bool = False
    usage: dict[str, int] | None = None
    error: str = ""


@dataclass(frozen=True)
class Limits:
    """Per-provider bounds and error-code prefix (e.g. ``HERMES_NATIVE``)."""

    code: str
    max_iterations: int = 8
    max_calls: int = 16
    max_calls_per_response: int = 4
    max_argument_bytes: int = 64_000
    max_tool_result_chars: int = 32_000


class Meter(Protocol):
    """Budget accounting for one outbound round."""

    async def begin(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        """Reserve before any outbound work; raises to refuse the round."""

    async def end(
        self, hold: Any, usage: dict[str, Any] | None, started: bool, output_chars: int
    ) -> None:
        """Settle or release the hold. Always called, even on cancel, timeout or error."""


Transport = Callable[[list[dict[str, Any]], list[dict[str, Any]]], AsyncIterator[dict[str, Any]]]


class Assembler:
    """One streamed completion: content plus tool calls assembled by delta index."""

    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self.content: list[str] = []
        self.calls: dict[int, dict[str, str]] = {}
        self.finish: str | None = None
        self.usage: dict[str, Any] = {}

    def feed(self, chunk: dict[str, Any]) -> None:
        code = self.limits.code
        self.usage = chunk.get("usage") or self.usage
        for choice in chunk.get("choices") or []:
            if choice.get("index", 0) != 0:
                raise ProviderError(f"{code}_BAD_RESPONSE: multiple choices")
            delta = choice.get("delta") or {}
            if delta.get("content"):
                self.content.append(delta["content"])
            for part in delta.get("tool_calls") or []:
                slot = self.calls.setdefault(
                    int(part.get("index", 0)), {"id": "", "name": "", "arguments": ""}
                )
                fn = part.get("function") or {}
                slot["id"] += part.get("id") or ""
                slot["name"] += fn.get("name") or ""
                slot["arguments"] += fn.get("arguments") or ""
                if len(slot["arguments"]) > self.limits.max_argument_bytes:
                    raise ProviderError(f"{code}_LIMIT: tool arguments too large")
            self.finish = choice.get("finish_reason") or self.finish

    def tool_calls(self) -> list[dict[str, Any]]:
        """Complete, validated calls in order; anything malformed fails the turn."""
        code = self.limits.code
        out = []
        for index in sorted(self.calls):
            slot = self.calls[index]
            if not slot["id"] or not slot["name"]:
                raise ProviderError(f"{code}_BAD_TOOL_CALL: incomplete call")
            try:
                args = json.loads(slot["arguments"] or "{}")
            except ValueError:
                raise ProviderError(f"{code}_BAD_TOOL_CALL: arguments are not JSON") from None
            if not isinstance(args, dict):
                raise ProviderError(f"{code}_BAD_TOOL_CALL: arguments are not an object")
            out.append({"id": slot["id"], "name": slot["name"], "arguments": args})
        if out and self.finish != "tool_calls":
            raise ProviderError(f"{code}_BAD_TOOL_CALL: call in an unfinished response")
        return out


async def sse_chunks(
    lines: AsyncIterator[str], code: str, max_bytes: int
) -> AsyncIterator[dict[str, Any]]:
    """Parse ``data:`` lines of a server-sent-event stream into JSON chunks."""
    size = 0
    async for line in lines:
        size += len(line)
        if size > max_bytes:
            raise ProviderError(f"{code}_LIMIT: response too large")
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except ValueError:
            raise ProviderError(f"{code}_BAD_RESPONSE: not JSON") from None


@dataclass
class LoopResult:
    text: str
    artifacts: list[dict[str, Any]]
    usage: dict[str, int]
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Prepared:
    ctx: Any
    server: Any
    offered: list[dict[str, Any]]


async def prepare(base: Any, task_id: uuid.UUID, code: str) -> Prepared:
    """Bind the turn's identity and build the server-side tool catalog for it."""
    from nexus.tools import manager_bridge
    from nexus.tools.mcp_server import MCPServer

    if base is None:
        raise ProviderError(f"{code}_NO_CONTEXT: no server-built execution context")
    # The turn's own identity, as for the MCP bridge: run principal, turn and session.
    try:
        ctx = await manager_bridge.bind(base.company_id, base.agent_id, task_id)
    except manager_bridge.BridgeDeniedError:
        raise ProviderError(f"{code}_CANCELLED: turn is not live") from None
    server = MCPServer(ctx, node_tools=False)
    return Prepared(ctx, server, await server.list_tools())


def tool_schemas(offered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            },
        }
        for t in offered
    ]


class _Emitter:
    """Calls the callback; a failing callback is dropped, never fatal."""

    def __init__(self, callback: Callable[[Event], None] | None) -> None:
        self.callback = callback

    def __call__(self, event: Event) -> None:
        if self.callback is None:
            return
        try:
            self.callback(event)
        except Exception:  # noqa: BLE001 -- a consumer must not break the governed turn
            logger.warning("governed-loop callback failed; dropping it", exc_info=True)
            self.callback = None


def _stable(error: str) -> str:
    return error.split(":", 1)[0]


async def run(
    prepared: Prepared,
    task_id: uuid.UUID,
    messages: list[dict[str, Any]],
    transport: Transport,
    limits: Limits,
    *,
    meter: Meter | None = None,
    on_event: Callable[[Event], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    on_tool_verified: Callable[[], None] | None = None,
) -> LoopResult:
    """Drive rounds until the model answers without tool calls."""
    emit = _Emitter(on_event)
    try:
        result = await _loop(
            prepared, task_id, messages, transport, limits, meter, emit, cancelled, on_tool_verified
        )
    except asyncio.CancelledError:
        emit(Event(CANCELLED))
        raise
    except ProviderError as exc:
        code = _stable(str(exc))
        emit(Event(CANCELLED if code.endswith("_CANCELLED") else ERROR, error=code))
        raise
    emit(Event(COMPLETED, usage=result.usage))
    return result


async def _loop(
    prepared: Prepared,
    task_id: uuid.UUID,
    messages: list[dict[str, Any]],
    transport: Transport,
    limits: Limits,
    meter: Meter | None,
    emit: _Emitter,
    cancelled: Callable[[], bool] | None,
    on_tool_verified: Callable[[], None] | None,
) -> LoopResult:
    from nexus.tools import manager_bridge
    from nexus.tools.effects import ToolSlot

    code = limits.code
    ctx, server = prepared.ctx, prepared.server
    names = {t["name"] for t in prepared.offered}
    tools = tool_schemas(prepared.offered)
    seen: set[str] = set()
    artifacts: list[dict[str, Any]] = []
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

    def check_cancel() -> None:
        if cancelled is not None and cancelled():
            raise ProviderError(f"{code}_CANCELLED: turn ended")

    # Tool-free call: no tool can follow, so text is final the moment it arrives and is
    # released progressively. Tool-capable round: text is provisional (a later native
    # tool_call discards it), so it is held until the round ends.
    progressive = not tools

    for round_no in range(limits.max_iterations):
        check_cancel()
        got = Assembler(limits)
        hold = await meter.begin(messages, tools) if meter else None
        started = False
        sent, tail = 0, ""
        try:
            async with aclosing(transport(messages, tools)) as stream:
                async for chunk in stream:
                    started = True
                    check_cancel()
                    got.feed(chunk)
                    if progressive:
                        for piece in got.content[sent:]:
                            # Tool-looking text still fails the turn, before it is released.
                            if TOOL_TEXT.search(tail + piece):
                                raise ProviderError(f"{code}_TOOL_TEXT: tool call in message text")
                            tail = (tail + piece)[-TOOL_TEXT_TAIL:]
                            emit(Event(TEXT_DELTA, round=round_no, text=piece))
                        sent = len(got.content)
        finally:
            if meter:
                text_len = sum(map(len, got.content)) + sum(
                    len(c["name"]) + len(c["arguments"]) for c in got.calls.values()
                )
                with anyio.CancelScope(shield=True):
                    await meter.end(hold, got.usage or None, started, text_len)
        for k in usage:
            usage[k] += int(got.usage.get(k) or 0)
        emit(Event(USAGE_UPDATE, round=round_no, usage=dict(usage)))
        text = "".join(got.content)
        calls = got.tool_calls()
        if TOOL_TEXT.search(text):
            raise ProviderError(f"{code}_TOOL_TEXT: tool call in message text")
        if not calls:
            check_cancel()
            if not progressive:  # a tool-capable round proved final only now
                for piece in got.content:
                    emit(Event(TEXT_DELTA, round=round_no, text=piece))
            messages.append({"role": "assistant", "content": text})
            return LoopResult(text, artifacts, usage, messages)
        # Native tool calls: this round's text is not an answer and is never emitted.
        if not tools or len(calls) > limits.max_calls_per_response:
            raise ProviderError(f"{code}_BAD_TOOL_CALL: tool calls not allowed here")
        messages.append(
            {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
                    }
                    for c in calls
                ],
            }
        )
        ids = [c["id"] for c in calls]
        if len(set(ids)) != len(ids) or seen & set(ids):
            raise ProviderError(f"{code}_BAD_TOOL_CALL: duplicate call id")
        if any(c["name"] not in names for c in calls):
            raise ProviderError(f"{code}_BAD_TOOL_CALL: tool not offered")
        if len(seen) + len(calls) > limits.max_calls:
            raise ProviderError(f"{code}_LIMIT: too many tool calls")
        seen.update(ids)
        for call in calls:
            emit(Event(TOOL_REQUESTED, round=round_no, tool_call_id=call["id"], name=call["name"]))
        for position, call in enumerate(calls):
            check_cancel()
            # The turn must still be this execution's, live and uncancelled.
            try:
                await manager_bridge.bind(ctx.company_id, ctx.agent_id, task_id)
            except manager_bridge.BridgeDeniedError:
                raise ProviderError(f"{code}_CANCELLED: turn ended") from None
            emit(Event(TOOL_RUNNING, round=round_no, tool_call_id=call["id"], name=call["name"]))
            # The ledger identity is the call's place in the turn (this round, this position
            # in the provider's order), never the provider's call id, which a rerun regenerates.
            result = await server.call_tool(
                call["name"], call["arguments"], slot=ToolSlot(round_no, position)
            )
            text_out = "".join(p.get("text", "") for p in result["content"])
            if on_tool_verified:
                on_tool_verified()
            artifacts.append(
                {"type": "tool_call", "tool_call_id": call["id"], "name": call["name"],
                 "is_error": bool(result["isError"])}
            )
            emit(
                Event(TOOL_COMPLETED, round=round_no, tool_call_id=call["id"], name=call["name"],
                      is_error=bool(result["isError"]))
            )
            messages.append(
                {"role": "tool", "tool_call_id": call["id"],
                 "content": text_out[: limits.max_tool_result_chars]}
            )
    raise ProviderError(f"{code}_LIMIT: too many model iterations")
