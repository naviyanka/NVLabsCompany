# Tool-effect recovery

This runbook describes how NEXUS keeps a recovered chat turn from repeating an external tool
effect, how to read the ledger, and what an operator does when a tool call has an unknown
outcome. The implementation is `nexus.tools.effects`, the models are
`nexus.models.tool_effect`, and the migration is `c5e8a3b71d94`.

## The problem

A chat turn that expires or is interrupted is requeued (`chat_turns._recover`), and the
requeued turn runs the model and its tool rounds again. A tool call had no stable identity
across that rerun: the model's own tool-call ids are regenerated, so nothing said "this is the
same call as before". A write such as sending a message could therefore happen twice.

## Classification

Every tool declares what a rerun of an interrupted call does. The class is explicit and lives
next to the tool; it is never inferred from a tool name, a category or a risk label.

| Class | Meaning | Ledgered | After an unknown outcome |
| --- | --- | --- | --- |
| `read_only` | No effect; repeating it is harmless. | No | Runs again. |
| `idempotent_write` | A rerun is proven harmless (see the proof column below). | Yes | Retried automatically. |
| `non_idempotent_write` | A second run would do the effect twice, or nothing proves it would not. | Yes | Never rerun. Waits for an operator. |

A tool with no declared class is `non_idempotent_write`, so a missing declaration fails closed.
`ManagerTool.effect` is a required field with no default. `hermes_adapter.register_tool(...,
effect=...)` and `mcp_server.NODE_EFFECTS` carry the class for the other tool sources. A tool
is declared idempotent only with a proof, one of:

- **ledger key**: the tool receives the ledger's invocation key as its own idempotency key and
  its service dedupes on it (see "Idempotent retry" below);
- **intrinsic**: repeating the operation leaves the same state, and a test shows it.

Complete table. `tests/test_tool_effect_idempotency.py` holds the same table and fails when a
tool exists that it does not classify, when a class differs from the declaration, when an
idempotent tool has no proof, or when a tool that takes an `idempotency_key` is not bound to
the ledger.

| Source | Tool | Class | Proof |
| --- | --- | --- | --- |
| Manager | `manager_delegate_task` | idempotent | intrinsic: one task attempt per manager and employee key (unique `(company, task, key)` on `task_attempts`) |
| Manager | `manager_request_hire` | idempotent | ledger key: `HireRequest.idempotency_key`; the hire id derives from it and a repeat returns the same request |
| Manager | `manager_list_reports`, `manager_employee_status`, `manager_task_evidence`, `manager_rollup`, `manager_list_hiring_requests`, `manager_get_hiring_request` | read only | no effect |
| CEO | `ceo_delegate_task_to_manager` | idempotent | intrinsic: same task attempt key as above |
| CEO | `ceo_create_goal_or_work_order` | idempotent | ledger key: the goal or work order id derives from it; a title mismatch is `IDEMPOTENCY_KEY_REUSED` |
| CEO | `ceo_request_hire` | idempotent | ledger key, as `manager_request_hire` |
| CEO | `ceo_record_decision` | non-idempotent | appends a memory entry each time |
| CEO | `ceo_get_organization_snapshot`, `ceo_list_managers`, `ceo_get_manager_status`, `ceo_list_pending_approvals`, `ceo_search_executive_memory`, `organization_get_snapshot` | read only | no effect |
| Node | `ai-chat`, `ai-sentiment`, `ai-summarize`, `ai-translate`, `db-redis-get`, `file-csv-parse`, `file-json-parse` | read only | no effect |
| Node | `db-redis-set` | non-idempotent | a relative `ttl` is applied again by a retry, so a rerun could extend the key's life (see below); every `db-redis-set` call is non-idempotent, with or without a `ttl` |
| Node | `db-sqlite-query`, `http-request`, `msg-discord-send`, `msg-slack-send`, `msg-telegram-send`, `msg-webhook-notify` | non-idempotent | arbitrary SQL, requests or messages |
| Obsidian | `obsidian.note_replace` | idempotent | intrinsic: compare-and-set on the hash the caller read, so a rerun finds the note changed and is refused (`WriteConflictError`) instead of rewriting |
| Hermes | `register_tool` without `effect` | non-idempotent | default |
| Hermes / MCP adapter | a ToolConnection call | non-idempotent | no `effect` is declared for external tools, so the default applies |
| Any other registration | dynamic or undeclared | non-idempotent | default |

## Logical invocation identity

One `tool_effects` row is one logical call, identified by its durable position in the turn, not
by its content:

