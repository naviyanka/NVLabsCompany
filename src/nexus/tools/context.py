"""The server-side identity behind one governed tool call.

An :class:`ExecutionContext` says who a tool call acts for: the company, the
principal and its RBAC role, the agent, the session, and which request path and
adapter produced it. Only server code builds one: from an authenticated
:class:`~nexus.auth.principal.Principal`, or from an agent row for autonomous
work that has no human behind it. Adapters receive it on the session and pass
it to :func:`nexus.tools.factory.guarded_call`; they never build one from
config, model output or a request body.

The fields are claims until :func:`nexus.tools.access.check_tool_access` has
checked them against the database (the agent and the session must belong to
the company), so a wrong value can only deny.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any

# Request paths. ``INBOUND_MCP`` is an external client calling NEXUS's own
# tools, which is default-deny (see ``nexus.tools.access``).
INBOUND_MCP = "mcp_inbound"


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Company, principal, role, agent and session for one governed call."""

    company_id: uuid.UUID
    principal_id: str
    principal_role: str
    source: str
    agent_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    adapter: str | None = None
    model: str | None = None
    # Set for task-attempt turns: "write" or "read_only". The CLI adapter maps
    # it to the backend's own cataloged permission flags; never model-chosen.
    work_mode: str | None = None

    @classmethod
    def for_principal(
        cls,
        principal: Any,
        *,
        source: str,
        agent_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        adapter: str | None = None,
        model: str | None = None,
    ) -> ExecutionContext:
        """Context for work an authenticated principal started.

        The company and the role come from the principal. A run principal
        names its own agent in its signed token, so a different ``agent_id``
        is refused rather than trusted.

        Raises:
            PermissionError: If a run principal is used for another agent.
        """
        if principal.kind == "run":
            if agent_id is not None and agent_id != principal.agent_id:
                raise PermissionError("run token is for a different agent")
            agent_id = principal.agent_id
            principal_id = f"run:{principal.run_id}"
        elif principal.kind == "service":
            principal_id = principal.display_name
        else:
            principal_id = f"user:{principal.user_id}"
        return cls(
            company_id=principal.company_id,
            principal_id=principal_id,
            principal_role=principal.role,
            source=source,
            agent_id=agent_id,
            session_id=session_id,
            adapter=adapter,
            model=model,
        )

    @classmethod
    def for_agent(
        cls,
        agent: Any,
        *,
        source: str,
        session_id: uuid.UUID | None = None,
        adapter: str | None = None,
        model: str | None = None,
    ) -> ExecutionContext:
        """Context for autonomous work (scheduler, orchestrator, webhooks).

        No human or key is behind the call, so the principal is the agent
        itself with the ``agent`` role, and the company is the agent row's.
        """
        return cls(
            company_id=agent.company_id,
            principal_id=f"agent:{agent.id}",
            principal_role="agent",
            source=source,
            agent_id=agent.id,
            session_id=session_id,
            adapter=adapter or getattr(agent, "adapter_type", None),
            model=model or getattr(agent, "model", None),
        )

    @classmethod
    def for_call(
        cls,
        agent: Any,
        principal: Any,
        *,
        source: str,
        session_id: uuid.UUID | None = None,
        adapter: str | None = None,
        model: str | None = None,
    ) -> ExecutionContext:
        """The authenticated principal's context when there is one, else the agent's.

        Callers that serve an HTTP request must pass its principal; ``None``
        means the work is autonomous. See :meth:`for_principal` for errors.
        """
        if principal is None:
            return cls.for_agent(
                agent, source=source, session_id=session_id, adapter=adapter, model=model
            )
        return cls.for_principal(
            principal,
            source=source,
            agent_id=agent.id,
            session_id=session_id,
            adapter=adapter,
            model=model,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form, for server-to-server hops such as a Temporal activity."""
        return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionContext:
        """Inverse of :meth:`to_dict`. Only for data the server itself produced."""
        ids = ("company_id", "agent_id", "session_id")
        return cls(**{k: uuid.UUID(v) if k in ids and v else v for k, v in data.items()})
