# Cronus AI-Company - Repository Analysis

## Overview

AI-Company (Cronus AI Team OS) is a **Python FastAPI + React dashboard** system that transforms Claude Code into a persistent, self-managing development team. It exposes **113 MCP tools across 19 tool modules**, implements cross-session orchestration (fleet downlink, session registry), a three-temperature Memory System v2 (hot/warm/cold with BM25 retrieval), progressive tool-loading governance, and comprehensive team management including structured meetings, agent templates, and a task wall.

---

## 1. Architecture

**Type:** Full-stack application (Python backend + React dashboard)  
**Pattern:** MCP-first tool provider with persistent team state  
**Primary Language:** Python 3.11+

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `src/aiteam/` | Core package (all business logic) |
| `src/aiteam/mcp/tools/` | 19 MCP tool modules (113 tools total) |
| `src/aiteam/api/` | FastAPI application (routes, middleware, event bus) |
| `src/aiteam/memory/` | Memory System v2 (3-temperature architecture) |
| `src/aiteam/orchestrator/` | Team orchestration (TeamManager) |
| `src/aiteam/meeting/` | Structured meeting system (8 templates) |
| `src/aiteam/loop/` | Execution loop (watchdog, auto-assign, failure alchemy) |
| `src/aiteam/storage/` | Storage repository abstraction |
| `src/aiteam/services/` | Business services |
| `src/aiteam/integrations/` | External service integrations |
| `src/aiteam/config/` | Configuration management |
| `src/aiteam/hooks/` | Lifecycle hooks |
| `dashboard/` | React 19 dashboard application |
| `migrations/` | Database migrations |
| `plugin/` | Plugin system |

### Architectural Patterns
- **MCP-first**: All capabilities exposed as MCP tools (Claude Code native)
- **Three-temperature memory**: Hot (in-memory) / Warm (SQLite) / Cold (JSON archive)
- **Progressive tool loading**: Tools loaded based on context/need
- **Fleet orchestration**: Cross-session agent coordination
- **Event-driven**: EventBus for async coordination
- **Repository pattern**: Clean data access abstraction

---

## 2. Runtime

- **Backend:** Python 3.11+, FastAPI + Uvicorn
- **Database:** SQLite (embedded, file-based)
- **MCP Server:** Custom MCP implementation (tool registration)
- **Dashboard:** React 19, modern bundling
- **Storage:** File-based (`.aiteam/` directory) + SQLite
- **Search:** BM25 for memory retrieval
- **Packaging:** Hatchling build system
- **CLI:** Integrated with Claude Code via MCP

---

## 3. Agent System

### Agent Model
- 25 agent templates for different roles
- Agent status tracking (`AgentStatus` enum)
- Per-agent configuration and specialization
- Agent reuse patterns (`api/agent_reuse.py`)
- Agent context management (`api/agent_context.py`)

### Team Orchestration (`src/aiteam/orchestrator/`)
- `TeamManager` - Unified entry point for all team operations
- Team CRUD operations
- Agent-to-team assignment
- Task execution coordination
- Status queries and monitoring
- `OrchestrationMode` - Different team execution strategies

### Cross-Session Coordination
- `session_registry.py` - Track active Claude Code sessions
- `session_probe.py` - Probe session health
- Fleet downlink for multi-instance coordination
- `wake_manager.py` - Session wake-up coordination
- `wake_actionable.py` - Actionable wake events

### Execution Loop (`src/aiteam/loop/`)
- `watchdog.py` - Monitor agent health and progress
- `auto_assign.py` - Automatic task assignment
- `completion_verifier.py` - Verify task completion quality
- `failure_alchemy.py` - Transform failures into learning
- `replay_engine.py` - Replay failed operations
- `task_wall_engine.py` - Task board management
- `what_if.py` - Speculative execution analysis

---

## 4. Skills

