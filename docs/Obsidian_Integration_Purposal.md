# NEXUS × Obsidian Integration

## Technical Integration & Architecture Proposal

**Project:** NVLabsCompany / NEXUS
**Integration:** Obsidian
**Status:** Proposed
**Objective:** Turn Obsidian into the human-readable, versionable knowledge layer for NEXUS while preserving PostgreSQL, pgvector, Redis and Temporal as the operational/machine layer.

---

# 1. Executive Summary

NEXUS currently contains substantial functionality around:

* Knowledge
* Memory
* RAG
* Research
* Agent knowledge
* Decisions
* Documentation
* Knowledge graph
* Workflow context
* Long-term organizational knowledge

Rather than continuing to expand NEXUS into a custom documentation/knowledge-management application, integrate **Obsidian as the human-facing knowledge substrate**.

The recommended architecture is:

```text
                         NEXUS
                           │
             ┌─────────────┴─────────────┐
             │                           │
       CONTROL PLANE                KNOWLEDGE PLANE
             │                           │
       PostgreSQL                    Obsidian
       Redis                         Markdown
       Temporal                      Wikilinks
       Agent Runtime                 Frontmatter
       Governance                    Git
             │                           │
             └─────────────┬─────────────┘
                           │
                     NEXUS Indexer
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
              Metadata            pgvector
                                   │
                                   ▼
                                  RAG
```

The goal is **not** to replace NEXUS's database.

The goal is to eliminate unnecessary custom knowledge/document infrastructure and make Obsidian the canonical human-readable representation of durable organizational knowledge.

---

# 2. Core Architectural Principle

Use this separation:

## NEXUS owns operational truth

Examples:

* Agent status
* Current task
* Workflow state
* Execution state
* Budgets
* Permissions
* Authentication
* Sessions
* Tool execution
* Approvals
* Audit events
* Queues
* Temporal workflows
* Runtime telemetry

These remain in PostgreSQL / Redis / Temporal / observability infrastructure.

## Obsidian owns human-readable knowledge

Examples:

* Architecture
* ADRs
* Research
* Lessons learned
* Agent knowledge
* Long-term memories
* Project documentation
* Meeting notes
* Decisions
* Procedures
* Playbooks
* Company knowledge
* Design notes
* Investigation reports

This distinction must remain strict.

---

# 3. What Obsidian Should Replace

## High-priority replacements

### 3.1 Knowledge Pages

Current NEXUS knowledge documents should become Markdown files in an Obsidian vault.

Instead of making NEXUS the primary document editor:

```text
KnowledgePage
KnowledgePageMetadata
KnowledgePageContent
```

use:

```text
Obsidian Markdown
+
YAML frontmatter
+
Wikilinks
```

---

### 3.2 Architecture Decision Records

Do not build a separate proprietary ADR editor.

Store:

```text
Architecture/
└── Decisions/
    ├── ADR-001-PostgreSQL.md
    ├── ADR-002-Temporal.md
    ├── ADR-003-Obsidian.md
    └── ADR-004-Agent-Memory.md
```

---

### 3.3 Research

Use Obsidian as the persistent research workspace.

```text
Research/
├── AI/
├── Cybersecurity/
├── Infrastructure/
├── Competitors/
├── Products/
└── Experiments/
```

Agents can create and update research notes.

---

### 3.4 Lessons Learned

Agent failures and successful discoveries should be able to produce durable notes.

```text
Lessons/
├── Agent/
├── Engineering/
├── Security/
├── Operations/
└── Product/
```

---

### 3.5 Meeting Notes

Use:

```text
Meetings/
└── 2026/
```

with links to agents, projects, decisions and tasks.

---

### 3.6 Long-Term Agent Knowledge

Each agent can have a human-readable knowledge area:

```text
Agents/
├── Architect/
├── Cipher/
├── Forge/
├── Nova/
└── ...
```

This should contain durable knowledge, not transient runtime state.

---

# 4. What Obsidian Should NOT Replace

Do not move these into Markdown:

