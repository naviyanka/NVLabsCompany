# Local CEO Voice Gateway (v1)

Talk to the designated CEO in Hindi, English or Hinglish. Speech recognition and
synthesis run on this machine. No cloud speech provider is used or falls back.

```
browser ─ binary WS ─▶ NEXUS /api/v1/voice/ws ─ loopback WS ─▶ voice worker (STT / TTS)
                              │                                    (own process, own env)
                              ├─▶ Redis: tickets, rate limits, revocation (shared by workers)
                              └─▶ existing durable CEO chat turn (Hermes-native governed tools)
```

The governed tool architecture is unchanged. A final transcript enters the same
`chat_turns.create_turn` path as a typed message: same snapshot context, executive
memory, ToolPolicy, idempotency, audit identity, cancellation and tenant isolation.

## Setup

Disabled by default.

```
cd voice
uv sync                                  # own env, CPython 3.11, nothing global
uv run nexus-voice setup                 # downloads pinned, SHA-256-checked, commercially licensed models
uv run nexus-voice diagnose              # GPU, CUDA, device, FFmpeg, models
NEXUS_VOICE_WORKER_SECRET=<32+ chars> uv run nexus-voice serve
nexus doctor --voice                     # read-only readiness report (below)
```

Backend `.env`: `VOICE_ENABLED=true`, `VOICE_WORKER_SECRET=<same secret>`, and a reachable
`REDIS_URL`. Optional: `VOICE_WORKER_URL` (loopback only), `VOICE_TICKET_TTL_SECONDS`,
`VOICE_SESSION_TTL_SECONDS`, `VOICE_MAX_UTTERANCE_SECONDS`, `VOICE_UTTERANCES_PER_MINUTE`,
`VOICE_SESSIONS_PER_MINUTE`, `VOICE_COMPANY_UTTERANCES_PER_MINUTE`,
`VOICE_COMPANY_SESSIONS_PER_MINUTE`, `VOICE_DEFAULT_EN`, `VOICE_DEFAULT_HI`.
Models live in `%LOCALAPPDATA%\nexus-voice\models`, never in Git.

## Models and licences

Only commercially usable models are the default and only they are downloaded by `setup`.
Nothing here is legal advice; licences were read from each model's own source, and where a
licence could not be verified the model is not included.

| Item | Model | Licence | Commercial | Default | Downloaded by `setup` |
|------|-------|---------|-----------|---------|----------------------|
| STT | `Systran/faster-whisper-medium` @ `08e178d4…` | MIT | yes | yes | yes |
| VAD | Silero VAD v6 (bundled with faster-whisper) | MIT | yes | yes | n/a |
| TTS en | `en_US-ljspeech-medium` | Public domain (LJ Speech) | yes | **yes** | yes |
| TTS en | `en_US-lessac-medium` | Blizzard 2013 Lessac research licence | no | no | only with the opt-in |
| TTS en | `en_US-ryan-medium` | CC BY-NC-SA 4.0 | no | no | only with the opt-in |
| TTS hi | `hi_IN-pratham-medium`, `hi_IN-priyamvada-medium` | CC BY-NC-SA 4.0 | no | no | only with the opt-in |
| TTS hi | `hi_IN-rohan-medium` | not verified | unknown | not included | never |
| Piper engine | `piper-tts` | GPL-3.0-or-later | n/a | yes | runs as a separate process |

- **No commercial Hindi voice is bundled.** Hindi *recognition* works; Hindi *replies* are text
  only until an operator supplies a voice. `tts_hi` reports `LIVE_CHECK_REQUIRED`.
- Non-commercial voices are listed but unselectable, and never downloaded, unless the worker
  runs with `NEXUS_VOICE_ALLOW_NONCOMMERCIAL_MODELS=true` (default `false`). While the gate is
  false the dashboard does not show them at all; the catalogue comes from the backend, which
  gets it from the worker (`/v1/voices`), and nothing is hardcoded in the UI.
- **User-supplied voice:** put `user_voices.json` in the model directory, with per voice
  `language` (`en`/`hi`), `license`, `commercial`, and `files` (`size`, `sha256`). It is never
  downloaded. `commercial` is the operator's claim and NEXUS does not verify it.
