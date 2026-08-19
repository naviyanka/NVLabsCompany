# NEXUS Cross-Repository Upgrade Plan

> Comprehensive analysis of 7 reference repositories identifying what can be extracted, adapted, replaced, or added to the NEXUS codebase.

---

## Executive Summary

After reviewing all 7 repos against the current NEXUS implementation, the most impactful upgrades fall into **4 priority tiers**:

| Priority | Category | Source | Impact |
|----------|----------|--------|--------|
| **P0** | CLI-Based Agent Execution (use installed CLIs) | NVLabsOrg | Transforms NEXUS from API-calling prototype to production multi-agent system |
| **P0** | Real LLM Provider Wiring | OpenCompany + current adapters | Makes agents actually functional |
| **P1** | Agent Templates + Phase Machine | NVLabsOrg | Instant team creation without manual config |
| **P1** | Guardrail Chain System | PraisonAI | Safety layer for autonomous execution |
| **P1** | Failure Alchemy (Learning from Failures) | AI-Company/Cronus | Powers the evolution engine with real data |
| **P2** | Enhanced Tool Access System | Paperclip | Enterprise-grade tool governance |
| **P2** | Decision Queue/Triage System | Paperclip | Production approval workflows |
| **P2** | 4-Layer Memory with Rule-Based Extraction | NVLabsOrg | Zero-cost memory intelligence |
| **P3** | A2A Protocol | Clawith | Cross-platform agent communication |
| **P3** | Durable Checkpoints | Clawith/OpenCompany | Crash recovery for long tasks |

---

## 1. WHAT TO ADD (New Capabilities)

### 1.1 CLI-Based Agent Backend (from NVLabsOrg) — P0

**What NEXUS is missing:** NEXUS's adapters call LLM APIs directly. NVLabsOrg demonstrates that the most powerful approach is to **spawn installed CLI agents** (Claude Code, Codex, Kiro, etc.) as subprocesses, because they come with their own tool use, file editing, and safety features built-in.

**What to add to NEXUS:**

```
src/nexus/adapters/cli_backend.py        — New CLIBackendAdapter (extends BaseAdapter)
src/nexus/adapters/cli_registry.py       — Auto-detect installed CLIs
src/nexus/adapters/cli_backends/
    claude_cli.py                        — Claude Code --output-format stream-json
    codex_cli.py                         — Codex exec --full-auto
    kiro_cli.py                          — kiro-cli chat --no-interactive
    gemini_cli.py                        — agy -p --output-format stream-json
    copilot_cli.py                       — copilot -p
    aider_cli.py                         — aider --message --yes --no-git
    opencode_cli.py                      — opencode run --format json
```

**Key patterns to port from NVLabsOrg:**
- `AIBackend` interface → extend NEXUS's existing `AgentAdapter` Protocol
- `detectBackends()` → `CLIRegistry.detect()` that runs `which`/`where` + version probing
- `buildArgs(prompt, opts)` → per-CLI argument construction with resume, model override, worktree
- `instructionPath` → each CLI reads its own convention file (`.claude/CLAUDE.md`, `AGENTS.md`, etc.)
- `stability` level (stable/beta/experimental) → drives routing decisions
- `guardType` (hooks/sandbox/flag/none) → informs the governance layer

**Why this is P0:** Without real CLI backends, NEXUS agents cannot actually do anything. The Claude Code adapter already exists in NEXUS as a subprocess spawner — extend that pattern to ALL backends with NVLabsOrg's proven interface.

---

### 1.2 Agent Templates System (from NVLabsOrg) — P1

**What NEXUS is missing:** Creating agents requires manual configuration. NVLabsOrg has 18 prebuilt Markdown agent templates that auto-sync to `~/.claude/agents/` on startup.

**What to add:**

```
src/nexus/templates/
    __init__.py
    registry.py              — Load, list, and sync templates
    sync.py                  — Sync templates to CLI agent directories
    agents/
        software-architect.md
        code-reviewer.md
        qa-engineer.md
        devops-engineer.md
        security-engineer.md
        product-manager.md
        technical-writer.md
        ui-designer.md
        data-engineer.md
        sre.md
        ... (18 total)
```

