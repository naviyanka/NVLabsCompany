# ADR 0006 — Azure conversational CEO

**Status:** Proposed (draft PR). Documentation only; no implementation starts before this ADR is approved.
**Date:** 2026-10-01
**Baseline:** `main` at `5f5502d22e5159c65d81a66739ccaca030554426`
**Amended:** 2026-10-01. The amendment resolves the open decisions of the first draft (Teams bot implementation, cost accounting, native calling, federation preview, telephony, merge ordering) and keeps the outbound-call policy requirement explicitly unresolved. The Azure OpenAI token scope was resolved on 2026-10-02 (see "Still unresolved by design").

## Problem

The CEO should be reachable by voice and chat from the NEXUS dashboard, Microsoft Teams and Telegram, and should be able to pull the human operator in when something needs attention. Every one of those surfaces must obey the same rules: the same identity checks, tenant isolation, tool policy, approvals, memory, audit, cancellation and budgets that already govern a dashboard chat turn.

Two things on `main` make this harder than "add a voice endpoint":

- The governed CEO path is the durable `ChatTurn` runtime (`chat_turns.create_turn(..., require_manager_tools=...)`, `ChatTurnWorker` with claim, lease and cancel, `ExecutionContext`, `guarded_call`, `ToolPolicy`, `AutonomyGate`, `tool_invocations`, `audit_log`). Anything that talks to a model outside that path bypasses the governance this project exists to enforce.
- The pieces that surround that path are not ready for streaming or for multiple channels (see "Current gaps on main" below).

An earlier attempt, PR #55 plus three uncommitted or unmerged local voice branches, built a local speech stack (Whisper, Piper, Kokoro, Chatterbox) behind a worker boundary. It contains good, reusable gateway work and a lot that does not belong in an Azure production path. The extraction plan (`docs/architecture/azure-conversational-ceo-extraction-plan.md`) decides, component by component, what is ported and what is rejected.

## Current gaps on main

These are facts about `main` at the baseline commit and are the reason the roadmap is ordered the way it is.

- **Provider streaming.** `adapters/hermes_provider.py` streams `/chat/completions` but assembles the response internally and exposes no `on_text` callback. `chat.py::_stream_llm` bypasses budget reserve and settle, estimates tokens roughly, and streams only for the `anthropic` and `openai` wire formats. `LLMConnection.wire_format` allows only `openai` and `anthropic`.
- **Azure adapter.** `adapters/azure_adapter.py` is non-streaming, authenticates with an `api-key` header, and has no SSRF guard.
- **Tool lifecycle.** No tool lifecycle events exist (requested, running, completed), so a voice or chat client cannot show or narrate tool progress.
- **Event bus.** `realtime/event_bus.py` is in-process only. It cannot fan turn events out to a separate channel service.
- **Hard-coded adapter support.** `ceo_service.tool_support` hard-codes which adapters can run tool-capable CEO turns.
- **Execution context.** `ExecutionContext` is frozen, carries a free-string `source`, and has no channel field.
- **Channel ingress.** The existing Telegram route has no secret-token check, no update de-duplication and no chat-to-user mapping, and `/task` creates a `Task` from any sender. Tenant is derived only from the API-key company. OIDC SSO hard-codes the default company and records no Entra `tid` or `oid`.
- **WebSocket origin.** Origin is enforced in `auth/middleware.py`, but a missing Origin header is allowed.

## Paths investigated

1. **Azure Speech plus Azure OpenAI behind the NEXUS `ChatTurn` runtime (chosen).** Speech is a transport and provider. The model is a provider. NEXUS keeps every authority.
2. **Azure Voice Live API as the primary path (rejected).** It is a managed speech-to-speech loop. The model and tool calls would run inside the provider's session, outside the durable `ChatTurn`, `guarded_call`, `ToolPolicy` and budget accounting. That bypasses the governed turn. It may be reconsidered only for a feature that has no tools and no tenant data.
3. **Keep the local voice stack as the production path (rejected).** It was built for a single workstation: a GPU-bound worker transport, Windows-specific engines and launcher scripts, and licence boundaries (Kokoro and Chatterbox packaging, GPL speech components) that must never enter the core backend. The branches are preserved as possible future offline fallbacks only, not as part of the Azure production path.
4. **A second permission engine in a channel service (rejected).** Teams and Telegram services must be thin. Duplicating `ToolPolicy` outside NEXUS would create two sources of truth for authorization.
5. **Hand-written Microsoft Graph and Teams authentication (rejected unless unavoidable).** Prefer a Microsoft-supported SDK in a thin channel service.

