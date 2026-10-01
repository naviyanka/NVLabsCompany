# Governance Studio v1

Governance Studio lets a human admin see, simulate, change and stop what agents may do. It is a
control surface over the existing policy engine. It is not a second permission engine.

## One enforcement point

Every tool call goes through `guarded_call`, which runs `check_tool_access` (role-based access,
`ToolPolicy`, `ToolProfile`), then guardrails and the autonomy gate, then the tool itself. Studio
adds nothing beside this path:

- `nexus.tools.governance_overlay` is consulted inside `check_tool_access`. It applies company
  lockdown, agent isolation and temporary grants.
- Role, job title, prompt text and anything the browser sends never grant authority. Only stored
  policy, grants and restrictions do.
- The effective-access matrix and the policy simulator read the same snapshot and decision code
  (`effective.load_snapshot` and `effective.decide`). A parity test holds that code to
  `check_tool_access`, so the screen cannot drift from the runtime.

## Capability catalogue

44 entries, each with a support level:

| Level | Meaning |
|-------|---------|
| `enforced` | The runtime enforces it today and Studio shows the real decision. |
| `approval_only` | Reaches an action only through a human approval. |
| `display_only` | Shown for information. No control. |
| `unsupported` | Not preventable today (all computer-use items). Shown as "Not enforceable", never as a toggle. |

## Decision precedence

Every surface (runtime `guarded_call`, the effective-access matrix, the simulator and the preset
and draft previews) applies the same order. The first step that decides wins:

1. The capability cannot be enforced (`NOT_ENFORCEABLE`): deny.
2. Role-based access does not allow tools (`RBAC_DENIED`): deny.
3. Company lockdown or agent isolation (`RESTRICTION_ACTIVE`): deny.
4. A live temporary deny (`TEMP_DENY`): deny.
5. A matching explicit deny rule (`POLICY_DENY`): deny.
6. Invariants still apply: tenant, CEO-only, direct-report, budget, headcount and signature rules
   live in the tools and run after `guarded_call` allows. The simulator does **not** evaluate them
   and says so in its `notes`.
7. A live, approved temporary allow satisfies a *default deny* (`TEMP_ALLOW`): only for its exact
   agent, tool, session scope and expiry. It never overrides steps 1 to 5, and it only applies
   where no policy rule matched. For an explicit-allow-only tool it counts only once a second
   person approved that exact grant.
8. Normal `ToolPolicy`, `ToolProfile` and default evaluation (`POLICY_ALLOW`, `DEFAULT_ALLOW`).
9. Default deny (`DEFAULT_DENY`, or `GRANT_EXPIRED` when only an expired grant exists).

Autonomy gates (`AUTONOMY_L*`) and secret-binding checks sit on top for approval-only and
secret-backed tools.

## Temporary access

- A grant names an agent, a tool, an effect, a required expiry, an optional use limit and an
  optional `session_id` scope. `session_id` is the **only** scope the engine can enforce. Task and
  resource scopes cannot be enforced, so the UI and API offer none.
- Non-read allows and every explicit-only allow start `pending_approval` and need a different
  person to approve. Until approved they have no effect.
- A temporary **deny** is a hard deny. A temporary **allow** only converts a default deny. It
  never overrides a policy deny, RBAC, a lockdown or an isolation.
- `expires_at` is required by the API and the column is `NOT NULL`.

### Consumption semantics

| Situation | Result |
|-----------|--------|
| Simulator, matrix, effective-access, any read | Never consumes. |
| Real `guarded_call` allowed by a grant | Consumes exactly one use, committed **before** the tool runs. |
| Two concurrent calls for the last use | One conditional `UPDATE` (`consume_temp_grant`): one winner, the other is denied. |
| Same invocation replayed while the grant is live | `invocation_key(turn, tool, args)` is unique per `(grant, key)` in `governance_grant_uses`. The replay is allowed and not charged twice. |
| Replay after revoke | Denied. |
| Denied, blocked, pending or autonomy-paused call | Consumes nothing. |
| Revoke or expiry racing a use | The same conditional `UPDATE` checks both: exactly one outcome, deterministic. |
| Downstream tool fails after the grant allowed it | **The use stays consumed.** The grant authorised the attempt, and refunding would let a failing tool be retried without bound. Request a new grant. |
| Another tenant asks about the grant | `404`, same as a missing id. Nothing reveals that it exists. |

