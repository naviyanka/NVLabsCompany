# NVLabsCompany vs. Reference Repositories — Deep Comparison

**Date:** 2026-08-26
**Baseline:** NVLabsCompany (`nexus`), branch `main` @ `01d02e8`
**Method:** all six reference repos cloned to `temp_repos/`, each indexed into its own
graphify knowledge graph, then read directly by parallel exploration agents. Every
structural claim below is traced to a file path; scale figures come from direct counts
over the working trees.

---

## 1. Scope and method

### 1.1 Repositories compared

| Repo | Origin | Stars | License | Primary lang | Last push |
|---|---|---|---|---|---|
| paperclip | `paperclipai/paperclip` | 79,431 | MIT | TypeScript | 2026-08-26 |
| MetaGPT | `FoundationAgents/MetaGPT` | 70,050 | MIT | Python | 2026-01-21 |
| PraisonAI | `MervinPraison/PraisonAI` | 8,964 | MIT | Python | 2026-08-26 |
| Clawith | `dataelement/Clawith` | 4,138 | Apache-2.0 | Python | 2026-08-25 |
| OpenCompany | `zeenie-ai/OpenCompany` | 677 | MIT | Python | 2026-08-24 |
| AI Team OS | `AI-company` (local clone) | — | — | Python | v1.11.3 |
| **NVLabsCompany** | this repo | — | — | Python | 2026-08-26 |

MetaGPT is the only reference that is not actively maintained — roughly seven months
since its last push, versus same-week activity for the other four public repos.

### 1.2 Knowledge graphs built

One graph per repo, code-only AST extraction (no LLM, no API key), written to
`temp_repos/<repo>/graphify-out/graph.json`:

| Repo | Nodes | Edges | Communities | Graph size |
|---|---|---|---|---|
| PraisonAI | 108,308 | 188,877 | 3,321 | — |
| paperclip | 44,367 | 121,062 | 1,133 | 65 MB |
| OpenCompany | 17,818 | 39,347 | 701 | 23 MB |
| Clawith | 14,409 | 45,463 | 415 | 25 MB |
| AI Team OS | 13,046 | 31,791 | 440 | — |
| MetaGPT | 8,290 | 18,942 | 415 | — |
| **NVLabsCompany** | **8,299** | — | — | (pre-existing) |

Each is independently queryable, e.g.:

```bash
cd temp_repos/paperclip && graphify query "how does the heartbeat wakeup queue work"
cd temp_repos/Clawith  && graphify query "how does the LangGraph state machine route turns"
```

Graph size is a rough proxy for structural surface area. Note that NVLabsCompany's graph
(8,299 nodes) is the smallest of the seven — comparable to MetaGPT, and roughly 5× smaller
than paperclip's.

---

## 2. Scale at a glance

| Repo | Python files / LOC | TS-TSX files / LOC | Test files | Migrations |
|---|---|---|---|---|
| paperclip | — | 3,599 / 1,313,866 | 1,414 | Drizzle SQL |
| PraisonAI | 4,492 / 1,049,105 | 481 / 94,896 | 1,529 | n/a (library) |
| Clawith | 604 / 242,551 | 123 / 44,203 | 197 | 70 |
| OpenCompany | 898 / 204,047 | 295 / 49,970 | 262 | — |
| AI Team OS | 435 / 127,691 | 119 / 22,114 | 185 | hand-rolled |
| MetaGPT | 890 / 88,865 | 8 / 782 | 249 | n/a (library) |
| **NVLabsCompany** | **351 / 77,228** | **132 tsx / 55,739** | **123** | **13** |

NVLabsCompany is the smallest codebase in the set on the backend. Frontend LOC is
mid-pack and disproportionately large relative to its backend (0.72:1 frontend:backend,
versus 0.29:1 for Clawith and 0.24:1 for OpenCompany) — a UI-forward ratio.

### Migration count as a maturity signal

Clawith has 70 Alembic migrations against NVLabsCompany's 13. Migration count tracks how
many times a schema has survived contact with real data. This is one of the sharpest
maturity gaps in the comparison and is not something feature work closes.

---

## 3. Architectural archetypes

The six references are not six versions of the same thing. They fall into four distinct
archetypes, and NVLabsCompany overlaps with three of them at once.

### 3.1 Control plane — orchestrates agents that execute elsewhere

**paperclip.** Explicitly not an agent runtime. It registers agents, assigns tasks,
tracks spend, and monitors heartbeats; actual execution happens in external adapters
(`packages/adapters/*` — 13 of them: claude-local, codex-local, cursor-cloud/local,
gemini-local, grok-local, hermes, hermes-gateway, kimi-local, openclaw-gateway,
opencode-local, pi-local). The design separates four concerns deliberately and never
conflates them (`doc/execution-semantics.md`, 840 lines): structure (parent/sub-issue),
dependency (blockers), ownership (assignee), execution (live run path).

### 3.2 Node canvas — visual workflow engine, agent-first

**OpenCompany.** Drag-and-drop React Flow canvas over a plugin-per-node backend. A node
is one self-contained Python folder under `server/nodes/<group>/<plugin>/__init__.py`
subclassing `BaseNode`; `__init_subclass__` auto-registers metadata, schema, handlers, and
the Temporal activity. Backend `NodeSpec` is the single source of truth for icon, color,
handles, and params — the frontend renders generically and contains zero node-specific
code. 76 plugin directories confirmed on disk across 37 top-level groups (the README's
"146 nodes across 31 categories" counts registered node types, not directories; the repo
deliberately never hardcodes the number anywhere, instructing readers to query the live
registry).