## Decision

### Pipeline

Azure Speech streaming speech-to-text, then a NEXUS durable `ChatTurn`, then an Azure OpenAI streaming governed tool loop, then sentence-safe Azure Speech text-to-speech, delivered to the browser, Teams or Telegram.

### Authority

- NEXUS is authoritative for identity, tenant isolation, `ToolPolicy`, approvals, memory, audit, cancellation and budgets.
- Azure, Teams and Telegram are transports and providers. They are not permission engines.
- Voice or chat can never approve a high-risk action. Approvals stay in the governed approval flow with an authenticated dashboard or equivalent step-up path.
- Tool calls are read only from the structured `tool_calls` field. No textual tool-call parsing, consistent with ADR 0005.
- There is no automatic LLM fallback for a tool-capable CEO turn. A different provider can change tool semantics, cost and data residency, so a provider failure fails the turn visibly.
- A speech failure falls back to text only. It never falls back to a different model.
- Late audio and late model output are rejected by generation ID (see the extraction plan and the roadmap for the state machine).

### Hosting

- The NEXUS backend, dashboard and ordinary channel services (Teams tab and bot, Telegram adapter) target Azure Container Apps.
- Native Teams media calling runs, if it is ever approved, as a separate isolated service compatible with Microsoft's media SDK requirements (see Limits and "Native Teams calling" below). That service contains no database access, no `ToolPolicy` and no business logic. It receives commands and returns media and call state.

### Authentication and secrets

- Entra ID and managed identity are preferred. Key Vault holds external credentials.
- No Azure OpenAI or Speech key appears in agent configuration or channel configuration. Agents may select only operator-listed deployment names, as ADR 0005 does for Hermes models.
- The Teams bot identity and the Teams calling identity are separate Entra applications with separate permissions.
- **Production credentials use a currently supported, stable method:** managed identity where the platform supports it, and a certificate credential held in Key Vault otherwise. Managed identity as a federated credential is in public preview and is not a production dependency. A preview feature may be evaluated only in the disposable test tenant, and any such evaluation must document a stable fallback that production would use instead.
- The Telegram webhook secret and bot token stay in Key Vault.

### Teams

- Ship order: personal app first, then bot and Adaptive Cards, then native outbound calling only after an explicit spike.
- One Teams tenant installation maps to exactly one NEXUS company in v1. The schema must not prevent a future, controlled multi-company design.
- **Bot implementation.** Prefer a Microsoft-supported Teams SDK or Microsoft 365 Agents SDK in a thin TypeScript channel service. The service performs the Teams protocol and authentication and forwards normalized, authenticated events to NEXUS. It contains no `ToolPolicy`, no database, no memory and no business logic. JWT and other Teams authentication is not hand-written unless a bounded SDK spike proves the supported SDK unsuitable, and that finding is recorded before any hand-written authentication is merged. Final SDK selection is an acceptance gate of the Teams bot PR (PR 8).
- Do not hand-write broad Graph authentication without necessity.

### Native Teams calling

- A development-only calling spike is approved only after the attention engine (PR 10) is complete. It runs with a fixed Azure budget and one allowlisted recipient.
- No production calling permission is granted before the spike. The Graph calling permissions listed under Limits are never consented in a production tenant by this work.
- Production calling is a separate go or no-go decision taken after the spike's written findings. It is not implied by the spike passing.
- The calling service stays isolated from the NEXUS database and tools in every case.
- Whether an application access policy or an equivalent tenant policy is required for outbound calls is unresolved until the spike. If the authorization requirements are unclear at any point, outbound calls stay disabled.

### Telephony

PSTN and Azure Communication Services telephony are explicitly out of scope for the initial release. Telephony needs its own future ADR, written after the Teams personal app, the Teams bot, Telegram, the attention engine and Teams calling acceptance.

### Telegram