**Template format (from NVLabsOrg):**
```markdown
---
name: Software Architect
description: System design, architectural patterns, trade-off analysis.
---

# Software Architect

Design systems that balance competing concerns.

## Rules
1. No architecture astronautics
2. Trade-offs over best practices
3. Domain first, technology second

## Process
1. Domain discovery
2. Architecture selection
3. Quality attributes
```

**Integration with NEXUS:** When creating an agent with `role: "software-architect"`, auto-apply the matching template. Templates define the `soul_description` and `responsibilities` fields.

---

### 1.3 Phase Machine (from NVLabsOrg) — P1

**What NEXUS is missing:** The CompanyWorkflow has a fixed CEO→CTO→Engineer→QA pipeline. NVLabsOrg has a dynamic `PhaseMachine` with user-gated transitions:

```
CREATE → DESIGN → EXECUTE → COMPLETE → (loop back on feedback)
```

**What to add:**

```python
# src/nexus/orchestration/phase_machine.py

class TeamPhase(str, Enum):
    CREATE = "create"       # Team lead produces initial plan
    DESIGN = "design"       # Plan awaits human approval
    EXECUTE = "execute"     # Workers execute approved plan
    COMPLETE = "complete"   # Results delivered, awaiting feedback

class PhaseMachine:
    def check_plan_detected(self, leader_output: str) -> bool
    def approve_plan(self, leader_id: UUID) -> TeamPhase
    def check_final_result(self, leader_id: UUID) -> TeamPhase
    def handle_user_feedback(self, leader_id: UUID) -> TeamPhase
```

**Key insight from NVLabsOrg:** The DESIGN→EXECUTE transition requires **explicit human approval**. This maps perfectly to NEXUS's approval system. The plan detection uses a `[PLAN]` tag in leader output.

---

### 1.4 Guardrail Chain (from PraisonAI) — P1

**What NEXUS is missing:** No input/output validation layer between agents and tools.

**What to add:**

```python
# src/nexus/guardrails/
    __init__.py
    protocol.py          — GuardrailProtocol (validate_input, validate_output, validate_tool_call)
    chain.py             — GuardrailChain (composable, short-circuit, fail-closed)
    structural.py        — JSON schema validation, length limits, required fields
    policy.py            — Policy-based rules (blocked patterns, sensitive data)
    llm_guardrail.py     — LLM-powered semantic validation (optional, expensive)
    content_safety.py    — Content safety filters (from Cronus)
```

**Pattern from PraisonAI:**
```python
class GuardrailProtocol(Protocol):
    def validate_input(self, input_data: Any) -> tuple[bool, str | dict]: ...
    def validate_output(self, output_data: Any) -> tuple[bool, str | dict]: ...
    def validate_tool_call(self, tool_name: str, args: dict) -> tuple[bool, str | dict]: ...

class GuardrailChain:
    def __init__(self, guardrails: list[GuardrailProtocol], fail_open: bool = False): ...
    # Short-circuits on first failure; fail_open=True logs but allows
```

---

### 1.5 Failure Alchemy (from AI-Company/Cronus) — P1

**What NEXUS is missing:** The evolution system can detect failures but doesn't transform them into structured learning artifacts.

**What to add to `src/nexus/evolution/failure_alchemy.py`:**

```python
class FailureAlchemist:
    """Transforms failed tasks into three learning artifact types."""

    async def analyze_failure(self, task: Task, error: str, context: dict) -> FailureLearning:
        """Produces:
        - Antibody: Defense rule to prevent recurrence
        - Vaccine: Structured failure case for agent training
        - Catalyst: System improvement proposal
        """

@dataclass
class FailureLearning:
    antibody: str          # "Never run npm install without checking package.json exists"
    vaccine: dict          # {scenario, expected, actual, root_cause}
    catalyst: str | None   # "Propose adding file-existence check to pre-execution guardrails"
```

**Integration:** Feed FailureLearning artifacts into the existing `EvolutionObserver` → `ImprovementProposer` pipeline. Antibodies become guardrail rules. Vaccines feed evaluation benchmarks. Catalysts become evolution proposals.

---

