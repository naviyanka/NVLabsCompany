# Azure Speech STT/TTS provider foundation

ADR 0006, PR 3. Code: `src/nexus/voice/provider_types.py` (neutral contracts) and
`src/nexus/voice/azure_speech.py` (Azure adapter). It is **off by default** and has no caller yet:
no gateway, dashboard, channel, tool, memory, approval or database code uses it. Browser/gateway wiring
belongs to later PRs.

## What it is

A transport only. Speech-to-text turns 16 kHz mono 16-bit PCM into transcripts. Text-to-speech turns
governed text into 24 kHz mono 16-bit PCM. Nothing a speech provider returns authorizes an action, and the
provider cannot reach tools, memory, approvals or the database (a test asserts the package imports none of
them). There is no fallback to another speech provider or to a key.

### Neutral contracts (`provider_types.py`)

No Azure SDK type crosses this boundary.

- STT session: `send_audio`, `finish`, `cancel`, `events`, `aclose`. Events: `Ready`, `SpeechStart`,
  `Partial`, `Final`, `NoMatch`, `Usage`, `Error`.
- TTS session: `write_text`, `end_text`, `cancel`, `events`, `aclose`. Events: `AudioChunk`, `Boundary`
  (reserved; Azure does not emit it yet), `Usage`, `Done`, `Error`.
- Every event carries the `generation` and `request_id` of its session, so a consumer can drop late output
  after Stop or barge-in. `AudioChunk` names its sample rate and encoding.
- `cancel()` is idempotent and never blocks. Cleanup runs in the background and `aclose()` awaits it.
- `repr` of an event hides audio bytes and transcript text. Errors carry stable `CODE: message` strings and
  never audio, tokens or credentials. An unknown event type fails closed (`check_event`).
- `SessionUsage` aggregates `stt.audio_ms` and `tts.characters` per voice session. PR 3 defines and tests
  the events and aggregation only. It adds no migration and settles nothing in a ledger; a gateway PR does that.

## Configuration (operator settings only)

Nothing here comes from agent configuration. Missing or invalid values fail closed with a stable reason
(`AZURE_SPEECH_<REASON>`).

| Setting | Meaning |
|---|---|
| `AZURE_SPEECH_ENABLED` | Gate. Default `false`. |
| `AZURE_SPEECH_ENDPOINT` | `https://<custom-subdomain>.cognitiveservices.azure.com`. https only, port 443, no path, userinfo, query or fragment. Regional shared hosts are rejected, and so is anything failing the existing SSRF check (`guard_url`). |
| `AZURE_SPEECH_REGION` | `centralindia` or `eastus2`. South India is not listed because it does not support speech processing. |
| `AZURE_SPEECH_VOICE_HI` | `hi-IN-SwaraNeural` (default) or `hi-IN-MadhurNeural`. |
| `AZURE_SPEECH_VOICE_EN` | `en-IN-NeerjaNeural` (default) or `en-IN-PrabhatNeural`. |
| `AZURE_SPEECH_CONNECT_TIMEOUT_SECONDS` | 0 < t <= 30. Default 3. |
| `AZURE_SPEECH_TTS_FIRST_AUDIO_TIMEOUT_SECONDS` | 0 < t <= 30. Default 4. |
| `AZURE_SPEECH_STT_FINAL_TIMEOUT_SECONDS` | 0 < t <= 60. Default 5. |

There is no key, scope, fallback or Hinglish setting. Zero, negative, NaN and infinite timeouts are rejected.

## Entra authentication

The adapter uses Entra only. The Speech resource needs a custom subdomain, and local (key) authentication
should be disabled on it. The role is Cognitive Services Speech User.

The scope is derived in code and is not configurable: `https://cognitiveservices.azure.com/.default`. The
Speech SDK itself requests exactly that scope from a `token_credential`. `_ScopedCredential` wraps one cached
`DefaultAzureCredential`, refuses any other scope (`AZURE_SPEECH_SCOPE_REJECTED`), forwards no extra
arguments, stores no token, and maps any failure to a sanitized `AZURE_SPEECH_AUTH_FAILED`. There is no second
scope, key path or runtime probing. The scope was validated live for recognition and synthesis (see "Live acceptance").

## Language modes

| Mode | Behavior |
|---|---|
| `en` | Recognizes `en-IN`. |
| `hi` | Recognizes `hi-IN` only. Urdu (`ur-IN`) is never a candidate, so explicit Hindi cannot be relabelled as Urdu. |
| `auto` | At-start language identification over the fixed allow-list `[en-IN, hi-IN]`. |
| `hinglish` | Recognized but gated: `open` raises `HINGLISH_UNVERIFIED`. Disabled and not configurable. |
| anything else | `VOICE_MODE_UNKNOWN` (fails closed). |

A `Final` keeps the selected mode, the requested locales and the detected locale as separate fields. Explicit
modes never report a detected locale. In `auto`, a detected locale outside the allow-list becomes unknown
(`detected_locale=None`, `notice=VOICE_LANGUAGE_UNRECOGNIZED`). Nothing here claims intra-sentence
code-switching.

## Synthesis

- One request per sentence, using the SDK's streaming audio callbacks. Output is raw 24 kHz 16-bit mono PCM.
- The voice is chosen by script: Devanagari uses the Hindi voice, Latin letters or digits use the English
  voice. Any other script, or a mix with another script, returns a non-fatal `VOICE_SCRIPT_UNSUPPORTED` notice
  and no synthesis. Urdu or other unsupported script is never sent to an incompatible voice.
- SSML is generated server-side from escaped governed text and an allow-listed voice; text cannot add tags.
  Control characters that are invalid in XML are stripped. A sentence over 2000 characters is a non-fatal
  `VOICE_TEXT_TOO_LONG` notice.
