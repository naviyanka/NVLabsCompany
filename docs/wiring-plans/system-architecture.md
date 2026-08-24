# NEXUS Agent System — Architecture & Wiring Status

This document maps every major subsystem, shows how they connect, and indicates what's fully wired end-to-end vs what exists but isn't connected yet.

---

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (React + Vite)                                │
│                                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────────────────┐  │
│  │ Agents Page │  │ Hire Modal  │  │ Agent Chat  │  │  Other Pages          │  │
│  │  (list/grid)│  │ (4 modes)   │  │  (drawer)   │  │  (activity, tasks...) │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └───────────┬───────────┘  │
│         │                │                │                      │              │
│         ▼                ▼                ▼                      ▼              │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                    API Client (apiClient + api/agents.ts)                │    │
│  └─────────────────────────────────────┬───────────────────────────────────┘    │
└────────────────────────────────────────┼────────────────────────────────────────┘
                                         │
                                         │ HTTP (JSON)
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                     EXPRESS MOCK SERVER (server.ts → dist/server.cjs)               │
│                                                                                    │
│  • GET/POST /agents (CRUD + persistence to disk)     ✅ WIRED                      │
│  • POST /agents/hire-team (batch hire)               ✅ WIRED                      │
│  • POST /agents/hire-from-manifest                   ✅ WIRED                      │
│  • GET /agent-archetypes (20 templates)              ✅ WIRED                      │
│  • GET /agent-providers (real CLI detection)         ✅ WIRED                      │
│  • GET /agent-providers/:id/models                   ✅ WIRED                      │
│  • GET /team-templates (6 presets)                   ✅ WIRED                      │
│  • GET /soul-templates (5 persona presets)           ✅ WIRED                      │
│  • POST /agents/:id/chat (CANNED response)          ⚠️  MOCK ONLY                 │
│  • Agents persist to data/agents_database.json       ✅ WIRED                      │
└────────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         │ (when PROXY_API=true or real backend running)
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                        FASTAPI BACKEND (src/nexus/main.py)                          │
│                                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │                        API ROUTES (50+ endpoints)                             │  │
│  │                                                                              │  │
│  │  ✅ agents.py      — CRUD, wake/pause/heartbeat/delete                       │  │
│  │  ✅ hiring.py      — hire-team, hire-from-manifest                           │  │
│  │  ✅ archetypes.py  — agent-archetypes, agent-templates, team-templates       │  │
│  │  ✅ providers.py   — agent-providers, models per provider                    │  │
│  │  ✅ chat.py        — REAL LLM chat (NEW - connects soul + adapter)           │  │
│  │  ✅ identity.py    — soul CRUD, soul-templates, working context              │  │
│  │  ✅ activity.py    — audit log feed                                          │  │
│  │  ✅ tasks.py       — task CRUD + assignment                                  │  │
│  │  ✅ goals.py       — goals + OKR tracking                                    │  │
│  │  ✅ memory.py      — memory store/retrieve/search                            │  │
│  │  ✅ skills.py      — skill registry + agent assignment                       │  │
│  │  ✅ tools.py       — tool registry + access control                          │  │
│  │  ✅ pipelines.py   — pipeline definitions + runs                             │  │
│  │  ✅ budgets.py     — budget policies + usage tracking                        │  │
│  │  ✅ approvals.py   — governance approval workflows                           │  │
│  │  ✅ events.py      — SSE real-time streaming                                 │  │
│  │  + 30 more routes...                                                         │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                         │                                          │
│  ┌──────────────────────────────────────┼──────────────────────────────────────┐   │
│  │                    DOMAIN SERVICES                                           │   │
│  │                                                                             │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐     │   │
│  │  │  Identity/Soul  │  │ Memory System   │  │  Adapter Registry       │     │   │
│  │  │                 │  │                 │  │                         │     │   │
│  │  │ • Soul dataclass│  │ • 3-temp store  │  │ • 10 adapter types     │     │   │
│  │  │ • 5 templates   │  │   (hot/warm/    │  │ • create_adapter()     │     │   │
│  │  │ • system_prompt │  │    cold)        │  │ • health_check()       │     │   │
│  │  │   _from_soul()  │  │ • 4-layer       │  │                         │     │   │
│  │  │ • Persona class │  │   (L1-L3)       │  │  Registered types:      │     │   │
│  │  │ • working       │  │ • BM25 search   │  │  • openai              │     │   │
│  │  │   context build │  │ • dedup         │  │  • anthropic           │     │   │
│  │  │ • token budget  │  │ • compaction    │  │  • ollama              │     │   │
│  │  └────────┬────────┘  └────────┬────────┘  │  • claude_code         │     │   │
│  │           │                    │            │  • cli (generic)       │     │   │
│  │           │                    │            │  • http                │     │   │
│  │           ▼                    ▼            │  • mcp                 │     │   │
│  │  ┌──────────────────────────────────────┐  │  • azure_openai        │     │   │
│  │  │         CHAT ENDPOINT (NEW)          │  │  • bedrock             │     │   │
│  │  │                                      │  │  • google_gemini       │     │   │
│  │  │  1. Load agent from DB               │  └────────────┬────────────┘     │   │
│  │  │  2. Build Soul from agent data       │               │                  │   │
│  │  │  3. Generate system prompt           │               │                  │   │
│  │  │  4. Get conversation history         │               │                  │   │
│  │  │  5. Call LLM adapter ─────────────────────────────────┘                  │   │
│  │  │  6. Return real response             │                                   │   │
│  │  └──────────────────────────────────────┘                                   │   │
│  │                                                                             │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────────┐    │   │
│  │  │  Runtime        │  │ Orchestration   │  │  Communication           │    │   │
│  │  │                 │  │                 │  │                          │    │   │
│  │  │ • TaskExecutor  │  │ • AgentRouter   │  │ • A2A messaging          │    │   │
│  │  │ • Lifecycle Mgr │  │ • TaskPlanner   │  │ • Broadcast/team         │    │   │
│  │  │ • Checkpoint    │  │ • ParallelExec  │  │ • Hive swarm             │    │   │
│  │  │ • Heartbeat     │  │ • GoalLoop      │  │ • Event bus (SSE)        │    │   │
│  │  │ • Watchdog      │  │ • LLM Critic    │  │ • Webhooks               │    │   │
│  │  └─────────────────┘  └─────────────────┘  └──────────────────────────┘    │   │
│  │                                                                             │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────────┐    │   │
│  │  │  Governance     │  │ Templates       │  │  Hiring System           │    │   │
│  │  │                 │  │                 │  │                          │    │   │
│  │  │ • Kill switch   │  │ • 20 archetypes │  │ • Hire manifests         │    │   │
│  │  │ • Circuit break │  │ • 10 md files   │  │ • Manifest registry      │    │   │
│  │  │ • Rate limits   │  │ • 6 team presets│  │ • Team batch hire        │    │   │
│  │  │ • Audit log     │  │ • Archetype     │  │ • Template-based hire    │    │   │
│  │  │ • Budget enforce│  │   Registry      │  │ • Security validation    │    │   │
│  │  │ • RBAC          │  │                 │  │ • CLI detection          │    │   │
│  │  └─────────────────┘  └─────────────────┘  └──────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                         │                                          │
│                                         ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │                           DATABASE (SQLite / PostgreSQL)                       │  │
│  │  agents, tasks, goals, memory_records, audit_log, approvals, pipelines, ...   │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         │ (Adapter calls)
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL LLM PROVIDERS                                     │
│                                                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐    │
│  │ Anthropic│  │  OpenAI  │  │  Ollama  │  │  Google  │  │ CLI Backends     │    │
│  │ (Claude) │  │ (GPT-4o) │  │ (local)  │  │ (Gemini) │  │ (claude, agy,    │    │
│  │          │  │          │  │          │  │          │  │  kiro, codex...)  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Wiring Status by Feature

