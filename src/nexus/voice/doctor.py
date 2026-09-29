"""``nexus doctor --voice``: read-only readiness report for the local CEO voice gateway.

Never opens a microphone, calls a paid model, creates a chat turn, invokes a CEO tool,
downloads a model or reveals a secret. Worker-environment facts come from the worker's own
``diagnose --no-load`` in its separate Python 3.11 env; everything else is a cheap probe.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nexus.config import settings
from nexus.voice import protocol, worker_client

PASS, FAIL, DEGRADED, LIVE = "PASS", "FAIL", "DEGRADED", "LIVE_CHECK_REQUIRED"
_ORDER = (FAIL, DEGRADED, LIVE, PASS)  # worst first
WORKER_DIR = Path(__file__).resolve().parents[3] / "voice"
_SCRIPTS = "Scripts/python.exe" if os.name == "nt" else "bin/python"


def _check(id_: str, status: str, detail: str) -> dict[str, str]:
    return {"id": id_, "status": status, "detail": detail}


def _worker_python() -> Path | None:
    env = os.environ.get("NEXUS_VOICE_PYTHON")
    exe = Path(env) if env else WORKER_DIR / ".venv" / _SCRIPTS
    return exe if exe.is_file() else None


def worker_diagnosis() -> dict[str, Any] | None:
    """The worker env's own diagnosis (no model load, no download); None if it cannot run."""
    exe = _worker_python()
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [str(exe), "-m", "nexus_voice.cli", "diagnose", "--no-load", "--full"],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=WORKER_DIR,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return json.loads(out.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _tts_check(voices: list[dict[str, Any]], lang: str) -> dict[str, str]:
    label = f"tts_{lang}"
    ready = [v for v in voices if v["language"] == lang and v["installed"] and v["selectable"]]
    if not ready:
        if lang == "hi":
            return _check(
                label,
                LIVE,
                "no commercially licensed Hindi voice installed; supply one via user_voices.json",
            )
        return _check(label, FAIL, "no selectable English voice installed (nexus-voice setup)")
    only_restricted = all(v["restricted"] for v in ready)
    detail = ", ".join(f"{v['id']} ({(v['license'] or '')[:40]})" for v in ready)
    if only_restricted:
        detail += "; non-commercial voice only"
    return _check(label, DEGRADED if only_restricted else PASS, detail)


def _worker_checks(d: dict[str, Any] | None) -> list[dict[str, str]]:
    if d is None:
        why = "worker env not found (cd voice && uv sync) or its diagnose failed"
        return [_check(i, FAIL, why) for i in ("ffmpeg", "worker_python", "stt_model")]
    out = [
        _check("ffmpeg", PASS, d["ffmpeg"])
        if d.get("ffmpeg")
        else _check("ffmpeg", FAIL, "ffmpeg not on PATH")
    ]
    py = d.get("python", "")
    out.append(
        _check(
            "worker_python",
            PASS if py.startswith("3.11.") else FAIL,
            f"Python {py}; worker needs 3.11",
        )
    )
    gpu = d.get("gpu")
    out.append(_check("gpu", PASS if gpu else DEGRADED, gpu or "no NVIDIA GPU: CPU int8 fallback"))
    vram = re.search(r"(\d+) MiB", gpu or "")
    if vram:
        out[-1]["vram_mib"] = vram.group(1)
    cuda = d.get("ctranslate2_cuda")
    out.append(
        _check(
            "ctranslate2_cuda",
            PASS if cuda else DEGRADED,
            "CUDA usable" if cuda else "CUDA not usable: CPU fallback",
        )
    )
    reason = f" ({d['fallback_reason']})" if d.get("fallback_reason") else ""
    out.append(
        _check(
            "stt_device",
            PASS if d.get("selected_device") == "cuda" else DEGRADED,
            f"{d.get('selected_device')}/{d.get('selected_compute_type')}{reason}",
        )
    )
    m = d.get("stt_model", {})
    ok = d.get("stt_model_available")
    out.append(
        _check(
            "stt_model",
            PASS if ok else FAIL,
            f"{m.get('id')}@{str(m.get('revision'))[:8]} license {m.get('license')}; "
            + (
                "files and SHA-256 verified"
                if ok
                else "not installed or hash mismatch (nexus-voice setup)"
            ),
        )
    )
    v = d.get("vad_model", {})
    out.append(
        _check(
            "vad_model",
            PASS if v.get("installed") else FAIL,
            f"{v.get('id')} license {v.get('license')}",
        )
    )
    voices = d.get("voices", [])
    return out + [_tts_check(voices, "en"), _tts_check(voices, "hi")]


async def _worker_link() -> list[dict[str, str]]:
    has_secret = len(settings.voice_worker_secret) >= 32
    health = await worker_client.worker_get("/health")
    got = (health or {}).get("protocol")
    return [
        _check(
            "worker_secret",
            PASS if has_secret else FAIL,
            "configured" if has_secret else "VOICE_WORKER_SECRET missing or under 32 chars",
        ),
        _check(
            "worker_reachable",
            PASS if health else FAIL,
            "loopback worker answered /health"
            if health
            else f"no answer at {settings.voice_worker_url}",
        ),
        _check(
            "worker_protocol",
            PASS if got == protocol.VERSION else FAIL,
            f"worker protocol {got}, gateway {protocol.VERSION}",
        ),
    ]


async def _shared_state() -> dict[str, str]:
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        await client.ping()
        return _check(
            "shared_state", PASS, "Redis reachable: tickets, rate limits and revocation are shared"
        )
    except Exception as exc:  # noqa: BLE001
        if settings.voice_allow_local_state:
            return _check(
                "shared_state",
                DEGRADED,
                "Redis unreachable; VOICE_ALLOW_LOCAL_STATE: single-process memory store",
            )
        return _check(
            "shared_state", FAIL, f"Redis unreachable ({type(exc).__name__}); voice fails closed"
        )
    finally:
        with_close = getattr(client, "aclose", None)
        if with_close:
            await with_close()


async def _gateway(urls: list[str]) -> dict[str, str]:
    """First active LLM connection (OmniRoute): unauthenticated GET, no key is sent."""
    import httpx

    if not urls:
        return _check("omniroute", DEGRADED, "no active LLM connection configured")
    u = urlparse(urls[0])
    where = f"{u.scheme}://{u.hostname}" + (f":{u.port}" if u.port else "")
    try:
        async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False) as http:
            r = await http.get(urls[0].rstrip("/") + "/models")
        return _check(
            "omniroute",
            PASS if r.status_code < 500 else FAIL,
            f"{where} answered {r.status_code}; no credentials sent",
        )
    except httpx.HTTPError as exc:
        return _check("omniroute", FAIL, f"{where} unreachable ({type(exc).__name__})")


