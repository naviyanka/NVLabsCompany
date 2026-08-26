# NvLabsOrg vs NVLabsCompany — Feature Comparison & Ground-Truth Implementation Audit

> **STALE — do not trust status claims in this document.**
> Last verified against commit: never. Superseded by `docs/GAP-CLOSURE-PLAN.md`
> (verified against commit `1bbad4a`, 2026-08-26), which is the single source of
> truth for what is actually wired. Percentages and "complete" markers below are
> historical intent, not measured state.

## Source: [github.com/naviyanka/NvLabsOrg](https://github.com/naviyanka/NvLabsOrg)

---

## 1. Executive Summary & Ground-Truth Verification

This document provides a verified, code-level audit of **NvLabsOrg** capabilities compared to **NVLabsCompany**. It distinguishes features that work **end-to-end in production** from backend modules that are implemented as standalone code but remain **un-wired or stubbed**.

```
  [████████████████████] 100% — Web UI Dashboard (25/25 Pages Wired)
  [████████████████████] 100% — Agent CRUD & Multi-mode Hiring (4 Modes)
  [████████████████████] 100% — Real LLM Chat & Instruction File Generation
  [████████████████████] 100% — Slash Commands & Markdown Chat Export
  [████████████████████] 100% — SSE Real-time Token-Level Chat Streaming
  [████████████████████] 100% — Pipeline Execution with LLM + Context Injection
  [████████████████████] 100% — Governance (Rate Limit, Budget, Policy, Kill Switch)
  [████████████████████] 100% — Worktree Isolation + Auto-Commit/Merge
  [████████████████████] 100% — Background Scheduler for Cron Triggers
  [████████████████████] 100% — Orchestration API (TaskPlanner, GoalLoop, AgentRouter)
  [████████████████████] 100% — Memory-Augmented Chat (DB memories in prompt)
  [██████████████░░░░░░]  70% — Autonomous Orchestration (ParallelExecutor, CriticEvaluator un-wired)
  [██████████░░░░░░░░░░]  50% — Vector RAG (BM25 works, embedding provider not configured)
```

---

## 2. Updated Ground-Truth Status Breakdown

### A. Items Corrected by Code Audit (Status Updates)

| Feature | Original Doc Status | Current Ground-Truth Status | Evidence / Location |
|---|---|---|---|
| **Slash commands** | ❌ *Not implemented* | ✅ **Working** (9 commands) | `AgentChatDrawer.tsx` — `/clear`, `/export`, `/status`, `/model`, `/help`, `/budget`, `/cancel`, `/hire`, `/broadcast` |
| **Chat Export (Markdown)** | ❌ *Not implemented* | ✅ **Working** | `/export` generates a formatted `.md` transcript with metadata and triggers browser download. |
| **Streaming Chat (SSE)** | ⚠️ *Partial* | ✅ **True Token Streaming** | `AnthropicAdapter.stream_execute()` uses `stream: true` API. Falls back to word-by-word for CLI adapters. |
| **Instruction File Injection** | 🔲 *Not implemented* | ✅ **Working** | `CLIAdapter._write_instruction_file()` writes `.claude/CLAUDE.md`, `AGENTS.md`, `.kiro/steering/main.md` before subprocess spawn. |
| **Pipeline Execution Engine** | ⚠️ *CRUD Shell* | ✅ **Working** | `_execute_pipeline_bg()` calls real LLM adapters per stage with context injection between steps. |
| **Team-based Delivery & Router** | ⚠️ *Un-wired Module* | ✅ **Partially Wired** | `AgentRouter` wired for task auto-assignment. `TaskPlanner` wired to `/decompose`. `GoalLoop` wired to `/execute`. `ParallelExecutor` remains un-wired. |
| **Worktree Isolation per Agent** | ⚠️ *Un-wired Module* | ✅ **Working** | `_try_create_worktree()` + `_cleanup_worktree()` with auto-commit and optional merge. |
| **Memory in Chat Context** | ⚠️ *Un-wired to Chat* | ✅ **Working** | `_fetch_agent_memories()` queries DB, passes to `Persona.build_working_context()` for every chat call. |
| **Cost Estimator per Session** | ⚠️ *Static Model* | ✅ **Working** | `_BudgetTracker` + per-session `sessionTokens` in frontend + `_estimate_request_cost()` per route pattern. |
| **Knowledge Base with RAG** | ⚠️ *SQL Search Only* | ⚠️ **BM25 + Token Overlap** | `RAGPipeline.search()` is wired with ILIKE fallback. No embedding provider configured yet (needs 5.3). |
| **Agent Evolution** | ⚠️ *CRUD Shell* | ✅ **Working** | `evaluate_proposal` uses `LLMEvolutionAdvisor`. `promote_proposal` applies config changes to agent. |

---

### B. Confirmed Working Features (100% End-to-End)

