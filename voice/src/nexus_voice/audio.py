"""FFmpeg helpers: conversion to the worker's wire format and output validation."""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

RATE = 16_000


def ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def ffmpeg_version() -> str | None:
    exe = ffmpeg()
    if not exe:
        return None
    out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=10).stdout
    return out.splitlines()[0] if out else None


def to_pcm16k(path: str | Path) -> bytes:
    """Any audio file to 16 kHz mono s16le, the only format the worker accepts."""
    exe = ffmpeg()
    if not exe:
        raise RuntimeError("ffmpeg is not on PATH")
    run = subprocess.run(
        [exe, "-v", "error", "-i", str(path), "-ar", str(RATE), "-ac", "1", "-f", "s16le", "-"],
        capture_output=True,
        timeout=120,
    )
    if run.returncode:
        raise ValueError("ffmpeg could not decode the audio")
    return run.stdout


def pcm_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def validate_wav(path: str | Path) -> dict:
    """Raise unless ``path`` is a non-empty, non-silent PCM WAV; return its shape."""
    with wave.open(str(path), "rb") as w:
        rate, channels, frames = w.getframerate(), w.getnchannels(), w.getnframes()
        data = np.frombuffer(w.readframes(frames), dtype="<i2")
    if frames == 0 or not data.any():
        raise ValueError("empty or silent audio")
    return {"sample_rate": rate, "channels": channels, "seconds": frames / rate}
