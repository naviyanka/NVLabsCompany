# ADR 0002 — Obsidian owns durable knowledge documents; PostgreSQL owns operational entities

**Status:** Accepted
**Date:** 2026-08-29
**Relates to:** `docs/Obsidian_Integration_Purposal.md` §29 Phase 0 (lines 1296–1304), which requires the
data-ownership and migration boundaries to be mapped before production code is modified. This ADR is that
map, and it gates Phase 1. No implementation code exists or is authorised by this document.

## 1. Context

`docs/Obsidian_Integration_Purposal.md` proposes Obsidian as the human-readable knowledge substrate for
NEXUS, retaining PostgreSQL, pgvector, Redis and Temporal as the operational/machine layer. The proposal
closes at line 1559 with: *"Do not start coding until the existing data ownership and migration boundaries
have been mapped."*

A repository audit was run across six boundaries — knowledge pages, memory, retrieval, graph, synchronisation,
and security/surface — each mapped against the real code and then adversarially challenged by an independent
reviewer. Obsidian has zero implementation today: no `obsidian` module, no routes, no tools, no watcher, no
frontmatter parser. The only artifacts are the proposal and an untracked, effectively empty vault at
`NVLabsCompany/` (`.obsidian/` plus `Welcome.md`; `git status` reports `?? NVLabsCompany/`).

The audit changed what the proposal means in practice, in five ways recorded in §3 and §4 below.

## 2. Current architecture

**Knowledge, DB-backed.** `src/nexus/models/knowledge.py:15` `KnowledgePage` holds `title`, `content`,
`category`, `tags`, `version`, `status`, `author_agent_id`, and an indexed `company_id` FK. `:41`
`KnowledgeChunk` holds chunked content plus `embedding_vector` typed `Vector(1536)` on PostgreSQL with a
SQLite JSON variant. `:64` `ExperienceRecord` holds `outcome`, `approach`, `result_quality`,
`lessons_learned`, `tags`, and FKs to `agents` and `tasks`.

**Access layer.** `src/nexus/knowledge/plaza.py:45` `KnowledgePlaza` creates, updates and searches pages,
and provides in-process page locking and change subscriptions. `src/nexus/knowledge/experience.py`
manages `ExperienceRecord`. `src/nexus/knowledge/rag.py:36` `RAGPipeline` chunks, embeds, indexes and
searches, with hybrid vector plus token-overlap ranking and context assembly.

**Retrieval support.** `src/nexus/knowledge/embeddings.py` provides OpenAI, Ollama, local-stub and null
providers. `retrievers.py` provides dense, sparse and hybrid retrievers. `rankers.py` provides BM25,
cross-encoder and a reranker pipeline. `parsers.py:170` `MarkdownParser` splits markdown by header, code
block, list and paragraph.

**API.** `src/nexus/api/routes/knowledge.py` exposes publish, list, get, update, history, RAG search,
experience record/search, stats, categories, delete and import.

**Graph.** `src/nexus/api/routes/memory_graph.py:16` derives nodes and edges from `MemoryRecord` rows at
request time. Nothing is persisted. The dashboard consumes it through
`dashboard/src/lib/memoryGraphAdapter.ts` and `dashboard/src/pages/MemoryGraph.tsx`.

**Memory.** `src/nexus/models/memory.py:11` `MemoryRecord` carries `scope`, `tier`, `importance`,
`access_count`. `src/nexus/memory/store.py:33` `MemoryStore` implements three tiers.
`src/nexus/memory/promotion.py:34` `PromotionEngine` promotes L2 agent facts to L3 shared knowledge.

**Tenancy.** `src/nexus/governance/tenant_guard.py:103` `validate_company_id`, `:145`
`inject_query_filter`, `:226` `detect_cross_tenant_access`. `scripts/arch_guard.py` rule R5 fails CI on an
unscoped query against a tenant table in `api/routes/`.

**Portability.** `src/nexus/services/portability_service.py:92` `CompanyPortabilityService.export_company`
walks every table carrying `company_id`, then follows foreign keys to reach child rows.

**Durable execution.** `src/nexus/temporal/` holds `GoalPursuitWorkflow` and `PipelineExecutionWorkflow`.
Per ADR 0001, Temporal is the single authoritative execution path.

## 3. Existing duplication