- **Piper licence boundary (facts only).** The worker's `piper-tts` dependency (1.8.0)
  declares `GPL-3.0-or-later` in its package metadata and ships `COPYING`; source:
  https://github.com/OHF-voice/piper1-gpl. Core NEXUS does not import Piper (no `piper`
  reference in `pyproject.toml` or `src/`); it talks to the worker over a loopback WebSocket.
  `voice/NOTICE.md` lists source and licence information. Restricted (non-commercial or
  unverified) models are opt-in and absent from the default setup and the default UI. This
  document draws no legal conclusion about how these pieces combine.
- **Windows voices.** With `NEXUS_VOICE_WINDOWS_TTS=1` (default on Windows) the worker lists
  voices Windows already has installed, offline, with no cloud call. Two separate Windows
  voice stores exist and the worker reads both:
  - **SAPI** (`System.Speech`, ids `win:`): the classic desktop voices, for example
    Microsoft David and Zira.
  - **OneCore / WinRT** (`Windows.Media.SpeechSynthesis`, ids `winrt:`): the voices behind
    Settings > Time & language > Speech and the Windows language features. They live in the
    `Speech_OneCore` registry hive and are **invisible to System.Speech**, so a voice you can
    hear in Windows Settings may be missing from a SAPI-only check.

  They are never a default, never downloaded or installed by NEXUS, and used only when
  chosen explicitly. Microsoft's terms for them apply; NEXUS does not verify commercial-use
  rights.
- Whisper output and TTS audio licences are separate from code licences; attribution strings
  live in `voice/src/nexus_voice/manifest.json`.

## Hindi speech on Windows

Windows does not ship a Hindi voice by default, and NEXUS never installs one. While no
`hi-IN` voice is installed, `tts_hi` stays `LIVE_CHECK_REQUIRED`, Hindi replies are text
only, and bilingual spoken output has **not** passed. English voice acceptance is
unaffected.

Install (administrator, needs internet; the language feature is a Windows Feature on
Demand):

1. Settings > Time & language > Language & region > Add a language > Hindi (India). In the
   optional features list keep **Text-to-speech** (and **Speech recognition** if wanted)
   ticked, then install. Or, in an elevated PowerShell:
   ```
   Get-WindowsCapability -Online -Name "Language.*hi-IN*"          # State should read Installed afterwards
   Add-WindowsCapability -Online -Name "Language.Basic~~~hi-IN~0.0.1.0"
   Add-WindowsCapability -Online -Name "Language.TextToSpeech~~~hi-IN~0.0.1.0"
   ```
   (`Language.TextToSpeech` depends on `Language.Basic`. Microsoft's Hindi voices are
   Hemant and Kalpana; the "natural" Prabhat and Neerja voices are added under Settings >
   Time & language > Speech > Manage voices where the OS offers them.)
2. Sign out and in, or reboot, if Windows asks for it.
3. Verify the OS sees it (OneCore, not System.Speech):
   ```
   [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime] | Out-Null
   [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object Language -like "hi*" | Select-Object DisplayName, Language
   ```
4. Restart the worker, then `nexus-voice voices` should list a `winrt:` voice with
   language `hi`, and `nexus doctor --voice` turns `tts_hi` to `PASS`.

Alternative: a Piper voice you are licensed to use, supplied through `user_voices.json`.

## Running the acceptance stack (Windows)

```
./scripts/start-local-voice.ps1 -HermesModel <model-id> -SecretRef <ref> -CompanyId <guid>
./scripts/stop-local-voice.ps1
```

`start-local-voice.ps1` starts Redis (reusing one that answers, otherwise a container it
labels and owns), the worker, the backend and the dashboard, then runs `nexus doctor
--voice --company <guid>`. OmniRoute must already be running; it is only probed, never
started, stopped or sent a credential.

- **Isolated database (default).** The backend runs on a private copy of the SQLite database
  named by the primary checkout's `.env`, made with SQLite's online backup API from a
  read-only connection, so the primary file is never written and an active database is
  copied consistently. The copy lives in the launcher's private temp directory. Encrypted
  rows are copied as they are, so the existing `SECRET_KEY` still resolves them; the launcher
  reads, decrypts, prints and hashes no secret and reports only whether the ref resolves.
  It hashes the primary file before and after and reports if it changed.
- **Migration of the copy only.** `scripts/prepare_acceptance.py migrate` runs `alembic
  upgrade head` with `DATABASE_URL` set to the copy, after checking there is exactly one
  head, then verifies `agents.is_ceo` and the Organization Snapshot tables. It refuses to run
  if the target resolves to the source file, and the primary database and `.env` are never
  migrated or edited. A failed migration stops startup and runs the normal cleanup. Several
  older revisions now skip objects that a `create_all`-built database already has, so a
  database whose schema drifted from its recorded revision still reaches head.