- Text only by default.
- Voice messages need opt-in consent and a disclosure that Telegram retains the message on its own platform.
- A live conversation opens the governed NEXUS voice experience rather than running voice inside Telegram.
- The existing Telegram route must not remain trusted as-is. PR 0 of the roadmap hardens it, and it is a product-security prerequisite rather than a voice feature (see "PR 0 security item").

### Costs

- **Extend the existing `cost_events` ledger.** The proposed fields are nullable `usage_unit`, `quantity`, `provider_request_id` and `provider_operation`. Existing rows and existing readers keep working because the new fields are optional. The migration is written after PR #58 merges and is reviewed for compatibility with every current reader of `cost_events`.
- Preserve the existing reserve, commit and release semantics.
- The provider request ID supports idempotent reconciliation: recording or settling the same provider request twice must not double-charge.
- A separate usage table requires a future ADR that proves retention or accounting semantics cannot fit `cost_events`.
- Reserve budget before every provider call. A streaming call must settle or release its reservation when the stream ends, is cancelled or fails, and may never bypass token or cost accounting.
- Speech seconds, TTS characters and model tokens all use the same company budget policy, so one budget covers a conversation.

### Data

- No Alembic revision is chosen until PR #58 (Governance Studio) merges, because it also adds migrations. Previously shipped migrations are never edited.
- Every new tenant table requires `ENABLE` and `FORCE ROW LEVEL SECURITY` with a `tenant_isolation` policy on `company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid`, and PostgreSQL tests, following the existing convention.
- Planned tables: `channel_installations`, `channel_identities`, `channel_sessions`, `channel_deliveries`, voice preferences and consent, `attention_rules`, `attention_incidents`, `attention_delivery_attempts`. Idempotency keys: unique (channel, provider_tenant, provider_subject) for identities, unique (channel, provider_update_id) for inbound updates, unique (incident, step, channel) for outbound escalation.

### Security model for `channel_installations`

A webhook or Teams activity arrives before the tenant is known, so resolving "which company does this installation belong to" cannot happen under a tenant-scoped session. The decision is:

- Do not create a globally readable mapping table.
- `channel_installations` is tenant-owned and protected by FORCE RLS like every other tenant table.
- Pre-tenant lookup goes through exactly one narrow, audited database function that takes the provider tenant or bot identifier and returns only the company ID (and an enabled flag). The application role gets `EXECUTE` on that function and no direct `SELECT` outside tenant scope.
- Every call to the function is audited, and a miss is indistinguishable from a disabled installation to the caller.
- After the lookup, the request runs under the normal tenant session, and the background-work tenant-session rules already on `main` apply.
- The design review for that PR must include a PostgreSQL test that the application role cannot read other tenants' installation rows directly.

### Fallback voice branches and PR #55

The local voice branches are preserved only as possible future offline fallbacks and are not part of the Azure production path. PR #55 is superseded and must not be merged. It stays open as a draft until the reusable ticket, gateway, backpressure and dashboard pieces have been ported by the roadmap PRs, then it is closed with a link to the replacing PRs.

## Required fixes when porting from PR #55

- Recheck membership and cookie-session validity during a live session, not only at connect time.
- Preserve single-use ticket redemption.
- Port generation IDs so stale audio and stale model output are rejected.
- Port non-blocking TTS cancellation.
- Port bounded drop-oldest backpressure with arrival-ahead protection.
- Preserve the no-raw-audio-storage tests.
- Replace the local worker transport with provider interfaces.
- Never edit previously shipped Alembic migrations.
- Never import GPL-licensed local voice workers into the core backend.

## Roadmap

Each PR is small, independently reviewable and disabled behind a feature flag until its gates pass. "Live Azure access" means the PR's own acceptance cannot be proven without a real Azure or Microsoft 365 tenant. Fake-provider tests are required in every case.

