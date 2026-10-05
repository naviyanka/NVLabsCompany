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
| Manager | `manager_assign_work` | idempotent | ledger key: `AssignWork.idempotency_key`; the child task id derives from it, a repeat returns the same task and attempt, and the same key for another employee or title is `IDEMPOTENCY_KEY_REUSED` |
| Manager | `manager_review_work` | idempotent | intrinsic: one conditional update decides the attempt, a repeat of the winning decision returns the stored result, and the one bounded retry has its own key (`review:<attempt>:retry`) |
| Manager | `manager_request_hire` | idempotent | ledger key: `HireRequest.idempotency_key`; the hire id derives from it and a repeat returns the same request |
| Manager | `manager_list_reports`, `manager_employee_status`, `manager_task_evidence`, `manager_rollup`, `manager_list_hiring_requests`, `manager_get_hiring_request` | read only | no effect |
| CEO | `ceo_delegate_task_to_manager` | idempotent | intrinsic: same task attempt key as above |
| CEO | `ceo_create_goal_or_work_order` | idempotent | ledger key: the goal or work order id derives from it; a title mismatch is `IDEMPOTENCY_KEY_REUSED` |
| CEO | `ceo_request_hire` | idempotent | ledger key, as `manager_request_hire` |
| CEO | `ceo_record_decision` | non-idempotent | appends a memory entry each time |
| CEO | `ceo_get_organization_snapshot`, `ceo_list_managers`, `ceo_get_manager_status`, `ceo_list_pending_approvals`, `ceo_search_executive_memory`, `ceo_get_work_status`, `organization_get_snapshot` | read only | no effect |
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
| Inbound MCP bridge (agent CLI) | `(-1, ordinal)`: the ordinal is allocated durably per invocation key, from the `Idempotency-Key` header or the declared `nexus_invocation_key` argument (see "Inbound MCP bridge identity") |
| REST node calls | none: no turn, not ledgered |

Parallel calls in one round have distinct positions fixed when the model's batch is read, so
the execution order does not matter.

A ledgered write (any write class, inside a chat turn, in a company) that reaches the guard with
no slot is refused with `effect_ledger_unavailable` before any approval, notification or run.
A path that cannot supply a slot does not get recovery it cannot provide.

### Inbound MCP bridge identity

The bridge builds a new `MCPServer` for every HTTP request, and a turn's agent process can be
restarted, so nothing in memory can say "this is the same write". The identity of a bridge
write is therefore a client-supplied invocation key, mapped to a slot in the database table
`tool_bridge_slots`. The key comes from either of two places:

- the `Idempotency-Key` HTTP request header, for clients that can set a header per call;
- a tool argument declared in the tool's MCP input schema: the tool's own `idempotency_key`
  when it has one, otherwise the reserved `nexus_invocation_key`. Every manager or CEO write
  tool exposed through the bridge lists it under `required` and tells the model to generate a
  new unique value for each intentional call; read tools do not declare it. A field that is not
  in the declared schema is never read.

Stock Claude Code cannot set a per-call header, but it sends the arguments the schema declares,
so it writes through the declared argument. The generated MCP config carries one static header,
the bearer credential; dynamic headers are optional and nothing here depends on them.

If a call carries both, they must be exactly equal; otherwise the call fails with
`IDEMPOTENCY_KEY_CONFLICT` before dispatch and nothing is reserved. The server never picks one
silently.

- The primary key is `(company_id, turn_id, idempotency_key)`; a second unique constraint on
  `(company_id, turn_id, ordinal)` makes the ordinal unique. The first request with a key takes
  the turn's next free ordinal, and every retry of that key, from any process and after any
  restart, finds the same row and so the same slot `(-1, ordinal)`. Two different keys never
  share a slot, however concurrently they arrive: the database arbitrates and the loser retries
  with the next ordinal. Nothing depends on arrival order or on a counter in memory.
- `company_id` and `turn_id` come from the authenticated bridge credential (the execution-scoped
  token resolved against the running chat turn), never from the client. A client cannot name
  another tenant's or turn's slot, and the provider's tool-call id is not part of the identity.
- The row stores the tool name and the digest of the arguments. A retry that reuses a key for a
  different tool or different arguments is refused with `IDEMPOTENCY_KEY_REUSED` and nothing
  runs.
