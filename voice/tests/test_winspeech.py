"""Windows TTS provider with a fake PowerShell: no OS voices needed."""

import io
import json
import wave

import numpy as np
import pytest
from nexus_voice import models, tts, winspeech
from nexus_voice.config import Settings

EN = {"name": "Microsoft Zira Desktop", "locale": "en-US", "gender": "Female"}
HI = {"name": "Microsoft Kalpana", "locale": "hi-IN", "gender": "Female"}


def wav(rate=16_000, ch=1, width=2, n=1600) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(ch), w.setsampwidth(width), w.setframerate(rate)
        w.writeframes(
            (np.full(n * ch, 1000, "<i2") if width == 2 else np.full(n * ch, 200, "u1")).tobytes()
        )
    return buf.getvalue()


@pytest.fixture
def fake(monkeypatch, tmp_path):
    state = {"voices": [EN], "said": [], "wav": wav()}

    def run(script, *, stdin=b"", env=None):
        if script is winspeech._LIST_SAPI:
            return json.dumps(state["voices"]).encode()
        if script is winspeech._LIST_ONECORE:
            return json.dumps(state.get("onecore", [])).encode()
        state["said"].append((stdin.decode(), env["NEXUS_WIN_VOICE"]))
        return state["wav"]

    monkeypatch.setattr(winspeech, "available", lambda: True)
    monkeypatch.setattr(winspeech, "_run", run)
    monkeypatch.setattr(winspeech, "_cache", None)
    return state, Settings(model_dir=tmp_path)


def test_enumeration_maps_locale_to_language(fake):
    state, s = fake
    state["voices"] = [EN, HI, {"name": "Microsoft Hazel", "locale": "fr-FR", "gender": "Female"}]
    cat = winspeech.catalog()
    assert set(cat) == {"win:Microsoft Zira Desktop", "win:Microsoft Kalpana"}
    assert cat["win:Microsoft Kalpana"]["language"] == "hi"


def test_hindi_unavailable_is_reported_not_faked(fake):
    _, s = fake
    info = models.voice_info(s)
    assert not any(v["language"] == "hi" and v["installed"] and v["selectable"] for v in info)
    assert models.voices_for("hi", s) == []


def test_hindi_available_via_fake_provider(fake):
    state, s = fake
    state["voices"] = [EN, HI]
    hi = [v for v in models.voice_info(s) if v["id"] == "win:Microsoft Kalpana"][0]
    assert hi["installed"] and hi["selectable"] and hi["provider"] == "windows-sapi"
    assert hi["locale"] == "hi-IN" and hi["restricted"] is False


def test_provider_selection_and_script_routing(fake):
    state, s = fake
    state["voices"] = [EN, HI]
    voices = {"en": "win:Microsoft Zira Desktop", "hi": "win:Microsoft Kalpana"}
    out = b"".join(tts.Synthesizer(s).synthesize("Hello नमस्ते", voices))
    assert out and len(out) % 2 == 0
    assert [v for _, v in state["said"]] == ["Microsoft Zira Desktop", "Microsoft Kalpana"]
    assert models.provider("win:x") == "windows-sapi" and models.provider("en_US-x-low") == "piper"


def test_onecore_voices_are_a_separate_provider(fake):
    state, s = fake
    state["onecore"] = [HI]
    v = [x for x in models.voice_info(s) if x["id"] == "winrt:Microsoft Kalpana"][0]
    assert v["provider"] == "windows-onecore" and v["language"] == "hi" and v["installed"]
    b"".join(tts.Synthesizer(s).synthesize("नमस्ते", {"hi": v["id"]}))
    assert state["said"] == [("नमस्ते", "Microsoft Kalpana")]


def test_removed_voice_fails_cleanly(fake):
    state, s = fake
    state["voices"] = []
    with pytest.raises(LookupError, match="not available|not installed"):
        b"".join(tts.Synthesizer(s).synthesize("Hi", {"en": "win:Microsoft Zira Desktop"}))


def test_windows_tts_can_be_disabled(fake):
    _, s = fake
    off = Settings(model_dir=s.model_dir, windows_tts=False)
    assert not any(v["id"].startswith("win:") for v in models.voice_info(off))


@pytest.mark.parametrize(
    ("kwargs", "frames"),
    [
        ({"rate": 16_000}, 2205),
        ({"rate": 22_050}, 1600),
        ({"rate": 44_100, "ch": 2}, 800),
        ({"width": 1}, 2205),
    ],
)
def test_pcm_normalisation(kwargs, frames):
    src = wav(**kwargs) if kwargs.get("width") != 1 else wav(rate=16_000, width=1)
    pcm = winspeech.to_pcm(src, tts.RATE)
    assert abs(len(pcm) // 2 - frames) <= 1


def test_no_audio_written_and_text_not_in_argv(fake, monkeypatch, tmp_path):
    state, s = fake
    monkeypatch.setenv("TMP", str(tmp_path))
    b"".join(tts.Synthesizer(s).synthesize("secret words", {"en": "win:Microsoft Zira Desktop"}))
    assert list(tmp_path.iterdir()) == []
    assert state["said"][0][0] == "secret words"


def test_restricted_voices_not_selectable_by_default(fake):
    _, s = fake
    assert not s.allow_noncommercial
    restricted = [v for v in models.voice_info(s) if v["restricted"]]
    assert restricted and not any(v["selectable"] for v in restricted)