- **CEO designation (`-CeoAgentId <guid>`, isolated mode only).** The launcher never picks a
  CEO. Without the parameter, and with no CEO in the copy, it lists the eligible agents (ID,
  name and role only), reports `LIVE_CHECK_REQUIRED`, cleans up and exits with code 3 before
  starting any service; rerun with `-CeoAgentId <id>`. With it, the agent must belong to the
  company and is appointed through the application's own CEO service under an explicit
  acceptance admin principal (audited as `acceptance-admin@acceptance.invalid`), so the
  hierarchy and uniqueness rules apply. The designation exists only in the disposable copy.
  If the copy already has a different CEO, the launcher stops unless `-ReplaceCeo` is given.
  `-CeoAgentId` is rejected with `-UseDevDatabase`.
- **Organization Snapshot.** After the appointment the launcher generates (or refreshes) the
  snapshot through its service, waits for a successful version and checks that it is fresh
  and that the stored payload hash matches, before the doctor runs for the company. With
  `-EvidenceFile` the preparation report is saved next to the doctor JSON as
  `<file>.prep.json`.
- **`-UseDevDatabase`** runs on the primary database instead. It prints a warning and
  requires typing `USE DEV DATABASE`. Acceptance activity then writes to that database.
- **Secrets.** The worker secret is random per run and exists only in the environment of the
  processes started. The database URL, `SECRET_KEY` and secret values are never printed or
  put in state files.
- **Ownership and cleanup.** Every process is recorded with its PID and start time, the
  Redis container with its ID and a per-run label, the database copy with the run that made
  it. `stop-local-voice.ps1` acts only on records that still match, deletes only the
  launcher's own files, never touches an existing Redis, OmniRoute or unrelated containers or
  processes, and is safe to run repeatedly. Failure and Ctrl+C run the same cleanup. A second
  start while one is recorded refuses. The container is removed only after `docker ps
  --filter id=<recorded id> --filter label=nexus.local-voice=<run>` returns exactly that full
  ID and its name and image match what the launcher created (`docker inspect -f` with a
  quoted label key is not used: Windows PowerShell 5.1 drops the inner quotes). If Docker
  cannot be asked, the record is kept so a later run can finish the job.
- **Hindi.** If `tts_hi` is not `PASS` the launcher says which voice is missing and pauses
  before manual acceptance (`-NoPause` skips the pause).

## Shared state

Tickets, rate limits and revocation live in Redis (`nexus.voice.shared_state`), so any number
of backend workers agree:

- **Ticket:** `SET NX` with the ticket TTL keyed by tenant and jti, so exactly one worker
  redeems it; a second redemption fails atomically. A consumed ticket is never reusable.
- **Rate limits:** per-user and per-company fixed one-minute windows for sessions and
  utterances, shared across workers. Rejected attempts still count.
- **Revocation:** `DELETE /api/v1/voice/sessions/{id}` marks a session revoked; every worker's
  socket closes with `SESSION_REVOKED`.
- **Fail closed:** if Redis is unreachable the gateway refuses with `SHARED_STATE_UNAVAILABLE`.
  The in-process store is only allowed with `VOICE_ALLOW_LOCAL_STATE=true` (development).

## `nexus doctor --voice`

Read-only. It never opens a microphone, calls a paid model, creates a chat turn, invokes a
CEO tool, downloads a model or prints a secret.

```
nexus doctor --voice [--json] [--company <uuid>]
```

Each check is `PASS`, `FAIL`, `DEGRADED` or `LIVE_CHECK_REQUIRED`; overall status is the worst
one, and the exit code is 1 only on `FAIL`. Checks: browser microphone (always
`LIVE_CHECK_REQUIRED`, only a browser can test it), FFmpeg, worker Python 3.11, GPU and VRAM,
CTranslate2 CUDA, selected STT device, STT model hashes, VAD, English and Hindi TTS, worker
secret (configured or not, never its value), worker reachability and protocol, Redis, and,
with `--company`, CEO designation, organization snapshot and OmniRoute reachability
(unauthenticated request, no key sent). It also reports Hermes-native tool readiness.

## Browser microphone check

