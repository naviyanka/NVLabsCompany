"""Windows local TTS through System.Speech (SAPI) and the OneCore voices (WinRT), run in a
Windows PowerShell 5.1 child.

Fully offline: no cloud voice is ever used. Text goes in on stdin and the WAV comes back
on stdout, so no audio file is written. Voices are whatever Windows has installed; NEXUS
never installs or downloads one. Voice IDs are ``win:<SAPI voice name>`` and
``winrt:<OneCore voice name>``.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
import wave

import numpy as np

PREFIXES = ("win:", "winrt:")  # SAPI, OneCore
ONECORE = "winrt:"
PS = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
_TTL = 30.0
_cache: tuple[float, list[dict]] | None = None

_LIST_SAPI = (
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.GetInstalledVoices()|Where-Object{$_.Enabled}|ForEach-Object{$i=$_.VoiceInfo;"
    "[pscustomobject]@{name=$i.Name;locale=$i.Culture.Name;gender=[string]$i.Gender}}"
    "|ConvertTo-Json -Compress"
)
_WINRT = (
    "[void][Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,"
    "ContentType=WindowsRuntime];Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
)
_LIST_ONECORE = (
    _WINRT + "[Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices|ForEach-Object{"
    "[pscustomobject]@{name=$_.DisplayName;locale=$_.Language;gender=[string]$_.Gender}}"
    "|ConvertTo-Json -Compress"
)
_SAY_ONECORE = (
    _WINRT + "$t=(New-Object System.IO.StreamReader([Console]::OpenStandardInput(),"
    "[Text.Encoding]::UTF8)).ReadToEnd();"
    "$as=([System.WindowsRuntimeSystemExtensions].GetMethods()|Where-Object{$_.Name -eq 'AsTask'"
    " -and $_.GetParameters().Count -eq 1 -and "
    "$_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'})[0];"
    "$s=New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer;"
    "$s.Voice=[Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices|"
    "Where-Object{$_.DisplayName -eq $env:NEXUS_WIN_VOICE}|Select-Object -First 1;"
    "if(-not $s.Voice){exit 3};"
    "$k=$as.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])"
    ".Invoke($null,@($s.SynthesizeTextToStreamAsync($t)));[void]$k.Wait(-1);"
    "$i=[System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($k.Result);"
    "$m=New-Object System.IO.MemoryStream;$i.CopyTo($m);"
    "$o=[Console]::OpenStandardOutput();$b=$m.ToArray();$o.Write($b,0,$b.Length);$o.Flush()"
)
# The voice name is read from the environment and the text from stdin, never interpolated.
_SAY_SAPI = (
    "Add-Type -AssemblyName System.Speech;"
    "$t=(New-Object System.IO.StreamReader([Console]::OpenStandardInput(),"
    "[Text.Encoding]::UTF8)).ReadToEnd();"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.SelectVoice($env:NEXUS_WIN_VOICE);"
    "$m=New-Object System.IO.MemoryStream;$s.SetOutputToWaveStream($m);$s.Speak($t);"
    "$o=[Console]::OpenStandardOutput();$b=$m.ToArray();$o.Write($b,0,$b.Length);$o.Flush()"
)


def available() -> bool:
    return sys.platform == "win32"


def _run(script: str, *, stdin: bytes = b"", env: dict | None = None) -> bytes:
    import os

    out = subprocess.run(  # noqa: S603
        [*PS, "-Command", script],
        input=stdin,
        capture_output=True,
        timeout=30,
        env={**os.environ, **(env or {})},
    )
    if out.returncode:
        raise RuntimeError(
            out.stderr.decode("utf-8", "replace").strip()[:200] or "powershell failed"
        )
    return out.stdout


def _list(script: str, prefix: str) -> list[dict]:
    try:
        raw = _run(script).decode("utf-8", "replace").strip()
        data = json.loads(raw) if raw else []
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return []
    return [{**v, "prefix": prefix} for v in ([data] if isinstance(data, dict) else data)]


def voices(*, refresh: bool = False) -> list[dict]:
    """Installed Windows voices as ``{name, locale, gender, prefix}``; ``[]`` off Windows."""
    global _cache
    if not available():
        return []
    if refresh or _cache is None or time.monotonic() - _cache[0] > _TTL:
        found = _list(_LIST_SAPI, "win:") + _list(_LIST_ONECORE, ONECORE)
        _cache = (time.monotonic(), found)
    return _cache[1]


def language(locale: str) -> str | None:
    tag = locale.lower()
    return "hi" if tag.startswith("hi") else "en" if tag.startswith("en") else None


def catalog() -> dict[str, dict]:
    """Catalogue entries for :mod:`nexus_voice.models`, keyed by voice ID."""
    out = {}
    for v in voices():
        lang = language(v["locale"])
        if lang:
            out[v["prefix"] + v["name"]] = {
                "language": lang,
                "locale": v["locale"],
                "gender": v["gender"],
                "license": "Installed by Windows; Microsoft terms apply, not verified by NEXUS",
                "commercial": None,
                "attribution": None,
                "source": "Windows OneCore" if v["prefix"] == ONECORE else "Windows System.Speech",
                "revision": None,
                "origin": "system",
                "provider": "windows-onecore" if v["prefix"] == ONECORE else "windows-sapi",
                "url_base": None,
                "files": {},
            }
    return out


def to_pcm(wav: bytes, rate: int) -> bytes:
    """WAV bytes (any PCM rate, mono or stereo, 8/16 bit) to mono s16le at ``rate``."""
    with wave.open(io.BytesIO(wav)) as w:
        ch, width, src = w.getnchannels(), w.getsampwidth(), w.getframerate()
        frames = w.readframes(w.getnframes())
    if width == 1:
        x = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) * 256
    elif width == 2:
        x = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    else:
        raise ValueError(f"unsupported sample width {width}")
    if ch > 1:
        x = x[: len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
    if src != rate and len(x):
        n = int(len(x) * rate / src)
        # ponytail: linear interpolation; fine for speech, use a polyphase filter if quality matters
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return np.clip(x, -32768, 32767).astype("<i2").tobytes()


def synthesize(voice_id: str, text: str, rate: int) -> bytes:
    """Speak ``text`` with an installed Windows voice; raises ``LookupError`` if it is gone."""
    onecore = voice_id.startswith(ONECORE)
    name = voice_id.removeprefix(ONECORE if onecore else "win:")
    if voice_id not in {v["prefix"] + v["name"] for v in voices(refresh=True)}:
        raise LookupError(f"voice {voice_id} is not installed (removed from Windows?)")
    try:
        wav = _run(
            _SAY_ONECORE if onecore else _SAY_SAPI,
            stdin=text.encode("utf-8"),
            env={"NEXUS_WIN_VOICE": name},
        )
        return to_pcm(wav, rate)
    except (RuntimeError, ValueError, wave.Error, subprocess.SubprocessError) as e:
        raise LookupError(f"Windows voice {voice_id} failed: {e}") from e