- A write with neither a header nor the argument is refused with `IDEMPOTENCY_KEY_REQUIRED`
  before any dispatch, and no slot is reserved. A key that is not 1 to 128 characters of
  `A-Z a-z 0-9 . _ : ~ -` is `IDEMPOTENCY_KEY_INVALID` (a malformed header is a 400 from the
  route). Read-only calls need no key and take no slot.
- Keys are scoped to the turn, so the same key in another turn is another write.
- The client's value is only a lookup key for the slot. It is never the downstream business
  idempotency key: the v2 ledger key stays authoritative, and the bridge-only argument is
  stripped before a handler that does not declare it is called.

Client requirement: the client must use a fresh, unique key for every intended write and send
the same key and arguments again when it retries that write (a transport retry). Two intentional
identical writes need two keys. Keys are per intentional call, not per session or per tool.

Clients that still cannot write through the bridge: one that neither sets the header nor sends
the declared argument (for example a client that strips or ignores tool arguments outside its
own schema cache, or a custom script that skips `tools/list`), and any model that reuses one key
for two intended writes. Those writes fail closed (`IDEMPOTENCY_KEY_REQUIRED` or
`IDEMPOTENCY_KEY_REUSED`) rather than run without a durable identity.

### Execution epoch

A recovered chat turn can have an old worker still running (a zombie). Every ledgered write
therefore carries an immutable epoch, `(execution_id, attempt)`:

- It is captured when the execution claims or starts the turn (`chat_turns.claim`, the legacy
  chat path and the bridge credential check) and travels on the server-built context through
  Hermes, the governed loop, the MCP adapter, the inbound bridge and any direct `guarded_call`.
  It is never refreshed from the database. No model, argument, header, service key or MCP client
  can set it, and a forged value in arguments is ignored.
- Before the autonomy gate, a grant, an approval, a notification, a ledger insert or a
  dispatch, `guarded_call` compares it with the turn's current attempt, and `claim` compares it
  again under the row lock. A difference is `stale_execution`: nothing is inserted, spent,
  approved, notified or run, and a stale `settle` cannot overwrite the current claim.
- The current recovery replays occupied slots exactly as described below. A write with no epoch
  on a chat turn is refused the same way.
- Reads are not fenced and never touch the epoch. Two racing recovery workers get one winner:
  `chat_turns.claim` hands out the attempt atomically.

### New write tools

The work-lifecycle tools (`manager_assign_work`, `manager_review_work`, `ceo_get_work_status`) are
classified in the table above. Any tool added after this change must declare: its `EffectClass`, which `ManagerTool` already requires at
construction; the bridge invocation argument if it is exposed over the HTTP bridge, which
`bridge_input_schema` adds for every write and which
`test_every_bridged_write_tool_requires_its_invocation_argument_and_no_read_does` enforces; and
its downstream idempotency behavior, which the `TABLE` check in `test_tool_effect_idempotency`
enforces. A write tool that does none of these fails those tests.

### Work attempts offer no tool

A text work attempt runs as a chat turn with `work_mode="text"`, so its calls are ledgered like any chat turn, but it is offered no tool: `manager_tools.catalog` returns nothing for a context with a work mode (this covers the HTTP bridge, the governed loop and `MCPServer`), the governed vault write tool is not registered, and a CLI runs with its read-only flags. A code attempt (`write`, `read_only`) already ran under cataloged CLI flags without the bridge. A retry is a new attempt and a new turn, which is safe because no attempt can write through a tool.

## Recovery of a turn that already wrote

A recovered chat turn has a second execution under a new `execution_id` but the same turn id.
`ChatTurn.attempt_count` counts the executions and is read from the turn row by the server;
neither a tool argument nor an HTTP header can set it. Each ledger row records the execution
that first claimed its slot (`turn_attempt`).

A durable record of what the first run *planned* does not exist: after recovery the model may
plan the same write at a different slot (for example after an extra read-only round), and the
slot alone cannot tell a new write from a shifted one. The rule is deliberately small:

| Call in a recovered execution (attempt > 1) | Result |
| --- | --- |
| Same tool and arguments at a slot an earlier execution used | replays the stored result, or follows the state machine for that row |
| Different tool or arguments at an occupied slot, including reordered calls | `effect_recovery_required` (`tool_effect.slot_mismatch` is audited) |
| Write at an empty slot, and an earlier execution already claimed a write in this turn | `effect_recovery_required`, whether the write is idempotent or not. No row is left behind and no grant is spent |
| Write at an empty slot, and no earlier execution claimed a write | runs normally |
| Read-only call | runs normally, never ledgered |

Rows created by the current execution do not count as earlier writes, so a recovered turn that
had written nothing may write freely, and a recovered turn that is making new progress is not
blocked by its own new rows. The cost is that a recovered turn which wrote before cannot make
further new writes at all. A blocked call has no ledger row, so there is nothing to resolve
through the manual recovery routes: check in the external system what the first run did, and
if the remaining work is still wanted, start it in a new turn.

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
| `http-request` and `msg-webhook-notify` that completed an HTTP exchange, **whatever the status code (including 4xx and 5xx)** | `succeeded`: the executor returns the response instead of raising, so the status is part of the stored, replayed result and the call is not retried |
| Slack, Discord or Telegram answering with an error status, or Discord and Telegram answering 200 with a body that is not JSON | `ambiguous` |
| HTTP error status from an MCP server (`is_error`; a 5xx also sets `effect_unknown`) | `ambiguous` |
| In-band MCP error | `ambiguous` |
| Obsidian `conflict`, `denied`, `approval_failure`, `secret_rejection`, `invalid_content` and other rejected statuses | `failed` |
| Obsidian `recovery_failure` and any other uncertain status | `ambiguous` |
| Result that cannot be serialized or retained | `ambiguous`, caller sees `effect_result_unavailable` |

No HTTP 4xx is assumed to prove that nothing happened. For `http-request` and
`msg-webhook-notify` that means a completed 4xx or 5xx response is recorded as an *executed*
effect, not as a failure: a recovered turn gets the same response back and the request is not
sent again. Only an exception (timeout, connection failure) after dispatch is `ambiguous`. An
exception is recorded by type name only; its message is never stored.

For an idempotent tool, `ambiguous` is retried automatically (the proof above makes the retry
harmless).

What the model sees:

| Result `status` | Meaning |
| --- | --- |
| `success`, `replayed: true` | An earlier run in this turn is returned. The tool did not run. |
| `effect_in_progress` | Another worker holds the call. Try later. |
| `effect_recovery_required` | Not run. Either the outcome is unknown, or the slot holds a different call, or (recovered turn) this is a new write at an empty slot after earlier executions already wrote. The last case leaves no ledger row (see "Recovery of a turn that already wrote"). |
| `effect_result_unavailable` | The tool ran, but its result could not be retained. The effect is recorded as ambiguous and is not rerun. |
| `effect_ledger_unavailable` | Not run, or not replayable: the ledger could not be used (no slot, no database, or arguments with no canonical form), or the call already ran but its stored result cannot be decoded (replay decode failure; the effect is not rerun). |
| `denied` | Not run: the access check refused it, or the temporary grant it relies on was spent or ended before the claim. |
| `failed` (Hermes tool loop only) | The tool raised, and the Hermes adapter returns `{"error": ..., "status": "failed"}` to the model. The ledger row is **not** `failed`: an exception after dispatch is `ambiguous`, so a recovered turn is blocked at that slot with `effect_recovery_required` (non-idempotent) or retried (idempotent). The model's view and the ledger deliberately differ. |

A tool that returns a failing result without raising (an in-band MCP error, an executor result
with `success = false`) reaches the model as `status: success` with the failing result inside,
because the guard cannot know more than the tool says; the ledger row is `ambiguous`.

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
send loses that notification; it is never sent twice, and nothing resends it on recovery. An
operator who needs to know about a call that ran during such a crash finds it in the ledger and
the audit log, not in the notification channel.

### Temporary grants

