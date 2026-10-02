# Canonical memory records

`MemoryRecord` (`memory_records`) is the single store for durable memory. PostgreSQL is canonical. Every new row is created by `nexus.memory.ingest.ingest_memory`, and every state change goes through `nexus.memory.lifecycle`. Nothing hard-deletes a memory row.

## Record shape

| Field | Meaning |
|-------|---------|
| `memory_type` | fact, preference, decision, directive, lesson, procedure, risk, error, outcome, summary, unknown |
| `status` | candidate, active, archived, superseded, rejected |
| `trust_state` | untrusted, asserted, verified |
| `source_type`, `source_id`, `source_created_at` | Server-owned provenance. Set only when the source is real; never invented. |
| `extractor_version` | Which extractor produced the row. |
| `content_hash` | SHA-256 of the normalized, redacted content. |
| `ingestion_key` | Idempotency key for one logical source event. Unique per company. |
| `supersedes_id` | Earlier record this one replaces. Same company, enforced in the service. |
| `lifecycle_changed_at`, `lifecycle_changed_by` | Last lifecycle transition. |

The vocabularies are bounded strings with check constraints, not database enums, so adding a value is a plain migration.

Immutable after insert: `content`, `content_hash`, source identity, `ingestion_key`, the original actor and the creation timestamp. An ORM guard rejects rewrites. A correction is a new record that supersedes the old one.

## Ingestion

`ingest_memory(db, ctx, item, origin)` runs in this order:

1. Derive company and actor from the server context. Callers never supply them, nor trust, hash or lifecycle identity.
2. Validate scope and ownership, and validate the source reference inside the same company.
3. Sanitize and redact recursively with `nexus.memory.safety`, then normalize deterministically.
4. Hash with SHA-256 and derive the ingestion key.
5. Insert an append-only row. On a uniqueness race, return the winner.
6. Audit safe metadata only (ids, hash, source). The audit row never holds memory content.

It makes no LLM call, writes no file and holds no transaction across model or network work.

### Idempotency

The ingestion key is a SHA-256 over company, source type, source id, extractor version, item key, the content digest, and a binding of scope, agent, scope id and memory type. `(company_id, ingestion_key)` is unique.

- Same key, same payload: the existing record is returned.
- Same key, different payload: `MEMORY_IDEMPOTENCY_CONFLICT` (409).
- Concurrent identical ingestion yields exactly one row.
- The same text from different sources is stored as separate records. `(company_id, scope, content_hash)` is deliberately not unique.

Public API writes accept an `Idempotency-Key` header, bound to the authenticated company, actor and canonical payload.

### Chat provenance

A chat-extracted fact has `source_type=chat_reply` and `source_id` = the durable ChatTurn id, set by the server; the model and the browser cannot supply it. The item key is `<category>:<ordinal>` (the ordinal counts within the category, in reply order), and the extractor version is `FACT_EXTRACTOR_VERSION`. Together with the content digest, retrying extraction for the same turn derives the same keys and returns the existing rows. Two facts in one reply stay distinct; the same fact twice in one reply is one row; identical text from different turns keeps separate provenance.

The response message id does not exist at extraction time (the reply is persisted after the model call), so it is not part of the key and no event id is invented. Model calls made outside a chat turn (scheduler, webhooks, orchestrator) use `source_id = reply:<sha256(agent, reply)[:40]>`, so a retry of the same reply still collapses. No random id is used as a logical source id. `PersistentLayeredMemory.store_fact` also keeps its near-duplicate check against live L2 rows, which can drop a repeat before ingest.

Supersession (`PATCH` with new content) is idempotent the same way: the successor's source is `memory_record:<old id>` with the content digest, so a retry returns the same replacement, a different replacement of an already-replaced record is `MEMORY_SUPERSESSION_CONFLICT` (409) and leaves no record behind, and a record of another company is `MEMORY_NOT_FOUND`.

### Trust defaults

