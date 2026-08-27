"""Per-agent, per-action autonomy policy (Phase 3.4).

An agent carries ``autonomy_policy`` — ``{action_type: 1|2|3}``:

* **L1** — run, no ceremony.
* **L2** — run, but notify an operator.
* **L3** — create an approval and block; the call runs only once approved.

Action type comes from the tool name (and, for spend, the arguments), so a
policy is written against five stable buckets rather than every tool name.

The correlation ID is a UUIDv5 of ``(agent_id, tool_id, canonical arguments)``
and is used *as the approval row's primary key*. Re-issuing the same tool call
therefore resolves to the same approval — that is what lets a blocked run
resume after approval instead of creating a second request.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

# Namespace for deterministic tool-call correlation IDs.
CORRELATION_NAMESPACE = uuid.UUID("6f2b7c1e-9a34-5d78-b1c0-4e8f2a6d3b91")

# Action buckets a policy can be written against.
ACTION_DELETE = "delete"
ACTION_EXECUTE_CODE = "execute_code"
ACTION_SEND_EXTERNAL_MESSAGE = "send_external_message"
ACTION_WRITE_FILE = "write_file"
ACTION_SPEND = "spend"
ACTION_READ = "read"

# Tool-name substrings per action bucket, most-dangerous first. The first
# bucket with a matching substring wins, so "delete_file" is a delete and not
# a write.
_NAME_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ACTION_DELETE, ("delete", "remove", "destroy", "drop", "purge", "rm_", "unlink")),
    (
        ACTION_EXECUTE_CODE,
        ("exec", "shell", "bash", "command", "run_code", "python", "eval", "terminal"),
    ),
    (
        ACTION_SEND_EXTERNAL_MESSAGE,
        (
            "email",
            "slack",
            "sms",
            "send_message",
            "webhook",
            "publish",
            "tweet",
            "post_to",
            "notify_external",
        ),
    ),
    (
        ACTION_WRITE_FILE,
        ("write", "create_file", "edit", "patch", "save", "upload", "commit", "mkdir"),
    ),
)

# Argument keys that mean "this call spends money".
_SPEND_KEYS = ("amount_cents", "cost_cents", "spend_cents", "price_cents")

# Policy key holding the spend threshold, in cents. Below it, a spending call
# is treated as a plain read and the spend level does not apply.
SPEND_THRESHOLD_KEY = "spend_above_cents"


def classify_action(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    spend_threshold_cents: int = 0,
) -> str:
    """Map a tool call to its action bucket.

    Args:
        tool_name: The tool being invoked.
        arguments: The call's arguments, inspected for spend amounts.
        spend_threshold_cents: Spend at or below this is not a spend action.

    Returns:
        One of the ``ACTION_*`` constants.
    """
    amount = _spend_amount(arguments)
    if amount is not None and amount > spend_threshold_cents:
        return ACTION_SPEND

    lowered = tool_name.lower()
    for action, patterns in _NAME_PATTERNS:
        if any(p in lowered for p in patterns):
            return action
    return ACTION_READ


def _spend_amount(arguments: dict[str, Any] | None) -> int | None:
    """Extract a spend amount in cents from arguments, if present."""
    if not arguments:
        return None
    for key in _SPEND_KEYS:
        value = arguments.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return None


def correlation_id(
    agent_id: uuid.UUID, tool_id: uuid.UUID, arguments: dict[str, Any] | None
) -> uuid.UUID:
    """Derive the deterministic ID for a tool call.

    The same agent, tool, and arguments always produce the same ID, so a
    retried call finds its existing approval rather than filing a new one.

    Args:
        agent_id: The calling agent.
        tool_id: The tool being called.
        arguments: The call's arguments.

    Returns:
        A UUIDv5 correlation ID.
    """
    canonical = json.dumps(arguments or {}, sort_keys=True, default=str)
    return uuid.uuid5(CORRELATION_NAMESPACE, f"{agent_id}:{tool_id}:{canonical}")


@dataclass
class AutonomyDecision:
    """Outcome of an autonomy check.

    Attributes:
        allowed: Whether the call may proceed.
        level: The resolved autonomy level (1, 2, or 3).
        action_type: The action bucket the call was classified into.
        correlation_id: Deterministic ID for this call.
        approval_id: The approval gating this call, when level 3.
        reason: Why the call was blocked, if it was.
        notified: Whether an operator notification was emitted.
    """

    allowed: bool
    level: int
    action_type: str
    correlation_id: uuid.UUID
    approval_id: uuid.UUID | None = None
    reason: str | None = None
    notified: bool = False


class AutonomyGate:
    """Resolves and enforces an agent's per-action autonomy policy.

    Collaborators are duck-typed so the gate works against the real
    ``ApprovalService`` or a fake:

    * ``approvals.get(approval_id)`` -> approval-like with ``.status``, or None.
    * ``approvals.request_approval(company_id=..., approval_type=...,
      requested_by_agent_id=..., payload=..., approval_id=...)``.
    * ``notifier(payload: dict)`` — awaited when a level-2 or level-3 call fires.
    """

    def __init__(
        self,
        policy_loader: Callable[[uuid.UUID], Awaitable[dict[str, Any] | None]],
        approvals: Any | None = None,
        notifier: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        default_level: int = 1,
    ) -> None:
        """Initialize the gate.

        Args:
            policy_loader: Async function(agent_id) -> the agent's
                ``autonomy_policy`` dict, or None when it has none.
            approvals: Approval store used for level-3 gating. Without it,
                level 3 blocks but files nothing.
            notifier: Async sink for level-2 and level-3 notifications.
            default_level: Level for an action the policy does not mention.
        """
        self._policy_loader = policy_loader
        self._approvals = approvals
        self._notifier = notifier
        self._default_level = default_level

    async def check(
        self,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        company_id: uuid.UUID | None = None,
    ) -> AutonomyDecision:
        """Decide whether a tool call may proceed under the agent's policy.

        Args:
            agent_id: The calling agent.
            tool_id: The tool being called.
            tool_name: The tool's name, used for classification.
            arguments: The call's arguments.
            company_id: Company scope for the approval record.

        Returns:
            An AutonomyDecision.
        """
        policy = await self._policy_loader(agent_id) or {}
        threshold = int(policy.get(SPEND_THRESHOLD_KEY, 0) or 0)
        action_type = classify_action(tool_name, arguments, threshold)
        level = _coerce_level(policy.get(action_type), self._default_level)
        cid = correlation_id(agent_id, tool_id, arguments)

        if level <= 1:
            return AutonomyDecision(True, level, action_type, cid)

        payload = {
            "correlation_id": str(cid),
            "action_type": action_type,
            "autonomy_level": level,
            "tool_id": str(tool_id),
            "tool_name": tool_name,
            "agent_id": str(agent_id),
        }

        if level == 2:
            await self._notify(payload)
            return AutonomyDecision(True, level, action_type, cid, notified=True)

        # Level 3: an approval decides. The correlation ID is the approval's
        # primary key, so a resumed call finds the decision made earlier.
        if self._approvals is None:
            return AutonomyDecision(
                False,
                level,
                action_type,
                cid,
                reason=(
                    f"Autonomy level 3 for '{action_type}' requires approval, "
                    "but no approval store is configured"
                ),
            )

        existing = await self._approvals.get(cid)
        status = getattr(existing, "status", None) if existing is not None else None

        if status == "approved":
            return AutonomyDecision(True, level, action_type, cid, approval_id=cid)
        if status == "rejected":
            return AutonomyDecision(
                False,
                level,
                action_type,
                cid,
                approval_id=cid,
                reason=f"Approval rejected for '{action_type}'",
            )

        if existing is None:
            await self._approvals.request_approval(
                company_id=company_id,
                approval_type=f"tool_call.{action_type}",
                requested_by_agent_id=agent_id,
                payload=payload,
                approval_id=cid,
            )
            await self._notify(payload)

        return AutonomyDecision(
            False,
            level,
            action_type,
            cid,
            approval_id=cid,
            reason=f"Awaiting approval for '{action_type}' (correlation {cid})",
            notified=existing is None,
        )

    async def _notify(self, payload: dict[str, Any]) -> None:
        """Emit an operator notification, if a sink is configured."""
        if self._notifier is not None:
            await self._notifier(payload)


def _coerce_level(value: Any, default: int) -> int:
    """Read a policy value as an autonomy level, falling back on junk."""
    try:
        level = int(value)
    except (TypeError, ValueError):
        return default
    return level if 1 <= level <= 3 else default


async def db_policy_loader(agent_id: uuid.UUID, db: Any) -> dict[str, Any] | None:
    """Load an agent's ``autonomy_policy`` from the database.

    Args:
        agent_id: The agent to load.
        db: An AsyncSession.

    Returns:
        The policy dict, or None when the agent has none.
    """
    from sqlalchemy import select

    from nexus.models.agent import Agent

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    return getattr(agent, "autonomy_policy", None) if agent else None
