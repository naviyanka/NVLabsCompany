# Micro-Phase 1.1: Request Idempotency Middleware & Ledger (F3)

## 1. Problem Statement
Agents, Temporal workflows, and network retries frequently re-dispatch mutating HTTP requests (`POST`, `PUT`, `PATCH`, `DELETE`). Without an authoritative idempotency layer, side-effecting operations like agent hiring, budget changes, or external integrations duplicate operations.

## 2. Technical Invariants
1. A mutating request with the same `(company_id, Idempotency-Key)` must execute exactly once.
2. An identical request received while the first is in-flight returns `409 Conflict` with `Retry-After: 2`.
3. A completed request re-sent with the same key returns the cached response with header `Idempotent-Replay: true`.
4. A re-sent request with the same key but different canonical body hash returns `422 Unprocessable Entity` (`IDEMPOTENCY_KEY_REUSED`).

## 3. Database Schema
```sql
CREATE TABLE idempotency_records (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id     uuid NOT NULL,
  idem_key       text NOT NULL,
  endpoint       text NOT NULL,
  request_hash   text NOT NULL,
  response_body  jsonb,
  status_code    int,
  state          text NOT NULL DEFAULT 'in_flight',
  created_at     timestamptz NOT NULL DEFAULT now(),
  expires_at     timestamptz NOT NULL DEFAULT now() + interval '24 hours',
  CONSTRAINT uq_company_idem_key UNIQUE (company_id, idem_key)
);
```

## 4. Middleware Implementation Logic
- Extract `Idempotency-Key` header. If missing, pass through.
- Compute SHA256 of canonical JSON body.
- Try `INSERT INTO idempotency_records ... state='in_flight'`.
- If `IntegrityError` (key exists):
  - If `request_hash` differs -> `422 IDEMPOTENCY_KEY_REUSED`.
  - If `state == 'in_flight'` -> `409 REQUEST_IN_FLIGHT`.
  - If `state == 'complete'` -> replay cached status and body with `Idempotent-Replay: true`.
- Execute route handler.
- Update record with `state='complete'`, `status_code`, and `response_body`.