| PR | Scope | Depends on | Feature flag | Acceptance gates | Rollback | Live Azure access required? |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 0 | Legacy channel ingress hardening (product-security prerequisite, see below) | PR #58 merged, then this documentation PR merged | none (default-disabled or fail closed) | Telegram route rejects a missing or wrong secret header; update-ID de-duplication; chat-to-user mapping required; `/task` from unmapped sender refused; tenant never derived from an unauthenticated sender; tests for replay and forged updates; a written finding on whether the route is reachable in any normal deployment | Revert the PR; the route is disabled by default until the previous behavior is explicitly re-enabled by an operator | No |
| 1 | ADR 0006, extraction plan, component matrix (this PR) | None | none | Docs checks pass; ADR approved | Revert the docs commit | No |
| 2 | Azure OpenAI streaming provider with `on_text` callback, tool lifecycle events and budget reserve and settle | 1 (PR 0 takes priority first if the Telegram route is reachable) | `AZURE_OPENAI_ENABLED` (operator setting, default false) | SSRF-guarded endpoint; Entra or managed-identity auth; structured `tool_calls` only; cancellation closes the stream; reserve and settle on success, cancel and error; fake-server tests; the Entra token scope verified against current official documentation and a disposable authenticated probe, then documented and tested (one scope only, no guessed second scope, no silent fallback) before the provider can be enabled | Flag off; provider unregistered | Yes, for token-scope and streaming verification only (one small paid call, approved first) |
| 3 | Azure Speech STT and TTS providers behind provider interfaces | 1 | `AZURE_SPEECH_ENABLED` (default false) | Interfaces replace the local worker transport; Entra auth with the custom subdomain; usage metered in the ledger; no raw audio persisted; fake-provider tests | Flag off | Yes, for the custom-subdomain and Entra token path |
| 4 | Channel-neutral streaming runtime: turn events with offsets, generation IDs, sentence-safe buffering, cancel, backpressure | 2, 3 | `CHANNEL_STREAMING_ENABLED` | State machine tests; late-output rejection; drop-oldest backpressure; reconnect from a `turn_events` offset; cross-process fan-out replaces the in-process-only bus where a separate channel service needs it | Flag off; the dashboard chat path is unchanged | No |
| 5 | Browser live voice on the new runtime | 4 | `BROWSER_VOICE_ENABLED` | Single-use ticket; cookie and Origin checks (missing Origin rejected for voice); live membership recheck; tenant and CEO binding with replacement watcher; ported voice panel and mic preflight; no-audio-storage tests; manual acceptance recorded | Flag off; text chat unaffected | Yes, for manual acceptance |
| 6 | Channel identity foundation: `channel_installations`, `channel_identities`, `channel_sessions`, `channel_deliveries`, narrow audited pre-tenant lookup | PR #58 merged (for the migration revision), 0 | `CHANNELS_ENABLED` | FORCE RLS on all tables with PostgreSQL tests; the lookup function is the only pre-tenant read; unique idempotency keys; OIDC records `tid` and `oid` instead of the hard-coded default company | Revert migration with a downgrade tested on a fresh database; flag off | No |
| 7 | Teams personal app and SSO | 6 | `TEAMS_TAB_ENABLED` | One installation maps to one company; Entra token validation; app manifest least privilege; sideload acceptance | Flag off; uninstall the app | Yes |
| 8 | Teams bot and Adaptive Cards (thin TypeScript channel service) | 6, 7 | `TEAMS_BOT_ENABLED` | Supported Teams SDK or Microsoft 365 Agents SDK selected and recorded (acceptance gate); service has no ToolPolicy, database, memory or business logic; activity validation; cards never approve high-risk actions; delivery idempotency | Flag off; remove the bot registration | Yes |
| 9 | Telegram bot | 0, 6 | `TELEGRAM_ENABLED` | Webhook secret check; update de-duplication; text-only default; voice messages need recorded consent and disclosure; live voice launches the NEXUS voice page | Flag off; deregister the webhook | Yes, for webhook registration |
| 10 | Attention engine: rules, incidents, escalation ladder | 6, and at least one of 7, 8, 9 | `ATTENTION_ENABLED` | Idempotent per (incident, step, channel); no duplicate outbound contact; quiet hours; budget-limited; audited | Flag off; rules stop firing | No for logic; Yes for end-to-end |
| 11 | Native Teams calling spike (development only, time-boxed, throwaway, fixed Azure budget, one allowlisted recipient) | 8 and 10 complete | none (not merged to production paths) | Written findings: permission set, admin consent, whether an application access policy or equivalent tenant policy is required (outbound calls stay disabled if unclear), media-host requirements, latency, cost; no production calling permission granted; production go or no-go recorded separately | Delete spike resources; remove the spike app registration | Yes |
| 12 | Calling production service (separate isolated media service) | 11 findings accepted and a separate production go decision | `TEAMS_CALLING_ENABLED` | No database or `ToolPolicy` in the service; separate calling identity; recording status handled; duplicate-call protection; kill switch | Flag off; scale to zero; revoke the calling permissions | Yes |
| 13 | Reliability and cost rollout: SLOs, alerts, quotas, load tests, runbooks | 2–10 | per-feature flags | Latency budgets measured; budget abuse tests; provider outage drills; cost dashboard | Stepwise flag-off per channel | Yes |

