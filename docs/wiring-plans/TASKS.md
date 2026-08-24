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
| P5 (Remaining Gaps) | 8 | 8 | 0 |
| **Total** | **27** | **27** | **0** |

---

## Priority 5: Remaining Gaps (Identified 2026-08-24 Re-verification)

These are features that were either partially claimed as done but have deeper gaps, or exist in NvLabsOrg and have no implementation at all.

### 5.1 Wire ParallelExecutor for Fan-Out Pipeline Stages
- **Status:** DONE
- **Problem:** Task 1.5 claimed orchestration wired, but `ParallelExecutor` is **never imported in any route or runner**. The pipeline runner (`_execute_pipeline_bg`) executes stages sequentially only.
- **Fix:** Add a `parallel: true` field to pipeline stage definitions. When a stage has `parallel: true` and contains multiple sub-prompts (or multiple agent_ids), use `ParallelExecutor` with semaphore-bounded concurrency to fan out and collect results.
- **Files:** `src/nexus/api/routes/pipelines.py`, `src/nexus/orchestration/parallel.py`
- **Effort:** Medium (2-3 hours)
- **Dependencies:** 1.3 (pipeline runner — already done)

### 5.2 Wire FailureAnalyzer into Evolution/Diagnostics
- **Status:** DONE
- **Problem:** `FailureAnalyzer` exists in `src/nexus/evolution/` but is never imported by any route. When evolution proposals are evaluated, failure patterns from execution history are not analyzed.
- **Fix:** Add a `POST /api/v1/agents/{agent_id}/diagnose` endpoint that calls `FailureAnalyzer` with the agent's recent task failures. Optionally wire into `evaluate_proposal` as a pre-evaluation step.
- **Files:** `src/nexus/api/routes/evolution.py` or new `src/nexus/api/routes/diagnostics.py`
- **Effort:** Medium (2 hours)
- **Dependencies:** None

### 5.3 Embedding Provider Configuration + Vector Store for Real RAG
- **Status:** DONE
- **Problem:** `RAGPipeline` accepts an `embedding_provider` but none is configured. The pipeline falls back to token-overlap heuristic (BM25-like). No vector store (pgvector, FAISS) is provisioned.
- **Fix:** Add an `EMBEDDING_PROVIDER` env var (options: `openai`, `ollama`, `none`). Create an `OpenAIEmbeddingProvider` class that calls the embeddings API. Configure the knowledge search endpoint to pass it to `RAGPipeline`. Add optional pgvector extension for PostgreSQL or FAISS for local dev.
- **Files:** `src/nexus/knowledge/embeddings.py` (new), `src/nexus/api/routes/knowledge.py`, `src/nexus/config.py`
- **Effort:** High (4-6 hours)
- **Dependencies:** OpenAI API key or Ollama embedding model available

### 5.4 Multi-Agent Terminal Panel in Dashboard
- **Status:** DONE
- **Problem:** Task 3.2 added WebSocket broadcasting from CLI adapter, but the dashboard has no UI panel that shows live output from multiple running agents simultaneously.
- **Fix:** Create a `TerminalPanel` component that opens a WebSocket to `/ws/{client_id}`, subscribes to `agent:*` channels, and displays streaming output in a split-pane terminal view per agent.
- **Files:** `dashboard/src/components/terminal/TerminalPanel.tsx` (new), `dashboard/src/pages/Terminal.tsx` (new)
- **Effort:** High (6-8 hours)
- **Dependencies:** 3.2 (WebSocket broadcasting — already done)

### 5.5 Live Agent-to-Agent Message Delivery
- **Status:** DONE
- **Problem:** Communication routes store messages in DB but nothing delivers them to agents during execution. Agent B doesn't "receive" messages from Agent A.
- **Fix:** When an agent sends a message, push it to the recipient's WebSocket channel. When the recipient agent is executing a task, include unread messages in its next prompt context (similar to memory injection). Add a `/agents/{id}/inbox` endpoint to retrieve unread messages.
- **Files:** `src/nexus/api/routes/communication.py`, `src/nexus/api/routes/chat.py`
- **Effort:** Medium (4-6 hours)
- **Dependencies:** 3.2 (WebSocket — done), 1.1 (memory in chat — done)

### 5.6 Wire CriticEvaluator as Quality Gate
- **Status:** DONE
- **Problem:** `CriticEvaluator` in `src/nexus/orchestration/critic.py` can assess output quality, but nothing triggers it. Agent outputs are never validated before being returned to the user.
- **Fix:** Add an optional quality gate in the pipeline runner and/or chat endpoint: after the LLM responds, pass the output through `CriticEvaluator`. If quality score is below threshold, retry or flag the response.
- **Files:** `src/nexus/api/routes/pipelines.py`, `src/nexus/api/routes/chat.py`
- **Effort:** Low (2-3 hours)
- **Dependencies:** None

### 5.7 Pipeline Builder UI (Visual Node Graph)
- **Status:** DONE
- **Problem:** NvLabsOrg has a drag-and-drop visual pipeline editor. NVLabsCompany only has pipeline list/detail API and basic CRUD forms.
- **Fix:** Create a React canvas component using reactflow or a similar library that allows users to visually compose pipeline stages, set agent assignments, and define dependencies.
- **Files:** `dashboard/src/components/pipelines/PipelineBuilder.tsx` (new), `dashboard/src/pages/Pipelines.tsx`
- **Effort:** High (8-12 hours)
- **Dependencies:** 1.3 (pipeline execution — done)

