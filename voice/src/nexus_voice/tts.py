"""Text to speech: Piper on CPU, so the GPU stays free for STT."""

from __future__ import annotations

import numpy as np

from nexus_voice import models, segment
from nexus_voice.config import Settings

RATE = 22_050  # every configured Piper voice
FADE = int(RATE * 0.008)  # 8 ms fades stop segment joins from clicking
GAP = np.zeros(int(RATE * 0.08), dtype="<i2")  # short pause between language segments


def _fade(x: np.ndarray, *, head: bool, tail: bool) -> np.ndarray:
    x = x.astype(np.float32)
    n = min(FADE, len(x) // 2)
    if n:
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        if head:
            x[:n] *= ramp
        if tail:
            x[-n:] *= ramp[::-1]
    return x.astype("<i2")


class Synthesizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._voices: dict[str, object] = {}

    def voice(self, voice_id: str):
        if voice_id not in self._voices:
            from piper import PiperVoice

            if not models.voice_available(self.settings, voice_id):
                raise LookupError(f"voice {voice_id} is not installed")
            path = models.voice_path(self.settings, voice_id)
            self._voices[voice_id] = PiperVoice.load(path, use_cuda=False)
        return self._voices[voice_id]

    def synthesize(self, text: str, voices: dict[str, str]):
        """Yield s16le PCM chunks at :data:`RATE`, one language segment after another.

        ``voices`` maps ``"en"``/``"hi"`` to installed voice IDs.
        """
        first = True
        for seg in segment.split(text):
            voice_id = voices.get(seg.language)
            if voice_id is None:
                raise LookupError(f"no {seg.language} voice selected")
            if not first:
                yield GAP.tobytes()
            first = False
            held: np.ndarray | None = None
            head = True
            for chunk in self.voice(voice_id).synthesize(seg.text):
                audio = np.frombuffer(chunk.audio_int16_bytes, dtype="<i2")
                if held is not None:
                    yield _fade(held, head=head, tail=False).tobytes()
                    head = False
                held = audio
            if held is not None:
                yield _fade(held, head=head, tail=True).tobytes()
