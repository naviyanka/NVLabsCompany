"""Policy Evaluation Context - request context builder for policy evaluation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PolicyContext:
    """Full context for evaluating policies against a request.

    Contains all information needed to determine whether an action should
    be allowed, denied, or require approval.

    Attributes:
        actor_type: Type of actor (agent, user, system).
        actor_id: Identifier of the actor making the request.
        resource_type: Type of resource being accessed.
        resource_id: Identifier of the specific resource.
        action: The action being performed.
        timestamp: When the request was made.
        cost: Projected cost of the action in cents.
        environment: Additional environment context (load, incidents, etc.).
        sensitivity_level: Sensitivity level of the resource (low, medium, high, critical).
    """

    actor_type: str = ""
    actor_id: str = ""
    resource_type: str = ""
    resource_id: str = ""
    action: str = ""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    cost: int = 0
    environment: dict[str, Any] = field(default_factory=dict)
    sensitivity_level: str = "low"


class ContextBuilder:
    """Builder for constructing PolicyContext objects.

    Provides a fluent interface for building the full evaluation context
    including actor identity, resource details, action, cost, and environment.
    """

    def __init__(self) -> None:
        """Initialize an empty context builder."""
        self._actor_type: str = ""
        self._actor_id: str = ""
        self._resource_type: str = ""
        self._resource_id: str = ""
        self._sensitivity_level: str = "low"
        self._action: str = ""
        self._cost: int = 0
        self._timestamp: datetime = datetime.now(timezone.utc)
        self._environment: dict[str, Any] = {}

    def with_actor(self, actor_type: str, actor_id: str) -> "ContextBuilder":
        """Set the actor identity.

        Args:
            actor_type: Type of actor (agent, user, system).
            actor_id: Identifier of the actor.

        Returns:
            Self for chaining.
        """
        self._actor_type = actor_type
        self._actor_id = actor_id
        return self

    def with_resource(
        self,
        resource_type: str,
        resource_id: str,
        sensitivity_level: str = "low",
    ) -> "ContextBuilder":
        """Set the resource details.

        Args:
            resource_type: Type of resource being accessed.
            resource_id: Identifier of the specific resource.
            sensitivity_level: Sensitivity level (low, medium, high, critical).

        Returns:
            Self for chaining.
        """
        self._resource_type = resource_type
        self._resource_id = resource_id
        self._sensitivity_level = sensitivity_level
        return self

    def with_action(self, action_name: str) -> "ContextBuilder":
        """Set the action being performed.

        Args:
            action_name: The action name (e.g., deploy, delete, create).

        Returns:
            Self for chaining.
        """
        self._action = action_name
        return self

    def with_cost(self, amount: int) -> "ContextBuilder":
        """Set the projected cost for the action.

        Args:
            amount: Cost in cents.

        Returns:
            Self for chaining.
        """
        self._cost = amount
        return self

    def with_environment(
        self,
        time: datetime | None = None,
        load: float | None = None,
        incidents: list[str] | None = None,
    ) -> "ContextBuilder":
        """Set environment context.

        Args:
            time: Override timestamp (defaults to now).
            load: Current system load (0.0-1.0).
            incidents: List of active incident identifiers.

        Returns:
            Self for chaining.
        """
        if time is not None:
            self._timestamp = time
        if load is not None:
            self._environment["load"] = load
        if incidents is not None:
            self._environment["incidents"] = incidents
        return self

    def build(self) -> PolicyContext:
        """Build the PolicyContext from configured values.

        Returns:
            A fully constructed PolicyContext.
        """
        return PolicyContext(
            actor_type=self._actor_type,
            actor_id=self._actor_id,
            resource_type=self._resource_type,
            resource_id=self._resource_id,
            action=self._action,
            timestamp=self._timestamp,
            cost=self._cost,
            environment=self._environment,
            sensitivity_level=self._sensitivity_level,
        )