### 5.8 A/B Test Trigger Endpoint
- **Status:** DONE
- **Problem:** `ABTestFramework` exists in `src/nexus/evolution/` and is used internally by `LLMEvolutionAdvisor`, but there's no API to trigger a real A/B experiment comparing two agent configurations against live traffic.
- **Fix:** Add `POST /api/v1/evolution/ab-test` that creates an experiment with control/variant configs, routes a percentage of traffic to each, and collects comparative metrics over a time window.
- **Files:** `src/nexus/api/routes/evolution.py`, `src/nexus/evolution/ab_test.py`
- **Effort:** Medium (3-4 hours)
- **Dependencies:** 1.6 (evolution engine — done)

---

## Priority 6: Autonomous Orchestration & System Completion

These are the final features needed to make the system fully autonomous rather than purely reactive.

### 6.1 Autonomous Orchestration Coordinator
- **Status:** TODO
- **Problem:** The system has 10 orchestration modules (router, planner, parallel, goal_loop, critic, etc.) that work independently but nothing composes them into a persistent autonomous loop. The platform is reactive (responds to API calls) not proactive (pursues goals).
- **Fix:** Create `src/nexus/runtime/orchestrator.py` — a background service that:
  1. Monitors active goals (status="active")
  2. Decomposes goals into subtasks (LLMTaskPlanner if LLM available, TaskPlanner fallback)
  3. Routes subtasks to best agents (AgentRouter)
  4. Executes in parallel where possible (ParallelExecutor)
  5. Evaluates quality (CriticEvaluator)
  6. Retries with SmartRetry on failure
  7. Escalates to humans when stuck
  8. Updates goal progress
- **Files:** `src/nexus/runtime/orchestrator.py` (new), `src/nexus/main.py` (wire to lifespan)
- **Effort:** High (6-8 hours)
- **Dependencies:** All P1-P5 orchestration work (done)

### 6.2 Persist Chat History to Database
- **Status:** TODO
- **Problem:** Chat conversation history is stored in an in-memory dict (`_conversations`). Lost on server restart.
- **Fix:** Create a `ChatMessage` model (or reuse Message model), persist each message to DB in `_add_message()`, load history from DB in `_get_history()`.
- **Files:** `src/nexus/api/routes/chat.py`, `src/nexus/models/chat.py` (new)
- **Effort:** Medium (2 hours)
- **Dependencies:** None

### 6.3 Persist OKR and Identity to Database
- **Status:** TODO
- **Problem:** OKR objectives/key-results and agent soul/persona state are in-memory only (lost on restart).
- **Fix:** Migrate `okr.py` in-memory dict to OKR model queries. Migrate `identity.py` in-memory soul store to persist via Agent.soul_description field.
- **Files:** `src/nexus/api/routes/okr.py`, `src/nexus/api/routes/identity.py`
- **Effort:** Medium (2-3 hours)
- **Dependencies:** None

### 6.4 OpenAI Adapter stream_execute
- **Status:** TODO
- **Problem:** Only AnthropicAdapter has true token streaming. OpenAI adapter awaits full response.
- **Fix:** Add `stream_execute()` async generator to OpenAIAdapter using `stream=true` in the chat completions API.
- **Files:** `src/nexus/adapters/openai_adapter.py`
- **Effort:** Medium (2 hours)
- **Dependencies:** None

### 6.5 Wire SmartRetry into TaskExecutor
- **Status:** TODO
- **Problem:** TaskExecutor has a simple 3x retry loop. SmartRetryWithEscalation exists but isn't used — it provides failure diagnosis and intelligent escalation (REASSIGN/DECOMPOSE/REPORT_BLOCKER).
- **Fix:** Replace the simple retry loop in `executor.py` with SmartRetryWithEscalation. On REASSIGN, re-route via AgentRouter. On DECOMPOSE, call TaskPlanner.
- **Files:** `src/nexus/runtime/executor.py`, `src/nexus/orchestration/smart_retry.py`
- **Effort:** Medium (2-3 hours)
- **Dependencies:** None

### 6.6 Wire LLMTaskPlanner into /decompose Endpoint
- **Status:** TODO
- **Problem:** The `/tasks/{id}/decompose` endpoint uses the basic TaskPlanner (returns single subtask). LLMTaskPlanner exists with structured JSON prompting for real multi-step decomposition.
- **Fix:** In the decompose endpoint, try LLMTaskPlanner first (if LLM adapter available), fall back to basic TaskPlanner.
- **Files:** `src/nexus/api/routes/tasks.py`, `src/nexus/orchestration/llm_planner.py`
- **Effort:** Low (1 hour)
- **Dependencies:** None

### 6.7 Wire LLMCriticEvaluator into Pipeline Quality Gate
- **Status:** TODO
- **Problem:** Pipeline quality gate uses heuristic CriticEvaluator (output length checks). LLMCriticEvaluator exists with per-criterion LLM evaluation and caching.
- **Fix:** In the pipeline runner quality gate, use LLMCriticEvaluator when LLM is available, fall back to heuristic.
- **Files:** `src/nexus/api/routes/pipelines.py`, `src/nexus/orchestration/llm_critic.py`
- **Effort:** Low (1 hour)
- **Dependencies:** None

### 6.8 Bridge Domain EventBus to Orchestration
- **Status:** TODO
- **Problem:** Two event bus systems exist (realtime + domain) but aren't connected. Task failures don't trigger FailureAnalyzer. Agent errors don't trigger evolution proposals.
- **Fix:** Subscribe to TASK_COMPLETED/AGENT_ERROR/BUDGET_WARNING events in the domain EventBus. On failure patterns, auto-trigger FailureAnalyzer and create evolution proposals.
- **Files:** `src/nexus/communication/event_bus.py`, `src/nexus/runtime/orchestrator.py`
- **Effort:** Medium (2-3 hours)
- **Dependencies:** 6.1 (orchestrator)

