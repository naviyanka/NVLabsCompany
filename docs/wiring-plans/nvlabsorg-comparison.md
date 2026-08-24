# NvLabsOrg vs NVLabsCompany — Feature Comparison & Implementation Status

## Source: [github.com/naviyanka/NvLabsOrg](https://github.com/naviyanka/NvLabsOrg)

---

## NvLabsOrg Architecture Summary

NvLabsOrg is a **TypeScript monorepo** (pnpm) with:
- `apps/gateway/` — Node.js WebSocket daemon handling orchestration, agent spawning, and REST API
- `apps/web/` — Next.js 15 PWA frontend (PixiJS office scene, dashboard, panels)
- `apps/desktop/` — Tauri v2 native wrapper
- `packages/memory/` — 4-layer persistent memory (session → agent → shared)
- `packages/orchestrator/` — Multi-agent execution, retry, delegation, pipelines
- `packages/shared/` — Zod-validated command/event schemas

### How It Launches Agents

1. **Auto-detection at startup** — Gateway scans PATH for installed CLI backends (claude, codex, agy, kiro-cli, copilot, cursor, aider, opencode)
2. **Subprocess spawn** — Each agent is a CLI process spawned with: command + flags + instruction file injection
3. **Worktree isolation** — Each agent gets its own git worktree (branch) to work in isolation
4. **WebSocket channels** — Gateway multiplexes stdout/stderr from each subprocess over WS to the frontend

### How It Provides System Prompts

Each backend has a designated **instruction file** that's auto-injected:

| Backend | Instruction File | Mechanism |
|---------|-----------------|-----------|
| Claude Code | `.claude/CLAUDE.md` | Claude reads it automatically |
| Codex | `AGENTS.md` | Codex reads it automatically |
| Antigravity | `GEMINI.md` | Gemini reads it automatically |
| Kiro CLI | `.kiro/steering/default.md` | Kiro reads steering files |
| Copilot | `.github/copilot-instructions.md` | Copilot reads it |
| Cursor | `.cursor/rules/instructions.md` | Cursor reads it |
| Aider | `.aider.conf.yml` | Config-based |
| OpenCode | `AGENTS.md` | Same as Codex |

The **orchestrator** (leader agent) coordinates by:
1. Accepting high-level tasks
2. Decomposing them into subtasks
3. Assigning subtasks to worker agents via their stdin
4. Monitoring completion through their stdout
5. Merging results back into main

---

## Feature-by-Feature Comparison

### Legend
- ✅ = Fully implemented in NVLabsCompany
- ⚠️ = Partially implemented
- ❌ = Not implemented yet
- 🔲 = NvLabsOrg has it, we don't

---

### Agent Backend Support

| Feature (NvLabsOrg) | NVLabsCompany Status | Notes |
|---------------------|---------------------|-------|
| Claude Code backend | ✅ Fully working | Spawns `claude --print --append-system-prompt` |
| Codex CLI | ⚠️ Registered but untested | Command mapped, not verified |
| Antigravity (Gemini/agy) | ✅ Working | Spawns `agy --print` |
| Kiro CLI | ✅ Working | Spawns `kiro-cli chat --no-interactive --trust-all-tools` |
| Copilot CLI | ⚠️ Registered | Not tested (not installed) |
| Cursor CLI | ❌ Not registered | NvLabsOrg supports it, we don't |
| Aider | ⚠️ Registered | Not tested |
| OpenCode | ⚠️ Registered | Not tested |
| Auto-detection of installed CLIs | ✅ Working | `where` command probing at startup |
| Backend health/version probing | ✅ Working | Version detected for installed CLIs |

### Agent Orchestration & Execution

| Feature (NvLabsOrg) | NVLabsCompany Status | Notes |
|---------------------|---------------------|-------|
| Team-based delivery (leader + workers) | ⚠️ Backend exists | `AgentRouter` + `TaskPlanner` exist but not wired to UI |
| Parallel agent collaboration | ⚠️ Backend exists | `ParallelExecutor` with semaphore, not triggered |
| Pipeline engine (multi-step chains) | ⚠️ Backend exists | Pipeline model + runs exist, not executing via adapters |
| Context injection between steps | ❌ Not implemented | NvLabsOrg passes output of step N as input to step N+1 |
| Worktree isolation per agent | ⚠️ Backend exists | `runtime/worktree.py` exists, not wired |
| Auto commit/merge/undo | ❌ Not implemented | NvLabsOrg does this per worktree |
| Task delegation (leader → worker) | ⚠️ Backend exists | A2A communication + routing exist |
| Retry with exponential backoff | ✅ Implemented | `TaskExecutor` has 3x retry |
| Goal loop (autonomous iteration) | ✅ Implemented | `GoalLoop` with judge, safety valves |

