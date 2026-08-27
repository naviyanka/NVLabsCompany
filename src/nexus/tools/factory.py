"""Production wiring for :class:`~nexus.tools.executor.ToolExecutor`.

The executor accepts a guardrail chain, an autonomy gate and an audit store,
but nothing in ``src/`` ever passed them — only tests did, so every guardrail
and autonomy check was dead code in production. This module is the one place
that assembles the real collaborators, so a caller wires policy by importing
a function instead of remembering six constructor arguments.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from nexus.guardrails import GuardrailChain, PolicyGuardrail, StructuralGuardrail
from nexus.tools.audit import ToolAuditStore
from nexus.tools.autonomy import AutonomyGate, db_policy_loader
from nexus.tools.executor import RateLimitConfig, ToolExecutor

logger = logging.getLogger(__name__)


# Baseline deny lists. Deliberately conservative: a false block is a support
# ticket, a false allow is an incident.
DANGEROUS_COMMANDS = [
    "rm -rf /",
    "rm -rf ~",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "shutdown",
    "reboot",
    "chmod -R 777 /",
    "DROP TABLE",
    "DROP DATABASE",
    "TRUNCATE TABLE",
    "curl | sh",
    "wget | sh",
]

SENSITIVE_PATHS = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    ".ssh/id_rsa",
    ".ssh/id_ed25519",
    ".aws/credentials",
    ".kube/config",
    ".env",
    "id_rsa",
]

BLOCKED_PATTERNS = [
    r"(?i)aws_secret_access_key\s*[:=]",
    r"(?i)private[_-]?key\s*[:=]",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)password\s*[:=]\s*\S",
]


def build_guardrail_chain(
    allowed_tools: list[str] | None = None,
    max_output_length: int = 200_000,
) -> GuardrailChain:
    """Assemble the production guardrail chain.

    Args:
        allowed_tools: Optional tool-name whitelist. ``None`` allows any tool
            that clears the other checks.
        max_output_length: Cap on a tool's string output length.

    Returns:
        A fail-fast, fail-closed chain of the policy and structural guardrails.
    """
    return GuardrailChain(
        guardrails=[
            PolicyGuardrail(
                name="policy",
                blocked_patterns=BLOCKED_PATTERNS,
                sensitive_paths=SENSITIVE_PATHS,
                dangerous_commands=DANGEROUS_COMMANDS,
                allowed_tools=allowed_tools,
            ),
            StructuralGuardrail(max_length=max_output_length),
        ],
        fail_fast=True,
        fail_closed=True,
    )


async def guard_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    allowed_tools: list[str] | None = None,
    context: dict[str, Any] | None = None,
    agent_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """Screen one tool call, for dispatch paths that cannot use a ToolExecutor.

    The adapter tool loops call handlers directly, so they cannot use a
    ToolExecutor. They can still get the same two checks: the guardrail chain,
    which needs nothing but the call itself, and — when the calling agent is
    known — the autonomy gate, which needs a database session and opens its own.

    Args:
        tool_name: Name of the tool about to run.
        arguments: Arguments the tool would receive.
        allowed_tools: Optional tool-name whitelist.
        context: Optional context passed through to the guardrails.
        agent_id: The calling agent. Without it the autonomy tier cannot be
            resolved and only the guardrail chain runs.

    Returns:
        None when the call may proceed, or an error dict shaped like an ordinary
        tool failure when it must not. Returning rather than raising keeps the
        refusal visible to the model so it can adapt.
    """
    chain = build_guardrail_chain(allowed_tools=allowed_tools)
    try:
        result = await chain.validate_tool_call(tool_name, arguments, context)
    except Exception as exc:  # noqa: BLE001
        # Fail open on a guardrail *error*: a bug in a check must not take out
        # legitimate work. A guardrail *verdict* still blocks, below.
        logger.warning("Guardrail check errored for tool %s, allowing: %s", tool_name, exc)
        result = None

    if result is not None and not result.passed:
        reason = "; ".join(result.violations) or "blocked by policy"
        logger.warning("Guardrail blocked tool %s: %s", tool_name, reason)
        return {
            "error": f"Blocked by guardrail: {reason}",
            "status": "guardrail_blocked",
        }

    if agent_id is None:
        return None

    # Guardrails first, autonomy second: a call the policy refuses outright
    # should not be sent to a human for approval.
    try:
        from nexus.database import async_session_factory

        async with async_session_factory() as db:
            gate = build_autonomy_gate(db)
            decision = await gate.check(
                agent_id=agent_id,
                tool_id=uuid.uuid5(uuid.NAMESPACE_URL, f"tool:{tool_name}"),
                tool_name=tool_name,
                arguments=arguments,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Autonomy check errored for tool %s, allowing: %s", tool_name, exc)
        return None

    if decision.allowed:
        return None

    return {
        "error": decision.reason or f"Requires approval: {decision.action_type}",
        "status": "autonomy_blocked",
        "correlation_id": str(decision.correlation_id),
    }


def build_autonomy_gate(db: Any, default_level: int = 1) -> AutonomyGate:
    """Assemble the autonomy gate against the live database.

    Args:
        db: An ``AsyncSession``. Used to load each agent's ``autonomy_policy``
            and to file level-3 approvals.
        default_level: Level applied to an action the agent's policy omits.

    Returns:
        A gate backed by :class:`~nexus.services.approval_service.ApprovalService`.
    """
    from nexus.services.approval_service import ApprovalService

    async def _load(agent_id: uuid.UUID) -> dict[str, Any] | None:
        return await db_policy_loader(agent_id, db)

    return AutonomyGate(
        policy_loader=_load,
        approvals=ApprovalService(db),
        notifier=_log_notifier,
        default_level=default_level,
    )


async def _log_notifier(payload: dict[str, Any]) -> None:
    """Emit a level-2/level-3 autonomy notification.

    ponytail: logs only — no operator notification service exists yet. Swap for
    the real sink (email, Slack, in-app inbox) once one lands.
    """
    logger.warning(
        "autonomy notification: level=%s action=%s tool=%s agent=%s correlation=%s",
        payload.get("autonomy_level"),
        payload.get("action_type"),
        payload.get("tool_name"),
        payload.get("agent_id"),
        payload.get("correlation_id"),
    )


def build_tool_executor(
    db: Any,
    timeout_seconds: float = 30.0,
    rate_limit: RateLimitConfig | None = None,
    audit_store: ToolAuditStore | None = None,
    allowed_tools: list[str] | None = None,
    guardrail_max_retries: int = 0,
    default_autonomy_level: int = 1,
) -> ToolExecutor:
    """Build a ToolExecutor with guardrails, autonomy gating and audit wired.

    This is the constructor production code should call. A bare
    ``ToolExecutor()`` enforces nothing beyond permissions, rate limits and
    timeouts.

    Args:
        db: An ``AsyncSession`` for policy loading and approval records.
        timeout_seconds: Per-execution timeout.
        rate_limit: Rate limit config; executor defaults apply when None.
        audit_store: Store for structured invocation records. A fresh
            in-memory store is created when None.
        allowed_tools: Optional tool-name whitelist for the policy guardrail.
        guardrail_max_retries: Retries when a guardrail blocks tool output.
        default_autonomy_level: Level for actions the agent's policy omits.

    Returns:
        A fully wired ToolExecutor.
    """
    executor = ToolExecutor(
        timeout_seconds=timeout_seconds,
        rate_limit=rate_limit,
        audit_store=audit_store if audit_store is not None else ToolAuditStore(),
        guardrails=build_guardrail_chain(allowed_tools=allowed_tools),
        guardrail_max_retries=guardrail_max_retries,
        autonomy_gate=build_autonomy_gate(db, default_level=default_autonomy_level),
    )
    executor.set_permission_checker(_make_permission_checker(db))
    return executor


def _make_permission_checker(db: Any) -> Any:
    """Build the DB-backed permission checker for the executor.

    An agent may use a tool when an unexpired ``ToolAccess`` row grants it. No
    row means no access — the executor's own default is permissive, so the
    checker must be installed for permissions to mean anything.
    """

    async def _check(agent_id: uuid.UUID, tool_id: uuid.UUID) -> bool:
        from datetime import UTC, datetime

        from sqlalchemy import or_, select

        from nexus.models.tool import ToolAccess

        # ToolAccess timestamps are stored naive-UTC, so compare against a
        # naive now rather than an aware one.
        now = datetime.now(UTC).replace(tzinfo=None)
        result = await db.execute(
            select(ToolAccess).where(
                ToolAccess.agent_id == agent_id,
                ToolAccess.tool_id == tool_id,
                or_(ToolAccess.expires_at.is_(None), ToolAccess.expires_at > now),
            )
        )
        return result.first() is not None

    return _check