### 1.6 Replay Engine (from AI-Company/Cronus) — P2

**What NEXUS is missing:** No way to reconstruct what happened during a task execution for debugging.

**What to add to `src/nexus/runtime/replay.py`:**

```python
class ReplayEngine:
    async def get_replay(self, task_id: UUID) -> TaskReplay:
        """Builds complete execution timeline with:
        - Lifecycle events (created, started, delegated, completed/failed)
        - All LLM calls with prompts/responses
        - Tool invocations with inputs/outputs
        - Delegation chain
        - Checkpoints (key decision points)
        - Cost accumulation over time
        """
```

---

### 1.7 Watchdog with Auto-Recovery (from AI-Company/Cronus) — P2

**What NEXUS is missing:** HeartbeatMonitor detects stale agents but doesn't auto-recover them.

**Enhance `src/nexus/runtime/heartbeat.py`:**

```python
class WatchdogRunner:
    """Background task that periodically checks all active agents."""

    async def patrol(self):
        # Stuck agents (executing > 30min) → reset to idle
        # Orphaned tasks (assigned to terminated agent) → reassign
        # Budget-exceeded agents → auto-pause
        # Circuit-broken agents → attempt half-open test after cooldown
```

---

### 1.8 Goal-Gated Loop with Independent Judge (from PraisonAI) — P2

**What NEXUS is missing:** No mechanism for agents to autonomously work toward a goal and know when they're done.

**What to add to `src/nexus/orchestration/goal_loop.py`:**

```python
class GoalLoop:
    """Runs an agent in a loop until an independent judge confirms goal completion."""

    async def execute(self, agent_id: UUID, goal: str, max_iterations: int = 10):
        for i in range(max_iterations):
            result = await self.execute_step(agent_id, goal)
            verdict = await self.judge_goal(goal, result)
            if verdict == "done":
                return result
            if self._consecutive_parse_failures >= 3:
                break  # Safety valve
        raise GoalNotAchievedError(...)

    async def judge_goal(self, goal: str, output: str) -> str:
        """Uses a SEPARATE cheap model to judge completion."""
        # Returns "done" or "continue" with reason
```

---

## 2. WHAT TO REPLACE (Existing NEXUS Code → Better Implementation)

### 2.1 Replace Simple Memory Hot Tier → 4-Layer Memory (from NVLabsOrg)

**Current NEXUS:** Hot tier is a plain Python dict, lost on restart.

**Replace with NVLabsOrg's 4-layer model:**

| Layer | Scope | Persistence | Content |
|-------|-------|-------------|---------|
| L0 | Conversation | Ephemeral (caller manages) | Sliding window of recent messages |
| L1 | Session | Persisted (ring buffer) | Structured task summaries extracted from output |
| L2 | Agent | Persisted | Per-agent learned facts with Jaccard dedup |
| L3 | Shared | Persisted | Cross-agent organizational knowledge |

**Key innovation:** Rule-based extraction (no LLM calls = zero token cost). Extract facts from agent stdout using regex/heuristics, deduplicate with Jaccard similarity, auto-promote frequently-reinforced L2 facts to L3.

**Files to modify:**
- `src/nexus/memory/store.py` → Add L1/L2/L3 layers with extraction
- New: `src/nexus/memory/extract.py` → Rule-based fact extraction from output
- New: `src/nexus/memory/dedup.py` → Jaccard similarity deduplication
- New: `src/nexus/memory/promotion.py` → L2→L3 promotion logic

---

### 2.2 Replace Basic TaskPlanner → Conductor Decide Pattern (from OpenCompany)

**Current NEXUS:** `TaskPlanner.decompose_task()` returns a single subtask passthrough.

**Replace with OpenCompany's Conductor "decide" pattern:**

```python
class ConductorExecutor:
    """Continuous scheduling loop that:
    1. Computes execution layers (topologically sorted parallel batches)
    2. Executes independent nodes in parallel (Fork/Join)
    3. On any node completion, immediately checks newly-ready dependents
    4. Uses distributed locking to prevent concurrent decides
    5. Has execution cache for idempotency
    6. Dead Letter Queue for permanently failed tasks
    """
```

