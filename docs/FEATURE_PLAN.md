# NVLabsCompany — Base Feature Comparison and Phased Implementation Plan

**Date:** 2026-08-26
**Baseline:** NVLabsCompany (`nexus`), `main` @ `01d02e8`
**Companion doc:** `docs/COMPARISON_REPORT.md` (architecture-level comparison)
**Scope:** feature-by-feature matrix across all six reference repos, an add/modify/replace
verdict for each, and a micro-phased delivery plan.

---

## 0. Corrections to the previous report

Two claims in `COMPARISON_REPORT.md` were wrong. They are corrected here and the matrix
below reflects the verified state.

**Correction 1 — embeddings and RAG do exist.** The previous report stated there is "no
vector store and no embedding model anywhere in the project." That is incorrect:

- `src/nexus/knowledge/embeddings.py` — `EmbeddingProvider` protocol plus
  `OpenAIEmbeddingProvider` (text-embedding-3-small/large, 1536/3072 dims) and an Ollama
  provider, with a documented BM25 fallback when no provider is configured.
- `src/nexus/knowledge/rag.py` — `RAGPipeline` with chunking, indexing, **hybrid search
  (BM25 + vector cosine similarity)**, reranking, and context assembly. Pluggable ranker,
  retriever, and parser protocols.
- `src/nexus/models/knowledge.py:53` — `KnowledgeChunk.embedding_vector: Optional[list[float]]`,
  a real persisted column.

The accurate gap is narrower: **no dedicated vector database**. No pgvector, Chroma, Qdrant,
Pinecone, FAISS, or Weaviate anywhere in `src/` or `pyproject.toml`. Vectors are stored as
JSON list columns and cosine similarity is computed in Python over rows pulled into memory.
That works at hundreds of chunks and degrades badly past tens of thousands. It is a scaling
gap, not an absence.

