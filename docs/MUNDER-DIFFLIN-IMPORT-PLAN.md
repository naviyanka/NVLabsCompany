# Munder Difflin Feature Import Plan

> Comprehensive micro-phase breakdown for importing 16 high-value features from `munder-difflin` (TypeScript/Electron, MIT license) into the NEXUS Python/FastAPI codebase.

---

## Executive Summary

The munder-difflin project is a production-grade multi-agent desktop harness (Electron + TypeScript) that has solved many of the same coordination, budgeting, and lifecycle problems NEXUS is building toward. This plan extracts the **design patterns and logic** from 16 features, adapts them to Python/FastAPI idioms, and integrates them with NEXUS's existing module structure.

**Current NEXUS state:** 1,230 tests passing, ~117 files changed across Sprints 1-4, with working modules for orchestration, governance, memory, runtime, evolution, tools, workflows, communication, templates, and models_router.

**Import scope:** 5 sprints, 16 features, targeting ~45 new/modified Python files and ~350 new tests.

---

## Priority Justification

| Priority | Features | Rationale |
|----------|----------|-----------|
| **P0** (Sprint 5) | Hire Manifests, Real-time Cost Tracking, Advanced Circuit Breaker, Agent Provider Presets, Hive Protocol | These are the _operational backbone_ - without cost tracking and circuit breakers, autonomous agents are dangerous; without hire manifests and provider presets, spinning up agents requires manual configuration; the hive protocol enables actual multi-agent coordination |
| **P1** (Sprint 6) | Memory Reflector, Webhook Inbound Server, Control Registry, Closing Time Protocol, Knowledge Graph | Production hardening - auto-condense prevents memory bloat, webhooks enable external integration, operator control prevents runaway agents, graceful shutdown prevents data loss |
| **P2** (Sprint 7) | Skills Discovery, Semantic Memory, Tool Catalog, Integration Registry, Trigger System, SSRF Protection | Nice-to-have ecosystem features that complete the platform but are not blocking core operation |

---

## Sprint 5: Operational Backbone (P0 Features)

### Feature 1: Hire Manifests (Portable Agent Role Templates)

**Source:** `src/shared/hire.ts` + `docs/hires/manifests/` (20 manifests + 60 provider variants)

**What it is:** A JSON-based "hire manifest" spec (`munder-difflin/hire@1`) that describes a fully-configured agent role: name, provider, model, command flags, goal, capabilities, token budget. Manifests are portable, shareable, and validate untrusted input with a strict security model.

**Target files to create:**
```
src/nexus/templates/hire_manifest.py        # HireManifest model + validation
src/nexus/templates/hire_security.py        # Security validation (flag allowlist, model regex)
src/nexus/templates/hire_registry.py        # Manifest storage/lookup/import
src/nexus/api/routes/hire.py                # REST endpoints for manifest CRUD
data/manifests/                             # 20 default manifests (JSON) adapted for NEXUS
tests/test_hire_manifest.py                 # Validation tests
tests/test_hire_security.py                 # Security boundary tests
tests/test_hire_registry.py                 # Registry CRUD tests
```

**Dependencies:** Agent Provider Presets (Feature 4) for provider validation

**Effort estimate:** 1.5 days

**Key adaptation patterns:**

```python
# src/nexus/templates/hire_manifest.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import re

HIRE_SPEC_V1 = "nexus/hire@1"
MODEL_RE = re.compile(r"^[A-Za-z0-9 ._()[\]/:@+-]{1,80}$")
FLAG_RE = re.compile(r"^[A-Za-z0-9._/=:,@+-]{1,100}$")
SAFE_FLAG_NAMES = frozenset(["--model", "--max-turns", "--output-format", "--verbose"])

class HireManifest(BaseModel):
    spec: str = HIRE_SPEC_V1
    name: str = Field(..., min_length=1, max_length=40)
    description: Optional[str] = Field(None, max_length=200)
    goal: Optional[str] = Field(None, max_length=4000)
    provider: Optional[str] = None  # validated against known providers
    model: Optional[str] = Field(None, max_length=80)
    command_flags: list[str] = Field(default_factory=list, max_length=16)
    capabilities: list[str] = Field(default_factory=list, max_length=12)
    isolate: bool = False
    token_cap: Optional[int] = Field(None, gt=0, le=10_000_000_000)
    author: Optional[str] = Field(None, max_length=80)
    homepage: Optional[str] = Field(None, max_length=300)

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not MODEL_RE.match(v):
            raise ValueError("model contains disallowed characters")
        return v

    @field_validator("command_flags")
    @classmethod
    def validate_flags(cls, flags: list[str]) -> list[str]:
        for i, f in enumerate(flags):
            if not FLAG_RE.match(f):
                raise ValueError(f"flag {f!r} contains disallowed characters")
            if i == 0 and not f.startswith("-"):
                raise ValueError("first flag must start with -")
            if f.startswith("-") and f.split("=", 1)[0].lower() not in SAFE_FLAG_NAMES:
                raise ValueError(f"flag {f!r} not in safe-flag allowlist")
        return flags
```

**Acceptance criteria:**
- [ ] `HireManifest` Pydantic model with all fields from the spec
- [ ] Flag-allowlist security validation rejects unsafe flags
- [ ] Model regex rejects shell metacharacters
- [ ] Registry supports CRUD operations and file-based storage
- [ ] 20 default manifests converted to NEXUS provider naming
- [ ] REST API for list/get/import/validate manifests
- [ ] All tests pass with coverage of security edge cases

---

### Feature 2: Real-time Cost Tracking (Per-Model Pricing)

**Source:** `src/main/pricing.ts`

**What it is:** A per-model-family pricing table (USD per million tokens) with input/output/cache-read/cache-write rates. Provides `estimate_cost_usd()` for offline cost estimation and `price_for()` model-family resolution. Designed as the ONE source of truth for per-model pricing.

**Target files to create/modify:**
```
src/nexus/models_router/pricing.py          # ModelPrice, price tables, estimation
src/nexus/models_router/cost_tracker.py     # Modify: integrate pricing into live tracking
tests/test_pricing.py                       # Unit tests for price resolution + estimation
```

**Dependencies:** None (standalone utility, enhances existing cost_tracker.py)

**Effort estimate:** 0.5 days

**Key adaptation patterns:**

