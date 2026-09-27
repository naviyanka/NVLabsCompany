"""Server-side authorization for one tool call (ws05).

``check_tool_access`` runs the access part of the tool chain:

    Agent -> Session -> MCP binding -> ToolConnection -> ToolCatalogEntry
          -> RBAC -> ToolPolicy / ToolProfile

The autonomy gate and the guardrails come after it, in
:func:`nexus.tools.factory.guard_tool_call`. Who is calling comes from a
server-built :class:`~nexus.tools.context.ExecutionContext`, and everything
else is resolved from the database; nothing the frontend, the model or an MCP
client sends can grant access.

Problems are either *hard* or *soft*:

- Hard: identity mismatches (an agent, session or connection that belongs to
  another company or agent), RBAC and ToolPolicy/ToolProfile denials. These
  deny in every mode, so a binding can never override them.
- Soft: the binding layer that ws05 introduces (unregistered or inactive
  connection, missing or disabled binding, tool disabled by a binding or in
  the catalog, unknown tool), a call with no agent identity, and a legacy
  call path that supplied no execution context at all.
  Under ``settings.tool_binding_enforcement == "audit"`` they produce
  ``would_deny`` and the call still runs; under ``"enforce"`` they deny.

Every problem is collected rather than returning at the first one, so a soft
problem can never hide a hard one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_
from sqlmodel import select

from nexus.governance.rbac import role_allows
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.mcp_binding import McpBinding
from nexus.models.tool import (
    ToolCatalogEntry,
    ToolConnection,
    ToolPolicy,
    ToolProfile,
    ToolProfileBinding,
)
from nexus.tools.context import INBOUND_MCP, ExecutionContext
from nexus.tools.policy_engine import (
    PolicyRule,
    ProfileBinding,
    ProfileResolver,
    ToolPolicyEngine,
)

ALLOWED = "allowed"
WOULD_DENY = "would_deny"
DENIED = "denied"

# Risk assumed for a tool with no catalog entry. Errs closed: a policy that
# denies writes also catches a tool nobody has classified.
UNCLASSIFIED_RISK = "write"

# NEXUS's own tools, served to external MCP clients by nexus.tools.mcp_server,
# are registered as one ToolConnection per company with this transport, so the
# same bindings and catalog govern them as any outbound connection.
BUILTIN_TRANSPORT = "nexus_builtin"
BUILTIN_ENDPOINT = "nexus://builtin"


@dataclass
class AccessDecision:
    """Outcome of :func:`check_tool_access`."""

    outcome: str
    enforcement: str
    company_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    connection_id: uuid.UUID | None = None
    binding_ids: list[str] = field(default_factory=list)
    risk_level: str = UNCLASSIFIED_RISK
    problems: list[dict[str, Any]] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        """Whether the call may run (``allowed`` or ``would_deny``)."""
        return self.outcome != DENIED

    @property
    def reason(self) -> str:
        """The problems, as one line for the model and the logs."""
        return "; ".join(f"{p['stage']}: {p['reason']}" for p in self.problems)

    def detail(self) -> dict[str, Any]:
        """JSON-safe record for ``ToolInvocation.authorization_detail``."""
        return {
            "enforcement": self.enforcement,
            "connection_id": str(self.connection_id) if self.connection_id else None,
            "binding_ids": self.binding_ids,
            "risk_level": self.risk_level,
            "problems": self.problems,
        }


async def check_tool_access(
    db: Any,
    ctx: ExecutionContext | None,
    *,
    tool_name: str,
    agent_id: uuid.UUID | None = None,
    connection_id: uuid.UUID | None = None,
    endpoint_url: str | None = None,
    default_risk: str | None = None,
    enforcement: str | None = None,
) -> AccessDecision:
    """Decide whether the caller in ``ctx`` may call ``tool_name``.

    Args:
        db: An ``AsyncSession``. Under PostgreSQL it should carry the tenant's
            RLS context (``nexus.database.tenant_session``).
        ctx: Server-built identity of the call: company, principal and role,
            agent and session. The agent and session are checked against the
            company here. ``None`` is a legacy path with no context: that is a
            soft problem, and RBAC cannot pass without a role.
        tool_name: The tool about to run.
        agent_id: Only used when ``ctx`` is ``None``: the agent the adapter
            session was created for.
        connection_id: The ``ToolConnection`` being called, when known.
        endpoint_url: The MCP server URL. Resolved to the company's
            ``ToolConnection`` when ``connection_id`` is not given.
        default_risk: Risk level for a tool with no catalog entry. Defaults to
            :data:`UNCLASSIFIED_RISK`.
        enforcement: ``audit`` or ``enforce``; defaults to
            ``settings.tool_binding_enforcement``.

    Returns:
        The decision. ``outcome`` is ``allowed``, ``would_deny`` or ``denied``.
        ``company_id``, ``agent_id`` and ``session_id`` are set only to values
        that passed their check.
    """
    if enforcement is None:
        from nexus.config import settings

        enforcement = settings.tool_binding_enforcement

    decision = AccessDecision(
        outcome=ALLOWED, enforcement=enforcement, risk_level=default_risk or UNCLASSIFIED_RISK
    )

    def problem(stage: str, reason: str, *, hard: bool) -> None:
        decision.problems.append({"stage": stage, "reason": reason, "hard": hard})

    if ctx is None:
        problem("context", "no server-side execution context", hard=False)
    else:
        decision.company_id = ctx.company_id
        agent_id = ctx.agent_id

    # Agent: must be in the context's company. Without a context, the agent
    # row is the only source of the company.
    agent = await db.get(Agent, agent_id) if agent_id is not None else None
    if agent_id is None:
        problem("agent", "no agent identity", hard=False)
    elif agent is None or (ctx is not None and agent.company_id != ctx.company_id):
        problem("agent", "agent not found in this company", hard=ctx is not None)
        agent = None
    else:
        decision.company_id = agent.company_id
        decision.agent_id = agent.id

    # Session: must be this agent's, in this company.
    if ctx is not None and ctx.session_id is not None:
        record = await db.get(AgentSessionRecord, ctx.session_id)
        if (
            record is None
            or record.agent_id != ctx.agent_id
            or record.company_id != ctx.company_id
        ):
            problem("session", "session does not belong to this agent", hard=True)
        else:
            decision.session_id = record.id

    # Connection, binding and catalog apply to calls into a ToolConnection.
    if connection_id is not None or endpoint_url is not None:
        await _check_connection(db, decision, problem, tool_name, connection_id, endpoint_url)

    # RBAC, with the role of the authenticated principal. Never defaulted: a
    # call without a context has no role and is already a problem above.
    if ctx is not None and not role_allows(ctx.principal_role, "execute", "tool", tool_name):
        problem("rbac", f"role '{ctx.principal_role}' may not execute tools", hard=True)

    # ToolPolicy, with the ToolProfile as the default effect.
    if decision.company_id is not None:
        policy = await _evaluate_policy(
            db,
            decision.company_id,
            agent,
            tool_name,
            decision.risk_level,
            external=ctx is not None and ctx.source == INBOUND_MCP,
        )
        if not policy.allowed:
            problem("policy", policy.reason, hard=True)

    if any(p["hard"] for p in decision.problems):
        decision.outcome = DENIED
    elif decision.problems:
        decision.outcome = DENIED if enforcement == "enforce" else WOULD_DENY
    return decision


async def _check_connection(
    db: Any,
    decision: AccessDecision,
    problem: Any,
    tool_name: str,
    connection_id: uuid.UUID | None,
    endpoint_url: str | None,
) -> None:
    """Connection, binding and catalog stages. Mutates ``decision``."""
    company_id = decision.company_id
    if connection_id is not None:
        connection = await db.get(ToolConnection, connection_id)
    elif company_id is not None:
        # The adapter only knows the URL it dialled. Match it against this
        # company's registered connections; another tenant's are never seen.
        connection = (
            await db.execute(
                select(ToolConnection).where(
                    ToolConnection.company_id == company_id,
                    ToolConnection.endpoint_url == endpoint_url,
                )
            )
        ).scalars().first()
    else:
        connection = None

    if connection is None:
        problem("connection", "MCP server is not a registered tool connection", hard=False)
        return
    if company_id is not None and connection.company_id != company_id:
        problem("connection", "tool connection belongs to another company", hard=True)
        return
    decision.connection_id = connection.id
    if not connection.is_active:
        problem("connection", "tool connection is inactive", hard=False)

    # Bindings in scope: the agent's, plus the session's. Only validated ids,
    # and never a NULL match: an unknown agent has no bindings.
    targets = [
        column == value
        for column, value in (
            (McpBinding.agent_id, decision.agent_id),
            (McpBinding.session_id, decision.session_id),
        )
        if value is not None
    ]
    bindings = (
        (
            await db.execute(
                select(McpBinding).where(
                    McpBinding.company_id == connection.company_id,
                    McpBinding.connection_id == connection.id,
                    or_(*targets),
                )
            )
        ).scalars().all()
        if targets
        else []
    )
    decision.binding_ids = [str(b.id) for b in bindings]
    if any(b.status == "disabled" for b in bindings):
        problem("binding", "a binding in scope disables this connection", hard=False)
    elif not any(b.status == "active" for b in bindings):
        problem("binding", "no active binding grants this connection", hard=False)
    if any(tool_name in (b.disabled_tools or []) for b in bindings):
        problem("binding", f"tool '{tool_name}' is disabled by a binding", hard=False)

    entry = (
        await db.execute(
            select(ToolCatalogEntry).where(
                ToolCatalogEntry.connection_id == connection.id,
                ToolCatalogEntry.tool_name == tool_name,
            )
        )
    ).scalars().first()
    if entry is None:
        problem("catalog", f"tool '{tool_name}' is not in the connection's catalog", hard=False)
        return
    decision.risk_level = entry.risk_level
    if not entry.is_active:
        problem("catalog", f"tool '{tool_name}' is disabled in the catalog", hard=False)


async def _evaluate_policy(
    db: Any,
    company_id: uuid.UUID,
    agent: Agent | None,
    tool_name: str,
    risk_level: str,
    *,
    external: bool = False,
) -> Any:
    """Evaluate the company's ToolPolicy rows for this call.

    With no matching policy the effect is the ``default_action`` of the
    agent's ToolProfile (agent, then department, then company binding). With
    no profile bound it is ``allow`` for NEXUS's own agents, which is the
    behaviour before ws05, and ``deny`` for an ``external`` caller (an inbound
    MCP client), which also gets :func:`default_read_policy` when the company
    has written no policies at all.
    """
    bound = (
        await db.execute(
            select(ToolProfileBinding, ToolProfile)
            .join(ToolProfile, ToolProfile.id == ToolProfileBinding.profile_id)
            .where(
                ToolProfileBinding.company_id == company_id,
                ToolProfile.is_active == True,  # noqa: E712
            )
        )
    ).all()
    resolver = ProfileResolver()
    resolver.load_bindings(
        [
            ProfileBinding(
                id=b.id,
                profile_id=b.profile_id,
                target_type=b.target_type,
                target_id=b.target_id,
                priority=b.priority,
                default_action=p.default_action,
            )
            for b, p in bound
        ]
    )
    agent_id = agent.id if agent is not None else None
    department_id = agent.department_id if agent is not None else None
    profile = resolver.resolve(agent_id, department_id, company_id)

    fallback = "deny" if external else "allow"
    engine = ToolPolicyEngine(default_effect=profile.default_action if profile else fallback)
    rows = (
        await db.execute(
            select(ToolPolicy).where(
                ToolPolicy.company_id == company_id,
                ToolPolicy.is_active == True,  # noqa: E712
            )
        )
    ).scalars().all()
    rules = [
        PolicyRule(
            id=r.id,
            company_id=r.company_id,
            name=r.name,
            priority=r.priority,
            effect=r.effect,
            conditions=r.conditions or {},
        )
        for r in rows
    ]
    if external and not rules:
        rules = [default_read_policy(company_id)]
    engine.load_policies(rules)
    return engine.evaluate(
        agent_id,
        tool_name,
        risk_level,
        {"company_id": str(company_id), "hour": datetime.now(UTC).hour},
    )


def default_read_policy(company_id: uuid.UUID) -> PolicyRule:
    """Inbound MCP baseline for a company with no tool policies: read-risk tools only.

    Write-risk tools stay denied until someone writes a policy allowing them,
    so turning the inbound server on cannot by itself hand an external client
    the ability to send mail or write rows.
    """
    return PolicyRule(
        company_id=company_id,
        name="default: read-only tools",
        priority=1000,
        effect="allow",
        conditions={"risk_level": ["read"]},
    )


# Command-line flags that would let a task payload give an out-of-process CLI
# agent tools or permissions of its own choosing. A CLI agent reaches NEXUS's
# governed tools only through the inbound MCP server (run token ->
# guarded_call), so a payload may not attach other tool servers, switch the
# CLI's own permission checks off, or widen the directories it may touch
# beyond the workspace the server chose.
_FORBIDDEN_CLI_FLAGS = (
    "--mcp-config",
    "--strict-mcp-config",
    "--allowed-mcp-server-names",
    "--dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",
    "--permission-mode",
    "--permission-prompt-tool",
    "--allowedtools",
    "--allowed-tools",
    "--yolo",
    "--full-auto",
    "--config",
    "-c",
    "--settings",
    "--add-dir",
    "--include-directories",
    "--cd",
    "--sandbox",
    "-s",
    # Per-CLI autonomy / approval bypasses (kiro, copilot, cursor, gemini,
    # aider, codex, hermes).
    "--trust-all-tools",
    "--trust-tools",
    "--allow-all-tools",
    "--allow-tool",
    "--force",
    "--approval-mode",
    "--yes",
    "--yes-always",
    "--approve-for-me",
    "--dangerously-bypass-hook-trust",
)


def check_cli_args(args: Any) -> str | None:
    """Why a task payload's extra CLI ``args`` are refused, or ``None``.

    The one place this rule lives; every CLI adapter calls it before spawning.
    """
    if args is None:
        return None
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return "args must be a list of strings"
    for arg in args:
        flag = arg.split("=", 1)[0].lower()
        if flag in _FORBIDDEN_CLI_FLAGS:
            return f"argument {flag} is not allowed in a task payload"
    return None
