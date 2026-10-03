# Azure Speech provider: live acceptance evidence

ADR 0006, PR 3. One live run on 2026-10-02 against a pay-as-you-go Azure Speech resource, driven by a
one-shot harness kept outside the repository. This file holds sanitized results only. It contains no tenant,
subscription, principal or resource identifiers, no endpoint hostname, no tokens or keys, no headers, no local
paths and no audio.

## Setup

| Item | Value |
|---|---|
| Region | `centralindia` |
| SKU | S0, pay-as-you-go only |
| Authentication | Entra (Azure CLI user credential). Local (key) authentication disabled on the resource. |
| Scope requested | `https://cognitiveservices.azure.com/.default`. Exactly one token request, one scope. |
| SDK | `azure-cognitiveservices-speech` 1.52.0, Python 3.12, Windows |
| Adapter retries | Disabled for the run (`adapter_retries_disabled: true`) |
| English voice, locale | `en-IN-NeerjaNeural`, `en-IN` |
| Hindi voice, locale | `hi-IN-SwaraNeural`, `hi-IN` |
| Input | Six fixed synthetic sentences (three English, three Hindi) and one fixed cancellation sentence. No personal audio and no company, agent, memory or tool data. |

The harness ran only after an offline fake acceptance of its control flow (33 tests: exact 41-call plan, no
hidden or retried call, each injected failure stops all later calls, caps, timeouts and exclusive-create
sentinel and result files).

## Call counts

| Operation | Count |
|---|---|
| TTS requests | 20 (10 English: 9 completed and 1 cancellation; 10 Hindi) |
| STT sessions | 21 (9 English explicit, 10 Hindi explicit, 1 English Auto, 1 Hindi Auto) |
| Total provider calls | 41, equal to the plan. SDK-level start counters matched the harness counters. |
| Token requests | 1 |
| Hinglish requests | 0 |
| Aborted | no |

## Results

- **Round trips.** All 21 STT sessions returned a final transcript equal to the synthetic sentence that was
  synthesized. Mean confidence was 0.974 (English, minimum 0.941) and 0.849 (Hindi, minimum 0.816).
- **Explicit Hindi.** All 10 explicit Hindi sessions kept `selected_mode=hi`, `requested_locales=[hi-IN]` and
  no detected locale. None was relabelled as Urdu.
- **Auto language identification** over the allow-list `[en-IN, hi-IN]`: the English clip was detected as
  `en-IN` and the Hindi clip as `hi-IN`.
- **Audio format.** Every synthesis returned 24 kHz 16-bit mono PCM of even length. Every complete clip was
  non-silent. The Speech service accepted headerless 16 kHz PCM as STT input.
- **Cancellation.** The English cancellation test cancelled on the first audio chunk (cancel call 0.015 ms).
  `aclose` took 64.6 ms. There were 0 audio chunks after cancel, 2,400 bytes were received before it, and no
  replacement synthesis started.
- **Errors.** None, on any of the 41 calls.
- **No leak.** The token was not found in the result or in 3 captured log records.

## Usage and estimated cost

| Measure | Value | Cap |
|---|---|---|
| Synthesized characters | 650 | 900 |
| STT audio (aggregated usage) | 61.458 s | 80 s |
| Estimated cost, actual usage | about ₹3.43 | ₹5 |
| Estimated cost, reserved | about ₹3.80 | ₹5 |

Cost is an estimate at pessimistic public rates ($16 per million TTS characters, $1 per audio hour, both
x1.25, ₹100 per USD). It is not a billed amount. The provider's `Usage` events were checked against the
harness counters (650 characters; audio seconds within rounding), but the service-side billed quantity was
not read back.

## Latency

Synthetic round trips only. The STT input was Azure-generated speech sent from a script, not microphone audio,
so these numbers say nothing about microphone accuracy or about end-to-end conversational latency (browser,
gateway, model and the whole turn). The samples are few, so p95 is the nearest-rank value and, at these sizes, equals
or sits next to the maximum. `n` is the sample size for each row, and all times are in milliseconds.

| Measure | n | p50 | p95 | max |
|---|---|---|---|---|
| TTS first audio, warm (completed requests after the first; excludes the cancellation request) | 18 | 360 | 468 | 468 |
| TTS first audio, cold first request (English) | 1 | 2,552 | | 2,552 |
| TTS first audio, cancellation request (first chunk, then cancelled) | 1 | 397 | | 397 |
| STT final after `finish`, explicit language | 19 | 1,353 | 1,802 | 1,802 |
| STT final after `finish`, Auto | 2 | 1,950 | not meaningful at n=2 | 2,016 |
| STT final after `finish`, all sessions | 21 | 1,364 | 1,884 | 2,016 |
| Token acquisition (cold, once) | 1 | 2,323 | | 2,323 |
| `aclose` after TTS | 20 | | | 109 |

By language (warm TTS, explicit STT): English TTS n=8, p50 360, p95 424; Hindi TTS n=10, p50 367, p95 468;
English STT n=9, p50 1,353, p95 1,802; Hindi STT n=10, p50 1,350, p95 1,478.

All were inside the adapter defaults (connect 3 s, first audio 4 s, STT final 5 s). The cold first English
request at 2.55 s is the closest to its 4 s limit. The STT audio was sent as fast as the script could write it,
not paced in real time, so "final after `finish`" is the tail wait after the last chunk, not a live-speech figure.

## What this run did not show

- A live Linux session. The run was on Windows. The Linux container smoke below covers loading and
  construction only, with no connection.
- `DefaultAzureCredential`. The harness used the Azure CLI credential, passed through the adapter's scoped
  credential wrapper. Managed identity and other chain members were not exercised.
- Billing. The billed character and audio quantities were not read from Azure cost data.
- Hinglish (gated, not requested), HD voices and the v2 text-stream endpoint (deferred), and any long-running or
  concurrent load.


## Linux container smoke (no network, no Azure call)

A separate offline follow-up, run after the live acceptance and not part of it. It made no Azure request and no
token request. Image: `python:3.12-slim` (Debian 13, glibc), SDK 1.52.0 installed with `--only-binary`, run with
`--network none` as a non-root user with a fake credential.

| Architecture | Native wheel | Smoke |
|---|---|---|
| linux/amd64 | `py3-none-manylinux1_x86_64` | pass (also run in CI as `speech-smoke`) |
| linux/arm64 | `py3-none-manylinux2014_aarch64` | pass once, locally, under QEMU emulation. Not run in CI. |

Both runs: only loopback present, Speech disabled by default, no token requested, only the `core` and `kws`
libraries loaded, no ALSA library loaded, no audio descriptor open, and no unresolved `ldd` dependency among the
loaded libraries. `ldd` does report unresolved libraries for two SDK extensions that were not loaded:
`extension.audio.sys` (`libasound.so.2`) and `extension.codec` (glib, GStreamer). No apt package was installed.
This does not show that a live Linux session works. See `docs/azure-speech-provider.md`.