| Origin | Status | Trust |
|--------|--------|-------|
| LLM-extracted chat fact | candidate | untrusted |
| Human-created memory, CEO human directive | active | asserted |
| Seed or import | active | asserted, with an explicit server-owned source |

Agents cannot set `verified`. Candidate memories never enter prompts.

## Lifecycle

`accept_candidate`, `archive_memory`, `reject_memory` and `supersede_memory` (plus `assert_trust` and `verify_trust`, below) are tenant scoped, use a conditional update, and are deterministic under concurrency. Each records the actor and time, writes an audit event, and keeps content and provenance. Repeating an identical transition returns the current result.

Stable error codes: `MEMORY_NOT_FOUND`, `MEMORY_ALREADY_ARCHIVED`, `MEMORY_INVALID_TRANSITION`, `MEMORY_SUPERSESSION_CONFLICT`, `MEMORY_IDEMPOTENCY_CONFLICT`.

Supersession creates the successor and closes the old record in one savepoint. If another writer closed the old record first, the successor rolls back and the caller gets `MEMORY_SUPERSESSION_CONFLICT`.

## Transactions

Ingest and lifecycle never commit or roll back. The caller owns the transaction: routes and services commit once at their boundary, and a rollback removes the memory row, its audit event, and any status change or supersession link together. The unique-key race is handled with a savepoint (`begin_nested`), never a full `session.rollback()`, so the caller's unrelated work is untouched.