A temporary allow with `max_uses` is spent once per **slot**, not per call content. A ledgered
write spends inside its claim transaction, and only when the decision is `run`: a replay, a busy
or blocked slot, a slot mismatch and a blocked recovery spend nothing, and a retake of the same
slot after a crash does not spend again. Two identical calls at two different slots are two
uses, so a grant with `max_uses = 1` allows one of them and denies the other. When the grant is
used up, expired or revoked before the claim, the call is `denied` and leaves no ledger row. A
call that is not ledgered spends under its slot key when it has one, or under a fresh key when
it has none.

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
- **Migration.** `c5e8a3b71d94` creates `tool_effects`, `tool_notifications` and
  `tool_bridge_slots` with forced row level security and the usual `tenant_isolation` policy on
  PostgreSQL. `tool_effects.turn_attempt` records the execution that claimed each slot. No
  existing table, policy or the memory tables change. The migration names no role and has no
  GRANT or OWNER statement: `nexus_migrator` owns the three tables, `nexus_app` owns none and
  reaches them through the default privileges of `deploy/postgres/provision-roles.sql`
  (SELECT, INSERT, UPDATE, DELETE). `nexus_app` cannot disable RLS, drop protections, truncate
  or alter a policy; `tests/test_db_role_separation_postgres.py` proves this, and that a
  refused downgrade and a re-upgrade keep the contract.

### Downgrade

Downgrading `c5e8a3b71d94` drops three tables. Two of them are the only record that something
already happened: `tool_effects` (the writes) and `tool_notifications` (the notices already
sent). It is therefore refused by default.

- **All three tables empty**: the downgrade succeeds.
- **Any row in `tool_effects` or in `tool_notifications`** (either one alone is enough): the
  downgrade raises `Refusing to downgrade`, reports both row counts, and deletes nothing. The
  check and the refusal are transactional, and row level security is left as it was.
- **Rows only in `tool_bridge_slots`**: not a reason to refuse. Those rows only map client keys
  to ordinals; with no effect or notice behind them nothing can repeat.
- **Explicit override**: set `NEXUS_DESTROY_TOOL_EFFECTS=destroy-ledger` (that exact value).
  The downgrade logs a `DESTRUCTIVE DOWNGRADE` warning that names the table row counts only
  (no tool names, arguments or results) and says replay protection is lost, then drops all
  three tables.
- **Re-upgrade** after a destructive downgrade creates empty tables.

After a destructive downgrade and re-upgrade, turns that were in flight must not be recovered
automatically: their completed non-idempotent calls are no longer in the ledger and would run
again, their notifications would be sent again, and a recovered bridge client's retried keys
would be allocated as brand new writes. Cancel or manually close those turns, or check the
external systems first. Nothing is cleaned up silently.

## Known limits

- Only calls inside a chat turn are ledgered. REST node calls and background task attempts are
  not; task-attempt recovery has its own idempotency key.
- A bridge write is only as safe as its client's invocation key: a client that sends a new key
  when it retries the same write executes it twice. A client that sends neither the header nor
  the declared argument cannot write through the bridge. The server enforces uniqueness and
  replay of a key; it cannot know that two different keys meant one intended write.
- A level-2 notice, or a level-3 approval request and notice, is created before the grant is
  spent. If the spend is then refused (a grant revoked in between), the notice stays for a call
  that did not run. It authorizes nothing: approvals and grants are matched per slot, a refused
  spend leaves no ledger row, and another slot sends its own notice. This is cosmetic noise and
  a follow-up, not an authorization gap.
- A recovered turn that already made writes can make no new write (`effect_recovery_required`),
  idempotent or not, because no durable plan record says which slots the first run planned.
  The blocked call leaves no ledger row for an operator to resolve.
- A succeeded row at a slot where recovery then plans a different call stays blocked until an
  operator decides.
- Notifications are at-most-once: a crash between marking and sending loses the notice and
  nothing resends it.
- `db-redis-set` is non-idempotent, with or without a `ttl`: a rerun could extend the key's
  life or overwrite a newer value, so an interrupted call waits for an operator. A hire
  approved automatically but not yet materialized when the process dies is completed by a
  human approval only (the work is not duplicated). A CEO delegation that dies between the
  attempt commit and the memory write loses that memory entry.
- `http-request` and `msg-webhook-notify` record a completed HTTP response, including 4xx and
  5xx, as an executed effect. A request the remote server rejected is not retried by recovery.
- A temporary grant is spent once per slot, so identical calls at different slots each take a
  use (see "Temporary grants").
- `HTTPException` from `ceo_record_decision` (non-idempotent) is ambiguous because it cannot
  be shown to precede the effect. Idempotent tools are unaffected.
- Classification is a declaration. If a tool's behavior changes, its class and its row in the
  table above must be reviewed with it.
