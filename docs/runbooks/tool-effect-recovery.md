# Tool-effect recovery

This runbook describes how NEXUS keeps a recovered chat turn from repeating an external tool
effect, how to read the ledger, and what an operator does when a tool call has an unknown
outcome. The implementation is `nexus.tools.effects`, the model is `nexus.models.tool_effect`
and the migration is `c5e8a3b71d94`.

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
| `idempotent_write` | Repeating the call with the same arguments leaves the same state. | Yes | Retried automatically. |
| `non_idempotent_write` | A second run would do the effect twice. | Yes | Never rerun. Waits for an operator. |

A write-capable tool with no declared class is treated as `non_idempotent_write`, so a missing
declaration fails closed. `ManagerTool.effect` is a required field with no default, and
`hermes_adapter.register_tool(..., effect=...)` and `mcp_server.NODE_EFFECTS` carry the class
for the other tool sources. A test fails when an executable node has no entry.

Current declarations:

| Source | Tool | Class |
| --- | --- | --- |
| Manager tools | `manager_delegate_task`, `manager_request_hire` | idempotent write |
| Manager tools | all other manager tools | read only |
| CEO tools | `ceo_delegate_task_to_manager`, `ceo_create_goal_or_work_order`, `ceo_request_hire` | idempotent write |
| CEO tools | `ceo_record_decision` | non-idempotent write |
| CEO tools | all other CEO tools | read only |
| Builtin nodes | `ai-chat`, `ai-sentiment`, `ai-summarize`, `ai-translate`, `db-redis-get`, `file-csv-parse`, `file-json-parse` | read only |
| Builtin nodes | `db-redis-set` | idempotent write |
| Builtin nodes | `db-sqlite-query`, `http-request`, `msg-discord-send`, `msg-slack-send`, `msg-telegram-send`, `msg-webhook-notify` | non-idempotent write |
| Obsidian | the chat-attached write tool (compare-and-set on the note hash) | idempotent write |
| Anything else | undeclared | non-idempotent write |

The delegation, goal and hire tools are idempotent because they already derive a deterministic
key from their arguments and the turn, so a second run returns the first run's record.

## Logical invocation key

One `tool_effects` row is one logical call. Its key is

```
invocation_key = sha256( json([KEY_VERSION, company_id, turn_id, tool_name, canonical_args]) )
```

- `KEY_VERSION` is `nexus.tool-effect.v1`. Changing the derivation requires a new version,
  because the old rows would otherwise stop matching.
- `company_id` and `turn_id` are the canonical lowercase hyphenated UUID strings. `turn_id` is
  the chat turn's stable id (`ChatTurn.id`), which survives recovery, unlike its per-claim
  execution id.
- `canonical_args` is the arguments object as JSON with sorted keys, `(",", ":")` separators,
  ASCII-only escapes and no `NaN` or infinity.
- The outer JSON array is also compact, so field boundaries cannot be confused (`("ab", {"c":1})`
  and `("a", {"bc":1})` give different keys).
- `arguments_digest` is the sha256 of `canonical_args` alone. It lets an operator match a ledger
  row to a call without the ledger storing the arguments.

Arguments that are not plain JSON (sets, bytes, arbitrary objects, `NaN`) have no canonical form.
The write is refused with `effect_ledger_unavailable` rather than run without an identity.

Two identical calls in one turn are one logical call. The second replays the first instead of
running again. Different arguments, a different tool, a different turn or a different tenant
are different calls.

Calls with no chat turn (a plain REST node request) are not ledgered, because nothing requeues
them.

## State machine

```
executing -> succeeded | failed | ambiguous
executing (lease expired) -> manual_recovery_required            non-idempotent
executing (lease expired) -> executing (attempt + 1)             idempotent
failed -> executing (attempt + 1)                                the tool said it did nothing
ambiguous -> manual_recovery_required                            non-idempotent, on the next claim
ambiguous -> executing (attempt + 1)                             idempotent
manual_recovery_required -> succeeded | failed                   audited operator decision only
```

- The row is inserted as `executing`, with a claim token and a 15 minute lease, before the tool
  runs. The insert is the claim: a unique key on `(company_id, invocation_key)` means exactly
  one caller gets `run`, and every other caller sees `busy`. Every takeover is a single
  compare-and-set `UPDATE` on status and attempt count, so concurrent takeovers also have one
  winner.
- Only the claim holding the token can settle the row, so a worker whose lease expired and whose
  row was taken over cannot overwrite the newer outcome.
- `succeeded` stores the bounded result. A later claim returns it with `"replayed": true` and
  does not run the tool, run the tool's budget accounting or spend a temporary grant again.