### Memory System

| Feature (NvLabsOrg) | NVLabsCompany Status | Notes |
|---------------------|---------------------|-------|
| 4-layer persistent memory | ✅ Fully implemented | L0 ephemeral, L1 session, L2 agent, L3 shared |
| Cross-session persistence | ✅ Implemented | JSON files + DB |
| Cross-agent shared memory (L3) | ✅ Implemented | `promote_to_shared()` |
| Jaccard deduplication | ✅ Implemented | In L2 store |
| Memory in chat context | ⚠️ Partial | Persona `build_working_context()` exists, not wired to chat yet |
| BM25 keyword retrieval | ✅ Implemented | `memory/retriever.py` |

### System Prompts & Identity

| Feature (NvLabsOrg) | NVLabsCompany Status | Notes |
|---------------------|---------------------|-------|
| Instruction file per backend | 🔲 Not implemented | NvLabsOrg writes `.claude/CLAUDE.md` etc. per project |
| System prompt from agent role/soul | ✅ Implemented | `buildAgentSystemPrompt()` + `system_prompt_from_soul()` |
| Soul templates (personality presets) | ✅ Implemented | 5 soul templates exposed via API |
| 20 archetype templates | ✅ Implemented | Full archetype registry |
| Dynamic system prompt injection | ✅ Implemented | Built from agent's capabilities, role, soul_description |
| `--append-system-prompt` for Claude | ✅ Implemented | Used in CLI spawn |
| Steering files for Kiro | 🔲 Not implemented | NvLabsOrg writes `.kiro/steering/default.md` |

### Web UI & Chat

| Feature (NvLabsOrg) | NVLabsCompany Status | Notes |
|---------------------|---------------------|-------|
| Agent chat with real CLI | ✅ Working | Spawns CLI, returns real response |
| Chat history persistence | ✅ Working | `data/chat_database.json` |
| 4 view modes (pixel office, dashboard, files, git) | ⚠️ Partial | We have office + dashboard, no file explorer/git panel in one view |
| Slash commands (24+) | ❌ Not implemented | NvLabsOrg has `/cancel`, `/hire`, `/broadcast`, etc. |
| Pipeline builder (visual) | ❌ Not implemented | NvLabsOrg has a visual pipeline editor |
| Diff viewer | ❌ Not implemented | |
| Theme system (18 themes) | ❌ Not implemented | |
| Agent context menu (right-click) | ❌ Not implemented | |
| Cost estimator per agent | ⚠️ Partial | Budget tracking exists, no real-time cost display per session |
| Chat export (Markdown) | ❌ Not implemented | |
| Notification center | ✅ Implemented | Bell + notifications page |
| Skeleton loaders | ✅ Implemented | Used across pages |
| Error boundaries | ⚠️ Partial | Not isolation per panel |
| Mobile responsive | ✅ Implemented | Tailwind responsive classes |

### Infrastructure

| Feature (NvLabsOrg) | NVLabsCompany Status | Notes |
|---------------------|---------------------|-------|
| REST API (22 endpoints) | ✅ Exceeded | 50+ endpoints |
| WebSocket real-time | ⚠️ Partial | SSE endpoint exists, no full WS multiplexing |
| Rate limiting | ✅ Implemented | Governance middleware |
| Scheduled/cron tasks | ❌ Not implemented | NvLabsOrg has cron-lite recurring tasks |
| Multi-workspace | ❌ Not implemented | NvLabsOrg switches between projects |
| Telegram bot | ❌ Not implemented | |
| Token tracking per agent | ⚠️ Partial | Budget model tracks spend, no real-time per-session token counting |
| Webhooks (outbound) | ⚠️ Partial | Webhook queue exists in communication module |
| API key auth | ✅ Implemented | Bearer token + session auth |
| Desktop app (Tauri) | ❌ Not implemented | |

### Hiring & Team Management