This replaces the simple `ParallelExecutor` + `TaskPlanner` combination with a proper workflow engine.

---

### 2.3 Replace RetryTracker → Smart Escalation (from NVLabsOrg)

**Current NEXUS:** `RetryWithBudget` does exponential backoff + budget check.

**Enhance with NVLabsOrg's escalation protocol:**

```python
class SmartRetryTracker:
    def get_retry_prompt(self, task_id: UUID) -> str:
        """Returns retry prompt with:
        1. DIAGNOSE: Read error carefully, identify root cause
        2. FIX: Address root cause first
        3. VERIFY: Confirm fix works before moving on
        + 'Do NOT repeat the same approach that failed.'
        """

    def get_escalation(self, task_id: UUID) -> EscalationPrompt | None:
        """When all retries exhausted, returns structured escalation:
        - If SAME error repeats: 'PERMANENT BLOCKER, report to user'
        - If FIXABLE: 'Reassign to DIFFERENT team member'
        - If TOO LARGE: 'Break into smaller pieces'
        """
```

---

### 2.4 Replace Simple PolicyEngine → Risk-Based Command Approval (from NVLabsOrg)

**Current NEXUS:** GovernanceMiddleware has TODO stubs for policy evaluation.

**Replace with NVLabsOrg's concrete PolicyEngine:**

```python
SENSITIVE_PATHS = ["~/.ssh", "/etc", "~/.aws", "~/.gnupg"]
DANGEROUS_COMMANDS = [
    {"pattern": r"\bgit\s+push\b", "title": "Git Push", "risk": "med"},
    {"pattern": r"\brm\s+-rf?\b", "title": "File Deletion", "risk": "high"},
    {"pattern": r"\b(npm|pip)\s+install\b", "title": "Package Install", "risk": "med"},
    {"pattern": r"\bdocker\s+run\b", "title": "Docker Run", "risk": "high"},
]

def check_policy(command_text: str) -> PolicyCheck:
    # Returns {needs_approval, title, summary, risk_level}
```

---

## 3. WHAT TO MODIFY (Enhance Existing NEXUS Code)

### 3.1 Enhance BudgetEnforcer (from Paperclip)

**Add to existing `src/nexus/governance/budget_enforcer.py`:**
- `BudgetIncident` model — track every budget violation with details
- `cancelWorkForScope()` hook — auto-cancel running tasks when budget breached
- Lifetime window type (not just monthly)
- Multi-metric tracking (cost_cents AND tokens AND api_calls simultaneously)
- `pause_agent_on_breach` flag — auto-pause instead of just denying new requests

### 3.2 Enhance Decision System (from Paperclip)

**Add to existing governance models:**
- `DecisionBundle` — group related decisions for batch review
- `DecisionTriage` — decide-by dates, snooze until, priority routing
- `DecisionRetention` — archive lifecycle (auto-archive after N days)
- `DecisionNotificationOutbox` — reliable delivery of decision notifications
- Seed rules on queues — auto-route decisions based on type/agent/risk

### 3.3 Enhance Tool System (from Paperclip)

**Add to existing `src/nexus/tools/`:**
- `ToolConnection` model — unified representation of MCP remote, REST API, local stdio
- `ToolCatalogEntry` — per-tool metadata with risk levels (read/write/destructive)
- `ToolProfile` — named allow/deny lists assignable to agents
- `ToolPolicy` — priority-ordered policy rules evaluated at invocation time
- `ToolInvocation` audit table — every tool call recorded with timing/cost/result
- `ToolRuntimeSlot` — managed subprocess lifecycle for stdio tools

### 3.4 Enhance Skill System (from Paperclip)

**Add to existing `src/nexus/models/skill.py` and `src/nexus/services/skill_service.py`:**
- Skill test inputs + test runs (benchmark capabilities)
- Skill versions with content snapshots
- Skill sharing scopes (private/company/public)
- Skill fork tracking (derive from existing skills)
- Skill test templates (reusable evaluation harnesses)

### 3.5 Enhance Heartbeat System (from Paperclip)

