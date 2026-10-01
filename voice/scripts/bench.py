"""STT benchmark on this machine: peak GPU memory, load time, latency, accuracy.

    uv run python scripts/bench.py fixtures            # synthesize the licensed English fixtures
    uv run python scripts/bench.py all                 # every candidate, one fresh process each

Fixtures are synthetic speech, never recordings of people. Only English is generated here,
with the public-domain ljspeech voice. Hindi and mixed audio need a Hindi voice, and no
commercially licensed one exists, so ``tests/local_fixtures/`` (git-ignored) holds
non-commercial-voice audio that is used for timing and indicative accuracy only.
"""

import json
import os
import statistics
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = Path(
    os.environ.get("NEXUS_VOICE_MODEL_DIR")
    or Path(os.environ["LOCALAPPDATA"]) / "nexus-voice" / "models"
)
CASES = {  # name -> (expected text, explicit language, folder)
    "en": (
        "Please summarise the quarterly hiring plan for the engineering team.",
        "en",
        "fixtures",
    ),
    "en2": ("The deployment finished without errors and the report is ready.", "en", "fixtures"),
    "hi": ("कृपया इंजीनियरिंग टीम की तिमाही भर्ती योजना का सारांश दीजिए।", "hi", "local_fixtures"),
    "mixed": ("मुझे TASK-142 का status बताइए और deployment की report भेजिए।", "hi", "local_fixtures"),
}
CANDIDATES = {  # name -> (model dir, device, compute type)
    "medium-cuda-int8_float16": (MODELS / "stt" / "faster-whisper-medium", "cuda", "int8_float16"),
    "large-v3-turbo-cuda-int8_float16": (
        MODELS / "bench" / "large-v3-turbo",
        "cuda",
        "int8_float16",
    ),
    "medium-cpu-int8": (MODELS / "stt" / "faster-whisper-medium", "cpu", "int8"),
}


def fixtures() -> None:
    from nexus_voice.config import Settings
    from nexus_voice.tts import RATE, Synthesizer

    tts = Synthesizer(Settings())
    for name, (text, _, folder) in CASES.items():
        if folder != "fixtures":
            continue
        pcm = b"".join(tts.synthesize(text, {"en": "en_US-ljspeech-medium", "hi": ""}))
        with wave.open(str(ROOT / "tests" / folder / f"{name}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            w.writeframes(pcm)


def edit_distance(a: list, b: list) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def norm(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum() or c.isspace()).strip()


def error_rate(expected: str, got: str) -> dict:
    e, g = norm(expected), norm(got)
    return {
        "wer": round(edit_distance(e.split(), g.split()) / len(e.split()), 2),
        "cer": round(edit_distance(list(e), list(g)) / len(e), 2),
    }


def gpu_used_mib() -> int:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
    )
    return int(out.stdout.split()[0])


def run_one(name: str) -> dict:
    import numpy as np
    from faster_whisper import WhisperModel
    from nexus_voice import audio, devices

    devices.add_cuda_dll_dirs()

    path, device, compute = CANDIDATES[name]
    base = gpu_used_mib() if device == "cuda" else 0
    peak, stop = [base], threading.Event()

    def sample() -> None:
        while not stop.wait(0.05):  # ponytail: 20 Hz nvidia-smi sampling can miss sub-50 ms spikes
            peak.append(gpu_used_mib())

    if device == "cuda":
        threading.Thread(target=sample, daemon=True).start()
    t = time.perf_counter()
    model = WhisperModel(str(path), device=device, compute_type=compute)
    load_cold = time.perf_counter() - t
    t = time.perf_counter()
    WhisperModel(str(path), device=device, compute_type=compute)
    load_warm = time.perf_counter() - t

    def transcribe(x, lang):
        t0 = time.perf_counter()
        segs, info = model.transcribe(
            x,
            language=lang,
            task="transcribe",
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segs).strip()
        return text, info, (time.perf_counter() - t0) * 1000

    transcribe(np.zeros(16_000, dtype=np.float32), None)  # first-use warm-up (CUDA kernels, cuDNN)
    rows = {}
    for case, (expected, lang, folder) in CASES.items():
        wav = ROOT / "tests" / folder / f"{case}.wav"
        if not wav.is_file():
            continue
        x = audio.pcm_to_float(audio.to_pcm16k(str(wav)))
        for label, hint in (("auto", None), ("explicit", lang)):
            runs = [transcribe(x, hint) for _ in range(3)]
            text, info, _ = runs[0]
            rows[f"{case}/{label}"] = {
                "audio_s": round(len(x) / 16000, 1),
                "lang": info.language,
                "p": round(info.language_probability, 2),
                "ms_median": int(statistics.median(r[2] for r in runs)),
                "got": text,
                **error_rate(expected, text),
            }
    stop.set()
    return {
        "candidate": name,
        "load_cold_s": round(load_cold, 1),
        "load_warm_s": round(load_warm, 1),
        "gpu_baseline_mib": base,
        "gpu_peak_delta_mib": max(peak) - base,
        "cases": rows,
    }


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "fixtures":
        fixtures()
    elif cmd == "all":
        for name in CANDIDATES:
            out = subprocess.run(
                [sys.executable, __file__, "one", name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            print(out.stdout or out.stderr[-600:])
    else:
        print(json.dumps(run_one(sys.argv[2]), ensure_ascii=False, indent=1))
