# Clawith - Repository Analysis

## Overview

Clawith is a **multi-tenant enterprise agent platform** combining Python FastAPI with a React frontend, powered by a **LangGraph-based durable execution engine**. Its distinguishing features include persistent agent identity (soul.md, memory.md), an Aware system with 6 trigger types (cron, once, interval, poll, on_message, webhook), Plaza (organizational knowledge feed), comprehensive RBAC, and A2A (Agent-to-Agent) protocol support. The platform manages 39 SQLModel tables and supports group conversations with multiple agents.

---

## 1. Architecture

**Type:** Full-stack monolith (FastAPI + React)  
**Pattern:** Service-oriented backend with LangGraph execution engine  
**Primary Languages:** Python 3.12+ (backend), TypeScript (frontend)

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `backend/app/` | FastAPI application root |
| `backend/app/services/agent_runtime/` | LangGraph execution engine (54 files) |
| `backend/app/models/` | SQLModel table definitions (39 tables) |
| `backend/app/api/` | REST API endpoints (46 route files) |
| `backend/app/services/` | Business logic services |
| `backend/app/schemas/` | Pydantic request/response schemas |
| `backend/app/dao/` | Data access objects |
| `backend/app/core/` | Core utilities and middleware |
| `frontend/` | React + Vite + Tailwind application |
| `deploy/` | Deployment configurations |
| `helm/` | Kubernetes Helm charts |
| `docs/` | Documentation |
| `scripts/` | Utility scripts |

### Architectural Patterns
- **LangGraph StateGraph**: Deterministic control flow with durable checkpoints
- **Command Worker Pattern**: Caller-transaction command intake with async execution
- **Event Stream Polling**: Stable product events (never checkpoint internals)
- **Service Layer**: Clean separation between API routes and business logic
- **Multi-tenancy**: Tenant isolation at database and service level
- **RBAC**: Role-based access control throughout

---

## 2. Runtime

- **Backend:** Python 3.12+, FastAPI (async)
- **Execution Engine:** LangGraph (StateGraph with PostgreSQL checkpoints)
- **Database:** PostgreSQL (via SQLAlchemy async + SQLModel)
- **Checkpointing:** `AsyncPostgresSaver` from `langgraph-checkpoint-postgres`
- **Frontend:** React + Vite + Tailwind CSS
- **Deployment:** Docker Compose, Kubernetes (Helm), CI/CD pipelines
- **Message Queue:** Internal event stream (polling-based)
- **Encryption:** Encrypted checkpoint serialization

---

## 3. Agent System

### Persistent Agent Identity
Each agent has a durable identity consisting of:
- **soul.md**: Core personality, values, communication style
- **memory.md**: Accumulated knowledge and experiences
- **workspace**: Sandboxed file system per agent
- **Configuration**: Model preferences, tool access, behavior settings

### LangGraph Execution Engine (`backend/app/services/agent_runtime/`, 54 files)

| Component | Purpose |
|-----------|---------|
| `graph.py` | StateGraph definition (control_guard -> compact -> model -> tool -> verify -> wait -> terminal) |
| `langgraph_driver.py` | Runtime graph registry and run resolution |
| `adapter.py` | Caller-transaction command intake |
| `command_worker.py` | Async command execution worker |
| `checkpointer.py` | LangGraph checkpoint persistence (PostgreSQL) |
| `context_builder.py` | LLM context construction |
| `node_executor.py` | Individual graph node execution |
| `model_step_service.py` | LLM model invocation |
| `event_stream.py` | Polling stream over product events |
| `cycle_guard.py` | Infinite loop prevention |
| `heartbeat_completion.py` | Liveness monitoring |
| `cancel_source.py` | Graceful run cancellation |
| `recovery.py` | Crash recovery mechanisms |
| `a2a_runtime.py` | Agent-to-Agent protocol runtime |
| `a2a_completion.py` | A2A task completion handling |
| `group_runtime_tools.py` | Group conversation tools |
| `group_handoff.py` | Agent handoff in groups |
| `group_context_builder.py` | Multi-agent context assembly |
| `chat_intake.py` | Chat message processing |
| `chat_stream.py` | Streaming response delivery |
| `delivery.py` | Output delivery routing |

### Graph Nodes (execution flow)
```
START -> control_guard -> compact_run_if_needed -> model -> tool -> verify -> wait -> terminal -> END
```
- **control_guard**: Authorization and rate limiting
- **compact**: Context window compaction if needed
- **model**: LLM inference call
- **tool**: Tool execution with retry
- **verify**: Output validation
- **wait**: Human/external input waiting states
- **terminal**: Run completion/failure