`ingest_memory`, `archive_memory`, `reject_memory` and `supersede_memory` all start with `begin_write(db)`. On PostgreSQL it does nothing: every statement already runs inside a real transaction, so a savepoint is nested in it. SQLite differs. Its driver only opens a transaction before the first insert, update or delete, not before a read or a `SAVEPOINT`. A write that begins with a read and a savepoint therefore runs the savepoint as the outermost transaction, and releasing it commits the row on its own. That breaks rollback atomicity, and it lets another writer take the lock before the audit insert, which then fails with `database is locked` (the audit chain's retries cannot help, because they run inside the same stale transaction).

On SQLite `begin_write` runs an update that matches no row, which starts the transaction and takes the write lock up front. It does not commit, replaces nothing the caller opened, and is harmless when repeated in one transaction (`supersede_memory` reaches it again through `ingest_memory`). It needs no WAL setting and uses no sleep or retry. `tests/test_memory_sqlite_transactions.py` covers rollback and commit atomicity, an explicit outer transaction, repeated calls and contention with a background writer.

## Hard deletes

No production path deletes a `memory_records` row.

| Path | Behavior |
|------|----------|
| `DELETE /api/v1/memory/{id}` (`memory_global.delete_memory`) | `archive_memory`, reason `deleted`; 204 |
| `POST /api/v1/memory/{id}/archive` | `archive_memory`, tier `cold` |
| L2 overflow in `store_fact` | archives the oldest live rows, reason `l2 capacity` |
| L3 (shared) | no eviction; promotion inherits the parent's status |
| `MemoryStore.demote` / `archive_old` | writes the redacted cold file, then sets `tier=cold`; the PG row stays |
| Cold restore | re-ingests through `ingest_memory` (`cold_archive` source) |
| Maintenance (`orchestrator`) | decays `importance` of active rows only; never changes status, scope or tier, never deletes |
| CEO supersede / resolve | `supersede_memory` / `archive_memory`, audited |
| `delete(MemoryRecord)`, `db.delete(row)`, raw `DELETE FROM memory_records` | none in `src`; `tests/test_memory_write_path_guard.py` fails on any |

Exceptions: no code deletes a company's memory rows. `DELETE /companies/{id}` issues `delete(Company)`, and `memory_records.company_id` has no `ON DELETE CASCADE`, so the database refuses that delete while the company still has memory rows; a real erasure needs a separate, explicit purge that does not exist yet. The migration downgrade drops the added columns and keeps the rows. Tests and migrations may clean up their own data.

## Reads

Two lifecycle policies, both applied in SQL before ranking and `LIMIT`. Filtering closed rows in Python after the `LIMIT` is not allowed: a newer closed row would take the place of an active one and starve it.

### Prompt-visible: `active` only

`PROMPT_STATUSES = ("active",)` (`nexus.models.memory`). Any read whose result can reach a model returns active rows only. Candidate, archived, superseded and rejected rows never appear, and neither does their text, so a hostile string stored in a closed row cannot become a prompt injection.

| Reader | Notes |
|--------|-------|
| `ceo_service.recall` (CEO executive context, snapshot view, `ceo_search_executive_memory` tool) | Active only; it has no lifecycle parameter. The tool schema has no `include_closed` (`additionalProperties: false`), so a model that sends it, forged or from a legacy prompt, gets `invalid arguments` before any query and before any audit. There is no fallback to an active-only answer for that call. |
| `PersistentLayeredMemory.get_agent_facts`, `all_agent_facts`, `get_shared_knowledge`, `get_context_window` | L2 and L3. |
| `chat._fetch_agent_memories`, shared knowledge in chat | Through the readers above. |
| `MemoryStore.retrieve` (warm tier and hot cache) | See "Hot cache" below: hot entries are re-checked against the database on every call. |
| `GET /agents/{id}/memory/search` | BM25 over active rows. |
| `GET /companies/{id}/memory/graph` | Active rows. |

`store_fact` still reads candidate and active rows for near-duplicate detection and the L2 capacity check (`LIVE_STATUSES`). That is a write-path concern: it stops the same unreviewed fact from being stored again. It never returns those rows to a caller.

### Hot cache

`MemoryStore` keeps a per-process hot tier (`_hot`). Nothing invalidates it when a lifecycle function runs, so the read does the check instead of the writer:

- The cache key is `<company_id>:<scope>:<scope_id>`, so two companies never share a key.
- On **every** `retrieve`, not only when a key is warmed, the hot ids are re-queried with `company_id == caller` and `status IN PROMPT_STATUSES`. An entry that was archived, superseded or rejected, or that belongs to another company, is dropped from the answer.
- A transition in one company changes only that company's rows; another company's cached entries are still served and untouched.

Covered by `tests/test_memory_lifecycle_read_safety.py` (archive, supersede and reject through the real lifecycle functions after caching, repeated retrieves, cross-company isolation, an entry planted under another company's key).

### Review-visible: human administrator only, audited

Candidate and closed content is reachable only through a human review path, never through a model tool, an agent or run token, an API key or an ordinary member.

- **Authority:** `routes.memory.is_memory_reviewer`, which is the Governance Studio write predicate `errors.can_write` (a human `admin` of the caller's own company). The principal is built server-side from the session, the user's active flag and the membership row on every request, so a deactivated user or a removed membership fails, and nothing in a request body or header can raise it. A dedicated Governance Studio memory-review capability is **deferred**; until it exists this is the narrowest existing human authority.
- `GET /api/v1/agents/{id}/memory` and `GET /api/v1/companies/{id}/memory` take `?status=<candidate|active|archived|superseded|rejected>`. Without it, or with `active`, they return active rows for any caller. A non-active value is `403 MEMORY_REVIEW_FORBIDDEN` for a non-reviewer. An unknown value is `422 MEMORY_STATUS_INVALID`.
- `GET /api/v1/memory/{id}`: an active row is served to any caller in the company. A non-active row is `404` for a non-reviewer, the same answer as an unknown or foreign id, so the route is no oracle for closed memory.
- `GET /ceo/memory?include_closed=true` is the executive review path: reviewer only (`403`), through `ceo_service.review_recall`. The default call uses the active-only `recall`.
- **Audit:** every review read writes one `memory.review_read` audit row with the actor, the view (`agent_list:<state>`, `company_list:<state>`, `executive_list:all`, `detail:<state>`), a count and the memory ids. Never content.
- **Tenancy:** every query filters on the authenticated company. The company routes (`/companies/{company_id}/memory`, `/stats`, `/health`, `/graph`) conceal the tenant: any path company other than the caller's, whether it exists or not, gets the same `404` with the stable code `COMPANY_NOT_FOUND` and a fixed message. The decision compares the path with the caller's own company and never reads the path company, so nothing (rows, counts, ids, names, audit entries) can tell the cases apart. It is enforced in the auth middleware and again by the `MemoryCompanyId` route dependency; the global `PathCompanyId` (`403`) is unchanged for every other company route. A human admin's authority stops at their own company. A foreign memory id (`/memory/{id}`) is `404`.
- **Aggregates:** `/memory/stats` and `/memory/health` return counts only, scoped to the company; `by_status` counts every state but carries no content.
- No dashboard for review. Accepting a candidate and promoting trust are API-only (see "Evidence and governed trust").

### Compatibility impact

- The default list no longer returns candidates (client change since the previous phase: pass `?status=candidate`).
- A non-active `?status=` is now `403` for a non-admin caller (it was open to any company member).
- `GET /memory/{id}` of a non-active row is `404` for a non-admin.
- `/companies/{company_id}/memory*` with a company other than the caller's, existing or not, is `404 COMPANY_NOT_FOUND` instead of an empty or foreign-scoped answer.
- `include_closed` is gone from the CEO memory tool schema; a call that sends it is rejected. The operator REST flag is unchanged for a human admin.

`PATCH /api/v1/memory/{id}` edits `importance` and `tier` only on a live row; a closed row returns `409 MEMORY_INVALID_TRANSITION` and is left as it was. A content change appends a superseding record.

## Maintenance

`orchestrator._memory_maintenance(db, company_id)` runs once per company per tick on the existing scheduler. It adds no polling loop.

- Every statement filters on `company_id`; one company's tick cannot change another's rows.
- Decay lowers `importance` by 5% (floor 0.1) for **active** rows not accessed in seven days.
- **Candidates are not decayed.** An unreviewed row keeps its rank until it is accepted or rejected, and nothing recalls a candidate, so it is never legitimately "accessed". Archived, superseded and rejected rows are frozen.
- Only `importance` changes. Status, trust, tier, scope, content and lifecycle columns are untouched.
- The access counter update in `get_agent_facts` is tenant-scoped and also filters on `status`, so a read cannot touch or reactivate a closed row. Tier moves (`promote`, `demote`, `archive_old`) write `tier` and `updated_at` only; `promote` refuses a non-active row.
- Known limitation: decay compounds on every tick for rows that stay unaccessed.

## Write-path guard

`tests/test_memory_write_path_guard.py` covers creation and deletion. `tests/test_memory_lifecycle_write_guard.py` covers lifecycle and trust. It scans `src/` and `scripts/` and fails when production code outside `nexus.memory.lifecycle`:

- writes `status`, `trust_state`, `lifecycle_changed_at`, `lifecycle_changed_by` or `supersedes_id`, through `update(MemoryRecord).values(...)` (keyword, dict or `**` spread), attribute assignment, `setattr`, raw `UPDATE memory_records SET ...`, or a `MemoryRecord(...)` constructor outside ingest;
- updates `MemoryRecord` outside the four scoring modules (orchestrator, layered memory, store, memory routes), without a `MemoryRecord.company_id` filter, or touches `importance`, `access_count` or `last_accessed_at` without a `MemoryRecord.status` filter.

Tenant-scoped, lifecycle-safe updates to `access_count`, `last_accessed_at`, `importance`, `tier` and `updated_at` are allowed. Migration and backfill exceptions are listed in `MIGRATION_EXCEPTIONS` with a reason; it is empty because Alembic revisions are outside the scanned trees.

The same file guards the evidence tables. It fails when production code:

- constructs `MemoryEvidence` or `MemoryOperation` anywhere but `nexus.memory.evidence`, or inserts, updates, deletes, assigns an immutable field of, or runs raw `INSERT`/`UPDATE`/`DELETE`/`TRUNCATE`/`DROP` on `memory_evidence` or `memory_operations` outside it;
- selects either table without a `company_id` filter;
- names `accept_candidate`, `assert_trust`, `verify_trust`, `attach_evidence`, `list_evidence`, `run_once` or `require_human_admin` outside the lifecycle module, the evidence module and the evidence routes;
- adds a model tool whose schema takes `include_closed`, `status`, `trust_state`, `evidence_id`, `memory_id` or similar, or whose name pairs memory with evidence, trust, accept or verify;
- adds a module that selects `MemoryRecord` without classifying it: a prompt reader must filter on `MemoryRecord.status` / `PROMPT_STATUSES`, and anything else must be a lifecycle module.

## Evidence and governed trust

Two orthogonal axes on every memory:

- `status` decides **prompt eligibility**. Only `active` reaches a model.
- `trust_state` records **evidence-backed trust**. `verified` is not prompt eligibility: a verified memory is still an ordinary memory that can be archived or superseded, and an `active` memory that was never verified is still served.

```
status:   candidate --accept--> active
          candidate --reject--> rejected
          candidate or active --archive--> archived
          candidate or active --supersede--> superseded

trust:    untrusted --assert--> asserted --verify--> verified      (no downgrade)
```

Accepting a candidate changes status only. Asserting or verifying changes trust only, and only on an `active` memory. The two are never combined silently. There is no trust downgrade: a wrong memory is corrected with archive, reject or supersede, and a successor starts as a new record with its own trust.

### Transition matrix

| Operation | From | To | Needs |
|-----------|------|----|-------|
| accept | status `candidate` | `active` | human admin |
| assert | `active` + `untrusted` | `asserted` | human admin, evidence graded `assert` or `verify` |
| verify | `active` + `asserted` | `verified` | human admin, evidence graded `verify` |

Anything else is `409 MEMORY_INVALID_TRANSITION` (closed or superseded memory, wrong current state, a competing writer won). Memories that ingest already created as `asserted` (human and API origin, seeds) skip the assert step and can go straight to verify once active.

### Evidence rows

`memory_evidence` is durable, append-only and company scoped. A row holds ids and digests, never content:

| Column | Meaning |
|--------|---------|
| `company_id`, `memory_id` | Owner and target; both `ON DELETE RESTRICT`. |
| `evidence_kind`, `source_type`, `source_id` | What the evidence is and the exact source row (`user`, `chat_turn`, `tool_invocation`, `task_attempt`). `source_id` is a string because the source table varies. |
| `reason_code` | Attestation reason from a fixed list; `''` otherwise. |
| `grade` | `none`, `assert` or `verify`: what the evidence can support, derived by the server. |
| `source_digest` | SHA-256 over the source's qualifying state (ids and flags, never content). |
| `policy_version` | `memory-evidence-v1`. |
| `created_by`, `created_at`, `idempotency_key` | Server-stamped actor, time and the caller's key. |

Unique on `(company_id, memory_id, source_type, source_id, reason_code)`, so the same source cannot be attached twice, and on `(company_id, idempotency_key)`. A caller cannot supply company, grade, digest, actor, trust or any qualification outcome: the request schema rejects unknown fields and has no such fields. Rows are immutable: ORM `before_update`/`before_delete` listeners raise, and database triggers refuse `UPDATE` and `DELETE` even for the table owner or a superuser. `memory_operations` (the idempotency ledger below) is append-only the same way.

### Qualification policy (`memory-evidence-v1`)

| Evidence | Grade | Why |
|----------|-------|-----|
| `human_attestation`, reason `reviewed_by_admin` | `assert` | The attester is the calling administrator, re-read as an active admin of the company. It supports asserting, never verifying. |
| `human_attestation`, reason `independently_verified_by_admin` | `verify` | An explicit statement by a named human administrator that they checked the claim independently. |
| `chat_turn` | `none` | Provenance only. A turn proves who said what, never that it is true. ChatTurn evidence cannot verify truth, alone or combined. |
| `tool_invocation` | `assert` if the run succeeded, a person approved it, access control allowed it and it completed; else `none` | A tool running proves the tool ran, not that its output is true. It can support asserting and never verifying. |
| `task_attempt` | `verify` only if the stored verifier result passed: attempt `completed`, reason `goal`, no error, every recorded check passed; else `none` | The only existing durable record of deterministic completion proof. A task without a passed verification, or in another company, does not qualify. |

Agent-authored text, an LLM opinion and the memory itself are not evidence, and no agent, chat extractor, tool response or background job can create evidence or promote trust: every route needs a human administrator and no model tool exposes any of it, so agents cannot self-verify. Anything ambiguous is `none` and is recorded as such.

Evidence is **re-derived at transition time**. `requalify` reloads the source in the caller's company (locking it `FOR UPDATE` on PostgreSQL), recomputes the digest and grade, and refuses with `409 MEMORY_EVIDENCE_STALE` if the source changed or disappeared since it was attached. A stale transaction therefore cannot verify with evidence that became invalid before commit.

### Authorization

Every evidence and promotion route is for a human company administrator, the Governance Studio write predicate `errors.can_write`, then re-checked in the database where the write happens: the actor is `user:<id>`, the user is active, the membership exists and its role normalizes to `admin`. A viewer, member, agent, run token, API key, deactivated user or removed membership fails with `403 MEMORY_EVIDENCE_FORBIDDEN`, before any memory, evidence or source is looked up. The development-fallback principal has no user, so it cannot mutate. Evidence listing is human-admin only as well. The company in the path is the caller's own or a fixed `404 COMPANY_NOT_FOUND` (see "Review-visible"); a foreign memory or evidence id answers the same `404` as one that does not exist.

### API

All paths are under `/api/v1/companies/{company_id}/memory/{memory_id}`. Request bodies reject unknown fields. Responses carry ids and states only.

| Method and path | Body | Result |
|-----------------|------|--------|
| `POST /evidence` | `evidence_kind`, `source_id` (not for an attestation), `reason_code` (attestation only) | `201` evidence view |
| `GET /evidence` | none | `200 {"evidence": [...]}`, oldest first, audited |
| `POST /accept` | none | `200` `{memory_id, status, trust_state, from_status}` |
| `POST /trust/assert` | `evidence_id` | `200` `{memory_id, status, trust_state, from_trust_state, evidence_id}` |
| `POST /trust/verify` | `evidence_id` | same shape |

Stable error codes: `MEMORY_EVIDENCE_FORBIDDEN` (403), `MEMORY_NOT_FOUND`, `MEMORY_EVIDENCE_NOT_FOUND` and `MEMORY_EVIDENCE_SOURCE_NOT_FOUND` (404), `MEMORY_EVIDENCE_INVALID` (422), `MEMORY_EVIDENCE_DUPLICATE`, `MEMORY_EVIDENCE_NOT_QUALIFYING`, `MEMORY_EVIDENCE_STALE`, `MEMORY_INVALID_TRANSITION`, `MEMORY_ALREADY_ARCHIVED` and `MEMORY_IDEMPOTENCY_CONFLICT` (409), `IDEMPOTENCY_KEY_REQUIRED` and `IDEMPOTENCY_KEY_INVALID` (422). Evidence can be attached to a candidate or active memory; attaching it to a closed one is `MEMORY_INVALID_TRANSITION`. Promoting trust needs an `active` memory.

### Idempotency and races

Mutations require `Idempotency-Key` (8 to 128 characters of letters, digits and `. _ : -`). The generic idempotency middleware stands aside for these paths (it answers 422 on a payload mismatch; here the answer is 409). Each request writes one `memory_operations` row in the same savepoint as its effect. It is unique on `(company_id, idempotency_key)` and holds the operation, the memory id, a digest of operation, memory, actor and body, the actor and the result.

- Same key, same request: the stored result is returned with `Idempotency-Replayed: true`. No second effect, no second audit row.
- Same key, different request (another body, memory, actor or operation): `409 MEMORY_IDEMPOTENCY_CONFLICT`.
- Concurrent identical requests: one wins the unique constraint; the others re-read the ledger and replay.
- Transitions are tenant-scoped conditional `UPDATE`s checking the current status or trust. Accept vs reject, accept vs supersede, assert vs assert and verify vs archive or supersede have exactly one winner; the loser gets `MEMORY_INVALID_TRANSITION` and leaves no evidence, ledger or audit residue. There are no sleeps or polling loops.
- The caller owns the transaction. The transition and its audit row commit or roll back together; a failed request leaves nothing behind.

### RLS

Both tables have row-level security enabled and forced, with a `tenant_isolation` policy on `company_id = nexus.company_id` (the existing `tenant_session` convention) for `USING` and `WITH CHECK`. An unbound session reads nothing and cannot insert, and the table owner is bound too. A same-company trigger refuses a row whose `memory_id` belongs to another company (a foreign key alone would accept it), on PostgreSQL and SQLite. Because that trigger fires before the policy check, a forged cross-company insert may be refused by either; both are refusals.

### Audit

All events are content-free: ids, states, kinds, grade, policy version, actor and idempotency key. They never carry memory, chat, tool arguments, deliverables or credentials.

| Action | Details |
|--------|---------|
| `memory.evidence_attached` | evidence id, kind, source type and id, reason code, grade, policy version, idempotency key |
| `memory.accepted` | from and to status, idempotency key |
| `memory.trust_asserted`, `memory.trust_verified` | from and to trust state, evidence id, kind, source type, grade, policy version, idempotency key |
| `memory.evidence_reviewed` | count and evidence ids |

### Limitations and deferred work

- `source_id` points at one of several tables, so it has no foreign key. The service validates it in the caller's company at attach and again at promotion, and the same-company trigger covers `memory_id` only.
- Nothing downgrades trust, and nothing re-opens a verified memory automatically when its source later changes; correct it with archive, reject or supersede.
- No retrieval-ranking change: trust does not influence recall order or eligibility.
- No automatic learning or verification, no agent self-verification, no dashboard for evidence, no broader trust scoring.
- Dev-fallback principals cannot mutate.
- Evidence kinds beyond the four above (for example external documents or signed approvals) are not modeled.

## Migration

`f1b7c9d2a508` follows `e7a1c2d3f407`. The backfill is deterministic: ordinary rows become `active`, metadata-marked untrusted candidates become `candidate`/`untrusted`, human and API rows become `asserted`, `memory_type` comes from metadata or scope (else `unknown`), and `content_hash` comes from stored content. Legacy rows get the key `legacy:<id>`. Source fields are filled only where the row itself names a real message or turn. Content is never rewritten, deleted or merged. Row-level security stays forced on PostgreSQL.

`b4d9f2a61c73` follows `e7a1c2d3f408`. It creates `memory_evidence` and `memory_operations`, their indexes, constraints and triggers, and enables and forces RLS on PostgreSQL. It leaves every `memory_records` row and the status and trust constraints unchanged. Downgrade drops the policies, triggers, tables and the two trigger functions it created and nothing else. The downgrade destroys all evidence and idempotency history: nothing is exported, and a later upgrade recreates the tables empty. On PostgreSQL the recreated tables carry no grants, so a deployment that grants table access to an application role must grant on them again.

While a memory has evidence, the foreign keys from `memory_evidence` and `memory_operations` to `memory_records` and `companies` are RESTRICT and the append-only triggers refuse UPDATE and DELETE, so that memory cannot be hard-deleted and neither can its company. PostgreSQL reports SQLSTATE 23503 for the memory (`memory_evidence_memory_id_fkey`). For a company the first constraint to fire is not necessarily an evidence one: on a freshly migrated database it is `audit_log_company_id_fkey`, because the company also has audit rows. SQLite refuses with an integrity error once `PRAGMA foreign_keys` is on, which each connection must enable.

## Not covered here

Autonomous promotion, verified agent learning, retrieval fusion, entity graphs, Obsidian projection and embeddings redesign are separate work.
