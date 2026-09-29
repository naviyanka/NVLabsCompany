"""Loopback voice worker: streaming STT and TTS over WebSocket.

Audio in is 16 kHz mono s16le PCM; audio out is s16le PCM at 22.05 kHz. The worker
never sees a company, user or CEO: only audio, text and a signed, single-use token.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from nexus_voice import audio
from nexus_voice.config import Settings
from nexus_voice.tokens import TokenError, TokenVerifier
from nexus_voice.vad import SileroModel, UtteranceDetector

PROTOCOL = 1
MODES = {"auto", "hi", "en", "mixed"}
MAX_TTS_CHARS = 2000
PARTIAL_EVERY_MS = 1500


def create_app(
    settings: Settings, transcriber: Any = None, synthesizer: Any = None, vad_model: Any = None
) -> FastAPI:
    """``transcriber``, ``synthesizer`` and ``vad_model`` (a factory) are injectable for tests."""
    app = FastAPI(title="nexus-voice", docs_url=None, redoc_url=None, openapi_url=None)
    verifier = TokenVerifier(settings.secret)
    lock = asyncio.Lock()  # one model job at a time
    state: dict[str, Any] = {"stt": transcriber, "tts": synthesizer}

    def stt():
        if state["stt"] is None:
            from nexus_voice.stt import Transcriber

            state["stt"] = Transcriber(settings)
        return state["stt"]

    def tts():
        if state["tts"] is None:
            from nexus_voice.tts import Synthesizer

            state["tts"] = Synthesizer(settings)
        return state["tts"]

    async def authenticate(ws: WebSocket, scope: str) -> bool:
        header = ws.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else ""
        try:
            verifier.verify(token, scope)
        except TokenError:
            await ws.close(code=1008)
            return False
        await ws.accept()
        return True

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "protocol": PROTOCOL}

    @app.websocket("/v1/stt")
    async def stt_socket(ws: WebSocket) -> None:
        if not await authenticate(ws, "stt"):
            return
        engine = await asyncio.to_thread(stt)
        detector = UtteranceDetector(
            (vad_model or SileroModel)(),
            silence_ms=settings.silence_ms,
            max_utterance_s=settings.max_utterance_s,
        )
        mode = "auto"
        last_partial = 0
        partial: asyncio.Task | None = None
        await ws.send_json(
            {
                "type": "ready",
                "protocol": PROTOCOL,
                "device": engine.device,
                "max_frame_bytes": settings.max_frame_bytes,
            }
        )

        async def handle(events) -> None:
            nonlocal last_partial, partial
            for ev in events:
                if ev.kind == "speech_started":
                    last_partial = 0
                    await ws.send_json({"type": "speech_started"})
                elif ev.kind == "noise":
                    await ws.send_json({"type": "empty", "reason": "noise"})
                elif ev.kind == "utterance":
                    if partial:
                        partial.cancel()
                    await ws.send_json(
                        {"type": "speech_ended", "reason": ev.reason, "duration_ms": len(ev.audio) // 16}
                    )
                    await ws.send_json({"type": "transcribing"})
                    async with lock:
                        result = await asyncio.to_thread(engine.transcribe, ev.audio, mode)
                    if result["text"]:
                        await ws.send_json({"type": "transcript", "final": True, **result})
                    else:
                        await ws.send_json({"type": "empty", "reason": "no_speech"})

        async def send_partial(snapshot) -> None:
            if lock.locked():  # never queue behind a final transcription
                return
            async with lock:
                result = await asyncio.to_thread(engine.transcribe, snapshot, mode, partial=True)
            if result["text"]:
                await ws.send_json({"type": "partial", "final": False, "text": result["text"]})

        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes") is not None:
                    data = msg["bytes"]
                    if len(data) > settings.max_frame_bytes or len(data) % 2:
                        await ws.send_json({"type": "error", "code": "BAD_FRAME"})
                        await ws.close(code=1003)
                        return
                    await handle(detector.feed(audio.pcm_to_float(data)))
                    if (
                        settings.partials
                        and detector.speaking
                        and (partial is None or partial.done())
                        and detector.buffered_ms - last_partial >= PARTIAL_EVERY_MS
                    ):
                        last_partial = detector.buffered_ms
                        partial = asyncio.create_task(send_partial(detector.snapshot()))
                elif msg.get("text") is not None:
                    try:
                        ctl = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        ctl = {}
                    kind = ctl.get("type") if isinstance(ctl, dict) else None
                    if kind == "config" and ctl.get("mode") in MODES:
                        mode = ctl["mode"]
                    elif kind == "flush":
                        await handle(detector.flush())
                    else:
                        await ws.send_json({"type": "error", "code": "BAD_CONTROL"})
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            if partial:
                partial.cancel()

    @app.websocket("/v1/tts")
    async def tts_socket(ws: WebSocket) -> None:
        if not await authenticate(ws, "tts"):
            return
        synth = await asyncio.to_thread(tts)
        await ws.send_json({"type": "ready", "protocol": PROTOCOL, "sample_rate": 22050, "format": "s16le"})
        cancel = threading.Event()
        jobs: asyncio.Queue = asyncio.Queue(maxsize=8)

        async def reader() -> None:
            try:
                while True:
                    try:
                        ctl = json.loads(await ws.receive_text())
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(ctl, dict):
                        continue
                    if ctl.get("type") == "cancel":
                        cancel.set()
                        while not jobs.empty():
                            jobs.get_nowait()
                    elif ctl.get("type") == "speak":
                        await jobs.put(ctl)
            except (WebSocketDisconnect, RuntimeError):
                cancel.set()
                await jobs.put(None)

        read_task = asyncio.create_task(reader())
        try:
            while True:
                job = await jobs.get()
                if job is None:
                    return
                cancel.clear()
                text = str(job.get("text", ""))[:MAX_TTS_CHARS]
                voices = job.get("voices") if isinstance(job.get("voices"), dict) else {}
                started = time.perf_counter()
                gen = synth.synthesize(text, voices)
                try:
                    while not cancel.is_set():
                        chunk = await asyncio.to_thread(next, gen, None)
                        if chunk is None:
                            break
                        await ws.send_bytes(chunk)
                except LookupError as exc:
                    await ws.send_json(
                        {"type": "error", "id": job.get("id"), "code": "NO_VOICE", "message": str(exc)}
                    )
                    continue
                await ws.send_json(
                    {
                        "type": "cancelled" if cancel.is_set() else "done",
                        "id": job.get("id"),
                        "tts_ms": int((time.perf_counter() - started) * 1000),
                    }
                )
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            cancel.set()
            read_task.cancel()

    return app


def run(settings: Settings) -> None:
    import uvicorn

    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")
