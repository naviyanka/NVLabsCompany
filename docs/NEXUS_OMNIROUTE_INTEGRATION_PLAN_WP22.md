# NEXUS x OmniRoute -- Full Integration Plan (WP-22 series)

> Addendum to `00_NEXT_CHANGES_PROMPT_R3.md`. Read that file first: rules R1-R8 in it still apply.
>
> **Baseline commit:** `68144249f0dc732696c0a6dd7bc9ee408fa037e1` (`main`, 2026-09-09T11:50:21Z)
> **Predecessors:** `00_NEXT_CHANGES_PROMPT.md` (WP-1..WP-9), `_R2.md` (WP-7..WP-14), `_R3.md` (WP-15..WP-21)
> **Repo destination:** `docs/production_readiness_plan/00_OMNIROUTE_INTEGRATION_PLAN_WP22.md`
> **Score today:** 7.4 weighted. **After R3 alone:** ~8.6. **After R3 + WP-22:** ~8.9, with LLM provider coverage 8.0 -> 9.5 and budget control 7.5 -> 9.5.
> **OmniRoute pinned at:** `diegosouzapw/OmniRoute` default-branch HEAD `ba597b631d22d85e56db6982f24b7d1ebe238df9`, release v3.8.51, MIT, Node >= 22.22.2.

---

## 0. Executive summary

OmniRoute is a self-hosted LLM gateway that speaks OpenAI-compatible (`/v1/chat/completions`), Anthropic-compatible (`/v1/messages`) and OpenAI-Responses (`/v1/responses`) wire formats on a single endpoint, fronting 352 registered providers / 2,554 provider-model pairs / 1,283 raw model IDs, with 19 routing strategies, a 4-tier cost cascade, 3-layer resilience, a 110-tool MCP server, and per-API-key USD budgets and token limits.

NEXUS already has the right shape to absorb it. `src/nexus/adapters/registry.py` is a real plugin registry, `src/nexus/adapters/uastl.py::resolve_provider` is a single chokepoint through which every LLM dispatch passes, and `openai_adapter.py` already honours a per-session `api_base` on both the streaming and non-streaming paths.

**The integration is NOT "add an OmniRoute adapter".** That would hard-code one vendor into the core. The correct design -- and the one this plan specifies -- is a generic **Connection** abstraction:

> A Connection is a user-created record: `{ name, base_url, api_key, wire_format }` where `wire_format` is `openai` or `anthropic`. NEXUS ships two wire-format adapters and zero vendor adapters. OmniRoute becomes *one Connection the user happens to add*. So do Ollama, LM Studio, vLLM, OpenRouter, Together, LiteLLM, and anything that ships in the next three years -- at zero marginal code cost.

Three integration tiers, in dependency order:

| Tier | What | Effort | Risk |
|---|---|---|---|
| **Tier 0** | Connection abstraction + two wire formats. Point one Connection at OmniRoute. | 2-3 days | Low |
| **Tier 1** | Model discovery from the gateway. Real context windows. Real per-call cost. | 3-4 days | Low-medium |
| **Tier 2** | Two-tier budget (company ceiling in OmniRoute + per-agent in NEXUS), MCP tool bridge, routing audit trail. | 5-7 days | Medium; **blocked on WP-18** |

**Two things must NOT be delegated to OmniRoute** (justified in SS7 and SS8): per-agent budget enforcement, and embeddings.

---

## 1. Ground rules (extends R1-R8 from R3)

These are non-negotiable. A work package that violates one is rejected regardless of whether the code works.

- **R1** (carried) A test that names a function in its title or docstring MUST invoke that function. Importing it is not invoking it.
- **R2** (carried) Every acceptance test in this document MUST be shown FAILING at `68144249` and PASSING after the change. Paste both outputs in the PR body.
- **R3** (carried) "Wired" means: a live call site in non-test code, plus a test that fails when the call site is removed.
- **R4** (carried) File counts in the PR body must match the work package.
- **R5** (carried) Verify code, not commit messages.
- **R6** (carried) Never widen a privilege to make a test pass.
- **R7** (carried) Any budget change must state month-boundary behaviour explicitly in the PR body.
- **R8** (carried) No generated artifacts committed.
- **R9 (NEW) No vendor name in core code paths.** The strings `omniroute`, `OmniRoute`, `OMNIROUTE` may appear ONLY in: (a) docs, (b) `.env.example` / `docker-compose.yml` sample values, (c) tests and fixtures, (d) one optional convenience seeder. They must NOT appear in `adapters/`, `models_router/`, `api/routes/` (except a docstring example), or any model/migration. If OmniRoute is deleted tomorrow, NEXUS must still compile and every test must still pass.
- **R10 (NEW) No network in unit tests.** Every gateway interaction is tested against a `respx` / `httpx.MockTransport` fixture. A test that requires a running OmniRoute goes in `tests/integration/` behind the `requires_gateway` marker and is excluded from the default `pytest` run.
- **R11 (NEW) Cost is never floats-in-cents.** Gateway costs arrive as 10-decimal USD strings. Store integer micro-USD (`10^-6` USD). Never `float`, never `round(usd*100)` on the settle path. `math.ceil` on a sub-cent value is a correctness bug at free-tier volume, not a rounding preference.
- **R12 (NEW) Fail closed on budget, fail open on discovery.** If the gateway is unreachable: model discovery falls back to the static catalog and the app boots (fail open). If the budget ledger is unreachable: the call is refused (fail closed). The current code does the opposite for budgets -- `chat.py:640` catches `Exception` and logs `"Budget reservation failed, allowing call"`. That inversion is in scope for WP-22e.
- **R13 (NEW) One counter of record.** After WP-22e there is exactly one authoritative spend counter per scope. Denormalized mirrors are allowed only if a single reconciler writes them and a test proves they converge.

---

## 2. Verified current state (read this before writing any code)

Everything in this section was read at commit `68144249f0dc732696c0a6dd7bc9ee408fa037e1` or from a blob-SHA-identical local snapshot. Line numbers are authoritative. **Do not re-derive these; do not assume they are stale.**

### 2.1 The adapter layer

`src/nexus/adapters/registry.py`
- `_register_defaults()` at L34 registers exactly 11 adapter types at L48-L58: `openai`, `anthropic`, `ollama`, `hermes`, `claude_code`, `cli`, `http`, `mcp`, `azure_openai`, `bedrock`, `google_gemini`.
- `register_adapter(adapter_type, adapter_class)` at L60 raises `TypeError` unless `issubclass(..., BaseAdapter)`. **This is a genuine plugin seam. Use it. Do not edit `_register_defaults` to add a vendor.**
- `create_adapter(adapter_type, config=None)` at L81.

`src/nexus/adapters/uastl.py`
- `resolve_provider(adapter_type: str, model: str | None = None) -> tuple[str, dict[str, Any]]` at **L146**.
- `_PROVIDER_SPECS` maps 13+ logical providers onto the 11 registry keys. Note that DeepSeek (L64) and Groq (L73) already map to `registry_key = "openai"` with a custom `api_base` -- **the OpenAI-compatible-gateway pattern already exists in this file.**
- L186-L187 copy `spec["api_base"]` into the returned config dict.
- **L189 `return registry_key, config` is THE injection point for the whole integration.**

`src/nexus/adapters/openai_adapter.py` (HEAD blob `7c70d1ba1e4cff78404b2ff17846c66728e1d190`, 11,469 B)
- `self._api_base = "https://api.openai.com/v1"` in `__init__`.
- `_do_create_session` copies `session.config["api_base"]` -> `session.metadata["api_base"]` when present.
- BOTH `_do_execute` and `stream_execute` resolve `api_base = session.metadata.get("api_base", self._api_base)` and POST to `f"{api_base}/chat/completions"`.
- **P0 BUG, see WP-22a:** `_do_execute` builds `"Idempotency-Key": f"{session.session_id}:{hashlib.sha256(prompt.encode()).hexdigest()[:16]}"` but the module has no `import hashlib`. Module imports are `asyncio`, `uuid`, `datetime/timezone`, `typing.Any`, `BaseAdapter`, `estimate_cost_cents`, `AgentSession`, `TaskResult`; `httpx` is imported inside the function. **Every non-streaming OpenAI-format call raises `NameError`.** `stream_execute` does not set that header, so streaming still works. This regression landed after the local snapshot (local blob `5e653d290a104bcde1e0eb88114cfd036fbdc9be`, 11,362 B) and proves no test invokes `_do_execute`.
- `stream_execute` parses `data: ` SSE lines and breaks on `[DONE]`. **It performs no cost accounting at all.**

`src/nexus/adapters/anthropic_adapter.py`
- L35 `self._api_base = "https://api.anthropic.com/v1"`, consumed at L121 and L315. **Hard-coded, no per-session override.** This is the 3-line fix in WP-22b.

`src/nexus/adapters/http_adapter.py`
- `validate_config` REQUIRES `config["base_url"]` and runs it through `_guard_url(...)` (SSRF protection). `_do_create_session` stores `session.metadata["base_url"]`. Configurable `execute_path` / `status_path` / `health_path`.
- **Watch out:** `_guard_url` is backed by `src/nexus/governance/ssrf_protection.py`. A Connection pointing at a Docker-internal host (`http://omniroute:20128`) or `127.0.0.1` will likely be rejected. See WP-22b step 6.

`src/nexus/adapters/mcp_adapter.py` -- 285 lines, registered as `mcp`. Already exists. Reused unchanged in WP-22h.

