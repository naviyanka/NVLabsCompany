# Micro-Phase 1.2: Atomic Budget Reservation & Overcommit Protection (F2)

## 1. Problem Statement
Concurrent agent operations evaluate remaining budget in Python before recording cost events. Under parallel load, two workers can both read `used=$95` against a `$100` limit, both pass validation, and both commit `$10`, leading to `$115` spend.

## 2. Technical Invariants
1. Database-level invariant: Total active committed spend plus outstanding reservations can never exceed the hard limit.
2. Concurrent requests competing for the remaining budget are arbitrated atomically inside the database engine without deadlock-prone table locks.
3. Abandoned reservations (crashed workers) automatically expire and are reaped.

## 3. Implementation Blueprint
1. Add table constraint or strict atomic update guard:
```sql
ALTER TABLE budget_policies ADD CONSTRAINT budget_never_overcommitted
  CHECK (spent_cents + reserved_cents <= amount);
```
2. Atomic reservation query with SQL `RETURNING`:
```sql
UPDATE budget_policies
   SET reserved_cents = reserved_cents + :amt,
       updated_at     = now()
 WHERE id             = :policy_id
   AND spent_cents + reserved_cents + :amt <= amount
RETURNING id, reserved_cents, amount;
```
3. If 0 rows updated, raise `BudgetExceeded(code="BUDGET_EXCEEDED", http_status=429)`.
4. Reservation Reaper: Background cron/interval task freeing reservations older than `RESERVATION_TTL_SECONDS`.
