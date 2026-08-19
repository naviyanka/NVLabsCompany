"""Tool Executor - executes tools with permission checks, audit logging, and rate limiting."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from nexus.models.tool_invocation import ToolInvocation


# Sensitive argument key substrings that trigger scrubbing
_SENSITIVE_KEYS = ("password", "secret", "token", "key")


def _scrub_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Scrub sensitive fields from tool arguments before audit storage.

    Keys containing 'password', 'secret', 'token', or 'key' (case-insensitive)
    have their values replaced with '***'.

    Args:
        arguments: The raw arguments dictionary.

    Returns:
        A new dictionary with sensitive values masked.
    """
    scrubbed: dict[str, Any] = {}
    for k, v in arguments.items():
        if any(s in k.lower() for s in _SENSITIVE_KEYS):
            scrubbed[k] = "***"
        else:
            scrubbed[k] = v
    return scrubbed


@dataclass
class ToolResult:
    """Result of a tool execution.

    Attributes:
        tool_id: The tool that was executed.
        agent_id: The agent that requested execution.
        success: Whether execution succeeded.
        output: The tool's output data.
        error: Error message if execution failed.
        duration_ms: Execution time in milliseconds.
        timestamp: When the execution occurred.
    """

    tool_id: uuid.UUID
    agent_id: uuid.UUID
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: int = 0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class RateLimitConfig:
    """Rate limit configuration for tool execution.

    Attributes:
        max_calls_per_minute: Maximum invocations per minute per agent.
        max_calls_per_hour: Maximum invocations per hour per agent.
    """

    max_calls_per_minute: int = 60
    max_calls_per_hour: int = 500


