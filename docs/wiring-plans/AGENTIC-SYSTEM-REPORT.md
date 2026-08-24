# NVLabsCompany — Agentic System Architecture Report

> **Scope:** Deep technical review of the autonomous agent execution engine — orchestration, identity, memory, adapters, governance, and real-time communication.
> **Generated:** 2026-08-24 | Verified against codebase via sub-agent analysis

---

## 1. Executive Summary

NVLabsCompany implements a **multi-layer autonomous agent platform** with:
- **10 LLM adapters** (Anthropic, OpenAI, Ollama, CLI, Azure, Bedrock, Google, HTTP, MCP, Claude Code)
- **Soul/Persona identity system** with token-budgeted context assembly
- **4-layer memory architecture** (L0 ephemeral → L1 session → L2 agent → L3 shared)
- **10 orchestration modules** (router, planner, parallel, goal loop, critic, phase machine, reasoning, smart retry, LLM planner, LLM critic)
- **Full governance stack** (kill switch, circuit breaker, budget enforcement, policy engine, rate limiter)
- **Real-time communication** (WebSocket channels, SSE streaming, event bus, A2A protocol)

### What Works End-to-End Today
```
User Message → Chat Endpoint → Memory Fetch → Soul/Persona Build →
Token Budget → Adapter Resolution → LLM Call (real API) →
Budget Recording → SSE Streaming → Frontend Display
```

### What's Built but Not Autonomously Connected
```
TaskPlanner → AgentRouter → ParallelExecutor → CriticEvaluator →
GoalLoop → SmartRetry → FailureAnalyzer → LLMEvolutionAdvisor
```
Each module works independently and is tested — they await a top-level orchestration coordinator.

---

## 2. Agent Execution Flow (Complete Trace)

### 2.1 Chat Request → Response (Non-Streaming)

```
POST /api/v1/agents/{id}/chat { prompt: "..." }

1. Load Agent from DB (SQLAlchemy, company_id scoped)
2. Fetch top-10 memories (MemoryRecord, importance DESC)
3. Build System Prompt:
   a. Construct Soul from agent fields (name, role, capabilities, soul_description)
   b. Parse structured persona (Personality/Communication/Values/Constraints/Tone)
   c. Create Persona + ContextBudget (4096 total: 1500 identity, 1500 memory, 1096 task)
   d. Call persona.build_working_context() → truncate to budget
   e. Append responsibilities, objectives, memory lines
4. Resolve Adapter:
   a. Map adapter_type → registry key (anthropic/openai/cli/ollama/etc.)
   b. Build config (API key from env, model from agent)
5. Call LLM:
   a. AdapterRegistry.create_adapter(key)
   b. adapter.create_session(agent_id, config)
   c. Build messages from last 10 history entries
   d. adapter.execute_task(session, task_id, payload)
   e. adapter.terminate(session)
6. Store response in conversation history (in-memory dict)
7. Record budget spend (~1 cent per 500 tokens)
8. Return ChatResponse { message, history, model_used, tokens_used }
```

### 2.2 Streaming Chat (SSE)

```
POST /api/v1/agents/{id}/chat/stream

Steps 1-4 same as above, then:
5a. If adapter has stream_execute (Anthropic):
    - httpx.AsyncClient.stream("POST", messages_api, stream=True)
    - Parse SSE lines: data: {"type": "content_block_delta", "delta": {"text": "..."}}
    - Yield each text chunk immediately to client
5b. If no streaming support:
    - Call adapter.execute_task() (full response)
    - Emit word-by-word with 10-20ms delays (simulated streaming)
6. Emit done event with full message + tokens
7. Emit [DONE] sentinel
```

### 2.3 Pipeline Execution (Background)

```
POST /api/v1/pipelines/{id}/run

1. Create PipelineRun record (status: "running")
2. Schedule BackgroundTask(_execute_pipeline_bg)
3. For each stage:
   a. Check if run was cancelled/paused (DB refresh)
   b. If stage.parallel=true + sub_prompts:
      - ParallelExecutor.execute_parallel(tasks, executor_fn)
      - Collect all outputs, join with separator
   c. Else: sequential single-agent execution
   d. Inject previous_output into current prompt
   e. Optional quality gate: CriticEvaluator.evaluate()
   f. Record stage results
4. Finalize run (status: "completed"/"failed")
```

### 2.4 Scheduled Trigger Execution