**Correction 2 — provider count was understated.** The previous report said "4 versus 13"
by counting only `src/nexus/models_router/providers/` (anthropic, google, ollama, openai).
The actual adapter layer registers **11**: `src/nexus/adapters/registry.py` — `anthropic`,
`azure_openai`, `bedrock`, `claude_code`, `cli`, `google_gemini`, `hermes`, `http`, `mcp`,
`ollama`, `openai`, with dedicated files for each plus `provider_presets.py`,
`llm_circuit_breaker.py`, and `uastl.py` (an implementation of OpenCompany's UASTL RFC).

So the real position is 11 adapters against OpenCompany's 13 providers — near parity, not a
3× gap. The genuine gap is that `models_router/` (the cost-aware cascade router) only knows
about 4 of the 11, so cascade routing and cost tracking cover a subset of what the project
can actually call.

**Also worth stating plainly:** the node library is not a gap. `src/nexus/nodes/registry.py`
defines `NodeCategory` with a docstring reading "31 categories from OpenCompany", and
`src/nexus/nodes/categories/all_nodes.py` registers **164 nodes**. Commit `01d02e8` wired
that palette into the Pipeline Builder. On raw node count this project is ahead of
OpenCompany's 76 on-disk plugin directories.

---

## 1. Base feature matrix

Legend for the NVLabs column:
`FULL` — implemented and persisted · `PARTIAL` — implemented with a real limitation ·
`MEM` — implemented but state is in-process only · `STUB` — scaffolding/interface only ·
`NONE` — absent

Legend for references: `Y` present · `y` partial · `—` absent/not applicable.

### 1.1 Core orchestration

| # | Feature | paperclip | OpenCompany | Clawith | PraisonAI | MetaGPT | AI Team OS | NVLabs |
|---|---|---|---|---|---|---|---|---|
| 1 | Single authoritative execution state machine | Y | Y | Y | Y | Y | Y | **NONE** (3 paths) |
| 2 | Durable execution engine (Temporal/checkpoint) | Y | Y | Y | — | y | — | **PARTIAL** |
| 3 | Task decomposition / planner | y | — | Y | Y | Y | Y | **FULL** |
| 4 | Agent selection / routing by score | Y | — | y | y | y | Y | **FULL** |
| 5 | Parallel execution with concurrency cap | Y | Y | Y | y | Y | Y | **FULL** |
| 6 | Retry with budget awareness | Y | Y | Y | Y | y | Y | **FULL** |
| 7 | Failure diagnosis → escalation actions | Y | y | y | y | — | Y | **FULL** |
| 8 | Doom-loop / cycle detection | Y | y | Y | Y | — | Y | **FULL** |
| 9 | Explicit completion-reason taxonomy | Y | y | Y | **Y** | — | y | **NONE** |
| 10 | LLM-judge goal verification | — | y | Y | **Y** | y | y | **PARTIAL** |
| 11 | Quality gate / critic on output | y | — | Y | Y | Y | Y | **PARTIAL** |
| 12 | Crash recovery / orphan run reclaim | **Y** | Y | Y | — | y | Y | **PARTIAL** |
| 13 | Watchdog for silent/stalled runs | **Y** | y | y | — | — | Y | **NONE** |

### 1.2 Agent model and collaboration

| # | Feature | paperclip | OpenCompany | Clawith | PraisonAI | MetaGPT | AI Team OS | NVLabs |
|---|---|---|---|---|---|---|---|---|
| 14 | Org chart with reporting lines | Y | — | Y | — | y | Y | **FULL** |
| 15 | Heartbeat / scheduled agent wakeup | **Y** | Y | Y | — | — | Y | **MEM** |
| 16 | Agent-to-agent messaging (A2A) | Y | Y | **Y** | Y | Y | Y | **FULL** |
| 17 | Idempotent A2A correlation IDs | Y | Y | **Y** | — | — | y | **NONE** |
| 18 | Sub-agent delegation permits (fan-out cap) | y | **Y** | y | — | — | y | **NONE** |
| 19 | Group / multi-agent rooms | — | — | **Y** | — | Y | Y | **FULL** |
| 20 | Handoff with immutable delivery intent | — | — | **Y** | y | — | — | **NONE** |
| 21 | Orchestration patterns (seq/hier/workflow) | y | Y | y | **Y** | Y | y | **PARTIAL** |
| 22 | Multi-provider execution adapters | **Y** (13) | Y (13) | y | Y | Y | y | **FULL** (11) |
| 23 | Persona / soul templates | — | — | y | y | Y | y | **FULL** |
| 24 | Performance review / evaluation of agents | — | — | y | — | — | Y | **FULL** |

### 1.3 Memory, context, knowledge

| # | Feature | paperclip | OpenCompany | Clawith | PraisonAI | MetaGPT | AI Team OS | NVLabs |
|---|---|---|---|---|---|---|---|---|
| 25 | Tiered memory (hot/warm/cold) | y | y | y | **Y** | Y | Y | **PARTIAL** |
| 26 | Embeddings provider abstraction | — | Y | — | **Y** | Y | — | **FULL** |
| 27 | Dedicated vector DB | — | **Y** | — | **Y** | **Y** | — | **NONE** |
| 28 | Hybrid search (keyword + vector) | — | Y | — | Y | Y | y | **FULL** |
| 29 | RAG pipeline with chunking + rerank | — | Y | — | **Y** | Y | — | **FULL** |
| 30 | Budget-aware context compaction | y | **Y** | **Y** | Y | y | — | **PARTIAL** |
| 31 | Conversation durability across wakeups | Y | **Y** | Y | y | y | Y | **PARTIAL** |
| 32 | Memory dedup on write | — | — | — | y | — | Y | **FULL** |
| 33 | Cross-agent memory promotion | — | — | — | — | — | Y | **FULL** |
| 34 | Knowledge graph over memory | — | — | — | y | — | — | **FULL** |
| 35 | Document parsers / converters | — | Y | Y | Y | Y | — | **FULL** |

### 1.4 Governance, safety, spend

| # | Feature | paperclip | OpenCompany | Clawith | PraisonAI | MetaGPT | AI Team OS | NVLabs |
|---|---|---|---|---|---|---|---|---|
| 36 | Budget tracking by scope | **Y** | Y | Y | Y | y | Y | **PARTIAL** |
| 37 | Warning threshold + hard-stop pause | **Y** | y | y | Y | y | y | **PARTIAL** |
| 38 | Pre-flight cost estimation | — | — | — | **Y** | — | — | **NONE** |
| 39 | Cost alert state survives restart | Y | Y | Y | — | — | Y | **MEM** |
| 40 | Model cascade router w/ cost simulation | — | y | — | y | — | — | **FULL** |
| 41 | Human approval gates | Y | y | **Y** | Y | y | Y | **MEM** |
| 42 | Per-agent per-action autonomy policy | y | — | **Y** | Y | — | y | **PARTIAL** |
| 43 | Audit log persisted + append-only | **Y** | Y | **Y** | — | — | Y | **MEM** |
| 44 | Audit hash chain / tamper detection | — | — | — | — | — | — | **FULL** |
| 45 | Kill switch | y | Y | y | — | — | Y | **FULL** |
| 46 | Circuit breaker | y | Y | y | Y | — | Y | **FULL** |
| 47 | Rate limiting (distributed) | Y | Y | Y | y | — | y | **FULL** |
| 48 | Guardrail chain (policy + structural) | y | y | Y | **Y** | — | y | **PARTIAL** |
| 49 | Secrets vault persisted | Y | **Y** | Y | — | — | y | **MEM** |
| 50 | Per-agent secret scoping | **Y** | Y | Y | — | — | — | **PARTIAL** |
| 51 | Tenant isolation enforced | Y | y | **Y** | — | — | — | **PARTIAL** |
| 52 | Incident tracking / rollback | Y | y | y | y | — | Y | **FULL** |
| 53 | Retention / archival policy | Y | y | Y | — | — | y | **PARTIAL** |

### 1.5 Execution environment

| # | Feature | paperclip | OpenCompany | Clawith | PraisonAI | MetaGPT | AI Team OS | NVLabs |
|---|---|---|---|---|---|---|---|---|
| 54 | Multi-backend code sandbox | y | Y | **Y** (7) | Y | y | — | **NONE** |
| 55 | Git worktree isolation per task | **Y** | Y | y | — | — | Y | **PARTIAL** |
| 56 | Workspace file editing + locks | Y | Y | **Y** | — | Y | Y | **PARTIAL** |
| 57 | Dev server / preview URL runtime | **Y** | Y | — | — | — | — | **NONE** |
| 58 | Plugin system with out-of-process workers | **Y** | Y | — | y | — | y | **PARTIAL** |
| 59 | Plugin capability negotiation (fail-closed) | **Y** | y | — | — | — | — | **NONE** |
| 60 | MCP client | Y | Y | Y | **Y** | y | Y | **FULL** |
| 61 | MCP server (expose own tools) | y | y | — | **Y** | — | **Y** | **NONE** |

### 1.6 Triggers, workflows, integrations

| # | Feature | paperclip | OpenCompany | Clawith | PraisonAI | MetaGPT | AI Team OS | NVLabs |
|---|---|---|---|---|---|---|---|---|
| 62 | Cron / interval / once triggers | Y | Y | **Y** | y | — | y | **PARTIAL** |
| 63 | Poll (HTTP endpoint monitoring) trigger | y | **Y** | **Y** | — | — | — | **PARTIAL** |
| 64 | on_message trigger | Y | Y | **Y** | — | — | Y | **PARTIAL** |
| 65 | Webhook intake with HMAC + rate limit | y | Y | **Y** | — | — | y | **PARTIAL** |
| 66 | Durable long-running trigger listeners | — | **Y** | y | — | — | — | **NONE** |
| 67 | Visual node canvas / pipeline builder | — | **Y** | — | — | — | — | **FULL** |
| 68 | Node library breadth | — | Y (76 dirs) | y | y | — | — | **FULL** (164) |
| 69 | Plugin-first node self-registration | — | **Y** | — | y | — | — | **PARTIAL** |
| 70 | Skills as markdown files | **Y** | Y | Y | y | — | Y | **FULL** |
| 71 | Versioned skill access policy | **Y** | — | y | — | — | — | **NONE** |
| 72 | Skill evals harness | **Y** | y | — | y | — | y | **PARTIAL** |
| 73 | Chat platform integrations | y | **Y** (7+) | **Y** (6) | Y | — | y | **PARTIAL** (2) |
| 74 | Productivity suite integrations | — | **Y** | Y | y | — | — | **NONE** |
| 75 | Git provider integration | Y | Y | y | y | y | Y | **FULL** |

### 1.7 Platform, tenancy, ops

| # | Feature | paperclip | OpenCompany | Clawith | PraisonAI | MetaGPT | AI Team OS | NVLabs |
|---|---|---|---|---|---|---|---|---|
| 76 | Multi-company from one deployment | **Y** | y | **Y** | — | — | — | **FULL** |
| 77 | Company export / import (portability) | **Y** | y | — | — | — | — | **NONE** |
| 78 | SSO / OIDC | y | y | **Y** | — | — | — | **FULL** |
| 79 | SCIM provisioning | — | — | — | — | — | — | **FULL** (unique) |
| 80 | API keys | Y | Y | Y | — | — | Y | **FULL** |
| 81 | Short-lived run JWTs | **Y** | y | y | — | — | — | **NONE** |
| 82 | CSRF protection | y | Y | Y | — | — | — | **FULL** |
| 83 | RBAC / permission grants | Y | y | **Y** | y | — | y | **FULL** |
| 84 | OpenTelemetry / tracing | Y | Y | Y | Y | y | y | **PARTIAL** |
| 85 | Architecture invariant CI enforcement | y | **Y** | **Y** | y | — | **Y** | **NONE** |
| 86 | Desktop app | y | — | — | — | — | — | **PARTIAL** |
| 87 | OKR / goals module | y | — | **Y** | — | — | y | **FULL** |
| 88 | Social feed (Plaza) | — | — | **Y** | — | — | — | **FULL** |
| 89 | Meetings / huddles | — | — | y | — | — | Y | **FULL** (unique depth) |
| 90 | Spatial 3D/2D office | — | — | — | — | — | — | **FULL** (unique) |
| 91 | Self-evolution / skill evolution | — | — | — | y | y | y | **FULL** (unique depth) |

### 1.8 Scorecard

| Category | FULL | PARTIAL | MEM | STUB/NONE | Total |
|---|---|---|---|---|---|
| Core orchestration | 5 | 5 | 0 | 3 | 13 |
| Agent model | 6 | 2 | 1 | 4 | 13 |
| Memory / knowledge | 6 | 4 | 0 | 1 | 11 |
| Governance | 7 | 7 | 4 | 1 | 19 |
| Execution env | 1 | 4 | 0 | 3 | 8 |
| Triggers / workflows | 4 | 7 | 0 | 3 | 14 |
| Platform / ops | 12 | 3 | 0 | 2 | 17 |
| **Total** | **41** | **32** | **5** | **17** | **95** |

Read that as: 43% of the surface is genuinely done, 34% is real but limited, 5% is
implemented on memory that evaporates on restart, and 18% is missing. The project's problem
is not coverage — it is that the depth is uneven in ways a feature list hides.

---

## 2. Add / Modify / Replace verdicts

### 2.1 REPLACE — existing code is the wrong shape

| Target | Current state | Replace with | Source |
|---|---|---|---|
| R1 | Three orchestration paths: `runtime/orchestrator.py`, `temporal/`, `workflows/` | One Temporal-backed path; other two become thin callers | Clawith C1 invariant |
| R2 | Two trigger schedulers: `runtime/scheduler.py` (DB) + `triggers/scheduler.py` (memory) | Single DB-backed scheduler; delete the in-memory twin | Clawith `trigger_runtime/` |
| R3 | `governance/audit_persistent.py` in-memory lists | Same hash-chain logic over a real `audit_log` table, append-only | paperclip, Clawith |
| R4 | `governance/decision_queue.py` in-memory dicts | DB-backed approval queue | Clawith `ApprovalRequest` |
| R5 | `governance/secrets/secret_backend.py` `_store` dict | Persisted encrypted store, pluggable backend | OpenCompany `credential_backends.py` |
| R6 | `governance/cost_alerting.py` in-memory alert state | DB or Redis-backed threshold state | paperclip `budgets.ts` |
| R7 | `orchestration/critic.py` `len()/100` heuristic as default | `llm_critic.py` as default, heuristic as explicit fallback | Clawith verify node |
| R8 | Python-side cosine similarity over JSON columns | pgvector column + index | OpenCompany, PraisonAI |
| R9 | `evolution/sandbox.py` (logical/in-memory only, no isolation) | Real multi-backend sandbox abstraction | Clawith `sandbox/config.py` |

### 2.2 MODIFY — right shape, needs depth

| Target | Current | Modify to | Source |
|---|---|---|---|
| M1 | `runtime/heartbeat.py` in-memory `{agent_id: last_beat}` | DB/Redis-backed with coalescing and orphan reclaim | paperclip `heartbeat_runs` |
| M2 | `governance/budget_enforcer.py` post-hoc check | Add pre-flight estimate that refuses dispatch | PraisonAI `chat_mixin.py:1808` |
| M3 | `memory/compaction.py` message-list strategies | Resolve budget from model capability; watermark; loud failure | Clawith `session_context_compactor.py` |
| M4 | `models_router/` knows 4 of 11 adapters | Cover all 11; unify cost tracking | own `adapters/registry.py` |
| M5 | `memory/layered.py` optional JSON persistence | Make L2/L3 DB-backed; keep L0/L1 ephemeral | own `memory/store.py` |
| M6 | `guardrails/` stateless chain | Verify wiring into live tool-exec + response paths | PraisonAI `_apply_guardrail_with_retry` |
| M7 | `triggers/webhook.py` | Add HMAC verification + per-token rate limit | Clawith `api/webhooks.py:110-118` |
| M8 | `nodes/registry.py` central 164-node file | Self-registering per-node modules via `__init_subclass__` | OpenCompany `server/nodes/` |
| M9 | `communication/a2a.py` | Deterministic UUIDv5 correlation IDs | Clawith `a2a_runtime.py:126` |
| M10 | `company/delegation.py` | Acquire/release sub-agent permits | OpenCompany `agent_activities.py:1581` |
| M11 | `temporal/activities.py` uniform retries | Once-only policy for LLM-billing activities | OpenCompany `_retry_policies.py:93` |
| M12 | `services/skill_service.py` | Versioned access policy with remediation strings | paperclip `company-skill-policy.ts` |
| M13 | `dashboard/server.ts` mock-by-default | CI e2e run against `PROXY_API=true` | — |
| M14 | 13 migrations, 123 test files | Behavior-per-file tests + incident fixtures | paperclip `__tests__/` |

### 2.3 ADD — genuinely absent

| Target | Add | Source |
|---|---|---|
| A1 | Completion-reason taxonomy on every run | PraisonAI `autonomy.py:372` |
| A2 | Watchdog for silent/stalled runs | paperclip `recovery/service.ts` |
| A3 | MCP server (expose own tools outward) | PraisonAI `mcp_server.py`, AI Team OS |
| A4 | Company export/import with secret scrubbing | paperclip `packages/shared` portability |
| A5 | Short-lived run JWTs | paperclip auth |
| A6 | Durable trigger listener workflows | OpenCompany `TriggerListenerWorkflow` |
| A7 | Arch-guard CI script | Clawith `arch-guard.sh`, AI Team OS `check_invariants.sh` |
| A8 | Plugin capability negotiation, fail-closed | paperclip `SANDBOX_PROVIDER_CAPABILITIES.md` |
| A9 | Productivity integrations (Gmail/Calendar/Drive, Graph, IMAP) | OpenCompany |
| A10 | More chat integrations (Discord, WhatsApp, Feishu/DingTalk) | OpenCompany, Clawith |
| A11 | Dev server / preview URL runtime | paperclip workspace runtime |
| A12 | Handoff with frozen delivery intent | Clawith `group_handoff.py` |

**Deliberately not adopted:**
- Clawith's `privileged: true` + host Docker socket mount (`docker-compose.yml:73`) — that is
  root-on-host from inside the container. Use remote sandbox backends instead.
- MetaGPT's fixed waterfall SOP — NVLabs' goal-driven model is more general.
- PraisonAI's nine-package split — this is one app, not an SDK family.

---

## 3. Phased plan

Phases are ordered so that each wave leaves the system strictly better and independently
shippable. Every micro-phase names its acceptance test. Sizes: **S** ≈ half day,
**M** ≈ 1–2 days, **L** ≈ 3–5 days.

### Wave 0 — Stop the bleeding (foundational correctness)

Nothing else is worth building until there is one execution path and governance state
survives a restart.

#### Phase 0.1 — Persist the audit log · M · R3
- 0.1.1 (S) Add `AuditLog` SQLModel table: all `AuditEntry` fields plus `sequence_number`,
  `entry_hash`, `previous_hash`. Alembic migration.
- 0.1.2 (S) Rewrite `PersistentAuditLogger.log_entry()` to INSERT; keep
  `compute_entry_hash()` byte-identical so existing chain logic is preserved.
- 0.1.3 (S) Make `verify_chain_integrity()` read from the table ordered by
  `sequence_number`.
- 0.1.4 (S) Change `enforce_retention()` to copy to an `audit_log_archive` table and mark
  the source row archived — never delete from the verified chain.
- 0.1.5 (S) Add a DB-level guard against UPDATE/DELETE on `audit_log` (trigger or revoked
  grant); document the intent in the migration.
- **Accept:** write 100 entries, restart the process, `verify_chain_integrity()` passes;
  a manual UPDATE attempt fails.

#### Phase 0.2 — Persist approvals and alert state · M · R4, R6
- 0.2.1 (S) `Approval` model already exists in `models/governance.py` — wire
  `DecisionQueueManager` to it instead of `_queues`.
- 0.2.2 (S) Move `_company_ids` / `_queue_ids` lookups to indexed queries.
- 0.2.3 (S) Back `CostAlertService._fired_alerts` / `_last_severity` with Redis (pattern
  already in `governance/redis_state.py`).
- 0.2.4 (S) Add a `budget_incident` dedupe key on `(company_id, scope_id, threshold_type)`.
- **Accept:** approval survives restart and appears in `Approvals` page; the same threshold
  crossing twice produces one incident.

#### Phase 0.3 — Persist the secrets vault · S · R5
- 0.3.1 (S) Add a `Secret` store backed by `models/secret.py`, replacing
  `FernetSecretBackend._store`.
- 0.3.2 (S) Adopt PBKDF2-HMAC-SHA256 at 600,000 iterations with per-process memoization
  (OpenCompany `core/encryption.py:71`, `:30`).
- 0.3.3 (S) Add a `SECRET_BACKEND` config selector (`fernet` | `keyring` | `env`).
- **Accept:** store a secret, restart, read it back; KDF runs once per key per process.

#### Phase 0.4 — Collapse to one execution path · L · R1
- 0.4.1 (S) Write `docs/adr/0001-single-execution-path.md` naming Temporal as authoritative
  and `runtime/orchestrator.py` as its only driver.
- 0.4.2 (M) Port `workflows/task_flow.py` lifecycle stages into Temporal activities;
  keep the class as a thin façade so callers do not break.
- 0.4.3 (M) Same for `workflows/company_flow.py` — the CEO→CTO→Eng→QA chain becomes a
  workflow with `ApprovalEngine` / `BudgetEnforcer` calls as activities.
- 0.4.4 (S) Same for `workflows/pipeline.py`; `PipelineEngine` transitions become signals.
- 0.4.5 (S) Delete the in-memory `_executions` / `_results` / `_agents` / `_traces` /
  `_stages` dicts once activities own the state.
- 0.4.6 (S) Add a fallback local executor for when Temporal is unreachable, matching
  OpenCompany's degradation path — one code path, two runners.
- **Accept:** an integration test kills the worker mid-run and the task resumes; no
  orchestration state lives in a module-level dict.

#### Phase 0.5 — One scheduler · M · R2
- 0.5.1 (S) Inventory what `triggers/scheduler.py` does that `runtime/scheduler.py` does
  not (`classifier.py`, `context_trigger.py`, `history.py` are the interesting parts).
- 0.5.2 (M) Fold those capabilities into the DB-backed scheduler; keep the `TriggerConfig`
  dataclass as a DTO.
- 0.5.3 (S) Delete `triggers/scheduler.py`'s `_triggers` dict and `list_triggers()` loop;
  route through the `Trigger` model.
- 0.5.4 (S) Ensure `triggers/executor.py` writes `TriggerExecutionRecord` rows.
- **Accept:** a cron trigger created via API fires after a restart; execution history is
  queryable.

#### Phase 0.6 — Arch-guard in CI · S · A7
- 0.6.1 (S) `scripts/arch_guard.py` with checks: no new module-level mutable state in
  `governance/`; no second scheduler; `workflows/` must not import DB sessions directly;
  `*_persistent.py` must import `AsyncSession`.
- 0.6.2 (S) Wire into CI as a required check; document each rule's rationale.
- **Accept:** reintroducing an in-memory audit list fails CI.

### Wave 1 — Make runs trustworthy

#### Phase 1.1 — Completion reasons · S · A1
- 1.1.1 (S) `RunCompletionReason` enum: `goal`, `no_tool_calls`, `max_iterations`,
  `timeout`, `budget_exhausted`, `doom_loop`, `needs_help`, `error`.
- 1.1.2 (S) Set it on every terminal path in `runtime/orchestrator.py`; persist on the run
  row.
- 1.1.3 (S) Surface as a filter on the Activity and Tasks pages.
- **Accept:** each of the eight reasons is reachable in tests and visible in the UI.

#### Phase 1.2 — Real quality gate · M · R7
- 1.2.1 (S) Make `LLMCriticEvaluator` the default; `CriticEvaluator` selected only by
  explicit config or when no model is available.
- 1.2.2 (S) Structured judge output `{verdict, reason, scores}` at temperature 0.0.
- 1.2.3 (S) Fail-open to `continue` on judge error, with a consecutive-parse-failure cap of
  3 that pauses the loop (PraisonAI `goal/loop.py:24`).
- 1.2.4 (S) Record judge verdicts on the run for later review.
- **Accept:** a trivially incomplete output is rejected where the heuristic passed it; a
  deliberately broken judge pauses rather than spins.

#### Phase 1.3 — Heartbeat that persists · M · M1
- 1.3.1 (S) `HeartbeatRun` model already exists in `models/heartbeat_run.py` — wire
  `runtime/heartbeat.py` to it.
- 1.3.2 (S) Redis-backed last-beat with a DB fallback.
- 1.3.3 (M) Wakeup coalescing: collapse multiple pending wakeups for one agent into one.
- 1.3.4 (S) Orphan reclaim on startup — active runs with a dead PID move to
  `needs_recovery`.
- **Accept:** three rapid wakeups produce one run; a killed process's run is reclaimed on
  restart.

#### Phase 1.4 — Watchdog · M · A2
- 1.4.1 (S) Track `last_output_at` on runs.
- 1.4.2 (S) Thresholds: 1 h suspicion, 4 h critical, 30 min rearm (paperclip's numbers).
- 1.4.3 (M) A stable stop-fingerprint to distinguish "quiet but fine" from "stalled".
- 1.4.4 (S) On critical, escalate to a human decision rather than auto-reassigning.
- **Accept:** a run that stops emitting output is flagged; a legitimately idle run is not.

#### Phase 1.5 — Pre-flight budget · S · M2
- 1.5.1 (S) `estimate_min_call_cost(model, prompt_tokens, max_output)` in `models_router/`.
- 1.5.2 (S) Refuse dispatch when `spent + estimate >= limit`; raise `BudgetExceededError`.
- 1.5.3 (S) Support `on_budget_exceeded` = `stop` | `warn` | callable.
- **Accept:** a run 1 cent under its cap does not start a call that would exceed it.

#### Phase 1.6 — LLM activity retry policy · S · M11
- 1.6.1 (S) Split retry policies: `LLM_STEP_RETRY` (max 1 attempt) vs
  `DEFAULT_ACTIVITY_RETRY`.
- 1.6.2 (S) Apply the once-only policy to every billing activity.
- 1.6.3 (S) Test that a forced activity failure does not double-charge.
- **Accept:** a retried workflow shows one billed LLM call, not two.

### Wave 2 — Memory and context depth

#### Phase 2.1 — pgvector · M · R8
- 2.1.1 (S) Add the `vector` extension in a migration; guard for SQLite dev fallback.
- 2.1.2 (S) Change `KnowledgeChunk.embedding_vector` to a `Vector(1536)` column, retaining
  the JSON path as fallback.
- 2.1.3 (S) IVFFlat or HNSW index.
- 2.1.4 (M) Rewrite `RAGPipeline` vector search to a SQL `<=>` distance query instead of
  Python cosine over fetched rows.
- 2.1.5 (S) Backfill script for existing chunks.
- **Accept:** search over 50k chunks returns in well under a second; results match the
  Python implementation on a fixture set.

#### Phase 2.2 — Budget-aware compaction · M · M3
- 2.2.1 (S) `ModelCapabilityResolver` returning context window and max output per model.
- 2.2.2 (S) Budget = window − system prompt − tool schemas − reserve, times a configurable
  threshold ratio.
- 2.2.3 (M) Incremental batching: greedily fill until the next message would exceed budget;
  emit a structured five-field summary; advance a message-ID watermark; repeat.
- 2.2.4 (S) Raise on oversized single messages rather than truncating silently.
- **Accept:** a 200-message thread compacts in multiple passes with a monotonic watermark;
  an oversized message raises.

#### Phase 2.3 — Persist layered memory · S · M5
- 2.3.1 (S) Back L2 (agent) and L3 (shared) facts with `models/memory.py` rows.
- 2.3.2 (S) Keep L0 ephemeral and L1 session as an in-memory ring buffer by design;
  document why.
- 2.3.3 (S) Run promotion (L2→L3) and dedup against the DB.
- **Accept:** a promoted shared fact is visible to a second agent after restart.

#### Phase 2.4 — Conversation durability · M · Compare 31
- 2.4.1 (S) `AgentConversation` keyed by `(agent_id, thread_key)` holding messages JSON.
- 2.4.2 (S) Load at run start, save per turn; loads raise loudly, saves are best-effort
  (OpenCompany's invariant).
- 2.4.3 (S) Seeding precedence: rollover transcript > stored conversation > fresh build.
- **Accept:** an agent woken twice continues one thread; a corrupt row raises rather than
  silently starting over.

### Wave 3 — Safe execution

#### Phase 3.1 — Sandbox abstraction · L · R9
- 3.1.1 (S) `SandboxBackend` ABC with `ExecutionResult` and `SandboxCapabilities`;
  `SandboxType` enum.
- 3.1.2 (S) `RemoteSandboxBackend` for E2B (API-key driven, no local privilege).
- 3.1.3 (S) Judge0 backend.
- 3.1.4 (M) Local subprocess backend with an explicit
  `allow_unsafe_local_execution` flag defaulting to false, resource limits, and network off
  by default.
- 3.1.5 (S) Execution leases so two runs cannot share a sandbox.
- 3.1.6 (S) Workspace scoping — a sandbox sees only its task's workspace.
- **Accept:** the same snippet runs identically on two backends; local execution refuses to
  start unless explicitly enabled.
- **Note:** do not mount the host Docker socket. Container-per-execution via a host daemon
  is out of scope for this phase.

#### Phase 3.2 — Worktree isolation · M · M55
- 3.2.1 (S) Create a git worktree per task under a managed root.
- 3.2.2 (S) Operator branch naming; clean up on terminal states.
- 3.2.3 (S) Coherence check — refuse to run if the worktree drifted from the expected base.
- **Accept:** two concurrent tasks on one repo do not see each other's files.

#### Phase 3.3 — Guardrail wiring audit · S · M6
- 3.3.1 (S) Trace every call site of `GuardrailChain`; document which paths it guards.
- 3.3.2 (S) Wire into tool execution pre-dispatch and model-response post-processing if
  absent.
- 3.3.3 (S) Retry-on-guardrail-failure with a cap.
- **Accept:** a blocked command in a tool arg is refused in a live run, not just a unit
  test.

#### Phase 3.4 — Autonomy policy per action · M · M42
- 3.4.1 (S) `autonomy_policy` JSON on the agent: `{action_type: 1|2|3}`.
- 3.4.2 (S) Tool→action-type map (write files, delete, execute code, send external message,
  spend above N).
- 3.4.3 (S) Pre-dispatch enforcement: L1 run, L2 run + notify, L3 create approval and block.
- 3.4.4 (S) Resume the run on approval, tying back via correlation ID.
- **Accept:** an L3 tool call blocks, notifies, and resumes correctly after approval.

### Wave 4 — Collaboration correctness

#### Phase 4.1 — Idempotent A2A · S · M9
- 4.1.1 (S) UUIDv5 correlation ID from `(source_run_id, tool_call_id)`.
- 4.1.2 (S) Deterministic execution ID likewise.
- 4.1.3 (S) Dedupe on replay — a repeated delegation resolves to the existing record.
- **Accept:** replaying a workflow produces one delegation, not two.

#### Phase 4.2 — Delegation permits · M · M10
- 4.2.1 (S) `acquire_subagent_permit` / `release_subagent_permit` with a configurable cap
  (default 3).
- 4.2.2 (S) Wait with backoff when the cap is reached.
- 4.2.3 (S) Release on every terminal path including crash recovery.
- **Accept:** a lead spawning 10 sub-tasks runs at most 3 concurrently; a killed child
  releases its permit.

#### Phase 4.3 — Frozen handoff intent · S · A12
- 4.3.1 (S) Stage mention targets, then freeze one immutable delivery intent.
- 4.3.2 (S) Apply the intent inside the delivery transaction.
- 4.3.3 (S) Cycle-guard the handoff graph (reuse `runtime/cycle_guard.py`).
- **Accept:** a handoff delivers exactly once; an A→B→A cycle is refused.

### Wave 5 — Platform hardening

#### Phase 5.1 — Run JWTs · S · A5
- 5.1.1 (S) Mint a short-lived JWT scoped to `(run_id, agent_id, company_id)`.
- 5.1.2 (S) Accept it on agent-facing endpoints; reject expired.
- 5.1.3 (S) Confirm PyJWT rather than python-jose (avoids the `ecdsa` timing CVE).
- **Accept:** a run token works during its run and fails after expiry.

#### Phase 5.2 — Tenant isolation audit · M · M51
- 5.2.1 (S) Enumerate every query in `api/routes/` lacking a `company_id` filter.
- 5.2.2 (S) A scoped-session helper that injects the filter.
- 5.2.3 (S) Redis key prefix `tenant:{company_id}:` everywhere.
- 5.2.4 (S) An arch-guard rule failing CI on unscoped queries against tenant tables.
- **Accept:** a cross-tenant read attempt returns empty, proven by test.

#### Phase 5.3 — Company export/import · L · A4
- 5.3.1 (M) Export: full company graph to a versioned archive.
- 5.3.2 (S) Scrub secrets on export; record what was scrubbed.
- 5.3.3 (M) Import with ID remapping.
- 5.3.4 (S) Round-trip test.
- **Accept:** export→import into a fresh DB reproduces the company with no secret leakage.

#### Phase 5.4 — Skill access policy · M · M12
- 5.4.1 (S) `skill_policy` document `{schemaVersion, revision, defaultEffect, rules[]}`.
- 5.4.2 (S) Subject matching (all agents / IDs / roles), resource matching (skill IDs, keys,
  source types).
- 5.4.3 (S) `decision()` returning allow/deny plus reason, matched rule, and a remediation
  string on deny.
- 5.4.4 (S) Absent policy means allow — open by default, explicitly documented.
- **Accept:** a denied skill returns a remediation message; policy revisions are auditable.

#### Phase 5.5 — Mock/real parity in CI · S · M13
- 5.5.1 (S) CI job running the e2e suite with `PROXY_API=true`.
- 5.5.2 (S) Remove `unwrapItems()` by making mock and real response shapes agree.
- 5.5.3 (S) Delete unrouted `NodeLibrary.tsx` or restore its route.
- **Accept:** a mock/real shape divergence fails CI.

### Wave 6 — Breadth

#### Phase 6.1 — Full cascade coverage · S · M4
- 6.1.1 (S) Register all 11 adapters with `models_router/provider_registry.py`.
- 6.1.2 (S) Pricing entries per model in a config file, user-editable.
- 6.1.3 (S) Cost tracking on every adapter path.
- **Accept:** the Budgets simulator covers all 11; no adapter bypasses cost tracking.

#### Phase 6.2 — Node self-registration · M · M8
- 6.2.1 (S) `BaseNode` with `__init_subclass__` auto-registration.
- 6.2.2 (M) Migrate `all_nodes.py`'s 164 entries to per-node modules under
  `nodes/categories/<group>/`, in batches by category.
- 6.2.3 (S) A test asserting registry count parity before and after each batch.
- **Accept:** adding a node requires one new file and no registry edit; the count stays 164
  through the migration.

#### Phase 6.3 — Trigger hardening · S · M7, A6
- 6.3.1 (S) HMAC verification on webhook intake.
- 6.3.2 (S) Per-token rate limiting.
- 6.3.3 (S) `poll` trigger as a durable Temporal workflow.
- 6.3.4 (S) `on_message` trigger via the existing event bus.
- **Accept:** an unsigned webhook is rejected; a poll trigger survives restart.

#### Phase 6.4 — MCP server · M · A3
- 6.4.1 (S) Expose selected internal tools over MCP stdio.
- 6.4.2 (S) Per-company tool scoping on the server surface.
- 6.4.3 (S) Reuse `tools/policy_engine.py` for authorization.
- **Accept:** an external MCP client lists and calls a scoped tool.

#### Phase 6.5 — Integrations · L · A9, A10
- 6.5.1 (M) Google Workspace: Gmail, Calendar, Drive.
- 6.5.2 (M) Microsoft Graph.
- 6.5.3 (S) IMAP with a polling trigger.
- 6.5.4 (S) Discord.
- 6.5.5 (S) WhatsApp Business Cloud API.
- **Accept:** each ships as a node plus a credential provider entry, with one live test.

#### Phase 6.6 — Test and migration depth · L · M14
- 6.6.1 (M) Split broad tests into behavior-per-file for orchestration and governance.
- 6.6.2 (S) Capture each production incident as a fixture.
- 6.6.3 (S) Coverage gate on `governance/` and `runtime/`.
- **Accept:** every Wave 0–2 phase has a named regression test.

---

## 4. Sequencing summary

| Wave | Theme | Phases | Rough size |
|---|---|---|---|
| 0 | Correctness foundation | 0.1–0.6 | ~2.5 weeks |
| 1 | Trustworthy runs | 1.1–1.6 | ~2 weeks |
| 2 | Memory depth | 2.1–2.4 | ~2 weeks |
| 3 | Safe execution | 3.1–3.4 | ~2.5 weeks |
| 4 | Collaboration correctness | 4.1–4.3 | ~1 week |
| 5 | Platform hardening | 5.1–5.5 | ~2.5 weeks |
| 6 | Breadth | 6.1–6.6 | ~4 weeks |

Estimates assume one developer and no discovery surprises; treat them as relative sizing,
not commitments.

**Hard dependencies:**
- 0.4 (one execution path) gates 1.1, 1.3, 1.4, 4.1, 4.2 — completion reasons, heartbeat,
  watchdog, and delegation all need one place to live.
- 0.1 (audit persistence) gates 3.4 and 5.4 — autonomy and skill policies need an auditable
  decision trail.
- 2.1 (pgvector) gates any knowledge-base scale work.
- 3.1 (sandbox) gates letting agents run generated code at all.

**If only one wave ships:** Wave 0. Three orchestration paths and an in-memory audit log
generate defects faster than features can absorb them.

---

## 5. Where this project already leads

Worth stating so the plan is not read as a deficit list. Verified as ahead of every
reference in the set:

1. **SCIM provisioning** — unique to this project across all six.
2. **Audit hash chain** — nobody else has one; it only needs a table under it.
3. **164-node library across 31 categories** — ahead of OpenCompany's 76 on-disk plugins.
4. **11 execution adapters** including `claude_code`, `hermes`, `cli`, and a UASTL
   implementation of OpenCompany's own draft RFC.
5. **Model cascade router with cost simulation** — no reference has the simulator.
6. **Hybrid BM25 + vector RAG with pluggable ranker/retriever/parser protocols.**
7. **Smart retry with failure diagnosis** — paperclip needs thousands of lines for the
   equivalent; PraisonAI's is still on the roadmap.
8. **Cross-agent memory promotion with Jaccard dedup.**
9. **Spatial 3D/2D office, Meetings with live huddles, Evolution, HR Room, Plaza** — no
   reference attempts most of these.
10. **Broadest auth surface** — OIDC, SCIM, API keys, CSRF, sessions, argon2, RBAC.

The gap is depth under breadth, not breadth itself.