class ToolExecutor:
    """Executes tools with permission verification, rate limiting, and audit logging.

    Before executing any tool, the executor verifies the requesting agent
    has access, checks rate limits, executes within a timeout, and logs
    the result for audit purposes.
    """

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        rate_limit: RateLimitConfig | None = None,
        audit_store: Any | None = None,
    ) -> None:
        """Initialize the tool executor.

        Args:
            timeout_seconds: Maximum time for a single tool execution.
            rate_limit: Rate limiting configuration. Uses defaults if None.
            audit_store: Optional ToolAuditStore for recording structured invocations.
        """
        self._timeout_seconds = timeout_seconds
        self._rate_limit = rate_limit or RateLimitConfig()
        self._audit_store = audit_store
        self._call_log: list[tuple[uuid.UUID, uuid.UUID, datetime]] = []
        self._audit_log: list[dict[str, Any]] = []
        # Permission check function can be injected
        self._permission_checker: Callable[
            [uuid.UUID, uuid.UUID], Awaitable[bool]
        ] | None = None

    def set_permission_checker(
        self,
        checker: Callable[[uuid.UUID, uuid.UUID], Awaitable[bool]],
    ) -> None:
        """Set the permission checker function.

        Args:
            checker: Async function(agent_id, tool_id) -> bool.
        """
        self._permission_checker = checker

    async def execute(
        self,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
        arguments: dict[str, Any],
        execute_fn: Callable[[dict[str, Any]], Awaitable[Any]],
        company_id: uuid.UUID | None = None,
    ) -> ToolResult:
        """Execute a tool with full permission and safety checks.

        Performs permission verification, rate limit checking, executes
        the tool within a timeout, and logs the action for audit.

        Args:
            agent_id: The agent requesting execution.
            tool_id: The tool to execute.
            arguments: Arguments to pass to the tool.
            execute_fn: The actual execution function.
            company_id: Company scope for audit logging.

        Returns:
            A ToolResult with the outcome.
        """
        import asyncio

        # Permission check
        if not await self._check_permission(agent_id, tool_id):
            result = ToolResult(
                tool_id=tool_id,
                agent_id=agent_id,
                success=False,
                error="Permission denied: agent lacks access to this tool",
            )
            self._log_audit(agent_id, tool_id, "denied", company_id)
            self._record_invocation(
                agent_id=agent_id,
                tool_id=tool_id,
                company_id=company_id,
                arguments=arguments,
                status="denied",
                duration_ms=0,
                error="Permission denied: agent lacks access to this tool",
            )
            return result

        # Rate limit check
        if not self._check_rate_limit(agent_id, tool_id):
            result = ToolResult(
                tool_id=tool_id,
                agent_id=agent_id,
                success=False,
                error="Rate limit exceeded",
            )
            self._log_audit(agent_id, tool_id, "rate_limited", company_id)
            self._record_invocation(
                agent_id=agent_id,
                tool_id=tool_id,
                company_id=company_id,
                arguments=arguments,
                status="rate_limited",
                duration_ms=0,
                error="Rate limit exceeded",
            )
            return result

        # Execute with timeout
        start = datetime.now(timezone.utc)
        try:
            output = await asyncio.wait_for(
                execute_fn(arguments),
                timeout=self._timeout_seconds,
            )
            elapsed = datetime.now(timezone.utc) - start
            duration_ms = int(elapsed.total_seconds() * 1000)

            result = ToolResult(
                tool_id=tool_id,
                agent_id=agent_id,
                success=True,
                output=output,
                duration_ms=duration_ms,
            )
            self._record_call(agent_id, tool_id)
            self._log_audit(agent_id, tool_id, "success", company_id)
            self._record_invocation(
                agent_id=agent_id,
                tool_id=tool_id,
                company_id=company_id,
                arguments=arguments,
                status="success",
                duration_ms=duration_ms,
            )
            return result

        except asyncio.TimeoutError:
            elapsed = datetime.now(timezone.utc) - start
            duration_ms = int(elapsed.total_seconds() * 1000)
            result = ToolResult(
                tool_id=tool_id,
                agent_id=agent_id,
                success=False,
                error=f"Tool execution timed out after {self._timeout_seconds}s",
                duration_ms=duration_ms,
            )
            self._log_audit(agent_id, tool_id, "timeout", company_id)
            self._record_invocation(
                agent_id=agent_id,
                tool_id=tool_id,
                company_id=company_id,
                arguments=arguments,
                status="timeout",
                duration_ms=duration_ms,
                error=f"Tool execution timed out after {self._timeout_seconds}s",
            )
            return result

        except Exception as exc:
            elapsed = datetime.now(timezone.utc) - start
            duration_ms = int(elapsed.total_seconds() * 1000)
            result = ToolResult(
                tool_id=tool_id,
                agent_id=agent_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
            self._log_audit(agent_id, tool_id, "error", company_id, error=str(exc))
            self._record_invocation(
                agent_id=agent_id,
                tool_id=tool_id,
                company_id=company_id,
                arguments=arguments,
                status="error",
                duration_ms=duration_ms,
                error=str(exc),
            )
            return result

    def _record_invocation(
        self,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
        company_id: uuid.UUID | None,
        arguments: dict[str, Any],
        status: str,
        duration_ms: int = 0,
        error: str | None = None,
    ) -> None:
        """Create and record a ToolInvocation in the audit store if configured.

        Args:
            agent_id: The agent that executed the tool.
            tool_id: The tool that was executed.
            company_id: Company scope for the invocation.
            arguments: Raw arguments (will be scrubbed before storage).
            status: Execution outcome status.
            duration_ms: Execution duration in milliseconds.
            error: Error message, if any.
        """
        if self._audit_store is None or company_id is None:
            return

        now = datetime.now(timezone.utc)
        invocation = ToolInvocation(
            company_id=company_id,
            agent_id=agent_id,
            tool_id=tool_id,
            tool_name="",
            arguments_scrubbed=_scrub_arguments(arguments),
            status=status,
            duration_ms=duration_ms,
            error=error,
            created_at=now,
            completed_at=now if status != "timeout" else None,
        )
        self._audit_store.record(invocation)

    async def _check_permission(
        self, agent_id: uuid.UUID, tool_id: uuid.UUID
    ) -> bool:
        """Verify the agent has permission to use the tool.

        Args:
            agent_id: The requesting agent.
            tool_id: The target tool.

        Returns:
            True if permitted.
        """
        if self._permission_checker:
            return await self._permission_checker(agent_id, tool_id)
        # Default: allow if no checker is configured
        return True

    def _check_rate_limit(
        self, agent_id: uuid.UUID, tool_id: uuid.UUID
    ) -> bool:
        """Check if the agent is within rate limits.

        Args:
            agent_id: The requesting agent.
            tool_id: The target tool.

        Returns:
            True if within limits.
        """
        now = datetime.now(timezone.utc)
        from datetime import timedelta

        # Count calls in last minute
        one_minute_ago = now - timedelta(minutes=1)
        recent_calls = sum(
            1 for aid, tid, ts in self._call_log
            if aid == agent_id and ts > one_minute_ago
        )
        if recent_calls >= self._rate_limit.max_calls_per_minute:
            return False

        # Count calls in last hour
        one_hour_ago = now - timedelta(hours=1)
        hourly_calls = sum(
            1 for aid, tid, ts in self._call_log
            if aid == agent_id and ts > one_hour_ago
        )
        if hourly_calls >= self._rate_limit.max_calls_per_hour:
            return False

        return True

    def _record_call(self, agent_id: uuid.UUID, tool_id: uuid.UUID) -> None:
        """Record a successful tool call for rate limiting.

        Args:
            agent_id: The agent that made the call.
            tool_id: The tool that was called.
        """
        self._call_log.append(
            (agent_id, tool_id, datetime.now(timezone.utc))
        )
        # Trim old entries (keep last 24 hours)
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        self._call_log = [
            (a, t, ts) for a, t, ts in self._call_log if ts > cutoff
        ]

    def _log_audit(
        self,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
        outcome: str,
        company_id: uuid.UUID | None = None,
        error: str | None = None,
    ) -> None:
        """Log a tool execution event for audit purposes.

        Args:
            agent_id: The agent involved.
            tool_id: The tool involved.
            outcome: Result of the execution attempt.
            company_id: Company scope.
            error: Error message, if any.
        """
        entry: dict[str, Any] = {
            "agent_id": str(agent_id),
            "tool_id": str(tool_id),
            "outcome": outcome,
            "company_id": str(company_id) if company_id else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            entry["error"] = error
        self._audit_log.append(entry)

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Retrieve recent audit log entries.

        Args:
            limit: Maximum entries to return.

        Returns:
            List of audit log entry dictionaries.
        """
        return self._audit_log[-limit:]
