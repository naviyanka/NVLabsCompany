"""Who performed a vault write (ADR 0002 §20 control 9).

Control 9 says audit through the existing path rather than a new log, and the
existing path is ``ToolInvocation`` — which requires a non-null ``agent_id`` and
``tool_id``, both foreign keys. Not every vault write has either. Stamping
``nexus_id`` into frontmatter is the first write the system will make (§17), and
it is an operator-invoked system operation, not an agent capability.

Three ways to resolve that, and the choice matters more than it looks:

1. **A first-class system actor row in ``agents``.** Rejected. It satisfies the
   foreign key by inventing an agent that does not exist, and every query that
   counts agents, bills agents, or shows agents on a dashboard then has to know
   to exclude it. A fake identity is a fact the whole system has to work around.
2. **An actor abstraction on ``ToolInvocation``.** Rejected for now. It means
   making ``agent_id`` nullable on a table with existing rows and existing
   queries that assume it is present — a schema change whose blast radius is
   every audit consumer, for one caller that does not exist yet.
3. **This module: an actor value object, recorded through whatever store the
   action already uses.** Chosen. An agent write is a genuine ``ToolInvocation``
   and stays one. A system or operator write is not a tool invocation at all —
   nobody granted it, no tool ran — and it is recorded on the domain row it
   already touches, plus the application log.

So the actor is modelled once, here, and each store receives the part it can
represent. The abstraction is small on purpose: it exists so an agent write, a
system write and an operator write can be *attributed* consistently, not so a
fourth audit system can grow.

**A write is never anonymous.** There is no default actor: a caller states who is
writing, because "the system did it" is the answer that makes an audit trail
useless.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

# Actor kinds.
ACTOR_AGENT = "agent"
ACTOR_SYSTEM = "system"
ACTOR_OPERATOR = "operator"


class ActorError(Exception):
    """An actor was constructed inconsistently with its kind."""


@dataclass(frozen=True)
class WriteActor:
    """Who is performing a vault write.

    Attributes:
        kind: ``agent``, ``system`` or ``operator``.
        agent_id: The acting agent. Required for an agent actor, and absent for
            the other two — a system write has no agent, and saying it does would
            attribute a human's or the platform's action to a model.
        user_id: The acting human, for an operator actor.
        reason: Why a system actor is writing, e.g. ``"nexus_id stamping"``. A
            system write has no prompt and no grant behind it, so the reason is
            the only thing that explains it later.
    """

    kind: str
    agent_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.kind == ACTOR_AGENT:
            if self.agent_id is None:
                raise ActorError("an agent actor needs an agent_id")
        elif self.kind in (ACTOR_SYSTEM, ACTOR_OPERATOR):
            if self.agent_id is not None:
                # The whole point of the abstraction: a system write must not be
                # recorded as an agent's.
                raise ActorError(f"a {self.kind} actor must not carry an agent_id")
            if self.kind == ACTOR_SYSTEM and not self.reason:
                raise ActorError("a system actor needs a reason")
        else:
            raise ActorError(f"unknown actor kind: {self.kind!r}")

    @classmethod
    def agent(cls, agent_id: uuid.UUID) -> WriteActor:
        """An agent acting through a granted tool."""
        return cls(kind=ACTOR_AGENT, agent_id=agent_id)

    @classmethod
    def system(cls, reason: str) -> WriteActor:
        """The platform itself, e.g. the operator-invoked sync path of §17."""
        return cls(kind=ACTOR_SYSTEM, reason=reason)

    @classmethod
    def operator(cls, user_id: uuid.UUID | None = None) -> WriteActor:
        """A human acting through an operator endpoint."""
        return cls(kind=ACTOR_OPERATOR, user_id=user_id)

    @property
    def is_agent(self) -> bool:
        """Whether per-agent authorization applies to this actor."""
        return self.kind == ACTOR_AGENT

    def audit_fields(self) -> dict[str, str]:
        """Attribution fields safe to persist or log.

        Ids only, never a path and never note content: an audit record is read by
        more people than the note is, and a reason string that carried a vault
        path would put host layout into it.
        """
        fields = {"actor_kind": self.kind}
        if self.agent_id is not None:
            fields["actor_agent_id"] = str(self.agent_id)
        if self.user_id is not None:
            fields["actor_user_id"] = str(self.user_id)
        if self.reason:
            fields["actor_reason"] = self.reason[:200]
        return fields

    def describe(self) -> str:
        """A short attribution string for a log line."""
        if self.kind == ACTOR_AGENT:
            return f"agent {self.agent_id}"
        if self.kind == ACTOR_OPERATOR:
            return f"operator {self.user_id}" if self.user_id else "operator"
        return f"system ({self.reason})"