- HD voices and the v2 text-stream endpoint are deferred.
- Tool-capable turns are silent until governed text is available. This PR adds no acknowledgement phrase.

## Timeouts, retries and cancellation

- Timeouts: connect 3 s, first audio 4 s, STT final after `finish` 5 s (operator-tunable within the ranges
  above).
- Retries are narrow. One connect retry before audio, only for a transient code (timeout, connection failure,
  service unavailable). One TTS sentence retry only if no audio was emitted for that sentence. Nothing is
  retried after audio was sent or returned. HTTP 429 maps to `AZURE_SPEECH_RATE_LIMITED` and is never retried.
- The SDK calls back on its own threads. Each callback is bridged to the event loop with
  `call_soon_threadsafe` and dropped if the session was cancelled or closed.
- Each session owns one single-worker executor and its asyncio tasks. `cancel()` clears queued output, cancels
  tasks and schedules cleanup (stop recognition or synthesis, close the push stream, shut the executor down).
  `aclose()` awaits it for at most 5 s. Tests assert no task or `azure-speech` thread survives.
- Event queues are bounded. Partial transcripts drop oldest first. If a consumer stops draining and nothing
  droppable remains, the session fails with `AZURE_SPEECH_BACKPRESSURE` rather than growing.
- Known ceiling: a late callback from a stopped TTS attempt could in principle be attributed to the next
  attempt of the same sentence. TTS pre-connect is deferred.

## Error codes

Configuration: `AZURE_SPEECH_DISABLED`, `_ENDPOINT_MISSING`, `_ENDPOINT_INVALID`, `_REGION_MISSING`,
`_REGION_INVALID`, `_SDK_MISSING`, `_IDENTITY_SDK_MISSING`, `_TIMEOUT_INVALID`, `_VOICE_INVALID`.
Runtime: `_AUTH_FAILED`, `_FORBIDDEN`, `_RATE_LIMITED`, `_BAD_REQUEST`, `_CONNECTION_FAILED`, `_TIMEOUT`,
`_UNAVAILABLE`, `_SERVICE_ERROR`, `_SCOPE_REJECTED`, `_BACKPRESSURE`. Messages are fixed strings. SDK error
details are never copied into an error, a log line or an event.

## Doctor / status

`azure_speech.status()` (and `provider.status()`) reports the enabled flag, SDK and identity-SDK presence,
endpoint validity and shape, region, auth mode, derived scope, selected voices, locale mapping, timeout
validity, the Hinglish gate and a stable unavailable reason. It makes no network request and never shows a
token, key or credential. It is not yet surfaced through `ceo_service.status`, which is deliberately untouched.

## Dependency: the `speech` extra

`pip install ".[speech]"` adds `azure-cognitiveservices-speech==1.52.0`.

- **License.** Proprietary Microsoft license (not an OSI license). Review it before redistributing an image.
- **Native wheels only.** The package ships `py3-none` wheels with native libraries for manylinux
  (x86_64, aarch64), macOS and Windows, and no source distribution. It does not install on Alpine/musl.
  The repository's images use Debian-based `python:3.12` images, which work.
- **Python.** CI and the production images use Python 3.12 and run the SDK construction smoke
  (`tests/test_voice_provider_contract.py`). Do not assume newer interpreters (for example the local 3.14)
  have a compatible wheel.
- **Not in the default image.** `Dockerfile.prod` installs `.[otel]` and is unchanged. A Speech-enabled image
  installs `.[otel,speech]`. Without the extra the provider reports `AZURE_SPEECH_SDK_MISSING`.
  Microsoft documents `libasound2` and `ca-certificates` as Linux prerequisites of the SDK; `python:3.12-slim`
  does not ship `libasound2`, so such an image must `apt-get install` it. This PR does not build a
  Speech-enabled image, so that image path is documented and unverified here (CI runs on `ubuntu-latest`).
- `azure-identity` is already a base dependency.

## Tests

Fakes only, no network (`tests/voice_fakes.py`): `tests/test_azure_speech_provider.py` (configuration,
scope, STT/TTS sessions, cancel, retries, timeouts, leaks) and `tests/test_voice_provider_contract.py`
(contract parity of the fake and Azure providers, plus an offline real-SDK construction smoke that is skipped
when the extra is not installed).

## Live acceptance

One live run on 2026-10-02 (region `centralindia`, S0 pay-as-you-go, SDK 1.52.0, Entra only, one request of the
approved scope) made 41 provider calls: 20 TTS (including one cancellation) and 21 STT (19 explicit-language
round trips and two Auto). All succeeded with no retry and no error. Sanitized results are in
`docs/testing/evidence/azure-speech-provider/ACCEPTANCE.md`. They settle the open questions this document
carried:

- The custom-subdomain endpoint without a trailing slash works for both STT and TTS.
- The service accepts headerless 16 kHz mono 16-bit PCM as STT input.
- The Entra scope above works for the data plane (recognition and synthesis), not only for the voices list.
- Explicit Hindi returned `hi-IN` transcripts that matched the synthetic text, and Auto identified `en-IN` and
  `hi-IN` correctly. Latency was inside the default timeouts (STT final after `finish`: p50 1.35 s, max 2.0 s;
  TTS first audio: p50 0.36 s, max 2.55 s on the first, cold request).
- Cancellation stopped at the first chunk with no late audio and no replacement synthesis.

Not shown by that run: Linux (`libasound2` on `python:3.12-slim` is still unverified), credentials other than the
Azure CLI one, and the billed quantities (the estimated cost of about ₹3.4 is from usage events at pessimistic
rates, not from billing data).
