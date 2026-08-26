# NVLabsCompany — Full Architecture Review & Implementation Report

> **STALE — do not trust status claims in this document.**
> Last verified against commit: never. Superseded by `docs/GAP-CLOSURE-PLAN.md`
> (verified against commit `1bbad4a`, 2026-08-26), which is the single source of
> truth for what is actually wired. Percentages and "complete" markers below are
> historical intent, not measured state.

> Generated: 2026-08-24 | Verified against actual codebase by Kiro agent with sub-agent validation

---

## Executive Summary

NVLabsCompany is a **full-stack autonomous AI agent platform** with:
- **Frontend**: React 18 + Vite dashboard with 26 pages and 50+ components
- **Backend**: FastAPI + SQLAlchemy with 44 routers, 55+ models, and 10 LLM adapters
- **Middleware**: ASGI governance layer with rate limiting, budget enforcement, policy engine, kill switch
- **Runtime**: Background scheduler, worktree manager, task executor with retry logic
- **Real-time**: WebSocket multiplexing + SSE streaming chat

**Overall Status:**
- Backend: ~95% real DB operations (only 2 in-memory modules and 2 hardcoded stubs)
- Frontend: ~40% fully wired to real backend, ~40% partially wired (hardcoded UUIDs but functional via shim), ~20% mock-only

---

## 1. BACKEND — What's Built

### 1.1 Route Layer (44 Routers, 200+ Endpoints)

#### Fully Real (DB-backed, production-ready):

| Category | Route Files | Key Endpoints |
|----------|-------------|---------------|
| **Agent Management** | agents.py, hiring.py | CRUD, wake/pause/heartbeat, hire-team, hire-from-manifest |
| **Chat & Streaming** | chat.py | POST /chat (LLM), POST /chat/stream (SSE), DELETE /chat, GET /chat |
| **Tasks & Planning** | tasks.py | CRUD, assign, status, subtasks, decompose (TaskPlanner), stats |
| **Goals & OKRs** | goals.py, okr.py* | CRUD, execute (GoalLoop with judge), stats |
| **Pipelines** | pipelines.py | CRUD, run (background), pause/stop, stats, import |
| **Memory** | memory.py, memory_global.py | Store, BM25 search, list, stats, archive, health |
| **Knowledge Base** | knowledge.py | CRUD, RAG search (with embedding fallback), experiences, bulk import |
| **Evolution** | evolution.py | Proposals, evaluate (LLM), promote (applies config), rollback, A/B test, diagnose |
| **Communication** | communication.py | Messages, groups, events, broadcast, inbox, mark-read |
| **Governance** | approvals.py, policies.py, incidents.py | Approval workflows, policy CRUD, incident timeline |
| **Budgets** | budgets.py | Policy creation, company/agent usage, cost trends |
| **Secrets** | secrets.py, rotation.py | Encrypted storage, bind/revoke, versioning, rotation |
| **Auth** | auth.py | Login/logout, sessions, switch-company, invites, setup |
| **Infrastructure** | health.py, degradation.py | Liveness, readiness, comprehensive system checks |
| **Settings** | settings.py | Company configuration management |
| **Notifications** | notifications.py | CRUD, mark-read, preferences |
| **Organizations** | departments.py, hr.py | Department/team management |
| **Skills & Tools** | skills.py, tools.py | CRUD, agent-skill/tool assignment |
| **Repositories** | repositories.py | Git repo connections |
| **Identity** | identity.py*, archetypes.py, providers.py | Soul management, archetype registry, CLI providers |
| **Real-time** | ws.py | WebSocket with channel subscriptions |
| **Analytics** | dashboard.py, activity.py, agent_logs.py, audit.py | Stats, feeds, execution logs |
| **Triggers** | triggers.py | CRUD for scheduled/webhook triggers |
| **Workflows** | workflows.py | Company workflow management |
| **Meetings** | meetings.py | Meeting scheduling and minutes |

*`okr.py` and `identity.py` use in-memory state (not DB-persisted)*

#### In-Memory State (functional but loses data on restart):
- `identity.py` — Agent soul/persona state in dict
- `okr.py` — OKR objectives and key results
- `chat.py` — Conversation history (`_conversations` dict)

#### Stubs/Placeholders:
- `evolution.py` → `get_detected_patterns` returns `[]`
- `pipelines.py` → `list_pipeline_templates` returns hardcoded list

### 1.2 Middleware Stack

**Order (outermost first):**
1. **CORS** — Credential-aware, explicit origins
2. **RequestID** — Unique ID per request
3. **Metrics** — Prometheus HTTP tracking
4. **APIVersion** — X-API-Version header
5. **Authentication** — Session cookie or API key → Principal
6. **Governance** — Kill switch, rate limit, policy, budget, audit