**Replace simple `HeartbeatMonitor` with rich `HeartbeatRun` model:**
- Track process PID, exit code, signal
- Store stdout/stderr excerpts (truncated)
- Liveness state machine (healthy/suspected_stale/confirmed_dead)
- Continuation attempts counter
- Context snapshot at each heartbeat (what was the agent doing?)
- Session ID tracking (before/after for crash recovery)

### 3.6 Add Worktree Isolation (from NVLabsOrg)

**Add to existing `src/nexus/runtime/`:**

```python
# src/nexus/runtime/worktree.py

class WorktreeManager:
    """Git worktree isolation for parallel agent execution."""

    def create_worktree(self, repo_path: str, agent_id: str, agent_name: str) -> str | None
    def merge_worktree(self, repo_path: str, worktree_path: str, branch: str) -> MergeResult
    def revert_worktree_commit(self, repo_path: str, worktree_path: str) -> RevertResult
    def sync_worktree_to_main(self, repo_path: str, worktree_path: str) -> None
    def has_pending_changes(self, repo_path: str, worktree_path: str) -> bool
```

Each non-leader agent gets its own worktree branch. On task completion, changes are merged back to main with conflict detection.

---

## 4. WHAT TO KEEP AS-IS (NEXUS is Already Good)

These NEXUS components are already at or above the quality of the reference repos:

| Component | Why It's Good Enough |
|-----------|---------------------|
| `AgentAdapter` Protocol | Clean 11-method interface, matches plan exactly |
| `BaseAdapter` with credential scrubbing | Security-conscious, well-structured |
| `AdapterRegistry` factory pattern | Proper plugin architecture |
| `AgentLifecycleManager` state machine | Complete state transitions with DB persistence |
| `CycleGuard` (doom-loop prevention) | Equivalent to Clawith's cycle_guard.py |
| `EvolutionProposer` / `EvolutionSandbox` / `ProposalEvaluator` | Unique to NEXUS, well-designed |
| `ApprovalEngine` with auto-approve policies | Matches Paperclip's pattern |
| `TenantGuard` (multi-tenancy) | More thorough than most reference repos |
| `RollbackManager` with cascading rollback | Exceeds reference repo capabilities |
| `RateLimiter` (token bucket + sliding window) | Production-quality algorithm |
| Dashboard Office visualization | Beyond what any reference repo has |
| `BM25Retriever` | Equivalent to Cronus's implementation |

---

## 5. CONCRETE IMPLEMENTATION ROADMAP

### Sprint 1 (Critical Path — Make It Work)

| # | Task | Source | Files | Effort |
|---|------|--------|-------|--------|
| 1 | Wire real API keys into OpenAI/Anthropic adapters | NEXUS REMAINING-WORK-PLAN FIX-01 | `config.py`, `openai_adapter.py`, `anthropic_adapter.py` | S |
| 2 | Add CLI Backend Adapter (Claude Code first) | NVLabsOrg `ai-backend.ts` + `backends.ts` | New `cli_backend.py`, `cli_registry.py` | M |
| 3 | Implement CLI auto-detection | NVLabsOrg `detectBackends()` | `cli_registry.py` | S |
| 4 | Port 8 agent templates to Markdown | NVLabsOrg `agents/*.md` | New `templates/agents/` directory | S |
| 5 | Persist KillSwitch + RateLimiter to Redis/DB | NEXUS REMAINING-WORK-PLAN FIX-02 | `kill_switch.py`, `rate_limiter.py` | M |
| 6 | Generate + test Alembic migration | NEXUS REMAINING-WORK-PLAN FIX-03 | `alembic/versions/` | M |

### Sprint 2 (Safety + Intelligence)

| # | Task | Source | Files | Effort |
|---|------|--------|-------|--------|
| 7 | Implement GuardrailChain Protocol | PraisonAI `guardrails/` | New `src/nexus/guardrails/` | M |
| 8 | Add PolicyEngine for dangerous commands | NVLabsOrg `policy-engine.ts` | Enhance `governance/` | S |
| 9 | Implement FailureAlchemist | Cronus `failure_alchemy.py` | New `evolution/failure_alchemy.py` | M |
| 10 | Implement PhaseMachine | NVLabsOrg `phase-machine.ts` | New `orchestration/phase_machine.py` | M |
| 11 | Add smart retry with escalation | NVLabsOrg `retry.ts` | Enhance `orchestration/retry.py` | S |
| 12 | Add Watchdog auto-recovery | Cronus `watchdog.py` | Enhance `runtime/heartbeat.py` | M |

