# UI Controls Plan — surfacing backend-only features in the dashboard

**Date:** 2026-08-26
**Context:** The Wave 0–6 backend work (see `FEATURE_PLAN.md`) is implemented and tested,
but ~8 features have no dashboard control. This plan closes that gap.

Backend-readiness was verified against `src/nexus/api/routes/`. Most gaps are **UI-only**
(the endpoints already exist); three need a small backend addition first.

## Endpoint readiness (verified)

| Feature | Backend | Endpoints |
|---|---|---|
| Autonomy policy | READY | `PATCH /api/v1/companies/{id}/agents/{aid}` accepts `autonomy_policy` (JSON `{action_type:1\|2\|3}`) |
| Triggers | READY | `GET/POST /api/v1/companies/{id}/triggers`, `PUT /api/v1/triggers/{id}`, `POST /api/v1/triggers/{id}/fire`, `GET /api/v1/triggers/{id}/executions` |
| Secrets vault | READY | `GET/POST /api/v1/secrets`, `POST /api/v1/secrets/{id}/rotate`, `/revoke`, `/bind` |
| Skill policy | READY | `skill_policy` doc stored in `CompanySettings.settings_json`; read/write via `GET/PATCH /api/v1/companies/{id}/settings` |
| Policies (generic) | READY | `GET/POST/PUT/DELETE /api/v1/policies`, `POST /api/v1/policies/evaluate` |
| Audit chain verify | NEEDS BACKEND | `audit.py` has list+stats only; add `GET /api/v1/companies/{id}/audit-logs/verify` |
| Watchdog / heartbeat | NEEDS BACKEND | `HeartbeatRun` table exists; add a read endpoint for run liveness |
| Company export/import | NEEDS BACKEND | no route yet; service may exist — add routes |
| MCP server / adapter coverage | UI later | lower priority; adapters registry exists |

## Micro-phases

Ordered by value-to-effort. Each phase is independently shippable and names its check.

### Phase U1 — Autonomy policy editor · UI only · HIGH
Per-agent autonomy tiers gate every tool call but are invisible today.
- U1.1 Add an "Autonomy" section to the agent detail page: a row per action type
  (`write_files`, `delete`, `execute_code`, `send_external`, `spend`) with an L1/L2/L3
  selector, plus an optional `spend_above_cents` threshold input.
- U1.2 Load current `autonomy_policy` from the agent; save via the agent PATCH.
- U1.3 Sensible default when the field is null (show L1 everywhere).
- **Check:** set an action to L3, reload — the value round-trips; PATCH hits the API.

### Phase U2 — Triggers management · UI only · HIGH
Triggers fire runs but cannot be created from the UI.
- U2.1 A Triggers surface (tab on Workflows or a section on the agent page): list triggers
  with type, schedule, next-fire, last-fire, active toggle.
- U2.2 Create modal: agent, trigger_type (`cron`/`interval`/`once`/`webhook`/`on_message`),
  name, config (cron expr / interval / webhook secret), active.
- U2.3 Row actions: activate/deactivate (PUT), fire now (POST `/fire`), view executions.
- **Check:** create a cron trigger, see it listed with a computed next-fire; fire it and see
  an execution row.

### Phase U3 — Audit chain verify (wire the real thing) · small backend + UI · HIGH · DONE
The button today fakes success client-side.
- U3.1 Backend: `GET /api/v1/companies/{id}/audit-logs/verify` calling the existing
  `PersistentAuditLogger.verify_chain_integrity()`; return `{valid, checked, broken_at?}`.
- U3.2 UI: `handleVerifyMerkleChain` calls it and shows the real verdict (green/red).
- **Check:** verify passes on a clean chain; a tampered row reports the break point.

### Phase U4 — Secrets vault panel · UI only · MEDIUM · DONE
- U4.1 New Settings tab "Secrets Vault": list secrets (metadata only — name, category,
  version, expiry, revoked).
