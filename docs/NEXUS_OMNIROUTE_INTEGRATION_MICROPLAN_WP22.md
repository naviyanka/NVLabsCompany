# NEXUS x OmniRoute -- Micro-Phase Integration Plan (WP-22 series, live-verified)

> **Working plan.** Break the big WP-22 packages into small, shippable, independently-testable phases.
> **Reference doc:** `NEXUS_OMNIROUTE_INTEGRATION_PLAN_WP22.md` (the full narrative + acceptance matrix). This file is the execution order; that file is the rationale. Where they disagree, THIS file wins because it was checked against the running gateway.
> **Baseline commit:** `68144249f0dc732696c0a6dd7bc9ee408fa037e1`.
> **Gateway verified live at:** `http://localhost:20128`, OmniRoute **3.8.50**, on 2026-09-09.
> **Rules R1-R13** from the reference doc still apply (R9 no-vendor-names-in-core, R10 no-network-in-unit-tests, R11 micro-USD, R12 fail-closed-on-budget, R13 one-counter-of-record).

---

## 0. What changed after probing the real gateway

These are corrections to the reference doc's assumptions. Each one narrows or de-risks a work package.

| Reference doc said | Live gateway (3.8.50) | Effect on plan |
|---|---|---|
| 352 providers / 2,554 pairs / 1,283 model IDs | `/v1/models` returns **3178 models**, **3174 with context_length > 8192** | WP-C (discovery) unchanged in shape; the 8K-default fix matters even more |
| 110 MCP tools across 33 scopes | `/api/mcp/tools` returns **45 tools**, phases 1-2, per-tool `scopes` | WP-H shrinks; still discovery+cache+audit only |
| Costs are 10-decimal USD strings | `/api/usage/budget` reports `dailyTotal: 0.002299` (6-decimal) | R11 still holds: `math.ceil(0.002299*100)=1` cent over-bills. Store micro-USD. |
| `periodStartAt`/`nextResetAt` must be ported | `/api/usage/budget` **returns them live** + `warningThreshold`, `daily/weekly/monthlyLimitUsd`, `budgetCheck{allowed,remaining,warningReached}` | WP-E/G window design is now copy-the-shape, not guess |
| Two key types (inference vs management) | **Confirmed.** Inference key: `/v1/*` = 200, `/api/*` = 403. Management key: `/api/*` = 200. | Connection stores BOTH: `api_key_ref` (inference) + `mgmt_key_ref` (management). Already modelled in WP-B. |
| `om-usage?format=json` gives JSON | Returns an **ANSI text dashboard**, ignores `format=json` | Do NOT parse om-usage. Use `/api/usage/budget?apiKeyId=` (real JSON) instead. |

**Verified auth model (the load-bearing fact):**
- Inference key `sk-...-b64694-...` -> `/v1/chat/completions` streams real completions (routed `auto/best-coding` -> `claude-haiku-4.5`, usage block present). `/api/*` -> 403.
- Management key `sk-...-4ae6c4-...` -> `/api/pricing`, `/api/keys`, `/api/mcp/tools`, `/api/usage/budget?apiKeyId=` all 200.
- `/v1/models` and `/api/monitoring/health` need no auth at all.

**Verified live shapes (captured to repo root, gitignored):** `om_models2.json` (3178), `om_tools2.json` (45), `om_pricing2.json` (33 provider prefixes -> `{model:{input,output,cached,reasoning,cache_creation}}`).

---

## 1. Micro-phase order (dependency-sorted)

```
M0  hashlib P0 fix ............... DONE (shipped, 2 tests pass)
M1  Connection model+migration+RLS  [WP-22b commit 1]
M2  dispatch wiring (uastl+chat) .. [WP-22b commit 2]   depends M1
M3  anthropic api_base ............ [WP-22b commit 3]   independent
M4  SSRF allowlist + key-leak API . [WP-22b commit 4+5] depends M1
     -- WP-22b COMPLETE after M4 --
M5  real context windows (8K fix) . [WP-22c step 5]     depends M2   <- highest value
M6  model discovery + cache ....... [WP-22c step 1-4]   depends M2,M5
M7  budget unification ............ [WP-22e]            independent, but gates M8/M9/M10
M8  micro-USD cost truth .......... [WP-22d]            depends M7
M9  Tier 1 company ceiling ........ [WP-22f]            depends M2,M7
M10 Tier 2 per-agent budgets ...... [WP-22g]            depends M7
M11 MCP bridge (45 tools) ......... [WP-22h]            depends M2
M12 routing audit trail ........... [WP-22i]            depends M8
M13 embeddings dimension guard .... [WP-22j]            independent
M14 compose/CI/.env ............... [WP-22k]            depends M2
```

**If you only ship three: M0 (done), M1-M4 (Connection), M5 (context windows).** That gives the user the feature they asked for -- add any gateway as a Connection -- plus the biggest quality win, real context windows.

---

## 2. Status

