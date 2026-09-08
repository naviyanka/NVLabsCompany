# Micro-Phase 3: Operational Guardrails & Fault Tolerance (F5)

## 1. Problem Statement
Production systems risk connection pool starvation from unconstrained long queries, single-tenant traffic spikes starving shared worker pools, and replay of hijacked run-tokens.

## 2. Technical Invariants
1. A runaway database query must terminate automatically after 30 seconds.
2. An idle transaction must be aborted after 60 seconds.
3. No single tenant can consume more than their allocated worker concurrency semaphore.
4. Run-tokens must contain a unique `jti` nonce redeemed exactly once.

## 3. Implementation Blueprint
1. Database engine server settings:
   - `statement_timeout: 30000` (30s)
   - `idle_in_transaction_session_timeout: 60000` (60s)
   - `lock_timeout: 5000` (5s)
2. `TenantBulkhead` concurrency governor in `src/nexus/governance/bulkhead.py`.
3. Single-use redemption check on `jti` claim in `src/nexus/auth/run_tokens.py`.
