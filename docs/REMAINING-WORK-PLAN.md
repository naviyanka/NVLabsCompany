# NEXUS Remaining Work Plan

> **STALE — do not trust status claims in this document.**
> Last verified against commit: never. Superseded by `docs/GAP-CLOSURE-PLAN.md`
> (verified against commit `1bbad4a`, 2026-08-26), which is the single source of
> truth for what is actually wired. Percentages and "complete" markers below are
> historical intent, not measured state.

> Comprehensive micro-phase breakdown for completing NEXUS from its current prototype state to production readiness.

## Current State Summary

The NEXUS project has a solid architectural skeleton built across 6 phases:
- 176 Python source files with well-defined module boundaries
- 89 React dashboard files with API client and hooks
- 50+ SQLModel table definitions across 17 model files
- Adapter stubs (OpenAI, Anthropic, Ollama, Claude Code, HTTP, MCP) with correct interfaces but simulated responses
- Governance modules (KillSwitch, RBAC, Audit, RateLimiter) using in-memory dataclass state
- Alembic configured but no migration scripts generated
- Docker Compose with PostgreSQL 16 + Redis 7 defined

**What works:** API routes return shaped data, models are importable, governance logic is correct in isolation.
**What does not work:** No real LLM calls, governance state is lost on restart, no database migrations exist, tenant isolation has gaps, MCP protocol is stubbed.

---

## Phase Organization

| Priority | Phase IDs | Focus |
|----------|-----------|-------|
| Critical | FIX-01 through FIX-06 | Must-fix gaps that block production use |
| Medium | ENH-07 through ENH-12 | Functional enhancements for real-world utility |
| Lower | POL-13 through POL-17 | Polish, observability, deployment, docs |

---

## CRITICAL FIXES

---

### FIX-01: Real LLM API Integration

#### FIX-01-A: OpenAI Chat Completions with Function Calling

**Description:** Replace the simulated response logic in `OpenAIAdapter.execute_task()` with real async httpx calls to the OpenAI Chat Completions API. Implement streaming support, function calling (tool_use), token counting from response headers, and cost calculation from actual usage.

**Files to modify:**
- `src/nexus/adapters/openai_adapter.py`
- `src/nexus/config.py` (add `openai_api_key`, `openai_org_id` fields)

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- `OpenAIAdapter.execute_task()` sends a real POST to `https://api.openai.com/v1/chat/completions`
- Function calling messages are formatted per OpenAI spec (tools array)
- Streaming responses are handled via async iteration of SSE lines
- Token counts come from `usage.prompt_tokens` / `usage.completion_tokens` in the response
- Cost is calculated using the existing `MODEL_PRICING` dict
- Exponential backoff retries on 429 (rate limit) and 5xx errors up to `MAX_RETRIES`
- Missing API key raises a clear `AdapterConfigError`

**Code hints:**
```python
# In config.py, add to Settings class:
openai_api_key: str = ""
openai_org_id: str = ""

# In openai_adapter.py execute_task():
import httpx

async with httpx.AsyncClient(timeout=120.0) as client:
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    if settings.openai_org_id:
        headers["OpenAI-Organization"] = settings.openai_org_id

    payload = {
        "model": config.get("model", "gpt-4o"),
        "messages": messages,
        "tools": tool_definitions,  # OpenAI function calling format
        "stream": config.get("stream", False),
    }

    response = await client.post(
        f"{self._api_base}/chat/completions",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()
    data = response.json()
    # Extract usage: data["usage"]["prompt_tokens"], data["usage"]["completion_tokens"]
```

---

#### FIX-01-B: Anthropic Messages API with Tool Use

**Description:** Implement real API calls to the Anthropic Messages API in the Anthropic adapter. Support tool_use blocks, streaming via SSE, and proper error handling for overloaded responses.

**Files to modify:**
- `src/nexus/adapters/anthropic_adapter.py`
- `src/nexus/config.py` (add `anthropic_api_key` field)

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- Real POST to `https://api.anthropic.com/v1/messages` with `anthropic-version` header
- Tool use formatted per Anthropic spec (tools array with input_schema)
- Streaming handled via `event: message_delta` SSE events
- Token counts from `usage.input_tokens` / `usage.output_tokens`
- Retries on 529 (overloaded) and 5xx with exponential backoff
- `anthropic-beta` header included when using extended features

**Code hints:**
```python
# Anthropic-specific headers
headers = {
    "x-api-key": settings.anthropic_api_key,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}

# Anthropic message format
payload = {
    "model": config.get("model", "claude-sonnet-4-20250514"),
    "max_tokens": config.get("max_tokens", 4096),
    "messages": messages,  # role: "user"/"assistant" only
    "system": system_prompt,  # separate from messages
    "tools": tool_definitions,  # Anthropic tool format
}
```

---

#### FIX-01-C: Ollama Local Model Integration

**Description:** Wire the Ollama adapter to make real REST calls to a local Ollama server. Support model listing, chat completions, and streaming responses from locally-running models.

**Files to modify:**
- `src/nexus/adapters/ollama_adapter.py`
- `src/nexus/config.py` (add `ollama_base_url` field)

**Dependencies:** None

**Estimated effort:** Small

**Acceptance criteria:**
- Real POST to `{ollama_base_url}/api/chat` (default `http://localhost:11434`)
- Model availability checked via GET `/api/tags` before execution
- Streaming support via newline-delimited JSON
- Graceful error when Ollama server is not running
- No API key required (local server)

**Code hints:**
```python
# Ollama chat format
payload = {
    "model": config.get("model", "llama3.1"),
    "messages": messages,
    "stream": config.get("stream", True),
    "options": {
        "temperature": config.get("temperature", 0.7),
        "num_predict": config.get("max_tokens", 2048),
    },
}
# POST to http://localhost:11434/api/chat
```

---

#### FIX-01-D: Retry Logic and Error Handling Module

**Description:** Create a shared retry utility used by all LLM adapters. Implements exponential backoff with jitter, configurable retry conditions, timeout handling, and structured error reporting.

**Files to create:**
- `src/nexus/adapters/retry.py`

**Files to modify:**
- `src/nexus/adapters/openai_adapter.py` (use shared retry)
- `src/nexus/adapters/anthropic_adapter.py` (use shared retry)
- `src/nexus/adapters/ollama_adapter.py` (use shared retry)

**Dependencies:** FIX-01-A, FIX-01-B, FIX-01-C

**Estimated effort:** Small

**Acceptance criteria:**
- `RetryConfig` dataclass with `max_retries`, `base_delay`, `max_delay`, `jitter`
- `async def with_retry(fn, config, retryable_statuses)` higher-order function
- Jitter prevents thundering herd (random factor 0.5-1.5x delay)
- Non-retryable errors (400, 401, 403) raise immediately
- Timeout errors are retryable
- Each retry attempt is logged with attempt number and wait time

**Code hints:**
```python
@dataclass
class RetryConfig:
    max_retries: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: bool = True
    retryable_statuses: set[int] = field(default_factory=lambda: {429, 500, 502, 503, 529})

async def with_retry(
    fn: Callable[[], Awaitable[T]],
    config: RetryConfig = RetryConfig(),
) -> T:
    for attempt in range(config.max_retries + 1):
        try:
            return await fn()
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in config.retryable_statuses:
                raise
            if attempt == config.max_retries:
                raise
            delay = min(config.base_delay * (2 ** attempt), config.max_delay)
            if config.jitter:
                delay *= 0.5 + random.random()
            await asyncio.sleep(delay)
```

---

#### FIX-01-E: Token Counting and Cost Tracking Service

**Description:** Create a dedicated service that tracks token usage and costs across all adapter invocations. Stores per-request usage in the database and provides aggregation queries for budget enforcement.

**Files to create:**
- `src/nexus/adapters/usage_tracker.py`

**Files to modify:**
- `src/nexus/models/agent.py` (ensure `AgentUsageLog` model exists with token/cost fields)

**Dependencies:** FIX-01-A, FIX-01-B

**Estimated effort:** Small

**Acceptance criteria:**
- `UsageTracker` class with `record_usage(agent_id, model, input_tokens, output_tokens, cost_cents)` method
- Cost calculated from model pricing tables (per-adapter)
- Usage stored in `agent_usage_log` table
- Aggregation methods: `get_daily_cost(company_id)`, `get_agent_total(agent_id, since)`
- Integration point for budget enforcement (FIX-01-E feeds into governance budget checks)

---

### FIX-02: Governance State Persistence

#### FIX-02-A: KillSwitch Database Persistence

**Description:** Migrate the `KillSwitchState` from in-memory dataclass to database-backed storage. The kill switch state must survive process restarts so that a triggered kill switch remains active across deployments.