| Feature (NvLabsOrg) | NVLabsCompany Status | Notes |
|---------------------|---------------------|-------|
| `/hire` command | ✅ Implemented | Full hire modal (4 modes) |
| `/hireteam` batch hire | ✅ Implemented | Team templates + batch endpoint |
| `/fire` agent | ✅ Implemented | DELETE endpoint |
| Agent switching between backends | 🔲 Not implemented | NvLabsOrg's `/switch <backend>` changes an agent's CLI |
| Agent reassignment | ⚠️ Partial | Can PATCH agent fields, no dedicated UI |

---

## What NvLabsOrg Has That We Should Implement (Priority)

### HIGH Priority (Agent Execution Quality)

| Feature | What It Does | Effort |
|---------|-------------|--------|
| **Instruction file generation** | Write per-project instruction files (`.claude/CLAUDE.md`, `.kiro/steering/`) with agent's role/soul so the CLI reads it automatically instead of relying on `--append-system-prompt` | Medium |
| **Memory injection into chat** | Use `Persona.build_working_context()` to include recent memories in the LLM prompt (we have the infra, just need to wire it) | Low |
| **Pipeline execution** | Actually run multi-step pipelines through adapters (we have the model, stages, and runs — just need execution glue) | Medium |
| **WebSocket streaming** | Stream agent output character-by-character instead of waiting for full response (better UX for long responses) | Medium |

### MEDIUM Priority (UX & Workflow)

| Feature | What It Does | Effort |
|---------|-------------|--------|
| **Slash commands** | `/cancel`, `/clear`, `/export`, `/model`, `/status` in chat input | Medium |
| **Chat export** | Download conversation as Markdown | Low |
| **Agent backend switching** | Change an agent's CLI provider without re-hiring | Low |
| **Scheduled tasks** | Cron-like recurring prompts/tasks per agent | Medium |
| **Cost tracking per session** | Track tokens/cost for each chat session, display in UI | Low |
| **Cursor CLI support** | Add `cursor` / `agent` command to providers | Low |

### LOW Priority (Polish)

| Feature | What It Does | Effort |
|---------|-------------|--------|
| **Git panel** | Show diff, log, push/PR from UI | High |
| **File explorer** | Browse project files from dashboard | Medium |
| **Theme system** | Multiple color themes | Low |
| **Telegram bot** | Remote control via Telegram | High |
| **Desktop Tauri app** | Native wrapper | High |
| **Multi-workspace** | Switch between projects | Medium |

---

## What We Have That NvLabsOrg Doesn't

| Our Feature | Description |
|-------------|-------------|
| **20 agent archetypes** | Rich dataclass templates with constraints, tools_allowed, interaction_style |
| **6 team composition templates** | Pre-built squads (Startup MVP, Platform, ML, etc.) |
| **Soul/Persona system** | Deep personality: traits, communication style, values, constraints, background, tone |
| **Hire manifest spec** | Portable JSON format with security validation (flag allowlist, model sanitization) |
| **3-temperature memory** | Hot/warm/cold with promote/demote (NvLabsOrg has 4-layer but no temperature model) |
| **BM25 retrieval** | Pure-Python keyword search across memories |
| **Governance system** | Kill switches, circuit breakers, approval workflows, rate limiting, RBAC |
| **Agent evolution** | Self-improvement proposals with evaluation |
| **Knowledge base with RAG** | Versioned documents with search |
| **Full Python backend** | SQLAlchemy models, Alembic migrations, production DB (vs NvLabsOrg's JSON store) |
| **10 LLM adapters** | Direct API adapters for Anthropic, OpenAI, Ollama, Azure, Bedrock, Google (NvLabsOrg only does CLI subprocess) |

---

## Summary

NvLabsOrg is a **TypeScript-native orchestrator** focused on:
- Multi-agent CLI spawning with worktree isolation
- Real-time WebSocket streaming of agent output
- Visual pipeline builder
- Slash command UX

Our NVLabsCompany has a **richer backend** with:
- 10 direct LLM API adapters (not just CLI subprocess)
- Deep identity/soul system
- Production database (not just JSON files)
- Governance, budgets, approvals
- More hiring flexibility (manifests, team templates, archetypes)

**The key gap is real-time streaming and the orchestrator "leader + worker" pattern** — NvLabsOrg coordinates multiple agents working simultaneously on different parts of a task, while ours currently handles one agent chat at a time.
