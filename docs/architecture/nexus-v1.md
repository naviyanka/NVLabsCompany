# NEXUS v1 Architecture

## Autonomous AI Company Operating System

NEXUS transforms multiple open-source agent frameworks into a unified system that behaves like a real autonomous AI company, not a chatbot or multi-agent demo. It combines organizational structure, durable agent execution, persistent identity, proactive behavior, and self-evolution into a single coherent platform.

---

## 1. Recommended Base

### Primary Foundation: Clawith + Paperclip (Dual-Base Strategy)

**Execution Layer Base: Clawith**
- Python FastAPI backend (production-grade async)
- LangGraph durable execution engine with PostgreSQL checkpoints
- Persistent agent identity model (soul.md + memory.md)
- Multi-tenant architecture with RBAC
- Aware system for proactive autonomous behavior
- A2A protocol for external agent communication
- SQLAlchemy async + SQLModel + Alembic (mature data layer)
- Apache 2.0 license (enterprise-friendly)

**Organization Layer Base: Paperclip (concepts, not code)**
- Company/organization hierarchy model (adapted to Python)
- Budget and cost tracking system
- Governance framework (approvals, decisions, queues)
- Agent lifecycle management concepts
- Multi-company isolation patterns
- Tool access governance

### Rationale

Clawith provides the strongest execution foundation because:
1. Already Python/FastAPI (no language migration needed)
2. LangGraph StateGraph is production-proven for durable agent execution
3. Persistent identity (soul.md) is essential for autonomous company agents
4. 54-file runtime engine is the most mature execution layer among all repos
5. Built-in trigger system enables proactive (not just reactive) agents
6. Multi-tenant architecture supports company isolation out of the box

Paperclip provides the best organizational model because:
1. 116-table schema covers every company concept (budgets, goals, teams, projects)
2. Governance system (approvals, decisions, cost control) is unmatched
3. Agent lifecycle (hire, configure, monitor, govern) maps to real company operations
4. However, TypeScript requires porting - we take concepts and schemas, not code

### Technology Stack Decision

| Layer | Technology | Source |
|-------|-----------|--------|
| Language | Python 3.12+ | Clawith, PraisonAI, Cronus |
| HTTP Framework | FastAPI (async) | Clawith |
| Database | PostgreSQL + SQLAlchemy async | Clawith |
| ORM | SQLModel + Alembic | Clawith |
| Execution Engine | LangGraph | Clawith |
| Checkpointing | PostgreSQL (langgraph-checkpoint-postgres) | Clawith |
| Frontend | React + Vite + Tailwind | All projects |
| MCP | Custom MCP server | PraisonAI + Cronus |
| Search | BM25 + Vector (hybrid) | Cronus + PraisonAI |
| Deployment | Docker + Kubernetes (Helm) | Clawith |

---

## 2. Components to Reuse (Use As-Is or Near As-Is)

These components require minimal modification and can be integrated directly:

### From Clawith
| Component | Files | Why Reuse |
|-----------|-------|-----------|
| LangGraph execution engine | `backend/app/services/agent_runtime/` (54 files) | Production-grade, durable, checkpoint-based |
| Persistent agent identity | soul.md + memory.md pattern | Essential for autonomous agents |
| Proactive triggers (Aware) | `trigger.py`, `trigger_execution.py` | 6 trigger types ready for autonomy |
| A2A protocol | `a2a_runtime.py`, `a2a_completion.py` | Industry-standard agent communication |
| Group conversations | `group_runtime_tools.py`, `group_handoff.py` | Multi-agent collaboration |
| Channel integrations | 46 API route files (Slack, Discord, etc.) | Comprehensive external connectivity |
| Audit logging | `audit.py`, `activity_logger.py` | Enterprise compliance |
| Database stack | SQLAlchemy async + SQLModel + Alembic | Mature, proven stack |
| Deployment | Docker Compose + Helm charts | Production-ready |
| Cycle guard | `cycle_guard.py` | Infinite loop prevention |

### From Cronus AI-Company
| Component | Files | Why Reuse |
|-----------|-------|-----------|
| Three-temperature memory | `src/aiteam/memory/store.py` | Clean hot/warm/cold architecture |
| BM25 retrieval | `retriever.py` | Simple, effective, no external deps |
| Execution loop | `src/aiteam/loop/` (7 files) | Watchdog, auto-assign, completion verify |
| Meeting system | `src/aiteam/meeting/` | 8 structured meeting templates |
| Content safety | `memory/content_safety.py` | Pre-storage content filtering |
| Progressive tool loading | `toolsets.py` | Context-aware tool availability |