async def _company_checks(company_id: uuid.UUID | None) -> list[dict[str, str]]:
    ids = ("ceo_designation", "organization_snapshot", "omniroute")
    if company_id is None:
        return [_check(i, LIVE, "pass --company <id> to check") for i in ids]
    from sqlalchemy import select

    from nexus.database import tenant_session
    from nexus.models.connection import LLMConnection
    from nexus.services import ceo_service, org_snapshot

    try:
        async with tenant_session(company_id) as db:
            ceo = await ceo_service.current_ceo(db, company_id)
            snap = await org_snapshot.read(db, company_id)
            rows = await db.execute(
                select(LLMConnection).where(
                    LLMConnection.company_id == company_id, LLMConnection.is_active.is_(True)
                )
            )
            urls = [c.base_url for c in rows.scalars().all()]
    except Exception as exc:  # noqa: BLE001
        return [_check(i, FAIL, f"database check failed ({type(exc).__name__})") for i in ids]
    fresh = snap["freshness"]
    status = FAIL if not snap["version"] else PASS if fresh["status"] == "fresh" else DEGRADED
    return [
        _check(
            "ceo_designation",
            PASS if ceo else FAIL,
            "CEO designated" if ceo else "no CEO designated",
        ),
        _check(
            "organization_snapshot",
            status,
            f"version {snap['version']}, {fresh['status']}, age {fresh['age_seconds']}s",
        ),
        await _gateway(urls),
    ]


def _hermes() -> dict[str, str]:
    from nexus.adapters import hermes_provider

    why = hermes_provider.unavailable_reason()
    return _check(
        "hermes_native", PASS if why is None else FAIL, why or "governed native tool turns ready"
    )


async def run(company_id: uuid.UUID | None = None) -> dict[str, Any]:
    checks = [
        _check(
            "browser_microphone",
            LIVE,
            "only a browser can test the microphone; use the voice panel's test",
        )
    ]
    checks += _worker_checks(await asyncio.to_thread(worker_diagnosis))
    checks += await _worker_link()
    checks.append(await _shared_state())
    checks += await _company_checks(company_id)
    checks.append(_hermes())
    status = next(s for s in _ORDER if any(c["status"] == s for c in checks))
    return {"status": status, "checks": checks}


def render(report: dict[str, Any]) -> str:
    lines = [f"{c['status']:<20} {c['id']:<22} {c['detail']}" for c in report["checks"]]
    return "\n".join([*lines, "", f"overall: {report['status']}"])


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="nexus doctor")
    ap.add_argument("--voice", action="store_true", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--company", type=uuid.UUID)
    args = ap.parse_args(argv)
    report = asyncio.run(run(args.company))
    sys.stdout.write((json.dumps(report, indent=2) if args.json else render(report)) + "\n")
    return 1 if report["status"] == FAIL else 0