The voice panel has a local **Test microphone** button. Nothing opens the microphone until it
is pressed (or until **Start voice**). It shows the permission state, lists input devices
only once permission is granted, remembers the chosen device in this browser only, and shows
an input level, the AudioContext sample rate, AudioWorklet status and whether frames flow.
The test sends no audio to NEXUS. Denied, no-device and busy microphones each have their own
message and a **Type instead** fallback. Device labels and IDs never leave the browser.

## Connection recovery

- Every connect creates a fresh session and ticket; a ticket is never reused.
- After an abnormal drop or a transient error (`WORKER_UNAVAILABLE`,
  `SHARED_STATE_UNAVAILABLE`, `INTERNAL`) the panel retries up to 4 times at 1, 2, 4 and 8 s.
  Then it stops and shows **Retry**.
- Reconnecting never opens the microphone unless hands-free is on; otherwise the next
  push-to-talk press opens it.
- Nothing is replayed: no audio, transcripts, turns or tool calls.
- `CEO_CHANGED`, `SESSION_REVOKED`, `BAD_PROTOCOL` and disabled voice never retry. A session
  whose CEO differs from the open chat is refused, so a replaced CEO is never spoken to as
  the former one.
- Ending voice revokes the session server-side.

## Protocol

Browser → NEXUS: first message is JSON `{"type":"hello","ticket":…,"protocol":1}`.
Audio up is binary: `!BBHI` header (version, kind=1, reserved, seq) + 16 kHz mono s16le PCM,
at most 8192 bytes per frame, sequence starting at 0. Malformed, oversized or out-of-order
frames close the session. Audio down is binary: `!BBHII` (version, kind=3, flags, seq,
sample_rate) + s16le PCM. There is no JSON or base64 audio.

Events (JSON): `ready listening speech_started speech_ended transcribing partial transcript
thinking text_delta speaking interrupted completed notice error`. Controls: `config`,
`ptt_start`, `ptt_end`, `stop`, `ping`. `notice` is non-fatal (for example `NO_VOICE`).

Close and error codes: `CEO_CHANGED SESSION_REVOKED SESSION_EXPIRED BAD_TICKET BAD_PROTOCOL
WORKER_UNAVAILABLE SHARED_STATE_UNAVAILABLE INTERNAL IDLE_TIMEOUT RATE_LIMITED BAD_FRAME
BAD_CONTROL STT_ERROR TURN_* TTS_ERROR`.

## Security and privacy

- The session is minted server-side (`POST /api/v1/voice/sessions`) from the authenticated
  person. Company, CEO, chat session and expiry come from the server; the browser only picks
  a language mode and voices. A replaced or removed CEO ends the session.
- The ticket is a 30 s single-use JWT, redeemed once in shared state. The WebSocket re-checks
  the principal, company and CEO.
- The worker binds `127.0.0.1`, accepts only short-lived (≤120 s) single-use HS256 tokens
  for `stt` or `tts`, and knows no company, user or CEO. It has no DB or tool access.
- Raw audio is memory-only: never written to disk, audit or logs. The transcript is stored
  as the normal user message with safe metadata (language, durations, model names).
  Spoken secrets are redacted by the same rules as typed text. No cloud fallback.
- Partial transcripts are off by default (`NEXUS_VOICE_PARTIALS=1` enables them). They are
  UI-only. STT work is serialised through one scheduler, so a partial never runs
  concurrently with a final on the model. Empty or noise utterances create no message.
- Only the CEO's visible reply text is spoken; never tool arguments or hidden context.
- Barge-in stops playback at once. The durable turn is cancelled only when a new non-empty
  utterance arrives or Stop is pressed. An uncertain tool call is never replayed.

## Benchmark (this machine)

RTX 3050 Laptop, 6144 MiB, CUDA, CTranslate2 int8_float16. `python voice/scripts/bench.py all`,
one fresh process per candidate, median of 3 warm runs. Fixtures are synthetic speech, not
recordings of people. **English fixtures use the public-domain ljspeech voice and are
committed. Hindi and mixed audio come from a non-commercial voice, so they are git-ignored and
their accuracy is indicative only** (one utterance each; not a statistical result).

| Candidate | Peak GPU (+MiB over idle) | Load cold / warm | en latency | hi latency | en WER | hi CER | mixed CER |
|-----------|---------------------------|------------------|-----------|-----------|--------|--------|-----------|
| medium, CUDA int8_float16 (default) | 1640 | 2.5 s / 2.3 s | 0.5–0.9 s | 1.6–1.9 s | 0.05 | 0.19 | 0.86 |
| large-v3-turbo, CUDA int8_float16 | 2056 | 2.5 s / 2.5 s | 0.4–1.0 s | 0.9–1.4 s | 0.05 | 0.08 | 0.55 |
| medium, CPU int8 (fallback) | 0 | 2.2 s / 2.3 s | 3.5–6.8 s | 6.3–9.3 s | 0.05 | 0.16 | 0.84 |