### From PraisonAI
| Component | Files | Why Reuse |
|-----------|-------|-----------|
| Guardrails | `guardrails/` (4 types + chain) | Comprehensive validation system |
| Doom-loop detection | `goal/loop.py` + ExecutionConfig | Critical safety mechanism |
| MCP client | `mcp/` (16 files) | Full MCP protocol support |
| Sandbox execution | `sandbox/` | Docker/E2B/Modal isolation |
| Event bus | `bus/bus.py` | Decoupled inter-agent events |

---

## 3. Components to Adapt (Modify for NEXUS)

These require significant refactoring but provide proven patterns:

### Organizational Model (from Paperclip, ported to Python)
**What to adapt:**
- Company hierarchy schema (116 tables -> ~60 NEXUS-relevant tables in SQLModel)
- Budget policy enforcement logic
- Approval/decision queue system
- Agent lifecycle management (hire, configure, wake, monitor)
- Goal alignment system
- Cost event tracking

**Adaptation needed:**
- TypeScript Drizzle schemas -> Python SQLModel definitions
- Express middleware -> FastAPI dependency injection
- PGlite embedded mode -> PostgreSQL-only (Clawith pattern)
- Zod validators -> Pydantic models
- Remove UI-specific routes; keep API logic

### Workflow Engine (from OpenCompany)
**What to adapt:**
- Conductor-style `workflow_decide()` pattern
- Task lifecycle (PENDING -> SCHEDULED -> RUNNING -> COMPLETED)
- Fork/Join parallel execution
- Dead letter queue and retry policies
- Condition-based routing

**Adaptation needed:**
- Remove Temporal dependency (use LangGraph for durability instead)
- Port from standalone execution to NEXUS agent runtime integration
- Adapt node-based tool system to NEXUS tool registry
- Remove n8n-style visual canvas dependencies (build NEXUS-specific UI)

### Agent SDK (from PraisonAI)
**What to adapt:**
- 5-layer agent stack concept (Prompt/Context/Harness/Loop/Graph)
- Orchestration patterns (route/parallel/loop/repeat)
- Knowledge/RAG pipeline (chunking, indexing, retrieval, reranking)
- Memory adapter system
- Hook lifecycle system

**Adaptation needed:**
- Simplify mixin architecture (too many mixins in current design)
- Replace file-based persistence with PostgreSQL
- Integrate with LangGraph execution (not standalone loops)
- Remove thread-safety complexity (use async-first design)
- Connect to NEXUS identity and governance systems

### Role Specialization (from MetaGPT)
**What to adapt:**
- Role base class with action subscriptions
- Predefined roles (ProductManager, Architect, Engineer, QA)
- Publish/subscribe message routing with tag filtering
- SOP-driven collaboration sequences
- Team composition patterns

**Adaptation needed:**
- Pydantic models stay (compatible with NEXUS stack)
- Replace simple Environment with NEXUS agent runtime
- Add persistence (MetaGPT is in-memory only)
- Extend beyond software development roles
- Integrate with NEXUS approval/governance gates

### Context Management (from OpenCompany RFC-0002)
**What to adapt:**
- Separation of Context (execution journal) from Memory (durable facts)
- Thread isolation (session/task/execution)
- Compaction algorithm for long conversations
- Atomic mutation with optimistic concurrency

**Adaptation needed:**
- Port from OpenCompany's custom DB to NEXUS PostgreSQL
- Integrate with LangGraph checkpoint system
- Connect to Cronus memory store (3-temperature)

---

## 4. Components to Build (New Development)

These capabilities do not exist in any source repo and must be built:

### Self-Evolution Engine (NEXUS Unique Layer)

| Component | Description | Complexity |
|-----------|-------------|-----------|
| **Self-Assessment Service** | Agents evaluate their own performance using metrics, peer review, and outcome analysis | Very High |
| **Skill Acquisition System** | Agents learn new capabilities from successful task completions, adapting prompts and tool usage | Very High |
| **Architecture Evolution** | System proposes and applies structural changes to itself based on performance patterns | Very High |
| **Continuous Improvement Loop** | Automated identification of bottlenecks, experiments with solutions, and rollout of improvements | High |
| **Knowledge Synthesis** | Cross-agent learning where one agent's discoveries become available to the team | High |

### Unified NEXUS API Gateway

| Component | Description | Complexity |
|-----------|-------------|-----------|
| **Unified REST API** | Single coherent API surface combining company management, agent operations, and workflow control | Medium |
| **GraphQL Layer** (optional) | Query flexibility for dashboard and external integrations | Medium |
| **Rate Limiting + Quotas** | Per-company, per-agent rate limiting tied to budget system | Medium |
| **API Versioning** | Stable public API with evolution path | Low |