### 3.3 Agent framework / library — no app, no tenancy

**PraisonAI** and **MetaGPT**. Neither ships a company. PraisonAI is a nine-package tiered
SDK (`praisonai-agents` core, plus code/bot/train/browser/mcp/sandbox/deploy and a wrapper),
with TypeScript and Rust ports tracked for parity. Confirmed absent from PraisonAI: any org
chart or company hierarchy model, any budget dashboard UI, and any real multi-tenancy —
`tenant_id` appears nowhere; the only mentions are comments noting the registry design
*permits* a multi-tenant host to inject its own. MetaGPT is a role-based SOP simulation
(ProductManager → Architect → ProjectManager → Engineer → QA) driven from a CLI entry point
`metagpt = metagpt.software_company:app`, with message routing funnelled through a
TeamLeader role literally named "Mike" (`metagpt/const.py`, `TEAMLEADER_NAME`).

### 3.4 Multi-tenant enterprise agent platform

**Clawith.** The closest structural analogue to what NVLabsCompany appears to be building:
FastAPI + LangGraph + Postgres + Redis, multi-tenant from the ground up, with a web UI, an
OKR module, a Plaza social feed, groups, org departments, SSO, and channel integrations
(Feishu, Slack, Discord, DingTalk, Atlassian, Google Workspace).

**AI Team OS** is a fifth, narrower archetype: a governance layer for Claude Code
sub-agent teams, distributed as a CC plugin (113 MCP tools, 208 REST endpoints, SQLite at
`~/.claude/data/ai-team-os/aiteam.db`), with no background daemon by design.

### 3.5 Where NVLabsCompany sits

NVLabsCompany spans archetypes 1, 2, and 4 simultaneously — control plane (agents, org
chart, budgets, approvals), node canvas (Pipelines, NodeLibrary, 164-node palette), and
multi-tenant platform (companies, SSO, SCIM, RBAC) — plus surfaces none of the references
have (3D Office, Plaza feed, HR Room, Meetings with live huddles, Evolution). That breadth
is the defining characteristic of the project, and it is the source of both its ambition
and its main structural risk (§6).

---

## 4. Subsystem-by-subsystem comparison

### 4.1 Agent execution loop

| Repo | Mechanism | Durability |
|---|---|---|
| Clawith | LangGraph `StateGraph`: `control_guard` → routes to `compact` / `model` / `tool` / `verify` / `wait` / `terminal`, each looping back to `control_guard` (`backend/app/services/agent_runtime/graph.py:257-291`); node bodies in `node_executor.py:559` `DeterministicRuntimeNodeExecutor` | Postgres LangGraph checkpoint is authoritative |
| OpenCompany | Temporal `AgentWorkflow` (`server/services/temporal/agent_workflow.py:507`) schedules activities; all I/O is an activity | Temporal event history |
| paperclip | `server/src/services/heartbeat.ts` — 19,767 lines, call-graph degree 747; runs recorded in `heartbeat_runs` with `processPid`, `livenessState`, watchdog fingerprints | Postgres run ledger + watchdog recovery |
| PraisonAI | `Agent` = 12 mixins (`agent/agent.py:292`); `run_autonomous` (`agent.py:4168`); inner `while True:` in `chat_mixin.py:3466` / `:4095` | In-process; optional DB adapter |
| MetaGPT | `Role._observe/_think/_act`, messages routed via `Environment` / `MGXEnv` | Serialization to `SERDESER_PATH` |
| **NVLabsCompany** | `runtime/orchestrator.py` — background asyncio task started at app lifespan, composing `GoalMonitor → TaskPlanner → AgentRouter → ParallelExecutor → CriticEvaluator → GoalLoop → SmartRetry → FailureAnalyzer` | Mixed — see §6 |

NVLabsCompany is unusual in having **three parallel orchestration paths** that do not share
a state model:

1. `runtime/orchestrator.py` composing the pure `src/nexus/orchestration/*` modules
2. `src/nexus/temporal/` (`GoalPursuitWorkflow`, `PipelineExecutionWorkflow`) — durable
3. `src/nexus/workflows/` (`task_flow.py`, `pipeline.py`, `company_flow.py`) — in-memory dicts

Plus two independent trigger schedulers: `runtime/scheduler.py` (DB-backed, 60-second tick)
and `src/nexus/triggers/` (in-memory list store). Every reference repo has exactly one
authoritative execution state machine, and Clawith enforces that as a constitutional law:

> Invariant C1: API/product code must never become a second execution state machine — it
> must submit through `RuntimeCommandIntake`, never touch checkpoint tables or call graph
> nodes directly. (`docs/constitution.md`, enforced by `scripts/arch-guard.sh`)

### 4.2 Completion reasons and loop safety

PraisonAI has the most explicit termination taxonomy in the set. `run_autonomous` reports
one of `goal | no_tool_calls | max_iterations | timeout | budget_exhausted | doom_loop |
needs_help | error` (`agent/autonomy.py:372`). Doom-loop detection is a real subsystem:
`escalation/doom_loop.py` defines six types (`REPEATED_ACTION`, `REPEATED_FAILURE`,
`NO_PROGRESS`, `CIRCULAR_PLAN`, `RESOURCE_EXHAUSTION`, `REPEATED_OUTPUT`), and
`agent/autonomy.py:403` `DoomLoopTracker` delegates to it. Goal completion is adjudicated
by an independent LLM judge at temperature 0.0 (`goal/judge.py:174`) that **fails open** to
`continue` on any exception or parse failure, with `_MAX_CONSECUTIVE_PARSE_FAILURES = 3`
(`goal/loop.py:24`) as the safety valve against a wedged judge.