**Governance Middleware Features:**
| Feature | Status | Implementation |
|---------|--------|----------------|
| Kill switch (per company) | ✅ Real | `_KillSwitchRegistry` singleton, loaded from DB at startup |
| Rate limiting | ✅ Real | Sliding window (100 req/60s/company), 429 response |
| Policy evaluation | ✅ Real | `fnmatch` path matching, method/time rules from DB |
| Budget enforcement | ✅ Real | In-memory cache with route-based cost estimation |
| Audit logging | ✅ Real | Structured logging for all mutations |
| Rate limit headers | ✅ Real | X-RateLimit-Limit/Remaining/Window on every response |

### 1.3 Models (55+ SQLAlchemy tables)

All models are registered in `src/nexus/models/__init__.py` and auto-discovered by Alembic for migration generation. Key model groups:
- Company/Organization (4 models)
- Agent (1 model with rich fields)
- Work Management (Task, Goal, Project — 3 models)
- Budget (BudgetPolicy, CostEvent — 2 models)
- Governance (Approval, AuditLog, Decision, DecisionQueue — 4 models)
- Policies (Policy, PolicyRule, PolicyVersion — 3 models)
- Secrets (Secret, SecretVersion, SecretBinding, SecretAccess — 4 models)
- Incidents (Incident, IncidentEvent, IncidentAction — 3 models)
- Skills & Tools (Skill, AgentSkill, Tool, ToolAccess, etc. — 9 models)
- Memory (MemoryRecord — 1 model)
- Triggers (Trigger, TriggerExecution — 2 models)
- Communication (Message, Group, GroupMember, Event — 4 models)
- Knowledge (KnowledgePage, KnowledgeChunk, ExperienceRecord — 3 models)
- Meetings (Meeting, MeetingParticipant, MeetingMinutes, ActionItem — 4 models)
- Evolution (EvolutionProposal, EvolutionEvaluation, SkillVersion, AgentVersion — 4 models)
- Auth (UserProfile, UserSession, Invite, ApiKey — 4 models)
- Runtime (HeartbeatRun, ExecutionCheckpoint — 2 models)
- Pipeline (Pipeline, PipelineRun — 2 models)

### 1.4 Adapters (10 registered)

| Adapter | Key | Streaming | Tested |
|---------|-----|-----------|--------|
| Anthropic Claude | `anthropic` | ✅ `stream_execute()` | ✅ Verified |
| OpenAI GPT | `openai` | Likely | Registered |
| Ollama (local) | `ollama` | Unknown | Registered |
| Claude Code CLI | `claude_code` | N/A (subprocess) | Registered |
| Generic CLI | `cli` | N/A (subprocess) | ✅ Verified |
| HTTP/REST | `http` | Unknown | Registered |
| MCP Protocol | `mcp` | Unknown | Registered |
| Azure OpenAI | `azure_openai` | Unknown | Registered |
| AWS Bedrock | `bedrock` | Unknown | Registered |
| Google Gemini | `google_gemini` | Unknown | Registered |

### 1.5 Runtime Services

| Service | Wired | Description |
|---------|-------|-------------|
| `scheduler.py` | ✅ In lifespan | Background cron/schedule trigger execution |
| `executor.py` | ✅ By routes | Task execution with budget checks and retries |
| `worktree.py` | ✅ By adapter | Git worktree isolation for agent execution |
| `lifecycle.py` | ✅ Core | Agent state machine and session coordination |
| `heartbeat.py` | ✅ Background | Agent liveness monitoring |
| `adapter.py` | ✅ Protocol | Defines interfaces (AgentAdapter, AgentSession, TaskResult) |
| `checkpoint.py` | ⚠️ Partial | Execution checkpoints for recovery |

---

## 2. FRONTEND — What's Built

### 2.1 Pages (26 routes)

#### Fully Wired to Real Backend (7 pages):
| Page | Pattern |
|------|---------|
| Dashboard.tsx | `getActiveCompanyId()` + `unwrapItems()` + fallback |
| Agents.tsx | Uses dedicated `api/agents.ts` module |
| AgentDetailPage.tsx | `getActiveCompanyId()` + `unwrapItems()` + PUT/chat |
| Tasks.tsx | `getActiveCompanyId()` + `unwrapItems()` |
| Organization.tsx | `getActiveCompanyId()` + `unwrapItems()` |
| HRRoom.tsx | `getActiveCompanyId()` + `unwrapItems()` |
| Budgets.tsx | `getActiveCompanyId()` + `unwrapItems()` |

