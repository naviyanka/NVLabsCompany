# SECURITY-DEBT-01: Transaction-scoped tenant RLS context

Status: open. This is a design and test task. It is deliberately not fixed inside
the Clubhouse-integration phases (P3 and later), so that no partial fix lands by
accident.

## Invariant

> A database connection must never retain tenant authorization context beyond
> the transaction in which it was established.

## Concern

`nexus.database.tenant_session` sets the tenant with a **session-level** GUC:

```python
await session.execute(text("SELECT set_config('nexus.company_id', :cid, false)"), ...)
...
finally:
    await session.execute(text("RESET nexus.company_id;"))
```

The third argument `false` means the setting belongs to the pooled
*connection*, not the transaction. That is unsafe in the following sequence:

1. `set_config(company_id)` runs on connection C1.
2. The caller commits. The `AsyncSession` releases C1 back to the pool.
3. A later statement in the same `AsyncSession` (or the `RESET` in `finally`)
   checks out a connection again, and may get C2 instead of C1.
4. Either:
   - the `RESET` runs on C2 and C1 goes back to the pool still carrying tenant
     A's `nexus.company_id`, where the next borrower (tenant B, or a code path
     that never sets a tenant) inherits tenant A's RLS visibility; or
   - statements after the commit run on a connection with **no** tenant context,
     so under `FORCE ROW LEVEL SECURITY` they silently see zero rows or fail
     `WITH CHECK` on insert.

A failed `RESET` is only logged at debug level, which widens the window.

## Proposed design (to validate, not yet approved)

- Use **transaction-local** settings: `set_config('nexus.company_id', :cid, true)`.
  PostgreSQL discards a transaction-local setting at COMMIT or ROLLBACK, so the
  connection cannot carry it past the transaction whatever the pool does.
- Re-apply it at the start of **every** transaction on the session with a
  SQLAlchemy `after_begin` event listener on the tenant session (keyed off a
  `session.info["company_id"]` value), so a commit in the middle of a request
  does not leave the next transaction without tenant context.
- Remove the `RESET` in `finally`, which becomes redundant, and add a pool
  `checkin` or `reset` hook that asserts `current_setting('nexus.company_id', true)`
  is empty. Violations are logged loudly and fail tests.
- The BYPASSRLS credential must never share a pool with tenant sessions. It has since
  been moved out of the API and workers entirely: only the system runtime process
  holds it, for discovery. See `docs/runbooks/system-runtime.md`.
- SQLite has no RLS or GUCs. The listener must be a no-op there, and the SQLite
  test suite must not pretend to cover RLS.

## Required tests

PostgreSQL-specific tests are marked and skipped on SQLite. SQLite behaviour is
covered by a separate test set.

| # | Scenario | Expectation |
|---|---|---|
| 1 | Connection reuse: a pool of size 1, tenant A's transaction commits, then a raw checkout reads `current_setting('nexus.company_id', true)` | Empty |
| 2 | Tenant A then tenant B on the same pooled connection | B sees only B's rows; no A rows are visible at any point |
| 3 | Commit, then more statements in the same tenant session | The second transaction still has tenant A's context (after_begin re-applied it) |
| 4 | Rollback | Context is cleared; the next transaction on the session re-applies it |
| 5 | Concurrent requests (N tasks, alternating tenants, small pool) | Every task sees only its own tenant's rows |
| 6 | Mid-request transaction (the session commits twice inside one request) | Both transactions are tenant-scoped; no insert fails `WITH CHECK` |
| 7 | RLS-protected tables (the `c4f7d2e91b50` set plus `agent_sessions` and `mcp_bindings`) | Read and insert isolation holds for each table |
| 8 | PostgreSQL specifically | Tests 1 to 7 run against a real PostgreSQL instance with `FORCE ROW LEVEL SECURITY` and a non-BYPASSRLS role |
| 9 | SQLite behaviour, tested separately | The listener is a no-op; tenant filtering still comes from application `WHERE company_id = ...`; no GUC SQL is emitted |

## Out of scope

- Enabling RLS on the currently unprotected tables (ws07, phase P10).
- Changing callers of `tenant_session`, beyond what the listener requires.
