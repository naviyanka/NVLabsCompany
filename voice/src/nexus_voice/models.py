"""Model manifest: download into the local model directory, verify size and SHA-256.

Model files never live in Git; ``manifest.json`` pins source revisions and hashes.
"""

from __future__ import annotations

import hashlib
import json
import re
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


USER_MANIFEST = "user_voices.json"
VOICE_ID = re.compile(r"^[a-z]{2}_[A-Z]{2}-[a-z0-9_]+-(x_low|low|medium|high)$")


def user_voices(settings: Settings) -> dict[str, Any]:
    """Voices the operator supplied in ``<model_dir>/user_voices.json``; never downloaded.

    Each needs ``language``, ``license``, ``commercial`` and hashed ``files``. The
    operator's ``commercial`` claim is kept as declared and is not verified by NEXUS.
    """
    path = settings.model_dir / USER_MANIFEST
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("voices", {})
    except (OSError, ValueError, AttributeError):
        return {}
    out = {}
    for vid, v in raw.items():
        files = v.get("files") if isinstance(v, dict) else None
        ok = (
            VOICE_ID.match(vid)
            and v.get("language") in ("en", "hi")
            and v.get("license")
            and isinstance(files, dict)
            and files
            and all(f.get("sha256") and f.get("size") for f in files.values())
        )
        if ok and vid not in manifest()["voices"]:
            out[vid] = {**v, "origin": "user", "url_base": None}
    return out


def catalog(settings: Settings) -> dict[str, Any]:
    return {
        **{k: {**v, "origin": "bundled"} for k, v in manifest()["voices"].items()},
        **user_voices(settings),
    }


def restricted(voice: dict[str, Any]) -> bool:
    """Anything not positively marked commercial-use is restricted (unknown counts)."""
    return voice.get("commercial") is not True


def selectable(settings: Settings, voice_id: str) -> bool:
    v = catalog(settings).get(voice_id)
    return v is not None and (settings.allow_noncommercial or not restricted(v))


def voice_info(settings: Settings, *, full: bool = False) -> list[dict[str, Any]]:
    keys = ("language", "license", "commercial", "attribution", "source", "revision", "origin")
    return [
        {
            "id": vid,
            **{k: v.get(k) for k in keys},
            "restricted": restricted(v),
            "selectable": settings.allow_noncommercial or not restricted(v),
            "installed": voice_available(settings, vid, full=full),
        }
        for vid, v in catalog(settings).items()
    ]


def vad_installed() -> bool:
    import importlib.util

    spec = importlib.util.find_spec("faster_whisper")
    root = Path(spec.origin).parent if spec and spec.origin else None
    return bool(root and (root / "assets" / "silero_vad_v6.onnx").is_file())


def stt_dir(settings: Settings) -> Path:
    return settings.model_dir / "stt" / manifest()["stt"]["id"]


def voice_path(settings: Settings, voice_id: str) -> Path:
    return settings.model_dir / "voices" / voice_id / f"{voice_id}.onnx"


def _entries(settings: Settings):
    m = manifest()
    for name, meta in m["stt"]["files"].items():
        yield m["stt"], stt_dir(settings) / name, name, meta
    for vid, v in catalog(settings).items():
        if not v.get("url_base") or not selectable(settings, vid):
            continue  # user-supplied, or restricted while the opt-in is off: never downloaded
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
    v = catalog(settings).get(voice_id)
    return bool(v) and all(
        check(settings.model_dir / "voices" / voice_id / n, meta, full=full)
        for n, meta in v["files"].items()
    )


def voices_for(language: str, settings: Settings | None = None) -> list[str]:
    """Voice IDs for a language; with ``settings`` only those allowed to be selected."""
    cat = catalog(settings) if settings else manifest()["voices"]
    return [
        k
        for k, v in cat.items()
        if v["language"] == language and (settings is None or selectable(settings, k))
    ]


def setup(settings: Settings, *, pin: bool = False, only: list[str] | None = None) -> list[str]:
    """Download what is missing and verify it. ``pin`` records hashes not yet in the manifest."""
    log: list[str] = []
    data = manifest()
    for name in only or []:
        v = catalog(settings).get(name)
        if v is not None and not selectable(settings, name):
            raise RuntimeError(
                f"{name} is not licensed for commercial use ({v['license']}); "
                "set NEXUS_VOICE_ALLOW_NONCOMMERCIAL_MODELS=true to opt in"
            )
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
