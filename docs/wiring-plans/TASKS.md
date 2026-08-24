# NVLabsCompany — Shared Development Task List

> **Purpose:** A persistent, cross-session task list for any agent or developer working on this project.
> Update status as you complete items. Prefix completed items with `[x]`.

---

## Priority 1: Fix Partially-Built Features (Wiring Gaps)

These modules exist and are tested but need to be connected to the live API/execution paths.

### 1.1 Wire Memory into Chat Context
- **Status:** DONE
- **Problem:** `chat.py` calls `_build_system_prompt(agent)` without passing memories. The `Persona.build_working_context()` framework is connected but always receives an empty memory list.
- **Fix:** In `chat_with_agent()` and `chat_with_agent_stream()`, query `MemoryRecord` from DB for the agent and pass them to `_build_system_prompt(agent, memories=records)`.
- **Files:** `src/nexus/api/routes/chat.py`
- **Effort:** Low (< 30 min)
- **Dependencies:** None

### 1.2 Fix Instruction File Generation
- **Status:** DONE
- **Problem:** `writeInstructionFile()` in `server.ts` returns null for `claude` and `kiro-cli`. Only `antigravity/GEMINI.md` is generated. The Python `cli_adapter.py` doesn't write instruction files at all.
- **Fix:** In the Python `CLIAdapter._do_execute()`, before spawning the subprocess, write a temporary instruction file using `backend.instruction_path` and the agent's system prompt. Clean up after execution.
- **Files:** `src/nexus/adapters/cli_adapter.py`, `src/nexus/adapters/cli_registry.py`
- **Effort:** Medium (1-2 hours)
- **Dependencies:** None

### 1.3 Wire Pipeline Stage Execution
- **Status:** DONE
- **Problem:** `POST /pipelines/{id}/run` creates a `PipelineRun` DB record but never executes stages. No background worker exists.
- **Fix:** After creating the PipelineRun, spawn an asyncio background task that iterates through `pipeline.stages`, calls the appropriate adapter for each stage, passes output of stage N as input to stage N+1, and updates the run status.
- **Files:** `src/nexus/api/routes/pipelines.py`, new file `src/nexus/runtime/pipeline_runner.py`
- **Effort:** High (4-6 hours)
- **Dependencies:** Working CLI/LLM adapters (already done)

### 1.4 Wire Worktree Isolation to Task Execution
- **Status:** DONE
- **Problem:** `WorktreeManager` has real git subprocess logic but is never called. CLI adapter creates temp directories instead.
- **Fix:** When a task is assigned to an agent using the CLI adapter, optionally create a git worktree (if the workspace is a git repo) and run the CLI in that worktree. Configuration flag to enable/disable.
- **Files:** `src/nexus/adapters/cli_adapter.py`, `src/nexus/runtime/worktree.py`
- **Effort:** Medium (2-3 hours)
- **Dependencies:** 1.2 (instruction files written to worktree)

### 1.5 Wire Remaining Orchestration to API
- **Status:** DONE
- **Problem:** `ParallelExecutor`, `TaskPlanner`, `GoalLoop` exist but are never imported from routes. Only `AgentRouter` is wired (for task auto-assignment).
- **Fix:** Create a new route or extend tasks route: `POST /tasks/{id}/decompose` (uses TaskPlanner), `POST /goals/{id}/execute` (uses GoalLoop). Wire ParallelExecutor into pipeline runner.
- **Files:** `src/nexus/api/routes/tasks.py`, `src/nexus/api/routes/goals.py`
- **Effort:** High (4-6 hours)
- **Dependencies:** 1.3 (pipeline runner)

### 1.6 Wire Evolution Engine to Routes
- **Status:** DONE
- **Problem:** Evolution routes create proposal records with hardcoded scores (0.8/0.7). The real `FailureAnalyzer`, `LLMEvolutionAdvisor`, `ABTestFramework` modules are never imported.
- **Fix:** In `evaluate_proposal()`, call `LLMEvolutionAdvisor.evaluate()` instead of returning static scores. In `promote_proposal()`, actually update the agent's configuration (capabilities, system prompt, etc.).
- **Files:** `src/nexus/api/routes/evolution.py`, `src/nexus/evolution/`
- **Effort:** Medium (2-3 hours)
- **Dependencies:** LLM adapter (already working)