### 6.9 Budget Tracker DB Flush
- **Status:** TODO
- **Problem:** `_budget_tracker.pending_spend` accumulates in memory but is never written back to the Company.spent_monthly_cents column in DB.
- **Fix:** Add a periodic flush (every 5 minutes or on shutdown) that writes accumulated spend back to DB.
- **Files:** `src/nexus/api/middleware.py`, `src/nexus/main.py`
- **Effort:** Low (1 hour)
- **Dependencies:** None

### 6.10 Activity Page Real-Time Feed
- **Status:** TODO
- **Problem:** Activity.tsx uses fake random events. The backend has a real activity/events endpoint.
- **Fix:** Wire Activity.tsx to `GET /api/v1/companies/{id}/activity` and optionally subscribe to SSE/WebSocket for real-time updates.
- **Files:** `dashboard/src/pages/Activity.tsx`
- **Effort:** Low (1 hour)
- **Dependencies:** None

---

## Completion Tracking

| Priority | Total | Done | Remaining |
|----------|-------|------|-----------|
| P1 (Wiring Gaps) | 7 | 7 | 0 |
| P2 (Governance) | 3 | 3 | 0 |
| P3 (Feature Gaps) | 5 | 5 | 0 |
| P4 (Polish) | 4 | 4 | 0 |
| P5 (Remaining Gaps) | 8 | 8 | 0 |
| P6 (Autonomy & Completion) | 10 | 7 | 3 |
| **Total** | **37** | **34** | **3** |

---

## Priority 7: Production Hardening (Phase 1)

Critical fixes for multi-worker deployment and data integrity.

### 7.1 Alembic Migration for New Models
- **Status:** TODO
- **Problem:** `ChatMessage` model (6.2) has no migration. SQLite auto-creates tables but PostgreSQL requires explicit migrations.
- **Fix:** Run `alembic revision --autogenerate -m "add chat_messages table"` and verify migration applies cleanly.
- **Files:** `alembic/versions/`, `src/nexus/models/__init__.py` (add ChatMessage import)
- **Effort:** Low (30 min)

### 7.2 Redis-Backed Rate Limiter
- **Status:** TODO
- **Problem:** `_SlidingWindowRateLimiter` is in-memory. Lost on restart, broken with multiple workers.
- **Fix:** Add optional Redis backend using `redis.asyncio`. If `REDIS_URL` env var is set, use Redis sorted sets for sliding window; otherwise fall back to in-memory.
- **Files:** `src/nexus/api/middleware.py`, `src/nexus/config.py`
- **Effort:** Medium (2 hours)

### 7.3 Redis-Backed Budget Tracker
- **Status:** TODO
- **Problem:** `_BudgetTracker` accumulates spend in-memory. Lost on restart, inconsistent across workers.
- **Fix:** Use Redis INCRBY for spend tracking with periodic DB flush. Load from DB on cold start.
- **Files:** `src/nexus/api/middleware.py`
- **Effort:** Medium (2 hours)
- **Dependencies:** 7.2 (Redis connection)

### 7.4 Leader Election for Background Services
- **Status:** TODO
- **Problem:** Scheduler and orchestrator run in every worker process. With `uvicorn --workers N`, triggers fire N times.
- **Fix:** Use Redis-based leader election (SET NX with TTL) or file-lock. Only the leader runs scheduler + orchestrator ticks.
- **Files:** `src/nexus/runtime/scheduler.py`, `src/nexus/runtime/orchestrator.py`
- **Effort:** Medium (2 hours)
- **Dependencies:** 7.2 (Redis connection)

### 7.5 Background Service Health Monitoring
- **Status:** TODO
- **Problem:** Scheduler and orchestrator can silently crash without detection.
- **Fix:** Add a heartbeat mechanism — each background task writes its last tick timestamp. Health endpoint checks staleness (>5 min = unhealthy).
- **Files:** `src/nexus/api/routes/health.py`, `src/nexus/runtime/scheduler.py`, `src/nexus/runtime/orchestrator.py`
- **Effort:** Low (1 hour)

### 7.6 Remove Duplicate Route Definitions
- **Status:** TODO
- **Problem:** 5 route files (tasks, pipelines, knowledge, dashboard, skills) have duplicate function definitions. FastAPI registers the last one; earlier ones are dead code.
- **Fix:** Identify and remove duplicate definitions. Run `tsc --noEmit` equivalent for Python (import all routers, check route count).
- **Files:** `src/nexus/api/routes/tasks.py`, `pipelines.py`, `knowledge.py`, `dashboard.py`, `skills.py`
- **Effort:** Low (30 min)

---

## Priority 8: Frontend Completion (Phase 2)

Wire remaining unmocked pages and integrate existing components.

### 8.1 Evolution Page — Wire to Real Backend
- **Status:** TODO
- **Problem:** Evolution.tsx exists but makes no API calls. Shows empty state.
- **Fix:** Add `useEffect` that fetches proposals from `GET /api/v1/companies/{id}/evolution/proposals`, evaluations from `GET /api/v1/companies/{id}/evolution/evaluations`, and skill versions. Display in a tabbed UI.
- **Files:** `dashboard/src/pages/Evolution.tsx`
- **Effort:** Medium (2 hours)

### 8.2 Terminal Page Route
- **Status:** TODO
- **Problem:** `AgentTerminalPanel` component exists but has no route. Users can't navigate to it.
- **Fix:** Add `/terminal` route in `App.tsx` rendering `AgentTerminalPanel`. Add nav link.
- **Files:** `dashboard/src/App.tsx`, `dashboard/src/components/layout/Sidebar.tsx`
- **Effort:** Low (15 min)