**Files to modify:**
- `src/nexus/governance/kill_switch.py`
- `src/nexus/models/governance.py` (add/verify `KillSwitchRecord` SQLModel table)

**Dependencies:** FIX-03-A (migrations must exist to create the table)

**Estimated effort:** Medium

**Acceptance criteria:**
- `KillSwitchManager.activate()` writes state to the `kill_switch_records` table
- `KillSwitchManager.deactivate()` updates the record
- `KillSwitchManager.is_active(company_id)` queries the database
- On startup, active kill switches are loaded from DB
- All operations use async SQLAlchemy session
- Unit tests verify state survives simulated restart (write, clear memory, read back)

**Code hints:**
```python
# In governance.py models (if not exists):
class KillSwitchRecord(SQLModel, table=True):
    __tablename__ = "kill_switch_records"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(index=True)
    is_active: bool = True
    reason: str = ""
    activated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    activated_by: str | None = None
    deactivated_at: datetime | None = None

# In kill_switch.py:
class KillSwitchManager:
    def __init__(self, session_factory: AsyncSessionFactory):
        self._session_factory = session_factory

    async def activate(self, company_id: UUID, reason: str, activated_by: str) -> None:
        async with self._session_factory() as session:
            record = KillSwitchRecord(company_id=company_id, reason=reason, activated_by=activated_by)
            session.add(record)
            await session.commit()
```

---

#### FIX-02-B: RBAC Assignments Database Persistence

**Description:** Move role-based access control assignments from in-memory dicts to the database. Ensure permission checks query the database (with caching) so that role changes persist across restarts.

**Files to modify:**
- `src/nexus/governance/rbac.py`
- `src/nexus/models/governance.py` (add/verify `RoleAssignment` SQLModel table)

**Dependencies:** FIX-03-A

**Estimated effort:** Medium

**Acceptance criteria:**
- `RBACManager.assign_role(user_id, role, company_id)` persists to `role_assignments` table
- `RBACManager.check_permission(user_id, permission, company_id)` queries DB with local cache (TTL 60s)
- `RBACManager.revoke_role(user_id, role, company_id)` soft-deletes the assignment
- Cache invalidation on role change
- Roles load from DB on service startup

---

#### FIX-02-C: Rate Limiter Redis Persistence

**Description:** Move rate limiter counters from in-memory dicts to Redis using sliding window or token bucket algorithm. This ensures rate limits work correctly in multi-process deployments and survive restarts.

**Files to modify:**
- `src/nexus/governance/rate_limiter.py`
- `src/nexus/config.py` (verify `redis_url` is accessible)

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- Rate limiter uses Redis sorted sets for sliding window algorithm
- Key format: `ratelimit:{company_id}:{resource}:{window}`
- Atomic check-and-increment via Lua script or Redis MULTI/EXEC
- TTL on keys matches window size (auto-cleanup)
- Falls back to in-memory if Redis is unavailable (with warning log)
- Works correctly across multiple server processes

**Code hints:**
```python
import redis.asyncio as aioredis

class RedisRateLimiter:
    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url)

    async def check_rate_limit(
        self, key: str, max_requests: int, window_seconds: int
    ) -> tuple[bool, int]:
        """Returns (allowed, remaining_requests)."""
        now = time.time()
        window_start = now - window_seconds
        pipe = self._redis.pipeline()
        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Count current window
        pipe.zcard(key)
        # Add current request
        pipe.zadd(key, {str(now): now})
        # Set TTL
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        current_count = results[1]
        allowed = current_count < max_requests
        return allowed, max(0, max_requests - current_count - 1)
```

---

#### FIX-02-D: Circuit Breaker State Persistence

**Description:** Persist circuit breaker state (open/closed/half-open, failure counts, last failure time) to Redis so that circuit breaker protection works across multiple server instances and survives restarts.

**Files to modify:**
- `src/nexus/governance/kill_switch.py` (CircuitBreaker class is here)

**Dependencies:** None

**Estimated effort:** Small

**Acceptance criteria:**
- Circuit breaker state stored in Redis hash: `cb:{service_name}:{company_id}`
- Fields: `state`, `failure_count`, `last_failure_at`, `opened_at`
- State transitions (closed->open, open->half-open, half-open->closed) update Redis atomically
- Half-open timeout reads from Redis `opened_at` field
- Multiple processes see the same circuit breaker state

---

#### FIX-02-E: Audit Logger Buffered Database Writes

**Description:** Integrate the existing `audit_persistent.py` module with the main `audit.py` logger. Implement buffered writes that batch audit events and flush them to PostgreSQL periodically or when the buffer reaches a threshold.

**Files to modify:**
- `src/nexus/governance/audit.py`
- `src/nexus/governance/audit_persistent.py`
- `src/nexus/models/governance.py` (verify `AuditLog` table)

**Dependencies:** FIX-03-A

**Estimated effort:** Medium

**Acceptance criteria:**
- Audit events are buffered in memory (max 100 events or 5 seconds, whichever comes first)
- Buffer flush writes batch INSERT to `audit_logs` table
- Flush triggered on: buffer full, timer expiry, graceful shutdown
- No audit events lost on normal shutdown (flush on SIGTERM)
- Async background task handles the periodic flush
- Performance: buffered writes are 10x+ faster than per-event writes

---

### FIX-03: Database Migrations (Alembic)

#### FIX-03-A: Generate Initial Migration

**Description:** Generate the initial Alembic migration that creates all 50+ tables defined in the SQLModel models. This is the foundation for all database-dependent features.

**Files to create:**
- `alembic/versions/001_initial_schema.py` (auto-generated, then reviewed)

**Files to modify:**
- `alembic/env.py` (ensure all models are imported for autogenerate)

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- Running `alembic upgrade head` creates all tables in a fresh PostgreSQL database
- Running `alembic downgrade base` drops all tables cleanly
- All 50+ SQLModel tables are represented
- Foreign key relationships are correct
- Indexes defined in models are created
- `alembic/env.py` imports from `src/nexus/models` so autogenerate detects all tables

**Code hints:**
```python
# In alembic/env.py, ensure target_metadata is set:
from nexus.models import *  # noqa: F401 F403
from nexus.models.agent import *  # noqa: F401 F403 - import all model modules
from sqlmodel import SQLModel

target_metadata = SQLModel.metadata
```

---

#### FIX-03-B: Seed Data Migration

**Description:** Create a data migration that inserts demo company, admin user, sample agents, and default policies. This allows developers to start with a functional system immediately after migration.

**Files to create:**
- `alembic/versions/002_seed_demo_data.py`

**Dependencies:** FIX-03-A

**Estimated effort:** Small

**Acceptance criteria:**
- Creates a demo company ("NVLabs Demo Co") with a known UUID
- Creates an admin user with default credentials
- Creates 3 sample agents (research, coding, communication)
- Creates default governance policies (rate limits, budget caps)
- Migration is idempotent (safe to run multiple times)
- Downgrade removes only the seeded data

---

#### FIX-03-C: Migration Workflow Documentation

**Description:** Document the Alembic migration workflow for developers: how to create new migrations, how to test them, naming conventions, and CI integration.

**Files to create:**
- `docs/migrations.md`

**Dependencies:** FIX-03-A, FIX-03-B

**Estimated effort:** Small

**Acceptance criteria:**
- Documents: `alembic revision --autogenerate -m "description"` workflow
- Documents: testing migrations up/down locally
- Documents: migration naming convention (sequential number + description)
- Documents: how to handle model changes (modify model, generate migration, review, test)
- Documents: production migration strategy (backup, migrate, verify)

---

### FIX-04: Tenant Isolation Hardening

#### FIX-04-A: Audit All Routes for Tenant Filter Gaps

**Description:** Systematically review every API route that fetches a single resource by ID (GET /resource/{id}, PUT /resource/{id}, DELETE /resource/{id}) and document which ones lack `company_id` filtering.

**Files to create:**
- `docs/tenant-isolation-audit.md`

**Files to review:**
- All files in `src/nexus/api/routes/` (24 files)

**Dependencies:** None

**Estimated effort:** Small

**Acceptance criteria:**
- Every route file is reviewed
- Each endpoint is classified as: isolated (has company_id filter), needs fix, or N/A (no tenant context)
- Output is a markdown table with route, method, status, and required fix

---

#### FIX-04-B: Add company_id Filters to Resource Endpoints

**Description:** Add `company_id` WHERE clause to all single-resource queries identified in FIX-04-A. Extract `company_id` from the authenticated user's JWT token or request context.

**Files to modify:**
- `src/nexus/api/routes/agents.py`
- `src/nexus/api/routes/tasks.py`
- `src/nexus/api/routes/tools.py`
- `src/nexus/api/routes/knowledge.py`
- `src/nexus/api/routes/workflows.py`
- `src/nexus/api/routes/skills.py`
- `src/nexus/api/routes/budgets.py`
- `src/nexus/api/routes/secrets.py`
- `src/nexus/api/routes/memory.py`
- (all routes identified in FIX-04-A)

