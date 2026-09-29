"""Streaming Silero VAD: cuts a 16 kHz mono stream into utterances.

Uses the Silero VAD v6 ONNX model bundled with faster-whisper, run one 32 ms frame
at a time with the recurrent state carried between calls.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

FRAME = 512  # samples, 32 ms at 16 kHz
CONTEXT = 64
FRAME_MS = 32


class SileroModel:
    """Frame probabilities with carried state; one instance per audio stream."""

    def __init__(self) -> None:
        import os

        import faster_whisper
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        path = os.path.join(os.path.dirname(faster_whisper.__file__), "assets", "silero_vad_v6.onnx")
        self.session = ort.InferenceSession(path, providers=["CPUExecutionProvider"], sess_options=opts)
        self.reset()

    def reset(self) -> None:
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros(CONTEXT, dtype=np.float32)

    def __call__(self, frames: np.ndarray) -> np.ndarray:
        """``frames``: (k, 512) float32. Returns k speech probabilities."""
        prev = np.concatenate([self.context[None, :], frames[:-1, -CONTEXT:]], axis=0)
        batch = np.concatenate([prev, frames], axis=1)
        probs, self.h, self.c = self.session.run(None, {"input": batch, "h": self.h, "c": self.c})
        self.context = frames[-1, -CONTEXT:].copy()
        return probs.reshape(-1)


@dataclass
class VadEvent:
    kind: str  # speech_started | utterance | noise
    audio: np.ndarray | None = None
    reason: str = ""


class UtteranceDetector:
    """Frame-by-frame utterance boundaries with pre-roll and bounded length."""

    def __init__(
        self,
        model: Callable[[np.ndarray], np.ndarray],
        *,
        silence_ms: int = 700,
        max_utterance_s: float = 30.0,
        threshold: float = 0.5,
        min_speech_ms: int = 96,
        min_utterance_ms: int = 250,
    ) -> None:
        self.model = model
        self.silence_frames = max(1, silence_ms // FRAME_MS)
        self.max_frames = int(max_utterance_s * 1000 / FRAME_MS)
        self.threshold, self.neg = threshold, threshold - 0.15
        self.start_frames = max(1, min_speech_ms // FRAME_MS)
        self.min_frames = max(1, min_utterance_ms // FRAME_MS)
        self.pending = np.zeros(0, dtype=np.float32)
        self.preroll: deque[np.ndarray] = deque(maxlen=10)
        self.buffer: list[np.ndarray] = []
        self.speaking = False
        self.run = 0
        self.silence = 0
        self.speech_frames = 0

    @property
    def buffered_ms(self) -> int:
        return len(self.buffer) * FRAME_MS

    def snapshot(self) -> np.ndarray:
        """Audio of the utterance so far (for an unstable partial transcript)."""
        return np.concatenate(self.buffer) if self.buffer else np.zeros(0, dtype=np.float32)

    def feed(self, samples: np.ndarray) -> list[VadEvent]:
        self.pending = np.concatenate([self.pending, samples])
        usable = len(self.pending) // FRAME * FRAME
        if not usable:
            return []
        frames = self.pending[:usable].reshape(-1, FRAME)
        self.pending = self.pending[usable:]
        events: list[VadEvent] = []
        for frame, p in zip(frames, self.model(frames)):
            events.extend(self._step(frame, float(p)))
        return events

    def _step(self, frame: np.ndarray, p: float) -> list[VadEvent]:
        events: list[VadEvent] = []
        if not self.speaking:
            self.preroll.append(frame)
            self.run = self.run + 1 if p >= self.threshold else 0
            if self.run >= self.start_frames:
                self.speaking, self.silence = True, 0
                self.buffer = list(self.preroll)
                self.speech_frames = self.run
                self.preroll.clear()
                events.append(VadEvent("speech_started"))
            return events
        self.buffer.append(frame)
        if p >= self.threshold:
            self.silence = 0
            self.speech_frames += 1
        elif p < self.neg:
            self.silence += 1
        if self.silence >= self.silence_frames:
            events.append(self._finish("silence"))
        elif len(self.buffer) >= self.max_frames:
            events.append(self._finish("max_duration"))
        return events

    def _finish(self, reason: str) -> VadEvent:
        audio, speech = np.concatenate(self.buffer), self.speech_frames
        self.buffer, self.speaking, self.run, self.silence, self.speech_frames = [], False, 0, 0, 0
        self.preroll.clear()
        if speech < self.min_frames:
            return VadEvent("noise", reason=reason)
        return VadEvent("utterance", audio, reason)

    def flush(self) -> list[VadEvent]:
        """Push-to-talk release: close whatever utterance is open."""
        if not self.speaking:
            self.preroll.clear()
            self.pending = np.zeros(0, dtype=np.float32)
            return []
        self.pending = np.zeros(0, dtype=np.float32)
        return [self._finish("flush")]