**Two knowledge stores exist, and one is dead.** `src/nexus/knowledge/graph.py:23` `KnowledgeManager` is a
second, entirely separate file-backed knowledge store: its own `index.json`, its own chunk directory under a
filesystem root, its own BM25 search via `nexus.memory.retriever`, its own atomic index writes (`mkstemp`
plus `os.replace`), and its own `ingest_file` / `ingest_text` / `search` / `list_docs` / `remove_doc` /
`stats` surface. A repository-wide search for its symbol finds callers only in
`tests/test_knowledge_graph.py`. It is absent from `src/nexus/knowledge/__init__.py`'s exports. There is no
production call site.

The proposal's instruction not to create a second knowledge source of truth describes a condition the
repository is already in.

**Three filesystem content copies already exist.** `KnowledgeManager`'s root, `MemoryStore`'s cold tier
(`data/cold_memory`, `src/nexus/memory/store.py:61`), and — once introduced — the vault. The cold-memory
archive is low-value archived memory, not knowledge; the vault indexer must never walk `data/`.

**Memory content has three physical homes before Obsidian is added.** `src/nexus/models/memory.py:16`
documents the hot tier as Redis. `src/nexus/memory/store.py:60` implements it as an in-process dict. Warm is
`memory_records`; cold is JSON files. The docstring is wrong and is corrected before any ownership statement
cites it.

**Version history is not version history.** `src/nexus/api/routes/knowledge.py:225` `get_page_history`
selects `KnowledgeChunk` rows ordered by `chunk_index` and returns them as history entries. There is no
page-version table anywhere in `src/nexus/models/`. `KnowledgePage.version` is an integer that no code
increments into a stored prior revision. `plaza.py:433` `get_page_history` has the same shape.

## 4. Problem statement

Four problems, each concrete.

**The proposal's framing implies knowledge leaves PostgreSQL. It cannot.**
`KnowledgeChunk.embedding_vector` is a fixed-width pgvector column, and `src/nexus/knowledge/rag.py:376-385`
enforces that width at write time. A vault note still produces PostgreSQL rows. The ownership boundary runs
*inside* a single document — body versus derived index — not between two systems. Left unstated, Phase 2
indexing inherits an undefined write path.

**Tenancy has no filesystem answer.** `KnowledgePage`, `KnowledgeChunk` and `MemoryRecord` all carry indexed
`company_id` FKs. A filesystem path carries no `company_id`. The proposal mentions tenancy twice in 1559
lines — "cross-tenant access" at line 1218 and a `[ ] tenant isolation enforced` checkbox at line 1449 — and
never decides the vault topology. That decision determines the config schema, the path validator, the
indexer's scoping, and whether a provider can satisfy tenant isolation at all.

**There is no filesystem-safety primitive to build on.** A search of `src/**/*.py` for `is_relative_to`,
`realpath`, `resolve().relative_to`, `os.path.commonpath` and the phrase "path traversal" returns nothing.
`src/nexus/guardrails/` holds content guardrails (`chain.py`, `policy.py`, `protocol.py`, `structural.py`),
not path validators; the modules named "sandbox" are process and eval sandboxes. Proposal §18 asks for five
controls and all five are new.

**A vault-backed body is invisible to company export.** `CompanyPortabilityService` walks tables. It cannot
see a filesystem. Every body moved to the vault silently drops out of export and import — a data-loss path,
not a feature gap.

## 5. Considered alternatives

**Keep PostgreSQL authoritative and treat the vault as an export target.** The smallest possible change, and
genuinely tempting. Rejected: it delivers none of the proposal's value. Humans cannot author, Git holds no
authoritative history, and a human edit to an exported note is discarded on the next export. It is a
Markdown export feature wearing an architecture proposal's clothes.

**Single shared vault with company-prefixed subtrees.** Rejected: isolation becomes a per-read authorisation
check against a shared filesystem, duplicating in Python what `tenant_guard.py` already does in SQL, and
cross-tenant note titles leak into Obsidian's own graph and backlink panes, which have no concept of a
tenant.

**Repurpose `KnowledgeManager` as the vault indexer.** It already contains file indexing, chunking and
atomic index writes. Rejected: it duplicates `RAGPipeline` and `KnowledgeChunk` wholesale, so adapting it
costs more than reusing the live path, and promoting a store with no production callers to production status
inverts the evidence. Its atomic-write pattern is retained as a pattern; its code is not.