**Dependencies:** FIX-04-A

**Estimated effort:** Large

**Acceptance criteria:**
- Every GET/PUT/DELETE by ID includes `WHERE company_id = :current_company_id`
- 404 returned if resource exists but belongs to different company (not 403, to avoid information leakage)
- Consistent pattern used across all routes

**Code hints:**
```python
# Pattern for tenant-scoped single-resource fetch:
async def get_agent(agent_id: UUID, current_user: User = Depends(get_current_user)):
    statement = select(Agent).where(
        Agent.id == agent_id,
        Agent.company_id == current_user.company_id  # TENANT FILTER
    )
    result = await session.execute(statement)
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent
```

---

#### FIX-04-C: Tenant Isolation Middleware

**Description:** Create middleware that automatically injects `company_id` into the request state from the authenticated user, and optionally validates tenant context on every database query via SQLAlchemy event hooks.

**Files to create:**
- `src/nexus/api/middleware/tenant.py`

**Files to modify:**
- `src/nexus/api/middleware.py` (register the new middleware)

**Dependencies:** FIX-04-B

**Estimated effort:** Medium

**Acceptance criteria:**
- Middleware extracts `company_id` from JWT claims and sets `request.state.company_id`
- Utility function `get_tenant_id(request)` available for route handlers
- Optional SQLAlchemy execution event that warns if a query on a tenant-scoped table lacks a `company_id` filter (development mode only)
- Middleware runs before route handlers

---

#### FIX-04-D: Cross-Tenant Isolation Integration Tests

**Description:** Write integration tests that create resources in Company A, then verify Company B cannot read, update, or delete them. These tests are the definitive proof that tenant isolation works.

**Files to create:**
- `tests/integration/test_tenant_isolation.py`

**Dependencies:** FIX-04-B, FIX-04-C

**Estimated effort:** Medium

**Acceptance criteria:**
- Test creates Agent in Company A, verifies Company B gets 404 on GET/PUT/DELETE
- Test creates Task in Company A, verifies Company B gets 404
- Test creates Knowledge in Company A, verifies Company B cannot search it
- Tests cover at least 5 different resource types
- Tests run against a real test database (pytest fixture with isolated transactions)

---

### FIX-05: Durable Execution / Checkpointing

#### FIX-05-A: Execution State Schema

**Description:** Define the database schema for storing execution checkpoints. Each checkpoint captures the full state of a running task at a specific step, enabling resumption after crashes.

**Files to create:**
- `src/nexus/runtime/checkpoint.py`

**Files to modify:**
- `src/nexus/models/task.py` (add `ExecutionCheckpoint` SQLModel table)

**Dependencies:** FIX-03-A

**Estimated effort:** Medium

**Acceptance criteria:**
- `ExecutionCheckpoint` table with: `id`, `task_id`, `step_index`, `state_json`, `created_at`, `status`
- State is serialized as JSON (agent context, completed steps, intermediate results)
- `CheckpointManager` class with `save_checkpoint()` and `load_latest_checkpoint()` methods
- Checkpoints are per-task, ordered by step_index
- Old checkpoints are cleaned up after task completion (keep last N)

**Code hints:**
```python
class ExecutionCheckpoint(SQLModel, table=True):
    __tablename__ = "execution_checkpoints"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    step_index: int
    state_json: str  # JSON-serialized execution state
    status: str = "active"  # active, completed, abandoned
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class CheckpointManager:
    async def save(self, task_id: UUID, step_index: int, state: dict) -> None: ...
    async def load_latest(self, task_id: UUID) -> ExecutionCheckpoint | None: ...
    async def cleanup(self, task_id: UUID, keep_last: int = 3) -> None: ...
```

---

#### FIX-05-B: Crash Recovery on Startup

**Description:** Implement a startup routine that checks for incomplete tasks with checkpoints and resumes them. This ensures that if the server crashes mid-execution, tasks resume from their last checkpoint rather than being lost.

**Files to modify:**
- `src/nexus/runtime/lifecycle.py`
- `src/nexus/runtime/executor.py`

**Dependencies:** FIX-05-A

**Estimated effort:** Medium

**Acceptance criteria:**
- On server startup, query for tasks with `status = "running"` and existing checkpoints
- For each interrupted task, load the latest checkpoint and resume from that step
- Tasks older than a configurable timeout (default 1 hour) are marked as `failed` instead of resumed
- Recovery is logged with task ID, checkpoint step, and time since interruption
- Concurrent startup of multiple server instances handles recovery safely (advisory locks)

---

#### FIX-05-C: Interrupt and Resume Semantics

**Description:** Implement user-initiated interrupt (pause) and resume for long-running tasks. When interrupted, the current step completes and a checkpoint is saved. Resume picks up from the saved state.

**Files to modify:**
- `src/nexus/runtime/executor.py`
- `src/nexus/api/routes/tasks.py` (add POST /tasks/{id}/interrupt, POST /tasks/{id}/resume)

**Dependencies:** FIX-05-A, FIX-05-B

**Estimated effort:** Medium

**Acceptance criteria:**
- POST `/api/v1/tasks/{id}/interrupt` sets a flag that the executor checks between steps
- Executor saves checkpoint and transitions task to `paused` status
- POST `/api/v1/tasks/{id}/resume` loads checkpoint and restarts execution
- Interrupt is graceful (current LLM call completes, then pauses)
- Task history shows interrupt/resume events with timestamps

---

### FIX-06: Real MCP Protocol Implementation

#### FIX-06-A: JSON-RPC 2.0 Message Layer

**Description:** Implement the JSON-RPC 2.0 message handling layer required by the MCP protocol. This handles request/response correlation, error codes, and batch messages.

**Files to create:**
- `src/nexus/tools/mcp/jsonrpc.py`

**Dependencies:** None

**Estimated effort:** Small

**Acceptance criteria:**
- `JsonRpcRequest` and `JsonRpcResponse` dataclasses
- Request ID generation and correlation
- Standard error codes: -32700 (parse error), -32600 (invalid request), -32601 (method not found), -32602 (invalid params), -32603 (internal error)
- Serialize/deserialize to/from JSON
- Batch request support (send multiple requests, correlate responses)

**Code hints:**
```python
@dataclass
class JsonRpcRequest:
    method: str
    params: dict[str, Any] | None = None
    id: str | int = field(default_factory=lambda: str(uuid.uuid4()))
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        return json.dumps(asdict(self))

@dataclass
class JsonRpcResponse:
    result: Any = None
    error: dict[str, Any] | None = None
    id: str | int | None = None
    jsonrpc: str = "2.0"

    @classmethod
    def from_json(cls, data: str) -> "JsonRpcResponse": ...
```

---

#### FIX-06-B: Stdio Transport for MCP

**Description:** Implement the stdio transport for communicating with MCP servers that run as subprocesses. Messages are sent via stdin and received via stdout, with each message as a newline-delimited JSON-RPC message.

**Files to create:**
- `src/nexus/tools/mcp/stdio_transport.py`

**Dependencies:** FIX-06-A

**Estimated effort:** Medium

**Acceptance criteria:**
- `StdioTransport` class that spawns a subprocess with given command/args
- Sends JSON-RPC messages to subprocess stdin (newline-terminated)
- Reads responses from subprocess stdout (newline-terminated JSON)
- Handles subprocess lifecycle (start, health check, graceful shutdown, force kill)
- stderr is captured for error logging
- Timeout handling for unresponsive servers

**Code hints:**
```python
class StdioTransport:
    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None):
        self._command = command
        self._args = args
        self._env = env
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            self._command, *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )

    async def send(self, request: JsonRpcRequest) -> JsonRpcResponse:
        self._process.stdin.write((request.to_json() + "\n").encode())
        await self._process.stdin.drain()
        line = await asyncio.wait_for(self._process.stdout.readline(), timeout=30.0)
        return JsonRpcResponse.from_json(line.decode().strip())
```

---

#### FIX-06-C: SSE Transport for MCP

**Description:** Implement the Server-Sent Events (SSE) transport for communicating with MCP servers that expose an HTTP endpoint. Requests are sent via POST, responses arrive via SSE stream.

**Files to create:**
- `src/nexus/tools/mcp/sse_transport.py`

**Dependencies:** FIX-06-A

**Estimated effort:** Medium

**Acceptance criteria:**
- `SSETransport` class connecting to an HTTP endpoint
- Sends JSON-RPC requests via POST to the server's message endpoint
- Receives responses via SSE stream (event: message, data: JSON-RPC response)
- Handles reconnection on connection drop
- Supports concurrent requests with response correlation via request ID
- Connection keepalive handling

