"""One browser voice connection: audio in, durable CEO chat turn, spoken reply out.

The gateway holds no audio beyond the bounded frames in flight and writes none to
disk or logs. The only text that enters chat is the final, redacted transcript,
through the same ``create_turn`` path a typed message takes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from typing import Any

from fastapi import HTTPException, WebSocket

from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.voice import protocol, worker_client
from nexus.voice.chunker import SentenceChunker
from nexus.voice.shared_state import SharedStateUnavailableError, get_store
from nexus.voice.tokens import TicketError, VoiceSession, read_ticket

logger = logging.getLogger(__name__)

VOICE_ID = re.compile(r"^[a-z]{2}_[A-Z]{2}-[a-z0-9_]+-(x_low|low|medium|high)$")
STT_QUEUE = 64
HELLO_TIMEOUT = 10
HELLO_MAX_CHARS = 4096  # a signed ticket is a few hundred bytes
SAMPLE_RATE_OUT = 22_050


class SessionCloseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code, self.message = code, message


def valid_voice(v: object) -> bool:
    return isinstance(v, str) and bool(VOICE_ID.match(v))


class VoiceConnection:
    def __init__(self, ws: WebSocket, sess: VoiceSession, principal: Principal) -> None:
        self.ws, self.sess, self.principal = ws, sess, principal
        self.mode, self.voice_en, self.voice_hi = sess.mode, sess.voice_en, sess.voice_hi
        # Tests inject a fake worker connector on app.state.
        self.connect = getattr(ws.app.state, "voice_connect", None) or worker_client.connect
        self.stt: Any = None
        self.tts: Any = None
        self.tts_reader: asyncio.Task | None = None
        self.stt_queue: asyncio.Queue[bytes] = asyncio.Queue(STT_QUEUE)
        self.out_seq = 0
        self.generation = 0
        self.pending = 0
        self.speaking = False
        self.active_turn = None
        self.turn_task: asyncio.Task | None = None
        self.first_audio_at: float | None = None
        self.n = 0
        self.utterance_bytes = 0
        self.tasks: list[asyncio.Task] = []
        self.store = ws.app.state.voice_store  # set by serve() before construction
        self.closed = asyncio.Event()
        self.drained = asyncio.Event()  # set while no synthesis is outstanding
        self.drained.set()

    # --- output -----------------------------------------------------------

    async def emit(self, type_: str, **fields: Any) -> None:
        if self.closed.is_set():
            return
        with contextlib.suppress(RuntimeError):
            await self.ws.send_text(json.dumps({"type": type_, **fields}))

    async def fail(self, code: str, message: str) -> None:
        await self.emit("error", code=code, message=message)

    # --- lifecycle --------------------------------------------------------

    async def run(self) -> None:
        try:
            self.stt = await self.connect("stt", self.sess.id)
            ready = json.loads(await self.stt.recv())
            if ready.get("type") != "ready":
                raise worker_client.WorkerUnavailableError("bad worker greeting")
            await self.stt.send(json.dumps({"type": "config", "mode": self.mode}))
        except (worker_client.WorkerUnavailableError, OSError, ValueError):
            await self.fail("WORKER_UNAVAILABLE", "The local voice worker is not available")
            return
        await self.emit(
            "ready",
            protocol=protocol.VERSION,
            voice_session_id=self.sess.id,
            mode=self.mode,
            sample_rate_in=protocol.SAMPLE_RATE_IN,
            sample_rate_out=SAMPLE_RATE_OUT,
            max_frame_bytes=protocol.MAX_PAYLOAD,
            max_utterance_seconds=settings.voice_max_utterance_seconds,
            voices={"en": self.voice_en, "hi": self.voice_hi},
        )
        await self.emit("listening")
        self.tasks = [
            asyncio.create_task(t)
            for t in (self.uplink(), self.stt_send(), self.stt_read(), self.watch())
        ]
        try:
            done, _ = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in (t for t in done if not t.cancelled()):
                exc = t.exception()
                if isinstance(exc, SessionCloseError):
                    await self.fail(exc.code, exc.message)
                elif exc:
                    logger.warning("voice connection ended: %s", type(exc).__name__)
                    await self.fail("INTERNAL", "Voice connection failed")
        finally:
            await self.close()

    async def close(self) -> None:
        self.closed.set()
        for t in self.tasks + ([self.turn_task] if self.turn_task else []):
            if t is not asyncio.current_task():
                t.cancel()
        await self.drop_tts()
        if self.stt:
            with contextlib.suppress(Exception):
                await self.stt.close()

    # --- browser -> worker ------------------------------------------------

    async def uplink(self) -> None:
        expected = 0
        limit = (settings.voice_max_utterance_seconds + 2) * protocol.BYTES_PER_SECOND_IN
        while True:
            try:
                msg = await asyncio.wait_for(self.ws.receive(), settings.voice_idle_timeout_seconds)
            except TimeoutError:
                raise SessionCloseError("IDLE_TIMEOUT", "Voice session idle") from None
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                try:
                    pcm = protocol.parse_up(msg["bytes"], expected)
                except protocol.FrameError as exc:
                    raise SessionCloseError("BAD_FRAME", str(exc)) from None
                expected += 1
                self.utterance_bytes += len(pcm)
                if self.utterance_bytes > limit:
                    self.utterance_bytes = 0
                    await self.fail("UTTERANCE_TOO_LONG", "Utterance exceeded the maximum length")
                    await self.stt.send(json.dumps({"type": "flush"}))
                    continue
                try:
                    self.stt_queue.put_nowait(pcm)
                except asyncio.QueueFull:
                    raise SessionCloseError(
                        "BACKPRESSURE", "Audio arrived faster than it can be processed"
                    ) from None
            elif msg.get("text") is not None:
                await self.control(msg["text"])

    async def control(self, raw: str) -> None:
        try:
            ctl = json.loads(raw)
        except json.JSONDecodeError:
            raise SessionCloseError("BAD_CONTROL", "Malformed control message") from None
        kind = ctl.get("type") if isinstance(ctl, dict) else None
        if kind == "config":
            if ctl.get("mode") in protocol.MODES:
                self.mode = ctl["mode"]
                await self.stt.send(json.dumps({"type": "config", "mode": self.mode}))
            if valid_voice(ctl.get("voice_en")):
                self.voice_en = ctl["voice_en"]
            if valid_voice(ctl.get("voice_hi")):
                self.voice_hi = ctl["voice_hi"]
        elif kind == "ptt_start":
            await self.interrupt("user_speaking")
        elif kind == "ptt_end":
            await self.stt.send(json.dumps({"type": "flush"}))
        elif kind == "stop":
            await self.interrupt("stop", cancel_turn=True)
            await self.emit("listening")
        elif kind != "ping":
            raise SessionCloseError("BAD_CONTROL", "Unknown control message")

    async def stt_send(self) -> None:
        while True:
            await self.stt.send(await self.stt_queue.get())

    # --- worker -> browser ------------------------------------------------

    async def stt_read(self) -> None:
        async for raw in self.stt:
            ev = json.loads(raw)
            kind = ev.get("type")
            if kind == "speech_started":
                self.utterance_bytes = 0
                await self.interrupt("barge_in")
                await self.emit("speech_started")
            elif kind in ("speech_ended", "transcribing"):
                self.utterance_bytes = 0
                await self.emit(kind)
            elif kind == "partial":
                await self.emit("partial", text=str(ev.get("text", ""))[:2000])  # ephemeral only
            elif kind == "empty":
                self.utterance_bytes = 0
                await self.emit("listening")
            elif kind == "transcript" and ev.get("final") and str(ev.get("text", "")).strip():
                await self.on_transcript(ev)
            elif kind == "error":
                await self.fail("STT_ERROR", "Speech recognition failed")

    async def on_transcript(self, ev: dict[str, Any]) -> None:
        from nexus.services import ceo_service

        text, redacted = ceo_service.redact(str(ev["text"]).strip()[:4000])
        try:
            allowed = await self.store.allow("utterance", self.sess.company_id, self.sess.user_id)
        except SharedStateUnavailableError:
            await self.fail("SHARED_STATE_UNAVAILABLE", "Voice limits are unavailable; try again")
            await self.emit("listening")
            return
        if not allowed:
            await self.fail("RATE_LIMITED", "Too many voice messages; wait a moment")
            await self.emit("listening")
            return
        await self.emit(
            "transcript",
            text=text,
            final=True,
            language=ev.get("language"),
            language_probability=ev.get("language_probability"),
            redacted=redacted,
        )
        # A real utterance replaces the answer in progress: cancel it durably first.
        await self.interrupt("new_utterance", cancel_turn=True)
        self.n += 1
        meta = {
            "voice_session_id": self.sess.id,
            "language_mode": self.mode,
            "detected_language": ev.get("language"),
            "language_probability": ev.get("language_probability"),
            "audio_duration_ms": ev.get("duration_ms"),
            "stt_model": ev.get("model"),
            "stt_device": ev.get("device"),
            "stt_ms": ev.get("stt_ms"),
        }
        self.turn_task = asyncio.create_task(self.run_turn(text, meta, self.generation, self.n))

    # --- barge-in ---------------------------------------------------------

    async def drop_tts(self) -> None:
        link, self.tts = self.tts, None
        reader, self.tts_reader = self.tts_reader, None
        if reader:
            reader.cancel()
        if link:
            with contextlib.suppress(Exception):
                await link.close()

    async def interrupt(self, reason: str, cancel_turn: bool = False) -> None:
        """Stop speaking now. The durable turn is cancelled only when asked to."""
        started = time.perf_counter()
        active = bool(
            self.speaking or self.pending or (self.turn_task and not self.turn_task.done())
        )
        self.generation += 1
        self.pending, self.speaking = 0, False
        self.drained.set()
        if active:
            await self.emit("interrupted", reason=reason)
        await self.drop_tts()
        if (
            self.turn_task
            and not self.turn_task.done()
            and self.turn_task is not asyncio.current_task()
        ):
            self.turn_task.cancel()
        if cancel_turn:
            await self.cancel_durable(f"voice:{reason}")
        if active:
            logger.info("voice interrupt handled in %d ms", (time.perf_counter() - started) * 1000)

    async def cancel_durable(self, by: str) -> None:
        turn_id, self.active_turn = self.active_turn, None
        if turn_id is None:
            return
        from nexus.database import tenant_session
        from nexus.runtime import chat_turns

        try:
            async with tenant_session(self.sess.company_id) as db:
                await chat_turns.request_cancel(
                    db, self.sess.company_id, self.sess.chat_session_id, turn_id, cancelled_by=by
                )
                await db.commit()
        except HTTPException:
            pass  # already gone: nothing further to cancel

    # --- CEO turn ---------------------------------------------------------

    async def check_ceo(self, db: Any) -> Any:
        from nexus.services import ceo_service

        ceo = await ceo_service.current_ceo(db, self.sess.company_id)
        if ceo is None or ceo.id != self.sess.ceo_id:
            raise SessionCloseError(
                "CEO_CHANGED", "The company's CEO changed; start a new voice session"
            )
        return ceo

    async def run_turn(self, text: str, meta: dict[str, Any], gen: int, n: int) -> None:
        try:
            await self._run_turn(text, meta, gen, n)
        except asyncio.CancelledError:
            raise
        except SessionCloseError as exc:
            await self.fail(exc.code, exc.message)
            await self.close()
            with contextlib.suppress(RuntimeError):
                await self.ws.close(code=1008)
        except HTTPException as exc:
            await self.fail("TURN_REJECTED", str(exc.detail)[:200])
            await self.emit("listening")
        except Exception as exc:
            logger.warning("voice turn failed: %s", type(exc).__name__)
            await self.fail("TURN_FAILED", "The CEO could not answer")
            await self.emit("listening")

    async def _run_turn(self, text: str, meta: dict[str, Any], gen: int, n: int) -> None:
        from nexus.api.routes import chat
        from nexus.database import tenant_session
        from nexus.governance.audit_service import record_audit
        from nexus.runtime import chat_turns
        from nexus.services.session_service import get_or_create_default_session

        t0 = time.perf_counter()
        cid = self.sess.company_id
        async with tenant_session(cid) as db:
            ceo = await self.check_ceo(db)
            record = await get_or_create_default_session(db, ceo)
            if record.id != self.sess.chat_session_id:
                raise SessionCloseError(
                    "CEO_CHANGED", "The chat session changed; start a new voice session"
                )
            kwargs: dict[str, Any] = {
                "principal": self.principal,
                "idempotency_key": f"voice:{self.sess.id}:{n}",
                "stream": True,
                "prompt_payload": {"voice": meta},
            }
            try:
                queued = await chat_turns.create_turn(
                    db, record, ceo, text, require_manager_tools=True, **kwargs
                )
            except HTTPException as exc:
                if not (
                    isinstance(exc.detail, dict)
                    and exc.detail.get("code") == "CEO_TOOLS_UNSUPPORTED"
                ):
                    raise
                queued = await chat_turns.create_turn(db, record, ceo, text, **kwargs)
        turn = queued.turn
        if gen != self.generation:
            return
        self.active_turn = turn.id
        chat_turns.get_worker().wake(cid)
        await self.emit("thinking", turn_id=str(turn.id))

        chunker, spoken, k = SentenceChunker(), 0, 0
        first_delta = None
        self.first_audio_at = None
        async for raw in chat.turn_events(turn.id, cid, 0):
            if gen != self.generation:
                return
            line = next((ln for ln in raw.splitlines() if ln.startswith("data: ")), "")[6:]
            if not line or line == "[DONE]":
                continue
            ev = json.loads(line)
            if ev.get("type") == "chunk":
                delta = str(ev.get("text", ""))
                first_delta = first_delta or time.perf_counter()
                spoken += len(delta)
                await self.emit("text_delta", text=delta)
                for sentence in chunker.feed(delta):
                    k += 1
                    await self.speak(sentence, gen, k)
            elif ev.get("type") == "done":
                reply = str((ev.get("message") or {}).get("text", ""))
                if len(reply) > spoken:  # a reply that was not streamed
                    await self.emit("text_delta", text=reply[spoken:])
                    chunker.feed(reply[spoken:])
                for sentence in chunker.flush():
                    k += 1
                    await self.speak(sentence, gen, k)
            elif ev.get("type") == "error":
                await self.fail(str(ev.get("code") or "TURN_ERROR"), str(ev.get("text", ""))[:200])
        await asyncio.wait_for(self.drained.wait(), 120)
        if gen != self.generation:
            return
        self.active_turn, self.speaking = None, False
        await record_audit(
            cid,
            "voice.turn",
            actor_type="user",
            actor_id=str(self.sess.user_id),
            resource_type="chat_turn",
            resource_id=str(turn.id),
            details={
                **meta,
                "tts_voices": {"en": self.voice_en, "hi": self.voice_hi},
                "timings_ms": {
                    "first_text": int((first_delta - t0) * 1000) if first_delta else None,
                    "first_audio": int((self.first_audio_at - t0) * 1000)
                    if self.first_audio_at
                    else None,
                    "total": int((time.perf_counter() - t0) * 1000),
                },
            },
        )
        await self.emit("completed", turn_id=str(turn.id))
        await self.emit("listening")

    # --- speech out -------------------------------------------------------

    async def speak(self, sentence: str, gen: int, k: int) -> None:
        if gen != self.generation:
            return
        if self.tts is None:
            self.tts = await self.connect("tts", self.sess.id)
            await self.tts.recv()  # ready
            self.tts_reader = asyncio.create_task(self.tts_read(gen, self.tts))
        self.pending += 1
        self.drained.clear()
        await self.tts.send(
            json.dumps(
                {
                    "type": "speak",
                    "id": f"{gen}:{k}",
                    "text": sentence,
                    "voices": self.voices(),
                }
            )
        )

    def voices(self) -> dict[str, str]:
        return {k: v for k, v in (("en", self.voice_en), ("hi", self.voice_hi)) if v}

    async def tts_read(self, gen: int, link: Any) -> None:
        try:
            async for msg in link:
                if gen != self.generation:
                    return
                if isinstance(msg, bytes):
                    if not self.speaking:
                        self.speaking = True
                        self.first_audio_at = time.perf_counter()
                        await self.emit("speaking")
                    frame = protocol.pack_down(self.out_seq, SAMPLE_RATE_OUT, msg)
                    self.out_seq += 1
                    with contextlib.suppress(RuntimeError):
                        await self.ws.send_bytes(frame)
                else:
                    ev = json.loads(msg)
                    if ev.get("type") in ("done", "cancelled", "error"):
                        self.pending = max(0, self.pending - 1)
                        if not self.pending:
                            self.drained.set()
                        if ev["type"] == "error" and ev.get("code") == "NO_VOICE":
                            # No usable voice for this language: the reply stays as text.
                            await self.emit("notice", code="NO_VOICE", message=ev.get("message"))
                        elif ev["type"] == "error":
                            await self.fail("TTS_ERROR", "Speech synthesis failed")
        except Exception as exc:
            logger.warning("voice tts ended: %s", type(exc).__name__)
            self.pending = 0
            self.drained.set()

    # --- session guard ----------------------------------------------------

    async def watch(self) -> None:
        from nexus.database import tenant_session

        while not self.closed.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.closed.wait(), 5)
                return
            if time.time() >= self.sess.expires_at:
                raise SessionCloseError("SESSION_EXPIRED", "Voice session expired")
            try:
                revoked = await self.store.revoked(self.sess.company_id, self.sess.id)
            except SharedStateUnavailableError:
                raise SessionCloseError(
                    "SHARED_STATE_UNAVAILABLE", "Voice state is unavailable"
                ) from None
            if revoked:
                raise SessionCloseError("SESSION_REVOKED", "Voice session was ended")
            async with tenant_session(self.sess.company_id) as db:
                await self.check_ceo(db)


async def serve(ws: WebSocket, principal: Principal) -> None:
    """Authenticate the hello ticket, then run the connection until it ends."""
    from nexus.database import tenant_session
    from nexus.services import ceo_service

    await ws.accept()
    conn: VoiceConnection | None = None
    try:
        try:
            first = await asyncio.wait_for(ws.receive(), HELLO_TIMEOUT)
            text = first.get("text")  # one small text frame; audio before hello has no text
            if not isinstance(text, str) or len(text) > HELLO_MAX_CHARS:
                raise ValueError("hello")
            hello = json.loads(text)
            sess, ticket_exp = read_ticket(str(hello.get("ticket", "")))
        except (TimeoutError, ValueError, TicketError, RuntimeError, AttributeError):
            raise SessionCloseError("BAD_TICKET", "Invalid voice ticket") from None
        if hello.get("protocol") != protocol.VERSION:
            raise SessionCloseError("BAD_PROTOCOL", "Unsupported protocol version")
        if (
            not ceo_service.is_human(principal)
            or principal.user_id != sess.user_id
            or principal.company_id != sess.company_id
            or time.time() >= sess.expires_at
        ):
            raise SessionCloseError("BAD_TICKET", "Invalid voice ticket")
        try:
            store = await get_store(ws.app)  # fails closed when shared state is required
            if await store.revoked(sess.company_id, sess.id) or not await store.redeem(
                sess.company_id, sess.jti, ticket_exp - time.time()
            ):
                raise SessionCloseError("BAD_TICKET", "Invalid voice ticket")
        except SharedStateUnavailableError:
            raise SessionCloseError(
                "SHARED_STATE_UNAVAILABLE", "Voice state is unavailable; try again"
            ) from None
        async with tenant_session(sess.company_id) as db:
            ceo = await ceo_service.current_ceo(db, sess.company_id)
        if ceo is None or ceo.id != sess.ceo_id:
            raise SessionCloseError(
                "CEO_CHANGED", "The company's CEO changed; start a new voice session"
            )
        conn = VoiceConnection(ws, sess, principal)
        await conn.run()
    except SessionCloseError as exc:
        with contextlib.suppress(RuntimeError):
            await ws.send_text(
                json.dumps({"type": "error", "code": exc.code, "message": exc.message})
            )
    finally:
        with contextlib.suppress(RuntimeError):
            await ws.close(code=1008 if conn is None else 1000)