**Delete `KnowledgePage` and let the vault own bodies outright.** Rejected: `KnowledgePage` is imported by
`plaza.py:18`, `api/routes/knowledge.py:13` and `models/__init__.py:26`, and serves types that are not in
Phase 1 scope. Deleting a table because it is theoretically redundant is how a migration becomes an outage.

**Watcher-based synchronisation in Phase 1.** Rejected: `watchdog` is not a declared dependency, and a poll
loop would collide with `scripts/arch_guard.py` rule R2, which permits exactly one tick loop
(`runtime/scheduler.py`). Neither cost is justified before the explicit path is proven.

**Agent write tools in Phase 1.** Rejected. See §23 and §24: the read-only architecture is validated first.

**Defer the security module and ship read-only tools first.** Rejected. Read-only access still needs
traversal, boundary, symlink, extension and size controls; only secret scanning and atomic-write concerns are
write-specific. Deferring saves two controls out of seven and leaves the trust boundary undefined while code
is already reaching the filesystem.

## 6. Final decision

Obsidian owns durable human-readable knowledge documents. PostgreSQL owns operational entities and state.

The governing rule, which supersedes any folder- or type-based reading of the proposal's §5 vault tree:

> A Markdown document may **project** an operational entity, but Markdown must never become the
> authoritative state for entities whose correctness depends on transactional relationships with agents,
> tasks, workflows, incidents, budgets, approvals, or other operational records.

Folder and frontmatter `type` are organisational conventions, not the ownership boundary. The boundary is the
transactional-relationship test: if correctness depends on a transactional relationship with an operational
record, PostgreSQL is authoritative and any note is a read-only projection.

Phase 1 is **read-only**. No agent write capability exists in Phase 1.

## 7. Data ownership matrix

`type` values are from proposal §6 (lines 338–354). "Authoritative body" is where the prose lives such that
an edit there is the real edit.

| `type` | Authoritative body | Derived index | Operational FKs | Phase 1 | Classification |
|---|---|---|---|---|---|
| `knowledge` | Obsidian | PostgreSQL | none | yes | active |
| `decision` | Obsidian | PostgreSQL | none | yes | active |
| `adr` | Obsidian | PostgreSQL | none | yes | active |
| `research` | Obsidian | PostgreSQL | none | yes | active |
| `procedure` | Obsidian | PostgreSQL | none | yes | active |
| `architecture` | Obsidian | PostgreSQL | none | yes | active |
| `project` | Obsidian | PostgreSQL | none | yes | active |
| `lesson` | Obsidian (prose) | PostgreSQL | `agents`, `tasks` | yes | split — see below |
| `memory` | PostgreSQL | PostgreSQL | `agents` | no | active |
| `meeting` | PostgreSQL | PostgreSQL | `agents` | no | active |
| `incident` | PostgreSQL | PostgreSQL | operational | no | active |
| `agent` | PostgreSQL | PostgreSQL | operational | no | active |
| `task` | PostgreSQL | PostgreSQL | operational | no | active |

The eight Obsidian-authoritative rows are Phase 1 scope. Every PostgreSQL row fails the transactional test
in §6 and stays where it is; a note about one is a projection, and a human edit to a projection is not
authoritative and does not write back.

**`lesson` is the one deliberate split.** `ExperienceRecord` (`models/knowledge.py:64-84`) mixes operational
telemetry with durable prose. `outcome`, `result_quality` and the `task_id` FK fail the transactional test
and stay in PostgreSQL. `lessons_learned` is prose with no transactional dependency and becomes a vault note
body referenced from the row. The row is not deleted.

A type whose row cannot be filled is out of Phase 1 scope. `memory` promotion into the vault is deferred
entirely (§24).

## 8. KnowledgePage decision

**Classification: active in Phase 1; `content` becomes `projection` for Obsidian-backed types.**

`KnowledgePage` is **not deleted**. It is imported at `plaza.py:18`, `api/routes/knowledge.py:13` and
`models/__init__.py:26`, and it remains the row for every type outside the Phase 1 set.

Its migration target is metadata and projection, not canonical body:

```text
KnowledgePage  →  metadata / projection row
                  (id, company_id, title, category, tags, status,
                   author_agent_id, timestamps)
```

Per-field classification:

| Field | Classification | Note |
|---|---|---|
| `id`, `company_id` | active | identity and tenancy |
| `title`, `category`, `tags`, `status` | active | queried metadata; mirrored from frontmatter for vault-backed docs |
| `author_agent_id` | active | operational FK |
| `created_at`, `updated_at` | active | |
| `content` | projection | authoritative in the vault for Obsidian-backed types; retained as a read cache |
| `version` | migration-only | not maintained for vault-backed types; Git is the version mechanism |

Whether `content` is eventually dropped or kept permanently as a cache is deferred to a Phase 1 read-path
audit against `plaza.py` (§27 tracks this). Retaining it as a cache is the reversible default. No field is
dropped in Phase 1.

## 9. KnowledgeManager decision

**Classification: DEPRECATE / REMOVE.**

Production-call-site analysis is zero: the only callers of `src/nexus/knowledge/graph.py:23` are in
`tests/test_knowledge_graph.py`, and it is not exported from `src/nexus/knowledge/__init__.py`. Removal is
subject to one final dependency verification at the start of Phase 1 (§27).

**Why it is being removed.** Keeping a second file-backed knowledge store alive while introducing a third
(the vault) is precisely the duplication the proposal exists to reduce. It has no production consumers to
protect, so removal carries no behavioural risk.

**What tests are affected.** `tests/test_knowledge_graph.py` is removed with it. No other test file
references the symbol. No production test coverage is lost, because no production code path is covered.

**What reusable patterns are retained.** The atomic index-write pattern — write to a `mkstemp` temporary,
then `os.replace` onto the target — is carried into the vault indexer as a pattern. Its chunking and its
BM25 search are not: `RAGPipeline` and the `rankers.py` BM25 implementation already cover both.

**What replaces it.** Nothing directly. The vault indexer is new code built on `MarkdownParser`,
`RAGPipeline` and `KnowledgeChunk`. Its architecture is *not* derived from `KnowledgeManager`; possessing
file-indexing code is not a reason to inherit a design.

## 10. Obsidian role

Obsidian is the authoring and reading surface for durable human-readable knowledge documents, and the
authoritative home of their bodies for the eight Phase 1 types in §7.

Obsidian is not a database, not a queue, not an index, and not a source of operational truth. It holds
Markdown files with YAML frontmatter, and NEXUS reads them.

In Phase 1, NEXUS's relationship to the vault is read-only. Humans write; NEXUS indexes.

## 11. PostgreSQL role

PostgreSQL remains the canonical operational datastore, unchanged in role by this ADR. It owns everything in
proposal §4, each of which the audit confirmed has a real home in the code: authentication, RBAC, sessions,
budgets, approvals, audit events, secrets, queues, Temporal workflow state, runtime telemetry, agent status,
current task, tool invocations.

It additionally owns, for vault-backed documents, all identity and index state (§17) and all derived
retrieval representations (§12).

## 12. KnowledgeChunk and pgvector role

`KnowledgeChunk` remains the derived retrieval representation, unchanged in shape. `embedding_vector` stays
`Vector(1536)` with the SQLite JSON variant. pgvector remains the semantic retrieval layer.

Chunks for vault-backed documents are derived data: cheap to discard and rebuild from the vault by reindex.
The vault owns the body; PostgreSQL owns every chunk, every vector, and the FK graph.

One change: the chunk's parent becomes an explicit polymorphic pair. `page_id` is renamed to
`source_id`, and a new `source_type` names the parent table (`knowledge_page` or
`obsidian_document`). Migration `c2f9a4d81b70` dropped the original single-target foreign key —
one column cannot reference two tables — and `d8e3b6c04a90` made the pair explicit, backfilling
every existing chunk to `knowledge_page` with its parent id unchanged.

An implicit `page_id` pointing at either table was the alternative, and it was rejected: a reader
could not tell which table a given chunk belonged to, and a delete filtered on id alone could reach
a chunk of a different document that happened to share a UUID. A `knowledge_sources` parent table
was also rejected — it buys real referential integrity, but at the cost of a join on every
retrieval path and a second row per document, which is more machinery than the two-provider case
needs.

`source_type` carries no database constraint either; correctness of the pair is enforced in
application code, and every query that resolves a parent filters on both columns.

## 13. RAG role

`src/nexus/knowledge/rag.py:36` `RAGPipeline` remains the RAG implementation. No parallel pipeline is
introduced. `src/nexus/knowledge/parsers.py:170` `MarkdownParser` is the parser for vault notes; frontmatter
extraction is added ahead of it, since the existing parser splits on markdown structure and has no
frontmatter awareness.

