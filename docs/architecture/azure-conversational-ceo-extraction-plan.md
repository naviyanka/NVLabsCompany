# Azure Conversational CEO — Extraction Plan

This plan accompanies [ADR 0006](../adr/0006-azure-conversational-ceo.md). It decides what is reused from the existing local voice work, what is changed on the way, and what is rejected. Nothing in this document is implemented by the pull request that introduces it.

## Sources

| Source | Reference | State |
| :-- | :-- | :-- |
| PR #55, `feat/local-multilingual-ceo-voice-v1` (committed) | Commits `52ef46e` through `58ea2c7`, based on merge base `9b6d51974b8ca35fdc29aa810a1025b1e46a76d5` | Open draft. Superseded by ADR 0006. Must not be merged. |
| Uncommitted work in the `voice` worktree (same branch) | Local backup artifacts `voice/tracked.patch` (SHA-256 `03e80c3724c99052f77f025c56c28aa404dbecfbe79c659b168d8ac50fefc78b`) and `voice/untracked-source.tar.gz` (SHA-256 `14e9f341e5ac42a328b042e62b6c5933c7b7a067b2f06f6def50b3f734b4c568`) | Not committed anywhere. The backup is local only; no backup artifact is part of any pull request. |
| `feat/fast-local-natural-voice-v1`, Kokoro (committed head `58ea2c7`) plus uncommitted work | Local backup artifacts `kokoro/tracked.patch` (SHA-256 `8d73e49127a9a820cf7db2ac02530b030658a9f9d4db7c729980ff1114b245bc`) and `kokoro/untracked-source.tar.gz` (SHA-256 `62586ac622b7fa066da6ffaca224dda27f611d57d312e41165e2d0825efeea1b`) | Preserved as a possible offline fallback. Not part of the Azure production path. |
| `feat/chatterbox-multilingual-ceo-voice` | Commit `241c61e21aae48282a40f5982ff17be3125174cf`; local git bundle `chatterbox-241c61e.bundle` (SHA-256 `424eb3a76c7cae1b54aa8050cff4b50866b90f4b276ecfccd14cf154f9ef7ad5`) | Clean worktree. Preserved as a possible offline fallback. Not part of the Azure production path. |

Backup artifacts are referenced by file name and hash only so that a reviewer with local access can verify them. Their contents and location are deliberately not part of the repository.

## How to read the table

- **Verdict:** *Port* means reuse after the listed changes. *Port unchanged* means reuse the idea or test with no behavior change. *Reject* means the component is not carried forward, with the reason stated.
- **Target PR** refers to the roadmap in ADR 0006 (PR 0 through PR 13).
- "Local voice branch" means the committed PR #55 history unless the row says it comes from uncommitted work.

## Component plan

