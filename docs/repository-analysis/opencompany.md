# OpenCompany - Repository Analysis

## Overview

OpenCompany is a **TypeScript + Python hybrid** workflow automation platform inspired by n8n but built agent-first. It provides a visual canvas-based workflow builder with a comprehensive plugin node system (132 nodes across 27+ categories), durable execution via Temporal, and a sophisticated agent runtime with context management, memory, and multi-provider LLM support.

---

## 1. Architecture

**Type:** Hybrid monorepo (pnpm workspace for CLI + Python for server)  
**Pattern:** Frontend (React) + Backend (Python FastAPI) + Durable Execution (Temporal)  
**Primary Languages:** Python 3.12 (backend), TypeScript (frontend/CLI)

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `server/` | Python FastAPI backend (nodes, services, execution) |
| `client/` | React + Vite frontend (visual canvas) |
| `cli/` | Python CLI (`company` command) for local development |
| `server/nodes/` | Plugin node modules (132 nodes, 27 categories) |
| `server/services/` | Core backend services (memory, execution, LLM, credentials) |
| `server/skills/` | Built-in agent skill definitions (19 categories) |
| `docs/` | Architecture documentation |
| `docs-internal/` | Internal design documents and RFCs |

### Architectural Patterns
- **Node-based plugin system**: BaseNode class hierarchy with auto-discovery
- **Conductor-style orchestration**: workflow_decide() pattern for execution routing
- **Temporal durable execution**: Activities + workflows for reliability
- **Provider-neutral agent runtime**: Abstraction over multiple LLM providers
- **Context V2 system**: Separated Context (execution journal) from Memory (durable facts)
- **Fork/Join parallel execution**: asyncio.wait with FIRST_COMPLETED pattern

---

## 2. Runtime

- **Backend:** Python 3.12, FastAPI (async)
- **Frontend:** Node.js 22, React + Vite, React Flow (canvas)
- **Durable Execution:** Temporal (workflow orchestration, activity retries)
- **Database:** Custom database abstraction (node parameter storage)
- **Cache:** Redis (execution cache, idempotency)
- **CLI:** Python Typer CLI (`company` command)
- **Package Manager:** pnpm (frontend), uv/pip (backend)
- **Build System:** Hatchling (Python), Vite (frontend)

---

## 3. Agent System

### Agent Node Types (20 variants in `server/nodes/agent/`)
The agent system provides specialized agent nodes for the visual canvas:
- `aiAgent` - General-purpose AI agent
- `chatAgent` - Conversational agent
- `codingAgent` - Code generation/editing
- `productivityAgent` - Task management
- `travelAgent` - Travel planning
- `socialAgent` - Social media management
- `languageAgent` - Translation/linguistics
- `webAgent` - Web browsing/research
- `paymentAgent` - Financial operations
- `cloudAgent` (gcloud, cloudflare, vercel) - Cloud infrastructure
- `terminalAgent` - System command execution
- `githubAgent` - Repository management
- `vertexAgent` - Google Vertex AI integration
- `rlmAgent` - Reinforcement learning
- `autonomousAgent` - Self-directed operation

### Agent Runtime (`server/services/agent_runtime.py`)
- Provider-neutral execution loop
- Context transition tracking with epoch-fenced sinks
- Tool call dispatch with duplicate name detection
- Multi-modal content support (images in tool results)
- Thinking configuration (extended thinking modes)
- Message filtering and hydration

### Agent Teams (`server/services/agent_team.py`, `server/services/agent_teams/`)
- Multi-agent collaboration within workflows
- Team composition and coordination
- Shared context between team members

---

## 4. Skills

### Built-in Skills (19 categories in `server/skills/`)
- `android_agent` - Android automation
- `assistant` - General assistance
- `autonomous` - Self-directed task completion
- `cloudflare` - Cloudflare management
- `coding_agent` - Software development
- `gcloud` - Google Cloud operations
- `github` - GitHub repository management
- `language_agent` - Translation/NLP
- `payments_agent` - Payment processing
- `productivity_agent` - Task/calendar management
- `rlm_agent` - Reinforcement learning
- `social_agent` - Social media
- `task_agent` - Task decomposition
- `terminal` - CLI/shell operations
- `travel_agent` - Travel planning
- `vercel` - Vercel deployment
- `vertex_agent` - Vertex AI
- `web_agent` - Web research

### Skill System (`server/services/auto_skill.py`)
- Auto-skill discovery and assignment
- Skill-to-node mapping
- Dynamic skill loading at runtime

---

## 5. Memory

### Memory Architecture (RFC-0002 Context V2)
Two distinct concepts:
1. **Context** - Backend-owned execution journal for LLM request reconstruction
   - Thread isolation (session/task/execution)
   - Never shared between agents
   - Owns compaction decisions
2. **Memory** - Explicitly invoked tool for durable fact storage
   - Shareable between agents
   - Vector store backed (`server/services/memory/vector_store.py`)
   - Tool-accessible retrieval

### Memory Services (`server/services/memory/`)
- `runtime.py` - Atomic persistence helpers (append without stale overwrites)
- `markdown.py` - Markdown-formatted memory storage
- `jsonl.py` - Structured event log format
- `state.py` - Memory state management
- `tool_store.py` - Tool-accessible memory interface
- `vector_store.py` - Embedding-based similarity search

### Compaction (`server/services/compaction.py`)
- Context window management via summarization
- Atomic replacement with optimistic concurrency
- Preserves newer content on conflict

---

## 6. Tools

### Node-based Tool System (132 nodes across 27 categories)
Each node type in `server/nodes/` is a tool:

| Category | Examples |
|----------|----------|
| `model/` | OpenAI, Anthropic, Gemini, Mistral, Groq, Ollama, Deepseek, xAI, Perplexity, Together, Fireworks, Cerebras, OpenRouter |
| `search/` | Brave, Serper, Perplexity, Tavily |
| `code/` | Python, JavaScript, TypeScript executors |
| `browser/` | Browser automation nodes |
| `google/` | Gmail, Calendar, Drive, Sheets, Docs |
| `microsoft/` | Outlook, Teams, OneDrive |
| `social/` | Unified social messaging |
| `telegram/` | Telegram bot integration |
| `discord/` | Discord integration |
| `stripe/` | Payment processing |
| `github/` | Repository operations |
| `filesystem/` | File read/write operations |
| `document/` | Document parsing/generation |
| `speech/` | TTS/STT |
| `email/` | Email send/receive |
| `scheduler/` | Cron and timer triggers |
| `utility/` | HTTP, webhooks, console, proxy |

### Tool Registration
- Auto-discovery via `pkgutil.walk_packages`
- `BaseNode` subclass system with `register_node()` decorator
- Credential registry for authenticated tools
- Circuit breaker for unreliable external services

---

## 7. Orchestration

### Workflow Execution Engine (`server/services/execution/`)
- **Conductor-style decide pattern**: Central orchestrator determines next steps
- **Task lifecycle**: PENDING -> SCHEDULED -> RUNNING -> COMPLETED/FAILED/CANCELLED
- **Caching**: Prefect-style task result caching for idempotency
- **Parallel execution**: Fork/Join with asyncio.wait (FIRST_COMPLETED)
- **Dynamic branching**: Runtime workflow modifications
- **Dead Letter Queue**: Failed task handling with retry policies
- **Condition evaluation**: Dynamic routing based on outputs

### Temporal Integration
- Durable workflow execution
- Activity retries with backoff
- Workflow versioning and migration
- Cross-service orchestration

### Execution Models (`server/services/execution/models.py`)
- `ExecutionContext` - Workflow execution state
- `NodeExecution` - Individual node run tracking
- `TaskStatus` - Conductor-style lifecycle enum
- `WorkflowStatus` - Overall workflow state
- Input hashing for cache keys
- Retry policy configuration

---

## 8. Persistence

### Database Layer
- Custom database abstraction (node parameter storage)
- JSON-serializable execution state
- Redis for execution cache and idempotency
- Atomic mutations with optimistic concurrency (`mutate_node_parameters_atomic`)

### Persistence Patterns
- Node parameters as JSON documents
- Memory as markdown with window trimming
- Execution state in Redis (cross-runtime portability)
- Credential storage with encryption
- Workflow definitions as JSON graphs

---

## 9. APIs

### FastAPI Backend
- RESTful API for workflow CRUD
- WebSocket for real-time execution updates
- SSE for streaming agent responses
- Node specification endpoint (canvas metadata)
- Credential management endpoints
- Execution control (start, pause, resume, cancel)

### CLI (`company` command)
- `company build` - Build the project
- `company clean` - Clean build artifacts
- `company dev` - Development server
- Process supervision (orphan cleanup on Windows via Job Objects)
- Platform-aware data/cache/log directories

### RFC-0001: Universal API Schema Translation Layer (UASTL)
- Standardized API schema translation between providers
- Provider-neutral tool definitions
- Schema normalization for multi-provider support

---

## 10. Extension Points

- **BaseNode Plugin System**: Add any tool/integration by subclassing `BaseNode` in appropriate category directory
- **Auto-discovery**: New `.py` files in `server/nodes/` are automatically loaded at startup
- **Provider Registry**: Add LLM providers via model node registration
- **Credential System**: Pluggable credential providers for authenticated services
- **Skill Definitions**: Add agent capabilities via skill YAML/markdown files
- **Workflow Triggers**: Multiple trigger types (webhook, chat, cron, schedule)
- **Theme System**: 12 visual themes for the canvas UI
- **Circuit Breaker**: Configurable resilience for external service calls

---

## 11. Licensing

- **License:** MIT
- **Copyright:** OpenCompany contributors
- No copyleft dependencies in core
- Permissive for commercial use and modification

---

## 12. Dependencies

### Backend (Python)
- `fastapi` - Async HTTP framework
- `temporal-sdk` - Durable execution
- `redis` - Cache and state store
- `chromadb` / vector store libs - Embedding search
- Multiple LLM SDKs (OpenAI, Anthropic, Google GenAI, etc.)
- `pydantic` - Data validation

### Frontend (TypeScript/React)
- `react` + `react-dom` - UI framework
- `@xyflow/react` (React Flow) - Visual canvas
- `vite` - Build tool
- `tailwindcss` - Styling

### CLI
- `typer` - CLI framework
- `rich` - Terminal formatting
- `psutil` - Process management
- `platformdirs` - OS-native paths
- `pywin32` (Windows) - Job Object for process groups

---

## Summary for NEXUS

**Strengths for NEXUS:**
- Production-grade workflow execution engine with durability (Temporal)
- 132 pre-built tool nodes covering a vast integration landscape
- Sophisticated agent runtime with provider neutrality (13 LLM providers)
- Context/Memory separation (RFC-0002) is architecturally sound
- Fork/Join parallelism with proper task lifecycle
- Visual canvas for workflow design
- Auto-discovery plugin system (zero-config node registration)

**Weaknesses / Gaps:**
- No organizational/company model (no multi-tenancy at org level)
- No governance system (approvals, budgets, decision queues)
- No agent lifecycle management (hire/fire/monitor)
- Python + TypeScript hybrid adds operational complexity
- Temporal dependency is heavyweight for simple workflows
- No role-based agent specialization
- Limited agent-to-agent communication beyond team nodes