NVLabsCompany's equivalents: `runtime/cycle_guard.py` (`MAX_CYCLE_COUNT = 5`,
`MAX_ANCESTOR_DEPTH = 256`) and `orchestration/smart_retry.py`, which diagnoses error
patterns via a `Counter` and escalates to `REPORT_BLOCKER` / `DECOMPOSE` / `REASSIGN` /
`RETRY` rather than retrying blindly. The escalation taxonomy is a genuine strength — but
the quality gate feeding it is weak: `orchestration/critic.py` `CriticEvaluator` scores
completeness as `len(result)/100`, correctness as a flat 0.8 if output exists, and quality
as `len > 10`. An LLM-backed sibling exists (`llm_critic.py`), so the heuristic is a
fallback rather than the design — but any run path using the default gets near-meaningless
quality signal.

### 4.3 Durable execution

Only three repos in the set have real durability.

**OpenCompany** is the most carefully engineered here. Six workflows
(`AgentWorkflow`, `DelegatedTaskWorkflow`, `PollingTriggerWorkflow`,
`TriggerListenerWorkflow`, `WorkflowControlWorkflow`, `MachinaWorkflow`) contain no I/O;
everything that touches an LLM, the DB, a socket, or a subprocess is an activity in
`server/services/temporal/agent_activities.py` — `agent.execute_llm_step:405`,
`agent.persist_turn:452`, `agent.broadcast_progress:531`, `agent.store_output:654`,
`agent.compact_context:1944`, plus a full delegation lifecycle
(`begin/queue/cancel/finish_delegation`, `acquire/release_subagent_permit`,
`register_task_execution`, `finalize_team`). The double-billing problem is solved
explicitly: `agent.execute_llm_step` gets a dedicated one-shot retry policy
(`LLM_STEP_RETRY` in `_retry_policies.py:93`) precisely because LLM calls are not
idempotent, while other activities use `DEFAULT_ACTIVITY_RETRY` / `QUICK_ACTIVITY_RETRY` /
`DELEGATION_CLEANUP_RETRY` / `PERMIT_WAIT_RETRY`.

**Clawith** uses LangGraph's Postgres checkpointer as the authoritative execution store —
`AsyncPostgresSaver` in a dedicated `langgraph_checkpoint` schema
(`backend/app/services/agent_runtime/checkpointer.py:22`, `:173-177`), optionally
AES-encrypted via `EncryptedSerializer` when `LANGGRAPH_AES_KEY` is set (`:150-166`).

**paperclip** does it without a workflow engine, using a Postgres run ledger plus an
unusually thorough recovery layer: `recovery/service.ts` (6,366 lines) with silence
thresholds (1 h suspicion, 4 h critical, 30 min continue-rearm) and `task-watchdogs.ts`
(1,815 lines) whose classifier uses a `stableStopFingerprint` to distinguish "nothing
changed, still fine" from "restoration failed, refire". Their recovery policy is
deliberately conservative: never auto-reassign, never infer dependency from `parentId`,
preserve ownership, escalate to a human when unsafe.

**NVLabsCompany** has Temporal wired (`temporal/workflows.py`, `activities.py`,
`worker.py` polling the `nexus-main` queue) and `runtime/checkpoint.py` is a real SQLModel
table with `recover_interrupted()` for crash resume. This is the right foundation. The gap
is that the other two orchestration paths bypass it entirely.

### 4.4 Memory and context

| Repo | Tiers | Vector store | Compaction |
|---|---|---|---|
| Clawith | Redis (pub/sub only), Postgres (durable), LangGraph checkpoint (execution) | **None** | `session_context_compactor.py` — budget-constrained incremental batching |
| OpenCompany | Plain conversation store per `(workflow_id, generation, agent_node_id)`; separate durable Memory tool | Chroma / Qdrant / Pinecone | `agent.compact_context` activity; five-section summary near context limit |
| PraisonAI | short-term + long-term SQLite (`short_term.db`, `long_term.db`), entity, user-scoped | Chroma, Mem0, MongoDB, Qdrant (via mem0 graph) | `compaction/compactor.py` |
| MetaGPT | Role memory, long-term memory, `role_zero_memory` | Chroma / FAISS / LanceDB / Milvus / Qdrant | — |
| AI Team OS | episodic `task_memos` (BM25) + directional `memories` (hook-injected) | None | — |
| **NVLabsCompany** | Two parallel systems (below) | **None** | `memory/compaction.py`, 3 strategies |

Clawith's compactor is worth studying because it solves the problem incrementally rather
than in one shot (`backend/app/services/agent_runtime/session_context_compactor.py`):
compute a token budget from model capability minus system prompt, tool schemas, and reserve
margins; greedily fill a batch of new messages until adding one more would exceed the
threshold; force exactly one call to a `commit_session_context` tool whose arguments must
match an exact field set (summary, requirements, decisions, open_items, evidence_refs,
workspace_refs); replace the rolling snapshot with the result; advance a message-ID
watermark; repeat until all new messages are consumed. Input that cannot fit raises
`session_compact_input_too_large` rather than silently truncating.

NVLabsCompany runs two memory systems side by side:

- `memory/store.py` `MemoryStore` — a genuine three-temperature design: hot = in-process
  dict, warm = Postgres (`AsyncSession`, `MemoryRecord`), cold = JSON file archive.
