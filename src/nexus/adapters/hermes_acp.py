"""Execution-scoped Hermes transport over the Agent Client Protocol (ACP).

The Hermes CLI reads MCP servers only from its persistent config, which Nexus
never writes. ``hermes acp`` instead accepts ``mcpServers`` in ``session/new``
and keeps them in that process's memory. One tool-enabled turn therefore gets
its own child: initialize, one session carrying the execution-scoped Nexus MCP
server, one prompt, then the whole process tree is ended. Nothing is shared
between executions and nothing is written to Hermes' config, auth or ``.env``.

The bearer credential exists only in the ``session/new`` request and in the
child's memory. Raw protocol traffic is never stored or logged; the only things
kept are the reply text and safe decision metadata (tool names, not arguments).

Hermes cannot be confined by ACP alone: it always enables its own coding
toolset (terminal, files, browser) in an ACP session and asks the client only
for dangerous commands. So the client is fail-closed on what it can see: every
permission request is denied, and a tool call that is not one of the offered
Nexus tools ends the turn. That second check is detective, not preventive; see
``docs/adr/0004-hermes-acp-tools.md``.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from nexus.adapters.cli_adapter import _contain, _terminate_tree

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 1024 * 1024
MAX_OUTPUT_CHARS = 200_000
STDERR_TAIL_BYTES = 4096
CANCEL_GRACE_SECONDS = 1.0
REDACTED = "[REDACTED]"


class ACPError(Exception):
    """A transport failure. ``code`` is stable; the message never has traffic."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class ACPResult:
    text: str = ""
    stop_reason: str = ""
    # Safe metadata only: ``{"kind": ..., "decision": ...}`` and tool names.
    permissions: list[dict[str, str]] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)


def tool_wire_name(server: str, tool: str) -> str:
    """The name Hermes gives an MCP tool: ``mcp__<server>__<tool>``, sanitized."""
    clean = lambda s: "".join(c if c.isalnum() or c == "_" else "_" for c in s)  # noqa: E731
    return f"mcp__{clean(server)}__{clean(tool)}"