## Policy drafts and versions

Drafts are proposals. Publishing writes an immutable version and swaps the active `ToolPolicy`
rows in one short transaction. The unique key `(company_id, version_number)` decides a publish race:
the loser gets `409`. The first publish also records the rules in force before it as version 1.
A change that loosens access must be published by someone other than its author, and by a named
reviewer when the draft lists any. A rollback that loosens access becomes a draft instead of
applying at once. A tightening rollback applies at once as a new version.

The dashboard (Policy tab) lists drafts with owner, base version, status, reason, author and a
STALE flag. The editor is structured: per rule name, effect, priority, capabilities (catalogue
tool names only), agents, risk levels, active hours, owner and review date. A rule's "approval
requirement" is **not** a policy-engine concept. Approval comes from autonomy level and
explicit-allow tools, and the editor says so. Publishing needs a human admin and an explicit review
confirmation, sends an optimistic `expected_version`, and shows the exact diff, a per-agent
simulator summary and high-risk warnings. A stale draft cannot be published. A stale edit or
publish returns `409` (`STALE_EDIT`, `STALE_BASE`, `VERSION_CONFLICT`, `DRAFT_NOT_OPEN`) and the UI
shows it. Rollback shows the exact diff first and creates a **new** version. History is never
deleted.

## Simulator

`POST /api/v1/governance/simulate` is a dry evaluation. It takes an agent, a catalogue capability,
an optional `session_id`, and optionally a draft's `proposed_rules`. It returns the decision and
reason code, an ordered explanation (each step `checked`, `decided` or `not reached`), matched
policy, approval requirement, grant validity, backend and feature-gate blockers, and risk findings.
It calls no tool, spends no grant, writes nothing and sends nothing. The UI has no arbitrary JSON
or code entry.

## Autonomy presets

Advisory, Assisted, Task autonomy, Delegated autonomy, Operational autonomy and Restricted
executive autonomy. There is no `PUT /agents/{id}/autonomy`. A preset only creates a **draft** with
an exact capability diff. Nothing is active until a human publishes it. It never bypasses role,
designation or an explicit deny, and unenforceable capabilities show `Not enforceable` and are
excluded. Delegated and Operational need an agent with direct reports. Restricted executive needs
the CEO.

## Runtime control

- Cancelling work reuses `task_attempts.cancel_attempt` and `chat_turns.request_cancel`. The audit
  entry commits first and fails closed: if it cannot be written, nothing is cancelled. The cancel
  then runs in its own short transactions.
- **Lockdown** blocks every non-read or explicit-only tool for the whole company. **Isolation**
  does the same for one agent. Both are human-admin only. Lockdown needs a reason and the typed
  phrase `LOCKDOWN` (release: `RELEASE LOCKDOWN`). Isolation needs a reason.
- There is no general "disable security" mode.

## Audit

Every change writes an audit row whose action starts with `governance.`. Rows hold ids and a
bounded reason, never secret values, prompts, memory, tokens, or raw tool arguments. The timeline
is `GET /api/v1/governance/audit`.

## Risk rules

Findings are advisory and deterministic. They never block a publish and no model produces them.
Combination rules read server-owned catalogue tags, set only where a capability really has the
property:

| Tag | Capabilities |
|-----|--------------|
| `secret_reference` | `data.secrets` |
| `terminal` | `computer.terminal`, `exec.execute_code` |
| `code_write` | `exec.write_file`, `computer.filesystem_write` |
| `fs_write_outside` | `computer.filesystem_write` |
| `browser_authentication` | `computer.browser` |
| `arbitrary_network` | webhook-style tools |
| `external_post` | webhook and chat-posting tools |
| `spend_request` | `exec.spend` |
| `hire_request` | `org.ceo_request_hire`, `org.manager_request_hire` |

