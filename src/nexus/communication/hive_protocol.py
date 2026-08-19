"""Hive Protocol - FIPA-lite message schema for multi-agent coordination."""

import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

HOP_CAP = 12  # Max hops before livelock prevention kicks in


class MessageAct(str, Enum):
    """Speech acts for agent-to-agent communication (FIPA-lite)."""

    REQUEST = "request"
    INFORM = "inform"
    PROPOSE = "propose"
    QUERY = "query"
    AGREE = "agree"
    REFUSE = "refuse"
    DONE = "done"


# Only these acts obligate a reply - prevents livelock
REPLY_OBLIGATING_ACTS: frozenset[str] = frozenset(
    [MessageAct.REQUEST, MessageAct.QUERY, MessageAct.PROPOSE]
)


def requires_reply_for_act(act: MessageAct) -> bool:
    """Return True if this message act obligates a reply."""
    return act in REPLY_OBLIGATING_ACTS


class HiveMessage(BaseModel):
    """A single message in the hive protocol."""

    id: str = Field(default_factory=lambda: secrets.token_hex(12))
    conversation: str
    in_reply_to: Optional[str] = None
    from_agent: str
    to_agent: str  # agent_id, "god", "broadcast", or "human"
    act: MessageAct
    subject: str
    body: str
    hops: int = 0
    requires_reply: bool = False
    needs_human: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentStatus(str, Enum):
    """Status of an agent in the hive."""

    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    GONE = "gone"


class HiveAgentMeta(BaseModel):
    """Metadata for a registered hive agent."""

    id: str
    name: str
    provider: Optional[str] = None
    role: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    cwd: str = ""
    is_god: bool = False
    status: AgentStatus = AgentStatus.IDLE
    last_seen: float = 0.0
    archived: bool = False
