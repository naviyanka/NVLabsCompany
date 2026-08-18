# Paperclip - Repository Analysis

## Overview

Paperclip is a TypeScript monorepo (pnpm workspace) that serves as a **Company/Organization Control Plane** for AI agents. It provides the management layer for hiring, configuring, budgeting, and governing autonomous AI agents operating within a company structure. The system models real organizational concepts (companies, projects, teams, budgets, approvals) and maps them onto AI agent operations.

---

## 1. Architecture

**Type:** Monorepo (pnpm workspace)  
**Pattern:** Client-Server with shared packages  
**Primary Language:** TypeScript (ES modules)

### Workspace Packages

| Package | Purpose |
|---------|---------|
| `server/` | Express.js API server (REST + SSE) |
| `ui/` | React + Vite single-page application |
| `packages/db/` | Drizzle ORM schema + migrations (116 tables) |
| `packages/shared/` | Shared types, validators, constants (Zod schemas) |
| `packages/adapters/` | Agent runtime adapters (12 adapter variants) |
| `packages/adapter-utils/` | Shared adapter utilities |
| `packages/mcp-server/` | MCP server implementation |
| `packages/plugins/` | Plugin SDK and system |
| `packages/skills-catalog/` | Built-in skill definitions |
| `packages/teams-catalog/` | Team template definitions |
| `cli/` | `paperclipai` CLI tool |
| `skills/` | Skill definitions and releases |

### Architectural Patterns
- Route-based Express API with middleware injection (validate, auth, authz)
- Service layer pattern (e.g., `agentService`, `approvalService`, `companySkillService`)
- Drizzle ORM with code-first schema (type-safe queries)
- Event-driven agent heartbeat system
- Multi-tenant company isolation
- Plugin system with sandboxed execution

---

## 2. Runtime

- **Server:** Node.js >= 20, Express.js
- **Database:** PostgreSQL (production) / PGlite (embedded/dev mode)
- **ORM:** Drizzle (code-first, type-safe)
- **Frontend:** React 19 + Vite, Tailwind CSS
- **Package Manager:** pnpm 9.15.4
- **Build:** esbuild for server bundling, Vite for UI
- **Test:** Vitest (unit + integration), Playwright (e2e)
- **Deployment:** Docker (Dockerfile present), self-hostable

---

## 3. Agent System

Paperclip implements a comprehensive agent lifecycle management system:

### Agent Models
- **Agent entity** (`packages/db/src/schema/agents.ts`): Core agent record with URL key, company binding, adapter type, configuration revisions
- **Agent Memberships** (`agent_memberships.ts`): Maps agents to projects/teams
- **Agent Runtime State** (`agent_runtime_state.ts`): Tracks running state, last heartbeat
- **Agent API Keys** (`agent_api_keys.ts`): Per-agent authentication credentials
- **Agent Task Sessions** (`agent_task_sessions.ts`): Active work session tracking
- **Agent Wakeup Requests** (`agent_wakeup_requests.ts`): Asynchronous wake triggers

### Agent Adapters (12 variants)
Located in `packages/adapters/`:
- `hermes` - Core adapter protocol server
- `hermes-gateway` - Gateway for remote Hermes connections
- `claude-local` - Claude Code local adapter
- `codex-local` - OpenAI Codex local adapter
- `cursor-local` - Cursor IDE adapter
- `cursor-cloud` - Cursor cloud adapter
- `openclaw-gateway` - OpenClaw agent gateway
- `opencode-local` - Generic open-source code agent
- `gemini-local` - Google Gemini local adapter
- `grok-local` - xAI Grok local adapter
- `pi-local` - Pi local adapter

### Agent Lifecycle
1. **Hire** (create agent with adapter config)
2. **Configure** (instructions, skills, permissions, environment)
3. **Wake** (trigger agent execution via wakeup request)
4. **Heartbeat** (monitor running state, detect stalls)
5. **Approve/Reject** (governance gates for agent actions)
6. **Cost Track** (budget enforcement per agent)

---

## 4. Skills

- **Company Skills** (`company_skills.ts`): Organization-scoped skill registry
- **Skill Policies** (`company_skill_policies.ts`): Governance over which skills agents can use
- **Skills Catalog** (`packages/skills-catalog/`): Built-in skill definitions
- **Skill Sync** (`agentSkillSyncSchema`): Synchronize skill assignments to agents
- Skill assignment modes: manual, auto, policy-based

---

## 5. Memory

Paperclip itself is not a memory system - it delegates execution to adapters. However, it tracks:
- **Issue Thread Interactions** (`issue_thread_interactions.ts`): Conversation history
- **Issue Comments** (`issue_comments.ts`): Threaded discussions
- **Document Revisions** (`document_revisions.ts`): Versioned document history
- **Activity Log** (`activity_log.ts`): Full audit trail
- **Agent Runtime State**: Tracks session continuity between agent runs
- **Issue Work Products** (`issue_work_products.ts`): Output artifacts from agent work

---

## 6. Tools

### Tool Access Control
- **Tool Access** (`tool_access.ts` schema, `tool-access.ts` route): Governs which tools agents can invoke
- **Tool Gateway** (`tool-gateway.ts`): Proxies tool invocations with auth/audit
- **MCP Server** (`packages/mcp-server/`): Exposes Paperclip as an MCP tool provider

### Built-in Tool Categories
- File resources management
- Secret management (encrypted vault pattern)
- Environment/workspace provisioning
- Pipeline execution
- Plugin-provided tools

