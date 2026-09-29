"""Worker settings, read from ``NEXUS_VOICE_*`` environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST = Path(__file__).with_name("manifest.json")


def _default_model_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "nexus-voice" / "models"


@dataclass(frozen=True)
class Settings:
    model_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("NEXUS_VOICE_MODEL_DIR") or _default_model_dir()
        )
    )
    stt_model: str = os.environ.get("NEXUS_VOICE_STT_MODEL", "faster-whisper-medium")
    device: str = os.environ.get("NEXUS_VOICE_DEVICE", "auto")  # auto | cuda | cpu
    host: str = "127.0.0.1"  # loopback only; not configurable
    port: int = int(os.environ.get("NEXUS_VOICE_PORT", "8765"))
    # Shared with the NEXUS backend, which alone mints the short-lived tokens.
    secret: str = os.environ.get("NEXUS_VOICE_WORKER_SECRET", "")
    max_utterance_s: float = float(os.environ.get("NEXUS_VOICE_MAX_UTTERANCE_S", "30"))
    max_frame_bytes: int = 8192
    silence_ms: int = int(os.environ.get("NEXUS_VOICE_SILENCE_MS", "700"))
    partials: bool = os.environ.get("NEXUS_VOICE_PARTIALS", "0") == "1"