- `failed` means the tool reported that it did nothing: a validation error, an HTTP 4xx, or a
  result with `success = false` or `is_error = true` and no `effect_unknown` flag. Retrying is
  safe for both classes.
- `ambiguous` means the effect may have happened: a timeout, a server error, a connection
  error, an unexpected exception, or cancellation. `ExecutorResult.effect_unknown` and
  `MCPResult.effect_unknown` carry this for tools that return instead of raising.
- A worker that dies while `executing` leaves a row whose lease later expires, which is treated
  as `ambiguous`.
- Settling never fails the tool call. If the ledger cannot be written, the row stays `executing`
  and the next claim treats it as ambiguous, which is the safe direction.

What the model sees:

| Result `status` | Meaning |
| --- | --- |
| `success`, `replayed: true` | An earlier run in this turn is returned. The tool did not run. |
| `effect_in_progress` | Another worker holds the call. Try later. |
| `effect_recovery_required` | The outcome is unknown and an operator must decide. |
| `effect_ledger_unavailable` | The ledger could not be used, so the write was refused. |

## What the ledger stores

The ledger holds identifiers and states, not payloads.

- No arguments. Only the digest.
- A result is stored only for `succeeded`, as JSON-safe data with secret-looking keys masked by
  the same rule as the invocation audit row (keys containing password, secret, token or key).
  Over 16 KiB it is not stored at all: the row keeps its size and digest, and a replay returns
  a note saying the result was omitted.
- Error text is passed through the guardrail secret patterns plus bearer-token, `sk-` key and
  JWT shapes and cut to 500 characters. An exception is recorded by type name only, because its
  message can carry request data.
- Audit events (`tool_effect.replayed`, `.ambiguous`, `.manual_recovery_required`, `.retaken`,
  `.manual_recovery_resolved`) carry the tool name, class, turn id, key, attempt count and
  states only. The transitions that change what may run next (`retaken`,
  `manual_recovery_required`, `manual_recovery_resolved`) fail the operation if the audit row
  cannot be written.

Because stored results are masked, a replay can show a masked value where the original result
held a secret-looking key.

## Manual recovery

A non-idempotent call whose outcome is unknown is never rerun by the system. List what is
waiting (administrators only, tenant scoped):

```
GET /api/v1/tool-effects/open
```

Each entry has the effect id, turn id, tool name, class, status, attempt count and arguments
digest. Find out in the external system whether the effect happened, then record the decision:

```
POST /api/v1/tool-effects/{effect_id}/resolve
{"outcome": "applied" | "not_applied", "reason": "...", "note": "..."}
```

- `applied`: the effect happened. The call becomes `succeeded`; a recovered turn replays the
  operator's note instead of running the tool.
- `not_applied`: the effect did not happen. The call becomes `failed`; the next call in the
  turn may run once.
- The decision is valid only from `ambiguous` or `manual_recovery_required`. Anything else
  returns 409, so two operators cannot both decide and a live call cannot be overridden.
- The actor, the reason and the outcome are written to the audit log in the same transaction. If
  the audit row cannot be written, nothing changes.

The service functions `effects.list_open` and `effects.resolve_manual_recovery` are the same
operations for scripts.

## Operations

- **Retention.** Rows are not pruned. A row is a few hundred bytes plus a result of at most 16
  KiB, and one exists per distinct write per turn. Pruning rows of finished turns older than the
  retention window you keep chat turns for is safe once nothing can recover that turn. Never
  prune `ambiguous` or `manual_recovery_required` rows.
- **Lease.** `LEASE_SECONDS` is 900. There is no heartbeat, so a call that runs longer than
  that is treated as interrupted by a later claim: an idempotent call is retried, a
  non-idempotent one waits for an operator.
- **Migration.** `c5e8a3b71d94` creates `tool_effects` only, with forced row level security and
  the usual `tenant_isolation` policy on PostgreSQL. The table is owned by the migrator role;
  the application role only has default DML privileges. No existing table, policy or the memory
  tables change.
- **Downgrade loses data.** Downgrading drops `tool_effects` and every recorded effect,
  including rows awaiting manual recovery. After the table is recreated a recovered turn can
  run the same non-idempotent tool a second time. Do not downgrade while any row is open.

## Known limits

- Only calls inside a chat turn are ledgered. REST node calls and background task attempts are
  not; task-attempt recovery has its own idempotency key.
- Tool-level budgets do not exist today, so "once" means a replay never reruns or charges the
  tool again. Approvals, autonomy checks, tenant and permission checks run on every call,
  including a replay, and a temporary grant is spent under its own per-turn key.
- A `ValueError` raised after a partial effect is treated as a definite refusal. A tool that
  validates late should return an error result with `effect_unknown` instead.
- Classification of a node or tool is a declaration. If a tool's behavior changes, its class
  must be reviewed with it.
