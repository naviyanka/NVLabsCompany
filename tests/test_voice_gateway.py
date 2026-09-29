"""Local CEO voice gateway: sessions, binary protocol, durable turn, barge-in, privacy.

The voice worker is faked (scripted events, synthetic PCM); the CEO reply is a mocked
model. No microphone, no recording, no model weights.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
import uuid

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401
from nexus.api.routes import chat as chat_routes
from nexus.api.routes import voice as voice_routes
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.chat import ChatMessage
from nexus.models.chat_turn import ChatTurn
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.voice import protocol
from nexus.voice.chunker import SentenceChunker
from nexus.voice.limits import RateLimiter
from nexus.voice.shared_state import MemoryStore
from nexus.voice.tokens import TICKET_AUDIENCE, WORKER_AUDIENCE, mint_worker_token

pytestmark = pytest.mark.core_employee

SECRET = "w" * 40


def pcm(seq: int, n: int = 1024) -> bytes:
    return protocol.pack_up(seq, b"\x01\x00" * (n // 2))


# --- fake worker ------------------------------------------------------------


class Link:
    """A worker connection: scripted answers to what the gateway sends."""

    def __init__(self, scope, script):
        self.scope, self.script, self.sent = scope, script, []
        self.q: asyncio.Queue = asyncio.Queue()
        self.q.put_nowait(json.dumps({"type": "ready"}))
        self.closed = False

    async def recv(self):
        return await self.q.get()

    async def send(self, data):
        self.sent.append(data)
        if isinstance(data, str):
            for out in self.script(self.scope, json.loads(data)):
                self.q.put_nowait(out)

    async def close(self):
        self.closed = True
        self.q.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.q.get()
        if item is None:
            raise StopAsyncIteration
        return item


def heard(text="give me the status", language="en", duration=1200):
    def script(scope, msg):
        if scope == "stt" and msg.get("type") == "flush":
            return [
                json.dumps({"type": "speech_started"}),
                json.dumps({"type": "speech_ended", "reason": "flush", "duration_ms": duration}),
                json.dumps({"type": "transcribing"}),
                json.dumps(
                    {
                        "type": "transcript",
                        "final": True,
                        "text": text,
                        "language": language,
                        "language_probability": 0.97,
                        "duration_ms": duration,
                        "stt_ms": 90,
                        "model": "faster-whisper-medium",
                        "device": "cuda",
                    }
                ),
            ]
        if scope == "tts" and msg.get("type") == "speak":
            return [
                b"\x02\x00" * 200,
                b"\x02\x00" * 200,
                json.dumps({"type": "done", "id": msg["id"], "tts_ms": 5}),
            ]
        return []

    return script


def silence(scope, msg):
    if scope == "stt" and msg.get("type") == "flush":
        return [json.dumps({"type": "empty", "reason": "noise"})]
    return []


# --- world ------------------------------------------------------------------


class World:
    def __init__(self, engine, factory):
        self.engine, self.factory = engine, factory
        self.links: list[Link] = []
        self.script = heard()
        self.gate: asyncio.Event | None = None

    def run(self, coro):
        return asyncio.run(coro)

    def rows(self, model, *where):
        async def go():
            async with self.factory() as s:
                return (await s.execute(select(model).where(*where))).scalars().all()

        return self.run(go())

    def update_agent(self, agent_id, **values):
        async def go():
            async with self.factory() as s:
                agent = await s.get(Agent, agent_id)
                for k, v in values.items():
                    setattr(agent, k, v)
                await s.commit()

        self.run(go())


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'v.db').as_posix()}", poolclass=NullPool
    )

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    asyncio.run(setup())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    monkeypatch.setattr(settings, "database_url", str(engine.url))
    monkeypatch.setattr(settings, "voice_enabled", True)
    monkeypatch.setattr(settings, "voice_worker_secret", SECRET)
    w = World(engine, factory)

    async def fake_prompt(db, agent, company_id, prompt):
        return "system"

    async def fake_llm(agent, system_prompt, prompt, history, **kw):
        if w.gate is not None:
            await w.gate.wait()
        return "The company is healthy. Two tasks are open.", "test-model", 7

    monkeypatch.setattr(chat_routes, "_build_chat_prompt", fake_prompt)
    monkeypatch.setattr(chat_routes, "_call_llm", fake_llm)
    monkeypatch.setattr(
        chat_routes, "_resolve_adapter_type", lambda agent, conn=None: ("openai", {})
    )

    async def seed():
        ids = {}
        async with factory() as s:
            for name in ("acme", "other"):
                company = Company(name=name)
                s.add(company)
                await s.flush()
                ceo = Agent(
                    company_id=company.id,
                    name=f"{name} ceo",
                    role="executive",
                    adapter_type="openai",
                    model="gpt-x",
                    is_ceo=True,
                )
                other = Agent(
                    company_id=company.id,
                    name=f"{name} deputy",
                    role="executive",
                    adapter_type="openai",
                    model="gpt-x",
                )
                s.add_all([ceo, other])
                await s.flush()
                ids[name], ids[f"{name}_ceo"], ids[f"{name}_deputy"] = company.id, ceo.id, other.id
            await s.commit()
        return ids

    w.ids = asyncio.run(seed())
    w.users = {"acme": uuid.uuid4(), "other": uuid.uuid4()}
    return w


def principal(world, who="acme", kind="user"):
    return Principal(
        kind=kind,
        company_id=world.ids[who],
        role="admin",
        user_id=world.users[who] if kind == "user" else None,
        email="a@b.test",
    )


class AsPrincipal:
    """ASGI middleware standing in for authentication (HTTP and WebSocket alike)."""

    def __init__(self, app, world):
        self.app, self.world = app, world

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope["headers"])
            who = headers.get(b"x-who", b"acme").decode()
            kind = "service" if who.endswith("-key") else "user"
            scope.setdefault("state", {})["principal"] = principal(
                self.world, who.split("-")[0], kind
            )
        await self.app(scope, receive, send)


@pytest.fixture
def client(world):
    app = FastAPI()
    app.include_router(voice_routes.router)

    def connect(scope, sid):
        async def go():
            link = Link(scope, lambda s, m: world.script(s, m))
            world.links.append(link)
            return link

        return go()

    app.state.voice_connect = connect
    app.state.voice_store = MemoryStore()  # single process; shared state has its own tests
    with TestClient(AsPrincipal(app, world)) as c:
        c.world, c.voice_app = world, app
        yield c


def new_session(client, who="acme", **body):
    r = client.post("/api/v1/voice/sessions", json=body, headers={"x-who": who})
    return r


def open_socket(client, ticket, who="acme"):
    ws = client.websocket_connect("/api/v1/voice/ws", headers={"x-who": who})
    return ws


def hello(ws, ticket, protocol_version=1):
    ws.send_text(json.dumps({"type": "hello", "ticket": ticket, "protocol": protocol_version}))


def read_until(ws, kind, limit=40):
    seen = []
    for _ in range(limit):
        m = ws.receive()
        if m.get("bytes") is not None:
            seen.append({"type": "audio", "bytes": m["bytes"]})
            continue
        if m["type"] == "websocket.close":
            seen.append({"type": "closed", "code": m.get("code")})
            return seen
        ev = json.loads(m["text"])
        seen.append(ev)
        if ev["type"] == kind:
            return seen
    raise AssertionError(f"no {kind} in {[e['type'] for e in seen]}")


def start(client, who="acme", **body):
    ticket = new_session(client, who, **body).json()["ticket"]
    ws = open_socket(client, ticket, who).__enter__()
    hello(ws, ticket)
    read_until(ws, "listening")
    return ws


# --- REST session -----------------------------------------------------------


class TestSession:
    def test_disabled_by_default_setting(self, client, monkeypatch):
        monkeypatch.setattr(settings, "voice_enabled", False)
        assert new_session(client).status_code == 404

    def test_session_is_bound_server_side(self, client, world):
        r = new_session(
            client,
            mode="hi",
            company_id=str(world.ids["other"]),
            ceo_id=str(world.ids["other_ceo"]),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["ceo"]["id"] == str(world.ids["acme_ceo"])
        claims = jwt.decode(
            body["ticket"], settings.secret_key, algorithms=["HS256"], audience=TICKET_AUDIENCE
        )
        assert claims["cid"] == str(world.ids["acme"])
        assert claims["ceo"] == str(world.ids["acme_ceo"])
        assert claims["sub"] == str(world.users["acme"]) and claims["mode"] == "hi"
        assert claims["exp"] - claims["iat"] <= settings.voice_ticket_ttl_seconds
        assert body["ws_path"] == "/api/v1/voice/ws"

    def test_needs_a_person_a_ceo_and_a_known_voice(self, client, world):
        assert new_session(client, who="acme-key").status_code == 403
        assert new_session(client, voice_en="../../etc/passwd").status_code == 422
        world.update_agent(world.ids["acme_ceo"], is_ceo=False)
        r = new_session(client)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_CEO"

    def test_session_rate_limit(self, client, monkeypatch):
        monkeypatch.setattr(settings, "voice_sessions_per_minute", 2)
        codes = [new_session(client).status_code for _ in range(3)]
        assert codes == [201, 201, 429]

    def test_no_raw_audio_claim_in_status(self, client):
        assert (
            client.get("/api/v1/voice/status", headers={"x-who": "acme"}).json()["raw_audio_stored"]
            is False
        )

    def test_defaults_are_commercially_licensed_and_hindi_is_unset(self, client):
        body = client.get("/api/v1/voice/status", headers={"x-who": "acme"}).json()
        assert body["default_voices"] == {"en": "en_US-ljspeech-medium", "hi": ""}
        assert "lessac" not in body["default_voices"]["en"]
        assert body["voices"] == [] and body["worker_reachable"] is False

    def test_status_lists_worker_voice_labels(self, client, monkeypatch):
        async def catalog(path):
            return {
                "allow_noncommercial": False,
                "voices": [{"id": "hi_IN-pratham-medium", "restricted": True, "selectable": False}],
            }

        monkeypatch.setattr(voice_routes.worker_client, "worker_get", catalog)
        body = client.get("/api/v1/voice/status", headers={"x-who": "acme"}).json()
        assert body["voices"][0]["restricted"] and body["allow_noncommercial_models"] is False
        assert new_session(client).json()["voices"]["hi"] == ""


# --- WebSocket auth ---------------------------------------------------------


class TestSocketAuth:
    def close_reason(self, client, ticket, who="acme", protocol_version=1):
        with open_socket(client, ticket, who) as ws:
            hello(ws, ticket, protocol_version)
            return [e for e in read_until(ws, "error")][-1]

    def test_other_tenant_user_cannot_use_a_ticket(self, client):
        ticket = new_session(client).json()["ticket"]
        assert self.close_reason(client, ticket, who="other")["code"] == "BAD_TICKET"

    def test_ticket_is_single_use(self, client):
        ticket = new_session(client).json()["ticket"]
        with open_socket(client, ticket) as ws:
            hello(ws, ticket)
            assert read_until(ws, "ready")
        assert self.close_reason(client, ticket)["code"] == "BAD_TICKET"

    def test_expired_forged_and_wrong_protocol_tickets(self, client, world):
        now = int(time.time())
        base = {
            "aud": TICKET_AUDIENCE,
            "iat": now,
            "jti": "x",
            "vsid": "v",
            "sub": str(world.users["acme"]),
            "cid": str(world.ids["acme"]),
            "ceo": str(world.ids["acme_ceo"]),
            "chat": str(uuid.uuid4()),
            "mode": "auto",
            "ven": "en_US-lessac-medium",
            "vhi": "hi_IN-pratham-medium",
            "sx": now + 60,
        }
        expired = jwt.encode({**base, "exp": now - 5}, settings.secret_key, algorithm="HS256")
        forged = jwt.encode({**base, "exp": now + 30}, "not-the-secret" * 3, algorithm="HS256")
        assert self.close_reason(client, expired)["code"] == "BAD_TICKET"
        assert self.close_reason(client, forged)["code"] == "BAD_TICKET"
        good = new_session(client).json()["ticket"]
        assert self.close_reason(client, good, protocol_version=99)["code"] == "BAD_PROTOCOL"

    def test_replaced_ceo_invalidates_the_session(self, client, world):
        ticket = new_session(client).json()["ticket"]
        world.update_agent(world.ids["acme_ceo"], is_ceo=False)
        world.update_agent(world.ids["acme_deputy"], is_ceo=True)
        assert self.close_reason(client, ticket)["code"] == "CEO_CHANGED"

    def test_worker_down_is_reported(self, client):
        def refuse(scope, sid):
            from nexus.voice.worker_client import WorkerUnavailableError

            raise WorkerUnavailableError("down")

        client.voice_app.state.voice_connect = refuse
        ticket = new_session(client).json()["ticket"]
        assert self.close_reason(client, ticket)["code"] == "WORKER_UNAVAILABLE"


# --- protocol ---------------------------------------------------------------


class TestFrames:
    def test_pack_and_parse(self):
        assert protocol.parse_up(pcm(0), 0) == b"\x01\x00" * 512
        down = protocol.pack_down(7, 22050, b"\x00\x00", last=True)
        ver, kind, flags, seq, rate = struct.unpack("!BBHII", down[:12])
        assert (ver, kind, flags, seq, rate) == (1, 3, 1, 7, 22050) and len(down) == 14

    @pytest.mark.parametrize(
        "frame,expected_seq",
        [
            (b"", 0),
            (protocol.pack_up(0, b""), 0),
            (pcm(3), 0),
            (protocol.pack_up(0, b"\x00" * 3), 0),
            (protocol.pack_up(0, b"\x00" * 9000), 0),
            (b"\x09" + pcm(0)[1:], 0),
        ],
        ids=["empty", "no_payload", "wrong_seq", "odd_length", "oversized", "bad_version"],
    )
    def test_rejects_malformed(self, frame, expected_seq):
        with pytest.raises(protocol.FrameError):
            protocol.parse_up(frame, expected_seq)

    def test_socket_closes_on_out_of_order_and_bad_frames(self, client):
        for frames in (
            [pcm(1)],
            [pcm(0), pcm(0)],
            [b"junk-frame"],
            [protocol.pack_up(0, b"\x00" * 9000)],
        ):
            ws = start(client)
            for f in frames:
                ws.send_bytes(f)
            assert read_until(ws, "error")[-1]["code"] == "BAD_FRAME"
            ws.__exit__(None, None, None)

    def test_unknown_control_is_rejected(self, client):
        ws = start(client)
        ws.send_text(json.dumps({"type": "exec", "cmd": "rm"}))
        assert read_until(ws, "error")[-1]["code"] == "BAD_CONTROL"
        ws.__exit__(None, None, None)


# --- the voice turn ---------------------------------------------------------


class TestTurn:
    def test_end_to_end_synthetic_turn(self, client, world):
        ws = start(client, mode="auto")
        ws.send_bytes(pcm(0))
        ws.send_text(json.dumps({"type": "ptt_end"}))
        events = read_until(ws, "completed")
        types = [e["type"] for e in events]
        for expected in (
            "speech_started",
            "speech_ended",
            "transcribing",
            "transcript",
            "thinking",
            "text_delta",
            "speaking",
            "audio",
            "completed",
        ):
            assert expected in types, types
        assert types.index("transcript") < types.index("thinking") < types.index("speaking")
        transcript = next(e for e in events if e["type"] == "transcript")
        assert transcript["text"] == "give me the status" and transcript["language"] == "en"
        audio = [e["bytes"] for e in events if e["type"] == "audio"]
        seqs = [struct.unpack("!BBHII", a[:12])[3] for a in audio]
        assert seqs == list(range(len(seqs))) and all(len(a) > 12 for a in audio)
        spoken = "".join(e["text"] for e in events if e["type"] == "text_delta")
        assert spoken.startswith("The company is healthy")
        # Only the visible reply went to TTS.
        tts_sent = [
            json.loads(m)
            for link in world.links
            if link.scope == "tts"
            for m in link.sent
            if isinstance(m, str)
        ]
        assert tts_sent and all(m["text"] in spoken for m in tts_sent if m["type"] == "speak")
        assert not any("tool" in m["text"].lower() for m in tts_sent if m["type"] == "speak")
        ws.__exit__(None, None, None)

        users = world.rows(ChatMessage, ChatMessage.sender == "user")
        assert [m.text for m in users] == ["give me the status"]
        assert users[0].payload["voice"]["detected_language"] == "en"
        assert users[0].payload["voice"]["stt_model"] == "faster-whisper-medium"
        turn = world.rows(ChatTurn)[0]
        assert turn.idempotency_key.startswith("voice:") and turn.agent_id == world.ids["acme_ceo"]
        audit = world.rows(AuditLog, AuditLog.action == "voice.turn")[0]
        assert (
            audit.details["audio_duration_ms"] == 1200
            and "first_audio" in audit.details["timings_ms"]
        )
        blob = json.dumps(audit.details) + " ".join(m.text for m in world.rows(ChatMessage))
        assert "\\x01" not in blob and "base64" not in blob

    def test_empty_or_noise_utterance_creates_nothing(self, client, world):
        world.script = silence
        ws = start(client)
        ws.send_bytes(pcm(0))
        ws.send_text(json.dumps({"type": "ptt_end"}))
        read_until(ws, "listening")
        ws.__exit__(None, None, None)
        assert world.rows(ChatMessage) == [] and world.rows(ChatTurn) == []

    def test_partials_are_never_submitted(self, client, world):
        def partials(scope, msg):
            if scope == "stt" and msg.get("type") == "flush":
                return [
                    json.dumps({"type": "partial", "final": False, "text": "delete everything"}),
                    json.dumps({"type": "empty", "reason": "no_speech"}),
                ]
            return []

        world.script = partials
        ws = start(client)
        ws.send_text(json.dumps({"type": "ptt_end"}))
        events = read_until(ws, "listening")
        assert any(e["type"] == "partial" for e in events)
        ws.__exit__(None, None, None)
        assert world.rows(ChatMessage) == []

    def test_spoken_secrets_are_redacted_before_chat(self, client, world):
        world.script = heard(text="my password: hunter2hunter2 and key sk-abcdefghijklmnopqrstuv")
        ws = start(client)
        ws.send_text(json.dumps({"type": "ptt_end"}))
        events = read_until(ws, "completed")
        ws.__exit__(None, None, None)
        assert next(e for e in events if e["type"] == "transcript")["redacted"] is True
        stored = world.rows(ChatMessage, ChatMessage.sender == "user")[0].text
        assert "hunter2" not in stored and "sk-abcdefghij" not in stored

    def test_utterance_rate_limit(self, client, world, monkeypatch):
        monkeypatch.setattr(settings, "voice_utterances_per_minute", 1)
        ws = start(client)
        ws.send_text(json.dumps({"type": "ptt_end"}))
        read_until(ws, "completed")
        ws.send_text(json.dumps({"type": "ptt_end"}))
        assert read_until(ws, "error")[-1]["code"] == "RATE_LIMITED"
        ws.__exit__(None, None, None)
        assert len(world.rows(ChatTurn)) == 1

    def test_missing_voice_is_a_notice_not_a_failure(self, client, world):
        base = heard("namaste", "hi")

        def script(scope, msg):
            if scope == "tts" and msg.get("type") == "speak":
                assert msg["voices"] == {"en": "en_US-ljspeech-medium"}  # unset Hindi not sent
                return [
                    json.dumps(
                        {"type": "error", "id": msg["id"], "code": "NO_VOICE", "message": "no hi"}
                    )
                ]
            return base(scope, msg)

        world.script = script
        ws = start(client)
        ws.send_bytes(pcm(0))
        ws.send_text(json.dumps({"type": "ptt_end"}))
        events = read_until(ws, "completed")
        assert any(e["type"] == "notice" and e["code"] == "NO_VOICE" for e in events)
        assert not any(e["type"] == "error" for e in events)
        ws.__exit__(None, None, None)

    def test_ceo_replaced_mid_session_blocks_the_next_turn(self, client, world):
        ws = start(client)
        world.update_agent(world.ids["acme_ceo"], is_ceo=False)
        world.update_agent(world.ids["acme_deputy"], is_ceo=True)
        ws.send_text(json.dumps({"type": "ptt_end"}))
        events = read_until(ws, "error")
        assert events[-1]["code"] == "CEO_CHANGED"
        ws.__exit__(None, None, None)
        assert world.rows(ChatTurn) == []


class TestBargeIn:
    def test_stop_stops_speech_and_cancels_the_durable_turn(self, client, world):
        world.gate = asyncio.Event()  # the CEO never answers on its own
        ws = start(client)
        ws.send_text(json.dumps({"type": "ptt_end"}))
        read_until(ws, "thinking")
        t0 = time.perf_counter()
        ws.send_text(json.dumps({"type": "stop"}))
        events = read_until(ws, "interrupted")
        assert events[-1]["reason"] == "stop"
        assert (time.perf_counter() - t0) < 0.3
        deadline = time.time() + 5
        while time.time() < deadline:
            turn = world.rows(ChatTurn)[0]
            if turn.status in ("cancelled", "completed"):
                break
            time.sleep(0.05)
        assert turn.status == "cancelled" and turn.cancelled_by == "voice:stop"
        ws.__exit__(None, None, None)

    def test_new_utterance_cancels_the_old_turn_but_keeps_its_prompt(self, client, world):
        world.gate = asyncio.Event()
        ws = start(client)
        ws.send_text(json.dumps({"type": "ptt_end"}))
        read_until(ws, "thinking")
        world.script = heard(text="never mind, what about hiring")
        ws.send_text(json.dumps({"type": "ptt_end"}))
        read_until(ws, "thinking")
        ws.__exit__(None, None, None)
        turns = sorted(world.rows(ChatTurn), key=lambda t: t.turn_seq)
        assert len(turns) == 2 and turns[0].status in ("cancelled", "running", "queued", "claimed")
        assert {t.idempotency_key.rsplit(":", 1)[1] for t in turns} == {"1", "2"}
        assert [m.text for m in world.rows(ChatMessage, ChatMessage.sender == "user")].count(
            "give me the status"
        ) == 1

    def test_speech_without_a_transcript_does_not_cancel_the_turn(self, client, world):
        world.gate = asyncio.Event()
        ws = start(client)
        ws.send_text(json.dumps({"type": "ptt_end"}))
        read_until(ws, "thinking")
        world.script = silence
        ws.send_text(json.dumps({"type": "ptt_end"}))
        read_until(ws, "listening")
        time.sleep(0.2)
        assert world.rows(ChatTurn)[0].status != "cancelled"
        ws.__exit__(None, None, None)


# --- units ------------------------------------------------------------------


class TestChunker:
    def test_sentences_stream_in_order_and_ids_survive(self):
        c = SentenceChunker()
        out = c.feed("Task TASK-142 is done and verified. Report report_v2.pdf is ")
        assert out == ["Task TASK-142 is done and verified."]
        out += c.feed("attached for review. Version 3.5 ships tomorrow after review.\nNext")
        assert out[1:] == [
            "Report report_v2.pdf is attached for review.",
            "Version 3.5 ships tomorrow after review.",
        ]
        assert c.flush() == ["Next"]

    def test_hindi_danda_and_long_runs(self):
        c = SentenceChunker()
        assert c.feed("कंपनी की स्थिति ठीक है। दो कार्य खुले हैं। ") == [
            "कंपनी की स्थिति ठीक है। दो कार्य खुले हैं।"
        ]
        long = c.feed("word " * 100)
        assert long and all(len(x) <= 200 for x in long)

    def test_short_fragments_wait(self):
        c = SentenceChunker()
        assert c.feed("Yes. ") == [] and c.flush() == ["Yes."]


class TestTokens:
    def test_worker_token_shape(self, monkeypatch):
        monkeypatch.setattr(settings, "voice_worker_secret", SECRET)
        t = mint_worker_token("sid1", "stt")
        c = jwt.decode(t, SECRET, algorithms=["HS256"], audience=WORKER_AUDIENCE)
        assert (
            c["scope"] == "stt" and c["sid"] == "sid1" and c["exp"] - c["iat"] <= 120 and c["jti"]
        )
        assert not {"company_id", "cid", "user", "sub", "ceo"} & set(c)  # worker learns no identity

    def test_worker_url_must_be_loopback_and_secret_set(self, monkeypatch):
        from nexus.voice import worker_client

        monkeypatch.setattr(settings, "voice_worker_secret", SECRET)
        monkeypatch.setattr(settings, "voice_worker_url", "ws://10.0.0.5:8765")
        with pytest.raises(worker_client.WorkerUnavailableError):
            worker_client.worker_url("/v1/stt")
        monkeypatch.setattr(settings, "voice_worker_url", "ws://127.0.0.1:8765")
        assert worker_client.worker_url("/v1/stt") == "ws://127.0.0.1:8765/v1/stt"
        monkeypatch.setattr(settings, "voice_worker_secret", "short")
        with pytest.raises(worker_client.WorkerUnavailableError):
            worker_client.worker_url("/v1/stt")

    def test_rate_limiter_window(self):
        r = RateLimiter(2)
        assert [r.allow("k"), r.allow("k"), r.allow("k"), r.allow("j")] == [True, True, False, True]