`embeddings.py`, `retrievers.py` and `rankers.py` are reused unchanged. Existing RAG search
(`api/routes/knowledge.py:255` `rag_search`) is the query surface for vault content; no new search endpoint
is added in Phase 1.

## 14. Graph role

Wikilinks are parsed during indexing and merged into the existing **derive-on-read** graph. No second
persisted graph, and no edge table.

`src/nexus/api/routes/memory_graph.py:16` already builds nodes and edges from rows at request time with
nothing persisted. That is the model to follow. Wikilink edges and explicit frontmatter relationships become
additional edge types on the same derived response; the operational relationships of proposal §22 are
already what `memory_graph.py` computes.

Node identity is namespaced by source — memory record, knowledge page, vault note — so a note and a memory
about the same subject are two nodes rather than a collision.

Proposal §23 (3D Office Integration) is **struck from scope**: commit `6a301c9` removed the 3D office and
kept the 2D floor.

Noted, not fixed here: `memory_graph.py` builds edges with an O(n²) pair scan over every memory in a company.
Adding vault nodes to that loop worsens an existing scaling ceiling.

## 15. Tenancy model

**One vault per company.** A single configuration value `obsidian_vault_root` is added to `Settings` in
`src/nexus/config.py`. A company's vault is:

```text
<obsidian_vault_root>/<company_id>/
```

Tenant isolation is a path root, not a per-read authorisation check. Obsidian's own graph and backlinks stay
tenant-scoped for free.

Every path derived from external input resolves through the §20 validator and must remain under the company
root after full symlink resolution. `obsidian_documents` carries `company_id` so that `tenant_guard.py` and
`arch_guard.py` rule R5 continue to apply to every query against it.

## 16. Vault layout

Within a company root, the layout follows proposal §5, reduced to the Phase 1 types:

```text
<obsidian_vault_root>/<company_id>/
├── Knowledge/
├── Decisions/
├── Architecture/
├── Research/
├── Procedures/
├── Projects/
└── Lessons/
```

Layout is convention for human navigation. It is **not** the ownership boundary — §6's transactional test is.
A note's `type` frontmatter, not its folder, drives indexing behaviour, so a misfiled note is still
classified correctly.

Only `.md` files are indexed (§20). The indexer never walks `data/`.

## 17. Identity model

A new table, `obsidian_documents`, owns identity and index state. None of these columns exist today:

```text
nexus_id              primary key, minted by NEXUS
company_id            tenancy, FK to companies.id
vault_path            mutable attribute, never identity
content_hash          change detection
mtime                 change detection
index_status          indexed | partial | failed | stale
embedding_model       recorded per document
embedding_dimension   recorded per document
indexed_at            timestamp
```

`nexus_id` is written into the note's frontmatter and mirrored in the row. This makes change classification
unambiguous: `nexus_id` present with a changed `vault_path` is a MOVE or RENAME; absence of the id is a
DELETE. Without it, a renamed file reindexes as a new document and leaves an orphan.

Identity cannot live in frontmatter alone — a MOVE would be undetectable — and cannot live on
`KnowledgePage`, which has no column for any of it.

Writing `nexus_id` into frontmatter is a file write, and Phase 1 is read-only for agents. Phase 1 mints ids
for notes lacking one via the operator-invoked sync path (§23), which is a system operation, not an agent
capability.

## 18. Git strategy

**The vault is a separate Git repository.** It is not nested inside the NEXUS repository. `NVLabsCompany/` in
its current location is a scratch artifact, not the vault: nesting a working vault inside the application repo
would put knowledge into application commits and application history into knowledge diffs.

Git is the version-history mechanism for vault-backed documents, replacing nothing (§19 records that no real
history mechanism exists today).

**No automatic Git commits in Phase 1.** Humans commit their own knowledge changes. Agent-proposed changes
reviewed as a Git branch (proposal §12) belong to the later write phase.

## 19. Portability strategy

`CompanyPortabilityService.export_company` (`services/portability_service.py:106`) walks tables carrying
`company_id` and follows FKs. It cannot see a filesystem, so a vault-backed body silently drops out of export
and import.

Phase 1 must do one of two things, and silence is not an option:

