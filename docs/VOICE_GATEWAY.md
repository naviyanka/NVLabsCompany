# Local CEO Voice Gateway (v1)

Talk to the designated CEO in Hindi, English or Hinglish. Speech recognition and
synthesis run on this machine. No cloud speech provider is used or falls back.

```
browser ─ binary WS ─▶ NEXUS /api/v1/voice/ws ─ loopback WS ─▶ voice worker (STT / TTS)
                              │
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
uv run nexus-voice setup                 # downloads pinned, SHA-256-checked models
uv run nexus-voice diagnose              # GPU, CUDA, device, FFmpeg, models
NEXUS_VOICE_WORKER_SECRET=<32+ chars> uv run nexus-voice serve
```

Backend `.env`: `VOICE_ENABLED=true`, `VOICE_WORKER_SECRET=<same secret>`. Optional:
`VOICE_WORKER_URL` (loopback only), `VOICE_TICKET_TTL_SECONDS`, `VOICE_SESSION_TTL_SECONDS`,
`VOICE_MAX_UTTERANCE_SECONDS`, `VOICE_UTTERANCES_PER_MINUTE`, `VOICE_SESSIONS_PER_MINUTE`.
Models live in `%LOCALAPPDATA%\nexus-voice\models`, never in Git.

## Models

| Item | Choice | License |
|------|--------|---------|
| STT | `Systran/faster-whisper-medium` @ `08e178d4…` (CUDA int8_float16, CPU int8 fallback) | MIT |
| VAD | Silero VAD v6 (bundled with faster-whisper) | MIT |
| TTS en | `en_US-lessac-medium` | Blizzard 2013 Lessac licence |
| TTS en (alt) | `en_US-ryan-medium` | CC BY-NC-SA 4.0 |
| TTS hi | `hi_IN-pratham-medium`, `hi_IN-priyamvada-medium` | CC BY-NC-SA 4.0 (non-commercial) |

Voice IDs, sources, sample rates and SHA-256s are in `voice/src/nexus_voice/manifest.json`
(from the `rhasspy/piper-voices` catalog at commit `c10ece1a…`). **The Hindi voices are
non-commercial.** Check licences before any commercial use. The catalog gives no gender labels.

## Protocol

Browser → NEXUS: first message is JSON `{"type":"hello","ticket":…,"protocol":1}`.
Audio up is binary: `!BBHI` header (version, kind=1, reserved, seq) + 16 kHz mono s16le PCM,
at most 8192 bytes per frame, sequence starting at 0. Malformed, oversized or out-of-order
frames close the session. Audio down is binary: `!BBHII` (version, kind=3, flags, seq,
sample_rate) + s16le PCM. There is no JSON or base64 audio.

Events (JSON): `ready listening speech_started speech_ended transcribing partial transcript
thinking text_delta speaking interrupted completed error`. Controls: `config`, `ptt_start`,
`ptt_end`, `stop`, `ping`.

## Security and privacy

- The session is minted server-side (`POST /api/v1/voice/sessions`) from the authenticated
  person. Company, CEO, chat session and expiry come from the server; the browser only picks
  a language mode and voices. A replaced or removed CEO ends the session.
- The ticket is a 30 s single-use JWT. The WebSocket re-checks the principal, company and CEO.
- The worker binds `127.0.0.1`, accepts only short-lived (≤120 s) single-use HS256 tokens
  for `stt` or `tts`, and knows no company, user or CEO. It has no DB or tool access.
- Raw audio is memory-only: never written to disk, audit or logs. The transcript is stored
  as the normal user message with safe metadata (language, durations, model names).
  Spoken secrets are redacted by the same rules as typed text. No cloud fallback.
- Partial transcripts are UI-only. Empty or noise utterances create no message.
- Only the CEO's visible reply text is spoken; never tool arguments or hidden context.
- Barge-in stops playback at once. The durable turn is cancelled only when a new non-empty
  utterance arrives or Stop is pressed. An uncertain tool call is never replayed.

## Limitations

- Tickets, replay guards and rate limits are per process. Multi-process deployments need
  a shared store.
- The dev-auth fallback principal (no user id) is not supported.
- Hindi and Hinglish accuracy of Whisper *medium* is limited. Fixture transcripts of
  synthetic speech were phonetically degraded. Larger models may help but need more VRAM.
- Mixed-script routing is by script (Devanagari → Hindi voice, Latin → English voice);
  romanised Hindi is spoken by the English voice.
- Real-microphone acceptance is a manual step (below).

## Manual acceptance

1. `diagnose` shows CUDA (or a documented CPU fallback); start the worker and NEXUS with voice enabled.
2. Open the CEO's chat, click the mic icon, press **Start voice**, and allow the microphone.
3. Hold **Hold to talk**, say a short English request, release: a transcript appears, the CEO answers, you hear it.
4. Repeat in Hindi and in Hinglish. Check the detected language and the Auto/Hindi/English/Mixed selector.
5. While the CEO speaks, hold to talk again: speech stops at once. Press **Stop** mid-answer: the turn is cancelled.
6. Deny microphone permission in a fresh profile: an error and *Type instead* appear.
7. Confirm the transcript is in the chat history and that no audio files were created.