```python
# src/nexus/models_router/pricing.py
from dataclasses import dataclass
from typing import Optional
import re

@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens for one model family."""
    input_per_m: float
    output_per_m: float
    cache_read_per_m: float
    cache_write_per_m: float

# Anthropic list prices, USD per million tokens
OPUS = ModelPrice(input_per_m=15.0, output_per_m=75.0, cache_read_per_m=1.5, cache_write_per_m=18.75)
SONNET = ModelPrice(input_per_m=3.0, output_per_m=15.0, cache_read_per_m=0.3, cache_write_per_m=3.75)
HAIKU = ModelPrice(input_per_m=0.8, output_per_m=4.0, cache_read_per_m=0.08, cache_write_per_m=1.0)

# OpenAI
GPT4O = ModelPrice(input_per_m=2.5, output_per_m=10.0, cache_read_per_m=1.25, cache_write_per_m=0.0)
GPT4O_MINI = ModelPrice(input_per_m=0.15, output_per_m=0.6, cache_read_per_m=0.075, cache_write_per_m=0.0)
O1 = ModelPrice(input_per_m=15.0, output_per_m=60.0, cache_read_per_m=7.5, cache_write_per_m=0.0)

DEFAULT_PRICE = SONNET  # fallback when model unknown

_VARIANT_SUFFIX_RE = re.compile(r"\[[^\]]*\]\s*$")

def normalize_model(model: Optional[str]) -> str:
    """Strip variant suffix so model-id[1m] resolves to base family."""
    return _VARIANT_SUFFIX_RE.sub("", (model or "").strip())

def price_for(model: Optional[str]) -> ModelPrice:
    """Resolve a model id to its price row by family, falling back to Sonnet."""
    m = normalize_model(model).lower()
    if "opus" in m: return OPUS
    if "haiku" in m: return HAIKU
    if "sonnet" in m: return SONNET
    if "gpt-4o-mini" in m: return GPT4O_MINI
    if "gpt-4o" in m or "gpt-4" in m: return GPT4O
    if "o1" in m or "o3" in m: return O1
    return DEFAULT_PRICE

@dataclass
class TokenSplit:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

def estimate_cost_usd(model: Optional[str], tokens: TokenSplit) -> float:
    """Estimate USD cost for a token split using the model's fallback price row."""
    p = price_for(model)
    return (
        (tokens.input_tokens / 1_000_000) * p.input_per_m
        + (tokens.output_tokens / 1_000_000) * p.output_per_m
        + (tokens.cache_read_tokens / 1_000_000) * p.cache_read_per_m
        + (tokens.cache_write_tokens / 1_000_000) * p.cache_write_per_m
    )
```

**Acceptance criteria:**
- [ ] `ModelPrice` dataclass with input/output/cache pricing
- [ ] Price tables for Anthropic (Opus/Sonnet/Haiku), OpenAI (GPT-4o/mini/o1), and Gemini families
- [ ] `normalize_model()` strips variant suffixes
- [ ] `price_for()` resolves model family by keyword matching
- [ ] `estimate_cost_usd()` computes costs from token splits
- [ ] Integration point with existing `cost_tracker.py`
- [ ] Tests cover all model families plus unknown/None fallback

---

### Feature 3: Advanced Circuit Breaker (Velocity/Loop/Cost Detection)

**Source:** `src/main/breaker.ts`

**What it is:** A sophisticated circuit breaker with an escalation ladder (`healthy -> steering -> constrained -> stopped`), multiple trip conditions (repeated tool calls, error storms, token velocity spikes, cost caps, no-progress detection), per-agent state tracking, and compaction-awareness. Escalates one level per beat, de-escalates one level per healthy beat.

**Target files to modify:**
```
src/nexus/governance/circuit_breaker_advanced.py   # New: full-featured CircuitBreaker class
src/nexus/governance/breaker_types.py              # New: BreakerLevel, BreakerState, BreakerDecision
tests/test_circuit_breaker_advanced.py             # Comprehensive trip-condition tests
```

**Dependencies:** Real-time Cost Tracking (Feature 2) for cost-cap evaluation

**Effort estimate:** 1.5 days

**Key adaptation patterns:**

```python
# src/nexus/governance/breaker_types.py
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Optional

class BreakerLevel(IntEnum):
    HEALTHY = 0
    STEERING = 1
    CONSTRAINED = 2
    STOPPED = 3

class BreakerAction(str, Enum):
    NONE = "none"
    STEER = "steer"
    CONSTRAIN = "constrain"
    STOP = "stop"

@dataclass
class BreakerState:
    agent_id: str
    level: BreakerLevel
    reason: str
    ts: float  # timestamp

@dataclass
class BreakerDecision:
    state: BreakerState
    action: BreakerAction
    changed: bool  # True when level changed since previous beat

@dataclass
class BreakerInput:
    agent_id: str
    sample: Optional["AgentUsageSample"]  # cumulative usage snapshot
    progressing: bool  # file-mtime coordination signal


# src/nexus/governance/circuit_breaker_advanced.py
class AdvancedCircuitBreaker:
    """Multi-signal circuit breaker with escalation ladder.

    Trip conditions:
      (a) Repeated identical tool calls (loop detection)
      (b) Error storms (consecutive API errors)
      (c) Per-agent token cap exceeded
      (d) Floor-wide cost cap exceeded (blame top spender)
      (e) Token velocity spike (output tokens/min)
      (f) No-progress: burning tokens without coordinating (debounced)

    Escalation: one level per tick, never jumps.
    De-escalation: one level per healthy tick.
    Hard stop: configurable (off by default, caps at CONSTRAINED).
    Compaction-aware: exempts velocity trips during context compaction.
    """

    def __init__(self, config_getter: Callable[[], BreakerConfig]):
        self._config_getter = config_getter
        self._agents: dict[str, _AgentBreakerState] = {}

    def tick(self, inputs: list[BreakerInput], now_ms: float) -> list[BreakerDecision]:
        """Evaluate all agents for this beat. Returns one decision per agent."""
        ...

    def record_tool_use(self, agent_id: str, tool_name: str, tool_input: Any) -> None:
        """Track tool calls for loop detection."""
        ...

    def record_error(self, agent_id: str) -> None:
        """Track API errors for storm detection."""
        ...

    def record_compact_start(self, agent_id: str) -> None:
        """Exempt velocity trips during compaction."""
        ...

    def forget(self, agent_id: str) -> None:
        """Drop state for archived agent."""
        ...
```

**Acceptance criteria:**
- [ ] Four-level escalation ladder (healthy/steering/constrained/stopped)
- [ ] Six distinct trip conditions, each testable in isolation
- [ ] Per-beat evaluation with escalation-only action emission
- [ ] Compaction exemption window prevents false positives during context compaction
- [ ] No-progress debouncing (N consecutive beats before trigger)
- [ ] Floor-wide cost cap blames single top spender
- [ ] Per-agent token caps
- [ ] `forget()` prevents state leaks from archived agents
- [ ] Tests cover each trip condition independently + combined scenarios

---

### Feature 4: Agent Provider Presets (11 CLI Metadata)

**Source:** `src/shared/agentProvider.ts`

**What it is:** A registry of 11 agent provider presets (Claude, Codex, Grok, Kimi, Antigravity/Gemini, Qwen, OpenCode, Crush, Pi, Copilot, Custom) with full metadata: default command, auto-mode flags, model flags, hive-awareness, hook bridges, inbox capability, install commands, resume support, and recommended orchestrator models.

**Target files to create/modify:**
```
src/nexus/adapters/provider_presets.py      # AgentProviderPreset model + 11 presets
src/nexus/adapters/__init__.py              # Export presets
tests/test_provider_presets.py              # Preset validation + lookup tests
```

**Dependencies:** None (standalone registry)

**Effort estimate:** 1 day

**Key adaptation patterns:**