---

## 7. Orchestration

### Heartbeat System
- `heartbeat_runs.ts` / `heartbeat_run_events.ts`: Track agent execution cycles
- `heartbeat_run_watchdog_decisions.ts`: Automated decisions on stalled agents
- Scheduler-based heartbeat agent monitoring (`InstanceSchedulerHeartbeatAgent`)

### Approval Gates
- `approvals.ts` / `issue_approvals.ts`: Multi-stage approval workflows
- `approval_comments.ts`: Threaded approval discussions
- `decision_queues.ts` / `decisions.ts`: Queue-based decision routing
- `decision_training_examples.ts`: ML-based auto-decision training data

### Issue Lifecycle
- Issues as work units with decomposition (`issue_plan_decompositions.ts`)
- Issue recovery actions for failed tasks
- Issue tree structure (parent/child hierarchy with holds)

---

## 8. Persistence

### Database Schema (116 tables, Drizzle ORM)
Key table groups:
- **Company/Org:** `companies`, `company_memberships`, `company_logos`, `company_onboarding_seeds`
- **Agents:** `agents`, `agent_memberships`, `agent_api_keys`, `agent_config_revisions`, `agent_runtime_state`
- **Projects:** `projects`, `project_memberships`, `project_goals`, `project_workspaces`
- **Issues:** `issues`, `issue_comments`, `issue_labels`, `issue_relations`, `issue_documents`
- **Finance:** `cost_events`, `finance_events`, `budget_policies`, `budget_incidents`
- **Governance:** `approvals`, `decisions`, `decision_queues`, `tool_access`
- **Plugins:** `plugins`, `plugin_config`, `plugin_state`, `plugin_jobs`, `plugin_entities`
- **Secrets:** `company_secrets`, `company_secret_versions`, `company_secret_bindings`
- **Environments:** `environments`, `environment_leases`, `execution_workspaces`

### Storage
- PostgreSQL for production (ACID, relational)
- PGlite for development/embedded mode (zero-config)
- Asset storage via configurable blob stores
- Database backups via CLI scripts

---

## 9. APIs

### REST API (60+ route files)
Key route groups:
- `/agents` - CRUD, hire, wake, configure, skill-sync
- `/companies` - Multi-company management
- `/issues` - Work item lifecycle
- `/approvals` - Governance gates
- `/costs` - Budget tracking and enforcement
- `/decisions` - Decision queue management
- `/goals` - Objective alignment
- `/projects` - Project management
- `/pipelines` - Workflow pipelines
- `/plugins` - Plugin management
- `/secrets` - Encrypted secret vault
- `/environments` - Execution environments

### Middleware Stack
- Authentication (multi-mode: API key, session, CLI challenge)
- Authorization (RBAC with principal permission grants)
- Validation (Zod schema-based request validation)
- Rate limiting (per-route limiters)

### Adapter Communication Protocol
- Hermes protocol (WebSocket/SSE based)
- MCP protocol support
- A2A-compatible agent communication

---

## 10. Extension Points

- **Plugin System** (`packages/plugins/`): Full plugin lifecycle (install, configure, state, webhooks, jobs, entities, managed resources)
- **Adapter Architecture**: Add new AI provider adapters by implementing the adapter interface
- **Skills Catalog**: Declarative skill definitions that agents can acquire
- **Teams Catalog**: Pre-built team templates
- **Pipelines**: Configurable multi-step workflows
- **Connection Apps**: Extensible third-party service integrations (`connections:ingest-app-definitions`)
- **Plugin UI**: Plugins can ship custom UI (`plugin-ui-static.ts` route)

---

## 11. Licensing

- **License:** MIT
- **Copyright:** PaperclipAI team
- All packages use MIT license consistently
- No copyleft dependencies in core

---

## 12. Dependencies

### Core Runtime Dependencies
- `express` - HTTP server
- `drizzle-orm` + `drizzle-kit` - Database ORM and migrations
- `zod` - Schema validation
- `pglite` - Embedded PostgreSQL
- `tsx` - TypeScript execution
- `esbuild` - Bundling

### Frontend Dependencies
- `react` 19 + `react-dom` 19
- `vite` - Build tool
- `tailwindcss` - Styling
- `lexical` 0.49 - Rich text editor

### Development Dependencies
- `vitest` - Unit/integration testing
- `@playwright/test` - E2e testing
- `typescript` 5.7
- `cross-env` - Cross-platform env vars

### Notable Overrides
- Pinned `rollup >= 4.59.0`
- Pinned `lexical` suite to 0.49.0
- Patched `embedded-postgres` and `acpx`

---

## Summary for NEXUS

**Strengths for NEXUS:**
- Production-grade multi-tenant company/org model
- Comprehensive agent lifecycle management (hire, configure, monitor, govern)
- Sophisticated governance system (approvals, decisions, budgets, tool access)
- Multi-adapter agent architecture supporting diverse AI providers
- Plugin system for extensibility
- Full-featured REST API with proper auth/authz
- 116-table database schema covering all organizational concepts

**Weaknesses / Gaps:**
- No built-in agent execution engine (delegates to adapters)
- No workflow orchestration (simple issue-based task model)
- No memory/knowledge management for agent reasoning
- No agent-to-agent communication protocol (beyond issue comments)
- TypeScript-only stack may limit ML/AI integration
- Tightly coupled to specific adapter implementations