1. Extend the export to bundle vault files alongside `obsidian_documents` rows, or
2. Represent the gap explicitly in the export manifest, marking exports of vault-backed documents as partial.

Option 2 is acceptable for Phase 1 given read-only scope; option 1 is required before any agent writeback
phase, because from that point the vault holds content that exists nowhere else.

## 20. Security boundary

A new module owns filesystem safety. Nothing in the repository validates paths today, so every control below
is new. This is a trust boundary and is not simplified away.

### Phase 1 — read-only vault access

1. **Vault boundary.** The company root from §15 is the boundary. Escape is refused, never clamped.
2. **Path traversal.** Resolve the candidate path; require it to remain under the company root.
3. **Symlink protection.** Resolve fully *before* the boundary check; a link whose target leaves the root is
   refused.
4. **Extension allowlist.** `.md` only. Anything else is ignored rather than parsed.
5. **File size limits.** A maximum note size, enforced before read.
6. **Tenant isolation.** Company root derivation is the only way to reach a vault path; `obsidian_documents`
   queries stay `company_id`-scoped under `tenant_guard.py` and `arch_guard.py` R5.

The threat model includes machine-generated paths, not only hostile users, because indexing runs over
attacker-influenceable filenames.

### Future write phase — additional controls

7. **Secret scanning.** An agent write can persist a credential into a Git-tracked file, where deletion does
   not remove it from history. Writes are scanned before the file is written, and a positive match refuses
   the write rather than redacting it.
8. **Approval gates.** Via `src/nexus/governance/approvals.py`, for document types whose mutation authority
   is human.
9. **Audit logging.** Through the existing path (`src/nexus/tools/audit.py`), not a new log.
10. **Conflict handling.** Recompute `content_hash` on write and compare against `obsidian_documents`. Equal
    means safe; unequal means the file changed outside NEXUS and the write is refused with a conflict state.
    No automatic merge, per proposal §11.
11. **Atomic writes.** Temporary file plus `os.replace`, the pattern retained from `KnowledgeManager` (§9).
12. **Rollback.** Git revert over the vault repository.
13. **Agent write authorisation.** Per-agent, per-path authorisation, expressed against
    `src/nexus/tools/registry.py`'s existing `grant_access` / `has_access` model.

Controls 7–13 are specified here so the write phase inherits a decision rather than a debate. None are
implemented in Phase 1, because Phase 1 has no write path to protect.

## 21. Embedding policy

**Phase 1: the production Obsidian corpus is 1536-dimensional embeddings only.**

If a configured embedding provider produces any other dimension, **configuration validation fails** at load
time. `src/nexus/config_validator.py` is the enforcement point.

`src/nexus/knowledge/rag.py:376-385` currently detects a width mismatch on PostgreSQL, logs a warning, drops
the vectors, and returns success — retrieval silently degrades to keyword-only and nothing surfaces. That
behaviour is not acceptable for the vault corpus. Where a mismatch is nonetheless reached at index time (a
provider changing under a running system), the document's `index_status` is set to a failure state so it is
visible.

Config-load rejection is the gate; `index_status` is the backstop. Vectors are never silently dropped, and
retrieval never silently falls back to keyword-only without an exposed failure state.

`embedding_model` and `embedding_dimension` are recorded per document (§17) and compared on read.

## 22. Migration strategy

Ordered, each step independently reversible except where stated.

1. **Correct the memory docstring.** `src/nexus/models/memory.py:16` claims Redis for the hot tier;
   `memory/store.py:60` implements an in-process dict. Zero risk, and it must not be cited while wrong.
2. **Add `obsidian_documents`** (§17). Additive Alembic migration, no existing data touched. Reversible.
3. **Make the chunk's parent an explicit `source_type` / `source_id` pair** (§12). Two migrations:
   `c2f9a4d81b70` drops the single-target FK, `d8e3b6c04a90` renames and adds. Reversible while no vault
   rows exist.
4. **Add config surface:** `obsidian_vault_root`, plus the §21 dimension validation. Reversible.
5. **Verify and remove `KnowledgeManager`** (§9), with `tests/test_knowledge_graph.py`. Reversible via
   version control; irreversible in the sense that the code is gone, which is the intent.
6. **Build the read-only provider, validator, frontmatter parser and indexer.** New code, no existing data
   mutated.
7. **Index the vault.** Creates `obsidian_documents` and `KnowledgeChunk` rows. Fully reversible: delete the
   rows and reindex.