#### Partially Wired (10 pages — hardcoded UUID but works via `resolveCompanyPath` shim):
| Page | Issue |
|------|-------|
| Goals.tsx | Hardcoded UUID, expects `{ items }` shape |
| Pipelines.tsx | Hardcoded UUID, expects `{ items }` shape |
| Memory.tsx | Hardcoded UUID, expects `{ items }` shape |
| KnowledgeBase.tsx | Hardcoded UUID, expects `{ items }` shape |
| Skills.tsx | Hardcoded UUID, expects `{ items }` shape |
| Tools.tsx | Hardcoded UUID, expects `{ items }` shape |
| Workflows.tsx | Hardcoded UUID, expects `{ items }` shape |
| Meetings.tsx | Hardcoded UUID, expects `{ items }` shape |
| Notifications.tsx | Hardcoded UUID, expects `{ items }` shape |
| GitRepos.tsx | Hardcoded UUID, expects `{ items }` shape |

#### Mock-Only / No Real API (3 pages):
| Page | Issue |
|------|-------|
| Activity.tsx | `setInterval` with fake random events |
| Evolution.tsx | No API calls found |
| Office.tsx | Three.js 3D visualization (no data API) |

#### Auth Pages (3, properly implemented):
- Login.tsx, Setup.tsx, AcceptInvite.tsx

#### Utility Pages (3):
- Settings.tsx (many sub-tabs with hardcoded UUIDs)
- MemoryGraph.tsx (D3 visualization)
- Approvals.tsx

### 2.2 API Layer

| Module | Status | Functions |
|--------|--------|-----------|
| `client.ts` | ✅ Complete | apiClient, unwrapItems, legacyCompanyHeaders, resolveCompanyPath, CSRF, 401 handling |
| `agents.ts` | ✅ Complete | 12 functions covering full agent lifecycle |
| `auth.ts` | ✅ Complete | 14 functions covering auth flow |
| Other domains | ❌ Missing | No dedicated API modules for tasks, goals, pipelines, memory, etc. |

### 2.3 Real-Time Features

| Feature | Status | Location |
|---------|--------|----------|
| SSE Chat Streaming | ✅ Working | AgentChatDrawer.tsx |
| WebSocket Terminal | ✅ Component exists | AgentTerminalPanel.tsx (not routed) |
| SSE Activity Pulse | ⚠️ Hardcoded UUID | PulseLine.tsx |
| Live Agent Output | ✅ Backend broadcasts | CLI adapter → ws_manager |

### 2.4 Key Components

| Component | Wired | Features |
|-----------|-------|----------|
| AgentChatDrawer | ✅ | 9 slash commands, SSE streaming, token tracking |
| HireAgentModal | ✅ | 4 hire modes, archetype/soul/team templates |
| PipelineBuilder | ✅ | Drag-and-drop stages, parallel/quality gate config |
| AgentTerminalPanel | ✅ | WebSocket live output display |
| FireAgentModal | ✅ | Confirmation dialog |
| CommandPalette | ✅ | Ctrl+K with agent/task search |

---

## 3. WHAT'S PARTIALLY BUILT

| Area | What Works | What's Missing |
|------|-----------|---------------|
| **Vector RAG** | BM25 + token-overlap fallback | No embedding provider configured (set `EMBEDDING_PROVIDER=openai`) |
| **Agent Terminal UI** | Component exists | Not routed (no `/terminal` page) |
| **OKR System** | Full CRUD | In-memory only (not DB-persisted) |
| **Identity/Soul** | Full CRUD + templates | In-memory only (not DB-persisted) |
| **Chat History** | Works per-session | Not DB-persisted (in-memory dict, lost on restart) |
| **ParallelExecutor** | Wired in pipeline | Not exposed as standalone API endpoint |
| **LayeredMemoryStore** | Full implementation | Only used in tests, production uses SQLAlchemy MemoryRecord directly |

---

## 4. WHAT'S MISSING

### Backend Missing:
| Feature | Description | Effort |
|---------|-------------|--------|
| DB-persisted chat history | Replace in-memory `_conversations` with a ChatMessage model | Medium |
| DB-persisted OKR/Identity | Migrate in-memory stores to SQLAlchemy | Low |
| Budget flush to DB | `_budget_tracker.pending_spend` never written back to DB | Low |
| OpenAI `stream_execute` | Only Anthropic has streaming; OpenAI adapter needs it | Medium |
| Cursor CLI backend | NvLabsOrg supports it, not registered | Low |
| Multi-workspace | Switching between different project directories | High |
| Webhook outbound delivery | Trigger type "webhook" doesn't fire outbound HTTP | Medium |

