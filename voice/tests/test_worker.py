import time
from pathlib import Path

import jwt
import numpy as np
import pytest
from fastapi.testclient import TestClient
from nexus_voice import audio, devices, models, segment
from nexus_voice.config import Settings
from nexus_voice.server import create_app
from nexus_voice.tokens import AUDIENCE, TokenError, TokenVerifier
from nexus_voice.vad import FRAME, UtteranceDetector
from starlette.websockets import WebSocketDisconnect

SECRET = "s" * 40
FIX = Path(__file__).parent / "fixtures"


def token(scope="stt", ttl=60, secret=SECRET, jti=None):
    now = int(time.time())
    return jwt.encode(
        {
            "aud": AUDIENCE,
            "sid": "v1",
            "scope": scope,
            "iat": now,
            "exp": now + ttl,
            "jti": jti or f"j{time.monotonic_ns()}",
        },
        secret,
        algorithm="HS256",
    )


class FakeStt:
    device = "cpu"

    def __init__(self):
        self.calls = []

    def transcribe(self, a, mode="auto", *, partial=False):
        self.calls.append((len(a), mode, partial))
        return {
            "text": "hello world",
            "language": "en",
            "language_probability": 0.99,
            "duration_ms": len(a) // 16,
            "stt_ms": 1,
            "model": "fake",
            "device": "cpu",
        }


class FakeTts:
    def synthesize(self, text, voices):
        for seg in segment.split(text):
            if seg.language not in voices:
                raise LookupError("no voice")
            yield b"\x01\x00" * 100


def loud_model(frames):  # first 20 frames speech, then silence
    loud_model.n = getattr(loud_model, "n", 0)
    out = np.array([0.9 if loud_model.n + i < 20 else 0.0 for i in range(len(frames))])
    loud_model.n += len(frames)
    return out


def app(stt=None, vad=None):
    return TestClient(
        create_app(
            Settings(secret=SECRET), stt or FakeStt(), FakeTts(), vad or (lambda: loud_model)
        )
    )


def hdr(t):
    return {"Authorization": f"Bearer {t}"}


class TestAuth:
    def test_rejects_missing_wrong_secret_scope_expired_and_replay(self):
        c = app()
        for bad in ["", token(secret="x" * 40), token(scope="tts"), token(ttl=-5)]:
            with pytest.raises(WebSocketDisconnect):
                with c.websocket_connect("/v1/stt", headers=hdr(bad)):
                    pass
        good = token()
        with c.websocket_connect("/v1/stt", headers=hdr(good)) as ws:
            assert ws.receive_json()["type"] == "ready"
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/v1/stt", headers=hdr(good)):
                pass

    def test_long_lived_token_rejected_and_short_secret_refused(self):
        with pytest.raises(TokenError):
            TokenVerifier(SECRET).verify(token(ttl=3600), "stt")
        with pytest.raises(ValueError):
            TokenVerifier("short")

    def test_binds_loopback_only(self):
        assert Settings().host == "127.0.0.1"


