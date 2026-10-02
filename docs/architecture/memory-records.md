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

`archive_memory`, `reject_memory` and `supersede_memory` are tenant scoped, use a conditional update, and are deterministic under concurrency. Each records the actor and time, writes an audit event, and keeps content and provenance. Repeating an identical transition returns the current result.

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
| `ceo_service.recall` (CEO executive context, snapshot view, `ceo_search_memory` tool) | Active by default. The tool's `include_closed` argument is accepted for compatibility but ignored: tool output is model-visible. |
| `PersistentLayeredMemory.get_agent_facts`, `all_agent_facts`, `get_shared_knowledge`, `get_context_window` | L2 and L3. |
| `chat._fetch_agent_memories`, shared knowledge in chat | Through the readers above. |
| `MemoryStore.retrieve` (warm tier and hot cache) | Hot entries are re-checked against the database, so an entry closed after it was cached is dropped. |
| `GET /agents/{id}/memory/search` | BM25 over active rows. |
| `GET /companies/{id}/memory/graph` | Active rows. |

`store_fact` still reads candidate and active rows for near-duplicate detection and the L2 capacity check (`LIVE_STATUSES`). That is a write-path concern: it stops the same unreviewed fact from being stored again. It never returns those rows to a caller.

### Review-visible: explicit

`LIVE_STATUSES = ("candidate", "active")` names what an administrative list may show, but the list endpoints now default to `active` and show anything else only when asked.

- `GET /api/v1/agents/{id}/memory` and `GET /api/v1/companies/{id}/memory` accept `?status=<candidate|active|archived|superseded|rejected>`. Without it they return `active`. An unknown value is `422 MEMORY_STATUS_INVALID`.
- **Contract change:** before this, the default listing also included candidates. A client that reviews candidates must now pass `?status=candidate`. Rows include `status` and `trust_state`.
- `GET /ceo/memory` is the operator-only executive review path; `include_closed=true` shows every status.
- Tenant isolation is unchanged: every query filters on the authenticated company.
- No new dashboard or acceptance workflow. Accepting a candidate is deferred (see below).

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

## Verified learning is deferred

Nothing here promotes a memory. There is no `candidate -> active` acceptance, no `untrusted -> asserted -> verified` change, no automatic promotion and no evidence metadata invented to justify one. `verified` and candidate acceptance need the future `memory_evidence` table, so a trust change can point at the source that supports it. Until then the only trust states a row ever has are the ones ingest assigns at insert.

## Migration

`f1b7c9d2a508` follows `e7a1c2d3f407`. The backfill is deterministic: ordinary rows become `active`, metadata-marked untrusted candidates become `candidate`/`untrusted`, human and API rows become `asserted`, `memory_type` comes from metadata or scope (else `unknown`), and `content_hash` comes from stored content. Legacy rows get the key `legacy:<id>`. Source fields are filled only where the row itself names a real message or turn. Content is never rewritten, deleted or merged. Row-level security stays forced on PostgreSQL.

## Not covered here

Autonomous promotion, verified agent learning, retrieval fusion, entity graphs, Obsidian projection and embeddings redesign are separate work.
