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

## Reads

Readers select `LIVE_STATUSES` (candidate, active) in SQL before any `LIMIT`. Readers that feed prompts (agent recall and shared L3 knowledge in chat) read `active` rows only, so a candidate never reaches a prompt until something makes it active.

## Migration

`f1b7c9d2a508` follows `e7a1c2d3f407`. The backfill is deterministic: ordinary rows become `active`, metadata-marked untrusted candidates become `candidate`/`untrusted`, human and API rows become `asserted`, `memory_type` comes from metadata or scope (else `unknown`), and `content_hash` comes from stored content. Legacy rows get the key `legacy:<id>`. Source fields are filled only where the row itself names a real message or turn. Content is never rewritten, deleted or merged. Row-level security stays forced on PostgreSQL.

## Not covered here

Autonomous promotion, verified agent learning, retrieval fusion, entity graphs, Obsidian projection and embeddings redesign are separate work.
