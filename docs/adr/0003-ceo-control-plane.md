# ADR 0003 — The CEO is a designation; its authority is governed tools, not prompts

**Status:** Accepted
**Date:** 2026-09-29

## 1. Decision

**Designation**
- `agents.is_ceo` holds the designation (migration `e7a1c2d3f406`).
- The partial unique index `uq_agents_one_ceo` allows at most one CEO per company.
- Only a human administrator can appoint, replace or remove the CEO: `PUT` or `DELETE /api/v1/organization/ceo`.
  - A human is a user session, or the keyless, unlabelled service principal used when `AUTH_ENABLED=false`.
  - API keys and agent runs cannot.
- Every change is audited:
  - `organization.ceo_appointed`
  - `organization.ceo_replaced`
  - `organization.ceo_removed`
- A role, title or prompt that says "CEO" grants nothing.

**Hierarchy**
- `agents.is_ceo` is the only source of CEO authority. A role, title, prompt or `adapter_config` value grants nothing.
- The CEO is the company's only root. On appointment, every other live root reports to it.
- The CEO cannot be given a manager (`CEO_IS_ROOT`). The existing cycle check still applies.
- Every agent-creation path (agents API, clone, hire-team, hiring, company sim, lifecycle, `agent_service`) resolves its manager through `ceo_service.resolve_manager`. An explicit valid manager is kept; otherwise the agent reports to the CEO.
- `ceo_service.lock_hierarchy` serializes appointments and placements per company (a PostgreSQL advisory lock; on SQLite the write lock).
- `appoint` takes `replaces`, the current CEO's id (or none). Of two racing appointments the loser gets `CEO_CONFLICT` (409); the unique index is the backstop. This is tested on PostgreSQL.
- Every reporting-line move is audited as `agent.manager_changed` (`reason: ceo_root`).

**Replacement and removal**
- Replacing or removing the CEO revokes it immediately.
- On replacement, the former CEO and its direct reports report to the new CEO. The former CEO keeps no direct reports, so it loses its manager tools, and the new CEO is the only root.
- On removal without a replacement, the removed CEO's direct reports become roots (`released_roots` in the audit).
- Every CEO tool call re-reads the designation in its own transaction.
- A tool that is no longer offered is refused with `TOOL_NOT_OFFERED`.

## 2. Executive context

On every CEO chat turn, the server adds an executive context to the system prompt. The prompt requests and the model's output never produce it.

**Contents**
- the latest organization snapshot: version, hash prefix, `generated_at`, `data_as_of` and freshness, with a warning when it is stale, rebuilding or failed
- the last refresh error
- the summary and attention items
- the managers
- the pending human approvals
- the newest active executive memory entries

**How it is built**
- It uses three indexed queries: the snapshot, its state, and the memory.
- It does no live aggregation and makes no LLM call.
- It is deterministic for the same inputs.
- It is capped at `CONTEXT_MAX_CHARS`.

## 3. Executive memory

Executive memory is stored as `memory_records` rows with `scope = "executive"` and the company as `scope_id`.

**Entry types:** directive, decision, delegation, commitment, hiring, risk and outcome.

**Metadata on each entry**
- the CEO it belongs to
- who recorded it
- its origin: human or tool
- its source: turn, message, session or attempt
- refs
- supersede and resolve links
- a content hash
- a redaction flag

**Rules**
- Secrets are redacted before storing.
- Only a person can supersede or resolve a human entry.
- The generic memory routes cannot store, edit, archive or delete executive entries.
- Memory is kept when the CEO is replaced.
- Memory is not status. Each memory line is annotated with the current snapshot state of the things it refers to, and the snapshot wins.

## 4. Governed tools

The CEO tools are served by the inbound MCP server, beside the manager tools. They run through `guarded_call`, which evaluates policy and audits the call.

**Read tools**
- `ceo_get_organization_snapshot`
- `ceo_list_managers`
- `ceo_get_manager_status`
- `ceo_list_pending_approvals`
- `ceo_search_executive_memory`

**Write tools**
- `ceo_delegate_task_to_manager`
- `ceo_create_goal_or_work_order`
- `ceo_record_decision`
- `ceo_request_hire`

The write tools are in `EXPLICIT_ALLOW_ONLY`. Only an allow `ToolPolicy` that names a write tool literally permits it; a wildcard does not.

**Hiring:** `ceo_request_hire` goes through the hiring workflow unchanged, so the hiring policy also needs its `manager_request_hire` permission.

**What the CEO cannot do:** there is no tool to approve anything, change policy, permissions or designation, read secrets, or create agents.

## 5. Hermes limitation

The Hermes CLI loads MCP servers only from its persistent user config. It has no flag for an execution-scoped MCP config, and Nexus never writes a user's global CLI config.

**What a Hermes CEO does**
- It chats normally, with the executive context injected.
- `ceo_tools_available` is `false`.
- A turn that explicitly requires tools is refused with `CEO_TOOLS_UNSUPPORTED`.

**What does not happen**
- Free-form output is never parsed as tool calls.
- Claude is never substituted silently.

Tools become available to a CEO whose backend supports an execution-scoped MCP config flag, such as Claude.