### 8.3 Embed PipelineBuilder in Pipelines Page
- **Status:** TODO
- **Problem:** `PipelineBuilder` component exists but isn't used anywhere in the Pipelines page.
- **Fix:** Add a "Builder" tab or mode in Pipelines.tsx that renders `PipelineBuilder` with `onSave` wired to `POST /pipelines` and `onRun` to `POST /pipelines/{id}/run`.
- **Files:** `dashboard/src/pages/Pipelines.tsx`
- **Effort:** Low (30 min)

### 8.4 Fix PulseLine SSE Hardcoded UUID
- **Status:** TODO
- **Problem:** `components/layout/PulseLine.tsx` uses hardcoded company UUID for the SSE activity stream URL.
- **Fix:** Replace with `getActiveCompanyId()`.
- **Files:** `dashboard/src/components/layout/PulseLine.tsx`
- **Effort:** Low (5 min)

### 8.5 Remove Fake setInterval from Activity.tsx
- **Status:** TODO
- **Problem:** When "live mode" is enabled, Activity.tsx generates random fake events via `setInterval`. Real API is wired but the mock polling still runs.
- **Fix:** Remove the `setInterval` block entirely. Optionally replace with WebSocket subscription for real-time activity.
- **Files:** `dashboard/src/pages/Activity.tsx`
- **Effort:** Low (15 min)

---

## Priority 9: Autonomous Intelligence (Phase 3)

Make the orchestration coordinator truly autonomous with self-healing and iterative refinement.

### 9.1 GoalLoop Integration in Orchestrator
- **Status:** TODO
- **Problem:** Orchestrator decomposes and executes linearly. Doesn't iterate on goals using GoalLoop's judge-based completion detection.
- **Fix:** After all subtasks complete, run GoalLoop with the goal description + combined subtask outputs to determine if the goal is truly complete or needs another iteration.
- **Files:** `src/nexus/runtime/orchestrator.py`
- **Effort:** Medium (2-3 hours)

### 9.2 SmartRetry REASSIGN Action
- **Status:** TODO
- **Problem:** When SmartRetry diagnoses REASSIGN (agent mismatch), the task just fails with a log message. No actual re-routing happens.
- **Fix:** In TaskExecutor, when escalation is REASSIGN, call AgentRouter to find a different agent and retry with the new assignment.
- **Files:** `src/nexus/runtime/executor.py`
- **Effort:** Medium (2 hours)

### 9.3 SmartRetry DECOMPOSE Action
- **Status:** TODO
- **Problem:** When SmartRetry diagnoses DECOMPOSE (task too complex), nothing decomposes. Just logged.
- **Fix:** On DECOMPOSE escalation, call TaskPlanner.decompose_task() on the failed task, create subtasks, and re-attempt execution on the smaller pieces.
- **Files:** `src/nexus/runtime/executor.py`
- **Effort:** Medium (2 hours)

### 9.4 Auto-Evaluate Evolution Proposals
- **Status:** TODO
- **Problem:** Event bridge creates proposals but nobody evaluates them. They sit in "proposed" status.
- **Fix:** In the orchestrator tick, find proposals in "proposed" status older than 5 minutes and auto-trigger evaluation (call the evaluate endpoint logic).
- **Files:** `src/nexus/runtime/orchestrator.py`
- **Effort:** Low (1 hour)

### 9.5 Worktree Isolation from Orchestrator
- **Status:** TODO
- **Problem:** Orchestrator executes tasks in the default process workspace. Agents don't get file-system isolation.
- **Fix:** Pass `use_worktree: true` and `workspace: repo_path` in the session config when orchestrator calls `_call_llm` for CLI-backed agents.
- **Files:** `src/nexus/runtime/orchestrator.py`
- **Effort:** Low (1 hour)

### 9.6 WebSocket Broadcast from Orchestrator
- **Status:** TODO
- **Problem:** Orchestrator executes silently (only logs). No real-time visibility in the UI.
- **Fix:** After each subtask completes/fails, broadcast a status event via `ws_manager.broadcast_to_channel("orchestrator", {...})`.
- **Files:** `src/nexus/runtime/orchestrator.py`
- **Effort:** Low (1 hour)

---

## Priority 10: Platform Features (Phase 4)

Features from the NvLabsOrg comparison that expand the platform's capability.

### 10.1 Cursor CLI Backend
- **Status:** TODO
- **Problem:** NvLabsOrg supports Cursor CLI agent. We don't have it registered.
- **Fix:** Add a `CursorBackendInfo` to `cli_registry.py` with `command="cursor"`, appropriate flags.
- **Files:** `src/nexus/adapters/cli_registry.py`
- **Effort:** Low (30 min)

### 10.2 Webhook Outbound Delivery
- **Status:** TODO
- **Problem:** Trigger type "webhook" exists in the model but no outbound HTTP request is made when a webhook trigger fires.
- **Fix:** In `scheduler.py._fire_trigger()`, if `trigger_type == "webhook"`, make an HTTP POST to `config.webhook_url` with the trigger payload.
- **Files:** `src/nexus/runtime/scheduler.py`
- **Effort:** Low (1 hour)

### 10.3 Multi-Workspace Project Switching
- **Status:** TODO
- **Problem:** The platform operates on a single workspace/repo. No way to switch between projects.
- **Fix:** Add a `Workspace` model (path, name, active). API endpoints to list/switch. CLI adapter uses the active workspace path.
- **Files:** `src/nexus/models/workspace.py` (new), `src/nexus/api/routes/workspaces.py` (new)
- **Effort:** High (6-8 hours)

### 10.4 Theme System
- **Status:** TODO
- **Problem:** Single dark theme. NvLabsOrg has 18 themes.
- **Fix:** Create a CSS variables system with theme presets. Add theme selector in Settings.
- **Files:** `dashboard/src/styles/themes/`, `dashboard/src/components/settings/tabs/ThemeTab.tsx`
- **Effort:** Medium (4-6 hours)