```
invocation_key = sha256( json(["nexus.tool-effect.v2", company_id, turn_id, round_index, invocation_index]) )
```

- `KEY_VERSION` is `nexus.tool-effect.v2`. Changing the derivation requires a new version.
- `company_id` and `turn_id` are canonical lowercase hyphenated UUID strings. `turn_id` is the
  chat turn's stable id (`ChatTurn.id`), which survives recovery.
- The slot is `ToolSlot(round_index, invocation_index)`: the model round in which the call was
  requested, and its position among that round's calls. Both are plain integers (booleans are
  rejected). The outer JSON array is compact, so field boundaries cannot be confused.
- Provider tool-call ids are never part of the identity: they are regenerated on every rerun.
- No process-global counter is used anywhere.

The row also stores `tool_name` and `arguments_digest` (sha256 of the canonical arguments).
When a call claims a slot that already has a row, the stored tool name and digest must match.
A different tool or different arguments at an occupied slot is not the same logical call, so
the call fails closed with `effect_recovery_required` and a `tool_effect.slot_mismatch` audit
event, and nothing runs. This is also what happens when a recovered model plans a different
sequence than the first run.

Consequences:

- Identical calls at different positions or rounds are different calls and each runs.
- Recovery of the same position reuses the same row, so it replays a finished call and never
  reruns a non-idempotent one.
- Arguments that are not plain JSON (sets, bytes, objects, `NaN`) have no canonical form; the
  write is refused with `effect_ledger_unavailable`.

Where each path gets its slot:

| Path | Slot |
| --- | --- |
| Hermes loop | `(round, position)`: the loop round and the call's index in that round's list |
| Governed loop | `(round_no, position)` |
| MCP adapter, ToolConnection calls | `(0, position)` |
| Inbound MCP bridge (agent CLI) | `(-1, n)`: `n` counts this server instance's ledgered writes, in call order; read-only calls are not counted |
| REST node calls | none: no turn, not ledgered |

Parallel calls in one round have distinct positions fixed when the model's batch is read, so
the execution order does not matter. The bridge's counter is the weakest identity: it assumes
a recovered agent run issues the same ordered sequence of writes. If it does not, the
mismatch rule above stops the divergent call. Calls issued in parallel over the bridge are
numbered by arrival, so their order is not deterministic and they can fail closed on recovery.

A ledgered write (any write class, inside a chat turn, in a company) that reaches the guard with
no slot is refused with `effect_ledger_unavailable` before any approval, notification or run.
A path that cannot supply a slot does not get recovery it cannot provide.

## State machine

```
executing -> succeeded | failed | ambiguous
executing (lease expired) -> manual_recovery_required            non-idempotent
executing (lease expired) -> executing (attempt + 1)             idempotent
failed -> executing (attempt + 1)                                the tool proved it did nothing
ambiguous -> manual_recovery_required                            non-idempotent, on the next claim
ambiguous -> executing (attempt + 1)                             idempotent
manual_recovery_required -> succeeded | failed                   audited operator decision only
```

- The row is inserted as `executing`, with a claim token and a 15 minute lease, before the tool
  runs. The insert is the claim: a unique key on `(company_id, invocation_key)` means exactly
  one caller gets `run`, and every other caller sees `busy`. Every takeover is a single
  compare-and-set `UPDATE` on status and attempt count, so concurrent takeovers also have one
  winner.
- Only the claim holding the token can settle the row (fencing). A worker whose lease expired
  and whose row was taken over cannot overwrite the newer outcome.
- `succeeded` stores the sealed result (below). A later claim returns it with
  `"replayed": true` and does not run the tool or spend a temporary grant again.
- Settling never fails the tool call. If the ledger cannot be written, the row stays
  `executing` and the next claim treats it as ambiguous, which is the safe direction.

### Lease clock

Lease expiry is decided by the database clock, never by the worker's. On PostgreSQL the claim
compares `lease_expires_at` with `timezone('UTC', clock_timestamp())` in the same statement,
and a new lease is `database now + LEASE_SECONDS`. A worker whose clock is a day fast or slow
therefore neither steals a live lease nor holds a dead one. SQLite (tests and single-process
development) reads its own `strftime('now')` in SQL, which is the same rule with one clock.
The worker clock is only used for `updated_at` and `completed_at`.

### Outcome classification

For a non-idempotent tool only a typed pre-effect rejection may become a retryable `failed`.
Everything else is `ambiguous`, including errors that look harmless.