```python
# src/nexus/adapters/provider_presets.py
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

class AgentProviderID(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    GROK = "grok"
    KIMI = "kimi"
    ANTIGRAVITY = "antigravity"
    QWEN = "qwen"
    OPENCODE = "opencode"
    CRUSH = "crush"
    PI = "pi"
    COPILOT = "copilot"
    CUSTOM = "custom"

@dataclass(frozen=True)
class AgentProviderPreset:
    id: AgentProviderID
    label: str
    default_command: str
    auto_mode_flag: str
    supports_model: bool
    model_flag: Optional[str] = None
    hive_aware: bool = False
    can_receive_inbox: bool = False
    hook_bridge: Optional[str] = None
    recommended_orchestrator_model: Optional[str] = None
    resume_flag: Optional[str] = None
    install_command: Optional[str] = None
    docs_url: Optional[str] = None
    non_interactive_env: dict[str, str] = field(default_factory=dict)

PROVIDER_PRESETS: dict[AgentProviderID, AgentProviderPreset] = {
    AgentProviderID.CLAUDE: AgentProviderPreset(
        id=AgentProviderID.CLAUDE,
        label="Claude Code",
        default_command="claude",
        auto_mode_flag="--permission-mode bypassPermissions",
        supports_model=True,
        model_flag="--model",
        hive_aware=True,
        can_receive_inbox=True,
        recommended_orchestrator_model="claude-opus-4-8[1m]",
        resume_flag="--resume",
        install_command="npm install -g @anthropic-ai/claude-code",
        docs_url="https://docs.claude.com/en/docs/claude-code",
    ),
    AgentProviderID.CODEX: AgentProviderPreset(
        id=AgentProviderID.CODEX,
        label="Codex (GPT)",
        default_command="codex",
        auto_mode_flag="--dangerously-bypass-approvals-and-sandbox",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=True,
        hook_bridge="codex",
        recommended_orchestrator_model="gpt-5-codex",
        install_command="npm install -g @openai/codex",
        docs_url="https://github.com/openai/codex",
        non_interactive_env={"CODEX_NON_INTERACTIVE": "1"},
    ),
    # ... remaining 9 presets follow same pattern
}

def get_preset(provider_id: AgentProviderID) -> AgentProviderPreset:
    return PROVIDER_PRESETS.get(provider_id, PROVIDER_PRESETS[AgentProviderID.CLAUDE])
```

**Acceptance criteria:**
- [ ] All 11 provider presets defined with full metadata
- [ ] `AgentProviderID` enum for type-safe references
- [ ] `get_preset()` lookup with fallback to Claude
- [ ] Integration with existing adapter system (adapters can reference presets)
- [ ] Tests verify all presets have required fields
- [ ] Tests verify preset metadata matches expected values for key providers

---

### Feature 5: Hive Protocol (File-Based Agent Coordination)

**Source:** `src/main/hive.ts` + `HIVE.md`

**What it is:** A file-based multi-agent coordination layer operating under a single directory. Per-agent workspaces (identity, memory, inbox, outbox, cursor), a shared registry, blackboard, task ledger, and append-only event log. A router drains each agent's outbox into recipients' inboxes. Single-committer git history. Message protocol with structured acts (request/inform/propose/query/agree/refuse/done).

**Target files to create:**
```
src/nexus/communication/hive_protocol.py    # HiveMessage, MessageAct, protocol types
src/nexus/communication/hive_manager.py     # HiveManager: workspace, registry, routing
src/nexus/communication/hive_router.py      # Message routing (outbox->inbox drain)
src/nexus/communication/hive_task.py        # HiveTask: kanban-style task ledger
src/nexus/api/routes/hive.py                # REST endpoints for hive operations
tests/test_hive_protocol.py                 # Protocol message tests
tests/test_hive_manager.py                  # Workspace + registry tests
tests/test_hive_router.py                   # Routing logic tests
```

**Dependencies:** Agent Provider Presets (Feature 4) for agent metadata

**Effort estimate:** 2 days

**Key adaptation patterns:**

```python
# src/nexus/communication/hive_protocol.py
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class MessageAct(str, Enum):
    REQUEST = "request"
    INFORM = "inform"
    PROPOSE = "propose"
    QUERY = "query"
    AGREE = "agree"
    REFUSE = "refuse"
    DONE = "done"

class HiveMessage(BaseModel):
    id: str = Field(default_factory=lambda: secrets.token_hex(12))
    conversation: str
    in_reply_to: Optional[str] = None
    from_agent: str = Field(alias="from")
    to_agent: str = Field(alias="to")  # agent_id, "god", or "broadcast"
    act: MessageAct
    subject: str
    body: str
    hops: int = 0
    requires_reply: bool = False
    needs_human: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    GONE = "gone"

class HiveAgentMeta(BaseModel):
    id: str
    name: str
    provider: Optional[str] = None
    role: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    cwd: str = ""
    is_god: bool = False
    status: AgentStatus = AgentStatus.IDLE
    last_seen: float = 0.0
    archived: bool = False


# src/nexus/communication/hive_manager.py
class HiveManager:
    """File-based multi-agent coordination layer.

    Directory layout:
      <hive_root>/
        registry.json          # Agent metadata
        board.md               # Shared blackboard
        log.jsonl              # Append-only event log
        agents/<id>/
          identity.md          # Agent role/mission
          memory.md            # Agent long-term memory
          inbox/               # Pending messages
          inbox/.done/         # Processed messages
          outbox/              # Outgoing messages
          outbox/.sent/        # Delivered messages
          cursor.json          # Agent state cursor
    """

    def __init__(self, root: Path):
        self._root = root
        self._ensure_structure()

    def register_agent(self, meta: HiveAgentMeta) -> None: ...
    def send(self, msg: HiveMessage, sender: str) -> None: ...
    def route(self) -> list[tuple[HiveMessage, list[str]]]: ...
    def registry(self) -> dict[str, HiveAgentMeta]: ...
    def append_log(self, event: dict) -> None: ...
```

**Acceptance criteria:**
- [ ] `HiveMessage` with full protocol (7 message acts, conversation threading)
- [ ] `HiveManager` creates and maintains per-agent directory structure
- [ ] `HiveRouter` drains outbox messages to correct inbox destinations
- [ ] Broadcast support (to="broadcast" fans out to all active agents)
- [ ] Agent registration with status tracking
- [ ] Task ledger (HiveTask) with todo/doing/blocked/done states
- [ ] Append-only event log (JSONL format)
- [ ] REST API for sending messages, querying registry, viewing tasks
- [ ] Tests for routing, broadcasting, conversation threading

---

## Sprint 6: Production Hardening (P1 Features)

### Feature 6: Memory Reflector (Auto-Condense)

**Source:** `src/main/reflect.ts`

**What it is:** An automatic memory condensation service. When an agent's `memory.md` crosses a size/section threshold, the reflector: (1) backs up the file, (2) uses a cheap LLM (Haiku) to summarize evicted sections while preserving durable facts, (3) verifies the rewrite structurally, (4) atomically swaps the file. Safety-first: backup-first, verify-dont-trust gate, atomic swap.

**Target files to create:**
```
src/nexus/memory/reflector.py               # MemoryReflector service
src/nexus/memory/reflector_types.py         # ReflectSettings, ReflectResult, Parsed
src/nexus/memory/reflector_helpers.py       # parse_memory, rebuild, verify (pure functions)
tests/test_memory_reflector.py              # Unit tests for helpers + integration tests
tests/test_memory_reflector_helpers.py      # Pure function tests
```