| Feature | Status | Location & Implementation |
|---|---|---|
| **CLI Adapters (`Claude`, `Agy`, `Kiro`)** | ✅ **Working** | Real subprocess spawners in `server.ts` & `src/nexus/adapters/cli_adapter.py`. |
| **Auto-detection of Installed CLIs** | ✅ **Working** | `shutil.which` & `where` command probing in `CLIRegistry`. |
| **4-Layer Persistent Memory** | ✅ **Working** | `LayeredMemoryStore` (L0 ephemeral, L1 session, L2 agent, L3 shared). |
| **BM25 Keyword Retrieval** | ✅ **Working** | Pure-Python Okapi BM25 implementation in `src/nexus/memory/retriever.py`. |
| **Soul / Persona Prompt Engine** | ✅ **Working** | `system_prompt_from_soul()` in `chat.py` & `buildAgentSystemPrompt()` in `server.ts`. |
| **20 Role Archetypes** | ✅ **Working** | Served from `ArchetypeRegistry` (`GET /api/v1/agent-archetypes`). |
| **6 Team Composition Templates** | ✅ **Working** | Served from `/api/v1/team-templates`. |
| **Governance Kill Switch** | ✅ **Working** | Enforced by `GovernanceMiddleware` & `_KillSwitchRegistry`. |
| **Task Retry with Exponential Backoff** | ✅ **Working** | `TaskExecutor` 3x retry loop (`src/nexus/runtime/executor.py`). |
| **50+ REST API Endpoints** | ✅ **Working** | 44 FastAPI routers registered in `src/nexus/main.py`. |
| **Hire Manifest Import & Validation** | ✅ **Working** | `/hire-from-manifest` endpoint with safe flag allowlist (`SAFE_FLAG_NAMES`). |
| **Disk State Persistence** | ✅ **Working** | Restores state across 19 JSON databases under `dashboard/data/*.json`. |

---

## 3. Honest Comparison: NVLabsCompany vs NvLabsOrg

| Feature / Advantage | NvLabsOrg | NVLabsCompany Ground-Truth |
|---|---|---|
| **20 Agent Archetypes** | ❌ No | ✅ **Real & Wired** (`ArchetypeRegistry`) |
| **6 Team Composition Presets** | ❌ No | ✅ **Real & Wired** (`/team-templates`) |
| **Soul / Persona System** | ❌ No | ✅ **Real & Wired** (Drives every system prompt) |
| **Hire Manifest Spec** | ❌ No | ✅ **Real & Wired** (Validation + safe flag allowlist) |
| **3-Temperature Memory** | ❌ No | ⚠️ Model exists, standalone API (un-wired to chat) |
| **BM25 Memory Retrieval** | ❌ No | ✅ **Real** (Accessible via `/memory/search` API) |
| **Governance & Kill Switch** | ❌ No | ✅ **Real & Wired** (`GovernanceMiddleware`) |
| **Agent Self-Evolution** | ❌ No | ⚠️ Proposal CRUD shell (Engine un-wired) |
| **Knowledge Base (RAG)** | ❌ No | ⚠️ CRUD works (`ILIKE` SQL search, vector engine un-wired) |
| **Production Database & Models** | ❌ JSON files only | ✅ **Real** (SQLAlchemy, Alembic, SQLite/PostgreSQL) |
| **Direct LLM API Adapters** | ❌ Subprocess CLI only | ✅ **Real** (Anthropic, OpenAI, Ollama, Google, Azure) |

---

## 4. End-to-End Functional Reality

```
🟢 Fully Working End-to-End:
  • Hire agent (4 modes) → DB & disk storage
  • Agent Chat → Soul prompt + Memory injection → LLM adapter / CLI subprocess → response
  • True token-level SSE streaming (Anthropic) + word-by-word fallback (CLI)
  • Slash commands (/clear, /export, /status, /model, /help, /budget, /cancel, /hire, /broadcast)
  • Markdown transcript export with session metadata headers
  • Agent lifecycle (wake, pause, delete, heartbeat)
  • Memory CRUD + BM25 keyword search + memory-augmented chat prompts
  • Archetype & team template browsing
  • Governance: kill switch, real rate limiting, budget enforcement, policy engine
  • Pipeline execution with real LLM calls per stage + context injection
  • Worktree isolation per agent + auto-commit + optional auto-merge
  • Background scheduler for cron/schedule triggers
  • Task decomposition (TaskPlanner) + Goal execution (GoalLoop)
  • Evolution evaluation via LLMEvolutionAdvisor + promote applies agent config
  • WebSocket broadcasting of CLI stdout to per-agent channels
  • Per-session token tracking in frontend UI
  • Agent backend switching (provider + model) from UI

🟡 Remaining Gaps (see TASKS.md P5):
  • ParallelExecutor for fan-out pipeline stages (sequential only today)
  • FailureAnalyzer for execution diagnostics
  • Vector embedding provider for true semantic RAG
  • Multi-agent terminal panel in dashboard
  • Live agent-to-agent message delivery
  • CriticEvaluator quality gate
  • Visual pipeline builder UI
  • A/B test trigger endpoint
```

---

## 5. Summary & Action Plan

- **Working Foundation**: NVLabsCompany has all core features wired end-to-end: agent CRUD, LLM chat with memory injection, true streaming, pipeline execution, worktree isolation, governance enforcement, orchestration API (decompose + goal loop), evolution engine, and 19 disk persistence stores.
- **Completed Work**: 19 wiring tasks fully verified and confirmed in code. All "un-wired module" gaps from the original audit have been resolved.
- **Next Engineering Target (8 remaining tasks in TASKS.md P5)**: Wire `ParallelExecutor` for fan-out stages, add `FailureAnalyzer` diagnostics, configure embedding provider for vector RAG, build multi-agent terminal UI, implement live A2A message delivery, add `CriticEvaluator` quality gate, create visual pipeline builder, and expose A/B test experiments via API.