8. **Mark `KnowledgePage.content` as projection and `version` as migration-only** for Obsidian-backed types.
   No column dropped, no data deleted. Reversible.
9. **Deprecate `get_page_history`** (§27 records the decision path). No consumer breaks: a repository search
   found no dashboard, e2e or desktop caller of the history endpoint; `plaza.py:433` is the only internal
   caller.

**Nothing is deleted merely for being theoretically redundant.** `KnowledgeManager` is removed on evidence of
zero production callers, not on redundancy grounds.

Direction of movement: existing `KnowledgePage` rows are **not** bulk-migrated into the vault in Phase 1.
Phase 1 indexes what humans put in the vault. Migration of existing page bodies is a later phase and needs
its own reversibility analysis, because Markdown round-tripping is lossy for anything the schema captures
structurally.

## 23. Phase 1 scope

Phase 1 is exactly this pipeline, read-only:

```text
Obsidian vault
      ↓
secure read-only provider          (§20 controls 1–6)
      ↓
Markdown parser                    (frontmatter + parsers.py:170 MarkdownParser)
      ↓
existing chunker                   (RAGPipeline.chunk_document)
      ↓
existing embedding pipeline        (embeddings.py, 1536-dim enforced at config load)
      ↓
obsidian_documents metadata        (§17)
      ↓
KnowledgeChunk / pgvector          (unchanged shape)
      ↓
existing RAG search                (api/routes/knowledge.py rag_search)
```

Agent-facing operations permitted in Phase 1, and no others:

```text
list
read
search / status
sync / reindex
```

Explicitly not permitted for agents in Phase 1: `create`, `update`, `append`, `move`, `delete`.

Synchronisation is explicit and manual: an operator-invoked endpoint performing a full scan, comparing
`content_hash` and `mtime` against `obsidian_documents`. Full reindex is intended to run as a Temporal
workflow — `temporalio` is already a dependency, `src/nexus/temporal/` is already the durable-orchestration
home per ADR 0001, and the `indexed` / `partial` / `failed` / `stale` states need resumability an inline
request handler cannot give. A synchronous first implementation is acceptable if the Temporal wrapper lands
in the same phase.

UI additions in Phase 1 are status-only, extending `dashboard/src/pages/KnowledgeBase.tsx`: connection state,
vault path, last sync, indexed count, failure count. No editor.

## 24. Deferred functionality

Deferred to later phases, with the phase gate being validation of the read-only architecture:

* agent writeback of any kind
* bidirectional synchronisation
* memory promotion into the vault
* MCP write tools, and MCP vault exposure generally (proposal §14)
* a Markdown editor in the NEXUS UI (proposal line 949 says not to build one, and `KnowledgeBase.tsx` is
  already large)
* file watcher, and any polling loop
* automatic Git commits
* Git-branch review of agent knowledge changes (proposal §12)
* bulk migration of existing `KnowledgePage` bodies into the vault
* security controls 7–13 in §20
* the 3D office integration of proposal §23 — struck, not deferred

## 25. Consequences

**Positive.** One authoritative body per document, with the derived index unambiguously in PostgreSQL. Git
supplies real version history where none existed. `KnowledgeManager` removal reduces an existing duplication
rather than adding to it. Tenant isolation becomes a path root instead of a filesystem authorisation check.
Six filesystem controls are written once, with tests, before any code reaches the vault. Read-only Phase 1
means the worst failure mode is a stale or missing index, never data loss or a corrupted note.

**Negative.** A new table plus the `KnowledgeChunk` source-pair change means migrations. The vault becomes a
second repository to operate, back up and secure. `KnowledgePage.content` carries a dual meaning during the
transition — cache for some types, authoritative for others — which is a correctness hazard until the
read-path audit closes. Portability work becomes mandatory. Humans must author in Obsidian for the vault to
hold anything, so Phase 1 delivers no value until content exists.

**Neutral.** `KnowledgePage`, `RAGPipeline`, `KnowledgeChunk`, the embedding providers, `MarkdownParser` and
`memory_graph.py` are all reused as-is or with additive changes. Most read paths are unchanged. The memory
subsystem is untouched in Phase 1.

