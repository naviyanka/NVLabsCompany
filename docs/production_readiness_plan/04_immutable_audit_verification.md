# Micro-Phase 2b: Immutable Audit Verification (F1)

## 1. Problem Statement
SQLite in-memory test engines do not trigger PostgreSQL PL/pgSQL triggers, allowing untested assumptions about audit log immutability and tamper resistance.

## 2. Technical Invariants
1. Database triggers `audit_log_append_only` must abort direct `UPDATE` queries on `audit_log` with an exception.
2. Database triggers must abort `DELETE` queries on `audit_log` with an exception.
3. Only `archived_at` may be updated by retention workers.

## 3. Implementation Status
- Container fixture runs `pgvector/pgvector:pg16` with full Alembic migration chain.
- Test `test_postgres_audit_log_immutability` executes in `tests/test_postgres_integration.py` (commit `93caec1`).