**Dependencies:** Memory module (existing), Models Router (for LLM call)

**Effort estimate:** 1.5 days

**Key adaptation patterns:**

```python
# src/nexus/memory/reflector_helpers.py
BUDGET_BYTES = 131_072  # 128 KB
PINNED_HEADING = "## Durable facts (pinned)"
CONDENSED_HEADING = "## Condensed history"
RECENT_HEADING = "## Recent"

@dataclass
class Section:
    heading: str
    body: str

@dataclass
class ParsedMemory:
    header: str
    pinned: Optional[str]
    condensed: Optional[str]
    recent: list[Section]

def parse_memory(text: str) -> ParsedMemory:
    """Split memory.md into the three canonical regions."""
    ...

def rebuild(header: str, pinned: list[str], condensed: str, keep: list[Section]) -> str:
    """Reassemble the canonical 3-region file."""
    ...

def verify(rebuilt: str, old_bytes: int, old_pinned_lines: list[str], ...) -> tuple[bool, str]:
    """Verify-dont-trust gate. Returns (ok, reason)."""
    ...
```

**Acceptance criteria:**
- [ ] `parse_memory()` correctly splits structured and legacy flat files
- [ ] `rebuild()` produces the canonical 3-region format
- [ ] `verify()` gate rejects: structure-missing, too-small, empty-condensed, not-smaller, pinned-dropped, recent-altered
- [ ] Reflector creates backup before any modification
- [ ] Atomic file write (temp + rename)
- [ ] Threshold-based triggering (bytes OR section count)
- [ ] Integration with existing memory module's layered storage
- [ ] Tests for parse/rebuild round-trip, verify gate edge cases

---

### Feature 7: Webhook Inbound Server

**Source:** `src/main/webhook.ts`

**What it is:** A generic, secret-gated inbound HTTP server that turns external POSTs into hive work. Features: per-endpoint secrets (constant-time comparison), JSON schema validation, rate limiting (global + per-endpoint), capability tokens for status polling, SSRF protection, tunneling support.

**Target files to create:**
```
src/nexus/communication/webhook_server.py   # WebhookServer: endpoints, auth, routing
src/nexus/communication/webhook_types.py    # WebhookEndpoint, WebhookInbound, WebhookDispatch
src/nexus/api/routes/webhooks.py            # REST endpoints for webhook management
tests/test_webhook_server.py                # Auth, rate limit, schema validation tests
```

**Dependencies:** Hive Protocol (Feature 5) for task creation, Trigger System (Feature 15) for schema validation

**Effort estimate:** 1.5 days

**Key adaptation patterns:**

```python
# src/nexus/communication/webhook_server.py
import hmac
import secrets
from fastapi import APIRouter, Request, HTTPException, Depends
from starlette.responses import JSONResponse

class WebhookServer:
    """Secret-gated inbound HTTP API for external integrations.

    Security properties:
    - Constant-time secret comparison (hmac.compare_digest)
    - Unknown endpoint ids answered identically to wrong secrets (no enumeration)
    - Secrets never logged, echoed, or forwarded
    - Body cap + fixed-window rate limiting
    - Capability tokens for status polling (192-bit, unguessable)
    """

    def __init__(self, max_body_bytes: int = 64 * 1024):
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._rate_windows: dict[str, list[float]] = {}
        self._decoy_secret = secrets.token_hex(32)

    async def handle_post(self, endpoint_id: str, request: Request) -> JSONResponse:
        """Validate secret, enforce rate limit, validate schema, dispatch."""
        ...

    def _constant_time_verify(self, provided: str, expected: str) -> bool:
        """Timing-safe secret comparison, length-guarded."""
        return hmac.compare_digest(
            provided.encode("utf-8"),
            expected.encode("utf-8")
        )
```

**Acceptance criteria:**
- [ ] Per-endpoint secret with constant-time verification
- [ ] Unknown endpoint ids produce identical response to wrong secret (no enumeration)
- [ ] JSON schema validation of inbound bodies
- [ ] Fixed-window rate limiting (global + per-endpoint)
- [ ] Capability token minting + single-task status lookup
- [ ] Body size cap enforced before parsing
- [ ] Integration with hive for task creation
- [ ] Tests for timing safety, rate limits, schema validation, token lookup

---

### Feature 8: Control Registry (Operator Control)

**Source:** `src/main/control.ts`

**What it is:** Per-agent operator control state that enables runtime intervention without typing into terminals. Supports: pause (deny all tool calls), gate specific tools, steer (inject guidance text at next opportunity), halt (graceful stop at next boundary), auto-delivery pause.

**Target files to create:**
```
src/nexus/governance/control_registry.py    # ControlRegistry class
src/nexus/api/routes/control.py             # REST endpoints for operator commands
tests/test_control_registry.py              # Control state + decision tests
```

**Dependencies:** None (standalone, consumed by runtime)

**Effort estimate:** 1 day

**Key adaptation patterns:**

```python
# src/nexus/governance/control_registry.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AgentControlSnapshot:
    paused: bool = False
    halted: bool = False
    auto_delivery_paused: bool = False
    gated_tools: list[str] = field(default_factory=list)
    pending_steers: int = 0

class ControlRegistry:
    """Per-agent operator control over running agents.

    Enables runtime intervention without terminal access:
    - pause: deny ALL tool calls for an agent
    - gate_tool: deny a specific tool
    - steer: inject guidance text at next hook boundary
    - halt: graceful stop at next boundary
    - auto_delivery_paused: hold inbox messages
    """

    def __init__(self):
        self._agents: dict[str, _AgentControl] = {}

    def pause(self, agent_id: str, on: bool) -> None: ...
    def gate_tool(self, agent_id: str, tool: str, on: bool) -> None: ...
    def steer(self, agent_id: str, text: str) -> None: ...
    def halt(self, agent_id: str) -> None: ...
    def resume(self, agent_id: str) -> None: ...

    def tool_decision(self, agent_id: str, tool: str) -> tuple[bool, Optional[str]]:
        """Returns (deny, reason) for a tool call."""
        ...

    def take_steer(self, agent_id: str) -> Optional[str]:
        """Dequeue one pending steer note, or None."""
        ...

    def snapshot(self, agent_id: str) -> AgentControlSnapshot: ...
```

**Acceptance criteria:**
- [ ] Pause/resume per agent (denies all tool calls when paused)
- [ ] Per-tool gating (deny specific tools while allowing others)
- [ ] Steer queue (FIFO, consumed once per boundary, max 10KB per entry)
- [ ] Halt flag (consumed by runtime for graceful stop)
- [ ] Auto-delivery pause (holds inbox messages)
- [ ] `tool_decision()` returns deny+reason consumed by tool executor
- [ ] Snapshot for dashboard display
- [ ] REST API for all operator commands
- [ ] Tests for each control type independently + combined

---

### Feature 9: Closing Time Protocol (Graceful Shutdown)

**Source:** `src/main/closingTime.ts`