**Enforcement.** `scripts/arch_guard.py` rule R6 fails CI when any module other than
`obsidian/security.py` reads `obsidian_vault_root` — from settings or from the environment — so a
future caller cannot build a vault path that skips the §20 controls. It caught one real violation on
introduction (`obsidian/embedding_policy.py` read the setting for an enablement check), which is now
routed through `security.is_vault_enabled()`.

## 26. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `KnowledgePage.content` means two things during transition | high | Read-path audit at Phase 1 start; classify per type in code, not by convention |
| Path validator bypassed by a code path added later | high | `arch_guard.py` rule (§25); validator is the only way to construct a vault path |
| A note body exists only in the vault and drops out of company export | high | §19; option 2 minimum in Phase 1, option 1 before any writeback |
| Embedding provider changes width under a running system | medium | Config-load rejection plus `index_status` backstop (§21) |
| Vault nested in the NEXUS repo by accident | medium | §18; `.gitignore` the scratch `NVLabsCompany/` path and document the separate-repo requirement |
| Wikilink nodes worsen `memory_graph.py`'s O(n²) edge scan | medium | Measured before vault nodes are added to the derived graph |
| `KnowledgeManager` removal breaks an unknown consumer | low | Final dependency verification at Phase 1 start (§27); evidence today is zero production callers |
| Indexer walks `data/` and ingests cold-memory archives | low | Explicit root scoping plus extension allowlist (§20) |
| Frontmatter `nexus_id` diverges from the row after a manual file copy | low | Duplicate-id detection during sync sets `index_status` to a failure state |

## 27. Definition of Done

**Phase 0 (this ADR) is done when:**

- [x] Existing knowledge, memory, RAG, graph and documentation subsystems audited against real code
- [x] Duplication inventoried with file and line evidence (§3)
- [x] Ownership boundary stated as a rule, not a folder convention (§6)
- [x] Data ownership matrix complete, one row per frontmatter `type` (§7)
- [x] `KnowledgePage` and `KnowledgeManager` decisions explicit, with classifications (§8, §9)
- [x] Tenancy model, vault layout and identity model decided (§15, §16, §17)
- [x] Git, portability, security and embedding policies decided (§18–§21)
- [x] Migration ordered with reversibility stated per step (§22)
- [x] Phase 1 scope and deferred functionality enumerated (§23, §24)
- [x] This ADR committed to `docs/adr/`

**Phase 1 may not begin until:**

- [ ] This ADR is committed and reviewed
- [ ] `KnowledgeManager` production-call-site verification re-run and confirmed zero (§9)
- [ ] `KnowledgePage.content` read-path audit against `plaza.py` complete, deciding cache versus drop (§8)
- [ ] `get_page_history` consumer check confirmed — repository search found no dashboard, e2e or desktop
      caller; `plaza.py:433` is the only internal caller — and the deprecate-versus-repoint decision recorded
- [ ] `models/memory.py:16` docstring corrected (§22 step 1)

**Phase 1 is done when:**

- [x] Vault-per-company config surface exists and validates — a configured root that does not exist,
      is not a directory, or is unreadable refuses startup rather than reporting an empty vault
- [x] All six §20 Phase 1 security controls implemented with tests, including a traversal test, a symlink
      escape test, and a cross-tenant path test
- [x] `obsidian_documents` migration applied; `KnowledgeChunk` carries an explicit `source_type` /
      `source_id` pair, with a regression test pinning that no existing chunk lost its parent
- [ ] Frontmatter parsing feeds `MarkdownParser`; `nexus_id` minted and mirrored
- [ ] Explicit sync endpoint detects create, update, MOVE, RENAME and DELETE correctly, proven by test
- [ ] 1536-dimension enforcement fails at config load, with a test; no silent vector drop reachable for the
      vault corpus
- [ ] `index_status` exposes `indexed` / `partial` / `failed` / `stale`, and failures are visible in the UI
- [ ] Vault content is retrievable through existing `rag_search` with no new search endpoint
- [x] Wikilink edges appear in the derived graph with no persisted edge table — targets parsed in
      `obsidian/wikilinks.py` and stored on `obsidian_documents.wikilink_targets` during indexing;
      `api/routes/memory_graph.py` resolves them into edges at request time
- [ ] Portability either bundles the vault or marks exports partial in the manifest (§19)
- [ ] `KnowledgeManager` and `tests/test_knowledge_graph.py` removed
- [ ] No agent-facing create, update, append, move or delete operation exists anywhere in the vault surface