- **M0 -- DONE.** `import hashlib` in `openai_adapter.py`; `tests/test_openai_adapter_wp22a.py` (2 tests, pass; baseline shows `NameError`).
- **M1-M4 -- CODE WRITTEN, tests green (17 passed incl. existing resolution suite).** Files: `models/connection.py`, `alembic/versions/a1b2c3d4e5f6_add_llm_connections.py`, `models/__init__.py`, `models/agent.py` (`connection_id`), `adapters/uastl.py` (`connection` param), `api/routes/chat.py` (`_resolve_connection` + relaxed blocker), `adapters/anthropic_adapter.py` (per-session `api_base`), `config.py` (4 settings), `api/routes/connections.py` (new routes), `main.py` (router), tests `test_connections_wp22b.py` + `test_alembic_migration.py` (added `llm_connections`) + `test_postgres_integration.py` (RLS test).
- **Open item:** the full suite showed ~19 failures. Confirmed-mine (2 alembic table-count) fixed. The rest (`completion_reasons`, `bulkhead`, `pgvector`, `config_validator`) must be diffed against baseline to prove pre-existing before M5 starts.

---

## 3. Per-phase acceptance (live-anchored)

### M1 -- Connection model + migration + RLS
- `test_connection_rls_isolates_companies` (Postgres, in `test_postgres_integration.py`) -- FAILS at baseline (no table).
- `llm_connections` in `EXPECTED_TABLES` -- alembic metadata + create_all tests pass.

### M2 -- dispatch wiring
- `test_agent_with_connection_dispatches_to_connection_base_url` -- resolves wire_format->registry_key, base_url->api_base. FAILS at baseline (chat.py:725 refusal).
- Existing resolution suite still green (kept `_resolve_adapter_type` sync; async load in `_resolve_connection`).

### M3 -- anthropic api_base
- `test_anthropic_adapter_honours_session_api_base` -- POSTs to session api_base. FAILS at baseline (L35 hard-coded).

### M4 -- SSRF + key-leak
- `test_connection_create_rejects_private_host_by_default` -- private IP rejected unless allowlisted.
- `test_connection_response_never_leaks_api_key` -- response carries `has_api_key` bool only.
- **Verified live:** `guard_url` permits bare hostnames (`omniroute`) and localhost; a Docker-host Connection needs no allowlist, a private-IP one does.

### M5 -- real context windows (do this next, highest value)
- `test_discovered_model_context_window_beats_default_limits` -- a 200K model resolves to 200K, not `DEFAULT_LIMITS=8192`. FAILS at baseline.
- Live source of truth: `/v1/models[].context_length` / `max_input_tokens` / `max_output_tokens`.

### M6 -- discovery + cache
- `test_catalog_falls_back_to_static_provider_models` (R12 fail-open), `test_catalog_sends_prefix_alias`.
- Source: `/v1/models` (no auth, 3178 rows). Cache TTL `gateway_catalog_refresh_seconds` (config, default 900).

### M7 -- budget unification (gates the money story)
- `test_monthly_window_resets_spent_counter`, `test_most_restrictive_policy_wins` (B1), `test_agent_spend_does_not_charge_a_sibling_agents_policy` (B2), `test_record_cost_raises_budget_exceeded_not_integrity_error` (B3), `test_reconciler_converges_agent_counter_to_cost_events` (R13), `test_budget_infra_failure_refuses_call` (R12), `test_budget_usage_endpoint_excludes_released_holds` (B5).

### M8 -- micro-USD
- `test_cost_micros_survives_sub_cent_charge` -- `0.002299` USD stores 2299 micro-USD, not `math.ceil*100`=1 cent.
- `test_openai_adapter_parses_gateway_cost_headers`, `test_cache_hit_does_not_double_count`.

### M9 -- Tier 1
- `POST /api/usage/budget` on the management key sets `monthlyLimitUsd`+`warningThreshold`. Live shape confirmed. `test_tier1_uses_management_key_not_inference_key`.

### M10 -- Tier 2
- `test_agent_policy_denies_when_company_policy_would_allow`, `test_model_scoped_policy_limits_single_model_only`, `test_token_metric_enforced_when_dollar_cost_is_zero`, `test_warn_threshold_emits_notification_once`.

### M11 -- MCP bridge
- 45 tools (not 110). `test_gateway_mcp_tools_are_discovered_and_cached`, `test_gateway_mcp_tool_invocation_writes_audit_row`. Reuse `mcp_adapter.py`. One permission flag for the whole set.

### M13 -- embeddings guard
- `test_embedding_dimension_mismatch_fails_fast`. pgvector pinned 1536; gateway embeddings out of scope (separate round).

---

## 4. Config (verified against live gateway)

| Setting | Default | Purpose |
|---|---|---|
| `llm_connection_host_allowlist` | `""` | SSRF exemptions for private gateway hosts (M4) |
| `budget_fail_open` | `false` | R12 inversion switch (M7) |
| `gateway_catalog_refresh_seconds` | `900` | Discovery cache TTL (M6) |
| `gateway_kill_switch_on_quota` | `false` | Halt on Tier 1 quota-exhaustion webhook (M9) |

**Connection to reach this gateway from NEXUS:**
- `base_url`: `http://localhost:20128/v1` (wire_format `openai`)
- `api_key_ref`: secret holding the inference key (`sk-...-b64694-...`)
- `mgmt_key_ref`: secret holding the management key (`sk-...-4ae6c4-...`), only needed for M9 Tier 1