### NEXUS Dashboard

| Component | Description | Complexity |
|-----------|-------------|-----------|
| **Company Overview** | Real-time view of all agents, projects, budgets, and health | Medium |
| **Agent Management UI** | Hire, configure, monitor, govern agents through visual interface | Medium |
| **Workflow Designer** | Visual workflow builder (simpler than OpenCompany canvas, focused on agent orchestration) | High |
| **Decision Center** | Human review queue for approval gates | Medium |
| **Self-Evolution Monitor** | Visualize system evolution decisions and their outcomes | High |

### Inter-Company Federation (Future)

| Component | Description | Complexity |
|-----------|-------------|-----------|
| **Company-to-Company Protocol** | Multiple NEXUS instances collaborating as business partners | Very High |
| **Shared Service Registry** | Discover and consume services from federated companies | High |
| **Cross-Company Governance** | Contracts, SLAs, and trust policies between entities | Very High |

---

## 5. Dependencies

### Runtime Dependencies

| Dependency | Version | Purpose | Source |
|-----------|---------|---------|--------|
| Python | >= 3.12 | Primary language | Clawith, Cronus |
| FastAPI | >= 0.115 | HTTP framework | Clawith, Cronus |
| SQLAlchemy[asyncio] | >= 2.0 | Database ORM | Clawith |
| SQLModel | latest | Data models | Clawith |
| LangGraph | latest | Durable execution | Clawith |
| langgraph-checkpoint-postgres | latest | Checkpoint persistence | Clawith |
| Pydantic | v2 | Data validation | All |
| Alembic | latest | DB migrations | Clawith |
| uvicorn[standard] | >= 0.32 | ASGI server | Clawith, Cronus |
| PostgreSQL | >= 15 | Primary database | Clawith |
| Redis | >= 7 | Cache, execution state | OpenCompany |

### Agent/AI Dependencies

| Dependency | Purpose | Source |
|-----------|---------|--------|
| openai | LLM client (OpenAI-compatible) | PraisonAI |
| anthropic | Claude models | Clawith |
| google-genai | Gemini models | OpenCompany |
| MCP SDK | Model Context Protocol | PraisonAI, Cronus |
| chromadb / pgvector | Vector search | PraisonAI |
| tiktoken | Token counting | MetaGPT |

### Frontend Dependencies

| Dependency | Purpose | Source |
|-----------|---------|--------|
| React 19 | UI framework | All |
| Vite | Build tool | All |
| Tailwind CSS | Styling | Clawith |
| React Flow | Workflow canvas (if adopted) | OpenCompany |

### Infrastructure Dependencies

| Dependency | Purpose |
|-----------|---------|
| Docker | Containerization |
| Kubernetes | Orchestration (optional, via Helm) |
| Nginx/Traefik | Reverse proxy |
| Prometheus/Grafana | Monitoring (optional) |

---

## 6. Risks

### Technical Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **LangGraph version lock-in** | High | Abstract execution behind interface; monitor LangGraph stability and alternatives |
| **TypeScript-to-Python schema porting** | Medium | Incremental migration; automated schema generation tools; comprehensive test coverage |
| **Multi-source integration complexity** | High | Phase-based integration; each source has clear boundaries; integration test suite |
| **Self-evolution safety** | Critical | Sandboxed evolution proposals; human approval gates for structural changes; rollback capability |
| **Performance at scale** | Medium | PostgreSQL proven for 100+ concurrent agents; Redis for hot path; profile early |
| **MCP protocol immaturity** | Medium | Version-pin MCP; maintain backward compatibility layer; fallback to direct tool calls |

### Organizational Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **Scope creep from 6 repos** | High | Strict component matrix adherence; say no to unplanned integrations |
| **Upstream divergence** | Medium | Fork critical components; monitor but do not track upstream changes |
| **License incompatibility** | Low | All MIT + one Apache 2.0; no copyleft; document all attributions |
| **Knowledge concentration** | Medium | Document architecture decisions; automated architecture tests |

### Operational Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| **Database migration complexity** | Medium | Alembic for managed migrations; blue-green deployment support |
| **Multi-tenant data isolation** | High | Row-level security; tenant-scoped queries everywhere; penetration testing |
| **Agent cost runaway** | High | Budget enforcement at multiple levels (org, project, agent, execution) |
| **Doom-loop in production** | Medium | PraisonAI doom-loop detection + Clawith cycle guard + NEXUS circuit breakers |

---

## 7. Phase 1 Implementation Plan

### Phase 1 Goal
Stand up the NEXUS core: a working system where agents can be created with persistent identity, execute tasks durably, operate within an organizational structure, and be governed by approval gates and budgets.