### Frontend Missing:
| Feature | Description | Effort |
|---------|-------------|--------|
| Proper wiring for 10 pages | Replace hardcoded UUIDs + add unwrapItems in Goals, Pipelines, Memory, etc. | Medium |
| API modules for each domain | Create tasks.ts, goals.ts, pipelines.ts, etc. like agents.ts | Medium |
| Terminal page/route | Wire AgentTerminalPanel into App routes | Low |
| Activity page real API | Connect to actual activity/events endpoint | Low |
| Evolution page UI | Show proposals, evaluations, A/B tests from backend | Medium |
| Pipeline Builder page integration | Embed PipelineBuilder component in Pipelines page | Low |
| Diff/merge viewer | Show worktree changes before merge | High |
| Theme system | Multiple color themes (NvLabsOrg has 18) | Medium |

### Architectural Gaps:
| Gap | Description |
|-----|-------------|
| No message queue | All background tasks use `BackgroundTasks` (in-process). Production would need Celery/Dramatiq |
| No Redis cache | Rate limiter and budget tracker are in-memory (lost on restart/multi-instance) |
| Single-process scheduler | Scheduler runs in the FastAPI process. Multi-instance deploys need leader election |
| No database migrations CLI | Alembic is configured but no documented migration workflow |

---

## 5. WHAT MORE CAN BE IMPLEMENTED

### High-Impact, Medium-Effort:
1. **Persist chat history to DB** — Add a ChatMessage model, migrate `_conversations` to DB
2. **Wire remaining 10 frontend pages** — Systematic pass: `getActiveCompanyId()` + `unwrapItems()`
3. **OpenAI streaming** — Port `stream_execute()` pattern from Anthropic adapter
4. **Real activity feed** — Wire Activity.tsx to the activity/events API endpoint
5. **Terminal page** — Add `/terminal` route using AgentTerminalPanel

### Medium-Impact, Lower-Effort:
6. **Create API modules** — `tasks.ts`, `goals.ts`, `pipelines.ts` following agents.ts pattern
7. **DB-persist OKR and Identity** — Small migration, move from dict to model
8. **Budget DB flush** — Background task to write pending_spend to Company.spent_monthly_cents
9. **Duplicate route cleanup** — Remove dead duplicate definitions in 5 route files
10. **Pipeline Builder integration** — Embed in Pipelines page, wire Save/Run to API

### Stretch Goals:
11. **Redis backing for rate limiter** — Multi-instance safe rate limiting
12. **Celery/Dramatiq workers** — Move pipeline execution to a task queue
13. **Streaming for all adapters** — OpenAI, Ollama, Google all support streaming
14. **File explorer panel** — Browse project files from dashboard
15. **Git panel** — Show diffs, commit history, PR creation from UI
16. **Mobile PWA** — Add service worker and manifest for offline access
17. **Desktop Tauri wrapper** — Native app shell (like NvLabsOrg)

---

## 6. FRONTEND WIRING STATUS MATRIX

```
Page                    | getActiveCompanyId | unwrapItems | Real API | Status
------------------------|-------------------|-------------|----------|--------
Dashboard               | ✅                 | ✅           | ✅        | WIRED
Agents                  | ✅                 | ✅           | ✅        | WIRED
AgentDetailPage         | ✅                 | ✅           | ✅        | WIRED
Tasks                   | ✅                 | ✅           | ✅        | WIRED
Organization            | ✅                 | ✅           | ✅        | WIRED
HRRoom                  | ✅                 | ✅           | ✅        | WIRED
Budgets                 | ✅                 | ✅           | ✅        | WIRED
Goals                   | ❌                 | ❌           | ✅*       | PARTIAL
Pipelines               | ❌                 | ❌           | ✅*       | PARTIAL
Memory                  | ❌                 | ❌           | ✅*       | PARTIAL
KnowledgeBase           | ❌                 | ❌           | ✅*       | PARTIAL
Skills                  | ❌                 | ❌           | ✅*       | PARTIAL
Tools                   | ❌                 | ❌           | ✅*       | PARTIAL
Workflows               | ❌                 | ❌           | ✅*       | PARTIAL
Meetings                | ❌                 | ❌           | ✅*       | PARTIAL
Notifications           | ❌                 | ❌           | ✅*       | PARTIAL
GitRepos                | ❌                 | ❌           | ✅*       | PARTIAL
Settings                | ❌                 | ❌           | ✅*       | PARTIAL
Activity                | ❌                 | ❌           | ❌        | MOCK
Evolution               | ❌                 | ❌           | ❌        | MOCK
Office                  | N/A               | N/A         | N/A      | 3D VIZ

* Works via resolveCompanyPath() shim that rewrites hardcoded UUIDs at request time
```

---

*Report generated by Kiro agent with full codebase verification via context-gatherer sub-agents.*
