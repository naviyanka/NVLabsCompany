"""Live acceptance: real worker (GPU/CPU STT + Piper TTS), real gateway, mocked CEO reply.

Skipped unless NEXUS_VOICE_LIVE=1 and the worker models are installed. Fixtures are
Piper-synthesised speech, not recordings of people. Writes timings to stdout (-s).
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import time
import wave
from array import array
from pathlib import Path

import httpx
import pytest

from nexus.config import settings
from nexus.voice import protocol
from tests.test_voice_gateway import client, read_until, start, world  # noqa: F401

pytestmark = pytest.mark.skipif(
    os.environ.get("NEXUS_VOICE_LIVE") != "1", reason="live voice acceptance"
)

VOICE = Path(__file__).resolve().parents[1] / "voice"
SECRET = "live-acceptance-secret-0123456789abcdef"
PORT = 18765


def to_16k(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        src, rate = array("h", w.readframes(w.getnframes())), w.getframerate()
    n = int(len(src) * 16000 / rate)
    out = array("h", (src[min(len(src) - 1, int(i * rate / 16000))] for i in range(n)))
    return out.tobytes()


@pytest.fixture(scope="module")
def worker():
    env = {
        **os.environ,
        "NEXUS_VOICE_WORKER_SECRET": SECRET,
        "NEXUS_VOICE_PORT": str(PORT),
        "NEXUS_VOICE_PARTIALS": "0",
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.Popen(["uv", "run", "nexus-voice", "serve"], cwd=VOICE, env=env)
    try:
        for _ in range(120):
            try:
                if httpx.get(f"http://127.0.0.1:{PORT}/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            pytest.fail("worker did not start")
        yield
    finally:
        if os.name == "nt":  # `uv run` leaves its python child behind on terminate()
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/F", "/T"], capture_output=True)
        else:
            proc.terminate()
        proc.wait(timeout=20)


@pytest.mark.parametrize("name,expect", [("en", "en"), ("hi", "hi"), ("mixed", None)])
def test_live_turn(name, expect, worker, client, world, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(settings, "voice_worker_url", f"ws://127.0.0.1:{PORT}")
    monkeypatch.setattr(settings, "voice_worker_secret", SECRET)
    del client.voice_app.state.voice_connect  # use the real loopback worker
    pcm = to_16k(VOICE / "tests" / "fixtures" / f"{name}.wav")

    ws = start(client)
    sent = time.perf_counter()
    for seq, off in enumerate(range(0, len(pcm), 1024)):
        ws.send_bytes(protocol.pack_up(seq, pcm[off : off + 1024]))
    ws.send_text(json.dumps({"type": "ptt_end"}))
    events = read_until(ws, "completed", limit=400)
    total = time.perf_counter() - sent
    ws.__exit__(None, None, None)

    transcript = next(e for e in events if e["type"] == "transcript")
    frames = [e["bytes"] for e in events if e["type"] == "audio"]
    assert transcript["text"].strip() and frames
    if expect:
        assert transcript["language"] == expect
    rate = struct.unpack("!BBHII", frames[0][:12])[4]
    out = tmp_path / f"{name}.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"".join(f[12:] for f in frames))
    assert out.stat().st_size > 10_000
    print(
        f"LIVE {name}: lang={transcript['language']} p={transcript['language_probability']:.2f} "
        f"text={transcript['text']!r} audio_s={len(pcm) / 32000:.1f} total_s={total:.2f} "
        f"reply_audio_s={sum(len(f) - 12 for f in frames) / 2 / rate:.1f}"
    )
