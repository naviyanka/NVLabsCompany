"""Model manifest: download into the local model directory, verify size and SHA-256.

Model files never live in Git; ``manifest.json`` pins source revisions and hashes.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

from nexus_voice.config import MANIFEST, Settings


def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stt_dir(settings: Settings) -> Path:
    return settings.model_dir / "stt" / manifest()["stt"]["id"]


def voice_path(settings: Settings, voice_id: str) -> Path:
    return settings.model_dir / "voices" / voice_id / f"{voice_id}.onnx"


def _entries(settings: Settings):
    m = manifest()
    for name, meta in m["stt"]["files"].items():
        yield m["stt"], stt_dir(settings) / name, name, meta
    for vid, v in m["voices"].items():
        for name, meta in v["files"].items():
            yield v, settings.model_dir / "voices" / vid / name, name, meta


def check(path: Path, meta: dict[str, Any], *, full: bool) -> bool:
    """Present, the pinned size, and (when ``full``) the pinned SHA-256."""
    if not path.is_file() or path.stat().st_size != meta["size"]:
        return False
    return not full or meta["sha256"] is None or sha256(path) == meta["sha256"]


def stt_available(settings: Settings, *, full: bool = False) -> bool:
    m = manifest()["stt"]
    return all(check(stt_dir(settings) / n, meta, full=full) for n, meta in m["files"].items())


def voice_available(settings: Settings, voice_id: str, *, full: bool = False) -> bool:
    v = manifest()["voices"].get(voice_id)
    return bool(v) and all(
        check(settings.model_dir / "voices" / voice_id / n, meta, full=full)
        for n, meta in v["files"].items()
    )


def voices_for(language: str) -> list[str]:
    return [k for k, v in manifest()["voices"].items() if v["language"] == language]


def setup(settings: Settings, *, pin: bool = False, only: list[str] | None = None) -> list[str]:
    """Download what is missing and verify it. ``pin`` records hashes not yet in the manifest."""
    log: list[str] = []
    data = manifest()
    for meta_src, path, name, meta in list(_entries(settings)):
        key = "stt" if path.parent.parent.name == "stt" else path.parent.name
        if only and key not in only:
            continue
        if not check(path, meta, full=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            urllib.request.urlretrieve(f"{meta_src['url_base']}/{name}", tmp)  # noqa: S310
            tmp.replace(path)
            log.append(f"downloaded {path.parent.name}/{name}")
        digest = sha256(path)
        if meta["sha256"] is None:
            if not pin:
                raise RuntimeError(f"{name}: no pinned SHA-256 (run setup --pin once)")
            _record(data, path, name, digest)
            log.append(f"pinned {name}")
        elif digest != meta["sha256"]:
            path.unlink()
            raise RuntimeError(f"{name}: SHA-256 mismatch; file removed")
    if pin:
        MANIFEST.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return log


def _record(data: dict[str, Any], path: Path, name: str, digest: str) -> None:
    section = data["stt"] if path.parent.parent.name == "stt" else data["voices"][path.parent.name]
    section["files"][name]["sha256"] = digest