**What it is:** A graceful multi-agent shutdown protocol. When triggered: (1) mail the god agent a shutdown brief, (2) god broadcasts to all workers, (3) each worker parks WIP, saves memory, sends ACK, (4) god verifies all ACKs, sends COMPLETE, (5) system tears down. Includes timeout handling, cancellation, and steer-based interruption for deeply busy agents.

**Target files to create:**
```
src/nexus/runtime/closing_time.py           # ClosingTimeController
src/nexus/api/routes/shutdown.py            # REST endpoints for graceful shutdown
tests/test_closing_time.py                  # Protocol phase tests
```

**Dependencies:** Hive Protocol (Feature 5), Control Registry (Feature 8)

**Effort estimate:** 1 day

**Key adaptation patterns:**

```python
# src/nexus/runtime/closing_time.py
import asyncio
import re
from enum import Enum
from dataclasses import dataclass

class ClosingTimePhase(str, Enum):
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETE = "complete"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

ACK_RE = re.compile(r"CLOSING[-_\s]*TIME[-_\s]*ACK", re.IGNORECASE)
COMPLETE_RE = re.compile(r"CLOSING[-_\s]*TIME[-_\s]*COMPLETE", re.IGNORECASE)
TIMEOUT_SECONDS = 360  # 6 minutes

@dataclass
class ClosingTimeEvent:
    phase: ClosingTimePhase
    acked: int
    total: int

class ClosingTimeController:
    """Graceful multi-agent shutdown protocol.

    Protocol:
    1. Human triggers closing time
    2. Mail god with shutdown brief (workers list)
    3. God broadcasts to team, workers park WIP + save memory + ACK
    4. God collects ACKs, saves own state, sends COMPLETE
    5. System verifies all ACKs received, then tears down

    Safety: premature COMPLETE is rejected if live workers are missing ACKs.
    Steer notes reach deeply-busy agents at their next hook boundary.
    """

    def __init__(self, hive_manager, control_registry, get_live_agents, on_concluded):
        ...

    async def start(self) -> dict: ...
    def cancel(self) -> None: ...
    def on_routed(self, msg, targets: list[str]) -> None: ...
```

**Acceptance criteria:**
- [ ] Full protocol lifecycle (started -> progress -> complete -> teardown)
- [ ] ACK tracking per worker (forgiving regex: "Closing Time Ack" counts)
- [ ] COMPLETE only honored from god agent
- [ ] Premature COMPLETE rejected when live workers missing ACKs
- [ ] Dead workers (terminal closed) excused from ACK requirement
- [ ] Timeout after 6 minutes with UI notification
- [ ] Cancellation: clears steers, informs god, resumes normal operation
- [ ] Steer-based interrupt for deeply busy agents
- [ ] Tests for each phase transition + edge cases

---

### Feature 10: Knowledge Graph

**Source:** `src/main/knowledge.ts` + `src/main/kg-core.cjs`

**What it is:** A file-backed enterprise knowledge graph with document ingestion (file or inline text), BM25 keyword search, per-document metadata (title, source, modality, tags, MIME), chunk-based storage, and stats reporting. Agents interact via a CLI sidecar.

**Target files to create/modify:**
```
src/nexus/knowledge/graph.py                # KnowledgeManager (CRUD + search)
src/nexus/knowledge/indexer.py              # Document chunking + indexing
src/nexus/knowledge/types.py                # KgMeta, KgHit, KnowledgeStatus
src/nexus/api/routes/knowledge.py           # REST endpoints
tests/test_knowledge_graph.py               # Ingest + search + CRUD tests
```

**Dependencies:** Existing memory module (for retriever patterns), existing BM25 retriever

**Effort estimate:** 1.5 days

**Key adaptation patterns:**

```python
# src/nexus/knowledge/graph.py
from pathlib import Path
from typing import Optional

class KnowledgeManager:
    """File-backed knowledge graph with document ingestion and search.

    Store layout:
      <root>/
        index.json            # Document metadata index
        chunks/               # Per-document chunk files
          <doc_id>/
            meta.json
            chunk_0.txt
            chunk_1.txt
            ...
    """

    def __init__(self, root: Path, enabled: bool = True):
        self._root = root
        self._enabled = enabled

    def ingest_file(self, src_path: Path, **opts) -> IngestResult: ...
    def ingest_text(self, text: str, **opts) -> IngestResult: ...
    def search(self, query: str, limit: int = 10) -> list[KgHit]: ...
    def list_docs(self) -> list[KgMeta]: ...
    def get_doc(self, doc_id: str) -> Optional[tuple[KgMeta, str]]: ...
    def remove_doc(self, doc_id: str) -> bool: ...
    def stats(self) -> KnowledgeStatus: ...
```

**Acceptance criteria:**
- [ ] Document ingestion from file path or inline text
- [ ] Automatic chunking with configurable chunk size
- [ ] BM25 keyword search across all chunks
- [ ] Per-document metadata (title, source, modality, tags, timestamps)
- [ ] Document CRUD (list, get, remove)
- [ ] Stats reporting (doc count, chunk count, by modality)
- [ ] Graceful degradation when disabled
- [ ] Integration with existing BM25 retriever in memory module
- [ ] REST API for all operations
- [ ] Tests for ingest, search relevance, CRUD operations

---

## Sprint 7: Ecosystem Completion (P2 Features)

### Feature 11: Skills Discovery + Catalog

**Source:** `src/main/skills.ts`

**What it is:** A dual system: (1) LOCAL discovery that walks CLI-specific directories to find installed skills (Claude Code `SKILL.md` with YAML frontmatter, OpenCode plugins, Codex configs), and (2) a CATALOG browser fetching community skill listings from GitHub repos. Discovery-only - installing is the user's decision.

**Target files to create:**
```
src/nexus/tools/skills_discovery.py         # Local skill scanner
src/nexus/tools/skills_catalog.py           # Remote catalog browser + cache
src/nexus/tools/skills_types.py             # LocalSkill, CatalogSkill models
src/nexus/api/routes/skills.py              # REST endpoints
tests/test_skills_discovery.py              # Scanner tests with mock directories
tests/test_skills_catalog.py                # Catalog parsing tests
```

**Dependencies:** Agent Provider Presets (Feature 4) for provider-specific paths

**Effort estimate:** 1 day

**Key adaptation patterns:**

```python
# src/nexus/tools/skills_types.py
@dataclass
class LocalSkill:
    id: str
    name: str
    description: str
    provider: str  # "claude", "opencode", "codex"
    scope: str     # "user", "project", "bundled"
    path: str

@dataclass
class CatalogSkill:
    name: str
    description: str
    url: str
    category: str
    owner: str

def parse_skill_frontmatter(md: str) -> dict[str, str]:
    """Extract name + description from YAML frontmatter in SKILL.md."""
    ...
```

**Acceptance criteria:**
- [ ] Scan Claude Code skill directories (user + project scope)
- [ ] Parse SKILL.md YAML frontmatter (name, description, block scalar support)
- [ ] Catalog fetching with disk cache (stale cache on network failure)
- [ ] REST API for listing local skills and browsing catalog
- [ ] Tests with mock directory structures
- [ ] Graceful handling of missing/malformed SKILL.md files

---

### Feature 12: Semantic Memory via MemPalace