**Code hints:**
```python
class SSETransport:
    def __init__(self, url: str, headers: dict[str, str] | None = None):
        self._url = url
        self._headers = headers or {}
        self._pending: dict[str, asyncio.Future] = {}

    async def connect(self) -> None:
        # Open SSE connection for receiving responses
        # Parse event stream, route responses to pending futures by ID
        ...

    async def send(self, request: JsonRpcRequest) -> JsonRpcResponse:
        # POST request to message endpoint
        # Wait on future keyed by request.id
        ...
```

---

#### FIX-06-D: MCP Tool Discovery and Invocation

**Description:** Implement the MCP client protocol methods for discovering available tools from a connected server and invoking them. This uses the `tools/list` and `tools/call` MCP methods.

**Files to modify:**
- `src/nexus/tools/mcp_client.py`

**Files to create:**
- `src/nexus/tools/mcp/client.py` (full MCP client using transports)

**Dependencies:** FIX-06-A, FIX-06-B, FIX-06-C

**Estimated effort:** Medium

**Acceptance criteria:**
- `MCPClient.initialize()` sends `initialize` request and handles server capabilities
- `MCPClient.list_tools()` sends `tools/list` and returns parsed `MCPTool` objects
- `MCPClient.call_tool(name, arguments)` sends `tools/call` and returns `MCPResult`
- Discovered tools are registered in the NEXUS tool registry
- Error responses from MCP servers are propagated as structured errors
- Client handles both stdio and SSE transports via a common interface

**Code hints:**
```python
class MCPClient:
    def __init__(self, transport: StdioTransport | SSETransport):
        self._transport = transport
        self._server_capabilities: dict = {}

    async def initialize(self) -> None:
        response = await self._transport.send(JsonRpcRequest(
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "nexus", "version": "0.1.0"},
            }
        ))
        self._server_capabilities = response.result.get("capabilities", {})

    async def list_tools(self) -> list[MCPTool]:
        response = await self._transport.send(JsonRpcRequest(method="tools/list"))
        return [MCPTool(**t) for t in response.result.get("tools", [])]

    async def call_tool(self, name: str, arguments: dict) -> MCPResult:
        response = await self._transport.send(JsonRpcRequest(
            method="tools/call",
            params={"name": name, "arguments": arguments}
        ))
        if response.error:
            return MCPResult(content=response.error, is_error=True)
        return MCPResult(content=response.result.get("content", []))
```

---

## MEDIUM PRIORITY - Functional Enhancements

---

### ENH-07: Real Adapter Implementations

#### ENH-07-A: Claude Code Subprocess Adapter

**Description:** Implement the Claude Code adapter that spawns a `claude` CLI subprocess, sends prompts via stdin, and captures structured output. This enables using Claude's agentic coding capabilities within NEXUS workflows.

**Files to modify:**
- `src/nexus/adapters/claude_code_adapter.py`

**Dependencies:** FIX-01-D (retry module)

**Estimated effort:** Medium

**Acceptance criteria:**
- Spawns `claude` subprocess with `--output-format json` flag
- Sends task description via stdin
- Captures structured JSON output from stdout
- Handles subprocess timeout (configurable, default 5 minutes)
- Captures and reports stderr on failure
- Supports `--allowedTools` flag for tool restriction
- Graceful process termination on cancel

---

#### ENH-07-B: HTTP Webhook Adapter

**Description:** Implement the HTTP adapter for webhook-based agent integration. Supports outbound webhook delivery with payload signing, and inbound webhook receipt for async responses.

**Files to modify:**
- `src/nexus/adapters/http_adapter.py`

**Files to create:**
- `src/nexus/api/routes/webhooks.py` (inbound webhook receiver)

**Dependencies:** FIX-01-D (retry module)

**Estimated effort:** Medium

**Acceptance criteria:**
- Outbound: POST to configured URL with JSON payload and HMAC-SHA256 signature header
- Outbound: Configurable timeout, retries on 5xx
- Inbound: Webhook receiver endpoint validates signature before processing
- Inbound: Maps webhook responses back to originating task
- Supports both fire-and-forget and request-response patterns

---

#### ENH-07-C: MCP Server Adapter

**Description:** Implement the MCP adapter that connects to an MCP-compatible tool server and exposes its tools within the NEXUS agent runtime. Uses the MCP client from FIX-06-D.

**Files to modify:**
- `src/nexus/adapters/mcp_adapter.py`

**Dependencies:** FIX-06-D

**Estimated effort:** Small

**Acceptance criteria:**
- Adapter wraps `MCPClient` and exposes connected tools as available to agents
- Auto-discovery: on connection, queries available tools and registers them
- Tool calls routed through the MCP client
- Adapter handles MCP server disconnection and reconnection
- Configuration includes server command, args, or URL (for SSE)

---

### ENH-08: WebSocket/SSE Real-time Updates

#### ENH-08-A: WebSocket Endpoint for Agent Status

**Description:** Add a WebSocket endpoint that streams real-time agent status updates (online, busy, error, idle) and task progress events to connected dashboard clients.

**Files to create:**
- `src/nexus/api/routes/ws.py`

**Files to modify:**
- `src/nexus/api/routes/__init__.py` (register WebSocket route)

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- WebSocket endpoint at `/ws/events`
- Authentication via token query parameter or first message
- Streams events: `agent.status_changed`, `task.progress`, `task.completed`, `task.failed`
- Room-based subscription by `company_id` (only see own company events)
- Heartbeat ping/pong every 30 seconds
- Graceful disconnect handling

**Code hints:**
```python
from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket, token: str = Query(...)):
    user = await authenticate_ws(token)
    await websocket.accept()
    # Subscribe to company events
    try:
        while True:
            # Send events from Redis pub/sub or internal event bus
            event = await event_queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
```

---

#### ENH-08-B: SSE Endpoint for Task Progress

**Description:** Add a Server-Sent Events endpoint for streaming task execution progress. This provides a simpler alternative to WebSockets for clients that only need to receive updates.

**Files to create:**
- `src/nexus/api/routes/sse.py`

**Dependencies:** None

**Estimated effort:** Small

**Acceptance criteria:**
- SSE endpoint at `/api/v1/tasks/{task_id}/stream`
- Streams: step started, step completed, token usage, final result
- Uses `text/event-stream` content type
- Client can reconnect using `Last-Event-ID` header
- Events have sequential IDs for resumption
- Endpoint closes when task completes

---

#### ENH-08-C: Dashboard WebSocket Client

**Description:** Update the React dashboard to connect via WebSocket for real-time updates instead of polling. Agent status indicators and task progress bars update in real-time.

**Files to modify:**
- `dashboard/src/hooks/useWebSocket.ts` (create or update)
- `dashboard/src/hooks/useAgents.ts` (integrate real-time updates)
- `dashboard/src/hooks/useTasks.ts` (integrate real-time updates)
- `dashboard/src/components/AgentStatusBadge.tsx` (live status indicator)

**Dependencies:** ENH-08-A

**Estimated effort:** Medium

**Acceptance criteria:**
- Dashboard connects WebSocket on mount with auth token
- Agent status badges update without page refresh
- Task progress shows real-time step completion
- Reconnection with exponential backoff on disconnect
- Visual indicator showing connection status (connected/reconnecting/disconnected)

---

### ENH-09: Vector Search / Embeddings

#### ENH-09-A: Embedding Generation Service

**Description:** Create a service that generates text embeddings using the OpenAI embeddings API (or local model fallback). Embeddings are used for semantic search in the knowledge/memory system.

**Files to create:**
- `src/nexus/memory/embeddings.py`

**Files to modify:**
- `src/nexus/config.py` (add `embedding_model`, `embedding_dimensions` settings)

**Dependencies:** FIX-01-A (OpenAI API integration)

**Estimated effort:** Medium

**Acceptance criteria:**
- `EmbeddingService.embed(text: str) -> list[float]` generates a single embedding
- `EmbeddingService.embed_batch(texts: list[str]) -> list[list[float]]` generates batch embeddings
- Uses OpenAI `text-embedding-3-small` by default (1536 dimensions)
- Configurable model and dimensions
- Caches embeddings by content hash to avoid re-computation
- Rate limiting on API calls

**Code hints:**
```python
class EmbeddingService:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self._api_key = api_key
        self._model = model

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": text},
            )
            return response.json()["data"][0]["embedding"]
```

---

#### ENH-09-B: pgvector Integration

**Description:** Add pgvector extension support to PostgreSQL for storing and querying vector embeddings. Create the embedding storage table and similarity search queries.

**Files to modify:**
- `src/nexus/models/knowledge.py` (add embedding column using pgvector)
- `src/nexus/memory/store.py` (add vector storage methods)

**Files to create:**
- `alembic/versions/003_add_pgvector.py` (migration to enable pgvector and add embedding columns)

