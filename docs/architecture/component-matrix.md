# NEXUS Component Matrix

## Overview

This document maps each NEXUS system component to its source project(s), identifying the existing implementation, recommended reuse strategy, integration difficulty, and rewrite requirements.

---

## Reuse Strategy Legend

| Strategy | Meaning |
|----------|---------|
| **Reuse** | Use as-is with minimal modification |
| **Adapt** | Modify existing implementation to fit NEXUS architecture |
| **Wrap** | Create NEXUS interface layer around existing code |
| **Merge** | Combine implementations from multiple sources |
| **Build** | Implement from scratch (no suitable source) |
| **Skip** | Do not use this implementation |

## Integration Difficulty Legend

| Level | Meaning |
|-------|---------|
| **Low** | Drop-in with configuration changes only |
| **Medium** | Interface adaptation + some refactoring needed |
| **High** | Significant restructuring or rewrite of integration layer |
| **Very High** | Fundamental architecture changes required |

---

## Component Mapping

### Company / Organization Layer

| NEXUS Component | Source Project | Existing Implementation | Reuse Strategy | Integration Difficulty | Rewrite Requirement |
|-----------------|---------------|------------------------|----------------|----------------------|-------------------|
| Multi-Company Model | Paperclip | `packages/db/src/schema/companies.ts` + `company_memberships.ts` | **Adapt** | Medium | Port schema to Python/SQLAlchemy; remove TypeScript-specific patterns |
| Organization Chart | Paperclip | `server/src/routes/org-chart-svg.ts` + team memberships | **Adapt** | Medium | Extract org hierarchy logic; rebuild in Python |
| Budget System | Paperclip | `budget_policies.ts`, `budget_incidents.ts`, `cost_events.ts`, `finance_events.ts` | **Adapt** | Medium | Port budget enforcement logic; integrate with agent execution costs |
| RBAC / Permissions | Paperclip + Clawith | Paperclip: `principal_permission_grants.ts`, Clawith: RBAC in services | **Merge** | High | Combine Paperclip's granular permissions with Clawith's tenant isolation |
| Governance (Approvals) | Paperclip | `approvals.ts`, `decisions.ts`, `decision_queues.ts`, `decision_training_examples.ts` | **Adapt** | Medium | Port decision queue system; add ML-based auto-approval |
| Multi-Tenancy | Clawith | `tenant.py`, `tenant_setting.py`, multi-tenant services | **Reuse** | Low | Already Python/SQLModel; integrate with NEXUS auth |
| OKR / Goals | Paperclip + Clawith | Paperclip: `goals.ts`, `project_goals.ts`; Clawith: `okr.py` | **Merge** | Medium | Combine goal alignment with OKR tracking |

### Agent Runtime Layer

| NEXUS Component | Source Project | Existing Implementation | Reuse Strategy | Integration Difficulty | Rewrite Requirement |
|-----------------|---------------|------------------------|----------------|----------------------|-------------------|
| Agent SDK Core | PraisonAI | `src/praisonai-agents/praisonaiagents/agent/agent.py` (mixin architecture) | **Adapt** | High | Simplify mixin architecture; integrate NEXUS identity model |
| Agent Execution Engine | Clawith | `backend/app/services/agent_runtime/` (54 files, LangGraph StateGraph) | **Reuse** | Medium | Production-grade durable execution; add NEXUS-specific nodes |
| Agent Lifecycle | Paperclip | `agents.ts`, `agent_runtime_state.ts`, `agent_wakeup_requests.ts` | **Adapt** | Medium | Port hire/configure/wake lifecycle to Python |
| Agent Identity | Clawith | soul.md + memory.md + workspace pattern | **Reuse** | Low | Excellent pattern for persistent autonomous agents |
| Agent Templates | Cronus AI-Company | 25 agent templates in `src/aiteam/` | **Adapt** | Low | Extend templates to NEXUS role system |
| Agent Heartbeat | Paperclip | `heartbeat_runs.ts`, `heartbeat_run_events.ts`, watchdog decisions | **Adapt** | Medium | Port monitoring logic; integrate with LangGraph checkpoints |
| LLM Provider Abstraction | OpenCompany | `server/services/llm/` + 13 provider nodes in `server/nodes/model/` | **Wrap** | Medium | Wrap existing provider implementations behind NEXUS interface |

### Workflow / Orchestration Layer