### ✅ FULLY WIRED (Frontend ↔ Mock Server ↔ Works End-to-End)

| Feature | Frontend | Mock Server | Real Backend | Notes |
|---------|----------|-------------|--------------|-------|
| Agent CRUD (list/create/update/delete) | ✅ | ✅ + disk persist | ✅ | Full lifecycle |
| Hire Agent (Manual mode) | ✅ | ✅ | ✅ | All fields sent |
| Hire from Template (20 archetypes) | ✅ | ✅ | ✅ | Pre-fills form |
| Hire a Team (6 presets + custom) | ✅ | ✅ | ✅ | Batch creation |
| Import from Manifest (JSON) | ✅ | ✅ | ✅ | Security validated |
| Provider/Backend detection | ✅ | ✅ (real PATH check) | ✅ | Green dots for installed |
| Model list per provider | ✅ | ✅ | ✅ | Curated catalogs |
| Soul/Persona configuration | ✅ | ✅ | ✅ | 5 templates + custom |
| Team template presets | ✅ | ✅ | ✅ | 6 compositions |
| Agent persistence (survive restart) | ✅ | ✅ (JSON file) | ✅ (DB) | Won't lose agents |
| Agent Chat UI (drawer) | ✅ | ✅ (canned) | ✅ (real LLM) | See below |