**Dependencies:** ENH-09-A, FIX-03-A

**Estimated effort:** Medium

**Acceptance criteria:**
- Migration creates `CREATE EXTENSION IF NOT EXISTS vector`
- `knowledge_chunks` table has a `vector(1536)` column for embeddings
- HNSW index on vector column for fast similarity search
- Query function: `find_similar(embedding, limit, threshold)` using cosine distance
- SQLAlchemy/SQLModel integration with pgvector types

**Code hints:**
```python
# In migration:
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
op.add_column("knowledge_chunks", sa.Column("embedding", Vector(1536)))
op.create_index("ix_knowledge_chunks_embedding", "knowledge_chunks", ["embedding"],
                postgresql_using="hnsw",
                postgresql_ops={"embedding": "vector_cosine_ops"})

# In query:
from pgvector.sqlalchemy import Vector
statement = select(KnowledgeChunk).order_by(
    KnowledgeChunk.embedding.cosine_distance(query_embedding)
).limit(10)
```

---

#### ENH-09-C: Hybrid Search (BM25 + Vector)

**Description:** Implement hybrid search that combines BM25 keyword matching (existing `retriever.py`) with vector similarity search and uses reciprocal rank fusion to merge results.

**Files to modify:**
- `src/nexus/memory/retriever.py`

**Dependencies:** ENH-09-A, ENH-09-B

**Estimated effort:** Medium

**Acceptance criteria:**
- `HybridRetriever.search(query, limit)` runs both BM25 and vector search
- Results merged using Reciprocal Rank Fusion (RRF) with configurable k parameter
- BM25 weight and vector weight are configurable
- Returns unified scored results with source attribution (bm25, vector, both)
- Performance: hybrid search completes in < 500ms for typical knowledge bases

**Code hints:**
```python
def reciprocal_rank_fusion(
    bm25_results: list[tuple[str, float]],
    vector_results: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Merge ranked lists using RRF."""
    scores: dict[str, float] = {}
    for rank, (doc_id, _) in enumerate(bm25_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
    for rank, (doc_id, _) in enumerate(vector_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

---

#### ENH-09-D: Knowledge Chunking Pipeline

**Description:** Implement a configurable text chunking pipeline for knowledge ingestion. Supports multiple strategies (fixed-size, paragraph-based, semantic) for splitting documents before embedding.

**Files to create:**
- `src/nexus/memory/chunking.py`

**Dependencies:** ENH-09-A

**Estimated effort:** Small

**Acceptance criteria:**
- `FixedSizeChunker(chunk_size=512, overlap=50)` splits by token count with overlap
- `ParagraphChunker()` splits on double newlines, respecting max size
- `SemanticChunker(embedding_service)` splits at semantic boundaries (sentence-level with similarity threshold)
- All chunkers implement `Chunker` protocol: `chunk(text: str) -> list[TextChunk]`
- `TextChunk` includes: text, start_offset, end_offset, metadata
- Configurable via settings

---

### ENH-10: Channel Integrations

#### ENH-10-A: Slack Integration

**Description:** Implement Slack integration with OAuth 2.0 flow, Events API subscription, and message posting. Agents can receive tasks from Slack messages and post results back.

**Files to create:**
- `src/nexus/channels/slack.py`
- `src/nexus/api/routes/channels/slack.py`

**Files to modify:**
- `src/nexus/config.py` (add Slack credentials)

**Dependencies:** None

**Estimated effort:** Large

**Acceptance criteria:**
- OAuth 2.0 flow for Slack workspace installation
- Events API endpoint receives and verifies Slack events (URL verification challenge)
- Message handler: mentions of the bot trigger task creation
- Message posting: agent results posted back to originating channel/thread
- Slash commands for common operations (/nexus status, /nexus run)
- Token storage per-company (multi-tenant Slack app)

---

#### ENH-10-B: Discord Bot Integration

**Description:** Implement Discord bot integration using the Discord Gateway for receiving events and REST API for posting messages.

**Files to create:**
- `src/nexus/channels/discord.py`
- `src/nexus/api/routes/channels/discord.py`

**Files to modify:**
- `src/nexus/config.py` (add Discord bot token)

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- Bot connects to Discord Gateway via WebSocket
- Responds to mentions and direct messages
- Task creation from Discord messages
- Result delivery back to originating channel
- Rich embeds for formatted results
- Bot presence/status updates

---

#### ENH-10-C: Generic Webhook Channel

**Description:** Implement a generic outbound webhook channel that can deliver agent results to any configured HTTP endpoint. Supports payload templates, signatures, and retry logic.

**Files to create:**
- `src/nexus/channels/webhook.py`

**Dependencies:** FIX-01-D (retry module)

**Estimated effort:** Small

**Acceptance criteria:**
- Configurable webhook URL per company
- Payload template with variable substitution (agent_name, task_result, timestamp)
- HMAC-SHA256 signature in header for verification
- Retry with exponential backoff on delivery failure
- Delivery status tracking (pending, delivered, failed)
- Dead letter queue for permanently failed deliveries

---

#### ENH-10-D: Email Notifications (SMTP)

**Description:** Implement email notification channel using SMTP for sending agent results, alerts, and status updates to configured recipients.

**Files to create:**
- `src/nexus/channels/email.py`

**Files to modify:**
- `src/nexus/config.py` (add SMTP settings)

**Dependencies:** None

**Estimated effort:** Small

**Acceptance criteria:**
- SMTP connection with TLS support
- HTML and plain text email templates
- Send notifications on: task completion, agent error, kill switch activation
- Per-company recipient configuration
- Rate limiting on email sends (max 10/minute per company)
- Email queue with async delivery

---

### ENH-11: Plugin System

#### ENH-11-A: Plugin Discovery and Loading

**Description:** Implement a plugin system that discovers plugins from a configured directory, loads them dynamically, and provides lifecycle management (install, configure, enable, disable, uninstall).

**Files to create:**
- `src/nexus/plugins/__init__.py`
- `src/nexus/plugins/loader.py`
- `src/nexus/plugins/registry.py`
- `src/nexus/plugins/base.py`

**Dependencies:** None

**Estimated effort:** Large

**Acceptance criteria:**
- Plugins are Python packages in `plugins/` directory with a `plugin.yaml` manifest
- `PluginBase` abstract class defines the plugin interface (on_load, on_unload, register_tools, register_routes)
- `PluginLoader` discovers manifests and imports plugin modules
- `PluginRegistry` tracks installed plugins, their state, and configuration
- Plugins are loaded in dependency order
- Errors in one plugin don't prevent others from loading

**Code hints:**
```python
# plugin.yaml manifest:
# name: my-plugin
# version: 1.0.0
# description: Does something useful
# author: developer
# dependencies: []
# entry_point: my_plugin.main:MyPlugin

class PluginBase(ABC):
    @abstractmethod
    async def on_load(self, context: PluginContext) -> None: ...
    @abstractmethod
    async def on_unload(self) -> None: ...
    def register_tools(self) -> list[ToolDefinition]: return []
    def register_routes(self) -> list[APIRoute]: return []
    def register_hooks(self) -> list[Hook]: return []