class TestStt:
    def test_utterance_yields_final_transcript_only_after_speech_ends(self):
        loud_model.n = 0
        stt = FakeStt()
        with app(stt).websocket_connect("/v1/stt", headers=hdr(token())) as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "config", "mode": "hi"})
            ws.send_bytes(np.zeros(FRAME * 60, dtype="<i2").tobytes()[:8192])
            for _ in range(8):
                ws.send_bytes(np.zeros(4096, dtype="<i2").tobytes())
            seen = []
            while True:
                m = ws.receive_json()
                seen.append(m["type"])
                if m["type"] == "transcript":
                    assert m["text"] == "hello world" and m["final"] is True
                    break
            assert seen[:3] == ["speech_started", "speech_ended", "transcribing"]
            assert stt.calls[-1][1] == "hi"

    def test_oversize_and_odd_frames_close_connection(self):
        for frame in (b"\x00" * 9000, b"\x00" * 101):
            with app().websocket_connect("/v1/stt", headers=hdr(token())) as ws:
                ws.receive_json()
                ws.send_bytes(frame)
                assert ws.receive_json()["code"] == "BAD_FRAME"

    def test_noise_makes_no_transcript(self):
        stt = FakeStt()
        with app(stt, vad=lambda: lambda f: np.zeros(len(f))).websocket_connect(
            "/v1/stt", headers=hdr(token())
        ) as ws:
            ws.receive_json()
            ws.send_bytes(b"\x00" * 4096)
            ws.send_json({"type": "flush"})
        assert stt.calls == []

    def test_bad_control_reports_error(self):
        with app().websocket_connect("/v1/stt", headers=hdr(token())) as ws:
            ws.receive_json()
            ws.send_json({"type": "config", "mode": "klingon"})
            assert ws.receive_json()["code"] == "BAD_CONTROL"


class TestVad:
    def test_boundaries_and_max_duration(self):
        probs = iter([0.9] * 10 + [0.0] * 30)
        det = UtteranceDetector(lambda f: np.array([next(probs) for _ in f]), silence_ms=320)
        ev = det.feed(np.zeros(FRAME * 40, dtype=np.float32))
        assert [e.kind for e in ev] == ["speech_started", "utterance"]
        det = UtteranceDetector(lambda f: np.full(len(f), 0.9), max_utterance_s=1.0)
        ev = det.feed(np.zeros(FRAME * 60, dtype=np.float32))
        assert any(e.kind == "utterance" and e.reason == "max_duration" for e in ev)


class TestTts:
    def test_speak_streams_binary_then_done_and_missing_voice_errors(self):
        with app().websocket_connect("/v1/tts", headers=hdr(token("tts"))) as ws:
            assert ws.receive_json()["sample_rate"] == 22050
            ws.send_json({"type": "speak", "id": "a", "text": "hello", "voices": {"en": "x"}})
            assert len(ws.receive_bytes()) == 200
            assert ws.receive_json()["type"] == "done"
            ws.send_json({"type": "speak", "id": "b", "text": "नमस्ते", "voices": {"en": "x"}})
            assert ws.receive_json()["code"] == "NO_VOICE"


class TestSegments:
    def test_routing_preserves_ids_and_order(self):
        text = "मुझे TASK-142 का status बताइए report_v2.pdf भेजिए।"
        segs = segment.split(text)
        assert "".join(s.text for s in segs) == text
        assert [s.language for s in segs] == ["hi", "en", "hi", "en", "hi", "en", "hi"]
        assert "TASK-142" in [s.text.strip() for s in segs][1]
        assert [s.language for s in segment.split("Hello there.")] == ["en"]

    def test_markdown_stripped_code_words_kept(self):
        assert segment.clean("**Run** `pytest -k foo_bar`") == "Run pytest -k foo_bar"


class TestModels:
    def test_manifest_pins_every_file(self):
        m = models.manifest()
        assert m["stt"]["license"] and len(m["voices"]) == 4
        for v in m["voices"].values():
            assert v["sample_rate"] == 22050 and v["license"] and v["source"]
            assert all(f["sha256"] for f in v["files"].values())
        assert all(f["sha256"] for f in m["stt"]["files"].values())

    def test_hash_mismatch_detected(self, tmp_path):
        p = tmp_path / "f"
        p.write_bytes(b"abc")
        assert (
            models.sha256(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )

    def test_cpu_fallback_choice(self, monkeypatch):
        monkeypatch.setattr(devices, "cuda_available", lambda: False)
        assert devices.choose("auto") == ("cpu", "int8")

    def test_fixtures_are_valid_wavs(self):
        for f in FIX.glob("*.wav"):
            assert audio.validate_wav(f)


def test_partials_are_off_by_default():
    assert Settings.__dataclass_fields__["partials"].default is False