- `memory/layered.py` `LayeredMemoryStore` — a separate L0–L3 system documented as
  augmenting rather than replacing the above. L1 session is an in-memory ring buffer,
  L2 agent and L3 shared are in-memory dicts/lists with *optional* JSON flush; with
  `persist_path=None` nothing is written at all.

Retrieval is pure-Python Okapi BM25 (`memory/retriever.py`, k1=1.5, b=0.75) over a list of
strings passed in by the caller. Deduplication and promotion are Jaccard-similarity based
(`dedup.py`; `promotion.py` promotes L2→L3 at access count ≥ 3 or Jaccard ≥ 0.8 across
≥ 2 agents). There is **no vector store and no embedding model anywhere in the project**.

Clawith also has no vector store, so this is not automatically a defect — but Clawith
compensates with a rigorous LLM-driven compactor, and NVLabsCompany's compactor
(`memory/compaction.py`: TRUNCATE / SUMMARIZE / SLIDING_WINDOW) operates on an in-memory
message list with no budget resolution against real model capability.

### 4.5 Triggers and scheduling

Clawith and NVLabsCompany converge remarkably closely here — same six-ish trigger types,
different rigor.

**Clawith** (`backend/app/services/trigger_runtime/evaluator.py:184-274`,
`evaluate_trigger()` dispatching on `trigger.type`): cron (L206), once (L243), interval
(L255), poll (L261), on_message (L268), webhook (L271 — always returns `None` here because
webhooks are fired externally, not polled). Webhook intake is a separate public path,
`backend/app/api/webhooks.py:45-158`, `POST /api/webhooks/t/{token}`, with HMAC verification
(L110-118) and rate limiting (L56-108) before `enqueue_webhook_execution` (L134). Trigger
rows live in Postgres (`backend/app/models/trigger.py:31`).

**OpenCompany** models triggers as Temporal workflows — `PollingTriggerWorkflow` and
`TriggerListenerWorkflow` — so a long-running listener survives restarts.

**NVLabsCompany** has trigger support twice over. `runtime/scheduler.py` is DB-backed with
a 60-second tick that computes next fire time and invokes the assigned agent's LLM adapter.
`src/nexus/triggers/` (`scheduler.py`, `executor.py`) is a second implementation with a
plain in-memory `_triggers` dict and a `list_triggers()` that filters `self._triggers.values()`
in a Python loop. Two schedulers with different persistence stories is a correctness hazard,
not just duplication.

### 4.6 Budget and cost control

**paperclip** is the reference implementation. `server/src/services/budgets.ts` (960 lines):
`budgetStatusFromObserved()` (L66-75) is a pure function returning `ok` / `warning` /
`hard_stop`; `computeObservedAmount()` (L143-166) sums `costEvents.costCents` from Postgres
filtered by scope (company / agent / project) and window (`calendar_month_utc` or all-time),
with the metric fixed to `billed_cents`. Crossing the soft threshold
(`ceil(amount * warnPercent / 100)`) emits a `budget.soft_threshold_crossed` activity and
creates an approval without pausing; crossing hard calls
`pauseAndCancelScopeForBudget()` (L252), setting `status: "paused"`,
`pauseReason: "budget"`, `pausedAt: now` on the row. Enforcement gates sit before new work
is admitted at L745 (company), L782 (agent), L857 (project), each returning a block reason.
Incidents dedupe on `companyId + scopeId + thresholdType` (L352-374).

**PraisonAI** enforces budget in the chat loop with a pre-call guard: it estimates the
minimum cost of the upcoming call and raises `BudgetExceededError` *before* dispatching if
`_total_cost + estimate >= _max_budget` (`chat_mixin.py:1808-1824`), then re-checks with
real cost after (`:1943-1957`). `on_budget_exceeded` accepts `"stop"` / `"warn"` / a
callable (`config/feature_configs.py:939`). The async path mirrors this exactly
(`:2508-2526`, `:2618-2632`). Pre-flight estimation is the detail worth copying — it
prevents the overspend rather than reporting it.

**OpenCompany** computes cost in `server/services/pricing.py` from a user-editable
`server/config/pricing.json` (USD/MTok for LLMs, plus per-call pricing for API services),
falling back to an empty registry on load failure.

**NVLabsCompany** has `models_router/cost_tracker.py`, `governance/budget_enforcer.py`,
`governance/budget_incident.py`, and a Budgets page with a model cascade router simulator —
architecturally the right pieces. But `governance/cost_alerting.py` `CostAlertService` holds
`_thresholds`, `_callbacks`, `_fired_alerts`, `_last_severity` in in-process dicts, so alert
state does not survive a restart.

### 4.7 Governance, approvals, audit

| Repo | Approval mechanism | Audit persistence |
|---|---|---|
| Clawith | Three-tier autonomy policy per agent per action type (`services/autonomy_service.py`); L1 auto, L2 auto + notify, L3 requires approval | `audit_logs` table (Postgres) |
| paperclip | `services/approvals.ts` generic approval rows; requirement scattered per-feature (budget threshold, hire, protected agent) rather than one central gate | Postgres tables + activity log |
| PraisonAI | `approval/backends.py` — `AutoApproveBackend:71`, `ConsoleBackend:80` (blocking stdin prompt), `WebhookBackend`, `CallbackBackend:304`; gated at `agent/tool_execution.py:1621` `needs_approval` | **None** — `audit/` contains only `baseline_metrics.txt` |
| **NVLabsCompany** | `governance/decision_queue.py`, `Approvals` page, `ApprovalEngine` in `workflows/company_flow.py` | See below |