### ⚠️ PARTIALLY WIRED (Backend exists, frontend uses mock)

| Feature | What Exists | What's Missing |
|---------|-------------|----------------|
| **Agent Chat (real LLM)** | Backend `chat.py` connects soul + adapter + LLM. Mock server returns canned text. | Frontend hits mock server, not real backend. Set `PROXY_API=true` to use real backend |
| **Activity Feed** | Backend queries AuditLog. Frontend has transforms. | Missing: enhanced fields (severity, latency), unified feed aggregation |
| **SSE Real-time Events** | Backend has full SSE `/events/stream`. Frontend simulates with setInterval. | Wire frontend EventSource to real SSE endpoint |
| **Agent Lifecycle (wake/pause)** | Backend has `/agents/{id}/wake` and `/pause`. Frontend has no buttons. | Add status action buttons to agent cards |
| **Memory System** | Backend: 3-temp store, 4-layer, BM25 search. Frontend: mock data. | Wire Memory page to real API |
| **Tools & Access Control** | Backend: ToolRegistry + grant/revoke. Frontend: mock data. | Wire Tools page |
| **Budget Enforcement** | Backend: per-agent budget check in TaskExecutor. Frontend: shows mock spend. | Wire Budgets page to real tracking |

### ❌ NOT WIRED (Backend fully built, no frontend connection)

| Feature | Backend Location | What It Does | Why Not Wired |
|---------|-----------------|-------------|---------------|
| **TaskExecutor** | `runtime/executor.py` | Budget check → retry → execute → cost record | Needs task assignment UI + real adapter call |
| **AgentLifecycleManager** | `runtime/lifecycle.py` | Full state machine (idle→ready→executing) | Needs orchestration trigger |
| **Orchestration/Router** | `orchestration/router.py` | Multi-factor agent scoring for task assignment | Needs task delegation UI |
| **TaskPlanner** | `orchestration/planner.py` | DAG decomposition of complex tasks | LLM planning logic stubbed |
| **ParallelExecutor** | `orchestration/parallel.py` | Concurrent task execution with semaphore | Needs orchestration pipeline |
| **GoalLoop** | `orchestration/goal_loop.py` | Autonomous iteration with judge | Needs goal-to-task pipeline |
| **A2A Communication** | `communication/a2a.py` | Agent-to-agent messaging | Needs inter-agent UI |
| **Hive Swarm** | `communication/hive_*.py` | Multi-agent coordination | Advanced orchestration feature |
| **Tool Execution** | `tools/executor.py` | Run MCP/API/script tools | Needs tool invocation UI |
| **Agent Enhancement** | `api/routes/hr.py` POST /enhance | Add capabilities post-hire | Not in UI |
| **Agent Training** | `api/routes/hr.py` POST /train | Start skill training | Not in UI |
| **Knowledge Base RAG** | `knowledge/` | Versioned docs + semantic search | KB page uses mock |
| **Pipeline Execution** | `runtime/` + adapters | Run multi-step workflows | Pipeline page uses mock |
| **Evolution System** | `evolution/` | Self-improvement proposals | Evolution page uses mock |
| **Meetings Minutes** | `meetings/` | Auto-generate minutes from agent discussions | Meetings page uses mock |