### Agent Lifecycle Services
- `agent_manager.py` - CRUD operations
- `agent_seeder.py` - Default agent provisioning
- `agent_context.py` - Runtime context management
- `agent_tools.py` - Tool binding and access control
- `agent_directory.py` - Agent discovery and search
- `autonomy_service.py` - Self-directed operation mode

---

## 4. Skills

### Skill System (`backend/app/services/`, `skills-lock.json`)
- External skill discovery from Smithery/ModelScope registries
- Skill-to-agent binding
- `skills-lock.json` - Pinned skill versions
- `builtin_tool_definitions.py` - Core built-in tools

### Agent Bay Integration
- `agentbay_client.py` - Remote agent sandbox client
- `agentbay_live.py` - Live agent monitoring

---

## 5. Memory

### Persistent Memory
- **soul.md**: Immutable core identity
- **memory.md**: Mutable accumulated knowledge
- Per-agent workspace with file persistence
- Session context state tracking

### Runtime Memory
- LangGraph checkpoint state (full conversation history)
- Context compaction for long conversations
- `checkpoint_side_effects.py` - Side effects during checkpointing
- Experience records (`experience.py`, `experience_reference.py`)

### Organizational Memory
- **Plaza**: Organization-wide knowledge feed (`plaza.py` model, `plaza.py` API)
- Published pages for shared documentation
- Activity logs for organizational learning

---

## 6. Tools

### Built-in Tools (`builtin_tool_definitions.py`)
- Core set of always-available tools
- Tool execution tracking (`agent_tool_execution.py` model)

### Tool Execution in LangGraph
- Tool node in StateGraph handles all tool calls
- Retry with `SAFE_READ_MAX_ATTEMPTS`
- `RetryableToolNodeError` for transient failures
- `async_tool_poll.py` - Polling for async tool results

### External Integrations (via API routes)
- Slack integration
- Discord bot
- Feishu/Lark
- WeChat/WeCom
- WhatsApp
- DingTalk
- Google Workspace
- Atlassian (Jira/Confluence)
- File management
- Webhook handlers

### Channel System
- `channel_session.py` - Per-channel session management
- `channel_user_service.py` - Channel user mapping
- `channel_delivery.py` - Output routing to channels
- `channel_provider_delivery.py` - Provider-specific delivery

---

## 7. Orchestration

### LangGraph-Based Orchestration
- Deterministic state machine execution
- Durable checkpoints for crash recovery
- Interrupt/resume semantics via `langgraph.types.interrupt`
- Command pattern for state transitions (`langgraph.types.Command`)

### Aware System (Proactive Triggers)
6 trigger types (`trigger.py` model):
1. **cron** - Scheduled recurring execution
2. **once** - One-time future execution
3. **interval** - Periodic execution
4. **poll** - External data source monitoring
5. **on_message** - Event-driven (message received)
6. **webhook** - External HTTP trigger

### Focus Items (`focus.py`)
- Agents maintain a list of focus items (attention priorities)
- Focus drives proactive behavior
- Trigger execution records track results

### Group Conversations
- Multiple agents in shared conversation
- `group_runtime_tools.py` - Group-specific tools (mention, handoff)
- `group_handoff.py` - Agent delegation within groups
- `group_context_builder.py` - Shared context assembly
- `group_at.py` - @mention handling

### A2A Protocol (`a2a_runtime.py`, `a2a_completion.py`)
- Agent-to-Agent protocol implementation
- Cross-platform agent communication
- Task delegation between agents

---

## 8. Persistence

### Database (39 SQLModel tables)
Key table groups:
- **Tenancy:** `tenant`, `tenant_setting`, `user`, `org`
- **Agents:** `agent`, `agent_run`, `agent_run_command`, `agent_run_event`, `agent_tool_execution`, `agent_credential`
- **Identity:** `identity` (agent soul/personality)
- **Communication:** `chat_session`, `group`, `participant`, `gateway_message`, `channel_config`, `channel_delivery`
- **Knowledge:** `plaza`, `published_page`, `experience`, `experience_reference`
- **Tasks:** `task`, `focus`, `trigger`, `trigger_execution`, `schedule`
- **Skills:** `skill`, `tool`, `workspace`
- **Security:** `audit`, `notification`, `invitation_code`
- **OKR:** `okr` (objectives and key results)
- **Onboarding:** `onboarding`
- **Settings:** `system_settings`, `llm`