### 10.5 Mobile PWA Support
- **Status:** TODO
- **Problem:** No offline support, no "Add to Home Screen" capability.
- **Fix:** Add `manifest.json`, service worker for caching, responsive tweaks for small screens.
- **Files:** `dashboard/public/manifest.json`, `dashboard/public/sw.js`
- **Effort:** Medium (3-4 hours)

### 10.6 File Explorer Panel
- **Status:** TODO
- **Problem:** No way to browse project files from the dashboard.
- **Fix:** Add a file tree component that calls a new `GET /api/v1/repos/{id}/tree` endpoint. Display in a drawer or dedicated page.
- **Files:** `dashboard/src/components/files/FileExplorer.tsx`, `src/nexus/api/routes/repositories.py`
- **Effort:** High (6-8 hours)

### 10.7 Git Diff/Merge Viewer
- **Status:** TODO
- **Problem:** Worktree changes can't be reviewed before merge. No diff visualization.
- **Fix:** Add `GET /api/v1/repos/{id}/diff` endpoint that runs `git diff`. Render with a diff viewer component (monaco-diff or react-diff-viewer).
- **Files:** `dashboard/src/components/git/DiffViewer.tsx`, `src/nexus/api/routes/repositories.py`
- **Effort:** High (8 hours)

---

## Completion Tracking

| Priority | Total | Done | Remaining |
|----------|-------|------|-----------|
| P1 (Wiring Gaps) | 7 | 7 | 0 |
| P2 (Governance) | 3 | 3 | 0 |
| P3 (Feature Gaps) | 5 | 5 | 0 |
| P4 (Polish) | 4 | 4 | 0 |
| P5 (Remaining Gaps) | 8 | 8 | 0 |
| P6 (Autonomy & Completion) | 10 | 10 | 0 |
| P7 (Production Hardening) | 6 | 6 | 0 |
| P8 (Frontend Completion) | 5 | 5 | 0 |
| P9 (Autonomous Intelligence) | 6 | 6 | 0 |
| P10 (Platform Features) | 7 | 7 | 0 |
| P11 (Integration & Polish) | 8 | 0 | 8 |
| P12 (Quality & Production) | 8 | 0 | 8 |
| P13 (Agent Intelligence) | 8 | 0 | 8 |
| P14 (Observability) | 6 | 0 | 6 |
| P15 (Developer Experience) | 6 | 0 | 6 |
| P16 (Competitive Features) | 6 | 0 | 6 |
| **Total** | **103** | **61** | **42** |

---

## Phase Execution Plan

```
COMPLETED PHASES (P1-P10):
  P1-P6:  Core wiring, governance, features, polish, autonomy      ✅ 37/37
  P7:     Production hardening (migrations, Redis, health)          ✅  6/6
  P8:     Frontend completion (Evolution, terminal, Activity)       ✅  5/5
  P9:     Autonomous intelligence (GoalLoop, SmartRetry, broadcast) ✅  6/6
  P10:    Platform features (Cursor, webhook, themes, PWA, files)   ✅  7/7

UPCOMING PHASES (P11-P16):

Phase 5 — Integration & Polish (P11)          ~5 hours
  ├── 11.1 Route FileExplorer + DiffViewer into pages
  ├── 11.2 Theme selector UI in Settings
  ├── 11.3 Workspace CRUD API routes
  ├── 11.4 Terminal nav link in sidebar
  ├── 11.5 PWA service worker for offline caching
  ├── 11.6 ChatMessage in __all__ export
  ├── 11.7 Fix duplicate routes in repositories.py
  └── 11.8 API docs link in dashboard

Phase 6 — Quality & Production (P12)         ~19 hours
  ├── 12.1 Proper OKR model (replace JSON-in-description hack)
  ├── 12.2 Persist Identity/Soul properly on save
  ├── 12.3 Chat cache cross-worker sync (Redis pub/sub)
  ├── 12.4 PipelineBuilder save to real API
  ├── 12.5 Evolution page — evaluate/promote buttons
  ├── 12.6 CI test integration
  ├── 12.7 Error boundaries per panel
  └── 12.8 Per-agent rate limiting

Phase 7 — Agent Intelligence (P13)           ~20 hours
  ├── 13.1 Multi-turn GoalLoop (multiple iterations per tick)
  ├── 13.2 LLM-based GoalJudge
  ├── 13.3 Inter-agent task delegation
  ├── 13.4 Auto-promote proposals above confidence threshold
  ├── 13.5 Memory importance decay over time
  ├── 13.6 Cross-agent L3 memory promotion
  ├── 13.7 Agent cloning/forking endpoint
  └── 13.8 Pipeline conditional branching

Phase 8 — Observability (P14)                ~11 hours
  ├── 14.1 Correlation ID in all structured logs
  ├── 14.2 Prometheus /metrics endpoint verification
  ├── 14.3 Agent execution timeline UI
  ├── 14.4 Budget alerts/notifications
  ├── 14.5 Audit log page wired to real backend
  └── 14.6 Kill switch admin UI

Phase 9 — Developer Experience (P15)         ~14 hours
  ├── 15.1 Docker Compose (backend + frontend + Redis + PostgreSQL)
  ├── 15.2 Environment variable documentation
  ├── 15.3 Link to /docs (FastAPI auto-docs) from dashboard
  ├── 15.4 Seed data CLI command
  ├── 15.5 Alembic migrations for all new models
  └── 15.6 End-to-end Playwright test suite

Phase 10 — Competitive Features (P16)       ~36 hours
  ├── 16.1 Telegram bot remote control
  ├── 16.2 Desktop Tauri app wrapper
  ├── 16.3 Enhanced 2D/3D office scene
  ├── 16.4 Terminal input (slash commands)
  ├── 16.5 Agent context menu (right-click actions)
  └── 16.6 Drag-and-drop organization chart
```