Clawith's approval model is the most operationally concrete. `_TOOL_AUTONOMY_MAP`
(`backend/app/services/agent_tools.py:2229-2239`) maps specific tools to policy keys —
`write_file`/`move_file` → `write_workspace_files`, `delete_file` → `delete_files`,
`execute_code`/`execute_code_e2b` → `execute_code`, plus messaging and search. The
enforcement hook at `agent_tools.py:4697-4728` looks up the level before running a mapped
tool; at L3 it creates an `ApprovalRequest` row and returns `"⏳... requires approval"`
(L4724), blocking execution until a human approves, with the creator notified.

NVLabsCompany's audit story needs correcting relative to its own naming. `governance/audit.py`
`AuditLogger` keeps `self._entries: list[AuditEntry]` in process memory — its own docstring
says "In production, writes to the AuditLog database table. This implementation maintains an
in-memory log for testing." `governance/audit_persistent.py` `PersistentAuditLogger`, despite
the name and a docstring claiming "database-backed audit with hash chain integrity", also
uses plain Python lists (`_buffer`, `_entries`, `_archived`) with a comment conceding
"Simulated persistent storage". It does add a real SHA-256 hash chain — `compute_entry_hash()`
over `id|actor_type|actor_id|action|resource_type|resource_id|timestamp|company_id|previous_hash`,
verified by `verify_chain_integrity()` (`:180`).

That is tamper *detection*, not tamper *prevention*, and it is not persistence. There is no
DB write path, no append-only file, no WORM storage, and `enforce_retention()` actively
removes entries from the chain after `max_age_days`. Any in-process code holding the logger
can rewrite an entry and recompute the hashes. Compare paperclip and Clawith, where audit
rows are DB rows.

Same pattern in `governance/decision_queue.py` (`_queues`, `_queue_ids`, `_company_ids` —
all in-memory dicts, retention just filters), `governance/health.py` (`_components` dict),
and `governance/secrets/secret_backend.py` (`FernetSecretBackend._store: dict[str, bytes]` —
encrypted values held in-process only).

Genuinely persistent, by contrast: `governance/persistent_kill_switch.py` and
`persistent_circuit_breaker.py` (SQLAlchemy `AsyncSession`), `kill_switch_model.py`
(`SQLModel(table=True)`), and `redis_state.py` / `redis_rate_limiter.py` /
`leader_election.py` (real Redis). The split is clean enough that it reads as a project
mid-migration from scaffolding to real storage, with the governance modules not yet moved.

### 4.8 Guardrails

**PraisonAI** enforces guardrails after the LLM response and before returning to the caller,
with retry on failure — `_apply_guardrail_with_retry` in `chat_mixin.py`, on both the JSON
and plain-text paths. It has three protocols (`guardrails/protocols.py:12`, `:81`, `:132`),
a `GuardrailChain` (`chain.py:11`), and an LLM-as-judge implementation
(`llm_guardrail.py:14`).

**NVLabsCompany** mirrors that structure closely — `guardrails/chain.py` `GuardrailChain`
with `_fail_fast` / `_fail_closed`, `policy.py` `PolicyGuardrail` (blocked patterns,
sensitive paths, dangerous commands, allowed tools), `structural.py` (length, required
fields, JSON schema), `protocol.py` (interface). The package is cleanly stateless
validation logic, which is correct design. What could not be confirmed is where the chain
runs in a live agent path — it should be verified that it is wired into the tool-execution
and model-response paths rather than only exercised by unit tests.

### 4.9 Sandboxing and code execution

**Clawith** offers seven backends via `SandboxType` (`backend/app/services/sandbox/config.py:13-22`):
`subprocess`, `docker`, `e2b`, `judge0`, `codesandbox`, `self_hosted`, `aio_sandbox`. Local
isolation is bubblewrap-based, with `allow_unsafe_fallback_when_bwrap_missing` (`:129`) as an
explicit escape hatch. The Docker backend (`local/docker_backend.py:44-80`) maps language to
image (`python:3.11-slim`, `bash:5.2`, `node:18-slim`) and reaches the host daemon through a
mounted socket.

**Security note on Clawith's deployment posture:** `docker-compose.yml:73` mounts
`/var/run/docker.sock` into the backend container, and the backend runs `privileged: true`
with `SYS_ADMIN` and seccomp/apparmor disabled. Mounting the host Docker socket into a
container is effectively root-on-host from inside that container. Their quickstart is
localhost-oriented, but this configuration should not be exposed to untrusted input or
multi-tenant untrusted code without additional isolation. Do not copy this compose file
pattern into NVLabsCompany without replacing the local Docker path with a remote sandbox
provider (E2B, Judge0, or a self-hosted runner on a separate host).

**paperclip** takes the opposite approach for plugins: capability negotiation with a
fail-closed formula, `effective = verified ∩ declared ∩ narrowing`
(`doc/plugins/SANDBOX_PROVIDER_CAPABILITIES.md:19`) — the host never trusts a plugin's
self-declared capability, intersecting it with what the live worker actually advertised and
a host-side narrowing pass. On config-resolution failure or plugin-identity mismatch, all
effective capabilities resolve to false.

**NVLabsCompany** has `evolution/sandbox.py` and `adapters/`, but no comparable
multi-backend sandbox abstraction was found. If agents will ever execute
model-authored code, this is the single highest-risk gap in the comparison.

### 4.10 Multi-agent collaboration

