"""The CEO: who it is, what it knows at the start of a turn, and what it remembers.

**Designation.** ``Agent.is_ceo``, at most one per company (a partial unique
index). Only a human administrator appoints, replaces or removes the CEO;
role, title, adapter configuration and prompt text never grant it. Every check
reads the column when it runs, so a replaced CEO loses its executive context
and its tools on its next turn or tool call.

**Hierarchy.** While a company has a CEO it is the only root: appointing it
attaches every other root to it, every agent-creation path and every manager
change goes through :func:`resolve_manager` (an explicit valid manager is kept,
otherwise the CEO), and a replacement moves the former CEO and its direct
reports under the new one. Removal makes the removed CEO's reports roots.
Designation changes and placements are serialized per company.

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
from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError

from nexus.config import settings
from nexus.memory.safety import MemoryRejected, render_memory_data, sanitize_value
from nexus.models.agent import Agent
from nexus.models.memory import PROMPT_STATUSES, MemoryRecord
from nexus.services import manager_service as ms
from nexus.services import org_snapshot

EXECUTIVE_SCOPE = "executive"
MemoryType = Literal[
    "directive", "decision", "delegation", "commitment", "hiring", "risk", "outcome"
]
ACTIVE, SUPERSEDED, RESOLVED = "active", "superseded", "resolved"
CONTENT_MAX = 2000
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
        settings.auth_bypass_active
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


async def lock_hierarchy(db: Any, company_id: uuid.UUID) -> None:
    """Serialize this company's CEO changes and agent placements until the transaction ends.

    On SQLite the no-op write takes the database write lock.
    """
    from nexus.models.company import Company

    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"org-hierarchy:{company_id}"},
        )
    else:
        await db.execute(
            update(Company).where(Company.id == company_id).values(updated_at=Company.updated_at)
        )


async def resolve_manager(
    db: Any, company_id: uuid.UUID, agent_id: uuid.UUID | None, manager_id: uuid.UUID | None
) -> uuid.UUID | None:
    """The manager ``agent_id`` gets when ``manager_id`` is requested (None: none named).

    ``agent_id`` is None for an agent not created yet.

    An explicit manager must be another agent of the same company that does not
    report, directly or not, to ``agent_id``. With none named, the CEO while
    there is one, since it is then the only root. The CEO itself reports to no
    one. Takes the hierarchy lock; call it before adding a new agent.
    """
    await lock_hierarchy(db, company_id)
    ceo = await current_ceo(db, company_id)
    if ceo is not None and ceo.id == agent_id:
        if manager_id is not None:
            raise ms._error(409, "CEO_IS_ROOT", "The CEO reports to no one")
        return None
    if manager_id is None:
        return ceo.id if ceo else None
    if manager_id == agent_id:
        raise ms._error(409, "MANAGER_CYCLE", "An agent cannot report to itself")
    found = (
        await db.execute(
            select(Agent.id).where(Agent.id == manager_id, Agent.company_id == company_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise ms._error(404, "MANAGER_NOT_FOUND", "Manager not found")
    # Walk up from the manager: meeting the agent means a cycle.
    cursor: uuid.UUID | None = manager_id
    seen: set[uuid.UUID] = set()
    while cursor is not None and cursor not in seen:
        if cursor == agent_id:
            raise ms._error(409, "MANAGER_CYCLE",
                            "An agent cannot report to itself or to one of its reports")
        seen.add(cursor)
        cursor = (
            await db.execute(
                select(Agent.manager_id).where(Agent.id == cursor, Agent.company_id == company_id)
            )
        ).scalar_one_or_none()
    return manager_id


async def release_reports(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """Before ``agent_id`` is deleted: its reports go to the CEO, or become roots."""
    await lock_hierarchy(db, company_id)
    ceo = await current_ceo(db, company_id)
    target = ceo.id if ceo is not None and ceo.id != agent_id else None
    await db.execute(
        update(Agent)
        .where(Agent.company_id == company_id, Agent.manager_id == agent_id)
        .values(manager_id=target)
    )


def _conflict() -> Exception:
    return ms._error(409, "CEO_CONFLICT",
                     "The company's CEO changed meanwhile; reload and retry")


async def appoint(
    db: Any, company_id: uuid.UUID, agent_id: uuid.UUID, principal: Any,
    replaces: uuid.UUID | None = None,
) -> dict:
    """Make ``agent_id`` the CEO. Idempotent. Commits.

    ``replaces`` must name the current CEO (None when there is none), so of two
    racing appointments the loser gets a deterministic ``CEO_CONFLICT``. The
    CEO stops reporting to anyone; every other live root, the former CEO and
    its direct reports start reporting to it, so the former CEO keeps no
    reports and with them no manager tools. Each move is audited like a manual
    one.
    """
    from nexus.realtime.publish import TOPOLOGY_CHANNEL, publish_event

    require_owner(principal)
    actor = principal.display_name
    await lock_hierarchy(db, company_id)
    agent = await ms.get_agent(db, company_id, agent_id)
    if agent.status == "terminated":
        raise ms._error(409, "AGENT_NOT_ACTIVE", "A terminated agent cannot be the CEO")
    previous = await current_ceo(db, company_id)
    if previous is not None and previous.id == agent.id:
        return await status(db, company_id)
    if (previous.id if previous else None) != replaces:
        raise _conflict()
    now = _now()
    changes: list[dict[str, Any]] = []

    def move(target: Agent, manager_id: uuid.UUID | None) -> None:
        changes.append({"agent_id": str(target.id),
                        "previous_manager_id": target.manager_id and str(target.manager_id),
                        "manager_id": manager_id and str(manager_id)})
        target.manager_id = manager_id
        target.updated_at = now

    try:
        if previous is not None:
            previous.is_ceo = False
            previous.updated_at = now
            await db.flush()  # free the company's one CEO slot first
        if agent.manager_id is not None:
            move(agent, None)
        agent.is_ceo = True
        agent.updated_at = now
        await db.flush()
    except IntegrityError:
        # Only without the lock (it serializes this): the index still holds one CEO.
        await db.rollback()
        raise _conflict() from None
    # Every other live root, and everyone who reported to the former CEO.
    live_root = Agent.manager_id.is_(None) & (Agent.status != "terminated")
    joining = live_root if previous is None else or_(live_root, Agent.manager_id == previous.id)
    rows = (
        await db.execute(
            select(Agent)
            .where(Agent.company_id == company_id, Agent.id != agent.id, joining)
            .order_by(Agent.name, Agent.id)
        )
    ).scalars().all()
    former_reports = sum(1 for r in rows if previous is not None and r.manager_id == previous.id)
    for row in rows:
        move(row, agent.id)
    await db.flush()
    for change in changes:
        await ms.audit(db, company_id, "agent.manager_changed", actor, "agent",
                       uuid.UUID(change["agent_id"]), **change, reason="ceo_root")
    await ms.audit(
        db, company_id,
        "organization.ceo_replaced" if previous else "organization.ceo_appointed",
        actor, "agent", agent.id,
        ceo_id=agent.id, previous_ceo_id=previous.id if previous else None,
        reparented=len(rows), former_ceo_reports=former_reports,
    )
    await db.commit()
    for change in changes:
        await publish_event(TOPOLOGY_CHANNEL, "agent.manager_changed", company_id, change)
    await publish_event(TOPOLOGY_CHANNEL, "organization.ceo_changed", company_id, {
        "ceo_id": str(agent.id), "previous_ceo_id": previous and str(previous.id),
    })
    return await status(db, company_id)


async def remove(db: Any, company_id: uuid.UUID, principal: Any) -> dict:
    """Clear the designation; the removed CEO's direct reports become roots. Commits.

    Agents, work and executive memory are kept.
    """
    from nexus.realtime.publish import TOPOLOGY_CHANNEL, publish_event

    require_owner(principal)
    actor = principal.display_name
    await lock_hierarchy(db, company_id)
    ceo = await current_ceo(db, company_id)
    if ceo is None:
        raise ms._error(404, "NO_CEO", "The company has no CEO")
    now = _now()
    ceo.is_ceo = False
    ceo.updated_at = now
    reports = (
        await db.execute(
            select(Agent)
            .where(Agent.company_id == company_id, Agent.manager_id == ceo.id)
            .order_by(Agent.name, Agent.id)
        )
    ).scalars().all()
    changes = [{"agent_id": str(r.id), "previous_manager_id": str(ceo.id), "manager_id": None}
               for r in reports]
    for report in reports:
        report.manager_id = None
        report.updated_at = now
    await db.flush()
    for change in changes:
        await ms.audit(db, company_id, "agent.manager_changed", actor, "agent",
                       uuid.UUID(change["agent_id"]), **change, reason="ceo_removed")
    await ms.audit(db, company_id, "organization.ceo_removed", actor, "agent", ceo.id,
                   previous_ceo_id=ceo.id, released_roots=len(reports))
    await db.commit()
    for change in changes:
        await publish_event(TOPOLOGY_CHANNEL, "agent.manager_changed", company_id, change)
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
    if agent.adapter_type == "hermes-native":
        from nexus.adapters import hermes_provider

        reason = hermes_provider.unavailable_reason()
        return (True, None) if reason is None else (False, f"CEO_TOOLS_UNSUPPORTED: {reason}")
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
    native = None
    if ceo is not None and ceo.adapter_type == "hermes-native":
        from nexus.adapters import hermes_provider

        native = hermes_provider.status()
    return {
        "company_id": str(company_id),
        "ceo": ceo and {**ms.agent_ref(ceo), "backend": org_snapshot._backend(ceo)},
        "ceo_tools_available": available,
        "ceo_tools_unavailable_reason": reason,
        "hermes_native": native,
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


def _view_status(record: MemoryRecord) -> str:
    """The column is the lifecycle truth; metadata only names *how* an archived entry closed."""
    if record.status == "archived":
        return RESOLVED if (record.record_metadata or {}).get("status") == RESOLVED else "archived"
    return record.status


def entry_view(record: MemoryRecord) -> dict[str, Any]:
    meta = record.record_metadata or {}
    return {
        "id": str(record.id),
        "type": meta.get("type"),
        "content": record.content,
        "status": _view_status(record),
        "ceo_id": meta.get("ceo_id"),
        "recorded_by": meta.get("recorded_by"),
        "source": meta.get("source"),
        "refs": meta.get("refs", {}),
        "supersedes": meta.get("supersedes"),
        "superseded_by": meta.get("superseded_by"),
        "resolved_at": meta.get("resolved_at"),
        "content_sha256": record.content_hash,
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

    Goes through the canonical ingest path. ``supersedes`` appends the entry as the
    successor of an earlier one and marks that one superseded; ``resolves`` marks one
    resolved (a follow-up done), which archives it. Neither deletes anything, and the
    same entry from the same turn is recorded once.
    """
    from nexus.memory.ingest import (
        MemoryContext,
        MemoryInput,
        MemoryOpError,
        Origin,
        executive_source,
        http_error,
        ingest_memory,
    )
    from nexus.memory.lifecycle import archive_memory, supersede_memory

    ceo = await current_ceo(db, company_id)
    if ceo is None:
        raise ms._error(409, "NO_CEO", "Executive memory belongs to a CEO; appoint one first")
    try:
        source_meta, source_hit = sanitize_value(
            {k: str(v) for k, v in (source or {}).items() if v is not None}
        )
        refs_meta, refs_hit = sanitize_value({k: str(v) for k, v in sorted(entry.refs.items())})
    except MemoryRejected as exc:
        raise ms._error(422, exc.code, str(exc)) from exc

    for target in (entry.supersedes, entry.resolves):
        if target is not None:
            earlier = await _entry(db, company_id, target)
            # Only a human may close what a human said.
            if origin != "human" and (earlier.record_metadata or {}).get("origin") == "human":
                raise ms._error(403, "HUMAN_ENTRY_PROTECTED",
                                "Only a human may supersede or resolve a human entry")

    source_type, source_id = executive_source(source_meta)
    item = MemoryInput(
        scope=EXECUTIVE_SCOPE,
        content=entry.content,
        memory_type=entry.type,
        agent_id=ceo.id,
        scope_id=company_id,
        importance=1.0,
        content_max=CONTENT_MAX,
        source_type=source_type,
        source_id=source_id,
        extractor_version="ceo-memory-v1",
        # The same turn saying the same thing about the same things is one entry.
        item_key=hashlib.sha256(
            repr((entry.type, sorted(refs_meta.items()), str(entry.supersedes),
                  str(entry.resolves))).encode()
        ).hexdigest()[:32],
        server_metadata={
            "type": entry.type,
            "status": ACTIVE,
            "ceo_id": str(ceo.id),
            "source": source_meta,
            "refs": refs_meta,
            "supersedes": entry.supersedes and str(entry.supersedes),
            "resolves": entry.resolves and str(entry.resolves),
        },
    )
    ctx = MemoryContext(company_id, recorded_by)
    kind = Origin.HUMAN if origin == "human" else Origin.TOOL
    try:
        if entry.supersedes is not None:
            result = await supersede_memory(
                db, ctx, entry.supersedes, item, kind,
                old_extra_metadata={"status": SUPERSEDED},
            )
        else:
            result = await ingest_memory(db, ctx, item, kind)
        record = result.record
        if entry.resolves is not None:
            await archive_memory(
                db, ctx, entry.resolves, reason=f"resolved by {record.id}",
                extra_metadata={
                    "status": RESOLVED, "resolved_by": str(record.id),
                    "resolved_at": ms._iso(_now()),
                },
            )
    except (MemoryOpError, MemoryRejected) as exc:
        raise http_error(exc) from exc
    if result.created:
        await ms.audit(db, company_id, "ceo.memory_recorded", recorded_by, "memory", record.id,
                       type=entry.type, ceo_id=ceo.id, origin=origin,
                       redacted=bool((record.record_metadata or {}).get("redacted"))
                       or source_hit or refs_hit,
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
    """Newest first, one bounded query; only this company's executive scope.

    The default is prompt-safe: only ``active`` rows, filtered (with ``type``) in SQL
    before the LIMIT, so a newer closed row cannot push an active one out of the pool.
    ``include_closed=True`` is the operator review path (every lifecycle status); it must
    never feed a prompt or a model-callable tool.
    """
    stmt = select(MemoryRecord).where(
        MemoryRecord.company_id == company_id, MemoryRecord.scope == EXECUTIVE_SCOPE
    )
    if not include_closed:
        stmt = stmt.where(MemoryRecord.status.in_(PROMPT_STATUSES))
    if type is not None:
        stmt = stmt.where(MemoryRecord.memory_type == type)
    if query:
        stmt = stmt.where(MemoryRecord.content.ilike(f"%{query[:200]}%"))
    rows = (
        await db.execute(
            stmt.order_by(MemoryRecord.created_at.desc(), MemoryRecord.id.desc())
            .limit(max(1, min(limit, SEARCH_MAX)))
        )
    ).scalars().all()
    return list(rows)


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
        "Executive memory (what was directed, decided or promised; NOT status; "
        "where it disagrees with the snapshot, the snapshot wins):"
    )
    items: list[dict[str, Any]] = []
    for r in memory[:CONTEXT_MEMORY]:
        meta = r.record_metadata or {}
        now_facts = sorted(
            f"{k}={facts[v]}" for k, v in (meta.get("refs") or {}).items() if v in facts
        )
        item = {
            "id": str(r.id),
            "type": meta.get("type"),
            "created_at": ms._iso(r.created_at),
            "origin": meta.get("origin"),
            "content": " ".join(str(r.content).split()),
        }
        if now_facts:
            item["snapshot_now"] = f"snapshot v{snap['version']}: {', '.join(now_facts)}"
        items.append(item)
    # Recalled memory is data, not instructions: escaped JSON inside a fixed envelope.
    # Drop the oldest entries until the whole context, envelope included, fits.
    while True:
        block = render_memory_data(items, item_max=CONTEXT_LINE_MAX) if items else "- none"
        text = "\n".join([*lines, block])
        if len(text) <= CONTEXT_MAX_CHARS or not items:
            break
        items.pop()
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