### MCP Tool Modules (19 modules, 113 tools)
| Module | Purpose |
|--------|---------|
| `team` | Team management operations |
| `agent` | Agent CRUD and configuration |
| `meeting` | Meeting scheduling and execution |
| `task` | Task creation and management |
| `project` | Project management |
| `analytics` | Performance analytics |
| `links` | Reference link management |
| `reports` | Report generation |
| `briefing` | Status briefings |
| `task_analysis` | Task decomposition and analysis |
| `memory` | Memory operations (store/recall) |
| `infra` | Infrastructure management |
| `channels` | Communication channels |
| `watchdog` | Health monitoring |
| `ecosystem` | Ecosystem research (42 tools) |
| `workflows` | Workflow management |

### Toolset Governance (`toolsets.py`)
- `DEFAULT_TOOLSETS` - Standard tool availability
- `WRITE_TOOLS` - Tools with write side effects
- `module_enabled()` - Check if module is active
- `resolve_readonly()` - Read-only mode enforcement (`AITEAM_READONLY`)
- `resolve_toolsets()` - Dynamic toolset resolution

### Progressive Tool Loading
- Tools loaded based on current context
- Heavy tools deferred until needed
- Read-only mode strips write capabilities

---

## 5. Memory

### Memory System v2 (`src/aiteam/memory/`)
Three-temperature architecture:

| Tier | Storage | Access Time | Capacity |
|------|---------|-------------|----------|
| Hot | Python dict (in-memory) | Instant | Limited |
| Warm | SQLite backend | Fast | Large |
| Cold | JSON file archive | Slow | Unlimited |

### Memory Components
- `store.py` - `MemoryStore` class managing all three tiers
- `retriever.py` - BM25 search + context string building
- `scoping.py` - Memory scope management (team/agent/project/task)
- `reconcile.py` - Cross-tier reconciliation
- `recovery.py` - Memory recovery from corruption
- `content_safety.py` - Content filtering before storage
- `backends/` - Pluggable backend implementations (SQLite)

### Memory Scopes (`MemoryScope` type)
- Team-level memories (shared)
- Agent-level memories (private)
- Project-level memories (scoped)
- Task-level memories (ephemeral)

### Retrieval
- BM25 text search for recall
- Context string building for LLM consumption
- Scope-filtered queries
- Hot cache for frequently accessed memories

---

## 6. Tools

### 113 MCP Tools Across 19 Modules
All tools registered via `register(mcp)` function pattern:

```python
# Pattern in each module:
def register(mcp):
    @mcp.tool("tool_name")
    def tool_function(params) -> result:
        ...
```

### Ecosystem Research Platform (42 tools in `ecosystem` module)
- Research automation
- Knowledge graph queries
- Reference management
- Technology scanning

### Tool Access Control
- Progressive loading (context-aware)
- Read-only mode (`AITEAM_READONLY` env var)
- Write tools explicitly listed and controllable
- Module-level enable/disable

### Infrastructure Tools (`infra` module)
- System health monitoring
- Resource management
- Configuration management
- Deployment operations

---

## 7. Orchestration

### TeamManager Orchestration
- Unified entry point for team operations
- Event bus integration for async coordination
- Task assignment algorithms
- Status monitoring and reporting
- `OrchestrationMode` enum for different strategies

### Execution Loop (`src/aiteam/loop/`)
Autonomous operation cycle:
1. **Auto-assign** - Match tasks to available agents
2. **Watchdog** - Monitor execution health
3. **Completion Verifier** - Validate task outputs
4. **Failure Alchemy** - Learn from failures
5. **Replay Engine** - Retry failed operations
6. **What-If** - Speculative planning

### Meeting System (`src/aiteam/meeting/`)
8 structured meeting templates:
- Standup meetings
- Planning sessions
- Retrospectives
- Design reviews
- Architecture discussions
- Priority alignment
- Sprint planning
- Status updates