| Repo | Mechanism |
|---|---|
| Clawith | `group_at.py` (an `at` tool stages up to 100 participant IDs for visible mention; agent targets get woken as new Runs, humans just get mentioned), `group_handoff.py` (freezes one immutable delivery intent, applied inside the delivery transaction, cycle-protected by `AgentCycleGuard`), `a2a_runtime.py` (three modes — `notify` / `consult` / `task_delegate` — with deterministic UUIDv5 correlation IDs per source-run + tool-call so retries are idempotent) |
| OpenCompany | Team leads assign bounded work through a Task Manager; up to three descendants run in parallel; completion requires lead acceptance. Implemented as Temporal `DelegatedTaskWorkflow` + `agent.acquire_subagent_permit` / `release_subagent_permit` activities |
| PraisonAI | Three processes — `sequential`, `hierarchical`, `workflow` (`process/process.py:20`); explicitly rejects `"parallel"` as a process value (`agents/agents.py:937`). Handoffs via `task.next_tasks` / `previous_tasks` edges; hierarchical injects a synthetic manager task driven by `manager_llm`. Separate per-agent `agent/handoff.py` for direct transfer |
| MetaGPT | `Environment` pub/sub; `MGXEnv` funnels nearly all inter-role messages through the TeamLeader role, with direct human-to-role chat as the one bypass |
| paperclip | Org chart via self-referencing `agents.reportsTo` (`packages/db/src/schema/agents.ts:24`), delegation through task assignment, atomic checkout to prevent duplicate work |
| **NVLabsCompany** | `communication/a2a.py`, `a2a_router.py`, `hive_manager.py`, `event_bus.py`, `group.py`; `company/delegation.py`, `org_chart.py`; `workflows/company_flow.py` (CEO → CTO → Engineers → QA chain gated by `ApprovalEngine` + `BudgetEnforcer`) |

Two ideas here are worth importing directly. Clawith's **deterministic UUIDv5 correlation
IDs** derived from source-run plus tool-call make A2A delegation idempotent across retries
and resumes without extra bookkeeping. OpenCompany's **sub-agent permits** bound fan-out at
the infrastructure level rather than trusting an agent to self-limit.

### 4.11 Skills

**paperclip** uses `SKILL.md` files (`.agents/skills/*/SKILL.md`) with per-adapter runtime
resolution through shared helpers (`readPaperclipRuntimeSkillEntries()`,
`resolvePaperclipDesiredSkillNames()`, `readInstalledSkillTargets()`,
`buildRuntimeMountedSkillSnapshot()`), so each adapter's `skills.ts` is thin — e.g.
`packages/adapters/claude-local/src/server/skills.ts:21-46` resolves `~/.claude/skills` and
diffs desired against installed. Access is governed by
`server/src/services/company-skill-policy.ts`: a versioned policy document
(`{schemaVersion, revision, defaultEffect, rules[]}`) stored in `company_skill_policies`,
matching subjects (all agents / specific IDs / roles) against resources (skill IDs, keys,
source types, normalized source locators), with `decision()` returning
`{allowed, action, reason, policyRevision, matchedRuleId, remediation}` — a deny always
carries a remediation string. Absence of a policy row means open by design
(`OPEN_DEFAULT_POLICY`, `defaultEffect: "allow"`).

**OpenCompany** ships 77 built-in skills as markdown across 19 folders, with user files in
`.opencompany/skills/` overriding same-named built-ins.

**NVLabsCompany** has `services/skill_service.py`, `evolution/skill_evolution.py`, a Skills
page, and `skills-lock.json`. The policy layer — who may use which skill, versioned and
auditable — is the piece paperclip has that this project does not.

### 4.12 Provider and integration breadth

| Repo | LLM providers | Integrations |
|---|---|---|
OpenCompany | 13 providers, 12 model nodes, native SDK per provider (`server/services/llm/providers/`) | Google Workspace, Microsoft Graph, IMAP, WhatsApp (personal + Business Cloud), Telegram, Discord, Twitter/X, Android device pairing, Stripe, Vercel, Cloudflare, GCloud, GitHub, browser automation, Crawlee/Apify, 4 search backends |
| Clawith | `services/llm/` (9 files, 5,134 LOC) | Feishu, Slack, Discord, DingTalk, Atlassian, Google Workspace, SSO |
| PraisonAI | Provider routing with rate limiting and failover (`praisonaiagents/llm/`) | MCP client *and* server, with OAuth discovery/registration |
| MetaGPT | openai, anthropic, azure, bedrock, ollama, dashscope, qianfan, spark, zhipuai, gemini, ark, openrouter, human | — |
| paperclip | via 13 execution adapters, not direct SDKs | MCP tool gateway |
| **NVLabsCompany** | `models_router/providers/` — anthropic, openai, google, ollama (4) | `adapters/mcp_adapter.py`, GitHub repos, Slack events, Telegram bot, SSO/SCIM |

Provider breadth is the clearest quantitative gap: 4 versus 13. Provider adapters are also
the cheapest gap to close, since `models_router/provider_registry.py` already exists as the
extension point.

### 4.13 Credentials and secrets

**OpenCompany** is the strongest here and the easiest to copy. `server/core/encryption.py`
uses Fernet (AES-128-CBC + HMAC-SHA256) with keys derived via PBKDF2-HMAC-SHA256 at
`PBKDF2_ITERATIONS = 600_000` (`:71`, matching the OWASP 2024 recommendation), memoized at
`:30` so the KDF cost is paid once per credential per process. Credentials live in a
separate `credentials.db` behind a pluggable backend (`core/credential_backends.py`:
`fernet` / `keyring` / `aws`, selected by `CREDENTIAL_BACKEND` in `core/config.py:380`).
Its auth deliberately uses PyJWT rather than python-jose to avoid the `ecdsa` timing-attack
CVE (`server/services/user_auth.py`), signing HS256 at `:204` and verifying at `:228-234`,
with single-owner registration allowed only while no users exist (`:79`).

