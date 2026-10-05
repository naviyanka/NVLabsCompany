"""Production wiring for :class:`~nexus.tools.executor.ToolExecutor`.

The executor accepts a guardrail chain, an autonomy gate and an audit store,
but nothing in ``src/`` ever passed them — only tests did, so every guardrail
and autonomy check was dead code in production. This module is the one place
that assembles the real collaborators, so a caller wires policy by importing
a function instead of remembering six constructor arguments.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from nexus.guardrails import GuardrailChain, PolicyGuardrail, StructuralGuardrail
from nexus.tools import effects
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
    company_id: uuid.UUID | None = None,
    invocation_key: str | None = None,
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
        company_id: The company the call was authorized for. The autonomy gate
            then runs under that tenant's RLS context, the same one
            :func:`nexus.tools.access.check_tool_access` used.
        invocation_key: The ledger key of a ledgered write. The autonomy gate sends its
            notification at most once per key, so a replay does not notify again.

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
        async with _access_session(company_id) as db:
            gate = build_autonomy_gate(db)
            decision = await gate.check(
                agent_id=agent_id,
                tool_id=uuid.uuid5(uuid.NAMESPACE_URL, f"tool:{tool_name}"),
                tool_name=tool_name,
                arguments=arguments,
                company_id=company_id,
                notice_key=invocation_key,
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


async def guarded_call(
    ctx: Any,
    tool_name: str,
    arguments: dict[str, Any],
    run: Callable[[], Awaitable[Any]],
    *,
    source: str,
    agent_id: uuid.UUID | None = None,
    connection_id: uuid.UUID | None = None,
    endpoint_url: str | None = None,
    default_risk: str | None = None,
    effect: str | None = None,
    slot: effects.ToolSlot | None = None,
) -> dict[str, Any]:
    """Authorize, screen, run and record one tool call.

    This is the one security boundary every governed tool call crosses, from
    an adapter loop in this process or from an external MCP client through
    :mod:`nexus.tools.mcp_server`. The whole chain runs server-side, in order:
    access (:func:`nexus.tools.access.check_tool_access`: company, agent,
    session, MCP binding, connection, catalog, RBAC, tool policy), then
    :func:`guard_tool_call` (guardrails, autonomy gate under the same tenant).
    Every attempt, refused or not, lands in ``tool_invocations`` with its
    authorization outcome; an access decision other than ``allowed``, and any
    refusal by the guardrails or the autonomy gate, also writes an
    ``audit_log`` entry.

    Args:
        ctx: The server-built :class:`~nexus.tools.context.ExecutionContext`.
            ``None`` only on a legacy path that has none, which is a soft
            problem (``would_deny`` in audit mode, ``denied`` in enforce).
        tool_name: Name of the tool about to run.
        arguments: Arguments the tool would receive.
        run: Coroutine factory that performs the call. It runs only when the
            chain allows it; its exceptions propagate after being recorded.
        source: Dispatch path, recorded in the audit detail (``mcp``,
            ``hermes``, ``mcp_inbound``).
        agent_id: The adapter session's agent, used only when ``ctx`` is
            ``None``.
        connection_id: The ``ToolConnection`` being called, when known.
        endpoint_url: MCP server URL, for calls into a ToolConnection.
        default_risk: Risk level of a tool with no catalog entry.
        effect: The tool's declared :class:`~nexus.tools.effects.EffectClass`. ``None`` is
            treated as a non-idempotent write: a missing declaration never makes a call
            repeatable. Only a call inside a chat turn (``ctx.turn_id``) is ledgered.
        slot: Where the call sits in the turn (model round and position). Required for a
            write inside a turn: the ledger identity is the slot, and a write with none is
            refused rather than run without a durable identity.

    Returns:
        ``{"status": "success", "result": ...}`` when the call ran (or, with
        ``"replayed": True``, when an earlier run of the same logical call in this turn is
        returned instead of running it again), or a refusal dict with ``error`` and
        ``status`` (``denied``, ``guardrail_blocked``, ``autonomy_blocked``,
        ``effect_in_progress``, ``effect_recovery_required``, ``stale_execution``,
        ``effect_ledger_unavailable``)
        when it did not. A call that ran but whose result cannot be retained safely returns
        ``effect_result_unavailable``; its effect is recorded as ambiguous, never rerun
        automatically unless the tool is idempotent.
    """
    from nexus.tools.access import DENIED, AccessDecision, check_tool_access

    company_id = ctx.company_id if ctx is not None else None
    turn_id = getattr(ctx, "turn_id", None)
    # The slot's durable identity is known before the tool runs; it also names the temporary
    # grant use this call may pay for, so a replay of the slot reads the grant as live.
    slot_key = (
        effects.invocation_key(company_id, turn_id, slot)
        if company_id is not None and turn_id is not None and slot is not None
        else None
    )
    try:
        async with _access_session(company_id) as db:
            decision = await check_tool_access(
                db,
                ctx,
                tool_name=tool_name,
                agent_id=agent_id,
                connection_id=connection_id,
                endpoint_url=endpoint_url,
                default_risk=default_risk,
                grant_key=slot_key,
            )
    except Exception as exc:  # noqa: BLE001
        # An error is a soft problem: audit mode keeps the pre-ws05
        # behaviour, enforce mode refuses.
        from nexus.config import settings

        logger.warning("Access check errored for tool %s: %s", tool_name, exc)
        enforcement = settings.tool_binding_enforcement
        decision = AccessDecision(
            outcome=DENIED if enforcement == "enforce" else "would_deny",
            enforcement=enforcement,
            company_id=company_id,
            problems=[{"stage": "error", "reason": str(exc), "hard": False}],
        )

    started = time.monotonic()
    refusal: dict[str, Any] | None = None
    # Write-capable calls inside a chat turn are reserved durably before they run, so a
    # recovered turn cannot repeat the effect (see nexus.tools.effects).
    held = None
    effect_class = effects.resolve_effect(effect)
    ledgered = bool(
        effect_class is not effects.EffectClass.READ_ONLY and turn_id and decision.company_id
    )
    ledger_key: str | None = None
    if not decision.allowed:
        logger.warning("Access denied for tool %s: %s", tool_name, decision.reason)
        refusal = {"error": f"Denied by access policy: {decision.reason}", "status": "denied"}
    elif ledgered and slot is None:
        # Without a durable position there is no identity that survives a rerun, so a write
        # must not pretend to have recovery. Refused before any guard or notice side effect.
        logger.error("Write tool %s called inside a turn with no durable slot", tool_name)
        refusal = {
            "error": "Tool call has no durable position in the turn, so the write was not run",
            "status": "effect_ledger_unavailable",
        }
    else:
        stale = ""
        if ledgered and slot is not None:
            ledger_key = effects.invocation_key(decision.company_id, turn_id, slot)
            # Fence first: an execution a recovery replaced must not reach the autonomy gate
            # (which can create an approval or send a notice) or the grant. The claim repeats
            # the check under a lock; this one keeps the earlier side effects from happening.
            stale = await _stale_execution(ctx, decision.company_id, turn_id)
        if stale:
            refusal = {"error": f"Tool call not run: {stale}", "status": "stale_execution"}
        # Only an agent that passed the access check reaches the autonomy
        # gate, and it runs under the company the call was authorized for.
        if not stale:
            refusal = await guard_tool_call(
                tool_name,
                arguments,
                agent_id=decision.agent_id,
                company_id=decision.company_id,
                invocation_key=ledger_key,
            )
        if refusal is None and decision.temp_grant_id is not None and not (
            ledgered and slot is not None
        ):
            # A ledgered call spends inside its claim, once it is known to run. Any other call
            # pays here, under its slot key, or a fresh key when it has no slot.
            refusal = await _spend_temp_grant(decision, slot_key or uuid.uuid4().hex)

    record = functools.partial(_record_invocation, decision, ctx, tool_name, arguments, source)
    if refusal is not None:
        await record(refusal["status"], started, error=refusal["error"])
        return refusal

    if ledgered and slot is not None:
        try:
            held = await effects.claim(
                decision.company_id,
                turn_id,
                slot,
                tool_name,
                effect_class,
                arguments,
                grant_id=decision.temp_grant_id,
                epoch=_epoch_of(ctx),
            )
        except Exception as exc:  # noqa: BLE001 - no ledger, no write: fail closed
            logger.error("Tool effect ledger unavailable for %s: %s", tool_name, exc)
            refusal = {
                "error": "Tool effect could not be recorded, so the call was not run",
                "status": "effect_ledger_unavailable",
            }
            await record(refusal["status"], started, error=refusal["error"])
            return refusal
        if held.action == "replay":
            try:
                replayed = effects.decode_result(held.stored or {})
            except Exception as exc:  # noqa: BLE001 - done once, but cannot be returned
                logger.error("Stored effect for %s cannot be replayed: %s", tool_name, exc)
                refusal = {
                    "error": "Tool already ran in this turn and its result is unavailable",
                    "status": "effect_ledger_unavailable",
                }
                await record(refusal["status"], started, error=refusal["error"])
                return refusal
            await record("replayed", started)
            return {"status": "success", "result": replayed, "replayed": True}
        if held.action == "denied":
            refusal = {
                "error": "Denied by access policy: temporary access is no longer valid",
                "status": "denied",
            }
            await record(refusal["status"], started, error=refusal["error"])
            return refusal
        if held.action != "run":
            refusal = {
                "error": f"Tool call not run: {held.reason}",
                "status": {
                    "busy": "effect_in_progress",
                    "stale": "stale_execution",
                }.get(held.action, "effect_recovery_required"),
            }
            await record(refusal["status"], started, error=refusal["error"])
            return refusal

    try:
        with effects.bind_invocation(held.key if held is not None else None):
            result = await run()
    except BaseException as exc:
        if held is not None:
            # Cancellation included: the effect may have happened. Shielded so a second
            # cancel cannot leave the row looking like a live holder.
            await asyncio.shield(
                # By type only: an exception message can carry request data or credentials.
                effects.settle(held, effects.outcome_of_exception(exc), error=type(exc).__name__)
            )
        if isinstance(exc, Exception):
            await record("error", started, error=str(exc))
        raise
    if held is not None:
        status, error = effects.outcome_of(result, tool_name)
        if status == "succeeded":
            # The replayable form is made once, here, and handed to this caller too, so the
            # first run and every replay see exactly the same bounded, scrubbed result.
            try:
                stored = effects.seal_result(result)
            except Exception as exc:  # noqa: BLE001 - the effect happened; never rerun it blind
                reason = type(exc).__name__
                logger.error("Result of %s cannot be retained: %s", tool_name, reason)
                await asyncio.shield(
                    effects.settle(held, "ambiguous", error=f"result not retainable: {reason}")
                )
                refusal = {
                    "error": (
                        "Tool ran but its result could not be retained safely; "
                        "the outcome needs review"
                    ),
                    "status": "effect_result_unavailable",
                }
                await record("error", started, error=refusal["error"])
                return refusal
            await asyncio.shield(effects.settle(held, "succeeded", stored=stored))
            result = effects.decode_result(stored)
        else:
            await asyncio.shield(effects.settle(held, status, error=error))
    # An MCP result reports a tool-side failure in-band rather than raising.
    failed = bool(getattr(result, "is_error", False))
    await record("error" if failed else "success", started)
    return {"status": "success", "result": result}


def _epoch_of(ctx: Any) -> effects.Epoch | None:
    """The execution epoch the server put on the context, or None when it has none."""
    attempt = getattr(ctx, "turn_attempt", None)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        return None
    return effects.Epoch(getattr(ctx, "turn_execution", None), attempt)


async def _stale_execution(ctx: Any, company_id: uuid.UUID, turn_id: uuid.UUID) -> str:
    """Why this call's execution of the turn is no longer the current one ("" if it is).

    A database error is reported as stale too: with no way to tell, nothing is written.
    """
    try:
        return await effects.is_current_execution(company_id, turn_id, _epoch_of(ctx))
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.error("Execution epoch check failed: %s", exc)
        return "the turn's execution could not be verified, so the write was not run"


async def _spend_temp_grant(decision: Any, key: str) -> dict[str, Any] | None:
    """Use up one use of the temporary allow a call with no ledger claim relies on.

    One conditional UPDATE, so a revoke, an expiry or a parallel call that got there first
    leaves this call denied. The grant is spent just before the tool runs, not at check time,
    and a later tool failure does not refund it. ``key`` is the call's slot key, so a replay of
    the same slot is not charged twice; a call with no slot gets a fresh key and is always
    charged. Ledgered calls spend inside :func:`nexus.tools.effects.claim` instead.
    """
    from nexus.tools import governance_overlay

    async with _access_session(decision.company_id) as db:
        spent = await governance_overlay.consume_temp_grant(
            db, decision.company_id, decision.temp_grant_id, key
        )
        await db.commit()
    if spent:
        return None
    return {
        "error": "Denied by access policy: temporary access is no longer valid",
        "status": "denied",
    }


def _access_session(company_id: uuid.UUID | None) -> Any:
    """A session carrying tenant RLS context when the company is known."""
    from nexus import database

    if company_id is not None:
        return database.tenant_session(company_id)
    return database.async_session_factory()


async def _record_invocation(
    decision: Any,
    ctx: Any,
    tool_name: str,
    arguments: dict[str, Any],
    source: str,
    status: str,
    started: float,
    *,
    error: str | None = None,
) -> None:
    """Persist one guarded call to ``tool_invocations`` (and ``audit_log``).

    The row carries only identities the access check validated, plus who the
    principal was and which request path and adapter made the call. Skipped
    when the company is unknown (a legacy call for an agent with no row):
    there is no tenant to attribute the row to. Best effort: a failed write is
    logged and never fails the tool call.
    """
    if decision.company_id is None:
        return

    from nexus.governance.audit_service import record_audit
    from nexus.models.tool_invocation import ToolInvocation
    from nexus.tools.executor import _scrub_arguments

    detail = {**decision.detail(), "source": source}
    if ctx is not None:
        # The agent and session the context claimed, kept even when the check
        # rejected them (the row's own columns hold only validated ids), so a
        # wrong-agent or wrong-session refusal says what was attempted.
        detail.update(
            principal_id=ctx.principal_id,
            principal_role=ctx.principal_role,
            request_source=ctx.source,
            adapter=ctx.adapter,
            model=ctx.model,
            claimed_agent_id=str(ctx.agent_id) if ctx.agent_id else None,
            claimed_session_id=str(ctx.session_id) if ctx.session_id else None,
        )
        if ctx.turn_id is not None:
            # A manager-bridge call; its principal_id is "run:<execution_id>".
            detail["turn_id"] = str(ctx.turn_id)
        actor_type, _, actor_id = ctx.principal_id.partition(":")
    else:
        actor_type, actor_id = "agent", str(decision.agent_id)
    try:
        async with _access_session(decision.company_id) as db:
            invocation = ToolInvocation(
                company_id=decision.company_id,
                agent_id=decision.agent_id,
                connection_id=decision.connection_id,
                session_id=decision.session_id,
                tool_name=tool_name,
                arguments_scrubbed=_scrub_arguments(arguments),
                status=status,
                duration_ms=int((time.monotonic() - started) * 1000),
                error=error,
                completed_at=datetime.now(UTC).replace(tzinfo=None),
                authorization=decision.outcome,
                authorization_detail=detail,
            )
            db.add(invocation)
            # Access refusals and would-denies, then refusals after access
            # passed: a refused call must be as visible as an allowed one.
            if decision.outcome != "allowed":
                action = f"tool.access_{decision.outcome}"
            elif status in ("guardrail_blocked", "autonomy_blocked"):
                action = f"tool.{status}"
            else:
                action = None
            if action is not None:
                await record_audit(
                    decision.company_id,
                    action,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    resource_type="tool_invocation",
                    resource_id=str(invocation.id),
                    details={**detail, "tool_name": tool_name, "status": status},
                    db=db,
                )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record invocation of tool %s: %s", tool_name, exc)


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
        notice_once=effects.claim_notice,
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