### 2.2 The dispatch path (`src/nexus/api/routes/chat.py`, blob `943420c438f4fabe687f7e7b3e3f1a0f39184e6f`, 48,964 B)

This file contains the comment that makes it the correct integration point:

> "Every LLM dispatch in the app funnels through this function, so guarding here covers the orchestrator, pipelines, triggers and Temporal activities rather than just the chat route."

Order of operations inside `_call_llm`:

1. L583 `_resolve_adapter_type` -> `return resolve_provider(agent.adapter_type or "anthropic", agent.model)`
2. L721 `registry_key, config = _resolve_adapter_type(agent)`
3. **L725 HARD BLOCKER:** `if registry_key in ("anthropic", "openai", "azure_openai") and not api_key:` -- returns an in-character refusal string and files a `secret_request` Approval (max 3 pending). With a gateway configured and `OPENAI_API_KEY` empty, **nothing works**. The env map is at L731.
4. L773 `reservation_id = await _reserve_budget(...)`
5. L781-782 `adapter_registry = AdapterRegistry()` then `adapter = adapter_registry.create_adapter(registry_key)`
6. `session_config = {**config, "system_prompt": system_prompt}` then `session = await adapter.create_session(agent.id, session_config)`
7. L908, inside `finally:` -- `await _settle_budget(reservation_id, cost_cents=spend["cost_cents"], ...)`

Note step 5: `create_adapter(registry_key)` receives no config, but the config DOES reach the adapter via `create_session`. So injecting `api_base` into the dict returned at `uastl.py:189` is sufficient -- no `create_adapter` signature change needed.

### 2.3 The budget layer -- THREE parallel systems that do not talk to each other

This is the single most important finding in this document. NEXUS currently has three independent spend counters and two independent enforcement engines. **Any two-tier budget design built on top of this will produce wrong numbers.**

**System A -- `BudgetPolicy` / `CostEvent` via `BudgetService`** (`src/nexus/services/budget_service.py`, 429 lines, blob `a623681b5668f291c5ed4735791c686d0ba9cf4e`)

`src/nexus/models/budget.py` (blob `ecab68318eaf1374b747b2e1221d3986fb635c79`):
- `BudgetPolicy` / table `budget_policies`: `id`, `company_id`, `scope_type` (company|department|agent|project), `scope_id`, `metric` (cost_cents|tokens|api_calls), `window_kind` (monthly|weekly|daily|per_execution), `amount`, `spent_cents`, `reserved_cents`, `warn_percent` (default 80), `hard_stop_enabled` (default True), `is_active`, `created_at`, `updated_at`.
  - **There is NO `period_start_at` and NO `next_reset_at` column.** `window_kind` is stored and never used by the counters.
  - **There is NO provider or model scope column.**
  - `warn_percent` already exists and is already defaulted to 80 -- this is OmniRoute's `warningThreshold` in percent form. It is computed in `check_budget` and then **nobody acts on it**.
- `CostEvent` / table `cost_events`: `id`, `company_id`, `agent_id`, `task_id`, `project_id`, `policy_id`, `provider`, `model`, `input_tokens`, `output_tokens`, `cost_cents`, `billing_type`, `status` (reserved|committed|released, indexed), `expires_at`, `occurred_at`, `created_at`.
  - `provider` and `model` ARE present -- so provider-scoped and model-scoped windows are computable from this table without a schema change.

`BudgetService` behaviour, verified line by line:
- `RESERVATION_TTL_SECONDS = 900`.
- `check_budget(scope_type, scope_id, amount, company_id)`: calls `reap_expired_reservations()` (**which commits -- a read path that commits; R7/WP-18 removes this**), then selects active policies for the scope, then uses `used = policy.spent_cents + policy.reserved_cents`.
  - **BUG B1:** the docstring and comment say "Check against the most restrictive active policy" but the loop `return`s on the FIRST policy with `metric == "cost_cents"`. It is first-match, not most-restrictive. OmniRoute's own semantics are most-restrictive-wins. This must be fixed for Tier 2 to mean anything.
  - No policy found -> `allowed=True, message="No budget policy configured"` (unlimited). Correct default, but it means a missing agent policy silently disables Tier 2.
- `reserve(...)` IS correct and IS atomic: conditional `UPDATE ... WHERE (spent_cents + reserved_cents + amt) <= amount ... RETURNING id, reserved_cents, amount`, and `if not row: return False`. Backed by the Postgres CHECK constraint `budget_never_overcommitted` from migration `e2f3a4b5c6d7`. **Keep this. OmniRoute has no equivalent.**
- `commit_reservation` / `release_reservation` / `reap_expired_reservations` all guard `rowcount == 0` and use `case((reserved_cents >= old_hold, reserved_cents - old_hold), else_=0)`. Correct.
- `record_cost(...)` at L143 -- **three defects:**
  - **BUG B2 (scope):** the `UPDATE BudgetPolicy` filters on `company_id`, `is_active`, `metric == "cost_cents"` ONLY. There is no `scope_type` / `scope_id` filter. It therefore increments `spent_cents` on **every** active cost policy in the company, including agent-scoped and project-scoped ones. Agent A's spend charges Agent B's budget. Latent today (see B4), **live the moment Tier 2 creates per-agent policies.**
  - **BUG B3:** no `.returning(...)`, no `BudgetExceeded` raise. When the CHECK constraint trips, the caller gets a raw `IntegrityError` instead of a clean 429.
  - **BUG B4:** `record_cost` has **zero call sites in `src/`**. Only `budget_service.py:143` (the definition) and `runtime/executor.py:116`, which is a *different* private method of the same name.
- `enforce_limit(agent_id, cost_cents)` at L331 -- the natural Tier-2 entry point -- also has **zero call sites**. Dead code.
- `_get_window_usage(scope_type, scope_id, window)` computes daily/weekly/monthly window starts correctly AND filters status correctly (`committed`, or `reserved` with `expires_at` NULL/future). It is reachable only via `get_usage(...)`, which itself has no caller in the enforcement path. **So `spent_cents` is a monotonic lifetime counter and `window_kind="monthly"` currently means nothing.** This is WP-18 in R3 and it is the hard prerequisite for everything in SS7.

**System B -- denormalized `spent_monthly_cents` counters**
- `agents.budget_monthly_cents` / `agents.spent_monthly_cents` (`src/nexus/models/agent.py:71-72`)
- `companies.budget_monthly_cents` / `companies.spent_monthly_cents` (`src/nexus/models/company.py:19-20`)
- **The only write site for the agent counter is `src/nexus/runtime/executor.py:151`**, inside `_record_cost`: `update(Agent).where(Agent.id == result.agent_id).values(spent_monthly_cents=Agent.spent_monthly_cents + result.cost_cents)`. That same method adds a `CostEvent` directly with `provider="adapter"` and `billing_type="task_execution"` -- **bypassing `BudgetService.record_cost`, so `BudgetPolicy.spent_cents` is never incremented on this path.**
- **The only write site for the company counter is `src/nexus/main.py:296`.**
- Read sites for the agent counter: `runtime/executor.py:93` (`_check_budget`), `runtime/orchestrator.py:558` (refuses work), `runtime/watchdog.py:479` (raises an alert), `api/routes/tasks.py:99`, `api/routes/hr.py:23`, `api/routes/agents.py:71`, `api/routes/company_sim.py:311`, `api/routes/evolution.py:306`, `runtime/orchestrator.py:829`, `runtime/executor.py:305`, `temporal/activities.py:155`, `runtime/watchdog_service.py:44`. **Twelve read sites, one write site.**
- Nothing resets either counter at a month boundary. "Monthly" is aspirational.

**System C -- `BudgetEnforcer`, in-memory** (`src/nexus/governance/budget_enforcer.py`, blob `dad07cfcf6d802c2feb096504d6413dbaddb85c8`)
- Pure in-process dicts: `_budgets`, `_warning_thresholds`, `_spent`, `_metrics`, `_metric_budgets`, `_metric_warn`, `_window_kinds`, `_scope_agent`, `_cost_events`.
- `BudgetDecision` = ALLOWED | WARNING | DENIED. `WindowKind` = MONTHLY | WEEKLY | DAILY | PER_EXECUTION | **LIFETIME**.
- `set_budget(scope_type, scope_id, total_cents, warn_percent=80, metric="cost_cents", window_kind=None, agent_id=None)`; `check_can_spend(...)`; `on_cost_event(..., tokens=0, api_calls=0, ...)` which computes the **worst decision across cost_cents/tokens/api_calls** -- exactly the most-restrictive-wins semantics System A is missing; `_handle_hard_stop` -> `BudgetIncident` + `auto_pause_callback` + `cancel_work_callback`.
- Wired into: `workflows/company_flow.py:406` (`check_can_spend`) and `:500` (`on_cost_event`), `workflows/task_flow.py:342-343`, `governance/cost_alerting.py:111` (constructs its own instance).
- `BudgetIncident` / `BudgetIncidentLog` (`governance/budget_incident.py`, 124 lines) support `build_dedupe_key(scope_type, scope_id, threshold_type)` and `clear_dedupe_key(...)` so one crossing yields one incident. **Not persisted -- lost on restart.**

**Net effect today:** a chat-route LLM call updates `BudgetPolicy.spent_cents` but not `agents.spent_monthly_cents`. A task-executor call updates `agents.spent_monthly_cents` but not `BudgetPolicy.spent_cents`. A workflow call updates an in-memory dict that dies with the process. The orchestrator refuses work based on a counter the chat route never increments. **All three views of "what has this agent spent" are wrong, in different directions.**