### Sprint 3 (Memory + Tools)

| # | Task | Source | Files | Effort |
|---|------|--------|-------|--------|
| 13 | Implement 4-layer memory (L0-L3) | NVLabsOrg `@bit-office/memory` | Refactor `memory/store.py` + new files | L |
| 14 | Add rule-based fact extraction | NVLabsOrg `extract.ts` | New `memory/extract.py` | M |
| 15 | Add Jaccard dedup for memory | NVLabsOrg `dedup.ts` | New `memory/dedup.py` | S |
| 16 | Enhance Tool model with connections/catalog | Paperclip `tool_access.ts` | Enhance `models/tool.py` | L |
| 17 | Add ToolInvocation audit table | Paperclip `tool_access.ts` | New model + migration | M |
| 18 | Add goal-gated loop with judge | PraisonAI `goal/loop.py` + `judge.py` | New `orchestration/goal_loop.py` | M |

### Sprint 4 (Production Hardening)

| # | Task | Source | Files | Effort |
|---|------|--------|-------|--------|
| 19 | Enhance budget with incidents + auto-pause | Paperclip `budgets.ts` | Enhance `governance/budget_enforcer.py` | M |
| 20 | Add decision triage/retention | Paperclip `decision_queues.ts` | New models + service | L |
| 21 | Add ReplayEngine | Cronus `replay_engine.py` | New `runtime/replay.py` | M |
| 22 | Implement worktree isolation | NVLabsOrg `worktree.ts` | New `runtime/worktree.py` | L |
| 23 | Add heartbeat_runs rich model | Paperclip `heartbeat_runs.ts` | Enhance models + service | M |
| 24 | Wire tenant isolation into all routes | NEXUS REMAINING-WORK-PLAN FIX-04 | All route files | L |

### Sprint 5 (Advanced Features)

| # | Task | Source | Files | Effort |
|---|------|--------|-------|--------|
| 25 | Add A2A protocol (notify/consult/delegate) | Clawith `a2a_runtime.py` | New `communication/a2a.py` | L |
| 26 | Implement durable checkpoints | Clawith + OpenCompany | New `runtime/checkpoint.py` | L |
| 27 | Add Conductor decide loop | OpenCompany `executor.py` | Replace `orchestration/parallel.py` | XL |
| 28 | Add skill test harness | Paperclip `company_skills.ts` | Enhance skill system | L |
| 29 | Add pipeline stages | Paperclip `pipelines.ts` | New `workflows/pipeline.py` | M |
| 30 | Implement LLM provider registry | OpenCompany `registry.py` | New `models_router/registry.py` | M |

---

## 6. SOURCE-TO-NEXUS MAPPING TABLE