---

## Priority 11: Integration & Polish (Phase 5)

Connect existing components that are built but not integrated into the UI.

### 11.1 Route FileExplorer + DiffViewer into Pages
- **Status:** TODO
- **Problem:** FileExplorer and DiffViewer components exist but aren't embedded in any page.
- **Fix:** Add FileExplorer as a tab in GitRepos page. Add DiffViewer as a drawer/modal triggered from repo detail.
- **Files:** `dashboard/src/pages/GitRepos.tsx`
- **Effort:** Low (30 min)

### 11.2 Theme Selector UI in Settings
- **Status:** TODO
- **Problem:** Theme system (`themes.ts`) with 5 themes exists but no UI to switch between them.
- **Fix:** Add a ThemeTab in Settings that lists themes with preview swatches and calls `applyTheme()` on selection.
- **Files:** `dashboard/src/components/settings/tabs/ThemeTab.tsx` (new), `dashboard/src/pages/Settings.tsx`
- **Effort:** Low (30 min)

### 11.3 Workspace CRUD API Routes
- **Status:** TODO
- **Problem:** Workspace model exists but no REST endpoints.
- **Fix:** Create `src/nexus/api/routes/workspaces.py` with list, create, switch (set active), delete. Register in main.py.
- **Files:** `src/nexus/api/routes/workspaces.py` (new), `src/nexus/main.py`
- **Effort:** Medium (2 hours)

### 11.4 Terminal Nav Link in Sidebar
- **Status:** TODO
- **Problem:** `/terminal` route exists but no navigation link to reach it.
- **Fix:** Add Terminal icon + link in the sidebar/nav component.
- **Files:** `dashboard/src/components/layout/Sidebar.tsx`
- **Effort:** Low (5 min)

### 11.5 PWA Service Worker
- **Status:** TODO
- **Problem:** manifest.json exists but no service worker for offline caching.
- **Fix:** Create `dashboard/public/sw.js` with cache-first strategy for static assets, network-first for API.
- **Files:** `dashboard/public/sw.js` (new), `dashboard/index.html` (register SW)
- **Effort:** Medium (1 hour)

### 11.6 ChatMessage in __all__ Export
- **Status:** TODO
- **Problem:** ChatMessage imported in models/__init__.py but not listed in `__all__`.
- **Fix:** Add `"ChatMessage"` to the `__all__` list.
- **Files:** `src/nexus/models/__init__.py`
- **Effort:** Trivial (1 min)

### 11.7 Fix Duplicate Routes in repositories.py
- **Status:** TODO
- **Problem:** repositories.py has duplicate stat/commits/PRs/contributors endpoints.
- **Fix:** Remove the shorter duplicate definitions (keep the detailed ones).
- **Files:** `src/nexus/api/routes/repositories.py`
- **Effort:** Low (20 min)

### 11.8 API Docs Link in Dashboard
- **Status:** TODO
- **Problem:** FastAPI auto-generates `/docs` (Swagger) but no link from the dashboard.
- **Fix:** Add an "API Docs" link in Settings or sidebar that opens `/docs` in a new tab.
- **Files:** `dashboard/src/components/layout/Sidebar.tsx`
- **Effort:** Trivial (5 min)

---

## Priority 12: Quality & Production (Phase 6)

Make existing features production-grade and multi-worker safe.

### 12.1 Proper OKR Model
- **Status:** TODO
- **Problem:** OKR data is persisted as Goal records with JSON in the description field. No proper FK relationships.
- **Fix:** Create `Objective` and `KeyResult` SQLModel tables with proper relationships. Migrate OKR routes to use them.
- **Files:** `src/nexus/models/okr.py` (new), `src/nexus/api/routes/okr.py`
- **Effort:** Medium (4 hours)

### 12.2 Persist Identity/Soul Properly
- **Status:** TODO
- **Problem:** identity.py stores agent souls in an in-memory dict. Lost on restart.
- **Fix:** On soul save, write structured data to `Agent.soul_description`. On load, parse from that field. Remove in-memory `_agent_souls` dict.
- **Files:** `src/nexus/api/routes/identity.py`
- **Effort:** Medium (2 hours)

### 12.3 Chat Cache Cross-Worker Sync
- **Status:** TODO
- **Problem:** In-memory `_conversations` dict isn't shared across workers. Same agent shows different history depending on which worker handles the request.
- **Fix:** Use Redis pub/sub to invalidate/update cache across workers. Or always read from DB (remove cache).
- **Files:** `src/nexus/api/routes/chat.py`
- **Effort:** Medium (2 hours)

### 12.4 PipelineBuilder Save to Real API
- **Status:** TODO
- **Problem:** PipelineBuilderCanvas saves are partially wired — creates/patches but may not include all stage metadata.
- **Fix:** Ensure all PipelineStage fields (parallel, quality_gate, sub_prompts, agent_id) are included in the API payload.
- **Files:** `dashboard/src/pages/Pipelines.tsx`
- **Effort:** Low (1 hour)

### 12.5 Evolution Page — Evaluate/Promote Buttons
- **Status:** TODO
- **Problem:** Evolution.tsx shows proposals but can only approve/reject. Can't trigger evaluation or promotion.
- **Fix:** Add "Evaluate" button that calls `POST /evolution/proposals/{id}/evaluate` and "Promote" button for approved proposals.
- **Files:** `dashboard/src/pages/Evolution.tsx`
- **Effort:** Medium (2 hours)