```
Background Loop (60s tick):
1. Query Triggers where next_fire_at <= now AND is_active
2. For each due trigger:
   a. Load assigned agent from DB
   b. Build system prompt (same flow as chat)
   c. Call _call_llm() with trigger's config.prompt
   d. Record TriggerExecution
   e. Calculate next_fire_at (cron parser)
```

---

## 3. Identity & Soul System

### 3.1 Soul Architecture

```python
@dataclass
class Soul:
    name: str               # "Atlas-01"
    role: str               # "software-architect"
    personality_traits: []  # ["analytical", "thorough", "pragmatic"]
    communication_style: "" # "Concise, data-driven, uses technical language"
    expertise: []           # ["system-design", "scalability", "trade-offs"]
    values: []              # ["correctness", "simplicity", "documentation"]
    constraints: []         # ["must document decisions", "no premature optimization"]
    background: ""          # Free-text narrative history
    tone: ""                # "professional" / "casual" / "analytical"
```

### 3.2 System Prompt Generation

`system_prompt_from_soul()` produces structured natural language:
```
You are Atlas-01 serving as a software-architect.

Background: Senior architect with 15 years of distributed systems experience.

Personality: You are analytical, thorough, pragmatic.

Communication style: Concise, data-driven, uses technical language

Tone: Maintain a professional tone in all interactions.

Expertise: Your areas of deep knowledge include system-design, scalability, trade-offs.

Core values: You prioritize correctness, simplicity, documentation.

Constraints:
- must document all architectural decisions
- no premature optimization
- prefer composition over inheritance
```

### 3.3 Token Budgeting (Persona.build_working_context)

```
Total Budget: 4096 tokens
├── Identity:  1500 tokens (Soul prompt, truncated if over)
├── Memory:    1500 tokens (memories fitted iteratively until full)
└── Task:      1096 tokens (responsibilities + objectives, key-by-key)
```

Token estimation: ~4 characters per token heuristic.

### 3.4 Templates

6 pre-built soul templates: `engineer`, `researcher`, `manager`, `qa_engineer`, `architect`, `ceo_orchestrator`. Exposed via `GET /api/v1/soul-templates`.

---

## 4. Memory System

### 4.1 Production Memory (DB-Backed)

`MemoryRecord` SQLAlchemy model:
- `agent_id` — owning agent
- `scope` — agent/team/department/company
- `content` — the memory text
- `importance` — 0.0-1.0 relevance score
- `tier` — hot/warm/cold (3-temperature)
- `access_count` — usage frequency tracking
- `last_accessed_at` — for decay calculations

**Chat Integration:** `_fetch_agent_memories()` queries top-10 by importance, passes to `build_working_context()` which fits them within the 1500-token memory budget.

### 4.2 LayeredMemoryStore (In-Process)

4-layer architecture for runtime use:
- **L0 (Ephemeral):** Managed by caller (working memory during task)
- **L1 (Session):** Ring buffer of session summaries (max 50, FIFO)
- **L2 (Agent):** Per-agent facts with Jaccard dedup (max 500/agent)
- **L3 (Shared):** Organization-wide knowledge (promoted from L2)

Features:
- `get_context_window(agent_id, limit)` — blends L1 (25%) + L2 (50%) + L3 (25%)
- Atomic JSON persistence (tempfile + os.replace)
- Jaccard similarity dedup (threshold 0.7)
- `promote_to_shared()` — copies L2 fact to L3

### 4.3 BM25 Retriever

Pure-Python Okapi BM25 (k1=1.5, b=0.75):
- `tokenize()` — lowercase + alphanumeric split
- `bm25_score()` — standard IDF weighting
- `search(query, memories, top_k)` — returns ranked (index, score) tuples
- Wired to `GET /api/v1/agents/{id}/memory/search`

### 4.4 LLM Fact Extraction

`LLMFactExtractor`:
- Calls LLM with structured prompt for: decisions_made, tools_discovered, patterns_learned, errors_encountered
- Rate limited (10 calls/min rolling window)
- Short-text bypass (<200 chars → regex fallback)
- Falls back to regex `FactExtractor` on failure

---

## 5. Orchestration Modules (10 Components)

### 5.1 Wired to API

| Module | Wired Via | Trigger |
|--------|-----------|---------|
| **AgentRouter** | `tasks.py` create_task | Auto-assigns when `assigned_agent_id` is null |
| **TaskPlanner** | `tasks.py` POST /decompose | Explicit API call |
| **GoalLoop** | `goals.py` POST /execute | Explicit API call |
| **ParallelExecutor** | `pipelines.py` parallel stages | Pipeline runner detects `parallel: true` |
| **CriticEvaluator** | `pipelines.py` quality gate | Pipeline stage with `quality_gate: true` |