**Source:** `src/main/memory.ts`

**What it is:** A semantic memory layer backed by the MemPalace CLI (a Python tool using embedding models). Maintains a shared "palace" directory, mines each agent's memory.md into per-agent "wings", enables meaning-based recall via `mempalace search`. Degrades silently when CLI unavailable.

**Target files to create/modify:**
```
src/nexus/memory/semantic.py                # SemanticMemoryManager
src/nexus/memory/embeddings.py              # Embedding model integration
tests/test_semantic_memory.py               # Manager tests (mock subprocess)
```

**Dependencies:** Memory module (existing), external CLI (optional)

**Effort estimate:** 1 day

**Key adaptation patterns:**

```python
# src/nexus/memory/semantic.py
class SemanticMemoryManager:
    """Semantic memory backed by embedding-based retrieval.

    Wraps a shared embedding store, mining each agent's memory into
    a per-agent namespace. Degrades to no-op when the embedding
    backend is unavailable.

    Operations:
    - init: create the palace directory
    - mine: index an agent's memory into its namespace
    - search: meaning-based recall across all agents
    """

    def __init__(self, root: Path, embedding_model: str = "minilm"):
        self._root = root
        self._model = embedding_model
        self._available = self._check_available()

    def active(self) -> bool: ...
    def mine_agent(self, agent_id: str, memory_path: Path) -> None: ...
    def search(self, query: str, limit: int = 5) -> list[SemanticHit]: ...
    def status(self) -> MemoryStatus: ...
```

**Acceptance criteria:**
- [ ] Silent degradation when embedding backend unavailable
- [ ] Per-agent namespace isolation ("wings")
- [ ] Periodic mining of changed memory files (mtime-based)
- [ ] Meaning-based search across all agents
- [ ] Status reporting (available, initialized, model)
- [ ] Tests with mock subprocess for CLI interactions

---

### Feature 13: Tool Catalog (Setup Prerequisites)

**Source:** `src/shared/toolCatalog.ts`

**What it is:** A catalog of every external tool the system can use, with presence detection, per-platform install commands, user-facing "why you need this" descriptions, and essential/optional classification. Engine rows are derived from provider presets rather than restated.

**Target files to create:**
```
src/nexus/tools/tool_catalog.py             # ToolSpec, catalog, presence detection
src/nexus/api/routes/setup.py               # REST endpoint for setup status
tests/test_tool_catalog.py                  # Catalog + detection tests
```

**Dependencies:** Agent Provider Presets (Feature 4)

**Effort estimate:** 0.5 days

**Key adaptation patterns:**

```python
# src/nexus/tools/tool_catalog.py
import shutil
from dataclasses import dataclass
from typing import Optional
import platform

class ToolKind(str, Enum):
    PREREQUISITE = "prerequisite"
    MEMORY = "memory"
    ENGINE = "engine"

@dataclass
class ToolSpec:
    id: str
    bin: Optional[str]  # executable to probe on PATH
    label: str
    kind: ToolKind
    why: str  # one-line benefit description
    essential: bool
    install_posix: str
    install_win32: str
    docs_url: Optional[str] = None

def probe_tool(spec: ToolSpec) -> bool:
    """Check if tool is available on PATH."""
    if spec.bin is None:
        return False
    return shutil.which(spec.bin) is not None

def get_setup_status() -> list[dict]:
    """Return all tools with their availability status."""
    ...
```

**Acceptance criteria:**
- [ ] Tool specs for all prerequisites (uv, git, mempalace)
- [ ] Engine tool specs derived from provider presets
- [ ] PATH-based presence detection
- [ ] Per-platform install commands (posix/win32)
- [ ] Essential vs optional classification
- [ ] REST endpoint returning current setup status
- [ ] Tests for probe logic with mock PATH

---

### Feature 14: Integration Registry + Encrypted Secrets

**Source:** `src/main/integrations.ts`

**What it is:** A config-backed integration registry (CRUD over metadata) paired with an encrypted-at-rest secret store. Secrets are never returned to the frontend, never logged, never placed in agent env. Records carry only a `secretRef` handle. Fail-closed: no plaintext fallback when encryption unavailable.

**Target files to create/modify:**
```
src/nexus/governance/integrations.py        # IntegrationRegistry
src/nexus/governance/secrets/integrations.py # Integration-specific secret store
src/nexus/api/routes/integrations.py        # REST endpoints (redacted view)
tests/test_integration_registry.py          # CRUD + secret lifecycle tests
```

**Dependencies:** Existing secrets module in governance

**Effort estimate:** 1 day

**Key adaptation patterns:**

```python
# src/nexus/governance/integrations.py
class IntegrationRegistry:
    """Config-backed integration registry with encrypted secrets.

    Two halves:
    1. Registry: CRUD over IntegrationRecord metadata (no secrets)
    2. Secret store: encrypted at rest, decrypted only in backend,
       never returned to API consumers

    Security: secrets never logged, never echoed, never in agent env.
    Fail-closed: no plaintext fallback.
    """

    def __init__(self, config_path: Path, secret_backend: SecretBackend):
        ...

    def list_records(self) -> list[IntegrationRecord]: ...
    def get_record(self, id: str) -> Optional[IntegrationRecord]: ...
    def upsert_record(self, record: IntegrationRecord) -> IntegrationRecord: ...
    def remove_record(self, id: str) -> bool: ...
    def set_secret(self, id: str, secret: str) -> None: ...
    def has_secret(self, id: str) -> bool: ...
    def get_secret(self, id: str) -> Optional[str]: ...  # internal only, never API-exposed
    def list_records_redacted(self) -> list[dict]: ...  # has_secret bool, no actual value
    def enabled_ids(self) -> list[str]: ...
```

**Acceptance criteria:**
- [ ] CRUD for integration records (config-backed storage)
- [ ] Encrypted secret storage (uses existing secrets backend)
- [ ] `secretRef` handle pattern (metadata never contains raw secret)
- [ ] Redacted list endpoint (has_secret boolean, not actual value)
- [ ] `enabled_ids()` filters by enabled + secret available
- [ ] Remove cascades to delete stored secret
- [ ] Fail-closed: refuse to store secret if encryption unavailable
- [ ] Tests for full lifecycle + security boundaries

---

### Feature 15: Trigger System (4 Types)

**Source:** `src/shared/triggers.ts`

**What it is:** A unified trigger framework with four types: (1) Schedule triggers (recurring missions), (2) Context triggers (auto-compact/clear based on context pressure), (3) Webhook triggers (inbound HTTP endpoints), (4) Org triggers (peer-to-peer between installations). All share a TriggerMode gate (strict/allow-all/communication-only) and a common history ledger.

**Target files to create:**
```
src/nexus/triggers/__init__.py              # Already exists as empty
src/nexus/triggers/types.py                 # TriggerMode, InboundKind, all trigger configs
src/nexus/triggers/classifier.py            # classify_inbound_kind heuristic
src/nexus/triggers/context_trigger.py       # Context pressure-based triggering
src/nexus/triggers/history.py               # TriggerHistoryEntry, capped ledger
src/nexus/triggers/schema_validator.py      # Minimal JSON Schema subset checker
src/nexus/api/routes/triggers.py            # REST endpoints
tests/test_triggers.py                      # Type tests + classifier tests
tests/test_trigger_schema.py                # Schema validator tests
```

