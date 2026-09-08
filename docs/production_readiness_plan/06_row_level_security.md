# Micro-Phase 4: Database-Level Row-Level Security (F4)

## 1. Problem Statement
Multi-tenant isolation currently depends on application developers remembering `.where(Model.company_id == cid)` in every query across 320+ endpoints. A single forgotten clause leaks cross-tenant records.

## 2. Technical Invariants
1. The database itself must refuse cross-tenant reads or writes even if the query omits the filter entirely.
2. Tenant identity is injected once per transaction into `current_setting('nexus.company_id')`.
3. Application connects via `nexus_app` role subject to `FORCE ROW LEVEL SECURITY`.

## 3. Implementation Blueprint
1. Migration generator applying RLS policies:
```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table> FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON <table>
  USING (company_id = current_setting('nexus.company_id', true)::uuid)
  WITH CHECK (company_id = current_setting('nexus.company_id', true)::uuid);
```
2. Session initialization in `src/nexus/api/deps.py`:
```python
await session.execute(
    text("SELECT set_config('nexus.company_id', :cid, true)"),
    {"cid": str(principal.company_id)},
)
```
3. Test asserting that `SELECT * FROM tasks` executed as Tenant A returns only Tenant A tasks even with zero WHERE conditions.