**NVLabsCompany** has `governance/secrets/vault.py` and `access.py`, plus `auth/` with
`api_keys.py`, `csrf.py`, `middleware.py`, `oidc.py`, `passwords.py` (pwdlib argon2),
`principal.py`, `sessions.py`, `users.py` — a broader auth surface than most references
(SSO/OIDC, SCIM, CSRF, API keys, sessions). But `FernetSecretBackend._store` being an
in-process dict means the vault does not persist.

---

## 5. What NVLabsCompany has that the references do not

This is a real list, not a courtesy one.

1. **Broadest auth surface of the set.** OIDC/SSO, SCIM provisioning, API keys, CSRF,
   sessions, argon2 passwords, RBAC. Only Clawith is comparable, and it lacks SCIM.
2. **3D/2D office simulation.** `Office.tsx` with Three.js, plus `office2d/`, `office3d/`,
   `officePixi/` component sets. No reference has a spatial UI.
3. **Meetings subsystem.** `meetings/conductor.py`, `scheduler.py`, `templates.py` with
   live huddles and action items. Absent everywhere else.
4. **Evolution subsystem.** `evolution/` — `failure_alchemy.py`, `agent_evolution.py`,
   `skill_evolution.py`, `proposer.py`, `promoter.py`, `evaluator.py`, `sandbox.py`. Only
   PraisonAI's roadmap gestures at self-improvement, and those classes are still stubs.
5. **Social/HR surfaces.** `PlazaFeed`, `HRRoom` (hiring, curricula, training),
   `company/performance.py`, `identity/persona.py`. Clawith has a Plaza and OKRs; nothing
   else has performance review or persona modeling.
6. **Memory graph visualization.** `MemoryGraph.tsx` — a visual memory canvas.
7. **Smart retry with failure diagnosis.** `orchestration/smart_retry.py` classifying error
   patterns into `REPORT_BLOCKER` / `DECOMPOSE` / `REASSIGN` / `RETRY`. paperclip has an
   equivalent in `recovery/service.ts` but far more code; PraisonAI's failure classifier is
   documented as still planned.
8. **Model cascade router with cost simulation.** `models_router/` plus the Budgets page
   simulator. OpenCompany has pricing; nobody has a cascade simulator.

---

## 6. Honest gap analysis

Findings are ordered by how much they threaten correctness, not by how much work they are.

### Tier 1 — correctness risks

**1. Three orchestration paths, two schedulers, no single authoritative state machine.**
`runtime/orchestrator.py`, `src/nexus/temporal/`, and `src/nexus/workflows/` each own a
version of "run work"; `runtime/scheduler.py` (DB-backed) and `src/nexus/triggers/`
(in-memory) each own "fire triggers". Every reference converges on exactly one, and Clawith
makes it constitutional law (C1) with a CI script enforcing it. Pick one path, delete or
demote the others to thin adapters over it.

**2. Governance state is in-process memory while named as persistent.**
`audit_persistent.py` is not persistent. `decision_queue.py` (approvals), `cost_alerting.py`
(budget alerts), `health.py`, and `secrets/secret_backend.py` all lose everything on
restart. For an audit log and an approval queue specifically, this is not a scaling concern
— it is a compliance and correctness one. The SHA-256 hash chain in `audit_persistent.py`
is genuinely good work that should be kept; it just needs a DB table underneath it, and
`enforce_retention()` needs to stop deleting from the chain it claims to verify.

**3. No sandbox abstraction for code execution.** If agents will run model-authored code,
Clawith's seven-backend `SandboxType` model is the pattern to copy — but copy the remote
backends (E2B, Judge0, self-hosted), not their privileged-container-with-Docker-socket
compose configuration.

**4. Default quality gate is near-meaningless.** `orchestration/critic.py` scoring
completeness as `len(result)/100` will pass almost any non-empty output. `llm_critic.py`
exists; make it the default and keep the heuristic as an explicit offline fallback.

### Tier 2 — capability gaps

**5. No vector store or embeddings.** BM25 over a caller-supplied list is a reasonable
floor (Clawith has no vectors either), but three references support four or more vector
backends. `memory/retriever.py` is the seam.

**6. Compaction is not budget-aware.** `memory/compaction.py` operates on a message list
with no resolution against real model capability. Clawith's
`session_context_compactor.py` — token budget from model capability minus system prompt,
tool schemas, and reserve; greedy batch fill; forced structured tool call; message-ID
watermark; loud failure on oversized input — is the pattern.

**7. Provider breadth: 4 versus 13.** Cheapest high-visibility gap. Extension point
already exists at `models_router/provider_registry.py`.

**8. No skill access policy.** paperclip's `company-skill-policy.ts` — versioned document,
subject/resource matching, decisions carrying remediation, open-by-default when absent — is
directly portable to `services/skill_service.py`.

**9. No pre-flight budget estimation.** `budget_enforcer.py` checks after the fact.
PraisonAI's pre-call guard (`chat_mixin.py:1808-1824`) estimates minimum cost and refuses
to dispatch, preventing overspend rather than reporting it.

**10. No delegation permits or idempotent A2A correlation.** OpenCompany's
`acquire_subagent_permit` bounds fan-out infrastructurally; Clawith's UUIDv5 correlation
IDs from source-run + tool-call make delegation retry-safe. Both are small additions to
`communication/a2a.py` and `company/delegation.py`.