A capability counts as held if it is allowed now **or cannot be restricted** (unsupported
`computer.*`). Live combinations: `SECRET_NETWORK_TERMINAL`, `FS_WRITE_OUTSIDE_SANDBOX` and
`BROWSER_AUTH_EXTERNAL_POST`. Removing one side clears the finding.

**Inert by design:** `PR_AUTHOR_MERGE`, `MERGE_DEPLOY`, `HIRE_REQUEST_APPROVE`,
`SPEND_REQUEST_APPROVE` and `POLICY_EDIT_APPROVE`. No capability exists for `pr_author`, `merge`,
`deploy`, `hire_approve`, `spend_approve`, `policy_edit` or `policy_approve`, so none carries the
tag. They start firing the day a real capability is tagged. No tag was added to make them fire.

Other rules: `WILDCARD_HIGH_RISK` (a rule matching every tool, or a pattern, at high risk),
`NO_OWNER_OR_REVIEW_DATE` (a permanent high-risk rule with no owner or review date), `SELF_REVIEW`,
`GRANT_LONG_DURATION` (a high-risk grant with excessive duration) and `HIGH_RISK_NO_APPROVAL` (a
high-risk capability with no required approval). The old "temporary high-risk grant with no
expiry" rule is gone because that state cannot occur.

## Migration chain

Memory Phase 2 (PR #57) merged first, so this migration sits on top of its migration:

| revision | down_revision |
|----------|---------------|
| `e7a1c2d3f407` (memory RLS) | |
| `f1b7c9d2a508` (memory canonical ingest) | `e7a1c2d3f407` |
| `e7a1c2d3f408` (governance studio, this PR) | `f1b7c9d2a508` |

`alembic heads` reports one head, `e7a1c2d3f408`. No merge migration is needed. Downgrading through
the governance revision drops only the five governance tables and leaves the Memory Phase 2
schema in place.

## Known unsupported capabilities

All `computer.*` capabilities (terminal, browser, filesystem) have no preventive enforcement. They
show `Not enforceable`, cannot be enabled, cannot be put in a rule or preset, and count as held for
risk findings. Task and resource scopes are not enforceable either.

## Dashboard

`/governance/access` has tabs for Effective access, Simulator, Policy (drafts and versions),
Autonomy presets, Runtime, Grants and Audit. Revoke, isolate, release, publish, rollback and
lockdown each ask for confirmation. Lists are paginated (`limit` up to 100, 20 in the UI) with
loading, empty and error states. State is always text as well as colour, tabs and dialogs are
keyboard reachable, and wide tables scroll inside their card. No secret reference, raw prompt or
raw policy internals are shown.

The agent picker has a search box. Selecting a capability name in the matrix opens its details:
reason code, source, what it is inherited from, conditions, approval need, grant validity and last
use. The Grants tab has a form to create a temporary grant (one enforceable tool, effect, expiry,
an optional session scope and a reason). The form checks the inputs before it posts; the server
still enforces the expiry limits and the approval rules. A viewer sees every screen but none of the write controls: lockdown, isolation, grant forms and
actions, draft editing, publish, rollback, preset drafts and cancel are hidden, and the page says it
is view only. The controls follow the signed-in role (`GET /auth/me`) and stay hidden until it is
known. This only shapes the screen; the server still answers 403 `HUMAN_ADMIN_REQUIRED` to every
change a non-administrator attempts.

## Not in v1

AI policy recommendations, automatic policy changes, compliance certification, policy scripting,
voice permissions, a full sandbox for computer use, and verified memory.

## Tests

- `tests/test_governance_*.py` run on SQLite and cover logic, permissions and fail-closed paths.
- `tests/test_governance_postgres.py` needs PostgreSQL (`TEST_DATABASE_URL`). It runs as the
  application role so row-level security applies, and covers: one-use grant under concurrency,
  revoke against use, expiry against use, the publish race, lockdown against invocation, tenant
  isolation on the four tables, and a simulator that writes nothing. CI runs it in the
  `postgres-integration` job.