- The "peak" includes a second model copy loaded for the warm-load measurement, so it
  overstates a single model. Load times are with the OS file cache warm; a truly cold disk
  read was not measured.
- large-v3-turbo fits within 6 GB (about 2.7 GB used in total), and recognises Hindi better
  and faster. The default stays `faster-whisper-medium`: it is the pinned, official
  conversion already in the manifest. large-v3-turbo was tested from
  `deepdml/faster-whisper-large-v3-turbo-ct2` @ `4df90f75…` (MIT, community conversion,
  `model.bin` SHA-256 `e76620f8…`) and is **not** in the manifest. There is no authoritative
  CTranslate2 build of large-v3-turbo: `Systran/faster-whisper-large-v3-turbo` does not exist,
  and `openai/whisper-large-v3-turbo` is in Transformers format. A community conversion is not
  accepted as a production model, so no "Higher Hindi accuracy" profile is offered. Revisit if
  Systran or OpenAI publish a CT2 build; it then needs a pinned revision and SHA-256.
- Hinglish (mixed) accuracy is poor for both models on these fixtures, partly because the
  synthetic voice reads English words in a Hindi accent. Treat real-speaker Hinglish as
  `LIVE_CHECK_REQUIRED`.
- The CPU int8 fallback works but is 4-8x slower; it is a fallback, not a target.

## Limitations

- No commercial Hindi voice ships: Hindi replies are text-only until an operator supplies one
  or installs a Windows Hindi voice. This machine has only en-US Windows voices.
- Hinglish recognition is weak (see the benchmark). Real-speaker accuracy is unmeasured.
- The dev-auth fallback principal (no user id) is not supported.
- Mixed-script routing is by script (Devanagari → Hindi voice, Latin → English voice);
  romanised Hindi is spoken by the English voice.
- Rate limits are fixed one-minute windows, so a burst at a window edge can reach 2x the limit.
- Real-microphone acceptance is a manual step (below), not done by the automated tests.

## Design provenance

JARVIS-OS-V.2 (MIT, commit `5fca0ac3…`) was read as a design reference only: separate voice
worker, push-to-talk, and a state machine for the UI. No code was copied; everything here is
a clean reimplementation against NEXUS's own gateway, tenancy and governed-tool paths.

## Manual acceptance

Not passed until a person does this on a real microphone.

1. `cd voice && uv run nexus-voice setup` once, then run `./scripts/start-local-voice.ps1` (above). It brings up Redis, the worker, the backend and the dashboard on an isolated database copy and runs the doctor.
2. The first run stops with `LIVE_CHECK_REQUIRED` and the eligible agents until you choose one; rerun with `-CeoAgentId <id>`. Expect no `FAIL` from `nexus doctor --voice --company <uuid>`; `browser_microphone` stays `LIVE_CHECK_REQUIRED`, and so does `tts_hi` until the Hindi voice is installed.
3. Open the CEO's chat and the voice panel. Nothing should ask for the microphone yet.
4. Press **Test microphone**, allow it, speak: the level moves, sample rate and "AudioWorklet loaded" and "frames flowing" show. Stop the test. Check the network tab: no audio was sent.
5. Choose a device, reload: the choice is remembered. Unplug it: a clear no-device message. Deny permission in a fresh profile: a denied message and *Type instead*.
6. Press **Start voice**. Hold **Hold to talk** (also try Space and Enter), say an English request, release: transcript, CEO answer, and you hear it.
7. Repeat in Hindi (reply is text only) and Hinglish. Check the detected language and the Auto/Hindi/English/Mixed selector.
8. While the CEO speaks, hold to talk again: speech stops. Press **Stop** mid-answer: the turn is cancelled.
9. Stop the worker: the panel shows "Reconnecting (attempt n of 4)", then Retry. Restart it and press Retry (or wait): a fresh session starts and the microphone stays closed until you press to talk.
10. Designate another CEO while a session is open: the session ends with a CEO-changed message and does not reconnect.
11. Confirm the transcript is in the chat history, no audio files exist, and the status line only announces state changes (test with a screen reader if you can, and with reduced motion on).