**Dependencies:** Webhook Server (Feature 7) for webhook trigger integration

**Effort estimate:** 1.5 days

**Key adaptation patterns:**

```python
# src/nexus/triggers/types.py
class TriggerMode(str, Enum):
    STRICT = "strict"           # every inbound waits for operator approval
    ALLOW_ALL = "allow-all"     # everything flows through
    COMMUNICATION_ONLY = "communication-only"  # chatter flows, directives need approval

class InboundKind(str, Enum):
    DIRECTIVE = "directive"       # asks hive to act
    COMMUNICATION = "communication"  # informational

def is_auto_allowed(mode: TriggerMode, kind: InboundKind) -> bool:
    """Whether a message may be routed without human approval."""
    if mode == TriggerMode.ALLOW_ALL:
        return True
    if mode == TriggerMode.COMMUNICATION_ONLY:
        return kind == InboundKind.COMMUNICATION
    return False  # strict

def classify_inbound_kind(text: str) -> InboundKind:
    """Best-effort intent classification. Conservative: unclear = directive."""
    t = text.strip().lower()
    if not t:
        return InboundKind.COMMUNICATION
    # Questions with no imperative verbs are communication
    asks_only = (
        re.match(r"^(what|how|when|where|who|why|is|are|do|does|did|can|could|status|any)\b", t)
        and t.endswith("?")
        and not re.search(r"\b(fix|build|ship|deploy|run|write|create|add|remove|delete)\b", t)
    )
    return InboundKind.COMMUNICATION if asks_only else InboundKind.DIRECTIVE
```

**Acceptance criteria:**
- [ ] Three TriggerMode values with `is_auto_allowed()` gate logic
- [ ] `classify_inbound_kind()` heuristic (conservative: unclear = directive)
- [ ] Context trigger with dual condition (time elapsed AND context pressure)
- [ ] Webhook trigger model with per-endpoint secret + schema + mode
- [ ] Trigger history ledger with 500-entry cap (oldest evicted)
- [ ] Minimal JSON Schema validator (type, required, properties, enum)
- [ ] REST API for trigger configuration + history viewing
- [ ] Tests for classifier edge cases + schema validator + mode logic

---

### Feature 16: SSRF Protection

**Source:** `src/main/hire.ts` (SSRF guard section)

**What it is:** A comprehensive SSRF protection layer using `node:net`'s BlockList with proper subnet membership checks. Blocks all dangerous address ranges: loopback, RFC1918 private, link-local (including 169.254.169.254 cloud metadata), CGNAT, ULA, deprecated site-local, unspecified/multicast/reserved. Handles IPv4-mapped IPv6 de-mapping.

**Target files to create:**
```
src/nexus/governance/ssrf_protection.py     # SSRFGuard with BlockList
tests/test_ssrf_protection.py              # Address validation tests
```

**Dependencies:** None (standalone utility, used by webhook server and any HTTP client)

**Effort estimate:** 0.5 days

**Key adaptation patterns:**

```python
# src/nexus/governance/ssrf_protection.py
import ipaddress
from urllib.parse import urlparse
import socket
from typing import Optional

# All ranges that must never be fetched from
BLOCKED_NETWORKS = [
    # IPv4
    ipaddress.ip_network("0.0.0.0/8"),        # "this network" / unspecified
    ipaddress.ip_network("10.0.0.0/8"),       # RFC1918
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("169.254.0.0/16"),   # link-local + cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),    # RFC1918
    ipaddress.ip_network("192.168.0.0/16"),   # RFC1918
    ipaddress.ip_network("224.0.0.0/3"),      # multicast + reserved
    # IPv6
    ipaddress.ip_network("::1/128"),          # loopback
    ipaddress.ip_network("::/128"),           # unspecified
    ipaddress.ip_network("fc00::/7"),         # ULA
    ipaddress.ip_network("fe80::/10"),        # link-local
    ipaddress.ip_network("fec0::/10"),        # deprecated site-local
    ipaddress.ip_network("ff00::/8"),         # multicast
]

class SSRFGuard:
    """Validates URLs and resolved IP addresses against SSRF blocklist.

    Key properties:
    - Resolves DNS BEFORE connecting (checks the IP, not just the hostname)
    - Handles IPv4-mapped IPv6 addresses (::ffff:127.0.0.1)
    - Protocol enforcement (https only for remote, http allowed for loopback)
    - Works with Python's ipaddress module for proper subnet math
    """

    def is_safe_url(self, url: str) -> tuple[bool, Optional[str]]:
        """Check if URL target is safe to fetch. Returns (safe, reason)."""
        ...

    def is_safe_ip(self, addr: str) -> bool:
        """Check a resolved IP address against the blocklist."""
        ip = ipaddress.ip_address(addr)
        # De-map IPv4-mapped IPv6
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return not any(ip in network for network in BLOCKED_NETWORKS)

    async def safe_resolve(self, hostname: str) -> tuple[bool, list[str]]:
        """DNS-resolve and check all addresses. Returns (all_safe, addresses)."""
        ...
```

**Acceptance criteria:**
- [ ] All RFC-mandated private/reserved ranges blocked (IPv4 + IPv6)
- [ ] IPv4-mapped IPv6 de-mapping (::ffff:127.0.0.1 detected as loopback)
- [ ] DNS resolution check (hostname resolved before connection attempt)
- [ ] Protocol enforcement (https for remote, http only for localhost dev)
- [ ] Cloud metadata endpoint blocked (169.254.169.254)
- [ ] Integration point for webhook server and any outbound HTTP
- [ ] Tests for every blocked range + de-mapping + edge cases

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Hive Protocol complexity causes delays | Medium | High | Start with core message routing; defer git integration to later iteration |
| Advanced Circuit Breaker false positives | Medium | Medium | Port the compaction-awareness and debouncing exactly; tune thresholds in config |
| Memory Reflector depends on LLM availability | Low | Low | Design with pluggable summarizer; mock in tests; degrade gracefully |
| SSRF bypass via DNS rebinding | Low | High | Resolve DNS at request time, not connection time; re-verify on redirect |
| Provider preset drift (new CLIs released) | High | Low | Presets are config-driven; easy to add new entries without code changes |
| Webhook rate limiting under load | Medium | Medium | Use sliding window; configurable limits per-endpoint; test with concurrent requests |
| Hire manifest injection via model field | Low | High | Strict regex + allowlist (ported from source); never pass through shell |

---

## Cross-Feature Dependencies Graph

```
Feature 4 (Provider Presets)
    |
    +---> Feature 1 (Hire Manifests) [validates provider field]
    |
    +---> Feature 5 (Hive Protocol) [agent metadata]
    |         |
    |         +---> Feature 7 (Webhook Server) [task creation]
    |         |
    |         +---> Feature 9 (Closing Time) [message routing]
    |         |
    |         +---> Feature 8 (Control Registry) [steer delivery]
    |
    +---> Feature 11 (Skills) [provider-specific paths]
    |
    +---> Feature 13 (Tool Catalog) [engine rows]

Feature 2 (Pricing)
    |
    +---> Feature 3 (Advanced Circuit Breaker) [cost cap evaluation]

Feature 16 (SSRF) [standalone, consumed by Feature 7]

Feature 15 (Triggers) [schema validation consumed by Feature 7]
```