```text
Authentication
Authorization
RBAC
Agent runtime state
Task execution state
Workflow execution state
Budget accounting
Rate limiting
Sessions
Secrets
Audit event storage
Distributed locks
Queues
Temporal state
Real-time telemetry
LLM request state
```

PostgreSQL remains the authoritative transactional datastore.

Redis remains appropriate for:

* caching
* distributed coordination
* rate limits
* ephemeral state

Temporal remains appropriate for durable workflow orchestration.

---

# 5. Recommended Vault Structure

Create a NEXUS-compatible vault structure:

```text
NEXUS-Vault/
│
├── Agents/
│   ├── Architect/
│   │   ├── Profile.md
│   │   ├── Knowledge/
│   │   ├── Decisions/
│   │   └── Lessons/
│   │
│   ├── Cipher/
│   └── Forge/
│
├── Company/
│   ├── Overview.md
│   ├── Principles.md
│   ├── Policies/
│   └── Processes/
│
├── Knowledge/
│   ├── Engineering/
│   ├── Security/
│   ├── Product/
│   ├── Infrastructure/
│   └── AI/
│
├── Projects/
│   ├── NEXUS/
│   └── ...
│
├── Architecture/
│   ├── System Architecture.md
│   ├── Agent Architecture.md
│   ├── Memory Architecture.md
│   ├── RAG Architecture.md
│   └── Decisions/
│
├── Research/
│   ├── AI/
│   ├── Security/
│   └── Market/
│
├── Decisions/
│
├── Lessons/
│
├── Meetings/
│
├── Incidents/
│
├── Tasks/
│
└── Daily/
```

The structure should be configurable rather than hard-coded.

---

# 6. Markdown Metadata Standard

Every NEXUS-managed note should use predictable frontmatter.

Example:

```yaml
---
nexus_id: knowledge-042
type: knowledge
status: active
created_at: 2026-08-30T01:00:00Z
updated_at: 2026-08-30T01:20:00Z
created_by: agent:cipher
project: NEXUS
tags:
  - security
  - ssrf
---
```

Supported `type` values should include:

```text
knowledge
memory
lesson
decision
adr
research
meeting
incident
project
agent
task
procedure
architecture
```

Additional metadata can be type-specific.

---

# 7. Wikilink-Based Knowledge Graph

Obsidian's `[[Wikilinks]]` should become a first-class NEXUS relationship mechanism.

Example:

```markdown
# SSRF Protection

NEXUS validates all remote URLs before network access.

## Related

- [[Security Architecture]]
- [[Cipher]]
- [[Agent Runtime]]
- [[Incident INC-042]]
```

NEXUS should parse these relationships.

Graph representation:

```text
Cipher
  │
  ├── discovered ──> SSRF Protection
  │
  └── investigated ──> Incident INC-042

SSRF Protection
  │
  └── part-of ──> Security Architecture
```

This should feed the existing NEXUS force-graph/knowledge visualization.

Do not create a second independent graph source of truth unless there is a demonstrated need.

---

# 8. RAG Architecture

Obsidian should become a **source corpus**, not the vector database.

Recommended pipeline:

```text
Obsidian Vault
      │
      ▼
File Watcher / Sync
      │
      ▼
Markdown Parser
      │
      ▼
Frontmatter Extraction
      │
      ▼
Wikilink Extraction
      │
      ▼
Chunker
      │
      ▼
Embedding Provider
      │
      ▼
pgvector
      │
      ▼
Hybrid Retrieval
      │
      ├── BM25
      ├── Vector Search
      └── Reranking
      │
      ▼
NEXUS Agent Context
```

The current NEXUS RAG architecture should be retained and modified to index Obsidian documents.

---

# 9. Document Identity and Synchronization

Every indexed note needs a stable identity.

Recommended:

```yaml
nexus_id: knowledge-042
```

Do not use the filename as the primary identity.

Maintain:

```text
nexus_id
vault_path
content_hash
mtime
version
indexed_at
embedding_model
embedding_dimension
```

The indexer should detect:

```text
CREATE
UPDATE
MOVE
RENAME
DELETE
```

---

# 10. Synchronization Strategy

Use a bidirectional-but-controlled model.

