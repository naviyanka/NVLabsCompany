# NEXUS / NVLabsCompany — Production Readiness & 10/10 Architecture Master Plan

**Date:** 2026-09-09  
**Scope:** Fail-Safe Concurrency, Real Database Verification, Multi-Tenancy RLS, Idempotency, and Enterprise 10/10 Hardening  
**Target:** 10.0 / 10 Across all Dimensions

---

## 1. Overview & Architecture Thesis

This master plan breaks down the findings from the external deep scan and production scorecard into granular, sequence-ordered **Micro-Phases**. Each phase contains:
1. **Concrete Technical Invariants** (what cannot fail under load).
2. **Implementation Blueprints** (code, schema, middleware, tests).
3. **Acceptance Gates** (how we prove the invariant holds).

---

## 2. Micro-Phase Roadmap Breakdown

- **Phase 1: Money & Idempotency Fail-Safe (F2 & F3)**
  - `01_idempotency_middleware.md`: Table, request hashing, replay header, deduplication.
  - `02_atomic_budget_reservations.md`: Atomic conditional UPDATE, CHECK constraint, reaper.
- **Phase 2: True Database Verification Engine (F1)**
  - `03_testcontainers_postgres.md`: Real Postgres + pgvector test harness, test split.
  - `04_immutable_audit_verification.md`: Verifying trigger rejection under real DB engine.
- **Phase 3: Operational Guardrails & Fault Tolerance (F5)**
  - `05_operational_guardrails.md`: statement_timeout, bulkheads, run-token nonce registry.
- **Phase 4: Database-Level Row-Level Security (F4)**
  - `06_row_level_security.md`: Postgres RLS across all tenant tables, nexus_app role.
- **Phase 5: Real-Time SSE/WS Event Pipeline**
  - `07_realtime_sse_wiring.md`: useEventStream hook, live UI invalidation.
- **Phase 6: Full-Scale Knowledge & RAG Modernization**
  - `08_rag_embeddings_and_rrf.md`: Pluggable embeddings, tsvector GIN, Reciprocal Rank Fusion.