| NEXUS Component | Source Project | Existing Implementation | Reuse Strategy | Integration Difficulty | Rewrite Requirement |
|-----------------|---------------|------------------------|----------------|----------------------|-------------------|
| Workflow Engine | OpenCompany | `server/services/execution/` (Conductor pattern + Temporal) | **Adapt** | High | Adapt executor for NEXUS; may replace Temporal with simpler durability |
| AgentFlow Patterns | PraisonAI | `workflows/`, `process/process.py` (route/parallel/loop/repeat) | **Adapt** | Medium | Extract orchestration patterns; integrate with workflow engine |
| Durable Execution | Clawith | LangGraph StateGraph + PostgreSQL checkpoints | **Reuse** | Medium | Already production-grade; extend for multi-step workflows |
| Proactive Triggers (Aware) | Clawith | `trigger.py`, `trigger_execution.py`, focus system | **Reuse** | Low | 6 trigger types ready for autonomous operation |
| Pipeline System | Paperclip | `pipelines.ts`, `pipeline_cases.ts`, `pipeline_case_events.ts` | **Adapt** | Medium | Port pipeline concept for multi-stage agent workflows |
| SOP-Driven Collaboration | MetaGPT | `metagpt/roles/`, `metagpt/team.py`, publish/subscribe messaging | **Wrap** | Medium | Wrap role patterns; integrate with NEXUS agent system |
| Execution Loop | Cronus AI-Company | `src/aiteam/loop/` (watchdog, auto-assign, completion verifier) | **Reuse** | Low | Well-designed autonomous loop; integrate with NEXUS task system |

### Memory / Knowledge Layer

| NEXUS Component | Source Project | Existing Implementation | Reuse Strategy | Integration Difficulty | Rewrite Requirement |
|-----------------|---------------|------------------------|----------------|----------------------|-------------------|
| Working Memory | Cronus AI-Company | `src/aiteam/memory/store.py` (3-temperature: hot/warm/cold) | **Reuse** | Low | Clean architecture; upgrade SQLite to PostgreSQL for multi-user |
| Long-term Memory | PraisonAI | `memory/` (adapters, auto-memory, search) | **Adapt** | Medium | Combine with Cronus 3-tier; add vector search |
| Memory Retrieval | Cronus AI-Company | `retriever.py` (BM25 search + context building) | **Reuse** | Low | Simple, effective; add embedding-based search as enhancement |
| Knowledge/RAG | PraisonAI | `knowledge/` (chunking, indexing, vector store, retrieval, reranking) | **Adapt** | Medium | Full RAG pipeline; integrate with NEXUS storage |
| Context Management | OpenCompany | RFC-0002 Context V2 (execution journal separate from memory) | **Adapt** | Medium | Sound architectural pattern; apply to NEXUS agent runtime |
| Organizational Knowledge | Clawith | Plaza system (`plaza.py`) + published pages | **Reuse** | Low | Knowledge feed for company-wide learning |
| Experience Pool | MetaGPT | `metagpt/exp_pool/` | **Wrap** | Medium | Pattern matching from past executions |
| Meeting Records | Cronus AI-Company | `src/aiteam/meeting/` (8 templates) | **Reuse** | Low | Structured meetings as organizational memory |

### Tool / Integration Layer

| NEXUS Component | Source Project | Existing Implementation | Reuse Strategy | Integration Difficulty | Rewrite Requirement |
|-----------------|---------------|------------------------|----------------|----------------------|-------------------|
| Tool Registry | OpenCompany | BaseNode plugin system + auto-discovery | **Adapt** | Medium | Extract registration pattern; adapt for Python-first NEXUS |
| MCP Protocol | PraisonAI + Cronus AI-Company | PraisonAI: `mcp/` (client+server); Cronus: 113 MCP tools | **Merge** | Medium | Combine MCP client from PraisonAI with Cronus tool patterns |
| Tool Execution | OpenCompany | `server/services/execution/` with circuit breaker | **Adapt** | Medium | Port execution + resilience patterns |
| Tool Access Governance | Paperclip | `tool_access.ts`, tool gateway | **Adapt** | Medium | Port access control; integrate with NEXUS RBAC |
| External Integrations | Clawith | 46 API routes (Slack, Discord, Feishu, etc.) | **Reuse** | Low | Rich channel integration library |
| Credential Management | OpenCompany | `credential_registry.py`, `credentials/` | **Adapt** | Medium | Secure credential storage with per-agent scoping |
| Secret Vault | Paperclip | `company_secrets.ts`, `company_secret_versions.ts`, encrypted storage | **Adapt** | Medium | Port encrypted vault pattern to Python |

### Communication Layer

| NEXUS Component | Source Project | Existing Implementation | Reuse Strategy | Integration Difficulty | Rewrite Requirement |
|-----------------|---------------|------------------------|----------------|----------------------|-------------------|
| Agent-to-Agent Protocol | Clawith | `a2a_runtime.py`, `a2a_completion.py` | **Reuse** | Low | Industry-standard A2A protocol |
| Group Conversations | Clawith | `group_runtime_tools.py`, `group_handoff.py`, `group_context_builder.py` | **Reuse** | Low | Multi-agent conversation support |
| Event Bus | PraisonAI + Cronus | PraisonAI: `bus/bus.py`; Cronus: `api/event_bus.py` | **Merge** | Medium | Combine in-process + async event distribution |
| Message Routing | MetaGPT | Publish/subscribe with tag-based filtering | **Wrap** | Medium | Clean pattern for role-based message routing |
| Channel Delivery | Clawith | `channel_delivery.py`, `channel_provider_delivery.py` | **Reuse** | Low | Output routing to external channels |

### Governance / Safety Layer