## Obsidian → NEXUS

When a Markdown file changes:

```text
File changed
   ↓
Detect change
   ↓
Parse
   ↓
Validate frontmatter
   ↓
Update metadata
   ↓
Rechunk
   ↓
Re-embed
   ↓
Update vector index
   ↓
Update graph relationships
```

## NEXUS → Obsidian

Agents may:

```text
create note
update note
append note
link notes
add frontmatter
```

Every mutation should:

1. Validate path.
2. Validate allowed vault boundary.
3. Write atomically.
4. Preserve frontmatter.
5. Update hash.
6. Trigger reindexing.
7. Record an audit event.

---

# 11. Conflict Handling

Do not silently overwrite user edits.

Use content hashes.

Example:

```text
NEXUS last known hash
        │
        ▼
Obsidian current hash
        │
        ├── same → safe update
        │
        └── different
              │
              ▼
         conflict detected
```

Possible strategies:

```text
manual conflict
three-way merge
new version
agent proposal
```

For early implementation, **manual conflict detection is preferable to destructive automatic merging**.

---

# 12. Git Integration

A Git-backed vault is strongly recommended.

Example:

```text
Obsidian Vault
      │
      ▼
Git Repository
      │
      ├── history
      ├── diff
      ├── rollback
      ├── branches
      └── review
```

This gives NEXUS something extremely valuable:

**versioned institutional memory.**

An agent can make a knowledge change and the change can be reviewed like code.

---

# 13. Agent Obsidian Tools

Expose Obsidian capabilities through the NEXUS tool system.

Recommended tools:

```text
obsidian.search
obsidian.read
obsidian.create
obsidian.update
obsidian.append
obsidian.move
obsidian.delete
obsidian.list
obsidian.backlinks
obsidian.links
obsidian.graph
obsidian.recent
```

Example:

```text
Agent:
"Find previous decisions about RAG."

→ obsidian.search()

Agent:
"Document today's decision."

→ obsidian.create()

Agent:
"Show everything related to SSRF."

→ obsidian.search()
→ obsidian.links()
→ graph traversal
```

---

# 14. MCP Compatibility

Where practical, implement the Obsidian integration through an abstraction compatible with the existing NEXUS MCP/tool architecture.

Do not hard-code agent logic directly against filesystem APIs.

Recommended abstraction:

```text
Agent
  ↓
NEXUS Tool Interface
  ↓
Knowledge Provider
  ↓
Obsidian Provider
```

This allows future providers:

```text
Obsidian
Git
S3
Notion
Confluence
Local Markdown
```

without changing agent code.

---

# 15. Memory Integration

Do not dump every short-lived memory into Obsidian.

Use a promotion model.

```text
Conversation
    ↓
Working Memory
    ↓
Episode
    ↓
Memory extraction
    ↓
Importance / confidence
    ↓
Should this become durable knowledge?
    │
    ├── NO → PostgreSQL only
    │
    └── YES
          ↓
      Obsidian note
```

Examples worthy of promotion:

* architectural decisions
* lessons learned
* stable preferences
* discovered procedures
* important research
* recurring failure patterns
* validated knowledge
* project history

Do not promote:

* every chat message
* transient tool calls
* temporary reasoning
* ephemeral status
* routine telemetry

---

# 16. Knowledge Lifecycle

Implement a lifecycle:

```text
Captured
   ↓
Candidate
   ↓
Validated
   ↓
Published
   ↓
Indexed
   ↓
Used
   ↓
Updated
   ↓
Archived
```

Use frontmatter:

```yaml
status: candidate
confidence: 0.82
review_required: true
```

Agents should not automatically publish potentially dangerous organizational knowledge without policy checks.

---

# 17. Governance Integration

Obsidian writes must go through NEXUS governance.

For example:

```text
Agent wants to modify knowledge
          ↓
Tool authorization
          ↓
RBAC
          ↓
Policy
          ↓
Path permission
          ↓
Approval if required
          ↓
Write
          ↓
Audit
          ↓
Index
```

Potential policy:

```yaml
allowed_paths:
  - "Agents/Cipher/**"
  - "Research/**"

approval_required_paths:
  - "Company/Policies/**"
  - "Architecture/Decisions/**"
```

This prevents an agent from casually rewriting company policy.

---

# 18. Security Requirements

The Obsidian integration must address:

### Path traversal

Reject:

```text
../../
absolute paths
symlinks escaping vault
```

### Vault boundary

All file operations must remain inside the configured vault.

### Symlinks

Resolve and validate real paths.

### File size limits

Prevent an agent from creating enormous files.

### Extension allowlist

Initially allow:

```text
.md
```

Potentially:

```text
.canvas
.json
.png
.jpg
```

later.

### Secret leakage

Do not allow agents to write:

```text
API keys
passwords
session tokens
private credentials
```

without explicit policy.

### Audit

Record:

```text
actor
agent
operation
path
timestamp
old hash
new hash
approval
```

---

# 19. Proposed Backend Module

Recommended structure:

```text
src/nexus/integrations/obsidian/
├── __init__.py
├── config.py
├── provider.py
├── vault.py
├── parser.py
├── frontmatter.py
├── wikilinks.py
├── sync.py
├── indexer.py
├── graph.py
├── conflicts.py
├── security.py
└── models.py
```

Potential interfaces:

```python
class ObsidianProvider:
    async def search(...)
    async def read(...)
    async def create(...)
    async def update(...)
    async def append(...)
    async def delete(...)
    async def move(...)
    async def backlinks(...)
```

Keep the provider interface independent of the UI.

---

# 20. API Proposal

Possible endpoints:

```text
GET    /api/v1/integrations/obsidian/status
POST   /api/v1/integrations/obsidian/configure
POST   /api/v1/integrations/obsidian/connect
POST   /api/v1/integrations/obsidian/sync
POST   /api/v1/integrations/obsidian/reindex
GET    /api/v1/integrations/obsidian/files
GET    /api/v1/integrations/obsidian/file
POST   /api/v1/integrations/obsidian/file
PATCH  /api/v1/integrations/obsidian/file
DELETE /api/v1/integrations/obsidian/file
GET    /api/v1/integrations/obsidian/graph
GET    /api/v1/integrations/obsidian/backlinks
GET    /api/v1/integrations/obsidian/conflicts
```

However, avoid duplicating generic Knowledge APIs unnecessarily.

The long-term goal should be:

```text
Knowledge API
      ↓
Knowledge Provider
      ├── PostgreSQL legacy provider
      └── Obsidian provider
```

rather than two completely independent knowledge systems.

---

# 21. Frontend Changes

Do not build another large Markdown editor unless required.

The NEXUS UI should focus on:

### Knowledge

```text
Search
Graph
Recent
AI-generated
Needs review
```

### Obsidian status

```text
Connected
Vault
Last sync
Indexed documents
Pending changes
Conflicts
Embedding status
```

### Actions

```text
Open in Obsidian
Sync
Reindex
View backlinks
View graph
```

NEXUS should remain the operational interface.

Obsidian should remain the knowledge-authoring interface.

---

# 22. Knowledge Graph Integration

The existing NEXUS graph should consume three relationship types:

### Wikilink relationships

```text
[[Cipher]] → [[SSRF]]
```

### Explicit frontmatter relationships

```yaml
agent: Cipher
project: NEXUS
related:
  - SSRF
  - Security Architecture
```

### Operational relationships

From PostgreSQL:

```text
Agent → Task
Task → Project
Agent → Workflow
Task → Incident
```

Merge them at visualization time:

```text
                    NEXUS GRAPH
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
       Obsidian       PostgreSQL    Runtime
       Knowledge      Entities      Events
           │             │             │
           └─────────────┼─────────────┘
                         ▼
                  Unified Graph
```

This is considerably more powerful than having an isolated Obsidian graph.

---

# 23. 3D Office Integration

Obsidian should **not** become the source of live agent telemetry.

However, the office can use Obsidian-derived knowledge for contextual information.

Example:

Agent Cipher is selected:

```text
Live state:
Working

Current task:
SSRF security review

Knowledge:
12 related notes

Recent lessons:
3

Architecture decisions:
5

Incidents:
2
```

The 3D Office can therefore become a visual interface to the **real NEXUS agent + knowledge system**, rather than displaying hard-coded mock telemetry.

---

# 24. Search Strategy

Implement three search layers:

```text
1. Exact / filename search
2. BM25 / lexical search
3. Semantic vector search
```

Then combine:

```text
Obsidian search
      +
PostgreSQL metadata
      +
pgvector
      +
NEXUS graph
```

Use metadata filters:

```text
agent
project
type
status
date
tags
security classification
```

---

# 25. Embedding Strategy

Do not rely on the current local hash-based embedding implementation for production semantic retrieval.

Obsidian integration should support:

```text
OpenAI embeddings
Ollama embeddings
other provider
```

with explicit model metadata:

```yaml
embedding_model: text-embedding-3-small
embedding_dimension: 1536
```

If the embedding model changes:

```text
old index
   ↓
migration/reindex
   ↓
new embeddings
```

Do not silently mix incompatible embedding dimensions/models.

---

# 26. Indexing Reliability

This should directly address the current NEXUS knowledge-indexing weaknesses.

A successful sync should guarantee:

```text
Markdown file exists
        ↓
Metadata exists
        ↓
Chunks exist
        ↓
Embeddings exist
        ↓
Vector index exists
        ↓
Graph relationships exist
```

If any stage fails:

```text
index_status = failed
```

rather than silently falling back and presenting the document as fully indexed.

Expose:

```text
indexed
partial
failed
pending
stale
```

states.

---

# 27. Testing Strategy

Required tests:

## Unit

* Markdown parser
* frontmatter parser
* wikilink parser
* path security
* hashing
* conflict detection
* chunking
* metadata extraction

## Integration

* create note
* update note
* delete note
* rename note
* sync
* reindex
* graph extraction
* PostgreSQL metadata
* pgvector indexing

## Security

* path traversal
* symlink escape
* unauthorized paths
* cross-tenant access
* malicious Markdown
* oversized file
* secret leakage

## Failure tests

* process crash during write
* embedding failure
* PostgreSQL failure
* vault unavailable
* partial indexing
* concurrent update
* conflicting agent/user edits

## End-to-end

```text
Create Markdown
 → sync
 → index
 → RAG search
 → agent retrieves
 → agent modifies note
 → reindex
 → graph updates
```

This exact workflow should have an E2E test.

---

# 28. Migration Strategy

Do not immediately delete the existing Knowledge system.

Phase migration.

## Phase 1

Obsidian as read-only source.

```text
Existing Knowledge
        +
Obsidian
        ↓
RAG
```

## Phase 2

Obsidian becomes primary source for new documents.

## Phase 3

Migrate existing KnowledgePage records into Markdown.

```text
KnowledgePage
     ↓
Markdown
     ↓
Obsidian
```

## Phase 4

Deprecate redundant KnowledgePage CRUD.

## Phase 5

Remove obsolete database tables only after migration verification.

---

# 29. Recommended Rollout

## Phase 0 — Architecture

* inspect existing Knowledge/Memory/RAG models
* identify duplicate functionality
* identify current KnowledgePage dependencies
* define canonical ownership
* define Obsidian vault format

No major code changes yet.

---

## Phase 1 — Provider

Implement:

```text
ObsidianProvider
VaultSecurity
MarkdownParser
FrontmatterParser
WikilinkParser
```

Add tests.

---

## Phase 2 — Indexing

Implement:

```text
Vault watcher
Sync
Chunking
Embedding
pgvector
Graph extraction
```

---

## Phase 3 — Agent tools

Expose:

```text
search
read
create
update
append
links
backlinks
```

through the existing NEXUS tool architecture.

---

## Phase 4 — Memory promotion

Implement:

```text
Memory
 ↓
Importance
 ↓
Promotion
 ↓
Obsidian
```

with governance.

---

## Phase 5 — UI

Add:

```text
Obsidian status
Sync status
Index status
Conflicts
Open in Obsidian
Graph
```

---