### 12.6 CI Test Integration
- **Status:** TODO
- **Problem:** 20+ test files exist but no CI pipeline runs them.
- **Fix:** Add `.github/workflows/test.yml` that runs `pytest` and `tsc --noEmit`.
- **Files:** `.github/workflows/test.yml` (new)
- **Effort:** Medium (3 hours)

### 12.7 Error Boundaries Per Panel
- **Status:** TODO
- **Problem:** A crash in one component white-screens the entire app.
- **Fix:** Add React ErrorBoundary wrapper around each major page section (sidebar, main content, drawers).
- **Files:** `dashboard/src/components/common/ErrorBoundary.tsx` (new)
- **Effort:** Medium (2 hours)

### 12.8 Per-Agent Rate Limiting
- **Status:** TODO
- **Problem:** Rate limiter is per-company only. A single noisy agent can consume all quota.
- **Fix:** Add optional per-agent rate limiting in the middleware (keyed by `company_id:agent_id` in chat paths).
- **Files:** `src/nexus/api/middleware.py`
- **Effort:** Low (1 hour)

---

## Priority 13: Agent Intelligence (Phase 7)

Deepen the autonomous capabilities.

### 13.1 Multi-Turn GoalLoop
- **Status:** TODO
- **Problem:** Orchestrator runs 1 iteration per tick. Fast goals waste 2-minute wait between iterations.
- **Fix:** After a subtask completes, immediately check if more work is needed (up to 3 iterations per tick).
- **Files:** `src/nexus/runtime/orchestrator.py`
- **Effort:** Medium (3 hours)

### 13.2 LLM-Based GoalJudge
- **Status:** TODO
- **Problem:** HeuristicGoalJudge only does keyword matching. Misses nuanced completion.
- **Fix:** Create `LLMGoalJudge` that prompts an LLM with the goal + output and asks "is this goal achieved?" Falls back to heuristic.
- **Files:** `src/nexus/orchestration/goal_loop.py`
- **Effort:** Medium (2 hours)

### 13.3 Inter-Agent Task Delegation
- **Status:** TODO
- **Problem:** Agents can't assign work to each other during execution.
- **Fix:** Add a `/agents/{id}/delegate` endpoint that creates a task assigned to another agent and notifies via inbox. The delegating agent can await the result.
- **Files:** `src/nexus/api/routes/agents.py`, `src/nexus/api/routes/communication.py`
- **Effort:** Medium (4 hours)

### 13.4 Auto-Promote Above Confidence Threshold
- **Status:** TODO
- **Problem:** Auto-evaluate creates evaluations but proposals sit in "evaluating" forever. No auto-promotion.
- **Fix:** If `evaluation.passed == True` and `proposal.confidence >= 0.8`, auto-promote (skip human approval for high-confidence proposals).
- **Files:** `src/nexus/runtime/orchestrator.py`
- **Effort:** Low (1 hour)

### 13.5 Memory Importance Decay
- **Status:** TODO
- **Problem:** MemoryRecord.importance never decreases. Old irrelevant memories dominate context.
- **Fix:** Add a decay function: on each orchestrator tick, reduce importance of memories not accessed in 7+ days by 5%.
- **Files:** `src/nexus/runtime/orchestrator.py`
- **Effort:** Medium (2 hours)

### 13.6 Cross-Agent L3 Memory Promotion
- **Status:** TODO
- **Problem:** When one agent discovers something useful, it stays in their L2 memory. Not shared.
- **Fix:** After task completion, if output contains "discovery" or "learned" patterns, promote key facts to L3 shared memory with `scope="company"`.
- **Files:** `src/nexus/runtime/orchestrator.py`, `src/nexus/api/routes/memory.py`
- **Effort:** Medium (3 hours)

### 13.7 Agent Cloning/Forking Endpoint
- **Status:** TODO
- **Problem:** No way to duplicate an agent's config + soul as a starting point for a new agent.
- **Fix:** Add `POST /agents/{id}/clone` that copies all fields (name suffixed "-clone"), creates a new agent record.
- **Files:** `src/nexus/api/routes/agents.py`
- **Effort:** Low (1 hour)

### 13.8 Pipeline Conditional Branching
- **Status:** TODO
- **Problem:** Pipelines are linear chains. Can't handle "if quality gate fails, run alternative path."
- **Fix:** Add `on_fail` field to stage definition (stage ID to jump to on failure). Pipeline runner checks and branches.
- **Files:** `src/nexus/api/routes/pipelines.py`
- **Effort:** Medium (4 hours)

---

## Priority 14: Observability (Phase 8)

Production monitoring and visibility.

### 14.1 Correlation ID in Structured Logs
- **Status:** TODO
- **Problem:** RequestIDMiddleware generates IDs but not all log calls include them.
- **Fix:** Add a context variable for request_id and inject into the logging format/filter.
- **Files:** `src/nexus/logging_config.py`
- **Effort:** Medium (2 hours)

### 14.2 Prometheus /metrics Verification
- **Status:** TODO
- **Problem:** MetricsMiddleware exists but the `/metrics` endpoint may not be serving proper Prometheus format.
- **Fix:** Verify the metrics endpoint returns text/plain with proper histogram/counter formatting. Add custom business metrics (active_agents, total_tokens_today).
- **Files:** `src/nexus/telemetry.py`
- **Effort:** Low (1 hour)

### 14.3 Agent Execution Timeline UI
- **Status:** TODO
- **Problem:** No visual timeline showing agent execution history (when, what, cost).
- **Fix:** Create a timeline component that fetches from `/agents/{id}/activity` or `/agent-logs` and displays as a chronological feed.
- **Files:** `dashboard/src/components/agents/AgentTimeline.tsx` (new)
- **Effort:** Medium (4 hours)