- U4.2 Create secret (name, category, value, optional expiry) → POST `/api/v1/secrets`.
- U4.3 Row actions: rotate (new value), revoke, bind-to-agent.
- **Check:** create → appears with version 1; rotate → version 2; value never shown after
  creation.

### Phase U5 — Skill access policy editor · small backend + UI · MEDIUM · DONE
- U5.1 On the Skills page, a "Access Policy" panel: `defaultEffect` allow/deny + an ordered
  rule list (`effect`, subject match, resource match).
- U5.2 Load/save the `skill_policy` document in company settings; bump `revision` on save.
- U5.3 A dry-run "test" using the existing decision semantics (client mirror or a small
  backend evaluate call).
- **Check:** add a deny rule, save, reload — the document round-trips and revision bumps.

### Phase U6 — Watchdog / heartbeat panel · small backend + UI · MEDIUM
- U6.1 Backend: `GET /api/v1/companies/{id}/runs/liveness` returning active `HeartbeatRun`
  rows with `last_output_at`, liveness state, and stalled flag.
- U6.2 UI: a read-only panel (Activity page section or Settings) listing runs, their
  liveness, and any `needs_recovery` state.
- **Check:** an active run shows live; a stalled fixture shows flagged.

### Phase U7 — Company export/import · backend + UI · LOW
- U7.1 Backend: `GET /api/v1/companies/{id}/export` (secret-scrubbed archive) and
  `POST /api/v1/companies/import` (ID remap) if a service exists; else defer.
- U7.2 UI: buttons in Settings → Backup/Restore (or a new tab).
- **Check:** export → import into a fresh company reproduces it with no secret leakage.

### Phase U8 — Adapter coverage / MCP server surface · UI later · LOW
- U8.1 A read-only "Adapters" view listing the 11 registered adapters and which the cascade
  router covers.
- U8.2 (Optional) MCP-server exposure toggle + per-company tool scoping.
- **Check:** the 11 adapters are listed; router coverage is visible.

## Sequencing

U1 → U2 → U3 are the high-value first wave (autonomy is invisible-but-critical; triggers are
unusable from UI; audit verify is a correctness lie). U4–U6 second. U7–U8 last.

## Status

- [x] U1 Autonomy policy editor — verified round-trip (delete=3 persisted)
- [x] U2 Triggers management — verified create/list/fire/history against real API
      (NOTE: backend `compute_next_fire` computed next-fire ~now for a `0 9 * * *` cron
      instead of the next 9am — a backend cron-parse issue to fix separately; UI stores the
      correct config and displays whatever next_fire_at the backend returns.)
- [x] U3 Audit chain verify — added GET /companies/{id}/audit-logs/verify calling
      PersistentAuditLogger.verify_chain_integrity(); wired the button to the real verdict
      (green Verified / red Tampered). Verified 200 {valid:true, checked:3}.
      NOTE: dev DB (`src/nexus_dev.db`) predated Wave 0-6 migrations — added missing columns
      (agents.autonomy_policy, goals.completion_reason, audit_log.sequence_number/entry_hash/
      previous_hash/archived_at) via ALTER TABLE to reconcile schema with models.
- [ ] U2 Triggers management
- [ ] U3 Audit chain verify (backend + UI)
- [x] U4 Secrets vault panel — new Settings tab; verified create (201), rotate (v1→v2),
      list. Backend needs SECRET_KEY set (not dev default) or create/rotate return 503,
      which the UI surfaces as a clear message.
- [x] U5 Skill access policy editor — the general /settings endpoint does NOT expose
      settings_json, so added dedicated GET/PUT /api/v1/companies/{id}/skill-policy (stores
      under settings_json["skill_policy"], bumps revision). Added an "Access Policy" view to
      the Skills page. Verified round-trip: rev 0→1, deny rule {roles:[contractor],
      keys:[deploy-*]} persisted.
- [ ] U6 Watchdog / heartbeat panel (backend + UI)
- [ ] U7 Company export/import
- [ ] U8 Adapter coverage / MCP surface