Also note `chat.py:630` -- `_reserve_budget` hard-codes `scope_type="company"`. `agent_id` is passed but only stamped onto the `CostEvent` row; **no agent-scoped policy is ever consulted at reservation time.** And `chat.py:640` catches `Exception` and logs `"Budget reservation failed, allowing call: %s"` -- fail-open, contra R12.

### 2.4 The budget API surface (`src/nexus/api/routes/budgets.py`, blob `857cae8a9b04b583a12abf9cbecdd9462bbc4d93`, 194 lines)

Four endpoints:
- `POST /api/v1/companies/{company_id}/budget-policies` (`PathCompanyId` + `RequireAdmin`) -- accepts `scope_type`, `scope_id`, `metric`, `window_kind`, `amount`, `warn_percent`, `hard_stop_enabled`. **This already lets you create a per-agent policy today.** No UI exposes it.
- `GET /api/v1/companies/{company_id}/budget-usage`
- `GET /api/v1/agents/{agent_id}/budget-usage`
- `GET /api/v1/companies/{company_id}/budgets/cost-trend?days=7`

**BUG B5:** all three GETs compute the window inline as `now.replace(day=1, hour=0, ...)` -- hard-coded monthly, ignoring `window_kind` -- and they sum **all** `CostEvent` rows with no `status` filter. Released holds and expired reservations are reported as spend. `_get_window_usage` in the service filters status correctly; these endpoints do not. The dashboard therefore over-reports.

### 2.5 Model catalog and capabilities

`src/nexus/api/routes/providers.py` (blob `b1da55aedcada237ac501d6d1febae3cd4374422`)
- `GET /api/v1/agent-providers`, `GET /api/v1/agent-providers/{id}`, `GET /api/v1/agent-providers/{id}/models` -> `PROVIDER_MODELS.get(provider_id, [])`.
- `PROVIDER_MODELS` is a hand-maintained dict, 13 keys, ~49 entries total: `claude`(6), `codex`(7), `grok`(3), `kimi`(2), `antigravity`(3), `qwen`(4), `opencode`(3), `crush`(3), `pi`(3), `copilot`(4), `kiro-cli`(3), `aider`(5). Tiers: flagship | fast | reasoning | balanced | local.
- Frontend consumers: `dashboard/src/api/agents.ts:133` and `:138`.

`src/nexus/models_router/capabilities.py`
- `_FAMILY_LIMITS` covers ~17 families by substring match, most-specific-first.
- **`DEFAULT_LIMITS = ModelLimits(8_192, 4_096)`.** Any model not in that list is assumed to have an 8K context window. This feeds `resolve_history_budget()` in `memory/compaction.py`, so an unknown 200K-context model gets its history compacted at 8K. **Fixing this is one of the highest-value wins in the entire integration** (WP-22c step 5).

`src/nexus/models_router/provider_registry.py`
- `LLMProviderSpec(name, models_available, pricing, capabilities, api_base, is_local=False)`; `ModelCapabilities(context_window, supports_tools, supports_vision, supports_streaming, supports_json_mode)`; `route_to_provider(task_type, requirements)` filtering on `needs_vision`, `needs_tools`, `min_context_window`, `prefer_local`, `needs_streaming`.
- Six hard-coded specs (OPENAI L139, ANTHROPIC L173, OLLAMA L199, DEEPSEEK L234, MISTRAL L260, GOOGLE L286), registered L324-329, each with a hard-coded `api_base`.
- **This class is the correct sink for gateway-discovered models.** Registering discovered models here makes `route_to_provider` and `ModelCapabilityResolver` work on the gateway catalog for free.

`src/nexus/models_router/pricing.py:254` -- `estimate_cost_cents(...) -> int` returns `math.ceil(usd * 100)`. **A `$0.0000000001` gateway charge becomes 1 cent.** With OmniRoute's free-tier cascade returning `X-OmniRoute-Response-Cost: 0.0000000000` on most calls, this systematically over-bills. See R11 and WP-22d.

`src/nexus/models_router/preflight.py` -- `DEFAULT_OUTPUT_RESERVATION_TOKENS = 1024`; `estimate_min_call_cost(model, prompt_tokens)`; `BudgetExceededError(model, estimate_usd, spent_usd, limit_usd)`; `check_budget_preflight(...)`. Its own docstring notes that `nexus.runtime.executor.BudgetExceededError` is a **separate, agent-scoped, cents-denominated** error -- two exception classes with the same name.

`src/nexus/models_router/router.py` -- `_DEFAULT_MODEL_MAP` at L27 maps (task, complexity) -> hard-coded `anthropic/claude-sonnet-4-20250514`, `openai/gpt-4o`, `openai/gpt-4o-mini`, `ollama/llama3`.

### 2.6 Config and embeddings

`src/nexus/config.py` -- 119 lines. `openai_api_key: str = ""` (L68), `anthropic_api_key: str = ""` (L69). `model_config` uses `env_prefix: ""` and anchors `.env` to the repo root. **No `api_base`, no gateway field, no connection field exists.**

`src/nexus/knowledge/embeddings.py` -- L36 `self._dimension = 1536 if "small" in model else 3072` (OpenAI); L86 `768` (Ollama); L136 `provider_type = os.environ.get("EMBEDDING_PROVIDER", "none").lower()`; L164 hash-fallback `dimension: int = 256`.

`alembic/versions/d5b1f7a3c210_*.py` -- `EMBEDDING_DIM = 1536`; `CREATE EXTENSION IF NOT EXISTS vector`; `ALTER COLUMN embedding_vector TYPE vector(1536)`; HNSW index `ix_knowledge_chunks_embedding_hnsw` with `vector_cosine_ops`. **The pgvector column is pinned at 1536 dimensions.** See SS8.

---

## 3. Work packages

> WP-22a..e specify the foundation: the P0 fix, the Connection abstraction, model discovery, cost truth, and budget unification. WP-22f..k (below) build the two budget tiers, the MCP bridge, the audit trail, the embeddings guard, and deployment on top of them. Sequencing in SS5; acceptance rows in SS6.

### WP-22a -- P0: the missing `hashlib` import

**Depends on: nothing. Ship TODAY as its own commit, ahead of everything else.**

`src/nexus/adapters/openai_adapter.py::_do_execute` builds
`"Idempotency-Key": f"{session.session_id}:{hashlib.sha256(prompt.encode()).hexdigest()[:16]}"`
but the module never imports `hashlib` (imports verified at SS2.1: `asyncio`, `uuid`, `datetime/timezone`, `typing.Any`, `BaseAdapter`, `estimate_cost_cents`, `AgentSession`, `TaskResult`; `httpx` is imported inside the function). **Every non-streaming OpenAI-format call raises `NameError`.** `stream_execute` sets no such header, so streaming is unaffected -- which is why the regression went unnoticed and proves no test invokes `_do_execute`.

**Files:** `src/nexus/adapters/openai_adapter.py`, `tests/test_openai_adapter_wp22a.py` (new).

#### Steps

1. Add `import hashlib` to the module import block. One line. Do not move the header construction, do not restructure `_do_execute` -- the header is correct once the name resolves.
2. Add the two acceptance tests. R10: mock the HTTP call via `httpx.MockTransport`; no network. R1: both tests call the public `execute_task` / `stream_execute`, not `_do_execute` directly.

**Acceptance**
- `test_do_execute_sends_idempotency_key_and_returns_result` -- `execute_task` returns `success=True` with parsed tokens, and the outbound request carries an `Idempotency-Key` header shaped `<session_id>:<16 hex>`. FAILS at `68144249` with `NameError: name 'hashlib' is not defined`.
- `test_stream_execute_yields_chunks_and_stops_on_done` -- `stream_execute` yields the SSE content deltas in order and stops at `[DONE]`. The path was untested at baseline.

---

### WP-22b -- Tier 0: the Connection abstraction (the core)

**Depends on: nothing (parallel-safe with WP-22a). Unlocks 22c/f/h/k. 5 commits.**

A **Connection** is a user-created record `{ name, base_url, api_key, wire_format }`, `wire_format in {openai, anthropic}`. NEXUS ships two wire-format adapters and zero vendor adapters (R9). OmniRoute -- and Ollama, vLLM, OpenRouter, anything OpenAI/Anthropic-compatible -- becomes one Connection the user adds, at zero marginal code cost. The injection point is `uastl.py` line ~189 `return registry_key, config` (SS2.1): when an agent has a Connection, its `base_url` is copied into `config["api_base"]` exactly as DeepSeek/Groq already do. `create_adapter(registry_key)` needs no signature change -- config reaches the adapter via `create_session` (SS2.2 step 5).

**Files:** `src/nexus/models/connection.py` (new), `alembic/versions/<new>_llm_connections.py` (new), `src/nexus/api/routes/connections.py` (new), `src/nexus/adapters/uastl.py`, `src/nexus/adapters/anthropic_adapter.py`, `src/nexus/adapters/openai_adapter.py`, `src/nexus/api/routes/chat.py`, `src/nexus/config.py`, `dashboard/src/pages/Connections.tsx` (new). **The string `omniroute` appears in NONE of these (R9).**

#### Steps (one commit each)

1. **Model + migration.** `LLMConnection`: `id`, `company_id`, `name`, `base_url`, `wire_format` (`openai|anthropic`), `api_key_ref` (secret-backend reference, never the raw key), `mgmt_key_ref` (nullable, for Tier 1 -- see WP-22f.6), `is_active`, timestamps. Add `agents.connection_id` FK (nullable). RLS policy scoping rows to `company_id`, matching the existing pattern on other tenant tables.
   - Acceptance: `test_connection_rls_isolates_companies` -- a row created under company A is invisible to a session scoped to company B. FAILS at baseline (table does not exist).
