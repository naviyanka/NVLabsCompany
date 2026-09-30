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

## Temporary access

- A grant names an agent, a tool, an effect, a required expiry and an optional use limit.
- A temporary **deny** is a hard deny. A temporary **allow** only converts a default deny. It never
  overrides a policy deny, a lockdown, or an explicit-allow-only tool's missing policy.
- Spending a use is one conditional `UPDATE` (`consume_temp_grant`). Two calls racing for the last
  use cannot both win, and a revoke racing a use has exactly one winner.
- "A temporary high-risk grant with no expiry" cannot exist. `expires_at` is required by the API
  and the column is `NOT NULL`, so no rule is needed to catch it.

## Policy drafts and versions

Drafts are proposals. Publishing writes an immutable version and swaps the active `ToolPolicy`
rows in one short transaction. The unique key `(company_id, version_number)` decides a publish race:
the loser gets `409`. The first publish also records the rules in force before it as version 1.
A change that loosens access must be published by someone other than its author, and by a named
reviewer when the draft lists any. A rollback that loosens access becomes a draft instead of
applying at once.

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

## Risk rules and limits

Rules are simple structural checks on a draft. Two groups depend on capability tags:

- The PR, deploy, hire-approve and spend-approve combination rules are **inert until a capability
  carries the matching tag**. No v1 capability does, so they never fire yet.
- Rules that need no tag (wildcards, loosening, self-review) are live.

## Dashboard

`/governance/access` covers the matrix, lockdown and isolation, runtime cancel, grants and the
audit list. The simulator and policy drafts/versions are **API only** in v1.

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
