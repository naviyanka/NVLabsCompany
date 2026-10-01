"""Speech recognition: faster-whisper, GPU first, CPU fallback."""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from nexus_voice import devices, models
from nexus_voice.config import Settings

log = logging.getLogger(__name__)

# The mode a user picks maps to Whisper's language hint; auto and mixed detect per utterance.
LANGUAGE = {"auto": None, "mixed": None, "hi": "hi", "en": "en"}


class Transcriber:
    def __init__(self, settings: Settings) -> None:
        from faster_whisper import WhisperModel

        self.settings = settings
        path = str(models.stt_dir(settings))
        self.fallback_reason: str | None = None
        self.device, self.compute_type = devices.choose(settings.device)
        try:
            self.model = WhisperModel(path, device=self.device, compute_type=self.compute_type)
            if self.device == "cuda":
                self._warm()
        except Exception as exc:  # noqa: BLE001 - any CUDA init failure falls back to CPU
            if self.device == "cpu":
                raise
            self.fallback_reason = f"cuda unavailable: {type(exc).__name__}"
            log.warning("STT %s", self.fallback_reason)
            self.device, self.compute_type = "cpu", "int8"
            self.model = WhisperModel(path, device="cpu", compute_type="int8")

    def _warm(self) -> None:
        # CUDA errors (missing cuDNN, out of memory) surface on first use, not on load.
        list(self.model.transcribe(np.zeros(16_000, dtype=np.float32), beam_size=1)[0])

    def transcribe(
        self, audio: np.ndarray, mode: str = "auto", *, partial: bool = False
    ) -> dict[str, Any]:
        start = time.perf_counter()
        segments, info = self.model.transcribe(
            audio,
            language=LANGUAGE.get(mode),
            task="transcribe",  # never translate
            beam_size=1 if partial else 5,
            vad_filter=False,  # utterances are already cut by the streaming VAD
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return {
            "text": text,
            "language": info.language,
            "language_probability": round(float(info.language_probability), 3),
            "duration_ms": int(len(audio) / 16),
            "stt_ms": int((time.perf_counter() - start) * 1000),
            "model": self.settings.stt_model,
            "device": self.device,
        }