### PR 0 security item: legacy channel ingress hardening

This item is documented here and is not implemented by this PR. PR 0 is a product-security prerequisite for the platform, not merely a voice feature.

- The existing legacy Telegram ingress must be default-disabled, or must fail closed, until sender mapping, webhook authentication and replay protection all exist. It must verify the `X-Telegram-Bot-Api-Secret-Token` header against a secret held in the secret backend, de-duplicate updates, map a Telegram chat to an authenticated NEXUS user, and refuse `/task` for unmapped senders.
- PR 0 must first determine whether the route is reachable in any normal deployment, and record that finding in the PR.
- If the route is reachable, the security fix takes priority over Azure provider implementation (PR 2 onward).
- Until PR 0 ships, operators who expose the Telegram webhook publicly should treat it as unauthenticated.

### Merge ordering

1. PR #58 (Governance Studio) merges first.
2. This documentation PR is then rebased onto the new `origin/main` and must remain docs-only after the rebase.
3. Only after this documentation PR merges may PR 0 begin. No source implementation starts before then.

## State machine and latency (design targets)

States: listening, partial transcript, final transcript, thinking, text delta, tool requested, tool running, tool completed, sentence ready, speaking, then interrupted, completed, cancelled or error. All numbers below are targets and are unmeasured until PR 13.

- **Sentence-safe buffering.** Only content from a model response that finishes without `tool_calls` is spoken. Tool JSON is never spoken.
- **Filler.** An optional fixed, server-written filler phrase may be spoken after roughly 800 ms of `tool_running`. The model does not generate it.
- **Generation IDs.** Every turn output carries a generation ID. Barge-in or a new turn increments it, and late audio or text from an old generation is dropped.
- **Cancellation.** Cancel closes the model stream and calls `request_cancel` on the turn. TTS cancels per sentence without blocking the event loop.
- **Backpressure.** Bounded queues drop the oldest audio first, with protection against the arrival side running ahead of playback.
- **Reconnect.** The client fetches a fresh single-use ticket and resumes from a `turn_events` offset.
- **Fallback.** A speech failure degrades to text. A model failure fails the turn.
- **Budgets (target, p50 / p95).** STT final 300 ms / 600 ms; enqueue to worker pickup 50 ms / 200 ms; first model delta 700 ms / 1500 ms; first TTS audio byte 300 ms / 600 ms; end of speech to first audible audio about 1.5 s / 3 s.

## Limits and unverified items

Everything here was determined without logging in to Azure, creating resources, calling a model, or reading credentials.