### Checkpoint Storage
- PostgreSQL-backed LangGraph checkpoints
- Encrypted serialization (`EncryptedSerializer`)
- JSON+ serialization with custom type registration
- Dedicated `langgraph_checkpoint` schema

### Migrations
- Alembic migrations (`migrations/` directory)
- `alembic.ini` configuration

---

## 9. APIs

### REST API (46 route files in `backend/app/api/`)
Key endpoint groups:
- `/agents` - Agent CRUD and management
- `/chat-sessions` - Conversation management
- `/groups` - Group conversation management
- `/messages` - Message send/receive
- `/focus` - Focus item management
- `/triggers` - Aware system triggers
- `/skills` - Skill management
- `/tools` - Tool configuration
- `/plaza` - Knowledge feed
- `/organization` - Org structure
- `/teams` - Team management
- `/tasks` - Task management
- `/okr` - OKR management
- `/auth` - Authentication
- `/admin` - Administrative operations
- `/tenants` - Multi-tenant management
- `/enterprise` - Enterprise features
- `/webhooks` - Webhook management
- Channel-specific: `/slack`, `/discord`, `/feishu`, `/dingtalk`, `/wechat`, `/wecom`, `/whatsapp`

### WebSocket
- `websocket.py` - Real-time agent communication
- `group_websocket.py` - Group conversation real-time
- Streaming responses via SSE/WebSocket

### A2A Protocol API
- `gateway.py` - A2A gateway endpoint
- Agent discovery and capability advertisement
- Cross-platform task delegation

---

## 10. Extension Points

- **Channel Integrations**: Add new communication channels (Slack/Discord/Feishu pattern)
- **Tool Definitions**: Register custom tools via `builtin_tool_definitions.py` pattern
- **Trigger Types**: Extend the Aware system with new trigger types
- **LLM Models**: Add providers via model configuration
- **Graph Topologies**: Create new LangGraph execution graphs
- **A2A Protocol**: Connect external agent platforms
- **Enterprise Features**: `enterprise.py` API for custom enterprise needs
- **SSO Integration**: `sso.py` for authentication providers
- **Skill Registries**: Connect to Smithery/ModelScope or custom registries
- **Agent Templates**: `agent_seeder.py` for pre-configured agents

---

## 11. Licensing

- **License:** Apache 2.0
- More permissive for enterprise use (patent grant)
- Compatible with MIT dependencies
- Allows proprietary derivative works

---

## 12. Dependencies

### Core Backend
- `fastapi` - HTTP framework
- `sqlalchemy[asyncio]` + `sqlmodel` - Database ORM
- `langgraph` - Execution engine
- `langgraph-checkpoint-postgres` - Durable checkpoints
- `pydantic` - Data validation
- `alembic` - Database migrations
- `uvicorn` - ASGI server

### Frontend
- `react` + `react-dom` - UI framework
- `vite` - Build tool
- `tailwindcss` - Styling

### Deployment
- Docker + Docker Compose
- Kubernetes (Helm charts)
- CI/CD (docker-compose.ci.yml, docker-compose.cd.yml)

### Integrations
- Slack SDK
- Discord.py
- Various messaging platform SDKs

---

## Summary for NEXUS

**Strengths for NEXUS:**
- Production-grade LangGraph execution with durable PostgreSQL checkpoints
- Persistent agent identity model (soul.md + memory.md) - crucial for autonomous company
- Aware system with 6 trigger types enables proactive autonomous behavior
- Multi-tenant architecture with proper isolation
- A2A protocol for cross-platform agent communication
- Group conversation support (multiple agents collaborating)
- Comprehensive channel integration (Slack, Discord, WeChat, etc.)
- Enterprise-ready (RBAC, audit, SSO, Helm charts)
- Plaza knowledge feed for organizational learning
- Apache 2.0 license (enterprise-friendly patent grant)

**Weaknesses / Gaps:**
- No organizational hierarchy/company model (flat tenant -> agents)
- No budget/cost tracking per agent
- No skill marketplace or catalog system
- Limited workflow orchestration (single LangGraph topology, not composable workflows)
- No multi-model tool ecosystem (built-in tools are limited)
- No CI/CD pipeline for agent development
- Heavyweight deployment requirements (PostgreSQL, LangGraph, multiple services)
- Relatively young codebase with potential stability concerns