### 14.4 Budget Alerts/Notifications
- **Status:** TODO
- **Problem:** Budget enforcement blocks at 100%. No warning before limit.
- **Fix:** When spend reaches 80%/90%, create a notification and optionally emit a WebSocket event.
- **Files:** `src/nexus/api/middleware.py`, `src/nexus/runtime/event_bridge.py`
- **Effort:** Low (1 hour)

### 14.5 Audit Log Page Wired to Backend
- **Status:** TODO
- **Problem:** AuditLogsTab in Settings uses static mock data.
- **Fix:** Wire to `GET /api/v1/companies/{id}/audit-logs` endpoint with real data from the DB.
- **Files:** `dashboard/src/components/settings/tabs/AuditLogsTab.tsx`
- **Effort:** Low (1 hour)

### 14.6 Kill Switch Admin UI
- **Status:** TODO
- **Problem:** GovernanceMiddleware kill switch works but no UI to activate/deactivate it.
- **Fix:** Add a "Governance" section in Settings with toggle for kill switch + confirmation modal.
- **Files:** `dashboard/src/components/settings/tabs/GovernanceTab.tsx` (new)
- **Effort:** Medium (2 hours)

---

## Priority 15: Developer Experience (Phase 9)

Make the project easy to set up, develop, and deploy.

### 15.1 Docker Compose
- **Status:** TODO
- **Problem:** No containerization. Developers must manually install Python, Node, set up DB.
- **Fix:** Create `docker-compose.yml` with services: backend (uvicorn), frontend (node), postgres, redis. Include `.env.example`.
- **Files:** `docker-compose.yml` (new), `.env.example` (new), `Dockerfile` (new)
- **Effort:** Medium (3 hours)

### 15.2 Environment Variable Documentation
- **Status:** TODO
- **Problem:** 15+ env vars across the system with no central reference.
- **Fix:** Create `docs/ENVIRONMENT.md` listing all env vars, their purpose, defaults, and examples.
- **Files:** `docs/ENVIRONMENT.md` (new)
- **Effort:** Low (1 hour)

### 15.3 API Docs Link from Dashboard
- **Status:** TODO
- **Problem:** FastAPI serves interactive docs at `/docs` but users don't know about it.
- **Fix:** Add "API Reference" link in the sidebar footer that opens `/docs` in new tab.
- **Files:** `dashboard/src/components/layout/Sidebar.tsx`
- **Effort:** Trivial (5 min)

### 15.4 Seed Data CLI Command
- **Status:** TODO
- **Problem:** Demo data is seeded at startup only. Can't re-seed without restarting.
- **Fix:** Add a CLI command: `python -m nexus.demo.seed --reset` that drops and re-creates demo data.
- **Files:** `src/nexus/demo/seed.py` (add __main__ support)
- **Effort:** Low (1 hour)

### 15.5 Alembic Migrations for All Models
- **Status:** TODO
- **Problem:** Only ChatMessage has an explicit migration. Workspace and other schema changes need migrations.
- **Fix:** Run `alembic revision --autogenerate` to detect Workspace and any other unmigrated models.
- **Files:** `alembic/versions/`
- **Effort:** Low (1 hour)

### 15.6 End-to-End Playwright Test Suite
- **Status:** TODO
- **Problem:** No browser-level tests for critical flows (login, hire, chat, stream).
- **Fix:** Set up Playwright with 5 core test scenarios. Add to CI.
- **Files:** `tests/e2e/` (new directory), `playwright.config.ts` (new)
- **Effort:** High (8 hours)

---

## Priority 16: Competitive Features (Phase 10)

Market positioning and differentiation vs NvLabsOrg.

### 16.1 Telegram Bot Remote Control
- **Status:** TODO
- **Problem:** Can only control agents from the web dashboard.
- **Fix:** Create a Telegram bot that accepts commands (/chat, /status, /hire, /kill) and proxies to the API.
- **Files:** `src/nexus/integrations/telegram_bot.py` (new)
- **Effort:** High (8 hours)

### 16.2 Desktop Tauri App
- **Status:** TODO
- **Problem:** No native desktop app. NvLabsOrg has Tauri v2 wrapper.
- **Fix:** Add `apps/desktop/` with Tauri config wrapping the web dashboard. System tray for notifications.
- **Files:** `apps/desktop/` (new Tauri project)
- **Effort:** High (10+ hours)

### 16.3 Enhanced Office Scene
- **Status:** TODO
- **Problem:** Basic 2D office exists. NvLabsOrg has richer PixiJS scene with agent animations.
- **Fix:** Add agent status indicators, walking animations, and interaction bubbles to the office canvas.
- **Files:** `dashboard/src/components/office2d/OpenOfficeCanvas.tsx`
- **Effort:** High (8 hours)

### 16.4 Terminal Input (Slash Commands)
- **Status:** TODO
- **Problem:** AgentTerminalPanel is view-only. Can't send commands.
- **Fix:** Add an input field that sends WebSocket messages to agents or executes slash commands.
- **Files:** `dashboard/src/components/terminal/AgentTerminalPanel.tsx`
- **Effort:** Medium (2 hours)

### 16.5 Agent Context Menu
- **Status:** TODO
- **Problem:** Agent cards only have click-to-detail and chat button. No quick actions.
- **Fix:** Add right-click context menu on agent cards: Wake, Pause, Chat, Clone, Fire, View Logs.
- **Files:** `dashboard/src/components/agents/AgentCard.tsx`
- **Effort:** Medium (2 hours)

### 16.6 Drag-and-Drop Organization Chart
- **Status:** TODO
- **Problem:** Organization page shows static department/squad structure.
- **Fix:** Add drag-and-drop to move agents between departments/squads. Save via PATCH API.
- **Files:** `dashboard/src/pages/Organization.tsx`
- **Effort:** High (6 hours)

---

*Last updated: 2026-08-24 by Kiro agent session*