| NEXUS Gap | Best Source Repo | Specific File/Pattern | Adaptation Strategy |
|-----------|-----------------|----------------------|-------------------|
| No real agent execution | NVLabsOrg | `orchestrator/src/ai-backend.ts` + `backends.ts` | Port interface to Python, keep subprocess spawning |
| No agent templates | NVLabsOrg | `orchestrator/agents/*.md` (18 files) | Copy directly, add Python loader |
| No phase-gated workflow | NVLabsOrg | `orchestrator/src/phase-machine.ts` | Port to Python dataclass + enum |
| No delegation depth tracking | NVLabsOrg | `orchestrator/src/delegation.ts` | Port TaskMeta pattern to Python |
| No guardrails | PraisonAI | `guardrails/protocols.py` + `chain.py` | Already Python — adapt directly |
| No doom-loop goal judge | PraisonAI | `goal/loop.py` + `judge.py` | Already Python — adapt directly |
| Simulated MCP | PraisonAI | `mcp/mcp.py` + transports | Already Python — replace MCPClient |
| No budget incidents | Paperclip | `schema/budget_incidents.ts` + `services/budgets.ts` | Port schema to SQLModel, port logic |
| Simple heartbeat | Paperclip | `schema/heartbeat_runs.ts` | Port rich schema to SQLModel |
| Basic tool access | Paperclip | `schema/tool_access.ts` (870 lines!) | Port enterprise tool governance |
| No skill testing | Paperclip | `schema/company_skills.ts` | Port test harness pattern |
| No decision triage | Paperclip | `schema/decision_queues.ts` | Port queue/triage/retention |
| No failure learning | Cronus | `loop/failure_alchemy.py` | Already Python — adapt directly |
| No execution replay | Cronus | `loop/replay_engine.py` | Already Python — adapt directly |
| No auto-recovery | Cronus | `loop/watchdog.py` | Already Python — adapt directly |
| No task scheduler | NVLabsOrg | `gateway/src/task-scheduler.ts` | Port cron-lite to Python |
| Memory lost on restart | NVLabsOrg | `packages/memory/src/` | Port 4-layer model to Python |
| No worktree isolation | NVLabsOrg | `orchestrator/src/worktree.ts` | Port git worktree management |
| No LLM provider registry | OpenCompany | `services/llm/registry.py` | Already Python — adapt |
| No conductor decide loop | OpenCompany | `services/execution/executor.py` | Port parallel Fork/Join pattern |
| No A2A protocol | Clawith | `agent_runtime/a2a_runtime.py` | Already Python — adapt |
| No durable checkpoints | Clawith | `agent_runtime/checkpointer.py` | Already Python — adapt |
| No cycle guard from DB | Clawith | `agent_runtime/cycle_guard.py` | Already Python — adapt |
| No trigger dispatch queue | Clawith | `trigger_runtime/dispatch.py` | Already Python — adapt |

---

## 7. RISK ASSESSMENT

| Risk | Mitigation |
|------|-----------|
| NVLabsOrg is TypeScript, porting takes time | Focus on patterns, not line-by-line translation. Key interfaces are simple. |
| PraisonAI code is Python but tightly coupled to its Agent class | Extract Protocol interfaces only, re-implement against NEXUS Agent model |
| Paperclip has 116 tables, scope creep danger | Only port the 5-6 tables that fill concrete NEXUS gaps |
| OpenCompany's Temporal dependency | Skip Temporal, keep the Conductor decide-loop pattern (pure async) |
| Clawith uses LangGraph deeply | Don't adopt LangGraph. Extract the STATE MACHINE PATTERN and checkpointing concept only |
| Feature overload | Follow sprint plan strictly. Each sprint produces a working system |

---

## 8. IMMEDIATE NEXT STEPS

1. **Start Sprint 1** — Wire real LLM API keys + add CLI backend adapter
2. **Create `src/nexus/adapters/cli_backend.py`** using NVLabsOrg's interface as reference
3. **Copy agent templates** from NVLabsOrg verbatim (they're MIT-licensed Markdown)
4. **Port GuardrailChain** from PraisonAI (already Python, minimal adaptation needed)
5. **Port FailureAlchemist** from Cronus (already Python, minimal adaptation needed)

The highest-leverage single change is **adding the CLI backend adapter** — it transforms NEXUS from a simulated prototype into a system that can actually execute real work through Claude Code, Codex, Kiro, and other installed AI CLIs.

---

## Appendix: License Compatibility

| Repo | License | Compatible with NEXUS (MIT)? |
|------|---------|------------------------------|
| NVLabsOrg | MIT | ✅ Yes — direct code reuse OK |
| Paperclip | MIT | ✅ Yes — schema patterns reusable |
| OpenCompany | Apache 2.0 | ✅ Yes — compatible with MIT |
| PraisonAI | MIT | ✅ Yes — direct code reuse OK |
| Clawith | Apache 2.0 | ✅ Yes — compatible with MIT |
| MetaGPT | MIT | ✅ Yes — direct code reuse OK |
| AI-Company/Cronus | MIT | ✅ Yes — direct code reuse OK |

All repos are license-compatible. Python code from PraisonAI, Clawith, and Cronus can be adapted with minimal rewriting. TypeScript code from NVLabsOrg and Paperclip requires porting but the patterns and interfaces translate cleanly.