| What happened | Outcome |
| --- | --- |
| Typed pre-effect rejection (`EffectNotStarted`, or a result flagged `effect_rejected`): missing parameters, SSRF refusal, missing token, a manager or CEO tool's argument validation | `failed` (retryable) |
| Result flagged `effect_unknown`, `is_error`, or `success = false` | `ambiguous` |
| Plain `ValueError`, `JSONDecodeError`, any other exception after execution began | `ambiguous` |
| Timeout, cancellation | `ambiguous` |
| HTTP error status (400, 422, 5xx alike), or an unreadable response body (Discord and Telegram answering 200 with a body that is not JSON) | `ambiguous` |
| In-band MCP error | `ambiguous` |
| Obsidian `conflict`, `denied`, `approval_failure`, `secret_rejection`, `invalid_content` and other rejected statuses | `failed` |
| Obsidian `recovery_failure` and any other uncertain status | `ambiguous` |
| Result that cannot be serialized or retained | `ambiguous`, caller sees `effect_result_unavailable` |

No HTTP 4xx is assumed to prove that nothing happened. An exception is recorded by type name
only; its message is never stored.

For an idempotent tool, `ambiguous` is retried automatically (the proof above makes the retry
harmless).

What the model sees:

| Result `status` | Meaning |
| --- | --- |
| `success`, `replayed: true` | An earlier run in this turn is returned. The tool did not run. |
| `effect_in_progress` | Another worker holds the call. Try later. |
| `effect_recovery_required` | The outcome is unknown, or the slot holds a different call. An operator must decide. |
| `effect_result_unavailable` | The tool ran, but its result could not be retained. The effect is recorded as ambiguous and is not rerun. |
| `effect_ledger_unavailable` | The ledger could not be used (no slot, or arguments with no canonical form), so the write was refused. |

## Idempotent retry

A retried idempotent call must reach the same effect as the first run. The model regenerates
its arguments on a rerun, so a model-chosen `idempotency_key` cannot be trusted. For every tool
with such a field (`manager_request_hire`, `ceo_request_hire`, `ceo_create_goal_or_work_order`)
`manager_tools.call` replaces the key with the call's ledger key before the service sees it.
`guarded_call` binds the key for the duration of the run (`effects.bind_invocation`), and a
path that is not ledgered keeps the caller's own key. The service's own dedupe (a deterministic
id derived from the key) then collapses the rerun into the first record.

Because the ledger key replaces the model's, a model that reuses one `idempotency_key` in two
different turns no longer dedupes across them: each turn's call is its own logical call. Only
a rerun of the same turn at the same slot collapses into the first record.

If a recovered model sends different arguments at the same slot (for example a fresh
`idempotency_key` value), the digest check stops it with `effect_recovery_required` instead of
guessing.

## Results

The first caller and a later replay see the same result. The result is normalized, key-masked
(password, secret, token, key and similar), strict-JSON checked, and bounded **once**, before
the row is settled; both the first return and every replay are decoded from that stored form.

- Identifiers are preserved. A result over 16 KiB is shrunk in tiers (long strings and lists
  are cut), keeps its top-level shape, and carries a `truncated` marker with the original size
  and digest.
- A typed result (`ExecutorResult`, `MCPResult`) keeps its type on replay.
- A result that cannot be serialized (`NaN`, arbitrary objects) or cannot be bounded is not
  stored and the tool is never rerun: the row is `ambiguous` and the caller gets
  `effect_result_unavailable`. An idempotent tool is retried like any ambiguous call.
- Secrets are never stored. Error text is passed through the guardrail secret patterns plus
  bearer-token, `sk-` key and JWT shapes and cut to 500 characters, and an exception is
  recorded by type name only.

## Notifications and approvals

Level-2 autonomy sends a notification before the tool runs. That side effect is deduplicated by
the same identity: `claim_notice` inserts a `tool_notifications` row keyed
`(company_id, invocation_key)`, and the insert is the decision. A replay of a completed call,
a recovered rerun, and any number of racing claims send at most one notification per slot; a
different slot sends its own.

Deduplication covers only the side effect. Permission, policy and autonomy are evaluated on
every call, including a replay: a revoked authority blocks the call before the stored result
is returned.

The notice is marked before it is sent, so it is at-most-once. A crash between the mark and the
send loses that notification; it is never sent twice.

## What the ledger stores