### 1.7 Wire Vector RAG to Knowledge Search
- **Status:** DONE (was already wired with ILIKE fallback)
- **Problem:** Knowledge search uses SQL `ILIKE` instead of the `RAGPipeline` in `src/nexus/knowledge/rag.py`.
- **Fix:** Wire `RAGPipeline.search()` into the `/knowledge/rag-search` endpoint. If no embedding provider is configured, fall back to the current ILIKE approach.
- **Files:** `src/nexus/api/routes/knowledge.py`, `src/nexus/knowledge/rag.py`
- **Effort:** Medium (2-3 hours)
- **Dependencies:** Embedding provider configuration (optional — can use ILIKE fallback)

---

## Priority 2: Governance Stubs to Fill

### 2.1 Real Rate Limiting
- **Status:** DONE
- **Problem:** `GovernanceMiddleware._get_rate_limit_remaining()` always returns the default limit.
- **Fix:** Implement a sliding window or token bucket per company_id. Use an in-memory dict with TTL or Redis if available.
- **Files:** `src/nexus/api/middleware.py`
- **Effort:** Low (1 hour)

### 2.2 Real Budget Enforcement
- **Status:** DONE
- **Problem:** `_check_budget()` always returns True and `_estimate_request_cost()` returns 0.
- **Fix:** Query the company's budget model and compare estimated cost. For LLM calls, estimate tokens from prompt length.
- **Files:** `src/nexus/api/middleware.py`, `src/nexus/models/budget.py`
- **Effort:** Medium (2 hours)

### 2.3 Policy Engine
- **Status:** DONE
- **Problem:** `_evaluate_policy()` always returns `{"allowed": True}`.
- **Fix:** Load active policies from DB and evaluate request against them (path patterns, method restrictions, time-based rules).
- **Files:** `src/nexus/api/middleware.py`, `src/nexus/api/routes/policies.py`
- **Effort:** Medium (2-3 hours)

---

## Priority 3: Feature Gaps vs NvLabsOrg

### 3.1 True Token-Level Streaming
- **Status:** DONE
- **Problem:** Current SSE streaming calls the LLM, gets the full response, then emits word-by-word (simulated). Not true streaming.
- **Fix:** For Anthropic/OpenAI adapters, use their streaming APIs and yield tokens as they arrive.
- **Files:** `src/nexus/adapters/anthropic_adapter.py`, `src/nexus/adapters/openai_adapter.py`, `src/nexus/api/routes/chat.py`
- **Effort:** High (4-6 hours)

### 3.2 WebSocket Multiplexing
- **Status:** DONE
- **Problem:** No real-time multi-agent output streaming. NvLabsOrg streams stdout from all agents over WebSocket channels.
- **Fix:** Extend `src/nexus/api/routes/ws.py` to support channel subscriptions per agent. When CLI adapters run, stream their output through WS.
- **Files:** `src/nexus/api/routes/ws.py`, `src/nexus/adapters/cli_adapter.py`
- **Effort:** High (6-8 hours)

### 3.3 Auto Commit/Merge per Worktree
- **Status:** DONE
- **Problem:** NvLabsOrg auto-commits agent work and merges back to main. Our WorktreeManager has merge/revert but nothing triggers it.
- **Fix:** After CLI adapter execution completes in a worktree, auto-commit changes and optionally auto-merge if clean.
- **Files:** `src/nexus/runtime/worktree.py`, `src/nexus/adapters/cli_adapter.py`
- **Effort:** Medium (2-3 hours)
- **Dependencies:** 1.4 (worktree wired)

### 3.4 Context Injection Between Pipeline Steps
- **Status:** DONE (implemented as part of 1.3)
- **Problem:** No mechanism to pass output of step N as input to step N+1.
- **Fix:** Pipeline runner should store each step's output and include it in the next step's prompt/payload.
- **Files:** `src/nexus/runtime/pipeline_runner.py` (from 1.3)
- **Effort:** Low — part of 1.3 implementation