---

## Sprint Implementation Order

### Sprint 5 (Week 1-2): Operational Backbone
| Order | Feature | Effort | Cumulative |
|-------|---------|--------|-----------|
| 1 | Feature 2: Real-time Cost Tracking | 0.5d | 0.5d |
| 2 | Feature 4: Agent Provider Presets | 1.0d | 1.5d |
| 3 | Feature 3: Advanced Circuit Breaker | 1.5d | 3.0d |
| 4 | Feature 1: Hire Manifests | 1.5d | 4.5d |
| 5 | Feature 5: Hive Protocol | 2.0d | 6.5d |

**Sprint 5 exit criteria:** Agents can be spawned from manifests, costs are tracked per-model, the circuit breaker has multi-signal detection, and agents coordinate via file-based messaging.

### Sprint 6 (Week 3-4): Production Hardening
| Order | Feature | Effort | Cumulative |
|-------|---------|--------|-----------|
| 1 | Feature 8: Control Registry | 1.0d | 1.0d |
| 2 | Feature 6: Memory Reflector | 1.5d | 2.5d |
| 3 | Feature 10: Knowledge Graph | 1.5d | 4.0d |
| 4 | Feature 7: Webhook Inbound Server | 1.5d | 5.5d |
| 5 | Feature 9: Closing Time Protocol | 1.0d | 6.5d |

**Sprint 6 exit criteria:** Operators can pause/steer/halt agents at runtime, memory auto-condenses when oversized, knowledge is searchable, external systems can trigger work via webhooks, and multi-agent shutdown is graceful and lossless.

### Sprint 7 (Week 5-6): Ecosystem Completion
| Order | Feature | Effort | Cumulative |
|-------|---------|--------|-----------|
| 1 | Feature 16: SSRF Protection | 0.5d | 0.5d |
| 2 | Feature 15: Trigger System | 1.5d | 2.0d |
| 3 | Feature 13: Tool Catalog | 0.5d | 2.5d |
| 4 | Feature 14: Integration Registry | 1.0d | 3.5d |
| 5 | Feature 11: Skills Discovery | 1.0d | 4.5d |
| 6 | Feature 12: Semantic Memory | 1.0d | 5.5d |

**Sprint 7 exit criteria:** Full SSRF protection on all outbound fetches, four trigger types operational, tool prerequisites are discoverable, integrations have encrypted secrets, skills are browsable from multiple providers, and semantic search across agent memories is available.

---

## Testing Strategy

Each feature targets **20-30 tests** covering:
1. **Happy path** - core functionality works as specified
2. **Edge cases** - empty inputs, boundary values, Unicode, large payloads
3. **Security** - injection attempts, bypass attempts, timing safety
4. **Integration** - feature works with existing NEXUS modules
5. **Degradation** - graceful behavior when optional dependencies are absent

**Total new tests expected:** ~350 across all 16 features

**Test patterns from existing codebase:**
- pytest with async support (`@pytest.mark.asyncio`)
- Fixtures for shared state (`conftest.py`)
- Mock subprocess for CLI interactions
- Temp directories for file-based features
- Pydantic model validation for API inputs

---

## Migration Notes

### TypeScript to Python Patterns

| TypeScript Pattern | Python Equivalent |
|-------------------|-------------------|
| `interface Foo { ... }` | `@dataclass` or `Pydantic BaseModel` |
| `type FooBar = 'a' \| 'b'` | `class FooBar(str, Enum)` |
| `Map<string, T>` | `dict[str, T]` |
| `Set<string>` | `set[str]` or `frozenset[str]` |
| `readonly` fields | `@dataclass(frozen=True)` or Pydantic `Field(frozen=True)` |
| `async/await` | `async/await` with `asyncio` |
| `setInterval(fn, ms)` | `asyncio.create_task` + `asyncio.sleep` loop |
| `existsSync/readFileSync` | `pathlib.Path.exists()` / `.read_text()` |
| `crypto.randomBytes` | `secrets.token_hex()` / `secrets.token_bytes()` |
| `timingSafeEqual` | `hmac.compare_digest()` |
| `BlockList` (node:net) | `ipaddress.ip_network` + membership check |
| `JSON.parse/stringify` | `json.loads/dumps` or Pydantic `.model_dump_json()` |
| Class with private `#field` | Convention `_field` + property if needed |
| `clearInterval/clearTimeout` | Cancel the `asyncio.Task` |

### File-Based Storage Pattern

Munder-difflin uses synchronous file I/O (Electron main process). NEXUS should use:
- `aiofiles` for async file operations where needed
- `pathlib.Path` throughout (not `os.path`)
- Atomic writes via temp-file + rename (same pattern, Python stdlib)
- JSON for structured data, JSONL for append-only logs

### Error Handling

Munder-difflin uses try/catch with best-effort logging. NEXUS should:
- Use structured logging (`structlog` or Python `logging`)
- Define domain exceptions per module
- Preserve the "degrade gracefully" philosophy (features are no-ops when prerequisites missing)

---

## Appendix: Source File Sizes (Lines of Code)

| Source File | Lines | Complexity |
|-------------|-------|------------|
| `src/main/hive.ts` | ~2,400 | Very High (routing, git, spawn, lifecycle) |
| `src/shared/agentProvider.ts` | ~634 | Medium (data + utilities) |
| `src/main/breaker.ts` | ~280 | Medium (state machine + evaluation) |
| `src/main/reflect.ts` | ~320 | Medium (pipeline + pure helpers) |
| `src/main/closingTime.ts` | ~200 | Medium (protocol state machine) |
| `src/shared/hire.ts` | ~250 | Medium (validation logic) |
| `src/shared/triggers.ts` | ~260 | Low-Medium (types + classifier) |
| `src/main/webhook.ts` | ~400 | Medium (HTTP server + auth) |
| `src/main/control.ts` | ~100 | Low (simple state map) |
| `src/main/knowledge.ts` | ~150 | Low (thin facade) |
| `src/main/pricing.ts` | ~70 | Low (lookup table) |
| `src/main/skills.ts` | ~250 | Low-Medium (filesystem walking) |
| `src/main/memory.ts` | ~200 | Medium (subprocess management) |
| `src/shared/toolCatalog.ts` | ~120 | Low (static catalog) |
| `src/main/integrations.ts` | ~100 | Low (CRUD + encryption) |
| `src/main/hire.ts` (SSRF) | ~120 | Medium (IP handling) |

---

## Summary

This plan imports 16 features across 3 sprints, producing a working system at each checkpoint. The implementation order respects dependencies (presets before manifests, pricing before breaker, hive before closing-time) and front-loads the highest-impact operational features. Each feature includes exact source references, target file paths, effort estimates, Python code hints, and measurable acceptance criteria.

**Total effort estimate:** ~18.5 developer-days across 3 sprints
**Total new files:** ~45
**Total new tests:** ~350
**Risk level:** Moderate (manageable with test-driven development and incremental integration)