---

## Data Flow: Agent Chat (How It Works Now)

```
USER types message in chat drawer
         │
         ▼
Frontend: AgentChatDrawer → POST /api/v1/agents/{id}/chat { prompt: "..." }
         │
         ├─── If hitting MOCK SERVER (current default):
         │         │
         │         ▼
         │    Canned response: "${agent.name} acknowledges: '${prompt}'"
         │         │
         │         ▼
         │    Returns { message, history }
         │
         └─── If hitting REAL BACKEND (PROXY_API=true or direct):
                   │
                   ▼
              chat.py endpoint:
                   │
                   ├── 1. Load Agent from DB (role, capabilities, soul_description, adapter_type, model)
                   │
                   ├── 2. Build Soul object from agent.soul_description
                   │       • Parses "Personality: ...", "Communication: ...", "Values: ...", etc.
                   │       • Falls back to agent.name + role + capabilities
                   │
                   ├── 3. system_prompt_from_soul(soul) → structured prompt
                   │       "You are Atlas serving as a ceo.
                   │        Background: Visionary leader...
                   │        Personality: You are strategic, delegating, decisive.
                   │        Expertise: strategic_planning, delegation...
                   │        Constraints:
                   │        - Always provide clear acceptance criteria
                   │        - ..."
                   │
                   ├── 4. Resolve adapter: agent.adapter_type → AdapterRegistry key
                   │       "anthropic" → AnthropicAdapter
                   │       "openai" → OpenAIAdapter
                   │       "cli" → CLIAdapter (spawns claude/agy/kiro process)
                   │       "ollama" → OllamaAdapter (local inference)
                   │
                   ├── 5. adapter.create_session(agent_id, {api_key, model, system_prompt})
                   │
                   ├── 6. adapter.execute_task(session, task_id, {prompt, messages, system_prompt})
                   │       │
                   │       ▼
                   │    REAL API CALL to Anthropic/OpenAI/Ollama/CLI
                   │       │
                   │       ▼
                   │    LLM generates response in character
                   │
                   ├── 7. Store conversation in memory
                   │
                   └── 8. Return { message: agent_reply, history, model_used, tokens_used }
```

---

## How to Switch from Mock to Real

**Option A: Set `PROXY_API=true`** in the dashboard's `.env.local`:
```env
PROXY_API=true
NEXUS_API_URL=http://localhost:8000
```
Then start the real backend: `uvicorn nexus.main:app --port 8000`

**Option B: Point frontend directly at backend**:
```env
VITE_API_BASE_URL=http://localhost:8000
```
Requires backend CORS to allow the dashboard origin.

**Required env vars for real LLM calls:**
```env
ANTHROPIC_API_KEY=sk-ant-...    # For Claude adapter
OPENAI_API_KEY=sk-...           # For GPT adapter
```
If keys aren't set, the chat endpoint returns a helpful fallback message explaining what's needed.

---

## Component Count Summary

| Category | Count | Status |
|----------|-------|--------|
| Backend API routes | 50+ endpoints | All implemented |
| LLM Adapters | 10 providers | All implemented, make real API calls |
| Agent Archetypes | 20 role templates | Exposed via API + frontend |
| Team Templates | 6 compositions | Exposed via API + frontend |
| Soul Templates | 5 personality presets | Exposed via API + frontend |
| Database Models | 25+ tables | Schema complete |
| Frontend Pages | 25 pages | All render (most use mock data) |
| Frontend → Real Backend | ~8 features | Others still hit mock server |
| Memory layers | 4 (L0-L3) + 3 temps | Fully implemented, not wired to frontend |
| Orchestration modules | 7 | Fully implemented, not triggered from UI |
| Governance features | 6 | Middleware active, UI partially wired |