```

---

#### ENH-11-B: Plugin Sandboxing

**Description:** Add security boundaries for plugins: restrict file system access, limit network calls, enforce resource quotas, and audit plugin actions.

**Files to create:**
- `src/nexus/plugins/sandbox.py`

**Dependencies:** ENH-11-A

**Estimated effort:** Medium

**Acceptance criteria:**
- Plugins run with restricted permissions (no arbitrary file access)
- Network calls are proxied through a gateway that enforces allowlists
- Resource limits: max memory, max CPU time per invocation
- All plugin actions are logged to the audit system
- Plugin crash is isolated (does not crash the main server)

---

#### ENH-11-C: Plugin API Routes

**Description:** Add API routes for managing plugins: list installed, install new, configure, enable/disable, and view plugin status.

**Files to create:**
- `src/nexus/api/routes/plugins.py`

**Dependencies:** ENH-11-A

**Estimated effort:** Small

**Acceptance criteria:**
- GET `/api/v1/plugins` - list installed plugins with status
- POST `/api/v1/plugins/install` - install a plugin from path or URL
- PUT `/api/v1/plugins/{name}/config` - update plugin configuration
- POST `/api/v1/plugins/{name}/enable` - enable a plugin
- POST `/api/v1/plugins/{name}/disable` - disable a plugin
- DELETE `/api/v1/plugins/{name}` - uninstall a plugin
- All endpoints tenant-scoped

---

### ENH-12: A2A Protocol (Agent-to-Agent Network Transport)

#### ENH-12-A: A2A HTTP Transport Layer

**Description:** Implement HTTP-based agent-to-agent communication following the A2A protocol spec. Agents can delegate subtasks to other agents (potentially on different NEXUS instances) and receive results.

**Files to create:**
- `src/nexus/communication/a2a_transport.py`
- `src/nexus/communication/a2a_protocol.py`

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- `A2AClient.send_task(agent_url, task)` sends a task to a remote agent
- `A2AClient.get_task_status(agent_url, task_id)` polls for result
- A2A server endpoint: POST `/api/v1/a2a/tasks` receives tasks from other agents
- Task format follows A2A spec: `{"id", "message", "artifacts", "status"}`
- Authentication via shared secret or mTLS
- Timeout and retry on communication failure

---

#### ENH-12-B: Agent Discovery and Advertisement

**Description:** Implement agent discovery so that agents can advertise their capabilities and other agents (or instances) can discover them for delegation.

**Files to create:**
- `src/nexus/communication/discovery.py`

**Files to modify:**
- `src/nexus/api/routes/communication.py` (add discovery endpoints)

**Dependencies:** ENH-12-A

**Estimated effort:** Medium

**Acceptance criteria:**
- Agents publish an "agent card" with: name, description, capabilities, skills, endpoint URL
- GET `/.well-known/agent.json` serves the agent card for this instance
- `DiscoveryService.find_agents(capability)` queries known registries
- Local registry for agents within the same NEXUS instance
- Remote registry query for cross-instance discovery
- Agent cards cached with configurable TTL

---

#### ENH-12-C: Cross-Instance Task Delegation

**Description:** Implement the delegation workflow where an agent can delegate a subtask to another agent (local or remote), wait for the result, and incorporate it into their own task execution.

**Files to modify:**
- `src/nexus/runtime/executor.py`
- `src/nexus/communication/a2a_transport.py`

**Dependencies:** ENH-12-A, ENH-12-B

**Estimated effort:** Medium

**Acceptance criteria:**
- Executor supports a `delegate` step type in task plans
- Delegation resolves target agent via discovery service
- Subtask is sent via A2A transport
- Executor polls or subscribes for result (configurable strategy)
- Delegation timeout with fallback behavior (fail or skip)
- Delegation chain tracked for debugging (parent task -> child task)

---

## LOWER PRIORITY - Polish and Production

---

### POL-13: Docker/Deployment Hardening

#### POL-13-A: Health Check Endpoints

**Description:** Add proper health check endpoints that Docker and load balancers can use to determine if the service is ready to accept traffic. Checks database connectivity, Redis availability, and critical service health.

**Files to create:**
- `src/nexus/api/routes/health.py` (replace or enhance existing)

**Dependencies:** None

**Estimated effort:** Small

**Acceptance criteria:**
- GET `/health/live` - returns 200 if process is running (liveness probe)
- GET `/health/ready` - returns 200 only if DB and Redis are connected (readiness probe)
- GET `/health/detailed` - returns JSON with component-by-component status (for dashboards)
- Docker compose healthcheck uses `/health/ready`
- Response includes version, uptime, and component statuses

---

#### POL-13-B: Production Docker Compose

**Description:** Create a production-ready Docker Compose configuration with proper secrets management, persistent volumes, resource limits, and security hardening.

**Files to create:**
- `docker-compose.prod.yml`
- `.env.example` (template for production environment variables)

**Dependencies:** POL-13-A

**Estimated effort:** Medium

**Acceptance criteria:**
- Secrets via Docker secrets or environment file (not hardcoded)
- Resource limits (memory, CPU) on all services
- Restart policies (unless-stopped)
- Named volumes for data persistence
- Network isolation (internal network for DB/Redis, external only for API)
- Non-root user in containers
- Read-only file system where possible
- Logging configuration (json-file with rotation)

---

#### POL-13-C: Nginx Reverse Proxy Configuration

**Description:** Add nginx configuration for production deployment with TLS termination, rate limiting, request buffering, and WebSocket upgrade support.

**Files to create:**
- `deploy/nginx/nginx.conf`
- `deploy/nginx/ssl.conf` (TLS settings)

**Dependencies:** POL-13-B

**Estimated effort:** Small

**Acceptance criteria:**
- TLS 1.2+ with strong cipher suites
- HTTP/2 enabled
- WebSocket upgrade for `/ws/` paths
- Rate limiting (10 req/s per IP for API, higher for static)
- Request size limits (10MB max body)
- Security headers (HSTS, X-Frame-Options, CSP)
- Proxy pass to nexus-server container
- Static file serving for dashboard build

---

#### POL-13-D: Kubernetes Helm Chart

**Description:** Create a Helm chart for deploying NEXUS to Kubernetes with configurable values for replicas, resources, secrets, and ingress.

**Files to create:**
- `deploy/helm/nexus/Chart.yaml`
- `deploy/helm/nexus/values.yaml`
- `deploy/helm/nexus/templates/deployment.yaml`
- `deploy/helm/nexus/templates/service.yaml`
- `deploy/helm/nexus/templates/ingress.yaml`
- `deploy/helm/nexus/templates/configmap.yaml`
- `deploy/helm/nexus/templates/secret.yaml`
- `deploy/helm/nexus/templates/hpa.yaml`

**Dependencies:** POL-13-A, POL-13-B

**Estimated effort:** Large

**Acceptance criteria:**
- `helm install nexus ./deploy/helm/nexus` deploys all components
- Configurable via values.yaml (replicas, resources, image tags)
- Horizontal Pod Autoscaler based on CPU/memory
- Ingress with TLS certificate configuration
- PostgreSQL and Redis can be external or in-cluster
- Health check probes configured
- Secrets from Kubernetes secrets or external secrets operator

---

### POL-14: Testing and CI

#### POL-14-A: Integration Test Infrastructure

**Description:** Set up pytest-asyncio integration test infrastructure with a test database, fixtures for creating test data, and proper isolation between tests.

**Files to create:**
- `tests/conftest.py` (enhanced with async DB fixtures)
- `tests/integration/__init__.py`
- `tests/integration/conftest.py`
- `tests/fixtures/__init__.py`
- `tests/fixtures/factories.py`

**Dependencies:** FIX-03-A

**Estimated effort:** Medium

**Acceptance criteria:**
- `pytest-asyncio` configured for async tests
- Test database created/destroyed per test session
- Alembic migrations run on test DB before tests
- Transaction rollback between tests (isolation)
- Factory functions for creating test companies, users, agents, tasks
- `httpx.AsyncClient` fixture for testing API routes

**Code hints:**
```python
# conftest.py
@pytest_asyncio.fixture
async def db_session():
    """Create a test database session with transaction rollback."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine) as session:
        async with session.begin():
            yield session
            await session.rollback()

@pytest_asyncio.fixture
async def client(db_session):
    """FastAPI test client with overridden DB dependency."""
    app.dependency_overrides[get_session] = lambda: db_session
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        yield client
```

---

#### POL-14-B: Route-Level API Tests

**Description:** Write FastAPI TestClient tests for all major API routes, verifying request/response formats, status codes, authentication, and error handling.

**Files to create:**
- `tests/integration/test_api_agents.py`
- `tests/integration/test_api_tasks.py`
- `tests/integration/test_api_companies.py`
- `tests/integration/test_api_tools.py`
- `tests/integration/test_api_governance.py`

**Dependencies:** POL-14-A

**Estimated effort:** Large

**Acceptance criteria:**
- Tests cover CRUD operations for agents, tasks, companies, tools
- Tests verify authentication is required (401 without token)
- Tests verify authorization (403 for wrong role)
- Tests verify input validation (422 for malformed requests)
- Tests verify pagination, filtering, sorting
- At least 80% route coverage

---

#### POL-14-C: GitHub Actions CI Pipeline

**Description:** Create a GitHub Actions workflow that runs on every PR: linting, type checking, unit tests, integration tests, and Docker build verification.

**Files to create:**
- `.github/workflows/ci.yml`

**Dependencies:** POL-14-A

**Estimated effort:** Medium

**Acceptance criteria:**
- Triggers on push to main and all PRs
- Steps: checkout, setup Python 3.12, install deps, lint (ruff), type check (mypy), test (pytest)
- PostgreSQL and Redis services for integration tests
- Docker build step to verify image builds
- Test coverage report uploaded as artifact
- Caching for pip dependencies
- Matrix testing (Python 3.11, 3.12) if desired

**Code hints:**
```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: nexus_test
        ports: ["5432:5432"]
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: ruff check src/ tests/
      - run: pytest --cov=src/nexus tests/
```

---

#### POL-14-D: Pre-commit Hooks Configuration

**Description:** Add pre-commit hook configuration for consistent code quality enforcement: formatting, linting, type checking, and import sorting.

**Files to create:**
- `.pre-commit-config.yaml`

**Dependencies:** None

**Estimated effort:** Small

**Acceptance criteria:**
- ruff format (code formatting)
- ruff check (linting)
- mypy (type checking, non-blocking)
- trailing whitespace removal
- end-of-file fixer
- YAML/JSON validation
- Large file check (prevent accidental commits of big files)

---

### POL-15: Observability

#### POL-15-A: Structured Logging

**Description:** Replace print statements and basic logging with structured JSON logging using Python's `structlog` or standard library with JSON formatter. Add correlation IDs for request tracing.

**Files to create:**
- `src/nexus/observability/__init__.py`
- `src/nexus/observability/logging.py`

**Files to modify:**
- `src/nexus/api/middleware.py` (add request correlation ID)
- `src/nexus/config.py` (add log format settings)

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- All log output is JSON-formatted in production (human-readable in development)
- Every request gets a unique `correlation_id` (from header or generated)
- `correlation_id` is included in all log entries for that request
- Log levels used consistently: DEBUG (internals), INFO (operations), WARNING (recoverable), ERROR (failures)
- Sensitive data (API keys, passwords) never logged
- Performance: no measurable overhead from structured logging

---

#### POL-15-B: Prometheus Metrics Endpoint

**Description:** Add a `/metrics` endpoint that exposes Prometheus-compatible metrics: request counts, latencies, active agents, task queue depth, error rates, and LLM API usage.

**Files to create:**
- `src/nexus/observability/metrics.py`
- `src/nexus/api/routes/metrics.py`

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- GET `/metrics` returns Prometheus text format
- Metrics: `nexus_requests_total{method, path, status}` (counter)
- Metrics: `nexus_request_duration_seconds{method, path}` (histogram)
- Metrics: `nexus_active_agents{company_id}` (gauge)
- Metrics: `nexus_tasks_queued{company_id}` (gauge)
- Metrics: `nexus_llm_tokens_total{model, direction}` (counter)
- Metrics: `nexus_llm_cost_cents_total{model}` (counter)
- Metrics: `nexus_errors_total{type}` (counter)

---

#### POL-15-C: OpenTelemetry Tracing

**Description:** Add distributed tracing using OpenTelemetry SDK. Traces span the full request lifecycle including database queries, Redis operations, and LLM API calls.

**Files to create:**
- `src/nexus/observability/tracing.py`

**Files to modify:**
- `src/nexus/api/middleware.py` (add trace context propagation)

**Dependencies:** POL-15-A

**Estimated effort:** Medium

**Acceptance criteria:**
- OpenTelemetry SDK initialized with configurable exporter (OTLP, Jaeger, console)
- Automatic instrumentation for FastAPI, httpx, SQLAlchemy, Redis
- Custom spans for: LLM API calls, tool executions, agent lifecycle events
- Trace context propagated via W3C Trace Context headers
- Configurable sampling rate (default 10% in production)
- Traces include: company_id, agent_id, task_id as attributes

---

#### POL-15-D: Grafana Dashboard Templates

**Description:** Create Grafana dashboard JSON templates for monitoring NEXUS in production. Dashboards cover system health, LLM usage, agent performance, and governance events.

**Files to create:**
- `deploy/grafana/dashboards/system-health.json`
- `deploy/grafana/dashboards/llm-usage.json`
- `deploy/grafana/dashboards/agent-performance.json`
- `deploy/grafana/provisioning/datasources.yaml`
- `deploy/grafana/provisioning/dashboards.yaml`

**Dependencies:** POL-15-B

**Estimated effort:** Medium

**Acceptance criteria:**
- System Health dashboard: request rate, error rate, latency percentiles, DB connections, Redis memory
- LLM Usage dashboard: tokens per model, cost per company, rate limit hits, error rates by provider
- Agent Performance dashboard: tasks completed, average duration, success rate, active agents
- Dashboards auto-provisioned when Grafana starts
- Variables for filtering by company, time range, agent

---

### POL-16: Dashboard Polish

#### POL-16-A: Authentication / Login Page

**Description:** Add a login page to the React dashboard with JWT token-based authentication. Store token in httpOnly cookie or secure localStorage with refresh token rotation.

**Files to create:**
- `dashboard/src/pages/LoginPage.tsx`
- `dashboard/src/hooks/useAuth.ts`
- `dashboard/src/context/AuthContext.tsx`

**Files to modify:**
- `dashboard/src/App.tsx` (add auth routing)
- `dashboard/src/api/client.ts` (add auth headers)

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- Login form with email/password
- JWT token stored securely (httpOnly cookie preferred)
- Auto-redirect to login on 401 responses
- Token refresh before expiry
- Logout clears token and redirects to login
- Protected routes redirect unauthenticated users

---

#### POL-16-B: Real-time Connection with WebSocket

**Description:** Connect the dashboard to the WebSocket endpoint for live updates. Replace polling-based data fetching with push-based updates for agent status and task progress.

**Files to modify:**
- `dashboard/src/hooks/useAgents.ts`
- `dashboard/src/hooks/useTasks.ts`
- `dashboard/src/components/AgentCard.tsx`
- `dashboard/src/components/TaskList.tsx`

**Dependencies:** ENH-08-A, ENH-08-C

**Estimated effort:** Medium

**Acceptance criteria:**
- Agent cards show live status without refresh
- Task progress bars animate in real-time
- New tasks appear in list without polling
- Connection status indicator in header
- Graceful degradation to polling if WebSocket unavailable

---

#### POL-16-C: Notification System (Toast Messages)

**Description:** Add a toast notification system that shows real-time alerts for important events: task completion, agent errors, kill switch activation, budget warnings.

**Files to create:**
- `dashboard/src/components/ToastNotification.tsx`
- `dashboard/src/hooks/useNotifications.ts`
- `dashboard/src/context/NotificationContext.tsx`

**Dependencies:** POL-16-B

**Estimated effort:** Small

**Acceptance criteria:**
- Toast appears on: task completed, task failed, agent error, governance alert
- Toast types: success (green), error (red), warning (yellow), info (blue)
- Auto-dismiss after 5 seconds (configurable)
- Click to dismiss
- Stack up to 3 toasts, queue the rest
- Sound notification option (configurable)

---

#### POL-16-D: Performance Optimization

**Description:** Optimize React rendering performance with React.memo, useMemo, useCallback, and virtual scrolling for large lists (agents, tasks, audit logs).

**Files to modify:**
- `dashboard/src/components/AgentCard.tsx` (React.memo)
- `dashboard/src/components/TaskList.tsx` (virtual scrolling)
- `dashboard/src/components/AuditLog.tsx` (virtual scrolling)
- `dashboard/src/hooks/useAgents.ts` (optimistic updates)

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- Agent list renders smoothly with 100+ agents (virtual scrolling)
- Task list handles 1000+ tasks without lag
- Audit log uses windowed rendering for long histories
- Component re-renders minimized (React DevTools profiler shows no unnecessary renders)
- Bundle size analyzed and lazy-loaded where appropriate

---

#### POL-16-E: End-to-End Tests (Playwright)

**Description:** Add Playwright E2E tests that verify critical user flows: login, view agents, create task, monitor progress, view audit log.

**Files to create:**
- `dashboard/e2e/login.spec.ts`
- `dashboard/e2e/agents.spec.ts`
- `dashboard/e2e/tasks.spec.ts`
- `dashboard/playwright.config.ts`

**Dependencies:** POL-16-A

**Estimated effort:** Medium

**Acceptance criteria:**
- Test: login with valid credentials, see dashboard
- Test: login with invalid credentials, see error
- Test: view agent list, click agent, see details
- Test: create a new task, see it in list
- Test: view audit log entries
- Tests run in CI (headless Chromium)
- Screenshot on failure for debugging

---

### POL-17: Documentation

#### POL-17-A: API Documentation with Examples

**Description:** Create comprehensive API documentation beyond auto-generated Swagger. Include practical examples, authentication guide, error handling patterns, and common workflows.

**Files to create:**
- `docs/api-guide.md`

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- Authentication section (how to get a token, how to use it)
- Example requests/responses for top 10 most-used endpoints
- Error handling guide (error format, common error codes, retry guidance)
- Pagination explanation with examples
- Rate limiting documentation
- WebSocket/SSE subscription guide

---

#### POL-17-B: Deployment Guide

**Description:** Write a deployment guide covering development setup, Docker Compose deployment, and production deployment on AWS/GCP/self-hosted.

**Files to create:**
- `docs/deployment-guide.md`

**Dependencies:** POL-13-B

**Estimated effort:** Medium

**Acceptance criteria:**
- Development setup: prerequisites, clone, configure, run
- Docker Compose: quick start, configuration, customization
- Production: server requirements, security checklist, backup strategy
- AWS deployment: ECS/EKS options, RDS for PostgreSQL, ElastiCache for Redis
- GCP deployment: Cloud Run/GKE options, Cloud SQL, Memorystore
- Monitoring setup: connecting to observability stack

---

#### POL-17-C: Agent Development Guide

**Description:** Write a guide for developers who want to create custom adapters, define agent templates, and extend NEXUS with new agent capabilities.

**Files to create:**
- `docs/agent-development-guide.md`

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- Adapter Protocol explanation (what methods to implement)
- Step-by-step: creating a new adapter (with code examples)
- Agent template authoring (YAML format, capability declarations)
- Skill definition guide (how to create agent skills)
- Testing adapters (unit test patterns, mock LLM responses)
- Registration and configuration

---

#### POL-17-D: Architecture Decision Records

**Description:** Create ADR documents for the major architectural decisions made during NEXUS development: why SQLModel over raw SQLAlchemy, why FastAPI, why LangGraph patterns, multi-tenancy approach, etc.

**Files to create:**
- `docs/adr/001-framework-choices.md`
- `docs/adr/002-multi-tenancy-strategy.md`
- `docs/adr/003-adapter-pattern.md`
- `docs/adr/004-governance-architecture.md`
- `docs/adr/005-memory-tiered-storage.md`
- `docs/adr/README.md`

**Dependencies:** None

**Estimated effort:** Medium

**Acceptance criteria:**
- Each ADR follows the standard format: Title, Status, Context, Decision, Consequences
- ADR-001: FastAPI + SQLModel + Alembic + async stack rationale
- ADR-002: Row-level tenant isolation via company_id approach
- ADR-003: Protocol-based adapter pattern for LLM providers
- ADR-004: Layered governance (rate limit -> budget -> guardrails -> approval)
- ADR-005: Hot/warm/cold memory tier justification

---

#### POL-17-E: Troubleshooting Guide

**Description:** Create a troubleshooting guide covering common issues: database connection failures, Redis timeouts, LLM API errors, tenant isolation violations, and deployment problems.

**Files to create:**
- `docs/troubleshooting.md`

**Dependencies:** None

**Estimated effort:** Small

**Acceptance criteria:**
- Organized by symptom (what the user sees)
- Each entry: symptom, likely causes, diagnostic steps, solution
- Covers: connection refused (DB/Redis), 500 errors, slow responses, memory leaks
- Covers: LLM API errors (rate limited, invalid key, model not found)
- Covers: Docker issues (container won't start, health check failing)
- Covers: Migration issues (failed migration, schema drift)

---

## Dependency Graph

```
FIX-03-A (initial migration)
  |-- FIX-02-A (kill switch persistence)
  |-- FIX-02-B (RBAC persistence)
  |-- FIX-02-E (audit persistence)
  |-- FIX-05-A (checkpoint schema)
  |     |-- FIX-05-B (crash recovery)
  |     |     |-- FIX-05-C (interrupt/resume)
  |-- ENH-09-B (pgvector)
  |-- POL-14-A (test infrastructure)

FIX-01-A (OpenAI integration)
  |-- FIX-01-E (usage tracker)
  |-- ENH-09-A (embeddings)
  |     |-- ENH-09-B (pgvector)
  |     |     |-- ENH-09-C (hybrid search)
  |     |-- ENH-09-D (chunking)

FIX-01-D (retry module)
  |-- ENH-07-A (Claude Code adapter)
  |-- ENH-07-B (HTTP adapter)
  |-- ENH-10-C (webhook channel)

FIX-06-A (JSON-RPC)
  |-- FIX-06-B (stdio transport)
  |-- FIX-06-C (SSE transport)
  |-- FIX-06-D (MCP client)
  |     |-- ENH-07-C (MCP adapter)

FIX-04-A (isolation audit)
  |-- FIX-04-B (add filters)
  |     |-- FIX-04-C (tenant middleware)
  |     |     |-- FIX-04-D (isolation tests)

ENH-08-A (WebSocket endpoint)
  |-- ENH-08-C (dashboard WebSocket)
  |     |-- POL-16-B (real-time dashboard)

POL-14-A (test infra)
  |-- POL-14-B (route tests)
  |-- POL-14-C (CI pipeline)

POL-13-A (health checks)
  |-- POL-13-B (prod docker compose)
  |     |-- POL-13-C (nginx)
  |     |-- POL-13-D (helm chart)
```

## Implementation Order (Recommended)

### Sprint 1: Foundation (Weeks 1-2)
1. FIX-03-A - Initial migration (unblocks everything DB-related)
2. FIX-01-A - OpenAI integration (unblocks real functionality)
3. FIX-01-B - Anthropic integration
4. FIX-01-C - Ollama integration
5. FIX-01-D - Shared retry module
6. FIX-04-A - Tenant isolation audit

### Sprint 2: Persistence (Weeks 3-4)
1. FIX-02-A - KillSwitch to DB
2. FIX-02-B - RBAC to DB
3. FIX-02-C - Rate limiter to Redis
4. FIX-02-D - Circuit breaker to Redis
5. FIX-02-E - Audit buffered writes
6. FIX-03-B - Seed data
7. FIX-04-B - Add tenant filters

### Sprint 3: Protocol & Safety (Weeks 5-6)
1. FIX-06-A - JSON-RPC layer
2. FIX-06-B - Stdio transport
3. FIX-06-C - SSE transport
4. FIX-06-D - MCP client
5. FIX-04-C - Tenant middleware
6. FIX-04-D - Isolation tests
7. FIX-05-A - Checkpoint schema

### Sprint 4: Durability & Real-time (Weeks 7-8)
1. FIX-05-B - Crash recovery
2. FIX-05-C - Interrupt/resume
3. FIX-01-E - Usage tracking
4. ENH-08-A - WebSocket endpoint
5. ENH-08-B - SSE endpoint
6. ENH-07-A - Claude Code adapter
7. ENH-07-B - HTTP adapter
8. ENH-07-C - MCP adapter

### Sprint 5: Intelligence (Weeks 9-10)
1. ENH-09-A - Embedding service
2. ENH-09-B - pgvector integration
3. ENH-09-C - Hybrid search
4. ENH-09-D - Chunking pipeline
5. ENH-08-C - Dashboard WebSocket
6. ENH-12-A - A2A transport

### Sprint 6: Integrations (Weeks 11-12)
1. ENH-10-A - Slack integration
2. ENH-10-B - Discord integration
3. ENH-10-C - Webhook channel
4. ENH-10-D - Email notifications
5. ENH-12-B - Agent discovery
6. ENH-12-C - Cross-instance delegation

### Sprint 7: Platform (Weeks 13-14)
1. ENH-11-A - Plugin discovery/loading
2. ENH-11-B - Plugin sandboxing
3. ENH-11-C - Plugin API routes
4. POL-14-A - Test infrastructure
5. POL-14-B - Route tests
6. POL-14-D - Pre-commit hooks

### Sprint 8: Production (Weeks 15-16)
1. POL-13-A - Health checks
2. POL-13-B - Production Docker Compose
3. POL-13-C - Nginx config
4. POL-14-C - CI pipeline
5. POL-15-A - Structured logging
6. POL-15-B - Prometheus metrics

### Sprint 9: Observability & Polish (Weeks 17-18)
1. POL-15-C - OpenTelemetry tracing
2. POL-15-D - Grafana dashboards
3. POL-16-A - Dashboard login
4. POL-16-B - Dashboard real-time
5. POL-16-C - Toast notifications
6. POL-16-D - Performance optimization

### Sprint 10: Documentation & Finalization (Weeks 19-20)
1. FIX-03-C - Migration docs
2. POL-13-D - Helm chart
3. POL-16-E - E2E tests
4. POL-17-A - API guide
5. POL-17-B - Deployment guide
6. POL-17-C - Agent development guide
7. POL-17-D - ADRs
8. POL-17-E - Troubleshooting guide

---

## Effort Summary

| Effort Level | Count | Definition |
|-------------|-------|-----------|
| Small | 20 | 1-4 hours, single file or straightforward change |
| Medium | 35 | 4-16 hours, multiple files, moderate complexity |
| Large | 7 | 16-40 hours, many files, high complexity or broad scope |

**Total micro-phases:** 62
**Estimated total effort:** 25-35 developer-weeks (1 person) or 8-12 weeks (3-person team)

---

## Notes for Implementers

1. **Always run tests after changes.** Use `pytest tests/ -x` for fast failure detection.
2. **Check tenant isolation on every new route.** If a route fetches by ID, it must filter by `company_id`.
3. **LLM adapters should be testable without API keys.** Use dependency injection and mock the httpx client in tests.
4. **Redis operations should have in-memory fallback.** Not all development environments have Redis running.
5. **Database operations must be async.** Use `async with session.begin()` pattern throughout.
6. **Configuration follows 12-factor.** All secrets come from environment variables, never hardcoded.
7. **Each micro-phase should result in a working system.** Never leave the codebase in a broken state between phases.
