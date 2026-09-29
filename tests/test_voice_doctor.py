"""``nexus doctor --voice``: statuses, JSON, and that it never touches secrets or models."""

from __future__ import annotations

import json
import subprocess

import pytest

from nexus.config import settings
from nexus.voice import doctor

pytestmark = pytest.mark.core_employee

SECRET = "doctor-test-secret-0123456789abcdefghij"
GOOD = {
    "python": "3.11.16",
    "gpu": "NVIDIA RTX 3050, 617.14, 6144 MiB",
    "ffmpeg": "ffmpeg version 9.0",
    "ctranslate2_cuda": True,
    "selected_device": "cuda",
    "selected_compute_type": "int8_float16",
    "fallback_reason": None,
    "stt_model_available": True,
    "stt_model": {"id": "m", "revision": "08e178d4aaaa", "license": "MIT"},
    "vad_model": {"id": "silero", "license": "MIT", "installed": True},
    "voices": [
        {
            "id": "en1",
            "language": "en",
            "installed": True,
            "selectable": True,
            "restricted": False,
            "license": "Public domain",
        },
        {
            "id": "hi1",
            "language": "hi",
            "installed": False,
            "selectable": False,
            "restricted": True,
            "license": "CC BY-NC-SA 4.0",
        },
    ],
}


@pytest.fixture
def probes(monkeypatch):
    monkeypatch.setattr(settings, "voice_worker_secret", SECRET)
    monkeypatch.setattr(settings, "voice_allow_local_state", False)
    monkeypatch.setattr(doctor, "worker_diagnosis", lambda: dict(GOOD))

    async def health(path):
        return {"ok": True, "protocol": 1}

    async def shared():
        return doctor._check("shared_state", doctor.PASS, "ok")

    monkeypatch.setattr(doctor.worker_client, "worker_get", health)
    monkeypatch.setattr(doctor, "_shared_state", shared)
    monkeypatch.setattr(
        doctor, "_hermes", lambda: doctor._check("hermes_native", doctor.PASS, "ready")
    )


def statuses(report):
    return {c["id"]: c["status"] for c in report["checks"]}


async def test_healthy_machine_still_needs_live_checks(probes):
    report = await doctor.run()
    s = statuses(report)
    assert s["browser_microphone"] == doctor.LIVE  # the CLI can never test a microphone
    assert s["tts_hi"] == doctor.LIVE  # no commercial Hindi voice: live check, not a pass
    assert s["ceo_designation"] == s["organization_snapshot"] == s["omniroute"] == doctor.LIVE
    assert s["tts_en"] == s["stt_model"] == s["worker_protocol"] == doctor.PASS
    assert report["status"] == doctor.LIVE
    assert any(c.get("vram_mib") == "6144" for c in report["checks"])


async def test_failures_and_degradation_are_ranked(probes, monkeypatch):
    monkeypatch.setattr(
        doctor, "worker_diagnosis", lambda: {**GOOD, "python": "3.14.0", "selected_device": "cpu"}
    )

    async def down(path):
        return None

    monkeypatch.setattr(doctor.worker_client, "worker_get", down)
    s = statuses(await doctor.run())
    assert s["worker_python"] == s["worker_reachable"] == s["worker_protocol"] == doctor.FAIL
    assert s["stt_device"] == doctor.DEGRADED
    assert (await doctor.run())["status"] == doctor.FAIL


async def test_missing_worker_env_fails_worker_checks(probes, monkeypatch):
    monkeypatch.setattr(doctor, "worker_diagnosis", lambda: None)
    s = statuses(await doctor.run())
    assert s["ffmpeg"] == s["stt_model"] == doctor.FAIL


async def test_only_noncommercial_english_voice_is_degraded(probes, monkeypatch):
    voices = [
        {
            "id": "x",
            "language": "en",
            "installed": True,
            "selectable": True,
            "restricted": True,
            "license": "CC BY-NC",
        }
    ]
    monkeypatch.setattr(doctor, "worker_diagnosis", lambda: {**GOOD, "voices": voices})
    assert statuses(await doctor.run())["tts_en"] == doctor.DEGRADED


async def test_output_never_contains_the_secret(probes, capsys):
    report = await doctor.run()
    assert SECRET not in json.dumps(report) and SECRET not in doctor.render(report)
    assert statuses(report)["worker_secret"] == doctor.PASS


async def test_short_secret_fails(probes, monkeypatch):
    monkeypatch.setattr(settings, "voice_worker_secret", "short")
    assert statuses(await doctor.run())["worker_secret"] == doctor.FAIL


def test_worker_diagnosis_never_loads_models_or_downloads(monkeypatch, tmp_path):
    exe = tmp_path / "python"
    exe.write_text("")
    monkeypatch.setenv("NEXUS_VOICE_PYTHON", str(exe))
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", fake)
    doctor.worker_diagnosis()
    assert "diagnose" in seen["cmd"] and "--no-load" in seen["cmd"] and "setup" not in seen["cmd"]


def test_cli_prints_json_and_exits_nonzero_on_failure(monkeypatch, capsys):
    async def fake(company_id=None):
        return {"status": doctor.FAIL, "checks": [doctor._check("x", doctor.FAIL, "bad")]}

    monkeypatch.setattr(doctor, "run", fake)
    from nexus import cli

    assert cli.main(["doctor", "--voice", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == doctor.FAIL
    assert cli.main(["nope"]) == 2