## Phase 6 — Migration

Move existing KnowledgePage content.

Deprecate duplicate functionality.

---

# 30. Success Criteria

The integration should not be considered complete until:

### Knowledge

* [ ] Obsidian can be configured as a vault
* [ ] Markdown is parsed reliably
* [ ] Frontmatter is supported
* [ ] Wikilinks are supported
* [ ] Files can be indexed
* [ ] Updates trigger reindex
* [ ] Deletes remove stale index records
* [ ] Renames preserve identity

### RAG

* [ ] Obsidian content is searchable
* [ ] BM25 works
* [ ] vector search works
* [ ] hybrid search works
* [ ] embedding dimensions are validated
* [ ] indexing failures are visible

### Agents

* [ ] agents can search
* [ ] agents can read
* [ ] agents can create notes
* [ ] agents can update notes
* [ ] agents can create links
* [ ] agent writes are governed
* [ ] agent writes are audited

### Memory

* [ ] important memories can be promoted
* [ ] transient memory isn't spammed into Obsidian
* [ ] promoted memories retain provenance
* [ ] confidence is tracked

### Graph

* [ ] Wikilinks become graph edges
* [ ] PostgreSQL relationships remain available
* [ ] unified graph can be generated

### Security

* [ ] path traversal blocked
* [ ] vault boundary enforced
* [ ] tenant isolation enforced
* [ ] RBAC enforced
* [ ] sensitive data protections enforced
* [ ] all mutations audited

### Reliability

* [ ] atomic writes
* [ ] conflict detection
* [ ] restart-safe indexing
* [ ] failed indexing visible
* [ ] reindex operation available

---

# 31. Recommended End State

The desired final architecture is:

```text
                         ┌──────────────────────┐
                         │      NEXUS UI        │
                         │                      │
                         │ Agents               │
                         │ Tasks                │
                         │ Workflows            │
                         │ Office               │
                         │ Knowledge Graph      │
                         └──────────┬───────────┘
                                    │
                         ┌──────────▼───────────┐
                         │    NEXUS CONTROL     │
                         │       PLANE          │
                         │                      │
                         │ Auth                 │
                         │ Governance           │
                         │ Agents               │
                         │ Tasks                │
                         │ Workflows             │
                         │ Budgets              │
                         │ Runtime              │
                         └──────────┬───────────┘
                                    │
               ┌────────────────────┼────────────────────┐
               │                    │                    │
               ▼                    ▼                    ▼
          PostgreSQL              Redis              Temporal
          operational             cache              workflows
          truth
               │
               │
               ▼
       ┌────────────────────┐
       │  Knowledge Layer   │
       └─────────┬──────────┘
                 │
       ┌─────────▼──────────┐
       │      Obsidian      │
       │                    │
       │ Markdown           │
       │ Wikilinks          │
       │ Frontmatter        │
       │ Research           │
       │ Decisions          │
       │ Lessons            │
       │ Agent knowledge    │
       └─────────┬──────────┘
                 │
              Indexer
                 │
          ┌──────┴──────┐
          ▼             ▼
       BM25          pgvector
          │             │
          └──────┬──────┘
                 ▼
              NEXUS RAG
                 │
                 ▼
               Agents
```

---

# 32. Final Recommendation

Proceed with Obsidian integration.

However, **do not treat this as another feature added on top of NEXUS**.

Treat it as an architectural simplification.

The goal should be to remove/reduce custom knowledge-management functionality from NEXUS and replace it with:

**Obsidian = human knowledge**

**PostgreSQL = operational truth**

**pgvector = semantic retrieval**

**Redis = ephemeral/distributed state**

**Temporal = durable workflows**

**NEXUS = intelligence + orchestration + governance**

This separation will reduce duplicate functionality, make the knowledge layer inspectable by humans, provide Git-based history, improve the knowledge graph, and give agents a persistent organizational memory that humans can directly understand and edit.

The implementation should begin with a repository audit of the existing Knowledge, Memory, RAG, Graph, Research and documentation subsystems before modifying production code.

**Do not start coding until the existing data ownership and migration boundaries have been mapped.**