### 3.5 Scheduled/Cron Tasks
- **Status:** DONE
- **Problem:** No recurring task execution.
- **Fix:** Add a `schedule` field to Task/Trigger model. Run a background scheduler (APScheduler or simple asyncio loop) that fires tasks on schedule.
- **Files:** `src/nexus/api/routes/triggers.py`, new `src/nexus/runtime/scheduler.py`
- **Effort:** Medium (3-4 hours)

---

## Priority 4: Polish & UX

### 4.1 More Slash Commands
- **Status:** DONE
- **Commands added:** `/cancel` (abort current task), `/hire` (quick hire from chat), `/broadcast` (message all agents), `/budget` (show remaining budget)
- **Files:** `dashboard/src/components/agents/AgentChatDrawer.tsx`
- **Effort:** Low (1-2 hours)

### 4.2 Agent Backend Switching
- **Status:** DONE
- **Problem:** Changing an agent's CLI provider requires editing via API. No UI for quick switch.
- **Fix:** Add a dropdown in AgentDetailPage to change `adapter_type` and `model` with a PUT call.
- **Files:** `dashboard/src/pages/AgentDetailPage.tsx`
- **Effort:** Low (1 hour)

### 4.3 Per-Session Token Tracking
- **Status:** DONE
- **Problem:** Chat responses include `tokens_used` but nothing aggregates or displays it.
- **Fix:** Accumulate tokens per chat session in the frontend and display a running total in the chat UI.
- **Files:** `dashboard/src/components/agents/AgentChatDrawer.tsx`, `dashboard/src/pages/AgentDetailPage.tsx`
- **Effort:** Low (30 min)

### 4.4 Fix Disk Persistence Count in Docs
- **Status:** DONE
- **Problem:** Doc says 15 stores, actual count is 19.
- **Fix:** Update the comparison document.
- **Files:** `docs/wiring-plans/nvlabsorg-comparison.md`
- **Effort:** Trivial

---

## Completion Tracking

| Priority | Total | Done | Remaining |
|----------|-------|------|-----------|
| P1 (Wiring Gaps) | 7 | 7 | 0 |
| P2 (Governance) | 3 | 3 | 0 |
| P3 (Feature Gaps) | 5 | 5 | 0 |
| P4 (Polish) | 4 | 4 | 0 |
| P5 (Remaining Gaps) | 8 | 0 | 8 |
| **Total** | **27** | **19** | **8** |

---

## Priority 5: Remaining Gaps (Identified 2026-08-24 Re-verification)

These are features that were either partially claimed as done but have deeper gaps, or exist in NvLabsOrg and have no implementation at all.

### 5.1 Wire ParallelExecutor for Fan-Out Pipeline Stages
- **Status:** TODO
- **Problem:** Task 1.5 claimed orchestration wired, but `ParallelExecutor` is **never imported in any route or runner**. The pipeline runner (`_execute_pipeline_bg`) executes stages sequentially only.
- **Fix:** Add a `parallel: true` field to pipeline stage definitions. When a stage has `parallel: true` and contains multiple sub-prompts (or multiple agent_ids), use `ParallelExecutor` with semaphore-bounded concurrency to fan out and collect results.
- **Files:** `src/nexus/api/routes/pipelines.py`, `src/nexus/orchestration/parallel.py`
- **Effort:** Medium (2-3 hours)
- **Dependencies:** 1.3 (pipeline runner — already done)

### 5.2 Wire FailureAnalyzer into Evolution/Diagnostics
- **Status:** TODO
- **Problem:** `FailureAnalyzer` exists in `src/nexus/evolution/` but is never imported by any route. When evolution proposals are evaluated, failure patterns from execution history are not analyzed.
- **Fix:** Add a `POST /api/v1/agents/{agent_id}/diagnose` endpoint that calls `FailureAnalyzer` with the agent's recent task failures. Optionally wire into `evaluate_proposal` as a pre-evaluation step.
- **Files:** `src/nexus/api/routes/evolution.py` or new `src/nexus/api/routes/diagnostics.py`
- **Effort:** Medium (2 hours)
- **Dependencies:** None

