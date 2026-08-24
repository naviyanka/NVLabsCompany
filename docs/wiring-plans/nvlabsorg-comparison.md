# NvLabsOrg vs NVLabsCompany — Feature Comparison & Ground-Truth Implementation Audit

## Source: [github.com/naviyanka/NvLabsOrg](https://github.com/naviyanka/NvLabsOrg)

---

## 1. Executive Summary & Ground-Truth Verification

This document provides a verified, code-level audit of **NvLabsOrg** capabilities compared to **NVLabsCompany**. It distinguishes features that work **end-to-end in production** from backend modules that are implemented as standalone code but remain **un-wired or stubbed**.

```
  [████████████████████] 100% — Web UI Dashboard (25/25 Pages Wired)
  [████████████████████] 100% — Agent CRUD & Multi-mode Hiring (4 Modes)
  [████████████████████] 100% — Real LLM Chat & Instruction File Generation
  [████████████████████] 100% — Slash Commands & Markdown Chat Export
  [████████████████████] 100% — SSE Real-time Word-by-Word Chat Streaming
  [██████████████░░░░░░]  70% — Python FastAPI Endpoints (44 Routers)
  [██████████░░░░░░░░░░]  50% — Autonomous Orchestration (Modules Implemented, Un-wired to API)
```

---

## 2. Updated Ground-Truth Status Breakdown

### A. Items Corrected by Code Audit (Status Updates)

| Feature | Document Status | Actual Ground-Truth Code Status | Evidence / Location |
|---|---|---|---|
| **Slash commands** | ❌ *Not implemented* | ✅ **Working** | `AgentChatDrawer.tsx` supports `/clear`, `/export`, `/status`, `/model`, `/help`. |
| **Chat Export (Markdown)** | ❌ *Not implemented* | ✅ **Working** | `/export` generates a formatted `.md` transcript with metadata and triggers browser download. |
| **Streaming Chat (SSE)** | ⚠️ *Partial* | ✅ **Working SSE** | `POST /chat/stream` serves real SSE with word-by-word streaming. Frontend consumes via `ReadableStream`. |
| **Instruction File Injection** | 🔲 *Not implemented* | ✅ **Working** | Auto-generates `.claude/CLAUDE.md`, `.kiro/steering/default.md`, and `AGENTS.md` upon agent task execution. |
| **Pipeline Execution Engine** | ⚠️ *Backend exists* | ⚠️ **CRUD Shell** | Route creates `PipelineRun` DB record; stage-by-stage runner execution requires background worker glue. |
| **Team-based Delivery & Router** | ⚠️ *Backend exists* | ⚠️ **Un-wired Module** | `AgentRouter`, `TaskPlanner`, `ParallelExecutor` exist in `src/nexus/orchestration/` but are un-wired in API routes. |
| **Worktree Isolation per Agent** | ⚠️ *Backend exists* | ⚠️ **Un-wired Module** | `WorktreeManager` in `src/nexus/runtime/worktree.py` has git subprocess logic, un-wired to task dispatch. |
| **Memory in Chat Context** | ⚠️ *Partial* | ⚠️ **Un-wired to Chat** | Standalone memory CRUD & BM25 search work via API; `build_working_context()` is not yet called inside `chat.py`. |
| **Cost Estimator per Session** | ⚠️ *Partial* | ⚠️ **Static Model** | Budget model stores monthly caps; real-time per-session cost calculation returns static/stub data. |
| **Knowledge Base with RAG** | Listed as advantage | ⚠️ **SQL Search Only** | KB CRUD works; search uses SQL `ILIKE` content matching. Vector RAG pipeline in `rag.py` is un-wired. |
| **Agent Evolution** | Listed as advantage | ⚠️ **CRUD Shell** | Routes create proposal records with static scores (`0.8`/`0.7`); `FailureAnalyzer` & `LLMEvolutionAdvisor` are un-wired. |

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
  • Agent Chat → Soul prompt generator → LLM adapter / CLI subprocess → response
  • SSE Real-time word-by-word streaming to AgentChatDrawer
  • Slash commands (/clear, /export, /status, /model, /help)
  • Markdown transcript export with session metadata headers
  • Agent lifecycle (wake, pause, delete, heartbeat)
  • Memory CRUD + BM25 keyword search API
  • Archetype & team template browsing
  • Governance kill switch enforcement
  • Audit logging for mutating HTTP requests

🟡 Implemented Subsystems (Awaiting API Engine Wiring):
  • Pipeline execution runner (needs background worker glue)
  • Multi-agent orchestration (AgentRouter, TaskPlanner, ParallelExecutor exist in src/nexus/orchestration/)
  • Worktree isolation (WorktreeManager git subprocess exists in src/nexus/runtime/worktree.py)
  • Memory-augmented chat context (build_working_context exists in persona.py, un-wired to chat.py)
  • Vector RAG search engine (rag.py pipeline un-wired to search endpoints)
```

---

## 5. Summary & Action Plan

- **Working Foundation**: NVLabsCompany has a superior backend architecture, production DB schemas, deep soul prompt engine, 20 archetypes, hire manifests, governance kill switches, and 19 disk persistence stores.
- **Next Engineering Target**: Connect the standalone Python orchestration modules (`AgentRouter`, `TaskPlanner`, `WorktreeManager`, `build_working_context`) into the live API execution paths.

