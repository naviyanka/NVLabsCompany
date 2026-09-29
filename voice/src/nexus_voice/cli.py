"""``nexus-voice``: diagnose, setup, serve."""

from __future__ import annotations

import argparse
import json
import sys

from nexus_voice.config import Settings


def diagnose(settings: Settings, *, full: bool = False, load_stt: bool = True) -> dict:
    from nexus_voice import audio, devices, models

    report: dict = {"gpu": devices.gpu_name(), "ffmpeg": audio.ffmpeg_version()}
    report["gpu_detected"] = report["gpu"] is not None
    report["ctranslate2_cuda"] = devices.cuda_available()
    device, compute = devices.choose(settings.device)
    reason = None
    if load_stt and models.stt_available(settings):
        from nexus_voice.stt import Transcriber

        stt = Transcriber(settings)
        device, compute, reason = stt.device, stt.compute_type, stt.fallback_reason
    report.update(selected_device=device, selected_compute_type=compute, fallback_reason=reason)
    report["ffmpeg_available"] = report["ffmpeg"] is not None
    report["stt_model_available"] = models.stt_available(settings, full=full)
    report["english_voice_available"] = any(
        models.voice_available(settings, v, full=full) for v in models.voices_for("en"))
    report["hindi_voice_available"] = any(
        models.voice_available(settings, v, full=full) for v in models.voices_for("hi"))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nexus-voice")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diagnose")
    d.add_argument("--full", action="store_true", help="verify SHA-256 of every model file")
    d.add_argument("--no-load", action="store_true", help="do not load the STT model")
    s = sub.add_parser("setup")
    s.add_argument("--pin", action="store_true")
    s.add_argument("only", nargs="*")
    sub.add_parser("serve")
    args = ap.parse_args(argv)
    settings = Settings()
    if args.cmd == "diagnose":
        print(json.dumps(diagnose(settings, full=args.full, load_stt=not args.no_load), indent=2))
    elif args.cmd == "setup":
        from nexus_voice import models

        for line in models.setup(settings, pin=args.pin, only=args.only or None):
            print(line)
    else:
        from nexus_voice.server import run

        run(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