2. **Dispatch wiring.** `resolve_provider(adapter_type, model, connection=None)`: when `connection` is present, force `registry_key` from `connection.wire_format` and set `config["api_base"] = connection.base_url`, `config["api_key"] = <resolved from api_key_ref>`. `chat.py::_resolve_adapter_type` loads the agent's Connection and passes it through. **Relax the `chat.py:725` blocker:** `if registry_key in (...) and not api_key` must not fire when a Connection supplies the key -- that line currently returns an in-character refusal and files a `secret_request` Approval, so with a gateway configured and `OPENAI_API_KEY` empty nothing works (SS2.2 step 3).
   - Acceptance: `test_agent_with_connection_dispatches_to_connection_base_url` -- an agent with a Connection POSTs to the connection's `base_url`, not `api.openai.com`. FAILS at baseline (returns the `chat.py:725` refusal string).
3. **Anthropic per-session `api_base`.** `anthropic_adapter.py:35` hard-codes `self._api_base`; L121 and L315 consume it. Mirror the OpenAI adapter: read `session.metadata.get("api_base", self._api_base)`, and copy `config["api_base"]` in `_do_create_session`. ~3 lines.
   - Acceptance: `test_anthropic_adapter_honours_session_api_base` -- FAILS at baseline (hard-coded).
4. **SSRF allowlist.** Connection create runs `base_url` through `ssrf_protection._guard_url` (the `http_adapter` already does this, SS2.1). Private/Docker-internal hosts (`http://omniroute:20128`, `127.0.0.1`) are rejected unless the host is in `LLM_CONNECTION_HOST_ALLOWLIST` (new `config.py` setting, default `""`). **Verify Appendix-B #6 first** -- if `_guard_url` already permits Docker hostnames this step is a no-op.
   - Acceptance: `test_connection_create_rejects_private_host_by_default` -- FAILS at baseline (endpoint does not exist).
5. **Never leak the key.** The Connection read endpoints serialize `api_key_ref` presence as a boolean (`has_api_key`), never the value or the reference.
   - Acceptance: `test_connection_response_never_leaks_api_key` -- FAILS at baseline (endpoint does not exist).

**Rollback:** `LLM_CONNECTIONS_ENABLED=false` hides the UI and makes `resolve_provider` ignore the `connection` argument; the column stays but is unread; existing agents are unaffected because the path is additive at `uastl.py:189` and the `chat.py:725` relaxation fires only when `connection is not None`.

---

### WP-22c -- Tier 1: model discovery + real context windows

**Depends on: WP-22b. Parallel-safe with R3 WP-15/16.**

Two data sources, fail-open (R12): (a) the gateway's model catalog for the full provider list, (b) the static `PROVIDER_MODELS` dict as fallback when the gateway is unreachable. **Step 5 is the highest-value half-day in the plan** and can ship independently of the catalog table.

**Files:** `src/nexus/models_router/catalog.py` (new), `src/nexus/models_router/capabilities.py`, `src/nexus/models_router/provider_registry.py`, `alembic/versions/<new>_gateway_models_cache.py` (new), `src/nexus/api/routes/providers.py`.

#### Steps

1. New `catalog.py`: `discover_models(connection)` calls the gateway model/pricing/manifest endpoints (Appendix A), returning `(model_id, context_window, pricing, capabilities)` tuples. Cache in a `gateway_models` table, TTL `GATEWAY_CATALOG_REFRESH_SECONDS` (new setting, default `900`).
2. Register discovered models into `provider_registry.LLMProviderSpec` (SS2.5) -- **the correct sink**; this makes `route_to_provider` and `ModelCapabilityResolver` work on the gateway catalog for free.
3. Send the catalog prefix alias (`MODELS_CATALOG_PREFIX_MODE=alias`, SS4 compose) on discovery requests.
4. **Fail open:** on any gateway error, `discover_models` returns the static `PROVIDER_MODELS` shape and the app boots (R12).
5. **Real context windows.** `capabilities.py` returns `DEFAULT_LIMITS = ModelLimits(8_192, 4_096)` for any unlisted model (SS2.5), so `resolve_history_budget()` in `memory/compaction.py` compacts a 200K-context model at 8K. Resolve limits from the discovered catalog (or a widened known-model table) so a discovered/known context window beats the 8K default.

**Acceptance**
- `test_discovered_model_context_window_beats_default_limits` -- a model with a discovered 200K window resolves to 200K, not 8K. FAILS at baseline (`DEFAULT_LIMITS` wins).
- `test_catalog_falls_back_to_static_provider_models` -- gateway error yields the static shape. FAILS at baseline (no catalog module).
- `test_catalog_sends_prefix_alias` -- FAILS at baseline (no catalog module).

**Rollback:** the static `PROVIDER_MODELS` fallback is never deleted; dropping the catalog table degrades to today's behaviour.

---

### WP-22d -- Cost truth: micro-USD accounting

**Depends on: WP-22b + WP-22e.**

`pricing.py:254` `estimate_cost_cents(...) -> int` returns `math.ceil(usd * 100)` (SS2.5), so a `$0.0000000001` gateway charge becomes 1 cent. OmniRoute's free-tier cascade returns `X-OmniRoute-Response-Cost: 0.0000000000` on most calls, so today's code systematically over-bills at free-tier volume. **R11: store integer micro-USD (`10^-6` USD); never float, never `round(usd*100)` on the settle path.**

**Files:** `src/nexus/models_router/pricing.py`, `src/nexus/adapters/openai_adapter.py`, `src/nexus/models/budget.py`, `src/nexus/services/budget_service.py`, `alembic/versions/<new>_cost_micros.py` (new).

#### Steps