### Phase 1 Timeline: 8-12 Weeks

---

#### Week 1-2: Foundation

**Objective:** Establish the base project structure and core infrastructure.

| Task | Source | Deliverable |
|------|--------|------------|
| Initialize NEXUS Python project (FastAPI + SQLModel + Alembic) | Clawith structure | Working empty server |
| Port Clawith database stack (SQLAlchemy async, migrations) | Clawith | DB connection + migration system |
| Define NEXUS company/org schema (from Paperclip, in SQLModel) | Paperclip (adapted) | 20-30 core tables |
| Set up Docker Compose development environment | Clawith | One-command dev setup |
| Establish CI pipeline (lint, type-check, test) | New | Quality gates |

---

#### Week 3-4: Agent Runtime

**Objective:** Port and integrate the durable agent execution engine.

| Task | Source | Deliverable |
|------|--------|------------|
| Port LangGraph execution engine | Clawith (reuse) | Durable agent runs with checkpoints |
| Implement persistent agent identity (soul.md + memory.md) | Clawith (reuse) | Agents survive restarts |
| Port agent lifecycle (create, configure, wake) | Paperclip (adapted) | Agent management API |
| Integrate 3-temperature memory store | Cronus (reuse) | Hot/warm/cold memory |
| Add cycle guard + doom-loop detection | Clawith + PraisonAI | Safety mechanisms |

---

#### Week 5-6: Orchestration + Tools

**Objective:** Enable multi-agent workflows and tool execution.

| Task | Source | Deliverable |
|------|--------|------------|
| Implement Aware trigger system (cron, webhook, on_message) | Clawith (reuse) | Proactive agent behavior |
| Port execution loop (watchdog, auto-assign) | Cronus (reuse) | Autonomous task management |
| Integrate MCP tool protocol | PraisonAI (reuse) | Standard tool interface |
| Implement basic workflow patterns (sequential, parallel) | PraisonAI (adapted) | Multi-agent orchestration |
| Add LLM provider abstraction (OpenAI, Anthropic, Gemini) | OpenCompany (wrapped) | Multi-model support |

---

#### Week 7-8: Governance + Safety

**Objective:** Add organizational controls that make NEXUS enterprise-ready.

| Task | Source | Deliverable |
|------|--------|------------|
| Port approval/decision queue system | Paperclip (adapted) | Human-in-the-loop gates |
| Implement budget enforcement | Paperclip + PraisonAI (merged) | Cost control at org/agent level |
| Add guardrails system | PraisonAI (reuse) | Output validation |
| Implement RBAC with tenant isolation | Clawith (reuse) | Security model |
| Add audit trail | Clawith (reuse) | Compliance logging |

---

#### Week 9-10: Communication + Knowledge

**Objective:** Enable agents to communicate, learn, and share knowledge.

| Task | Source | Deliverable |
|------|--------|------------|
| Implement A2A protocol | Clawith (reuse) | Agent-to-agent communication |
| Add group conversation support | Clawith (reuse) | Multi-agent collaboration |
| Port Plaza knowledge feed | Clawith (reuse) | Organizational knowledge |
| Implement BM25 + vector hybrid search | Cronus + PraisonAI | Knowledge retrieval |
| Add meeting system | Cronus (reuse) | Structured coordination |

---

#### Week 11-12: Dashboard + Integration Testing

**Objective:** Provide visibility into the system and validate end-to-end.

| Task | Source | Deliverable |
|------|--------|------------|
| Build minimal React dashboard (agent list, status, health) | New (Clawith patterns) | Visual management |
| End-to-end integration tests | New | System validation |
| Performance profiling and optimization | New | Baseline metrics |
| Documentation (API, deployment, architecture) | New | Operator guide |
| Demo scenario: autonomous dev team completing a project | New | Proof of concept |

---

### Phase 1 Exit Criteria

1. NEXUS server boots with PostgreSQL, runs migrations, serves API
2. Agents can be created with persistent identity (soul + memory)
3. Agent tasks execute durably (survive server restart via LangGraph checkpoints)
4. Proactive triggers fire agents on schedule/webhook/event
5. Approval gates block agent actions until human/auto-approval
6. Budget limits prevent runaway cost
7. Multiple agents can collaborate in a group conversation
8. MCP tools are discoverable and executable
9. Basic dashboard shows system health and agent status
10. Docker Compose brings up entire system with one command

---

### Phase 2 Preview (Post-Phase 1)

- Self-evolution engine (the differentiator)
- Advanced workflow designer (visual canvas)
- Skill marketplace
- Inter-company federation
- Production scaling (horizontal agent execution)
- Advanced analytics and reporting
- Natural language system administration