| Component | Source | Verdict | Target PR | Required changes | Tests to port | Security gaps to close |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Voice ticket mint and single-use redemption (`src/nexus/voice/tokens.py`, `api/routes/voice.py`) | `cfb6134`, `39c72ad` | Port | 5 | Bind a ticket to user, company, CEO agent and session. Keep redemption atomic and single use. Short expiry. Reconnect always fetches a fresh ticket. | Ticket reuse, expiry, wrong-user, wrong-company tests from `tests/test_voice_gateway.py`. | Recheck membership and cookie-session validity during a live session, not only at redemption. |
| Shared ticket, rate-limit and revocation state in Redis (`shared_state.py`, `limits.py`) | `39c72ad` | Port | 5 | Keep the shared store so multiple replicas agree. Fail closed if the shared store is unavailable. Key by tenant. | `tests/test_voice_shared_state.py`. | Per-tenant and per-user caps so one tenant cannot exhaust another's voice capacity. |
| Cookie and Origin authentication on the voice WebSocket | `cfb6134` | Port | 5 | Reject a missing Origin for the voice socket (the general middleware allows it). Authenticate by session cookie or ticket only. | Origin and cookie cases from `tests/test_voice_gateway.py`. | Missing-Origin acceptance on the general WebSocket middleware is a gap this port must not inherit. |
| Tenant and CEO binding, with watcher for CEO replacement or membership removal | `cfb6134`, uncommitted `gateway.py` changes in the voice worktree (backup artifact above) | Port | 5 | Bind the session to the CEO agent at start. Close the session if the CEO is replaced or the user's membership or session is revoked. | Binding and replacement tests in `tests/test_voice_gateway.py`. | Live recheck (see ticket row). Include a PostgreSQL test with a real tenant session. |
| Binary WebSocket protocol (`protocol.py`, `dashboard/src/lib/voice/protocol.ts`) | `cfb6134`, `9e33091` | Port | 4, 5 | Add generation IDs to every server event. Keep binary audio frames with a small typed header. Version the protocol. | Protocol round-trip tests. | Bound frame size and rate on both directions. |
| Dashboard WebSocket proxy (`dashboard/voiceSocketProxy.ts`) | `58ea2c7`, `cfb6134` | Port | 5 | Forward the voice socket through the dev server. Keep Origin and cookie forwarding exact. Do not log tickets. | `voiceSocketProxy.test.ts`. | Ensure tickets in the query string or subprotocol never appear in proxy logs. |
| STT worker boundary and local worker client (`worker_client.py`, `voice/` worker package) | `52ef46e`, `35848c4` | Reject | n/a | Replace with the provider interfaces introduced in PR 3. | None ported; the interface contract tests are new. | The local worker transport trusts a local process. A provider interface to Azure uses managed identity and a network boundary instead. |
| Durable ChatTurn integration and voice metadata on `create_turn` | `c98e452`, `cfb6134` | Port | 4 | Keep the voice settings and message payload on `create_turn`. Add a channel field to the turn or its metadata rather than overloading the free-string `ExecutionContext.source`. Run the turn with `require_manager_tools` for the CEO. | `create_turn` voice-payload tests. | A voice turn must go through the same `guarded_call` and `ToolPolicy` as a text turn. Add a regression test that voice cannot approve a high-risk action. |
| Cancellation and generation IDs (uncommitted) | Uncommitted work in the voice worktree (backup artifact above) | Port | 4 | Generation ID on every output. A new turn or barge-in bumps the generation, and late output is dropped. Cancel closes the model stream and calls `request_cancel`. | `voiceClient.test.ts` and the gateway cancellation tests from the backup. | Late audio or text from a cancelled turn must never reach the client. |
| Bounded drop-oldest backpressure with arrival-ahead protection (uncommitted) | Uncommitted `tests/test_voice_backpressure.py` and `gateway.py` changes (backup artifact above) | Port | 4 | Keep the bounded queue, drop oldest, protect against the receive side running ahead of playback. | `tests/test_voice_backpressure.py`. | Bounds are mandatory so a slow client cannot grow server memory. |
| Non-blocking TTS cancellation (`drop_tts`) (uncommitted) | Uncommitted work in the voice worktree (backup artifact above) | Port | 4, 5 | Cancel per sentence without blocking the event loop. Apply to the Azure TTS provider rather than the local worker. | Backpressure and cancel tests from the backup. | Cancellation must also stop provider billing where the provider supports it. |
| Reconnect with bounded retries and mic preflight (`micPreflight.ts`, `MicCheck.tsx`, `voiceClient.ts`) | `8a86d24`, plus uncommitted `voiceClient.ts` and `voiceState.ts` changes | Port | 5 | Reconnect uses a fresh single-use ticket and a `turn_events` offset. Keep bounded retries and the accessible state UI. | `micCheck.test.tsx`, `voice.test.tsx`, uncommitted `voiceClient.test.ts`. | A reconnect must never replay a consumed ticket. |
| Language routing and multilingual selection | `52ef46e`, `fe33567` | Reject | n/a | The Azure path takes the language from user preference and Azure Speech language settings. The local model-routing logic is tied to local engines. | None. | None. |
| Sentence chunker (`src/nexus/voice/chunker.py`) | `cfb6134` | Port | 4 | Keep sentence-safe splitting. Speak only content from responses that end without `tool_calls`. Never speak tool JSON. | Chunker unit tests. | Strip structured tool content before the chunker sees it. |
| Dashboard voice panel (`VoicePanel.tsx`, `voiceState.ts`) | `9e33091`, plus uncommitted changes | Port | 5 | Keep push-to-talk and the state UI. Remove local-engine and local-voice-catalogue UI. | `voice.test.tsx`. | Show a clear "no audio is stored" statement matching the tests. |
| Doctor checks (`src/nexus/voice/doctor.py`, `nexus doctor --voice`) | `369bf3a`, plus uncommitted changes | Port after modification | 3, 5 | Replace local-engine checks with provider health: endpoint set, identity resolved, deployment or voice present. Never print values. | `tests/test_voice_doctor.py`. | Checks must not make a paid call unless explicitly requested. |
| Audit behavior for voice sessions | `cfb6134` | Port | 5 | Audit session start, end, ticket redeemed and revoked, denied attempts. Never audit audio. | Audit assertions in gateway tests. | Include channel and provider request ID once the ledger fields exist. |
| Privacy and no-raw-audio-storage tests | `cfb6134`, `98a962f` | Port unchanged | 3, 5 | Keep the tests asserting that no raw audio is persisted or logged. Extend to the Azure provider path. | `tests/test_voice_live.py` privacy assertions and gateway tests. | Provider SDK diagnostics must not write audio to disk. |
| Voice gateway guide (`docs/VOICE_GATEWAY.md`) | `98a962f`, `0f3327c`, plus uncommitted changes | Port after rewrite | 5 | Rewrite for the Azure path. Keep the protocol and recovery sections where still true. | n/a | n/a |
| Piper local TTS | `52ef46e` | Reject | n/a | Not part of the Azure path. | None. | GPL and model-licence boundary; must never enter the core backend. |
| Windows SAPI and OneCore TTS (`winspeech.py`) | `91ccd82`, plus uncommitted changes | Reject | n/a | Windows-specific, workstation-only. | None. | None. |
| Kokoro natural voice (`voice-kokoro/`, `natural.py`) | `feat/fast-local-natural-voice-v1` plus uncommitted work (backup artifacts above) | Reject for production; preserve | n/a | Possible offline fallback only. | `tests/test_gpl_boundary.py` idea (a test that GPL code is never imported by the core backend) is worth porting regardless of speech provider. | The GPL boundary test is the one reusable piece. |
| Chatterbox neural voice, GPU coordinator (`voice-neural/`, `gpu.py`, `vram.py`, `neural.py`) | `241c61e` | Reject for production; preserve | n/a | Possible offline fallback only. GPU admission is local-hardware logic. | None. | Pinned supply chain and licence boundary stay with the preserved branch. |
| Alembic edit `b58c4c5` ("skip objects a create_all database already has") | `b58c4c5` | Reject | n/a | It edits previously shipped migrations. That is forbidden. | None. | Shipped migrations must never change. |
| PowerShell launcher scripts (`scripts/start-local-voice.ps1`, `stop-local-voice.ps1`) and local launcher tests | `fb4f4e5`, `91ccd82` | Reject | n/a | Workstation-only. | None. | None. |
| Isolated acceptance stack script | `fb4f4e5` | Reject | n/a | Local-engine specific. A new acceptance procedure is written per roadmap PR. | None. | None. |
| Doctor-acceptance evidence JSON | Uncommitted, `voice/LOCAL-ONLY-evidence.tar.gz` | Reject (never commit) | n/a | Kept in the local backup only. Secret scan found no credentials, but the evidence is machine-specific. | None. | Never put machine evidence in the repository. |

