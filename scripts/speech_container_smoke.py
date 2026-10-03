"""Offline Linux smoke for the Azure Speech SDK and the NEXUS adapter.

Runs inside a ``python:3.12-slim`` image that was built with the ``speech`` extra, with the network
disabled (``docker run --network none``; see docker/speech-smoke/Dockerfile). It makes no
connection, requests no token and opens no audio device. It fails (non-zero exit, one ``FAIL:``
line per problem) if the SDK or its native libraries cannot be loaded, if a loaded native library
has an unresolved dependency, or if anything touched an audio device.

Nothing here is a live test: construction of SDK objects is local and a fake credential is used.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

PINNED_SDK = "1.52.0"
failures: list[str] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        failures.append(message)


def mapped_libs() -> set[str]:
    maps = Path("/proc/self/maps").read_text()
    return {Path(line.split()[-1]).name for line in maps.splitlines() if ".so" in line}


def audio_fds() -> list[str]:
    found = []
    for fd in Path("/proc/self/fd").iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("/dev/snd") or "pulse" in target or "alsa" in target.lower():
            found.append(target)
    return found


def ldd_report(sdk_dir: Path) -> dict[str, list[str]]:
    """Map each SDK native library to the dependencies ldd cannot resolve."""
    missing: dict[str, list[str]] = {}
    for lib in sorted(sdk_dir.glob("*.so*")):
        out = subprocess.run(["ldd", str(lib)], capture_output=True, text=True, timeout=30).stdout
        bad = sorted(m.group(1) for m in re.finditer(r"^\s*(\S+) => not found", out, re.M))
        missing[lib.name] = bad
    return missing


def main() -> int:
    report: dict[str, object] = {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "libc": platform.libc_ver()[0],
    }

    # No network namespace: only loopback may exist, and nothing may be configured for Azure.
    nets = sorted(p.name for p in Path("/sys/class/net").iterdir())
    report["network_interfaces"] = nets
    check(nets in (["lo"], []), f"network is not disabled: {nets}")
    for key in list(os.environ):
        check(not key.startswith("AZURE_"), f"unexpected Azure environment variable: {key}")
    check(not Path("/dev/snd").exists(), "/dev/snd exists in the smoke container")

    # Import the SDK and the adapter.
    import azure.cognitiveservices.speech as speechsdk
    from azure.core.credentials import AccessToken, TokenCredential

    from nexus.voice import azure_speech as az

    sdk_dir = Path(speechsdk.__file__).parent
    from importlib.metadata import version

    report["sdk_version"] = version("azure-cognitiveservices-speech")
    check(report["sdk_version"] == PINNED_SDK, f"SDK version {report['sdk_version']}")

    # Disabled by default, status() works with no network and shows no secret.
    status = az.status()
    report["status_enabled"] = status.get("enabled")
    report["status_reason"] = status.get("unavailable_reason") or status.get("reason")
    check(status.get("enabled") is False, "Azure Speech is not disabled by default")

    # Build the objects the adapter builds, with fake non-secret values, without connecting.
    class FakeCredential:
        calls = 0

        def get_token(self, *scopes, **kwargs):  # pragma: no cover - must never run
            FakeCredential.calls += 1
            return AccessToken("fake", 4_000_000_000)

    cred = az._ScopedCredential(FakeCredential())
    check(isinstance(cred, TokenCredential), "scoped credential is not a TokenCredential")
    config = speechsdk.SpeechConfig(
        endpoint=az.ENDPOINT_SHAPE.replace("<custom-subdomain>", "smoke"), token_credential=cred
    )
    config.output_format = speechsdk.OutputFormat.Detailed
    config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
    )
    fmt = speechsdk.audio.AudioStreamFormat(
        samples_per_second=16000, bits_per_sample=16, channels=1
    )
    push = speechsdk.audio.PushAudioInputStream(stream_format=fmt)
    audio = speechsdk.audio.AudioConfig(stream=push)
    reco = speechsdk.SpeechRecognizer(speech_config=config, audio_config=audio, language="hi-IN")
    auto = speechsdk.AutoDetectSourceLanguageConfig(languages=["en-IN", "hi-IN"])
    config.set_property(speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "AtStart")
    auto_reco = speechsdk.SpeechRecognizer(
        speech_config=config, audio_config=audio, auto_detect_source_language_config=auto
    )
    synth = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)  # None: no speaker
    for name in ("recognizing", "recognized", "canceled", "session_stopped"):
        getattr(reco, name).connect(lambda _evt: None)
    for name in ("synthesizing", "synthesis_completed", "synthesis_canceled"):
        getattr(synth, name).connect(lambda _evt: None)
    push.write(b"\x00\x00" * 160)  # local buffer only; nothing consumes it
    push.close()
    check(cred.token_requests == 0 and FakeCredential.calls == 0, "construction requested a token")

    # Native libraries: every one the SDK ships must resolve, or be shown never to have loaded.
    loaded = mapped_libs()
    report["native_libs_loaded"] = sorted(n for n in loaded if "Speech" in n or "asound" in n)
    missing = ldd_report(sdk_dir)
    report["ldd_unresolved"] = {k: v for k, v in missing.items() if v}
    report["sdk_native_libs"] = sorted(missing)
    check(bool(missing), "no native libraries found next to the SDK")
    for lib, bad in missing.items():
        if bad:
            check(lib not in loaded, f"loaded library {lib} has unresolved dependencies: {bad}")
    check(not any("asound" in name for name in loaded), "libasound was loaded on the stream path")
    check(not audio_fds(), f"audio device file descriptor open: {audio_fds()}")

    del auto_reco, reco, synth
    report["failures"] = failures
    print(json.dumps(report, indent=2, sort_keys=True))
    for message in failures:
        print(f"FAIL: {message}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