- No arguments. Only the digest.
- A sealed result for `succeeded`, as above.
- Audit events (`tool_effect.replayed`, `.ambiguous`, `.manual_recovery_required`, `.retaken`,
  `.slot_mismatch`, `.manual_recovery_resolved`) carry the tool name, class, turn id, slot,
  key, attempt count and states only. The transitions that change what may run next fail the
  operation if the audit row cannot be written.

## Manual recovery

A non-idempotent call whose outcome is unknown is never rerun by the system. Both routes are
for signed-in human administrators of the tenant only:

| Caller | Result |
| --- | --- |
| Active human administrator | allowed |
| Inactive or removed human | 401 |
| Non-admin human | 403 |
| Service or API key, even with the admin role | 403 |
| Agent run token | 403 |
| Auth-bypass principal or an unknown principal kind | 403 |
| Foreign or missing effect id | the same 404 |

List what is waiting, a page at a time (`limit` up to 500, `cursor` from `next_cursor`; an
invalid cursor is 422). Paging is keyset on creation time and id, so resolving a row never
shifts the next page:

```
GET /api/v1/tool-effects/open?limit=100&cursor=...
```

Each item has the effect id, turn id, round and invocation index, tool name, class, status,
attempt count and arguments digest. Find out in the external system whether the effect
happened, then record the decision:

```
POST /api/v1/tool-effects/{effect_id}/resolve
{"outcome": "applied" | "not_applied", "reason": "...", "note": "..."}
```

- `applied`: the effect happened. The call becomes `succeeded`; a recovered turn replays the
  operator's note instead of running the tool.
- `not_applied`: the effect did not happen. The call becomes `failed`; the next call at the
  slot may run once.
- The decision is valid only from `ambiguous` or `manual_recovery_required`. Anything else
  returns 409.
- The actor, the reason and the outcome are written to the audit log in the same transaction.

## Operations

- **Retention.** Rows are not pruned. Pruning rows of finished turns older than the retention
  window you keep chat turns for is safe once nothing can recover that turn. Never prune
  `ambiguous` or `manual_recovery_required` rows, and never prune `tool_notifications` rows of
  a turn that can still be recovered.
- **Lease.** `LEASE_SECONDS` is 900. There is no heartbeat, so a call that runs longer is
  treated as interrupted by a later claim: an idempotent call is retried, a non-idempotent one
  waits for an operator.
- **Migration.** `c5e8a3b71d94` creates `tool_effects` and `tool_notifications` with forced row
  level security and the usual `tenant_isolation` policy on PostgreSQL. No existing table,
  policy or the memory tables change.

### Downgrade

Downgrading `c5e8a3b71d94` drops the ledger, which is the only record that a write already
happened. It is therefore refused by default.

- **Empty ledger**: the downgrade succeeds.
- **Any row in `tool_effects`**: the downgrade raises `Refusing to downgrade` and deletes
  nothing. Row level security is left as it was.
- **Explicit override**: set `NEXUS_DESTROY_TOOL_EFFECTS=destroy-ledger` (that exact value).
  The downgrade logs a `DESTRUCTIVE DOWNGRADE` warning with the row counts saying replay
  protection is lost, then drops both tables.
- **Re-upgrade** after a destructive downgrade creates empty tables.

After a destructive downgrade and re-upgrade, turns that were in flight must not be recovered
automatically: their completed non-idempotent calls are no longer in the ledger and would run
again. Cancel or manually close those turns, or check the external systems first. Nothing is
cleaned up silently.

## Known limits

- Only calls inside a chat turn are ledgered. REST node calls and background task attempts are
  not; task-attempt recovery has its own idempotency key.
- The inbound MCP bridge numbers writes by arrival order. A recovered agent that issues a
  different sequence, or parallel writes in a different order, fails closed
  (`effect_recovery_required`) rather than running, but needs an operator.
- A succeeded row at a slot where recovery then plans a different call stays blocked until an
  operator decides.
- Notifications are at-most-once: a crash between marking and sending loses the notice.
- `db-redis-set` refreshes the key's TTL when retried. A hire approved automatically but not
  yet materialized when the process dies is completed by a human approval only (the work is
  not duplicated). A CEO delegation that dies between the attempt commit and the memory
  write loses that memory entry.
- A temporary grant is spent under a key derived from the turn, tool and arguments, so
  identical calls in one turn share one use of it.
- `HTTPException` from `ceo_record_decision` (non-idempotent) is ambiguous because it cannot
  be shown to precede the effect. Idempotent tools are unaffected.
- Classification is a declaration. If a tool's behavior changes, its class and its row in the
  table above must be reviewed with it.