### Tier 3 — maturity gaps

**11. Test and migration depth.** 123 test files and 13 migrations, against Clawith's 197
and 70, paperclip's 1,414, PraisonAI's 1,529. paperclip's approach is instructive: one test
file per behavior (40+ `heartbeat-*.test.ts`, each isolating one edge case) plus captured
real-incident fixtures such as `watchdog-confirmation-incident-8bef17ef.json`.

**12. Dashboard is mock-first.** `dashboard/server.ts` (5,418 lines) answers most
`/api/v1/*` routes from in-memory arrays by default, proxying only `/api/v1/auth/*` to the
real backend; full proxying requires `PROXY_API=true`. That is a legitimate dev-tooling
choice, but it means UI completeness is not evidence of backend completeness, and the two
can drift silently. `api/client.ts`'s `unwrapItems<T>()` exists specifically to paper over
a shape difference between mock (`{items: []}`) and real backend (bare array) — a small
signal of that drift. Worth adding a CI run of the e2e suite against `PROXY_API=true` so
divergence fails loudly.

**13. Thin API client layer.** Only three modules in `dashboard/src/api/` (`client.ts`,
`auth.ts`, `agents.ts`) for ~28 pages, so most pages call `apiClient` inline. Fine at this
size; it will resist typed-contract enforcement later.

**14. Dead code.** `NodeLibrary.tsx` has no route in `App.tsx` — apparently superseded by
the Pipelines node palette.

**15. No architecture invariant enforcement.** Clawith's `scripts/arch-guard.sh` and AI
Team OS's `check_invariants.sh` (14 machine checks) both make architectural rules
executable. Given the duplicate-orchestrator situation, a guard script that fails CI on new
parallel state machines would pay for itself.

---

## 7. Recommended borrowings, ranked

| # | Borrow | From | Target in this repo |
|---|---|---|---|
| 1 | Single authoritative execution state machine + arch-guard script | Clawith (C1, `scripts/arch-guard.sh`) | collapse `runtime/` + `workflows/` + `temporal/` |
| 2 | DB-backed append-only audit under the existing hash chain | paperclip, Clawith | `governance/audit_persistent.py` |
| 3 | Budget-aware incremental compactor with watermark | Clawith `session_context_compactor.py` | `memory/compaction.py` |
| 4 | Multi-backend sandbox (remote-first) | Clawith `sandbox/config.py` — *not* its compose file | `evolution/sandbox.py` |
| 5 | Pre-flight budget estimation | PraisonAI `chat_mixin.py:1808-1824` | `governance/budget_enforcer.py` |
| 6 | Non-idempotent-activity retry policy | OpenCompany `_retry_policies.py:93` | `temporal/activities.py` |
| 7 | Versioned skill access policy | paperclip `company-skill-policy.ts` | `services/skill_service.py` |
| 8 | Sub-agent permits + UUIDv5 A2A correlation | OpenCompany, Clawith | `communication/a2a.py`, `company/delegation.py` |
| 9 | Credential encryption params + separate store | OpenCompany `core/encryption.py` (PBKDF2 600k) | `governance/secrets/vault.py` |
| 10 | Explicit completion-reason taxonomy | PraisonAI `agent/autonomy.py:372` | `runtime/orchestrator.py` |
| 11 | Plugin-first node registration via `__init_subclass__` | OpenCompany `server/nodes/` | `src/nexus/nodes/` |
| 12 | One test file per behavior + incident fixtures | paperclip `server/src/__tests__/` | `tests/` |

---

## 8. Bottom line

NVLabsCompany is the broadest project in the comparison set by feature surface and the
smallest by backend code. It reaches into three archetypes at once — control plane, node
canvas, and multi-tenant platform — and adds surfaces (3D office, meetings, evolution,
HR/persona, memory graph) that no reference attempts. The auth surface is genuinely ahead
of the field, and several designs are sound: the smart-retry escalation taxonomy, the
model-cascade router, the three-temperature memory tiers, the audit hash chain, and a
Temporal foundation that is correctly shaped.

The gap is not features. It is that the breadth is currently supported by scaffolding in
places where the references have load-bearing storage — an audit log and approval queue in
process memory, a secrets vault that does not persist, three orchestration paths and two
schedulers with different durability stories, and a dashboard whose default backend is
mocked. Every one of those is a known, bounded piece of work rather than a redesign, and
the modules that are already DB- or Redis-backed (`persistent_kill_switch`,
`persistent_circuit_breaker`, `redis_rate_limiter`, `leader_election`,
`runtime/checkpoint`) show the project already knows the right shape.

The single highest-leverage change is #1: collapse to one execution path and make that
rule executable in CI. Clawith treats this as a constitutional law for good reason — a
second state machine is the defect that generates all the others.

---

## Appendix — querying the reference graphs

```bash
# Per-repo graphs, independently queryable
cd temp_repos/paperclip   && graphify query "budget hard stop enforcement"
cd temp_repos/Clawith     && graphify query "trigger evaluation dispatch"
cd temp_repos/OpenCompany && graphify query "node plugin registration"
cd temp_repos/PraisonAI   && graphify query "autonomous loop completion reasons"
cd temp_repos/MetaGPT     && graphify query "role think act react"
cd temp_repos/AI-company  && graphify query "task wall watchdog"

# Name a community to get GRAPH_REPORT.md for any of them
graphify cluster-only temp_repos/<repo>
```