### 5.2 Standalone (Not Wired to API)

| Module | Purpose | What's Needed to Wire |
|--------|---------|----------------------|
| **PhaseMachine** | Team collaboration state machine (CREATE→DESIGN→EXECUTE→COMPLETE) | Leader agent workflow endpoint |
| **ThoughtTree/ToTPlanner** | Tree-of-thought reasoning with beam search | LLM callable injection + planner endpoint |
| **SmartRetryWithEscalation** | Intelligent failure diagnosis (REPORT_BLOCKER / REASSIGN / DECOMPOSE) | Wrap TaskExecutor calls |
| **LLMTaskPlanner** | LLM-based task decomposition (structured JSON output) | Replace default planner in /decompose |
| **LLMCriticEvaluator** | LLM-based quality evaluation with caching | Replace heuristic critic in pipeline |

### 5.3 The Missing Orchestration Coordinator

There is no top-level "autonomous loop" that chains these together:
```
[Not yet implemented]
TaskPlanner.decompose()
  → AgentRouter.route() (per subtask)
    → ParallelExecutor.execute() (ready subtasks)
      → CriticEvaluator.evaluate() (quality gate)
        → GoalLoop.run() (retry if not done)
          → SmartRetry.escalate() (on repeated failure)
            → FailureAnalyzer.diagnose() (if escalated)
```

Each piece works. The composition doesn't exist yet.

---

## 6. Adapter System (10 Backends)

### 6.1 Adapter Registry

| Key | Class | Streaming | CLI Backend |
|-----|-------|-----------|-------------|
| `anthropic` | AnthropicAdapter | ✅ `stream_execute()` | — |
| `openai` | OpenAIAdapter | Planned | — |
| `ollama` | OllamaAdapter | — | — |
| `cli` | CLIAdapter | — (subprocess) | claude, codex, aider, kiro-cli, agy, opencode |
| `claude_code` | ClaudeCodeAdapter | — | claude (direct) |
| `http` | HTTPAdapter | — | — |
| `mcp` | MCPAgentAdapter | — | — |
| `azure_openai` | AzureOpenAIAdapter | — | — |
| `bedrock` | BedrockAdapter | — | — |
| `google_gemini` | GoogleGeminiAdapter | — | — |

### 6.2 CLI Adapter Features
- Multi-backend via `CLIRegistry` (auto-detects installed CLIs via `shutil.which`)
- Instruction file generation (`.claude/CLAUDE.md`, `AGENTS.md`, `.kiro/steering/main.md`)
- Git worktree isolation (optional, creates per-agent branch)
- Auto-commit + merge on cleanup
- Interactive stdin mode with `_stream_output()` → WebSocket broadcast
- Artifact detection (file diffs before/after execution)
- Token/cost parsing from CLI output

### 6.3 Session Lifecycle
```
create_session(agent_id, config) → AgentSession
  ↓
execute_task(session, task_id, payload) → TaskResult
  ↓ (can repeat)
terminate(session) → cleanup
```

---

## 7. Governance Stack

### 7.1 Middleware (Every Request)

```
Request → CORS → RequestID → Metrics → APIVersion → Authentication → Governance
                                                                        ↓
                                                          1. Kill Switch (503)
                                                          2. Rate Limit (429)
                                                          3. Policy (403)
                                                          4. Budget (429)
                                                          5. Audit Log
                                                          6. Headers
```

### 7.2 Kill Switch
- Per-company activation via `_KillSwitchRegistry` singleton
- Loaded from DB at startup via `PersistentKillSwitch`
- Returns 503 immediately for all requests from killed companies
- ControlRegistry also has per-agent halt/pause/gate

### 7.3 Rate Limiting
- Sliding window per company (100 req/60s default)
- Thread-safe deque of timestamps
- Returns 429 + `Retry-After` header when exceeded

### 7.4 Budget Enforcement
- In-memory `_BudgetTracker` seeded from Company.budget_monthly_cents at startup
- Route-pattern cost estimation: chat=5¢, execute=10¢, other=0
- `record_spend()` accumulates post-LLM-call
- Returns 429 when (spent + estimated) > budget

### 7.5 Policy Engine
- `_policy_cache` loaded from Policy model at startup
- `fnmatch`-based path matching for deny rules
- Method restrictions (deny DELETE, etc.)
- Time-based restrictions (deny_after_hour/deny_before_hour UTC)

