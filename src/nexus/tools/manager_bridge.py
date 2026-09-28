"""The manager tool bridge: a CLI-backed manager's manager tools during one chat turn.

A CLI agent runs as a subprocess and reaches NEXUS's governed tools only
through MCP. For a manager's chat turn the CLI adapter asks :func:`open_bridge`
for an execution-scoped MCP server: an HTTP endpoint on this API (``PATH``)
plus a short-lived bearer credential for it. Nothing about the bridge is
persisted:

* The credential is a JWT for this module's own audience, so the REST
  middleware, which accepts only ``nexus:run`` tokens, never treats it as a
  login. It names the turn's execution, agent and company, all taken from the
  server-built :class:`~nexus.tools.context.ExecutionContext`, never from the
  CLI, the agent's config or the prompt. It lives at most
  ``min(CLI timeout, MAX_TTL_SECONDS)``.
* It reaches the CLI only through the child's environment. The config file the
  CLI loads names the variable (``${NEXUS_MANAGER_BRIDGE_TOKEN}``) rather than
  the value, and the adapter deletes the file when the execution ends.
* :func:`authenticate` re-checks, on every request, that the token's chat turn
  is still running that execution for that agent in that company, with a live
  lease and no cancel request. Completion, failure, cancellation, timeout and
  a lost lease all end that, and a retried or recovered turn is claimed with a
  new execution ID, so a leftover token stops working with its execution.

The endpoint serves only the manager tools, through the same
:class:`~nexus.tools.mcp_server.MCPServer` and ``guarded_call`` boundary as the
stdio server, so RBAC, ToolPolicy and the ToolInvocation audit apply
unchanged. Backends without per-run MCP config (Agy) chat as before, without
the tools, unless the turn requires them.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

import jwt

from nexus.auth.run_tokens import ALGORITHM
from nexus.config import settings
from nexus.models._time import utcnow
from nexus.tools import manager_tools
from nexus.tools.context import INBOUND_MCP, ExecutionContext

AUDIENCE = "nexus:manager-bridge"
TOKEN_ENV = "NEXUS_MANAGER_BRIDGE_TOKEN"
SERVER_NAME = "nexus"
PATH = "/api/v1/mcp/manager"
MAX_TTL_SECONDS = 15 * 60
REDACTED = "[REDACTED]"


class BridgeUnavailableError(Exception):
    """The turn requires manager tools that this execution cannot have."""


class BridgeDeniedError(Exception):
    """A bridge request's credential is invalid or its execution is over."""


@dataclass
class Bridge:
    """What one manager CLI execution gets. ``available`` False: no tools."""

    available: bool
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    config_path: str | None = None

    def redact(self, text: str | None) -> str | None:
        """``text`` with the credential removed, for anything that outlives the run."""
        token = self.env.get(TOKEN_ENV)
        return text.replace(token, REDACTED) if text and token else text

    def close(self) -> None:
        """Remove the config file. Idempotent."""
        if self.config_path is None:
            return
        try:
            os.unlink(self.config_path)
        except FileNotFoundError:
            pass
        self.config_path = None


def bridge_url() -> str:
    """Where the CLI reaches this API: ``manager_bridge_url``, else loopback."""
    return settings.manager_bridge_url or f"http://127.0.0.1:{settings.server_port}{PATH}"


async def open_bridge(
    ctx: ExecutionContext | None, execution_id: uuid.UUID, backend: Any, timeout: float
) -> Bridge | None:
    """The bridge for one CLI execution; None when it is not a manager's chat turn.

    Only a plain chat turn (not a task attempt) of an agent with direct reports
    is eligible; everything else runs exactly as before. An eligible turn on a
    backend without per-run MCP config gets ``Bridge(available=False)`` and
    runs without the tools.

    Raises:
        BridgeUnavailableError: The context requires manager tools and this
            execution cannot have them.
    """
    required = ctx is not None and ctx.manager_tools_required
    eligible = (
        ctx is not None
        and ctx.source == "chat"
        and ctx.work_mode is None
        and ctx.agent_id is not None
        and await manager_tools.is_manager(ctx)
    )
    if not eligible:
        if required:
            raise BridgeUnavailableError(
                "MANAGER_TOOLS_UNAVAILABLE: manager tools need a chat turn of an agent "
                "with direct reports."
            )
        return None
    if not backend.mcp_config_flag:
        if required:
            raise BridgeUnavailableError(
                f"MANAGER_TOOLS_UNSUPPORTED: {backend.name} cannot load an "
                "execution-scoped MCP server, so it cannot run with manager tools. "
                "Use a backend that can (Claude Code)."
            )
        return Bridge(available=False)
    now = utcnow()
    token = jwt.encode(
        {
            "sub": str(ctx.agent_id),
            "company_id": str(ctx.company_id),
            "execution_id": str(execution_id),
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(seconds=min(float(timeout), MAX_TTL_SECONDS)),
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )
    config = {
        "mcpServers": {
            SERVER_NAME: {
                "type": "http",
                "url": bridge_url(),
                "headers": {"Authorization": f"Bearer ${{{TOKEN_ENV}}}"},
            }
        }
    }
    # mkstemp: a new file only this user can read, outside the agent's workspace.
    fd, path = tempfile.mkstemp(prefix="nexus-mcp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(config, f)
    return Bridge(
        True, [backend.mcp_config_flag, path, *backend.mcp_bridge_args], {TOKEN_ENV: token}, path
    )


async def authenticate(token: str) -> ExecutionContext:
    """The context a bridge request acts under, bound to its running chat turn.

    Raises:
        BridgeDeniedError: Bad signature, audience or claims, expired, or the turn
            is not running this execution for this agent and company any more.
            One error for all, as in ``verify_run_token``.
    """
    from sqlalchemy import select

    from nexus.auth.principal import Principal
    from nexus.database import tenant_session
    from nexus.models.chat_turn import ChatTurn

    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "aud", "company_id", "execution_id"]},
        )
        agent_id = uuid.UUID(claims["sub"])
        company_id = uuid.UUID(claims["company_id"])
        execution_id = uuid.UUID(claims["execution_id"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise BridgeDeniedError("invalid bridge credential") from exc

    async with tenant_session(company_id) as db:
        turn = (
            await db.execute(
                select(ChatTurn).where(
                    ChatTurn.company_id == company_id,
                    ChatTurn.agent_id == agent_id,
                    ChatTurn.execution_id == str(execution_id),
                    ChatTurn.status == "running",
                    ChatTurn.cancel_requested_at.is_(None),
                )
            )
        ).scalar_one_or_none()
    if turn is None or turn.lease_expires_at is None or turn.lease_expires_at < utcnow():
        raise BridgeDeniedError("invalid bridge credential")

    principal = Principal(
        kind="run", company_id=company_id, role="agent", run_id=execution_id, agent_id=agent_id
    )
    ctx = ExecutionContext.for_principal(principal, source=INBOUND_MCP, session_id=turn.session_id)
    return replace(ctx, turn_id=turn.id)