## Required fixes when porting

Every ported component must satisfy these. A reviewer should reject a port that does not.

1. Recheck membership and cookie-session validity during a live session.
2. Preserve single-use ticket redemption.
3. Port generation IDs so stale output is rejected.
4. Port non-blocking TTS cancellation.
5. Port bounded drop-oldest backpressure with arrival-ahead protection.
6. Preserve the no-raw-audio-storage tests.
7. Replace the local worker transport with provider interfaces.
8. Never edit previously shipped Alembic migrations.
9. Never import GPL-licensed local voice workers into the core backend.

## Branch verdicts

- **PR #55 / `feat/local-multilingual-ceo-voice-v1`:** superseded by ADR 0006. Do not merge. Keep open as a draft until the ticket, gateway, backpressure and dashboard pieces above have been ported by PR 4 and PR 5, then close it with links to the replacing pull requests.
- **`feat/fast-local-natural-voice-v1` (Kokoro):** preserve as a possible future offline fallback. Not part of the Azure production path. Do not merge.
- **`feat/chatterbox-multilingual-ceo-voice`:** preserve as a possible future offline fallback. Not part of the Azure production path. Do not merge.
- **Uncommitted voice work:** backed up locally. The reusable fixes are listed above. It is not committed to any branch by this work, and no backup artifact is in the repository.

## Porting procedure

1. Start each port from an up-to-date `main` on its own branch, never from a voice branch.
2. Copy only the files named in a row, reviewing each line. Do not cherry-pick whole commits, because most commits mix reusable gateway work with local-engine code.
3. Apply the changes in the "Required changes" column.
4. Port the listed tests first and see them fail against the new code before they pass.
5. Add a PostgreSQL test for any new tenant table (FORCE RLS) and for any behavior that depends on a tenant session.
6. Run the existing architecture guard rules (R1 through R6) and the generated-artifact check.

## Unknowns that could change this plan

- Whether the four proposed nullable `cost_events` fields are compatible with every current reader (confirmed at migration review after PR #58 merges; ADR 0006 prefers extending `cost_events`).
- Which Microsoft-supported Teams SDK the TypeScript bot service adopts (a PR 8 acceptance gate).
- Whether the uncommitted gateway changes contain further fixes not yet catalogued. Before PR 4, the patch in the local backup should be re-read in full against the rows above.
