"""The CEO: who it is, what it knows at the start of a turn, and what it remembers.

**Designation.** ``Agent.is_ceo``, at most one per company (a partial unique
index). Only a human administrator appoints, replaces or removes the CEO;
role, title, adapter configuration and prompt text never grant it. Every check
reads the column when it runs, so a replaced CEO loses its executive context
and its tools on its next turn or tool call. The CEO is the root of the
hierarchy: appointing it detaches it from any manager and attaches every other
root to it.

**Executive context.** A bounded, deterministic text block for each CEO chat
turn, built from the latest stored organization snapshot (two indexed
lookups) and one bounded executive-memory query. No live aggregation, no CLI
or LLM call. The snapshot is authoritative for status; memory records what was
said, decided or promised, and is labelled as such.

**Executive memory.** ``MemoryRecord`` rows with scope ``executive``: company
memory that survives a change of CEO and records which CEO each entry belongs
to. Agents' own memory retrieval never reads this scope, so only the current
CEO's executive context and CEO tools see it. Secrets are redacted before
anything is stored.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.memory import MemoryRecord
from nexus.services import manager_service as ms
from nexus.services import org_snapshot

EXECUTIVE_SCOPE = "executive"
MemoryType = Literal[
    "directive", "decision", "delegation", "commitment", "hiring", "risk", "outcome"
]
ACTIVE, SUPERSEDED, RESOLVED = "active", "superseded", "resolved"
CONTENT_MAX = 2000
# Retrieval reads at most this many rows, newest first; searches return fewer.
MEMORY_POOL = 50
SEARCH_MAX = 25
# Context caps: fixed counts per section, then a hard character cap.
CONTEXT_MANAGERS = 8
CONTEXT_ATTENTION = 5
CONTEXT_APPROVALS = 5
CONTEXT_MEMORY = 12
CONTEXT_LINE_MAX = 240
CONTEXT_MAX_CHARS = 6000
TRUNCATED = "\n[executive context truncated]"
# The CEO's chat instructions. They describe the designation; they grant
# nothing: authority is only the governed tools a turn is actually given.
CHAT_DIRECTIVE = (
    "You are this company's designated CEO. Answer company status from the "
    "EXECUTIVE CONTEXT below; where executive memory disagrees with the snapshot, "
    "the snapshot wins, and say when the snapshot is stale or failed. You act only "
    "through governed CEO tools when this turn has them; otherwise recommend "
    "actions for a human and never claim an action you did not take. You cannot "
    "approve requests, change policies or permissions, read secrets, or create agents."
)

_SECRETS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
                re.S), "[REDACTED]"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED]"),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)(\s*[:=]\s*)\S+"),
     r"\1\2[REDACTED]"),
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def redact(text: str) -> tuple[str, bool]:
    """``text`` with credential-shaped values replaced, and whether any were."""
    out = text
    for pattern, repl in _SECRETS:
        out = pattern.sub(repl, out)
    return out, out != text


# --- designation --------------------------------------------------------------


def dev_fallback(principal: Any) -> bool:
    """The ``AUTH_ENABLED=false`` development principal: keyless, unlabelled service admin."""
    return (
        not settings.auth_enabled
        and principal.kind == "service"
        and principal.api_key_id is None
        and not principal.label
    )


def is_human(principal: Any) -> bool:
    """A person: a user session, or the auth-disabled development fallback."""
    return principal.kind == "user" or dev_fallback(principal)


def require_owner(principal: Any) -> None:
    """Only a human administrator changes who the CEO is."""
    if principal.role != "admin" or not is_human(principal):
        raise ms._error(
            403, "CEO_APPOINTMENT_FORBIDDEN",
            "Only a human administrator may appoint, replace or remove the CEO",
        )


async def current_ceo(db: Any, company_id: uuid.UUID) -> Agent | None:
    return (
        await db.execute(
            select(Agent).where(Agent.company_id == company_id, Agent.is_ceo == True)  # noqa: E712
        )
    ).scalar_one_or_none()


async def is_ceo(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID | None) -> bool:
    if agent_id is None:
        return False
    return (
        await db.execute(
            select(Agent.id).where(
                Agent.id == agent_id, Agent.company_id == company_id,
                Agent.is_ceo == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none() is not None


async def require_ceo(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID | None) -> None:
    if not await is_ceo(db, company_id, agent_id):
        raise ms._error(403, "NOT_CEO", "Only the company's current CEO may do this")


async def appoint(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID, principal: Any) -> dict:
    """Make ``agent_id`` the CEO, replacing any other. Idempotent. Commits.

    The CEO stops reporting to anyone, and every other root agent starts
    reporting to it; each reporting change is audited like a manual one.
    """
    from nexus.realtime.publish import TOPOLOGY_CHANNEL, publish_event

    require_owner(principal)
    actor = principal.display_name
    agent = await ms.get_agent(db, company_id, agent_id)
    if agent.status == "terminated":
        raise ms._error(409, "AGENT_NOT_ACTIVE", "A terminated agent cannot be the CEO")
    previous = await current_ceo(db, company_id)
    if previous is not None and previous.id == agent.id:
        return await status(db, company_id)
    now = _now()
    if previous is not None:
        previous.is_ceo = False
        previous.updated_at = now
        await db.flush()  # free the company's one CEO slot first
    changes: list[dict[str, Any]] = []
    if agent.manager_id is not None:
        changes.append({"agent_id": str(agent.id), "previous_manager_id": str(agent.manager_id),
                        "manager_id": None})
        agent.manager_id = None
    agent.is_ceo = True
    agent.updated_at = now
    await db.flush()
    roots = (
        await db.execute(
            select(Agent)
            .where(Agent.company_id == company_id, Agent.manager_id.is_(None),
                   Agent.id != agent.id, Agent.status != "terminated")
            .order_by(Agent.name, Agent.id)
        )
    ).scalars().all()
    for root in roots:
        root.manager_id = agent.id
        root.updated_at = now
        changes.append({"agent_id": str(root.id), "previous_manager_id": None,
                        "manager_id": str(agent.id)})
    await db.flush()
    for change in changes:
        await ms.audit(db, company_id, "agent.manager_changed", actor, "agent",
                       uuid.UUID(change["agent_id"]), **change, reason="ceo_root")
    await ms.audit(
        db, company_id,
        "organization.ceo_replaced" if previous else "organization.ceo_appointed",
        actor, "agent", agent.id,
        ceo_id=agent.id, previous_ceo_id=previous.id if previous else None,
    )
    await db.commit()
    for change in changes:
        await publish_event(TOPOLOGY_CHANNEL, "agent.manager_changed", company_id, change)
    await publish_event(TOPOLOGY_CHANNEL, "organization.ceo_changed", company_id, {
        "ceo_id": str(agent.id), "previous_ceo_id": previous and str(previous.id),
    })
    return await status(db, company_id)


async def remove(db: Any, company_id: uuid.UUID, principal: Any) -> dict:
    """Clear the designation; the hierarchy stays as it is. Commits."""
    from nexus.realtime.publish import TOPOLOGY_CHANNEL, publish_event

    require_owner(principal)
    ceo = await current_ceo(db, company_id)
    if ceo is None:
        raise ms._error(404, "NO_CEO", "The company has no CEO")
    ceo.is_ceo = False
    ceo.updated_at = _now()
    await ms.audit(db, company_id, "organization.ceo_removed", principal.display_name,
                   "agent", ceo.id, previous_ceo_id=ceo.id)
    await db.commit()
    await publish_event(TOPOLOGY_CHANNEL, "organization.ceo_changed", company_id, {
        "ceo_id": None, "previous_ceo_id": str(ceo.id),
    })
    return await status(db, company_id)


def tool_support(agent: Agent) -> tuple[bool, str | None]:
    """Whether the CEO's backend can run with its governed tools, and why not.

    Only a CLI backend with an execution-scoped MCP config flag can. The Hermes
    CLI has none: it reads MCP servers only from its persistent config, which
    Nexus never writes.
    """
    from nexus.adapters.cli_registry import get_cli_registry

    backend = org_snapshot._backend(agent)
    if agent.adapter_type == "cli":
        registry = get_cli_registry()
        info = registry.get_backend(registry.resolve_backend_id(backend))
        if info is not None and info.mcp_config_flag:
            return True, None
    return False, (
        f"CEO_TOOLS_UNSUPPORTED: {backend} cannot load an execution-scoped MCP server; "
        "the CEO chats with its executive context but without governed tools."
    )


async def status(db: Any, company_id: uuid.UUID) -> dict[str, Any]:
    """The CEO, its backend and tool availability, snapshot freshness, memory, approvals."""
    ceo = await current_ceo(db, company_id)
    snap = await org_snapshot.read(db, company_id)
    payload = snap["snapshot"] or {}
    available, reason = tool_support(ceo) if ceo else (False, None)
    return {
        "company_id": str(company_id),
        "ceo": ceo and {**ms.agent_ref(ceo), "backend": org_snapshot._backend(ceo)},
        "ceo_tools_available": available,
        "ceo_tools_unavailable_reason": reason,
        "snapshot": {k: snap[k] for k in (
            "version", "generated_at", "payload_hash", "freshness", "last_refresh_error")},
        "pending_approvals": (payload.get("approvals") or {}).get("items", []),
        "memory": [entry_view(r) for r in await recall(db, company_id, limit=10)],
    }


# --- executive memory ---------------------------------------------------------


class MemoryEntry(BaseModel):
    """What may be recorded. Identity, source and integrity are set by the server."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: MemoryType
    content: str = Field(min_length=1, max_length=CONTENT_MAX)
    refs: dict[str, uuid.UUID] = Field(default_factory=dict, max_length=8)
    supersedes: uuid.UUID | None = None
    resolves: uuid.UUID | None = None


