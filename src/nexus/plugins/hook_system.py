"""Hook system for NEXUS plugin extensibility.

Provides hook points throughout the NEXUS lifecycle that plugins can
attach handlers to. The HookManager executes handlers with error
isolation so that one failing handler does not prevent others from running.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HookPoint(Enum):
    """Available hook points in the NEXUS system.

    Plugins can register handlers at any of these points to be notified
    of and optionally modify system behavior.

    Attributes:
        pre_task_execute: Before a task begins execution.
        post_task_execute: After a task completes execution.
        pre_tool_call: Before a tool is invoked.
        post_tool_call: After a tool invocation completes.
        on_agent_create: When a new agent is created.
        on_agent_terminate: When an agent is terminated.
    """

    pre_task_execute = "pre_task_execute"
    post_task_execute = "post_task_execute"
    pre_tool_call = "pre_tool_call"
    post_tool_call = "post_tool_call"
    on_agent_create = "on_agent_create"
    on_agent_terminate = "on_agent_terminate"


@dataclass
class HookContext:
    """Context object passed to hook handlers during execution.

    Provides relevant information about the event that triggered
    the hook, allowing handlers to make informed decisions.

    Attributes:
        agent_id: Identifier of the agent involved, if applicable.
        task_id: Identifier of the task involved, if applicable.
        tool_name: Name of the tool being called, if applicable.
        timestamp: UTC datetime when the hook was triggered.
        metadata: Additional arbitrary context data.
    """

    agent_id: str | None = None
    task_id: str | None = None
    tool_name: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _HookHandler:
    """Internal representation of a registered hook handler.

    Attributes:
        callback: The callable to invoke.
        priority: Execution priority (lower numbers execute first).
        name: Identifier for this handler (for unregistration).
    """

    callback: Callable[..., Any]
    priority: int = 0
    name: str = ""


class HookManager:
    """Manages hook registration, unregistration, and execution.

    Handlers are registered per hook point and executed in priority order.
    Error isolation ensures that one handler raising an exception does not
    prevent subsequent handlers from running.
    """

    def __init__(self) -> None:
        """Initialize the HookManager with empty handler registrations."""
        self._handlers: dict[HookPoint, list[_HookHandler]] = {
            point: [] for point in HookPoint
        }

    def register(
        self,
        hook_point: HookPoint,
        callback: Callable[..., Any],
        priority: int = 0,
        name: str = "",
    ) -> None:
        """Register a handler for a specific hook point.

        Args:
            hook_point: The hook point to attach the handler to.
            callback: The callable to invoke when the hook fires.
            priority: Execution priority (lower values execute first).
            name: Optional name for identifying the handler.
        """
        handler = _HookHandler(callback=callback, priority=priority, name=name)
        self._handlers[hook_point].append(handler)
        # Keep handlers sorted by priority
        self._handlers[hook_point].sort(key=lambda h: h.priority)

    def unregister(self, hook_point: HookPoint, name: str) -> bool:
        """Unregister a named handler from a hook point.

        Args:
            hook_point: The hook point to remove the handler from.
            name: The name of the handler to remove.

        Returns:
            True if a handler was removed, False if not found.
        """
        original_count = len(self._handlers[hook_point])
        self._handlers[hook_point] = [
            h for h in self._handlers[hook_point] if h.name != name
        ]
        return len(self._handlers[hook_point]) < original_count

    def unregister_all(self, name: str) -> int:
        """Unregister all handlers with a given name from all hook points.

        Args:
            name: The handler name to remove across all hook points.

        Returns:
            Total number of handlers removed.
        """
        removed = 0
        for hook_point in HookPoint:
            original_count = len(self._handlers[hook_point])
            self._handlers[hook_point] = [
                h for h in self._handlers[hook_point] if h.name != name
            ]
            removed += original_count - len(self._handlers[hook_point])
        return removed

    def execute(self, hook_point: HookPoint, context: HookContext) -> list[Any]:
        """Execute all handlers for a hook point with error isolation.

        Each handler is called in priority order. If a handler raises an
        exception, the error is logged but execution continues with the
        remaining handlers.

        Args:
            hook_point: The hook point to execute.
            context: The context to pass to each handler.

        Returns:
            List of results from handlers that executed successfully.
        """
        results: list[Any] = []
        for handler in self._handlers[hook_point]:
            try:
                result = handler.callback(context)
                results.append(result)
            except Exception as exc:
                logger.error(
                    "Hook handler '%s' for %s raised an error: %s",
                    handler.name or "<unnamed>",
                    hook_point.value,
                    exc,
                )
        return results

    def get_handler_count(self, hook_point: HookPoint) -> int:
        """Get the number of handlers registered for a hook point.

        Args:
            hook_point: The hook point to query.

        Returns:
            Number of registered handlers.
        """
        return len(self._handlers[hook_point])
