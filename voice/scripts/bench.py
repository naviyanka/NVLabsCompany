"""Synthesize fixtures with Piper, transcribe with the configured STT, print timings.

Fixtures are generated speech (Piper voices), never recordings of people.
"""

import json
import time
import wave

import numpy as np

from nexus_voice import audio, cli
from nexus_voice.config import Settings
from nexus_voice.stt import Transcriber
from nexus_voice.tts import RATE, Synthesizer

CASES = {
    "en": ("Please summarise the quarterly hiring plan for the engineering team.", "en"),
    "hi": ("कृपया इंजीनियरिंग टीम की तिमाही भर्ती योजना का सारांश दीजिए।", "hi"),
    "mixed": ("मुझे TASK-142 का status बताइए और deployment की report भेजिए।", "mixed"),
}
VOICES = {"en": "en_US-lessac-medium", "hi": "hi_IN-pratham-medium"}

s = Settings()
tts = Synthesizer(s)
stt = Transcriber(s)
out = {"device": stt.device, "compute": getattr(stt, "compute_type", None), "cases": {}}
for name, (text, mode) in CASES.items():
    pcm = b"".join(tts.synthesize(text, VOICES))
    path = f"tests/fixtures/{name}.wav"
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
    a = audio.to_pcm16k(path)
    x = audio.pcm_to_float(a)
    stt.transcribe(x, "auto")  # warm
    t = time.perf_counter()
    r = stt.transcribe(x, "auto")
    out["cases"][name] = {"expected": text, "got": r["text"], "lang": r["language"],
                          "p": round(r["language_probability"], 2), "audio_s": round(len(x) / 16000, 2),
                          "stt_ms": r["stt_ms"], "wall_ms": int((time.perf_counter() - t) * 1000)}
print(json.dumps(out, ensure_ascii=False, indent=1))