| NEXUS Component | Source Project | Existing Implementation | Reuse Strategy | Integration Difficulty | Rewrite Requirement |
|-----------------|---------------|------------------------|----------------|----------------------|-------------------|
| Guardrails | PraisonAI | `guardrails/` (structural, policy, LLM-based, chain) | **Reuse** | Low | Comprehensive guardrail system |
| Doom-Loop Detection | PraisonAI | `goal/loop.py`, ExecutionConfig limits | **Reuse** | Low | Critical safety for autonomous operation |
| Budget Enforcement | Paperclip + PraisonAI | Paperclip: budget policies; PraisonAI: max_budget in ExecutionConfig | **Merge** | Medium | Combine org-level budgets with per-execution limits |
| Approval Gates | Paperclip + PraisonAI | Paperclip: decision queues; PraisonAI: `approval/` module | **Merge** | Medium | Multi-level approval (auto + human) |
| Audit Trail | Clawith | `audit.py`, `activity_logger.py`, `audit_logger.py` | **Reuse** | Low | Enterprise audit logging |
| Content Safety | Cronus AI-Company | `memory/content_safety.py` | **Reuse** | Low | Filter unsafe content before storage |
| Cycle Guard | Clawith | `cycle_guard.py` in LangGraph runtime | **Reuse** | Low | Infinite loop prevention at execution level |

### Self-Evolution Layer (New)

| NEXUS Component | Source Project | Existing Implementation | Reuse Strategy | Integration Difficulty | Rewrite Requirement |
|-----------------|---------------|------------------------|----------------|----------------------|-------------------|
| Self-Assessment | None | No existing implementation | **Build** | Very High | Novel capability - agents evaluate own performance |
| Code Self-Modification | Cronus AI-Company (partial) | Ecosystem research + workflow tools | **Build** | Very High | Foundation exists but core capability is new |
| Architecture Evolution | None | No existing implementation | **Build** | Very High | System redesigns itself based on performance data |
| Skill Acquisition | PraisonAI (partial) | `knowledge/`, `memory/learn/` | **Build** | High | Agents learn new skills from experience |
| Performance Optimization | Cronus AI-Company (partial) | `analytics` module, `completion_verifier.py` | **Build** | High | Self-tuning based on metrics |
| Failure Learning | Cronus AI-Company | `failure_alchemy.py`, `replay_engine.py` | **Adapt** | Medium | Transform failures into system improvements |

### Infrastructure Layer

| NEXUS Component | Source Project | Existing Implementation | Reuse Strategy | Integration Difficulty | Rewrite Requirement |
|-----------------|---------------|------------------------|----------------|----------------------|-------------------|
| API Gateway | Clawith + Paperclip | Clawith: FastAPI routes; Paperclip: Express middleware | **Adapt** | Medium | Unified Python FastAPI gateway |
| Database Layer | Clawith | SQLAlchemy async + SQLModel + Alembic | **Reuse** | Low | Production-grade async ORM stack |
| Deployment | Clawith | Docker Compose + Helm charts + CI/CD | **Reuse** | Low | Enterprise deployment ready |
| Plugin System | Paperclip + OpenCompany | Paperclip: full plugin lifecycle; OpenCompany: BaseNode auto-discovery | **Merge** | High | Combine managed lifecycle with auto-discovery |
| Sandbox Execution | PraisonAI | `sandbox/` (Docker, E2B, Modal) | **Reuse** | Medium | Multiple isolation options |
| Session Management | Cronus AI-Company | `session_registry.py`, `session_probe.py`, fleet downlink | **Adapt** | Medium | Cross-session coordination for distributed agents |

---

## Difficulty Distribution Summary

| Difficulty | Count | Percentage |
|-----------|-------|-----------|
| Low | 18 | 35% |
| Medium | 24 | 47% |
| High | 6 | 12% |
| Very High | 3 | 6% |

## Source Project Usage Summary

| Project | Components Referenced | Primary Role |
|---------|---------------------|--------------|
| Paperclip | 12 | Company/Org control plane, governance |
| OpenCompany | 7 | Workflow engine, tool system, LLM providers |
| PraisonAI | 11 | Agent SDK, orchestration, guardrails, RAG |
| MetaGPT | 4 | Role patterns, message routing, experience |
| Clawith | 17 | Execution engine, identity, triggers, infra |
| Cronus AI-Company | 11 | Memory, MCP tools, meetings, loop, fleet |
| New (Build) | 5 | Self-evolution capabilities |

---

## Key Integration Risks

1. **TypeScript to Python migration** (Paperclip): Schema porting requires careful type translation
2. **Temporal dependency** (OpenCompany): May need replacement with LangGraph for simpler durability
3. **LangGraph lock-in** (Clawith): Core execution tied to LangGraph library updates
4. **MCP protocol maturity**: Protocol still evolving; tool definitions may change
5. **Multi-database**: Merging SQLite (Cronus) + PostgreSQL (Clawith) + PGlite (Paperclip)
6. **Self-evolution novelty**: No proven patterns to follow; highest risk component