- **Azure OpenAI token scope is unverified and stays unverified in this ADR.** The v1 base path is `/openai/v1/` and the role is Cognitive Services OpenAI User, but whether the Entra scope is `https://ai.azure.com/.default` or `https://cognitiveservices.azure.com/.default` is not decided here. PR 2 must verify the correct scope against current official documentation and a disposable authenticated probe. It must not implement both guessed scopes or fall back silently, and the accepted scope must be documented and tested before the provider can be enabled.
- **Speech Entra authentication** needs a custom subdomain on the Speech resource, which cannot be changed afterwards. Roles: Cognitive Services Speech User or Contributor. Scope: `https://cognitiveservices.azure.com/.default`. The Python Speech SDK accepts a `token_credential` with the custom endpoint.
- **Graph permissions for calling** are application permissions that all need administrator consent: `Calls.Initiate.All`, `Calls.InitiateGroupCall.All`, `Calls.JoinGroupCall.All`, `Calls.JoinGroupCallasGuest.All` and `Calls.AccessMedia.All`. They are requested only by the PR 11 and PR 12 identity, never by the bot or tab.
- **Manifest.** The bot's calling support is declared in `bots[0].supportsCalling` (manifest schema 1.11).
- **Native media service requirements.** The Microsoft media SDK path needs a .NET service on Windows Server with at least two cores, a public IPv4 address, a CA-signed certificate for a public FQDN, and port 443 plus UDP media ports. This is why it cannot run on the ordinary Container Apps channel services. Recording or persisting media requires `updateRecordingStatus`.
- **Whether an application access policy (or an equivalent tenant policy) is needed for outbound calls is unresolved.** The PR 11 spike must verify it. If the authorization requirements are unclear, outbound calls remain disabled.
- **Bot Framework SDK** receives no servicing after 2025-12-31. Microsoft recommends the Teams SDK or the Microsoft 365 Agents SDK. The Teams bot is planned as a TypeScript channel service, so the Python library status of either SDK is not a dependency; the final SDK is chosen in PR 8.
- **Managed identity as a federated credential** is in public preview and is not a production dependency. Production uses managed identity where supported, or a certificate credential otherwise.
- **Telegram.** The `secret_token` header is `X-Telegram-Bot-Api-Secret-Token`. Telegram retains voice messages on its own platform, which is why voice is opt-in with a disclosure.
- **Latency numbers** are targets. None has been measured.
- **Migration compatibility** of extending `cost_events` with the four nullable fields is expected but unconfirmed until migration review after PR #58 merges.

## Resolved and remaining decisions

Resolved by the 2026-10-01 amendment:

1. Teams bot: a Microsoft-supported SDK in a thin TypeScript channel service; final selection is a PR 8 acceptance gate.
2. Cost accounting: extend `cost_events` with four nullable fields; a separate usage table needs a future ADR.
3. Native Teams calling: a development-only spike after PR 10, fixed budget, one allowlisted recipient, no production permission before it; production is a separate decision.
4. Federation preview: not a production dependency; a stable method is required in production.
5. Telephony: out of scope for the initial release; needs a future ADR.
6. Merge ordering: PR #58, then rebase this PR, then PR 0.
7. Telegram: PR 0 is a product-security prerequisite and takes priority over Azure provider work if the route is reachable.

Still unresolved by design:

1. ~~The Azure OpenAI Entra token scope~~ **Resolved 2026-10-02:** for `*.openai.azure.com` on `/openai/v1/chat/completions`, NEXUS uses `https://ai.azure.com/.default`. Microsoft Learn pages disagree for that path, so one live probe tested both candidates (one user principal, one tenant, one South India resource): both `https://cognitiveservices.azure.com/.default` and `https://ai.azure.com/.default` returned HTTP 200. NEXUS deliberately selects `ai.azure.com` as the service-specific audience; this does not claim the other scope is invalid. There is no fallback, scope setting or runtime probing, and other endpoint families stay rejected. One application-level request through the adapter then succeeded (details in `docs/azure-openai-provider.md`, sanitized record in `docs/testing/evidence/azure-openai-entra/ACCEPTANCE.md`); production enablement remains a separate decision. **Still unverified:** managed-identity and service-principal authentication, other tenants, regions and endpoint families.
2. Whether outbound calls need an application access policy or equivalent tenant policy (PR 11 verifies it).
3. Whether the Azure OpenAI deployment is one global deployment or one per environment, and the data-residency region.

## PR 2 implementation note (2026-10-02)

The Azure OpenAI streaming provider is implemented behind `AZURE_OPENAI_ENABLED` (default false); see `docs/azure-openai-provider.md`. Microsoft Learn disagrees on the Entra scope for the resource family (`*.openai.azure.com`) on `/openai/v1/`, and no disposable authenticated probe has been run, so unresolved item 1 above stays open. Only that family is supported; Foundry project endpoints (`*.services.ai.azure.com`) are disabled with a stable reason. The scope is derived in code from the endpoint family and is currently unresolved, so Entra is unavailable and development key auth (secret reference) is the only usable mode; there is no scope setting and no fallback. A live probe in the disposable tenant must verify one scope before Entra production enablement. `azure-identity` and `aiohttp` are pinned base dependencies, import-smoked on the production image in CI. Text is streamed progressively only for tool-free calls; a tool-capable round buffers its text until the round ends, so low-latency governed voice needs a later two-phase conversation strategy (not part of this PR).