def redact(text: str, secrets: Iterable[str]) -> str:
    """``text`` with every secret and any Authorization value removed."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


class HermesACPTransport:
    """One ``hermes acp`` child for one turn. Not reusable."""

    def __init__(
        self,
        cmd: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        mcp_servers: list[dict[str, Any]],
        allowed_tools: Iterable[str],
        turn_timeout: float,
        startup_timeout: float = 30.0,
        request_timeout: float = 30.0,
        max_frame: int = MAX_FRAME_BYTES,
        max_output: int = MAX_OUTPUT_CHARS,
        secrets: Iterable[str] = (),
    ) -> None:
        self._cmd = cmd
        self._cwd = cwd
        self._env = env
        self._servers = mcp_servers
        self._allowed = frozenset(allowed_tools)
        self._turn_timeout = turn_timeout
        self._startup_timeout = startup_timeout
        self._request_timeout = request_timeout
        self._max_frame = max_frame
        self._max_output = max_output
        self._secrets = tuple(secrets)
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._fatal: ACPError | None = None
        self._done = False
        self._proc: asyncio.subprocess.Process | None = None
        self._session_id: str | None = None
        self._chunks: list[str] = []
        self._size = 0
        self._stderr_tail = b""
        self.result = ACPResult()

    async def run(self, prompt: str) -> ACPResult:
        """Run one prompt to completion; raises :class:`ACPError` on any failure."""
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self._cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                env=self._env,
                limit=self._max_frame,
                start_new_session=os.name != "nt",
            )
        except OSError as exc:
            raise ACPError(
                "ACP_SETUP_FAILED", f"cannot start Hermes ({type(exc).__name__})"
            ) from None
        _contain(self._proc)
        tasks = [
            asyncio.create_task(self._read_loop(self._proc)),
            asyncio.create_task(self._drain_stderr(self._proc)),
        ]
        try:
            await self._request(
                "initialize",
                {"protocolVersion": PROTOCOL_VERSION, "clientCapabilities": {}},
                self._startup_timeout,
                stage="setup",
            )
            new = await self._request(
                "session/new",
                {"cwd": self._cwd, "mcpServers": self._servers},
                self._startup_timeout,
                stage="setup",
            )
            self._session_id = new.get("sessionId") if isinstance(new, dict) else None
            if not isinstance(self._session_id, str) or not self._session_id:
                raise ACPError("ACP_SETUP_FAILED", "session/new returned no session id")
            reply = await self._request(
                "session/prompt",
                {
                    "sessionId": self._session_id,
                    "prompt": [{"type": "text", "text": prompt}],
                },
                self._turn_timeout,
                stage="turn",
            )
            self.result.stop_reason = str((reply or {}).get("stopReason", ""))
            self.result.text = "".join(self._chunks)
            self._done = True
            return self.result
        finally:
            await self._close(tasks)

    async def _close(self, tasks: list[asyncio.Task[Any]]) -> None:
        """Ask ACP to cancel a live turn, then end the process tree. Idempotent."""
        proc = self._proc
        try:
            if proc is not None and proc.returncode is None:
                if (
                    self._session_id
                    and proc.stdin is not None
                    and not self._done
                    and self._fatal is None
                ):
                    try:
                        self._write(
                            {
                                "jsonrpc": "2.0",
                                "method": "session/cancel",
                                "params": {"sessionId": self._session_id},
                            }
                        )
                        await asyncio.wait_for(proc.stdin.drain(), CANCEL_GRACE_SECONDS)
                        # Let Hermes stop on its own; the tree is ended either way.
                        await asyncio.wait_for(proc.wait(), CANCEL_GRACE_SECONDS)
                    except (TimeoutError, OSError, ConnectionError):
                        pass
                await asyncio.shield(asyncio.ensure_future(_terminate_tree(proc)))
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _write(self, message: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))

    async def _request(
        self, method: str, params: dict[str, Any], timeout: float, *, stage: str
    ) -> Any:
        if self._fatal is not None:
            raise self._fatal
        self._next_id += 1
        rid = self._next_id
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            assert self._proc is not None and self._proc.stdin is not None
            await self._proc.stdin.drain()
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            raise ACPError("ACP_TIMEOUT", f"{method} timed out after {timeout:g}s") from None
        except (BrokenPipeError, ConnectionError):
            raise self._fatal or ACPError("ACP_CHILD_EXIT", "Hermes closed its input") from None
        finally:
            self._pending.pop(rid, None)

    def _fail(self, error: ACPError) -> None:
        """First failure wins; it ends every waiting request."""
        if self._fatal is None:
            self._fatal = error
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(self._fatal)

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        """Keep the child from blocking on a full pipe; keep only a redacted tail."""
        assert proc.stderr is not None
        while chunk := await proc.stderr.read(4096):
            self._stderr_tail = (self._stderr_tail + chunk)[-STDERR_TAIL_BYTES:]

    async def _read_loop(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while True:
            try:
                line = await proc.stdout.readline()
            except ValueError:  # a frame over the stream limit
                self._fail(
                    ACPError("ACP_FRAME_TOO_LARGE", f"a message exceeded {self._max_frame} bytes")
                )
                return
            if not line:
                self._fail(ACPError("ACP_CHILD_EXIT", "Hermes exited before the turn finished"))
                return
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError
            except ValueError:
                self._fail(ACPError("ACP_PROTOCOL", "Hermes sent a malformed message"))
                return
            try:
                await self._dispatch(message)
            except ACPError as exc:
                self._fail(exc)
                return

    async def _dispatch(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        mid = message.get("id")
        if method is None:  # a response
            fut = self._pending.get(mid) if isinstance(mid, int) else None
            if fut is None or fut.done():
                return  # unknown or duplicate id: ignored, never replayed
            if "error" in message:
                code = (
                    (message["error"] or {}).get("code")
                    if isinstance(message["error"], dict)
                    else None
                )
                fut.set_exception(
                    ACPError("ACP_REQUEST_FAILED", f"Hermes rejected the request (code {code})")
                )
            else:
                fut.set_result(message.get("result"))
        elif method == "session/update" and mid is None:
            self._on_update((message.get("params") or {}).get("update") or {})
        elif method == "session/request_permission" and mid is not None:
            self._on_permission(mid, message.get("params") or {})
            assert self._proc is not None and self._proc.stdin is not None
            await self._proc.stdin.drain()
        elif mid is not None:  # fs/*, terminal/* or anything else: not offered
            self._write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": "method not supported"},
                }
            )

    def _on_update(self, update: dict[str, Any]) -> None:
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content") or {}
            text = content.get("text") if isinstance(content, dict) else None
            if isinstance(text, str):
                self._size += len(text)
                if self._size > self._max_output:
                    raise ACPError(
                        "ACP_OUTPUT_LIMIT", f"output exceeded {self._max_output} characters"
                    )
                self._chunks.append(text)
        elif kind == "tool_call":
            name = str(update.get("title") or "")
            if name in self._allowed:
                self.result.tool_calls.append(name)
            else:
                # Detective: Hermes runs its own tools without asking, so the
                # turn ends here. The name is safe to record; arguments are not.
                self.result.tool_calls.append("[denied]")
                raise ACPError(
                    "ACP_POLICY_VIOLATION", "Hermes used a tool that is not an offered Nexus tool"
                )

    def _on_permission(self, mid: Any, params: dict[str, Any]) -> None:
        """Deny by default; allow only an offered Nexus tool with an allow-once option."""
        call = params.get("toolCall") or {}
        name = str(call.get("title") or "")
        options = [o for o in params.get("options") or [] if isinstance(o, dict)]
        allow = next((o for o in options if o.get("kind") == "allow_once"), None)
        if name in self._allowed and allow is not None:
            outcome = {"outcome": "selected", "optionId": allow.get("optionId")}
            decision = "allow"
        else:
            deny = next((o for o in options if str(o.get("kind", "")).startswith("reject")), None)
            outcome = (
                {"outcome": "selected", "optionId": deny.get("optionId")}
                if deny is not None
                else {"outcome": "cancelled"}
            )
            decision = "deny"
        self.result.permissions.append(
            {"kind": str(call.get("kind") or "unknown"), "decision": decision}
        )
        self._write({"jsonrpc": "2.0", "id": mid, "result": {"outcome": outcome}})

    @property
    def stderr_tail(self) -> str:
        return redact(self._stderr_tail.decode("utf-8", "replace"), self._secrets)
