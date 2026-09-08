# Micro-Phase 2: True Database Verification Engine & Test Split (F1)

## 1. Problem Statement
The 3,789-test suite currently executes against SQLite via `aiosqlite`. SQLite cannot test:
- Postgres update/delete trigger rejections on the immutable audit log.
- pgvector HNSW `<=>` cosine distance queries.
- `JSONB` operators and GIN indexing.
- `SELECT ... FOR UPDATE` and Postgres `READ COMMITTED` race conditions.
- Row-Level Security (RLS) policies.

## 2. Technical Invariants
1. CI integration tests must execute against real PostgreSQL 17 with the `pgvector` extension.
2. Every test run must apply real Alembic migrations (`head`), never unconstrained `SQLModel.metadata.create_all()`.
3. Unit tests remain fast on SQLite; integration and chaos suites run against Postgres.

## 3. Implementation Blueprint
1. Add `testcontainers[postgres]>=4.8.0` to `pyproject.toml`.
2. Session-scoped Postgres fixture in `tests/conftest.py`.
3. Split test suites into:
   - `tests/unit/`: SQLite-compatible, fast.
   - `tests/integration/`: Postgres required, tests real constraints.
   - `tests/chaos/`: Concurrency, failure injection, reaper tests.
4. Add assertion test verifying that modifying an audit log entry raises DBAPIError due to the immutable trigger.