def entry_view(record: MemoryRecord) -> dict[str, Any]:
    meta = record.record_metadata or {}
    return {
        "id": str(record.id),
        "type": meta.get("type"),
        "content": record.content,
        "status": meta.get("status", ACTIVE),
        "ceo_id": meta.get("ceo_id"),
        "recorded_by": meta.get("recorded_by"),
        "source": meta.get("source"),
        "refs": meta.get("refs", {}),
        "supersedes": meta.get("supersedes"),
        "superseded_by": meta.get("superseded_by"),
        "resolved_at": meta.get("resolved_at"),
        "content_sha256": meta.get("content_sha256"),
        "redacted": meta.get("redacted", False),
        "created_at": ms._iso(record.created_at),
    }


async def _entry(db: Any, company_id: uuid.UUID, entry_id: uuid.UUID) -> MemoryRecord:
    record = (
        await db.execute(
            select(MemoryRecord).where(
                MemoryRecord.id == entry_id, MemoryRecord.company_id == company_id,
                MemoryRecord.scope == EXECUTIVE_SCOPE,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise ms._error(404, "MEMORY_NOT_FOUND", f"Executive memory {entry_id} not found")
    return record


def _close(record: MemoryRecord, state: str, now: datetime, by: uuid.UUID) -> None:
    meta = dict(record.record_metadata or {})
    meta["status"] = state
    meta["superseded_by" if state == SUPERSEDED else "resolved_by"] = str(by)
    if state == RESOLVED:
        meta["resolved_at"] = ms._iso(now)
    record.record_metadata = meta  # reassign: the JSON column is not mutation-tracked
    record.updated_at = now


async def remember(
    db: Any,
    company_id: uuid.UUID,
    entry: MemoryEntry,
    *,
    recorded_by: str,
    origin: str,
    source: dict[str, Any] | None = None,
) -> MemoryRecord:
    """Store one entry for the company's current CEO. Flushes; the caller commits.

    ``supersedes`` marks an earlier entry superseded, ``resolves`` marks one
    resolved (a follow-up done). Neither deletes anything.
    """
    ceo = await current_ceo(db, company_id)
    if ceo is None:
        raise ms._error(409, "NO_CEO", "Executive memory belongs to a CEO; appoint one first")
    content, redacted = redact(entry.content)
    now = _now()
    record = MemoryRecord(
        id=uuid.uuid4(),
        company_id=company_id,
        agent_id=ceo.id,
        scope=EXECUTIVE_SCOPE,
        scope_id=company_id,
        content=content,
        importance=1.0,
        created_at=now,
        updated_at=now,
        record_metadata={
            "type": entry.type,
            "status": ACTIVE,
            "ceo_id": str(ceo.id),
            "recorded_by": recorded_by,
            "origin": origin,
            "source": {k: str(v) for k, v in (source or {}).items() if v is not None},
            "refs": {k: str(v) for k, v in sorted(entry.refs.items())},
            "supersedes": entry.supersedes and str(entry.supersedes),
            "resolves": entry.resolves and str(entry.resolves),
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "redacted": redacted,
        },
    )
    for target, state in ((entry.supersedes, SUPERSEDED), (entry.resolves, RESOLVED)):
        if target is not None:
            earlier = await _entry(db, company_id, target)
            # Only a human may close what a human said.
            if origin != "human" and earlier.record_metadata.get("origin") == "human":
                raise ms._error(403, "HUMAN_ENTRY_PROTECTED",
                                "Only a human may supersede or resolve a human entry")
            _close(earlier, state, now, record.id)
    db.add(record)
    await db.flush()
    await ms.audit(db, company_id, "ceo.memory_recorded", recorded_by, "memory", record.id,
                   type=entry.type, ceo_id=ceo.id, origin=origin, redacted=redacted,
                   supersedes=entry.supersedes, resolves=entry.resolves)
    return record


async def recall(
    db: Any,
    company_id: uuid.UUID,
    *,
    query: str | None = None,
    type: str | None = None,
    include_closed: bool = False,
    limit: int = SEARCH_MAX,
) -> list[MemoryRecord]:
    """Newest first, one bounded query; only this company's executive scope."""
    stmt = select(MemoryRecord).where(
        MemoryRecord.company_id == company_id, MemoryRecord.scope == EXECUTIVE_SCOPE
    )
    if query:
        stmt = stmt.where(MemoryRecord.content.ilike(f"%{query[:200]}%"))
    rows = (
        await db.execute(
            stmt.order_by(MemoryRecord.created_at.desc(), MemoryRecord.id.desc()).limit(MEMORY_POOL)
        )
    ).scalars().all()
    out = [
        r for r in rows
        if (type is None or (r.record_metadata or {}).get("type") == type)
        and (include_closed or (r.record_metadata or {}).get("status", ACTIVE) == ACTIVE)
    ]
    return out[: max(1, min(limit, SEARCH_MAX))]


# --- executive context --------------------------------------------------------


def _line(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= CONTEXT_LINE_MAX else text[: CONTEXT_LINE_MAX - 1] + "…"


def _snapshot_facts(payload: dict[str, Any]) -> dict[str, str]:
    """Current state by id, for annotating memory: tasks by bucket, agents by status."""
    facts = {e["id"]: f"employee {e['status']}" for e in payload["employees"]["list"]}
    for bucket, items in payload["work"]["items"].items():
        for item in items:
            facts[item["id"]] = f"task {bucket}"
    for result in payload["work"]["latest_results"]:
        facts.setdefault(result["task_id"], f"task {result['status']}")
    for hire in payload["hiring"]["requests"]:
        facts[hire["id"]] = f"hiring request {hire['state']}"
    return facts


def render_context(snap: dict[str, Any], memory: list[MemoryRecord]) -> str:
    """The executive context text: deterministic for the same inputs, capped in size."""
    payload = snap.get("snapshot")
    fresh = snap["freshness"]
    lines = ["EXECUTIVE CONTEXT (server-provided; authoritative for company status)"]
    if payload is None:
        lines.append("Organization snapshot: NONE YET. Say that status is unknown; do not guess.")
    else:
        label = {"fresh": "FRESH", "stale": "STALE", "rebuilding": "REBUILDING",
                 "failed_refresh": "FAILED REFRESH"}.get(fresh["status"], fresh["status"].upper())
        lines.append(
            f"Organization snapshot v{snap['version']} hash {str(snap['payload_hash'])[:12]} "
            f"generated_at {snap['generated_at']} data_as_of {snap['data_as_of']} "
            f"freshness {label}"
        )
        if fresh["status"] != "fresh":
            lines.append(
                f"WARNING: the snapshot is {label}; say so when reporting status "
                f"(age {fresh['age_seconds']}s)."
            )
    if snap.get("last_refresh_error"):
        err = snap["last_refresh_error"]
        lines.append(_line(f"Last refresh error at {err['at']}: {err['message']}"))
    if payload is not None:
        lines.append("Summary: " + _line(payload["summary"]["text"]))
        attention = payload["summary"]["attention"][:CONTEXT_ATTENTION]
        if attention:
            lines.append("Needs attention:")
            lines += [f"- {_line(a)}" for a in attention]
        names = {e["id"]: e["name"] for e in payload["employees"]["list"]}
        managers = payload["hierarchy"]["managers"]
        lines.append(f"Managers ({len(managers)}):")
        for m in managers[:CONTEXT_MANAGERS]:
            w = m["work"]
            lines.append(_line(
                f"- {m['name']} ({m['id']}): {m['direct_reports']} report(s); "
                f"{w['active']} active, {w['queued']} queued, {w['stale']} stale, "
                f"{w['completed']} completed, {w['failed']} failed, {w['blocked']} blocked"
            ))
        if len(managers) > CONTEXT_MANAGERS:
            lines.append(f"- … {len(managers) - CONTEXT_MANAGERS} more")
        approvals = payload["approvals"]
        lines.append(f"Pending human approvals: {approvals['pending']}")
        for a in approvals["items"][:CONTEXT_APPROVALS]:
            who = names.get(a["requested_by_agent_id"] or "", a["requested_by_agent_id"])
            lines.append(_line(
                f"- {a['type']} {a['id']} requested by {who}, amount_cents {a['amount_cents']}"
            ))
    facts = _snapshot_facts(payload) if payload else {}
    lines.append(
        "Executive memory (what was directed, decided or promised; NOT status — "
        "where it disagrees with the snapshot, the snapshot wins):"
    )
    if not memory:
        lines.append("- none")
    for r in memory[:CONTEXT_MEMORY]:
        meta = r.record_metadata or {}
        now_facts = sorted(
            f"{k}={facts[v]}" for k, v in (meta.get("refs") or {}).items() if v in facts
        )
        note = f" [snapshot v{snap['version']}: {', '.join(now_facts)}]" if now_facts else ""
        lines.append(_line(
            f"- {ms._iso(r.created_at)} {meta.get('type')} {r.id}: {r.content}"
        ) + note)
    text = "\n".join(lines)
    if len(text) > CONTEXT_MAX_CHARS:
        text = text[: CONTEXT_MAX_CHARS - len(TRUNCATED)] + TRUNCATED
    return text


async def executive_context(db: Any, company_id: uuid.UUID) -> str:
    """Three indexed queries: the snapshot, its state, and bounded executive memory."""
    snap = await org_snapshot.read(db, company_id)
    return render_context(snap, await recall(db, company_id, limit=CONTEXT_MEMORY))


async def chat_context(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
    """The CEO's per-turn system-prompt addition; None for any other agent."""
    if not await is_ceo(db, company_id, agent_id):
        return None
    return f"{CHAT_DIRECTIVE}\n\n{await executive_context(db, company_id)}"