### Task Wall Engine
- Visual task board management
- Task state transitions
- Priority ordering
- Assignment tracking

---

## 8. Persistence

### Storage Repository (`src/aiteam/storage/`)
- Abstract repository pattern
- File-based default implementation
- `.aiteam/` directory structure:
  - Team definitions
  - Agent configurations
  - Task state
  - Memory archives
  - Meeting records

### Database
- SQLite for warm-tier memory
- Alembic migrations for schema changes
- Session management

### File Storage
- JSON serialization for cold storage
- Markdown files for human-readable state
- Archive directory for historical data
- Reference graph persistence

---

## 9. APIs

### FastAPI Application (`src/aiteam/api/`)
Route modules in `src/aiteam/api/routes/`:
- Agent management endpoints
- Team operations
- Task management
- Memory queries
- Meeting management
- Analytics/reports
- Health/status

### MCP Protocol (Primary Interface)
- 113 tools exposed via MCP
- Claude Code native integration
- Progressive tool loading
- Read-only mode support

### WebSocket (`src/aiteam/api/ws/`)
- Real-time event streaming
- Session state updates
- Task progress notifications

### Event Bus (`src/aiteam/api/event_bus.py`)
- Internal event distribution
- Async coordination between components
- WebSocket broadcast integration

### Middleware (`src/aiteam/api/middleware.py`)
- Request logging
- Error handling
- Authentication
- Rate limiting

---

## 10. Extension Points

- **MCP Tool Modules**: Add new modules following `register(mcp)` pattern
- **Memory Backends**: Implement `MemoryBackend` protocol for custom storage
- **Meeting Templates**: Add structured meeting types
- **Agent Templates**: 25 templates, easily extensible
- **Integrations** (`src/aiteam/integrations/`): Add external service connections
- **Hooks** (`src/aiteam/hooks/`): Lifecycle hooks for custom behavior
- **Plugin System** (`plugin/`): External plugin loading
- **Workflow Definitions**: Custom workflow templates
- **Ecosystem Research Tools**: Extend the 42-tool research platform
- **Dashboard Widgets**: React 19 component-based extension

---

## 11. Licensing

- **License:** MIT
- Permissive for commercial use
- No copyleft dependencies
- Claude Code integration requires Anthropic agreement

---

## 12. Dependencies

### Core Dependencies
- `fastapi >= 0.115.0` - HTTP framework
- `uvicorn[standard] >= 0.32.0` - ASGI server
- SQLite (stdlib) - Embedded database
- `pydantic` - Data validation

### MCP
- Custom MCP tool registration framework
- Claude Code integration protocol

### Dashboard
- React 19
- Modern bundling (Vite or similar)
- Tailwind CSS (likely)

### Optional
- BM25 search implementation
- JSON serialization libraries
- Alembic for migrations

---

## Summary for NEXUS

**Strengths for NEXUS:**
- Three-temperature memory architecture (practical, performant, scalable)
- 113 MCP tools covering comprehensive team operations
- Cross-session orchestration (fleet downlink) - unique among the repos
- Structured meeting system (critical for autonomous company simulation)
- Task wall with auto-assignment and completion verification
- Failure alchemy (learn from failures, replay operations)
- Progressive tool loading (resource-efficient for large tool sets)
- BM25 retrieval for memory recall (simple, effective, no vector DB needed)
- Agent templates (25 pre-built) for rapid team composition
- Lightweight deployment (SQLite, no heavy infrastructure)

**Weaknesses / Gaps:**
- Tightly coupled to Claude Code (MCP-only interface limits portability)
- SQLite limits concurrent multi-user access
- No visual workflow builder
- No durable execution engine (relies on Claude Code sessions)
- No multi-tenant isolation
- No formal approval/governance system
- Limited LLM provider support (Claude-centric)
- No agent-to-agent communication protocol
- Dashboard is supplementary (primary interface is CLI/MCP)
- Single-process architecture limits scaling
