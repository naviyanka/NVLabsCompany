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

### Wheel audit (1.52.0)

Published wheels are all `py3-none` (no CPython ABI tag, so CPython 3.12 is covered) and there is no source
distribution:

| Platform | Wheel tag | Native wheel |
|---|---|---|
| Linux amd64 | `py3-none-manylinux1_x86_64` | yes |
| Linux arm64 | `py3-none-manylinux2014_aarch64` | yes |
| macOS x86_64 / arm64 | `macosx_10_14_x86_64` / `macosx_11_0_arm64` | yes |
| Windows amd64 / arm64 | `win_amd64` / `win_arm64` | yes |

Both Linux architectures were installed separately on `python:3.12-slim` (Debian 13, glibc) and each resolved its
own native wheel. There is no source build to fall back to, and the image installs with
`pip install --only-binary azure-cognitiveservices-speech`, so a future release that drops a platform fails the
build instead of attempting a silent build. The package does not install on Alpine/musl (no musllinux wheel).

- **License.** Proprietary Microsoft license (classifier `License :: Other/Proprietary License`, not an OSI
  license). The wheel ships `LICENSE.md`, `REDIST.txt` and `ThirdPartyNotices.md` under
  `licenses/licensefiles/speech/` in its dist-info. Review them before redistributing an image.
- **Native libraries and size.** About 7.6 MB: `core`, `extension.audio.sys`, `extension.codec`,
  `extension.kws`, `extension.kws.ort` and two `libpal_azure_c_shared` variants. `core` and the PAL libraries
  need only libc-family libraries, `libstdc++`, `libgcc_s` and `libuuid`, all present in `python:3.12-slim`.
- **`libasound2` is not needed for the server-side stream path.** `extension.audio.sys` needs `libasound.so.2`
  and `extension.codec` needs glib and GStreamer. Neither extension is loaded when the adapter feeds a push
  stream of headerless PCM and synthesizes with no audio output (`audio_config=None`). The Linux smoke below
  shows only `core` and `kws` loading, no ALSA library and no audio device. That is a statement about an
  offline construction path. A live Linux connection was not run, so it is unproven for a real session, and
  anything that uses a microphone, a speaker or a compressed audio format does need those libraries.
  Microsoft's general Linux prerequisites list `libasound2` and `ca-certificates`; `ca-certificates` is already
  in the slim image. The smoke image therefore installs no apt package. If a deployment hits an audio or codec
  load error, add the smallest package for the named library (`libasound2` for ALSA) through the smoke
  Dockerfile's `RUNTIME_APT` build argument and re-run the smoke.
- **Python.** CI and the images use Python 3.12. Do not assume newer interpreters (for example a local 3.14)
  have a compatible wheel.
- `azure-identity` is already a base dependency.

### Not in the default image

`Dockerfile.prod` installs `.[otel]` and is unchanged, so the normal multi-architecture image gate does not
involve the Speech SDK. Without the extra the provider reports `AZURE_SPEECH_SDK_MISSING`.

A Speech-enabled production image is a deployment decision and is not built here. To make one, change the
install line in a copy of `Dockerfile.prod` to
`pip install --no-cache-dir --only-binary azure-cognitiveservices-speech ".[otel,speech]"`, then build it for the
architecture you run. Verified architecture: **linux/amd64** (the CI smoke runs on it). linux/arm64 has a native
wheel and passed the same smoke once, locally, under QEMU emulation, but CI does not cover it, so multi-architecture
Speech support is not claimed. If the Speech wheel ever disappears for an architecture, `--only-binary` fails that
build with a clear pip error, and the Speech service should then run on amd64.

### Linux container smoke (offline)

`docker/speech-smoke/Dockerfile` installs the repo with the `speech` extra on `python:3.12-slim` (the build may use
the network) and `scripts/speech_container_smoke.py` runs in it with the network disabled:

```
docker build -f docker/speech-smoke/Dockerfile -t nexus-speech-smoke .
docker run --rm --network none nexus-speech-smoke
# arm64, on a host with QEMU: add --platform linux/arm64 to both commands
```

The smoke imports the SDK and `nexus.voice.azure_speech`, checks that `status()` reports Speech disabled by
default, and builds, without connecting, a `SpeechConfig` (fake endpoint, scoped fake credential), the 16 kHz mono
push stream and recognizers (explicit `hi-IN` and Auto), and a synthesizer with the raw 24 kHz PCM output format
and no audio output. It asserts that no token was requested, that only loopback exists, that no `AZURE_*`
variable and no `/dev/snd` is present, that no audio descriptor is open, that ALSA was not loaded, and that
`ldd` finds no unresolved dependency for any SDK library that actually loaded. It runs as `nobody`, and it fails
("network is not disabled") if `--network none` is omitted. GitHub Actions runs it as the `speech-smoke` job. It
makes no Azure call and holds no credential.

## Tests

Fakes only, no network (`tests/voice_fakes.py`): `tests/test_azure_speech_provider.py` (configuration,
scope, STT/TTS sessions, cancel, retries, timeouts, leaks) and `tests/test_voice_provider_contract.py`
(contract parity of the fake and Azure providers, plus an offline real-SDK construction smoke that is skipped
when the extra is not installed). The backend suite runs with and without the SDK installed.

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
  `hi-IN` correctly. Latency was inside the default timeouts. STT final after `finish` (explicit language, n=19): p50 1.35 s, p95
  1.80 s, max 1.80 s. TTS first audio, warm (n=18): p50 0.36 s, p95 0.47 s, max 0.47 s. The cold first TTS request
  (n=1) took 2.55 s. p95 here is nearest-rank on few samples, so it is close to the maximum. These are synthetic
  round trips of Azure-generated speech sent from a script: they do not represent microphone accuracy or
  end-to-end conversational latency.
- Cancellation stopped at the first chunk with no late audio and no replacement synthesis.

Not shown by that run: Linux (it ran on Windows; the offline Linux container smoke above covers loading and
construction only, not a live connection), credentials other than the Azure CLI one, and the billed quantities (the estimated cost of about ₹3.4 is from usage events at pessimistic
rates, not from billing data).