1. Add `cost_micros` (BIGINT) to `CostEvent`; keep `cost_cents` written alongside for the 12 legacy read sites (rollback safety). New `estimate_cost_micros(model, in_tokens, out_tokens) -> int` doing the arithmetic in integer micro-USD.
2. Parse the gateway cost headers (`X-OmniRoute-Response-Cost` and siblings -- vendor strings live in the adapter only via the connection's response, not as literals; **the string `omniroute` must not appear in `adapters/`**, so match the header by the configured key, not a hard-coded name) into `cost_micros`. `stream_execute` currently does no cost accounting (SS2.1) -- see step 3.
3. **Streaming reconciler:** streaming responses carry no cost headers (Appendix A note). Reconcile from `GET /api/usage/request-logs` keyed by request id. If Appendix-B #3 confirms `stream_options: {include_usage: true}`, this is largely unnecessary for streaming.

**Acceptance**
- `test_cost_micros_survives_sub_cent_charge` -- a `$0.0000000001` charge stores a non-inflated `cost_micros`, not 1 cent. FAILS at baseline (`math.ceil(usd*100)` -> 1).
- `test_openai_adapter_parses_gateway_cost_headers` -- FAILS at baseline (headers ignored).
- `test_cache_hit_does_not_double_count` -- a cache-hit response does not double-count spend. FAILS at baseline (no header parsing).

---

### WP-22e -- Budget unification (folds in R3 WP-18)

**Depends on: nothing structural, but is the hard prerequisite for WP-22d/f/g. This is R3's WP-18 -- do not implement WP-18 separately.**

SS2.3 is the justification: three parallel spend counters that do not talk to each other (`BudgetPolicy.spent_cents`, `agents.spent_monthly_cents`, the in-memory `BudgetEnforcer`), plus five verified bugs. Building any two-tier budget before this yields precisely wrong numbers. **R13: after this WP there is exactly one authoritative spend counter per scope; denormalized mirrors are allowed only if a single reconciler writes them and a test proves convergence.**

**Files:** `src/nexus/models/budget.py`, `alembic/versions/<new>_budget_windows.py` (new), `src/nexus/services/budget_service.py`, `src/nexus/api/routes/budgets.py`, `src/nexus/api/routes/chat.py`, `src/nexus/runtime/executor.py`, `src/nexus/config.py`.

#### Steps

1. **Windows as columns.** Add `period_start_at` / `next_reset_at` to `BudgetPolicy`; `window_kind` is stored but unused today (SS2.3). A monthly window resets `spent_cents` at the boundary instead of accumulating for life. **State month-boundary behaviour in the PR body (R7).** Also drop the commit-on-read: `check_budget` currently calls `reap_expired_reservations()`, which commits (SS2.3) -- move reaping off the read path.
2. **Fix the five bugs (SS2.3/2.4):**
   - **B1** `check_budget` returns on the first `cost_cents` policy -> make it **most-restrictive-wins** across all matching policies.
   - **B2** `record_cost` `UPDATE` has no `scope_type`/`scope_id` filter -> add it, so Agent A's spend stops charging Agent B.
   - **B3** `record_cost` -> add `.returning(...)` and raise a clean `BudgetExceeded` instead of leaking `IntegrityError` on the CHECK-constraint trip.
   - **B4/dead code** `record_cost` and `enforce_limit` have zero call sites -> wire `record_cost` into the settle path so `BudgetPolicy.spent_cents` is actually incremented.
   - **B5** the three budget-usage GETs sum all `CostEvent` rows with no `status` filter and hard-code monthly -> filter `status` (exclude released/expired holds) and honour `window_kind`.
3. **One counter of record (R13).** The task-executor path (`executor.py:151`) writes a `CostEvent` directly and increments `agents.spent_monthly_cents`, bypassing `BudgetService.record_cost` (SS2.3). Route it through `record_cost`. Keep the denormalized `agents.spent_monthly_cents` mirror (12 read sites -- deleting it is a separate refactor, SS7 anti-goal) but write it only via a single reconciler.
   - `test_reconciler_converges_agent_counter_to_cost_events` -- the reconciler makes the mirror equal the authoritative sum. FAILS at baseline (reconciler does not exist).
4. **R12 inversion.** `chat.py:640` catches `Exception` and logs `"Budget reservation failed, allowing call"` -- fail-open. Invert to **fail-closed**: on budget-infra failure the call is refused, gated by `BUDGET_FAIL_OPEN` (new setting, default `false`).

**Acceptance**
- `test_monthly_window_resets_spent_counter` -- FAILS at baseline (`spent_cents` is a lifetime counter).
- `test_most_restrictive_policy_wins` -- FAILS at baseline (B1 first-match).
- `test_agent_spend_does_not_charge_a_sibling_agents_policy` -- FAILS at baseline (B2 no scope filter).
- `test_record_cost_raises_budget_exceeded_not_integrity_error` -- FAILS at baseline (B3).
- `test_reconciler_converges_agent_counter_to_cost_events` -- FAILS at baseline (no reconciler).
- `test_budget_infra_failure_refuses_call` -- FAILS at baseline (`chat.py:640` logs and allows).
- `test_budget_usage_endpoint_excludes_released_holds` -- FAILS at baseline (B5 no status filter).

**Rollback (riskiest WP):** land behind `BUDGET_WINDOWS_ENABLED` for one release, run the reconciler report-only first, diff the three counters in a log line before enforcing. **Do not enforce on the same day you enable.**

---

### WP-22f -- Tier 1: the company-wide ceiling, owned by the gateway

**Depends on: WP-22b.** Independent of WP-22e/g.

**Principle:** OmniRoute owns the **hard outer wall** -- one ceiling for the whole company, enforced at the wire, unbypassable by any NEXUS bug. NEXUS owns the **inner walls** (WP-22g). Two independent enforcement layers with different failure modes is the whole point; do not collapse them.

| | Tier 1 (OmniRoute) | Tier 2 (NEXUS) |
|---|---|---|
| Owner | The gateway | NEXUS `BudgetPolicy` |
| Unit | One API key = the whole company | Per agent / department / project |
| Role | Hard ceiling, last line of defence | Attribution, pre-flight refusal, per-agent caps |
| Enforcement | Inline on the request path, `429` | Two-phase reserve/commit before the call |
| Bypassable by a NEXUS bug | **No** | Yes |
| Knows about agents | No | Yes |

**Files:** `src/nexus/services/gateway_admin.py` (new), `src/nexus/api/routes/connections.py`, `src/nexus/models/incident.py`, `alembic/versions/<new>_persist_budget_incidents.py` (new), `dashboard/src/pages/Budgets.tsx`

#### Steps

1. **Provision the ceiling.** `POST /api/usage/budget` on the management key with:
   ```json
   { "apiKeyId": "<the key NEXUS uses>",
     "monthlyLimitUsd": 120,
     "warningThreshold": 0.8,
     "resetInterval": "monthly",
     "resetTime": "00:00" }
   ```
   - Schema notes verified from the API reference: `apiKeyId` is **required**; at least one of `dailyLimitUsd` / `weeklyLimitUsd` / `monthlyLimitUsd` must be `> 0`; `warningThreshold` is a fraction in `0..1` (**not** a percent -- NEXUS's `warn_percent` is a percent; convert); `resetInterval` is `daily|weekly|monthly`; `resetTime` is `HH:MM`. The legacy `{keyId, limit, period}` body returns `400 Bad Request`.
   - `GET /api/usage/budget` reads it back.
2. **Set the ceiling ABOVE the NEXUS cap, not equal to it.** Recommended `1.2x`. If they are equal, whichever layer rounds first produces confusing double-refusals and you cannot tell which layer fired. Tier 1 should only ever fire when Tier 2 has failed.
3. **Optional token ceiling.** `POST /api/usage/token-limits` with `{apiKeyId, scopeType: "global"|"provider"|"model", scopeValue, tokenLimit, resetInterval, resetTime, enabled}`. `scopeValue` is required unless `scopeType` is `global`; `tokenLimit` is a positive integer (string-coercible). These are enforced **inline on the request path with `429 Too Many Requests`, most restrictive wins.** `GET` enriches with `tokensUsed`, `remaining`, `windowStart`, `periodStartAt`, `nextResetAt` -- which is exactly the shape WP-22e.1 ports.
4. **Read usage back for the dashboard.** `GET /api/usage/om-usage?format=json`. **Requires `allowUsageCommand: true` on the key** (off by default -- otherwise `403`). Enable it via `PATCH /api/keys/[id]`. The JSON shape is `{allowed, personal:{dailySpentUsd, dailyLimitUsd, dailyResetAtIso, weeklySpentUsd, weeklyLimitUsd, weeklyResetAtIso}, provider:{connectionId, provider, plan, quotas}, providers:[...]}`; a refusal returns `{allowed: false, error: {message}}`. Poll at most every 60s from the scheduler and cache.
5. **Webhook -> persisted incident.** `POST /api/webhooks` with `{url, events: ["*"], secret, description}`. Point it at a new `POST /api/v1/webhooks/gateway` endpoint on NEXUS that verifies the shared secret and writes a **persisted** `BudgetIncident` row.
   - Today `BudgetIncidentLog` is in-memory (SS2.3) and dies on restart. This WP adds the table and reuses `BudgetIncident.build_dedupe_key(...)` as a unique constraint so a repeated webhook delivery is idempotent.
   - Optionally trip the existing kill switch (`governance/persistent_kill_switch.py`) on a quota-exhaustion event. **Make this opt-in via a setting, default off** -- an automatic company-wide halt on a webhook you have not yet load-tested is worse than the overspend.
   - **Verify before wiring:** the exact event-name vocabulary for quota exhaustion is in `docs/frameworks/WEBHOOKS.md`; the API reference lists webhook events generically as request completion / quota exhaustion / key rotation. Do not guess the string. Also use `POST /api/webhooks/[id]/test` and `GET /api/webhooks/[id]/deliveries` during development.
6. **Two credentials, not one.** Store both on the Connection: `api_key_ref` (inference, used for `/v1/*`) and `mgmt_key_ref` (management, used for `/api/*`). **Management routes are not authorized by ordinary inference keys** -- confirmed in the API reference and `docs/guides/MANAGEMENT-AUTH.md`. Every Tier 1 call in this WP uses the management key. If `mgmt_key_ref` is NULL, the connection still works for inference; Tier 1 features simply render as unavailable in the UI.

**Acceptance**
- `test_gateway_admin_sets_monthly_ceiling` -- mock transport asserts the outbound body contains `apiKeyId` and `monthlyLimitUsd`, and that `warningThreshold` was converted from `warn_percent=80` to `0.8`.
- `test_gateway_admin_rejects_legacy_budget_body` -- guards against regressing to `{keyId, limit, period}`.
- `test_gateway_webhook_incident_is_idempotent` -- deliver the same payload twice, assert one row.
- `test_tier1_uses_management_key_not_inference_key` -- assert the `Authorization` header on `/api/usage/budget` came from `mgmt_key_ref`.

---

### WP-22g -- Tier 2: per-agent budgets, OmniRoute-inspired

**Hard dependency: WP-22e.** This WP is small *because* WP-22e did the hard work. If WP-22e is skipped this WP produces confidently wrong numbers.

**Files:** `src/nexus/models/budget.py`, `alembic/versions/<new>_budget_scoped_limits.py` (new), `src/nexus/services/budget_service.py`, `src/nexus/api/routes/budgets.py`, `src/nexus/api/routes/chat.py`, `dashboard/src/pages/Budgets.tsx`, `dashboard/src/components/agents/EditAgentModal.tsx`

#### The four things worth porting from OmniRoute (and nothing else)

1. **Explicit window bookkeeping** -- `periodStartAt` / `nextResetAt` as stored columns rather than computed-on-read. Already specified in WP-22e.1. This is the port.
2. **Soft warning threshold** -- OmniRoute's `warningThreshold` (0..1). NEXUS already has `warn_percent` (0..100) and already computes `warn_threshold_reached` in `check_budget` -- **and then ignores it.** Make it act: emit a notification via the existing `models/notification.py` + `api/routes/notifications.py`, and surface an amber state in `Budgets.tsx`. Paperclip's 80% soft / 100% hard auto-pause pattern is the reference behaviour.
3. **Scoped limits** -- add `scope_kind` (`global` | `provider` | `model`) and `scope_value` to `BudgetPolicy`, mirroring OmniRoute's `scopeType` / `scopeValue`. `CostEvent` already carries `provider` and `model` (SS2.3), so the windowed sums need no new join. Combined with B1's most-restrictive-wins this gives "this agent may spend $20/month, but no more than $5 of it on `gpt-4o`".
4. **Token limits alongside dollar limits.** `BudgetPolicy.metric` already accepts `tokens` and `api_calls`, and `BudgetEnforcer` already evaluates all three. Wire the `tokens` metric through `BudgetService` too. **This is not optional decoration:** OmniRoute's subscription and coding-plan providers report `$0.0000000000`, so a dollar-only budget is unenforceable on exactly the providers a personal deployment will use most. Tokens are the only meaningful unit there.

#### What NOT to port

- **Do not replace the two-phase `reserve()` -> `commit_reservation()` with OmniRoute-style post-hoc counting.** OmniRoute has no pre-flight reservation primitive; NEXUS's is atomic, DB-backed, TTL-reaped and CHECK-constrained. It is strictly better for the per-agent case. Keep it.
- Do not port OmniRoute's Quota-Share fair-share scheduler in this round. Interesting, out of scope.

#### Steps

1. Migration: add `scope_kind`, `scope_value` to `budget_policies`; index `(company_id, scope_type, scope_id, scope_kind, scope_value)`.
2. `chat.py::_reserve_budget` (L586-L630) currently hard-codes `scope_type="company"`. Change it to resolve the **full applicable policy chain** -- company + agent + project + any provider/model-scoped policies -- and reserve against all of them, most-restrictive-wins. Roll back every partial hold if any one fails (the existing `release_reservation` is the primitive).
3. Expose per-agent budget in the UI: a monthly cap field in `EditAgentModal.tsx` writing through `POST /api/v1/companies/{id}/budget-policies` with `scope_type="agent"`. **The endpoint already exists and already accepts this** (SS2.4) -- only the UI is missing.
4. Extend `Budgets.tsx` with a per-agent table: cap, spent, reserved, remaining, warn state, next reset. Plus a Tier 1 panel showing the gateway ceiling from WP-22f step 4, clearly labelled as the company-wide wall.
5. Add `GET /api/v1/agents/{agent_id}/budget-policies` so the UI can read what it wrote.

**Acceptance**
- `test_agent_policy_denies_when_company_policy_would_allow` -- proves the inner wall works independently.
- `test_model_scoped_policy_limits_single_model_only` -- spend on `gpt-4o` denied while spend on `gpt-4o-mini` still allowed under the same agent.
- `test_token_metric_enforced_when_dollar_cost_is_zero` -- all cost events at `cost_micros=0` with real token counts; assert the token policy denies. **This is the subscription-provider case and it must FAIL at `68144249`.**
- `test_warn_threshold_emits_notification_once` -- crossing 80% emits one notification, re-checking does not duplicate (reuse the `clear_dedupe_key` pattern).

---

### WP-22h -- Bonus: the 110-tool MCP bridge

**Depends on: WP-22b. Otherwise independent. High value for effort.**

OmniRoute exposes an MCP server at `/api/mcp/stream` (plus `/api/mcp/status`, `/tools`, `/sse`, `/audit`, `/audit/stats`) with **110 tools across 33 scopes**. NEXUS already ships `src/nexus/adapters/mcp_adapter.py` (285 lines, registered as `mcp` at `registry.py:55`).

**Steps**
1. Add an optional `mcp_url` column to `LLMConnection` (default: derive as `{base_url without /v1}/api/mcp/stream`).
2. On connection probe, call `GET /api/mcp/tools` with the management key and cache the tool list in a `gateway_tools` table (same caching pattern as `gateway_models`).
3. Expose the cached tools in the existing agent tools picker so an agent's `tools` JSON field can reference them.
4. Route invocations through the existing `mcp_adapter.py`. **No new adapter.**
5. Mirror `/api/mcp/audit` into the NEXUS audit log so tool calls made through the gateway appear in the same hash-chained trail as native ones.

**Acceptance:** `test_gateway_mcp_tools_are_discovered_and_cached`, and `test_gateway_mcp_tool_invocation_writes_audit_row`.

**Scope discipline:** 110 tools is a lot of surface. Ship discovery + caching + audit first. Do not attempt per-tool permission modelling in this round; gate the whole gateway tool set behind one permission flag on the connection.

---

### WP-22i -- Bonus: routing decisions in the audit trail

**Depends on: WP-22d.** Two hours of work; disproportionate diagnostic value.

`X-OmniRoute-Decision` (`strategy=<name>; provider=<alias>; latency_ms=<n>`) is present on every completion response. Persist it alongside the existing hash-chained audit record for the call, together with `X-OmniRoute-Fallback-Attempts`, `X-OmniRoute-Cache-Hit` and `X-OmniRoute-Request-Id`.

Result: for any agent output you can answer "which provider actually served this, under which strategy, after how many failovers, at what cost" -- from NEXUS's own tamper-evident log. Combined with Report C's Merkle-root compliance export, that is a genuinely differentiated capability: **verifiable provenance of every model call, including which upstream served it.** No competitor in the benchmark set has this.

**Also worth capturing (cheap):**
- `GET /api/monitoring/health` and `GET /api/resilience/model-cooldowns` -> surface gateway breaker state on the NEXUS ops dashboard next to the existing `circuit_breaker_records`. OmniRoute's thresholds are OAuth 8x / API-key 12x / local 2x with 60s/30s/15s resets; cooldown base 5s OAuth / 3s API-key with `Retry-After` honoured.
- `GET /api/analytics/diversity` -> Shannon-entropy provider-concentration warnings.
- `auto/chaos` -> **the repo's first chaos-testing capability.** The old fail-safe audit found `chaos` had zero hits anywhere in the codebase. A nightly CI job that runs a fixed task set through `auto/chaos` and asserts graceful degradation would close that gap for almost no code. Recommended as a WP-22i stretch goal, or as its own small WP in Round 4.

---

### WP-22j -- Embeddings: an explicit BLOCKER, with the one safe option

**Do not route embeddings through the gateway in this round.** This is a hard technical constraint, not a preference.

**The constraint:** migration `d5b1f7a3c210` pins `knowledge_chunks.embedding_vector` to `vector(1536)` with an HNSW index using `vector_cosine_ops`. `embeddings.py:36` produces 1536 only for OpenAI `text-embedding-3-small`; 3072 for other OpenAI models; `:86` produces 768 for Ollama.

**What OmniRoute actually offers** (live-verified in `docs/reference/EMBEDDINGS.md` against v3.8.49 on 2026-08-17):

| Model id | Dimensions | Fits `vector(1536)`? |
|---|---|---|
| `openrouter/google/gemini-embedding-2` | 3072 | No |
| `openrouter/google/gemini-embedding-2-preview` | 3072 | No |
| `openrouter/google/gemini-embedding-001` | 3072 | No |
| `jina-ai/jina-embeddings-v5-omni-small` | 1024 | No |
| `jina-ai/jina-embeddings-v5-omni-nano` | 768 | No |

**Zero working gateway embedding models produce 1536 dimensions.** Additionally these are known-broken: native `gemini-embedding-2` -> `400 No credentials for embedding provider: gemini`; `google/gemini-embedding-2` -> `400 Unknown embedding provider: google`; `POST /v1/multimodal-embeddings` -> `404 unknown_route`. The docs also warn explicitly: **"Do not mix nano (768-d) and small (1024-d) in one index."**

**Therefore:**
- Keep embeddings on OpenAI `text-embedding-3-small` direct, or on a Connection whose `base_url` happens to serve that exact model at 1536.
- If you later want gateway embeddings, it is a **separate work package** requiring: a new dimension-parameterized column (or a second table), a full re-embed of the corpus, a new HNSW index, and a migration path. Budget it as its own round.
- **Action for this round:** add a startup assertion that the configured embedding provider's dimension equals the column's declared dimension, and fail fast with a clear message. Today a mismatch surfaces as an opaque pgvector insert error. `test_embedding_dimension_mismatch_fails_fast` must FAIL at `68144249`.

---

### WP-22k -- Deployment wiring and CI

**Files:** `docker-compose.yml`, `docker-compose.dev.yml`, `.env.example`, `.env.production.example`, `.github/workflows/test.yml`, `INSTALLATION.md`

#### Compose

1. Add an OmniRoute service **behind a compose profile** (`--profile gateway`) so the default `docker compose up` is unchanged:
   ```yaml
   omniroute:
     profiles: ["gateway"]
     image: diegosouzapw/omniroute:3.8.51
     restart: unless-stopped
     stop_grace_period: 40s
     environment:
       - DATA_DIR=/app/data
       - PORT=20128
       - DASHBOARD_PORT=20128
       - API_PORT=20129
       - API_HOST=0.0.0.0
       - REQUIRE_API_KEY=true
       - MODELS_CATALOG_PREFIX_MODE=alias
       - OMNIROUTE_MEMORY_MB=2048
       - NODE_OPTIONS=--max-old-space-size=2048
     volumes:
       - ./data/omniroute:/app/data
     healthcheck:
       test: ["CMD", "node", "healthcheck.mjs"]
       interval: 30s
       timeout: 5s
       retries: 3
       start_period: 15s
   ```
2. Add `depends_on: { omniroute: { condition: service_healthy } }` to the `backend` service **only in the gateway profile override file**, never in the base compose -- otherwise the default stack refuses to boot without the gateway.
3. Pin the image tag. Do not use `:latest`. OmniRoute ships very frequently (its `CHANGELOG.md` is 2.6 MB).
4. Both services must share a network so `http://omniroute:20128/v1` resolves.

#### Hard warnings, verified from OmniRoute's own `docker-compose.yml`

- **Never enable OmniRoute's `cli` profile.** It mounts `/var/run/docker.sock`, `/usr/libexec/docker/cli-plugins:ro` and `${AUTO_UPDATE_HOST_REPO_DIR:-.}:/workspace/omniroute:rw`. Docker-socket access is host root. For a personal deployment reachable from anywhere, that is an unacceptable blast radius.
- **Never enable the `host` profile** unless you intend it: it bind-mounts `~/.codex`, `~/.claude`, `~/.factory`, `~/.openclaw`, `~/.cursor`, `~/.config/cursor` -- i.e. your local CLI credentials.
- **OmniRoute's bundled Redis has no `requirepass`** (stated in a comment in their own compose file) and binds `${REDIS_BIND_HOST:-127.0.0.1}`. Do not expose that port beyond localhost, and do not point NEXUS's own Redis at it.
- Set `REQUIRE_API_KEY=true`. The default zero-config mode works keyless via pre-wired OpenCode Free routes; an unauthenticated LLM gateway on your network is an open relay.
- Coding agents on `/v1/responses` need `OMNIROUTE_MEMORY_MB` in the `10240`-`12288` range per OmniRoute's own sizing note. The `2048` above is right for chat-only use; raise it if you enable Codex-style flows.
- Memory/vector profile (`qdrant/qdrant:v1.12.4`), `bifrost`, `cliproxyapi` and `codex-app-server` profiles are all out of scope.

#### CI

1. Extend R3's `compose-boot` job (WP-16b) to also boot with `--profile gateway` and assert the backend reaches `/health` **and** that a Connection probe succeeds. Grep the logs for `POSTURE FAILURE|permission denied|new row violates row-level security|NameError`.
2. Add a `gateway-contract` job that runs the `tests/integration/` suite marked `requires_gateway` against the real container. Keep it off the default `pytest` path (R10).
3. Add an `arch_guard.py` rule **R8-gateway**: fail the build if the string `omniroute` (case-insensitive) appears in `src/nexus/adapters/`, `src/nexus/models_router/`, `src/nexus/models/`, or `alembic/versions/`. **This is R9 enforced mechanically.** Add it to the `CHECKS` tuple alongside `check_r1..check_r7`.

#### Env vars added by this plan

| Variable | Default | Purpose |
|---|---|---|
| `LLM_CONNECTION_HOST_ALLOWLIST` | `""` | SSRF allowlist for private gateway hosts (WP-22b.4) |
| `BUDGET_FAIL_OPEN` | `false` | R12 inversion switch (WP-22e.4) |
| `GATEWAY_CATALOG_REFRESH_SECONDS` | `900` | Discovery cache TTL (WP-22c) |
| `GATEWAY_KILL_SWITCH_ON_QUOTA` | `false` | Opt-in halt on Tier 1 quota webhook (WP-22f.5) |

All four go in `src/nexus/config.py` as `Settings` fields. Note `model_config` uses `env_prefix: ""`, so the env var name is the field name uppercased.

**No secrets in `docker-compose.yml`.** Keys go in `.env` and into the secret backend; `.env.example` gets placeholder values only.

---

## 5. Sequencing and dependency graph

```
WP-22a  (hashlib)            -- ship TODAY, standalone, blocks nothing
   |
WP-22b  (Connection)         -- the core; 5 commits
   |
   +--> WP-22c  (discovery)   -- parallel-safe with R3's WP-15/16
   |
   +--> WP-22f  (Tier 1)      -- needs 22b only
   |
   +--> WP-22h  (MCP bridge)  -- needs 22b only
   |
   +--> WP-22k  (compose/CI)  -- needs 22b only

R3 WP-18  ==MERGED INTO==>  WP-22e  (budget unification)
   |
   +--> WP-22d  (cost truth)  -- needs 22b + 22e
   |       |
   |       +--> WP-22i  (routing audit)
   |
   +--> WP-22g  (Tier 2)      -- needs 22e

WP-22j  (embeddings guard)   -- independent, 1 hour, do it early
```

**Recommended order for a personal deployment, by value per hour:**

1. **WP-22a** -- 10 minutes. Fixes live broken inference.
2. **WP-22j** -- 1 hour. Fail-fast guard, prevents a class of opaque errors.
3. **WP-22b** -- 2-3 days. Unlocks everything, and is the feature the user actually asked for.
4. **WP-22c step 5 only** -- half a day. Real context windows stop `memory/compaction.py` truncating 200K models at 8K. Biggest single quality win in the whole plan.
5. **WP-22k** -- half a day. Makes it reproducible and adds the R9 guard before drift sets in.
6. **WP-22e** -- 2 days. Necessary evil; nothing budget-shaped is trustworthy until it lands.
7. **WP-22d** -> **WP-22g** -> **WP-22f** -- the budget story, in that order.
8. **WP-22h**, **WP-22i** -- bonuses, any time after 22b/22d.

**If you only do three things:** WP-22a, WP-22b, WP-22c step 5.

---

## 6. Acceptance test matrix

Every row must be demonstrated FAILING at `68144249` and PASSING after (R2). Paste both outputs.

| WP | Test | Fails at baseline because |
|---|---|---|
| 22a | `test_do_execute_sends_idempotency_key_and_returns_result` | `NameError: name 'hashlib' is not defined` |
| 22a | `test_stream_execute_yields_chunks_and_stops_on_done` | test does not exist; path untested |
| 22b.1 | `test_connection_rls_isolates_companies` | table does not exist |
| 22b.2 | `test_agent_with_connection_dispatches_to_connection_base_url` | returns the "provider API key is not set" string (`chat.py:725`) |
| 22b.3 | `test_anthropic_adapter_honours_session_api_base` | `anthropic_adapter.py:35` is hard-coded |
| 22b.4 | `test_connection_create_rejects_private_host_by_default` | endpoint does not exist |
| 22b.5 | `test_connection_response_never_leaks_api_key` | endpoint does not exist |
| 22c | `test_discovered_model_context_window_beats_default_limits` | `DEFAULT_LIMITS = ModelLimits(8_192, 4_096)` wins |
| 22c | `test_catalog_falls_back_to_static_provider_models` | no catalog module |
| 22c | `test_catalog_sends_prefix_alias` | no catalog module |
| 22d | `test_cost_micros_survives_sub_cent_charge` | `math.ceil(usd*100)` -> 1 cent (`pricing.py:254`) |
| 22d | `test_openai_adapter_parses_gateway_cost_headers` | headers ignored |
| 22d | `test_cache_hit_does_not_double_count` | no header parsing |
| 22e | `test_monthly_window_resets_spent_counter` | `spent_cents` is a lifetime counter |
| 22e | `test_most_restrictive_policy_wins` | `check_budget` returns on first match (B1) |
| 22e | `test_agent_spend_does_not_charge_a_sibling_agents_policy` | `record_cost` has no scope filter (B2) |
| 22e | `test_record_cost_raises_budget_exceeded_not_integrity_error` | no `.returning()` guard (B3) |
| 22e | `test_reconciler_converges_agent_counter_to_cost_events` | reconciler does not exist |
| 22e | `test_budget_infra_failure_refuses_call` | `chat.py:640` logs and allows |
| 22e | `test_budget_usage_endpoint_excludes_released_holds` | no status filter (B5) |
| 22f | `test_gateway_admin_sets_monthly_ceiling` | module does not exist |
| 22f | `test_tier1_uses_management_key_not_inference_key` | module does not exist |
| 22f | `test_gateway_webhook_incident_is_idempotent` | incidents are in-memory |
| 22g | `test_agent_policy_denies_when_company_policy_would_allow` | `_reserve_budget` hard-codes company scope |
| 22g | `test_model_scoped_policy_limits_single_model_only` | no `scope_kind` column |
| 22g | `test_token_metric_enforced_when_dollar_cost_is_zero` | `tokens` metric unwired in `BudgetService` |
| 22g | `test_warn_threshold_emits_notification_once` | `warn_threshold_reached` computed and discarded |
| 22h | `test_gateway_mcp_tools_are_discovered_and_cached` | no discovery |
| 22i | `test_routing_decision_persisted_to_audit` | header ignored |
| 22j | `test_embedding_dimension_mismatch_fails_fast` | fails late with an opaque pgvector error |

---

## 7. Anti-goals for this round

Explicitly out of scope. Do not let scope creep in; each of these is defensible on its own but none belongs here.

- **Rewriting `_DEFAULT_MODEL_MAP` to `auto/*` channels.** Attractive, untested, deferred (SS3.4).
- **Gateway embeddings.** Blocked by the 1536-dim column (WP-22j).
- **OmniRoute's Quota-Share fair-share scheduler.**
- **Per-tool permission modelling for the 110 MCP tools.** One connection-level flag this round.
- **OmniRoute's compression engines, guardrails, memory/Qdrant, A2A, ACP, skills, plugin SDK.** All interesting; all separate rounds.
- **Bifrost / CLIProxyAPI sidecar profiles.**
- **Deleting `agents.spent_monthly_cents` / `companies.spent_monthly_cents`.** Twelve read sites; separate refactor (WP-22e.3 step 3).
- **Everything already deferred in R3 SS4:** gVisor/runsc sandbox hardening, `agents/` SOP depth, GAIA eval harness, Postgres `tsvector` BM25 channel, policy-as-code, the 3D office.
- **No force-pushes to `main`.** Every WP is a normal commit or PR.

---

## 8. Expected scoring impact

| Dimension | At `68144249` | After R3 | After R3 + WP-22 |
|---|---|---|---|
| LLM provider coverage | 8.0 | 8.0 | **9.5** |
| Budget and cost control | 7.5 | 9.0 | **9.5** |
| Observability | 8.0 | 8.0 | **8.5** |
| Repo hygiene | 7.5 | 8.5 | 8.5 |
| Reproducible tests / CI | 8.0 | 9.0 | **9.2** |
| Tenant isolation | 5.5 | 8.5 | 8.5 |
| Concurrency isolation | 5.0 | 8.0 | 8.0 |
| RAG | 8.5 | 9.0 | 9.0 |
| **Weighted overall** | **7.4** | **~8.6** | **~8.9** |

WP-22 does not move the R3 dimensions -- it is additive. The uplift comes from provider coverage (1 gateway = 352 providers / 2,554 provider-model pairs, discovered rather than hand-listed), from cost control becoming *actually correct* rather than merely present, and from two independent budget enforcement layers with different failure modes.

**Net-new differentiators unlocked** (none of MetaGPT, ChatDev, CAMEL/OWL, OpenCompany or Paperclip has these):
- Verifiable provenance of every model call including which upstream served it, inside a hash-chained audit log (WP-22i + Report C's Merkle export).
- Two-layer budget enforcement where the outer wall cannot be bypassed by an application bug (WP-22f + WP-22g).
- Token-denominated budgets that still work on subscription providers that report `$0.00` (WP-22g step 4).
- User-addable arbitrary inference endpoints with no code change (WP-22b) -- Paperclip and OpenCompany both hard-code their provider lists.

---

## 9. Rollback plan

Every WP must be revertable independently.

- **WP-22a** -- trivially revertable.
- **WP-22b** -- `LLM_CONNECTIONS_ENABLED=false` hides the UI and makes `resolve_provider` ignore the `connection` argument. The `agents.connection_id` column stays but is unread. Existing agents are unaffected because the code path is additive at `uastl.py:189` and the `chat.py:725` relaxation only fires when `connection is not None`.
- **WP-22c** -- the static `PROVIDER_MODELS` fallback is never deleted, so dropping the catalog table degrades to today's behaviour.
- **WP-22d** -- `cost_cents` continues to be written alongside `cost_micros`, so the 12 legacy read sites keep working.
- **WP-22e** -- the riskiest WP. It changes counter semantics. Land it behind `BUDGET_WINDOWS_ENABLED` for one release, run the reconciler in report-only mode first, and diff the three counters in a log line before enforcing. **Do not enforce on the same day you enable.**
- **WP-22f** -- delete the gateway budget via the management API; NEXUS keeps working.
- **WP-22g** -- deactivate the agent-scoped policies (`is_active=False`); enforcement reverts to company scope.
- **WP-22h/i** -- pure additions.
- **WP-22k** -- the gateway compose profile is opt-in; the default stack never depends on it.

---

## Appendix A -- OmniRoute API surface used by this plan

All verified from `docs/reference/API_REFERENCE.md` at OmniRoute HEAD `ba597b631d22d85e56db6982f24b7d1ebe238df9` (v3.8.51, 105,809 bytes).

### Inference (inference key, `Authorization: Bearer`)
- `POST /v1/chat/completions` -- OpenAI format
- `POST /v1/messages` -- Anthropic format
- `POST /v1/responses` -- OpenAI Responses format; `supports_websockets` available
- `GET /v1/models` -- catalog; `?prefix=alias|dual|canonical`, server default `dual`
- `POST /v1/messages/count_tokens`
- `GET /v1/embeddings` (lists) / `POST /v1/embeddings` -- see WP-22j
- Also available, unused here: `/v1/images/{generations,edits}`, `/v1/audio/{speech,transcriptions}`, `/v1/rerank`, `/v1/classify`, `/v1/segment`, `/v1/search`, `/v1/web/fetch`, `/v1/moderations`, `/v1/ocr`, `/v1/videos/generations`, `/v1/music/generations`, `/v1/files`, `/v1/batches`, `/v1/quotas/check`, `/v1/api/chat` + `/api/tags` (Ollama-compatible), `/v1beta/models` (Gemini-compatible)

### Management (management key -- NOT the inference key)
- `GET /api/v1/provider-plugin-manifest` -- rich catalog; `Cache-Control: public, max-age=60`, strong `ETag`, honours `If-None-Match` -> `304`
- `GET|POST /api/usage/budget` -- company ceiling (WP-22f.1)
- `GET|POST|DELETE /api/usage/token-limits` -- scoped token ceilings (WP-22f.3)
- `GET /api/usage/om-usage?format=json` -- self-service usage; needs `allowUsageCommand` (WP-22f.4)
- `GET /api/usage/{history,logs,request-logs,model-latency-stats,cache-health}` -- `request-logs` is the streaming reconciliation source (WP-22d.3)
- `GET|POST /api/webhooks`, `POST /api/webhooks/[id]/test`, `GET /api/webhooks/[id]/deliveries`
- `POST /api/keys`, `PATCH /api/keys/[id]` -- key settings incl. `allowUsageCommand`, `cacheDefaultMode`
- `GET /api/monitoring/health`, `PATCH /api/resilience`, `POST /api/resilience/reset`, `GET|DELETE /api/resilience/model-cooldowns`, `GET /api/rate-limits`
- `GET /api/models/catalog`, `GET /api/pricing`, `GET /api/models/alias`
- `GET /api/analytics/{auto-routing,compression,diversity}`, `GET /api/telemetry/summary`
- `GET /api/mcp/{status,tools,audit,audit/stats}`, `POST /api/mcp/stream`, `GET /api/mcp/sse`

### Request headers NEXUS should send
| Header | Value | Why |
|---|---|---|
| `Authorization` | `Bearer <inference key>` | required when `REQUIRE_API_KEY=true` |
| `X-OmniRoute-Session-Id` | `{company_id}:{agent_id}:{task_id}` | persisted verbatim to `call_logs.session_tag`; **never synthesized if absent** |
| `Idempotency-Key` | `{session_id}:{sha256(prompt)[:16]}` | gateway dedupes within 5s; already built in `openai_adapter.py` |
| `X-Request-Id` | correlation id | ties gateway logs to NEXUS audit rows |

Optional / not used this round: `X-OmniRoute-No-Cache`, `x-omniroute-no-memory`, `X-OmniRoute-Progress`, `x-omniroute-compression`, `x-omniroute-disabled-guardrails`, `X-OmniRoute-Lease-Owner`, `X-OmniRoute-Provider-Manifest-Url`.

### Response headers NEXUS should parse
See the table in WP-22d. **Reminder: streaming responses carry none of them.**

### Auth families (why two credentials are unavoidable)
OmniRoute recognises: a dashboard `auth_token` cookie, a local CLI token, an `oma_live_...` Access Token, and manage-scoped API keys. **Management routes (`/api/*`, except public auth/login) are not authorized by ordinary inference keys.** `/v1/*` requires a Bearer token only when `REQUIRE_API_KEY=true`. Reference: `docs/guides/MANAGEMENT-AUTH.md`.

---

## Appendix B -- Items to verify at implementation time

Do not guess these. Each is a small read against OmniRoute's own docs, and each has a specific consequence if guessed wrong.

| # | Question | Where to look | Consequence if wrong |
|---|---|---|---|
| 1 | Does `/api/v1/provider-plugin-manifest` require the management key? | `docs/guides/MANAGEMENT-AUTH.md`; the API reference lists it without an explicit auth line | WP-22c step (a) 401s and silently degrades to (b), losing context windows |
| 2 | Exact webhook event name for quota exhaustion | `docs/frameworks/WEBHOOKS.md` | WP-22f.5 subscribes to a string that never fires |
| 3 | Does OmniRoute honour `stream_options: {include_usage: true}`? | `docs/reference/API_REFERENCE.md` streaming section | If yes, WP-22d.3's reconciler becomes largely unnecessary for streaming |
| 4 | Exact `GET /api/pricing` response shape | live call + API reference | Needed before feeding `models_router/pricing.py` |
| 5 | Minimal env var set for a chat-only deployment | `docs/reference/ENVIRONMENT.md` (**357,228 bytes -- grep, do not read**) | Over- or under-configured container |
| 6 | Does `ssrf_protection._guard_url` reject Docker-internal hostnames today? | `src/nexus/governance/ssrf_protection.py` | Determines whether WP-22b.4 is required or a no-op |
| 7 | Free-tier routing policy gates | `docs/reference/FREE_TIERS.md` (56,345 B), `PROVIDER_REFERENCE.md` (68,210 B) | Only if you want to policy-gate free routing |
| 8 | The 13 providers OmniRoute itself flags "avoid" on terms-of-service risk | README provider table | You may want to blocklist them in the Connection config |

---

## Appendix C -- Prompt for the implementing agent

Paste this verbatim ahead of the work packages when handing off.

> You are implementing the WP-22 series in `naviyanka/NVLabsCompany`, baseline commit `68144249f0dc732696c0a6dd7bc9ee408fa037e1` on `main`.
>
> Rules R1-R13 in SS1 are binding. In particular:
> - **R1**: a test that names a function must invoke it. Importing is not invoking.
> - **R2**: for every acceptance test, paste the FAILING output at `68144249` and the PASSING output after. A PR without both is not reviewable.
> - **R5**: verify code, not commit messages. Three previous rounds of commit messages in this repo materially overclaimed what landed.
> - **R9**: the string `omniroute` must not appear in `adapters/`, `models_router/`, `models/` or `alembic/versions/`. WP-22k adds an `arch_guard.py` check that enforces this mechanically -- do not disable it.
> - **R13**: after WP-22e there is exactly one authoritative spend counter per scope.
>
> Every file path and line number in SS2 was verified at the baseline commit. **Do not assume they are stale and do not re-derive them.** If a line number does not match what you see, stop and report the discrepancy rather than guessing -- it means the tree moved and this plan needs re-verification.
>
> Ship WP-22a as its own commit before anything else. It is a live `NameError` on the primary execution path of the primary adapter.
>
> Do not merge work packages. Do not skip WP-22e before WP-22g. Do not implement R3's WP-18 separately -- it is folded into WP-22e.
>
> If a work package turns out to be larger than described, split it and say so. Do not silently descope an acceptance test.