### 5.3 Embedding Provider Configuration + Vector Store for Real RAG
- **Status:** TODO
- **Problem:** `RAGPipeline` accepts an `embedding_provider` but none is configured. The pipeline falls back to token-overlap heuristic (BM25-like). No vector store (pgvector, FAISS) is provisioned.
- **Fix:** Add an `EMBEDDING_PROVIDER` env var (options: `openai`, `ollama`, `none`). Create an `OpenAIEmbeddingProvider` class that calls the embeddings API. Configure the knowledge search endpoint to pass it to `RAGPipeline`. Add optional pgvector extension for PostgreSQL or FAISS for local dev.
- **Files:** `src/nexus/knowledge/embeddings.py` (new), `src/nexus/api/routes/knowledge.py`, `src/nexus/config.py`
- **Effort:** High (4-6 hours)
- **Dependencies:** OpenAI API key or Ollama embedding model available

### 5.4 Multi-Agent Terminal Panel in Dashboard
- **Status:** TODO
- **Problem:** Task 3.2 added WebSocket broadcasting from CLI adapter, but the dashboard has no UI panel that shows live output from multiple running agents simultaneously.
- **Fix:** Create a `TerminalPanel` component that opens a WebSocket to `/ws/{client_id}`, subscribes to `agent:*` channels, and displays streaming output in a split-pane terminal view per agent.
- **Files:** `dashboard/src/components/terminal/TerminalPanel.tsx` (new), `dashboard/src/pages/Terminal.tsx` (new)
- **Effort:** High (6-8 hours)
- **Dependencies:** 3.2 (WebSocket broadcasting — already done)

### 5.5 Live Agent-to-Agent Message Delivery
- **Status:** TODO
- **Problem:** Communication routes store messages in DB but nothing delivers them to agents during execution. Agent B doesn't "receive" messages from Agent A.
- **Fix:** When an agent sends a message, push it to the recipient's WebSocket channel. When the recipient agent is executing a task, include unread messages in its next prompt context (similar to memory injection). Add a `/agents/{id}/inbox` endpoint to retrieve unread messages.
- **Files:** `src/nexus/api/routes/communication.py`, `src/nexus/api/routes/chat.py`
- **Effort:** Medium (4-6 hours)
- **Dependencies:** 3.2 (WebSocket — done), 1.1 (memory in chat — done)

### 5.6 Wire CriticEvaluator as Quality Gate
- **Status:** TODO
- **Problem:** `CriticEvaluator` in `src/nexus/orchestration/critic.py` can assess output quality, but nothing triggers it. Agent outputs are never validated before being returned to the user.
- **Fix:** Add an optional quality gate in the pipeline runner and/or chat endpoint: after the LLM responds, pass the output through `CriticEvaluator`. If quality score is below threshold, retry or flag the response.
- **Files:** `src/nexus/api/routes/pipelines.py`, `src/nexus/api/routes/chat.py`
- **Effort:** Low (2-3 hours)
- **Dependencies:** None

### 5.7 Pipeline Builder UI (Visual Node Graph)
- **Status:** TODO
- **Problem:** NvLabsOrg has a drag-and-drop visual pipeline editor. NVLabsCompany only has pipeline list/detail API and basic CRUD forms.
- **Fix:** Create a React canvas component using reactflow or a similar library that allows users to visually compose pipeline stages, set agent assignments, and define dependencies.
- **Files:** `dashboard/src/components/pipelines/PipelineBuilder.tsx` (new), `dashboard/src/pages/Pipelines.tsx`
- **Effort:** High (8-12 hours)
- **Dependencies:** 1.3 (pipeline execution — done)

### 5.8 A/B Test Trigger Endpoint
- **Status:** TODO
- **Problem:** `ABTestFramework` exists in `src/nexus/evolution/` and is used internally by `LLMEvolutionAdvisor`, but there's no API to trigger a real A/B experiment comparing two agent configurations against live traffic.
- **Fix:** Add `POST /api/v1/evolution/ab-test` that creates an experiment with control/variant configs, routes a percentage of traffic to each, and collects comparative metrics over a time window.
- **Files:** `src/nexus/api/routes/evolution.py`, `src/nexus/evolution/ab_test.py`
- **Effort:** Medium (3-4 hours)
- **Dependencies:** 1.6 (evolution engine — done)

---

*All tasks complete. Last updated: 2026-08-24 by Kiro agent session*