### 7.6 ControlRegistry (Operator Controls)
Per-agent runtime controls:
- **pause** — deny all tool calls
- **gate_tool** — deny specific tools
- **steer** — inject guidance text into context (FIFO queue, max 10KB)
- **halt** — graceful stop at next hook boundary
- **resume** — clear pause + halt

---

## 8. Communication & Real-Time

### 8.1 WebSocket
- `/ws/{client_id}` endpoint with auth (cookie or API key)
- Channel subscriptions: `subscribe/unsubscribe` commands
- `broadcast_to_channel(channel, data)` — from CLI adapter `_stream_output()`
- Multi-tenant isolation (company_id stored per connection)

### 8.2 SSE Streaming
- Chat stream endpoint: `StreamingResponse` with `text/event-stream`
- Protocol: `data: {"type": "chunk"/"done"/"error", ...}\n\n`
- True token streaming for Anthropic (httpx async stream)
- Simulated streaming for other adapters (word-by-word)

### 8.3 Agent-to-Agent Protocol (A2A)
- Message types: request, response, notification, delegation, handoff
- Priorities: urgent, normal, low
- Delivery routes: direct, broadcast, team
- Deduplication via correlation_id
- Inbox API: `GET /agents/{id}/inbox`, `POST /agents/{id}/inbox/mark-read`
- Broadcast API: `POST /communication/broadcast`

### 8.4 Event Bus (Dual Implementation)
1. **Realtime EventBus** — asyncio.Queue-based for WebSocket/SSE streaming (non-blocking pub/sub)
2. **Domain EventBus** — handler-based for business events (TASK_COMPLETED, AGENT_ERROR, etc.) with DB persistence and replay capability

---

## 9. Evolution & Self-Improvement

### 9.1 Flow
```
Agent Failures → FailureAnalyzer.root_cause_analysis()
                        ↓
LLMEvolutionAdvisor.suggest_improvements()
                        ↓
EvolutionProposal (DB record)
                        ↓
POST /evaluate → LLM scoring + ABTestFramework
                        ↓
POST /approve (human gate)
                        ↓
POST /promote → applies config changes to Agent model
```

### 9.2 Components
- **FailureAnalyzer** — root cause analysis, success factor extraction, bottleneck identification
- **LLMEvolutionAdvisor** — LLM-driven improvement suggestions with heuristic fallback
- **ABTestFramework** — power analysis, Welch's t-test, effect size, early stopping
- **POST /diagnose** — triggers failure analysis for an agent
- **POST /ab-test** — runs comparative experiment between two configs

---

## 10. What's Missing for Full Autonomy

### The Autonomous Orchestration Coordinator
A background service that continuously:
1. Monitors goal progress
2. Decomposes goals into tasks (LLMTaskPlanner)
3. Routes tasks to best agents (AgentRouter)
4. Executes in parallel where possible (ParallelExecutor)
5. Evaluates quality (CriticEvaluator)
6. Retries with intelligence (SmartRetry)
7. Escalates to humans when stuck
8. Triggers evolution proposals on repeated failures
9. Self-heals via promote cycle

### Current Gap
Today each piece works in isolation or via explicit API calls. The system is **reactive** (responds to user commands) rather than **proactive** (autonomously pursues goals). Bridging this gap requires:
- A persistent goal monitor that polls goal progress
- An event-driven trigger from TaskExecutor failures → FailureAnalyzer → EvolutionAdvisor
- Wiring SmartRetry into the pipeline runner
- Connecting the domain EventBus to the orchestration layer

---

## 11. System Statistics

| Metric | Count |
|--------|-------|
| Backend route files | 44 |
| API endpoints | 200+ |
| SQLAlchemy models | 55+ |
| LLM adapters | 10 |
| Orchestration modules | 10 |
| CLI backends supported | 6 (claude, codex, aider, kiro-cli, agy, opencode) |
| Soul templates | 6 |
| Agent archetypes | 20 |
| Team templates | 6 |
| Memory layers | 4 (L0-L3) |
| Governance checks per request | 6 |
| Frontend pages | 26 |
| Frontend components | 50+ |
| Background services | 2 (scheduler, heartbeat) |
| Disk persistence stores | 0 (removed — all DB now) |
| Tests | 20+ test files covering orchestration, memory, persistence |

---

*Report generated by Kiro agent with full codebase verification via context-gatherer sub-agents.*
