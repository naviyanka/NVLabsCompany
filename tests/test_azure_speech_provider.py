"""Azure Speech adapter: configuration, auth scope, STT/TTS sessions, cancel, leaks.

Fakes only (tests/voice_fakes.py): no network, no real SDK, no credential.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import pathlib
import threading
import xml.dom.minidom
from types import SimpleNamespace

import pytest

from nexus.config import settings
from nexus.voice import azure_speech as az
from nexus.voice import provider_types as pt
from tests.voice_fakes import (
    FakeCredential,
    FakeSdk,
    audio_event,
    canceled_stt,
    canceled_tts,
    drain,
    recognized,
)

ENDPOINT = "https://nexus-speech-test.cognitiveservices.azure.com"
PCM = b"\x01\x02" * 1600  # 100 ms of 16 kHz s16le


def in_thread(fn, *args) -> None:
    thread = threading.Thread(target=fn, args=args)
    thread.start()
    thread.join()


@pytest.fixture
def env(monkeypatch):
    for key, value in {
        "azure_speech_enabled": True,
        "azure_speech_endpoint": ENDPOINT,
        "azure_speech_region": "centralindia",
        "azure_speech_voice_hi": "hi-IN-SwaraNeural",
        "azure_speech_voice_en": "en-IN-NeerjaNeural",
        "azure_speech_connect_timeout_seconds": 3.0,
        "azure_speech_tts_first_audio_timeout_seconds": 4.0,
        "azure_speech_stt_final_timeout_seconds": 5.0,
    }.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(az, "_sleep", _no_sleep)
    sdk, cred = FakeSdk(), FakeCredential()
    rt = az.AzureSpeechRuntime(sdk_loader=lambda: sdk, credential_factory=lambda: cred)
    return SimpleNamespace(
        sdk=sdk,
        cred=cred,
        rt=rt,
        stt=az.AzureSpeechSttProvider(rt),
        tts=az.AzureSpeechTtsProvider(rt),
        set=lambda **kw: [
            monkeypatch.setattr(settings, f"azure_speech_{k}", v) for k, v in kw.items()
        ],
    )


async def _no_sleep(_seconds: float) -> None:
    return None


async def stt_open(env, mode="en", usage=None, gen=3, rid="req-1"):
    return await env.stt.open(mode, generation=gen, request_id=rid, usage=usage)


async def tts_open(env, mode="en", usage=None, gen=3, rid="req-1"):
    return await env.tts.open(mode, generation=gen, request_id=rid, usage=usage)


async def wait_for(predicate, limit: float = 2.0) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(_poll(), limit)


async def first(session):
    async for event in session.events():
        return event


def tts_script(*chunks: bytes, complete: bool = True):
    """A synthesizer hook that delivers audio (and completion) from a non-loop thread."""

    def hook(synth, _ssml):
        def run():
            for chunk in chunks:
                synth.synthesizing.fire(audio_event(chunk))
            if complete:
                synth.synthesis_completed.fire(None)

        in_thread(run)

    return hook


# --- configuration, doctor, scope ---------------------------------------------------------
def test_disabled_by_default_and_open_refuses():
    reason = az.AzureSpeechRuntime().unavailable_reason()
    assert reason and reason.startswith("AZURE_SPEECH_DISABLED")
    assert settings.azure_speech_enabled is False


async def test_open_when_disabled_raises(env):
    env.set(enabled=False)
    with pytest.raises(pt.SpeechProviderError) as err:
        await stt_open(env)
    assert err.value.code == "AZURE_SPEECH_DISABLED"
    assert env.sdk.recognizers == [] and env.cred.scopes == []


def test_missing_sdk(env, monkeypatch):
    monkeypatch.setattr(az, "_installed", lambda *m: False)
    rt = az.AzureSpeechRuntime(credential_factory=lambda: env.cred)
    assert rt.unavailable_reason().startswith("AZURE_SPEECH_SDK_MISSING")
    assert rt.status()["sdk_installed"] is False


def test_missing_identity_sdk(env, monkeypatch):
    monkeypatch.setattr(az, "_installed", lambda *m: m[0] != "azure.identity")
    rt = az.AzureSpeechRuntime(sdk_loader=lambda: env.sdk)
    assert rt.unavailable_reason().startswith("AZURE_SPEECH_IDENTITY_SDK_MISSING")


def test_import_error_maps_to_sdk_missing(env, monkeypatch):
    def boom():
        raise ImportError("no native wheel")

    rt = az.AzureSpeechRuntime(sdk_loader=boom, credential_factory=lambda: env.cred)
    with pytest.raises(pt.SpeechProviderError) as err:
        rt.load_sdk()
    assert err.value.code == "AZURE_SPEECH_SDK_MISSING"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://nexus-speech-test.cognitiveservices.azure.com",
        "https://centralindia.api.cognitive.microsoft.com",  # shared regional host
        "https://centralindia.stt.speech.microsoft.com",
        "https://nexus-speech-test.cognitiveservices.azure.com.evil.example",
        "https://evil.example/nexus.cognitiveservices.azure.com",
        "https://user:pw@nexus-speech-test.cognitiveservices.azure.com",
        "https://nexus-speech-test.cognitiveservices.azure.com:8443",
        "https://nexus-speech-test.cognitiveservices.azure.com/speech",
        "https://nexus-speech-test.cognitiveservices.azure.com?x=1",
        "https://nexus-speech-test.cognitiveservices.azure.com#f",
        "https://127.0.0.1",
        "https://10.0.0.5",
        "https://169.254.169.254",
        "http://localhost",
        "ftp://nexus-speech-test.cognitiveservices.azure.com",
        "nexus-speech-test",
    ],
)
def test_endpoint_rejected(env, endpoint):
    env.set(endpoint=endpoint)
    with pytest.raises(pt.SpeechProviderError) as err:
        env.rt.check()
    assert err.value.code == "AZURE_SPEECH_ENDPOINT_INVALID"
    assert endpoint not in str(err.value)  # the rejected value is never echoed


@pytest.mark.parametrize(
    "endpoint", [ENDPOINT, ENDPOINT + "/", ENDPOINT.upper().replace("HTTPS", "https")]
)
def test_endpoint_accepted(env, endpoint):
    env.set(endpoint=endpoint)
    assert env.rt.check().endpoint == ENDPOINT


def test_endpoint_missing(env):
    env.set(endpoint="")
    with pytest.raises(pt.SpeechProviderError) as err:
        env.rt.check()
    assert err.value.code == "AZURE_SPEECH_ENDPOINT_MISSING"


@pytest.mark.parametrize(
    ("value", "code"),
    [("", "REGION_MISSING"), ("southindia", "REGION_INVALID"), ("mars", "REGION_INVALID")],
)
def test_region_validation(env, value, code):
    env.set(region=value)
    with pytest.raises(pt.SpeechProviderError) as err:
        env.rt.check()
    assert err.value.code == f"AZURE_SPEECH_{code}"


def test_region_allow_list_and_case(env):
    env.set(region=" CentralIndia ")
    assert env.rt.check().region == "centralindia"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("voice_hi", "ur-PK-UzmaNeural"),
        ("voice_hi", "en-IN-NeerjaNeural"),  # wrong locale for the Hindi slot
        ("voice_en", "hi-IN-SwaraNeural"),
        ("voice_en", "en-IN-NeerjaNeural; evil"),
        ("voice_en", ""),
    ],
)
def test_voice_must_be_approved_for_its_locale(env, key, value):
    env.set(**{key: value})
    with pytest.raises(pt.SpeechProviderError) as err:
        env.rt.check()
    assert err.value.code == "AZURE_SPEECH_VOICE_INVALID"


def test_alternate_approved_voices_accepted(env):
    env.set(voice_hi="hi-IN-MadhurNeural", voice_en="en-IN-PrabhatNeural")
    cfg = env.rt.check()
    assert (cfg.voice_hi, cfg.voice_en) == ("hi-IN-MadhurNeural", "en-IN-PrabhatNeural")


@pytest.mark.parametrize("key", ["connect", "tts_first_audio_timeout", "stt_final"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), 1e9])
def test_timeouts_validated(env, key, value):
    field = {
        "connect": "connect_timeout_seconds",
        "tts_first_audio_timeout": "tts_first_audio_timeout_seconds",
        "stt_final": "stt_final_timeout_seconds",
    }[key]
    env.set(**{field: value})
    with pytest.raises(pt.SpeechProviderError) as err:
        env.rt.check()
    assert err.value.code == "AZURE_SPEECH_TIMEOUT_INVALID"
    assert env.rt.status()["timeouts_valid"] is False


def test_status_makes_no_request_and_leaks_nothing(env):
    status = env.rt.status()
    assert status["available"] is True and status["unavailable_reason"] is None
    assert status["entra_scope"] == az.ENTRA_SCOPE == "https://cognitiveservices.azure.com/.default"
    assert status["auth"] == "entra" and status["hinglish"] == "gated_off"
    assert status["locale_mapping"]["hinglish"] is None
    assert status["locale_mapping"]["auto"] == ["en-IN", "hi-IN"]
    assert "ur-IN" not in json.dumps(status)
    assert env.cred.scopes == [] and env.sdk.configs == []  # no token, no SDK object
    text = json.dumps(status).lower()
    assert "secret" not in text and "token_value" not in text and "key" not in status


def test_module_status_is_json_safe_when_disabled():
    status = az.status()
    json.dumps(status)
    assert status["enabled"] is False and status["available"] is False


def test_scoped_credential_serves_only_the_approved_scope():
    inner = FakeCredential()
    cred = az._ScopedCredential(inner)
    token = cred.get_token(az.ENTRA_SCOPE)
    assert token.token == "SECRET-TOKEN-VALUE"  # passed through, never stored on the wrapper
    assert inner.scopes == [(az.ENTRA_SCOPE,)] and cred.token_requests == 1
    assert "SECRET" not in repr(vars(cred)).replace("FakeCredential", "")
    for bad in [
        ("https://management.azure.com/.default",),
        ("https://cognitiveservices.azure.com",),
        (az.ENTRA_SCOPE, "https://other/.default"),
        (),
    ]:
        with pytest.raises(pt.SpeechProviderError) as err:
            cred.get_token(*bad)
        assert err.value.code == "AZURE_SPEECH_SCOPE_REJECTED"
    assert inner.scopes == [(az.ENTRA_SCOPE,)]  # nothing else was ever forwarded


def test_scoped_credential_failure_is_sanitized_with_no_fallback():
    inner = FakeCredential(fail=True)
    cred = az._ScopedCredential(inner)
    with pytest.raises(pt.SpeechProviderError) as err:
        cred.get_token(az.ENTRA_SCOPE)
    assert err.value.code == "AZURE_SPEECH_AUTH_FAILED"
    assert "SECRET" not in str(err.value) and err.value.__cause__ is None
    assert err.value.__suppress_context__ is True
    assert inner.scopes == [(az.ENTRA_SCOPE,)]  # one attempt, no second scope or key path


def test_scoped_credential_is_a_token_credential():
    pytest.importorskip("azure.core")
    from azure.core.credentials import TokenCredential

    assert isinstance(az._ScopedCredential(FakeCredential()), TokenCredential)


def test_runtime_caches_one_credential_and_closes_it(env):
    assert env.rt.credential() is env.rt.credential()
    env.rt.close()
    assert env.cred.closed is True


# --- modes --------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["", "ur", "ur-IN", "fr", "EN-US", None, 5, "hi-IN"])
async def test_unknown_modes_fail_closed(env, mode):
    for provider in (env.stt, env.tts):
        with pytest.raises(pt.SpeechProviderError) as err:
            await provider.open(mode, generation=1, request_id="r")
        assert err.value.code == pt.VOICE_MODE_UNKNOWN
    assert env.sdk.recognizers == [] and env.sdk.synthesizers == []


@pytest.mark.parametrize("name", ["hinglish", "Hinglish", " HINGLISH "])
async def test_hinglish_recognized_but_gated(env, name):
    for provider in (env.stt, env.tts):
        with pytest.raises(pt.SpeechProviderError) as err:
            await provider.open(name, generation=1, request_id="r")
        assert err.value.code == pt.HINGLISH_UNVERIFIED
    assert env.sdk.configs == []


async def test_explicit_hindi_is_hi_in_only(env):
    session = await stt_open(env, "hi")
    await first(session)  # Ready
    reco = env.sdk.recognizers[0]
    assert reco.kw["language"] == "hi-IN" and "auto_detect_source_language_config" not in reco.kw
    assert pt.LOCALES_BY_MODE["hi"] == ("hi-IN",)
    assert "ur-IN" not in pt.ALLOWED_LOCALES
    session.cancel()
    await session.aclose()


async def test_auto_uses_start_only_allow_list_without_urdu(env):
    session = await stt_open(env, "auto")
    await first(session)
    cfg, reco = env.sdk.configs[0], env.sdk.recognizers[0]
    assert reco.kw["auto_detect_source_language_config"].languages == ["en-IN", "hi-IN"]
    assert cfg.props[env.sdk.PropertyId.SpeechServiceConnection_LanguageIdMode] == "AtStart"
    assert "language" not in reco.kw
    session.cancel()
    await session.aclose()


# --- STT ----------------------------------------------------------------------------------
async def run_stt(env, mode="en", *, language="en-IN", text="namaste", usage=None, nbest=None):
    env.sdk.language_result = language
    env.sdk.on_push_close = lambda: in_thread(_stt_script, env, text, nbest)
    session = await stt_open(env, mode, usage=usage)
    await session.send_audio(PCM)
    await session.send_audio(PCM)
    await session.finish()
    events = await drain(session)
    await session.aclose()
    return session, events


def _stt_script(env, text, nbest):
    reco = env.sdk.recognizers[0]
    reco.speech_start_detected.fire(None)
    reco.recognizing.fire(SimpleNamespace(result=SimpleNamespace(text="nam")))
    reco.recognized.fire(recognized(text, offset=20_000, duration=1_500_000, nbest=nbest))
    reco.session_stopped.fire(None)


async def test_stt_round_trip_events_ordered_and_stamped(env):
    usage = pt.SessionUsage()
    session, events = await run_stt(env, "en", nbest={"Confidence": 0.93}, usage=usage)
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["Ready", "SpeechStart", "Partial", "Final", "Usage"]
    assert all((e.generation, e.request_id) == (3, "req-1") for e in events)
    final = events[3]
    assert final.text == "namaste" and final.confidence == 0.93
    assert (final.offset_ms, final.duration_ms) == (2, 150)  # 100 ns ticks
    assert (final.selected_mode, final.requested_locales) == ("en", ("en-IN",))
    assert final.detected_locale is None and final.notice is None  # explicit: nothing detected
    assert events[4].quantity == 200  # 2 x 100 ms
    assert usage.snapshot() == {"stt.audio_ms": 200}
    assert session._push is None  # released


async def test_stt_push_stream_is_headerless_16k_mono_pcm(env):
    env.sdk.on_push_close = lambda: in_thread(_stt_script, env, "x", None)
    session = await stt_open(env)
    await session.send_audio(PCM)
    await session.finish()
    await drain(session)
    push = env.sdk.pushes[0]
    assert push.format.samples_per_second == 16000
    assert (push.format.bits_per_sample, push.format.channels) == (16, 1)
    assert push.writes == [PCM] and push.closed  # raw frames: no WAV container added
    assert env.sdk.configs[0].kw["endpoint"] == ENDPOINT
    assert env.sdk.configs[0].kw["token_credential"].token_requests == 0  # SDK pulls it later
    await session.aclose()


@pytest.mark.parametrize(
    ("language", "detected", "notice"),
    [
        ("hi-IN", "hi-IN", None),
        ("en-IN", "en-IN", None),
        ("ur-IN", None, pt.VOICE_LANGUAGE_UNRECOGNIZED),
        ("", None, pt.VOICE_LANGUAGE_UNRECOGNIZED),
        (None, None, pt.VOICE_LANGUAGE_UNRECOGNIZED),
    ],
)
async def test_auto_separates_selected_requested_and_detected(env, language, detected, notice):
    _, events = await run_stt(env, "auto", language=language)
    final = next(e for e in events if isinstance(e, pt.Final))
    assert final.selected_mode == "auto" and final.requested_locales == ("en-IN", "hi-IN")
    assert final.detected_locale == detected and final.notice == notice


async def test_explicit_hindi_never_reports_a_detected_locale(env):
    _, events = await run_stt(env, "hi", language="ur-IN")  # even if the SDK said Urdu
    final = next(e for e in events if isinstance(e, pt.Final))
    assert final.detected_locale is None and final.notice is None
    assert final.requested_locales == ("hi-IN",)


async def test_stt_no_match_and_missing_confidence(env):
    env.sdk.on_push_close = lambda: in_thread(
        lambda: (
            env.sdk.recognizers[0].recognized.fire(
                recognized("", reason=env.sdk.ResultReason.NoMatch)
            ),
            env.sdk.recognizers[0].session_stopped.fire(None),
        )
    )
    session = await stt_open(env)
    await session.send_audio(PCM)
    await session.finish()
    kinds = [type(e).__name__ for e in await drain(session)]
    assert kinds == ["Ready", "NoMatch", "Usage"]
    await session.aclose()


@pytest.mark.parametrize(
    "bad",
    [b"", b"\x00", b"\x00" * 64_002, "text", None],
    ids=["empty", "odd-length", "too-big", "str", "none"],
)
async def test_stt_rejects_invalid_audio(env, bad):
    session = await stt_open(env)
    with pytest.raises(pt.SpeechProviderError) as err:
        await session.send_audio(bad)
    assert err.value.code == pt.VOICE_AUDIO_INVALID
    session.cancel()
    await session.aclose()


async def test_stt_audio_after_finish_is_closed_error(env):
    session = await stt_open(env)
    await session.finish()  # no audio: ends cleanly without waiting for the service
    with pytest.raises(pt.SpeechProviderError) as err:
        await session.send_audio(PCM)
    assert err.value.code == pt.VOICE_SESSION_CLOSED
    await session.aclose()


async def test_stt_final_timeout(env):
    env.set(stt_final_timeout_seconds=0.05)  # session_stopped never arrives
    usage = pt.SessionUsage()
    session = await stt_open(env, usage=usage)
    await session.send_audio(PCM)
    await session.finish()
    events = await drain(session)
    assert [type(e).__name__ for e in events] == ["Ready", "Usage", "Error"]
    assert events[-1].code == "AZURE_SPEECH_TIMEOUT" and events[-1].fatal
    assert usage.snapshot() == {"stt.audio_ms": 100}  # settled once
    await session.aclose()


@pytest.mark.parametrize(
    ("name", "code", "retryable"),
    [
        ("AuthenticationFailure", "AUTH_FAILED", False),
        ("Forbidden", "FORBIDDEN", False),
        ("TooManyRequests", "RATE_LIMITED", True),
        ("BadRequest", "BAD_REQUEST", False),
        ("ConnectionFailure", "CONNECTION_FAILED", True),
        ("ServiceTimeout", "TIMEOUT", True),
        ("ServiceUnavailable", "UNAVAILABLE", True),
        ("RuntimeError", "SERVICE_ERROR", False),
    ],
)
async def test_stt_service_errors_map_stably_and_are_never_retried(env, name, code, retryable):
    session = await stt_open(env)
    await session.send_audio(PCM)
    reco = env.sdk.recognizers[0]
    sdk = env.sdk
    in_thread(
        reco.canceled.fire,
        canceled_stt(sdk.CancellationReason.Error, getattr(sdk.CancellationErrorCode, name)),
    )
    events = await drain(session)
    error = events[-1]
    assert isinstance(error, pt.Error) and error.code == f"AZURE_SPEECH_{code}"
    assert error.retryable is retryable and error.fatal
    assert len(sdk.recognizers) == 1 and reco.started == 1  # no mid-stream retry
    await session.aclose()


async def test_stt_end_of_stream_cancel_is_not_an_error(env):
    env.sdk.on_push_close = lambda: in_thread(
        lambda: (
            env.sdk.recognizers[0].canceled.fire(
                canceled_stt(env.sdk.CancellationReason.EndOfStream)
            ),
            env.sdk.recognizers[0].session_stopped.fire(None),
        )
    )
    session = await stt_open(env)
    await session.send_audio(PCM)
    await session.finish()
    assert not any(isinstance(e, pt.Error) for e in await drain(session))
    await session.aclose()


async def test_stt_connect_retries_once_before_audio(env):
    env.sdk.start_errors = [RuntimeError("transient SECRET-TOKEN-VALUE")]
    session = await stt_open(env)
    assert isinstance(await first(session), pt.Ready)
    assert len(env.sdk.recognizers) == 2  # first start failed, second succeeded
    session.cancel()
    await session.aclose()


async def test_stt_connect_gives_up_after_one_retry(env):
    env.sdk.start_error = RuntimeError("down SECRET-TOKEN-VALUE")
    session = await stt_open(env)
    events = await drain(session)
    assert len(env.sdk.recognizers) == 2
    assert [type(e).__name__ for e in events] == ["Error"]
    assert events[0].code == "AZURE_SPEECH_CONNECTION_FAILED" and events[0].retryable
    assert "SECRET" not in events[0].message
    with pytest.raises(pt.SpeechProviderError):
        await session.send_audio(PCM)  # nothing was sent, nothing was counted
    assert session._bytes == 0
    await session.aclose()


async def test_stt_connect_timeout(env):
    env.set(connect_timeout_seconds=0.05)
    release = threading.Event()
    env.sdk.start_error = None
    real = env.sdk.SpeechRecognizer

    def slow(**kw):
        release.wait(2)
        return real(**kw)

    env.sdk.SpeechRecognizer = slow
    session = await stt_open(env)
    events = await drain(session, limit=5)
    release.set()
    assert events[-1].code == "AZURE_SPEECH_TIMEOUT"
    await session.aclose()


# --- TTS ----------------------------------------------------------------------------------
async def run_tts(env, texts, *, mode="en", usage=None, hook=None):
    session = await tts_open(env, mode, usage=usage)
    await first_ready_tts(env, session, hook or tts_script(b"\x01\x00\x02\x00", b"\x03\x00"))
    for text in texts:
        await session.write_text(text)
    await session.end_text()
    events = await drain(session)
    await session.aclose()
    return session, events


async def first_ready_tts(env, session, hook):
    await wait_for(lambda: env.sdk.synthesizers)
    env.sdk.synthesizers[0].on_start = hook


async def test_tts_ordered_audio_usage_done_and_stamping(env):
    usage = pt.SessionUsage()
    _, events = await run_tts(env, ["Hello there.", "Second sentence."], usage=usage)
    audio = [e for e in events if isinstance(e, pt.AudioChunk)]
    assert [a.pcm for a in audio] == [b"\x01\x00\x02\x00", b"\x03\x00"] * 2  # per-sentence order
    assert all((a.sample_rate, a.encoding, a.channels) == (24000, "pcm_s16le", 1) for a in audio)
    assert [type(e).__name__ for e in events][-2:] == ["Usage", "Done"]
    assert events[-2].quantity == len("Hello there.") + len("Second sentence.")
    assert all((e.generation, e.request_id) == (3, "req-1") for e in events)
    assert usage.snapshot() == {"tts.characters": 28}
    assert env.sdk.configs[0].synthesis_format == "raw24"
    assert env.sdk.synthesizers[0].kw["audio_config"] is None  # never plays to a speaker


async def test_tts_script_selects_voice_and_ssml_is_escaped(env):
    _, events = await run_tts(env, ["Tom & Jerry <b>x</b>", "नमस्ते दुनिया"])
    ssml = env.sdk.synthesizers[0].ssml
    assert 'name="en-IN-NeerjaNeural"' in ssml[0] and 'xml:lang="en-IN"' in ssml[0]
    assert "Tom &amp; Jerry &lt;b&gt;x&lt;/b&gt;" in ssml[0]
    assert 'name="hi-IN-SwaraNeural"' in ssml[1] and 'xml:lang="hi-IN"' in ssml[1]
    assert not any(isinstance(e, pt.Error) for e in events)


def test_ssml_cannot_inject_tags_or_control_characters():
    evil = 'hi</voice></speak><voice name="x">\x00\x1b boom ]]>'
    ssml = az.build_ssml(evil, "en-IN-NeerjaNeural")
    assert ssml.count("<voice") == 1 and ssml.count("</voice>") == 1
    assert "\x00" not in ssml and "\x1b" not in ssml
    assert "&lt;/voice&gt;" in ssml and "]]&gt;" in ssml
    parsed = xml.dom.minidom.parseString(ssml)  # well-formed
    assert [n.tagName for n in parsed.getElementsByTagName("*")] == ["speak", "voice"]


@pytest.mark.parametrize("text", ["مرحبا یہ اردو ہے", "你好", "नमस्ते hello مرحبا", "!!!", "..."])
async def test_unsupported_script_is_noticed_and_never_synthesized(env, text):
    session = await tts_open(env)
    await first_ready_tts(env, session, tts_script(b"\x00\x00"))
    await session.write_text(text)
    await session.end_text()
    events = await drain(session)
    await session.aclose()
    notices = [e for e in events if isinstance(e, pt.Error)]
    assert [(n.code, n.fatal) for n in notices] == [(pt.VOICE_SCRIPT_UNSUPPORTED, False)]
    assert env.sdk.synthesizers[0].ssml == []  # no request, so no characters billed
    assert isinstance(events[-1], pt.Done) and not any(isinstance(e, pt.Usage) for e in events)


async def test_tts_overlong_sentence_is_noticed_not_sent(env):
    _, events = await run_tts(env, ["a" * (az.MAX_SENTENCE_CHARS + 1)])
    assert [e.code for e in events if isinstance(e, pt.Error)] == [pt.VOICE_TEXT_TOO_LONG]
    assert env.sdk.synthesizers[0].ssml == []


async def test_tts_write_after_end_and_backpressure(env):
    session = await tts_open(env)
    await session.end_text()
    with pytest.raises(pt.SpeechProviderError) as err:
        await session.write_text("late")
    assert err.value.code == pt.VOICE_SESSION_CLOSED
    session.cancel()
    await session.aclose()

    stuck = await tts_open(env)
    await wait_for(lambda: env.sdk.synthesizers)
    env.sdk.synthesizers[-1].on_start = lambda *_: None  # never produces audio
    with pytest.raises(pt.SpeechProviderError) as err:
        for _ in range(az.MAX_PENDING_SENTENCES + 3):
            await stuck.write_text("word")
            await asyncio.sleep(0)
    assert err.value.code == pt.VOICE_BACKPRESSURE
    stuck.cancel()
    await stuck.aclose()


async def test_tts_first_audio_timeout_retries_once_without_audio(env):
    env.set(tts_first_audio_timeout_seconds=0.05)
    session = await tts_open(env)
    await first_ready_tts(env, session, lambda *_: None)  # service never answers
    await session.write_text("Hello")
    await session.end_text()
    events = await drain(session, limit=5)
    errors = [e for e in events if isinstance(e, pt.Error)]
    assert [(e.code, e.fatal) for e in errors] == [("AZURE_SPEECH_TIMEOUT", True)]
    assert len(env.sdk.synthesizers[0].ssml) == 2  # original + the one allowed retry
    await session.aclose()


async def test_tts_retry_before_audio_succeeds_once(env):
    attempts = []

    def hook(synth, _ssml):
        attempts.append(1)
        if len(attempts) == 1:
            in_thread(
                synth.synthesis_canceled.fire,
                canceled_tts(
                    env.sdk.CancellationReason.Error, env.sdk.CancellationErrorCode.ServiceTimeout
                ),
            )
        else:
            tts_script(b"\x09\x00")(synth, _ssml)

    _, events = await run_tts(env, ["Hello"], hook=hook)
    assert len(attempts) == 2
    assert [e.pcm for e in events if isinstance(e, pt.AudioChunk)] == [b"\x09\x00"]
    assert not any(isinstance(e, pt.Error) for e in events)
    assert [e for e in events if isinstance(e, pt.Usage)][0].quantity == 5  # counted once


async def test_tts_no_retry_after_audio_was_emitted(env):
    attempts = []

    def hook(synth, ssml):
        attempts.append(1)

        def run():
            synth.synthesizing.fire(audio_event(b"\x01\x00"))
            synth.synthesis_canceled.fire(
                canceled_tts(
                    env.sdk.CancellationReason.Error,
                    env.sdk.CancellationErrorCode.ServiceUnavailable,
                )
            )

        in_thread(run)

    _, events = await run_tts(env, ["Hello"], hook=hook)
    assert len(attempts) == 1
    assert isinstance(events[-1], pt.Error) and events[-1].code == "AZURE_SPEECH_UNAVAILABLE"
    assert [type(e).__name__ for e in events].count("AudioChunk") == 1
    assert not any(isinstance(e, pt.Done) for e in events)


async def test_tts_rate_limit_is_mapped_and_not_retried(env):
    attempts = []

    def hook(synth, _ssml):
        attempts.append(1)
        in_thread(
            synth.synthesis_canceled.fire,
            canceled_tts(
                env.sdk.CancellationReason.Error, env.sdk.CancellationErrorCode.TooManyRequests
            ),
        )

    _, events = await run_tts(env, ["Hello"], hook=hook)
    assert len(attempts) == 1
    assert events[-1].code == "AZURE_SPEECH_RATE_LIMITED" and events[-1].retryable


async def test_tts_cancelled_by_user_callback_is_not_an_error(env):
    def hook(synth, _ssml):
        in_thread(
            synth.synthesis_canceled.fire, canceled_tts(env.sdk.CancellationReason.CancelledByUser)
        )
        tts_script(b"\x01\x00")(synth, _ssml)

    _, events = await run_tts(env, ["Hello"], hook=hook)
    assert not any(isinstance(e, pt.Error) for e in events)


async def test_tts_start_failure_is_sanitized(env):
    env.sdk.start_error = RuntimeError("boom SECRET-TOKEN-VALUE https://x/?sig=1")
    _, events = await run_tts(env, ["Hello"])
    error = events[-1]
    assert error.code == "AZURE_SPEECH_CONNECTION_FAILED"
    assert "SECRET" not in error.message and "sig=" not in error.message


# --- cancel, late callbacks, cleanup ------------------------------------------------------
def adapter_threads():
    return [t for t in threading.enumerate() if t.name.startswith("azure-speech")]


async def assert_clean(session):
    assert all(task.done() for task in session._tasks) and session._cleanup.done()
    await wait_for(lambda: not adapter_threads())


async def test_cancel_before_connect_is_immediate_and_clean(env):
    session = await stt_open(env)
    session.cancel()
    session.cancel()  # idempotent
    assert await drain(session) == []
    await session.aclose()
    assert env.sdk.recognizers == [] and env.cred.scopes == []
    await assert_clean(session)


async def test_tts_cancel_before_connect(env):
    session = await tts_open(env)
    session.cancel()
    assert await drain(session) == []
    await session.aclose()
    assert env.sdk.synthesizers == []
    await assert_clean(session)


async def test_stt_cancel_during_stream_drops_late_callbacks_and_releases(env):
    usage = pt.SessionUsage()
    session = await stt_open(env, usage=usage)
    assert isinstance(await first(session), pt.Ready)
    await session.send_audio(PCM)
    session.cancel()
    reco = env.sdk.recognizers[0]
    in_thread(reco.recognized.fire, recognized("late words"))  # arrives after cancel
    in_thread(reco.canceled.fire, canceled_stt(env.sdk.CancellationReason.Error))
    assert await drain(session) == []
    await session.aclose()
    assert env.sdk.pushes[0].closed and reco.stopped == 1
    assert usage.snapshot() == {"stt.audio_ms": 100}  # incurred usage kept, no event emitted
    await assert_clean(session)


async def test_tts_cancel_mid_synthesis_drops_late_audio(env):
    session = await tts_open(env)
    await first_ready_tts(env, session, lambda *_: None)  # synthesis in flight
    await session.write_text("A long sentence in flight.")
    await wait_for(lambda: env.sdk.synthesizers[0].ssml)
    session.cancel()
    in_thread(env.sdk.synthesizers[0].synthesizing.fire, audio_event(b"\x07\x00"))  # late
    in_thread(env.sdk.synthesizers[0].synthesis_completed.fire, None)
    assert await drain(session) == []
    await session.aclose()
    assert env.sdk.synthesizers[0].stops >= 1  # the SDK was told to stop
    await assert_clean(session)


async def test_cancel_does_not_block_the_loop(env):
    session = await tts_open(env)
    await first_ready_tts(env, session, lambda *_: None)
    await session.write_text("Hello")
    gate = threading.Event()
    env.sdk.synthesizers[0].stop_speaking_async = lambda: (
        gate.wait(2),
        SimpleNamespace(get=lambda: None),
    )[1]
    loop = asyncio.get_running_loop()
    started = loop.time()
    session.cancel()
    assert loop.time() - started < 0.1  # returns at once; the slow stop runs in the background
    gate.set()
    await session.aclose()


async def test_aclose_without_cancel_releases_everything(env):
    session = await stt_open(env)
    await first(session)
    await session.aclose()
    assert env.sdk.pushes[0].closed
    await assert_clean(session)


async def test_late_events_after_close_are_dropped(env):
    session = await stt_open(env)
    await first(session)
    await session.aclose()
    session._emit(session._stamp(pt.Ready))
    assert len(session._queue) == 0


# --- bounded queues -----------------------------------------------------------------------
def test_event_queue_drops_oldest_partial_then_refuses():
    queue = pt.EventQueue(2)
    stamp = {"generation": 1, "request_id": "r"}
    assert queue.put(pt.Partial(text="a", **stamp)) and queue.put(pt.Ready(**stamp))
    assert queue.put(pt.Partial(text="b", **stamp))  # evicts the oldest Partial
    assert [type(e).__name__ for e in queue._items] == ["Ready", "Partial"]
    assert queue.put(pt.Ready(**stamp)) is True  # evicts the remaining Partial
    assert queue.put(pt.Ready(**stamp)) is False  # nothing droppable: caller must fail
    queue.put_force(pt.Error(code="X", message="m", **stamp))  # terminal errors always land
    assert isinstance(queue._items[-1], pt.Error)


async def test_session_fails_closed_when_consumer_never_drains(env):
    session = await stt_open(env)
    await wait_for(lambda: env.sdk.recognizers)
    await asyncio.sleep(0.05)
    for _ in range(az.STT_QUEUE_EVENTS + 5):
        session._emit(session._stamp(pt.SpeechStart))
    events = await drain(session)
    assert events[-1].code == "AZURE_SPEECH_BACKPRESSURE"
    assert len(events) <= az.STT_QUEUE_EVENTS + 1
    await session.aclose()


# --- no leaks, no extra surface -----------------------------------------------------------
async def test_no_audio_token_or_secret_in_repr_status_logs_or_errors(env, caplog):
    caplog.set_level(logging.DEBUG)
    env.sdk.start_errors = [RuntimeError("SECRET-TOKEN-VALUE")]
    audio = b"\xde\xad" * 1600
    env.sdk.on_push_close = lambda: in_thread(
        _stt_script, env, "private words", {"Confidence": 0.5}
    )
    session = await stt_open(env)
    await session.send_audio(audio)
    await session.finish()
    stt_events = await drain(session)
    await session.aclose()
    _, tts_events = await run_tts(env, ["private words"], hook=tts_script(b"\xca\xfe\x00\x00"))
    blob = "\n".join(repr(e) for e in [*stt_events, *tts_events])
    blob += (
        json.dumps(env.rt.status()) + caplog.text + repr(session) + repr(vars(env.rt.credential()))
    )
    for secret in ("SECRET-TOKEN-VALUE", "private words", "\\xde\\xad", "\\xca\\xfe", "namaste"):
        assert secret not in blob
    assert "Bearer" not in blob


def test_voice_package_has_no_tool_memory_approval_or_db_surface():
    root = pathlib.Path(az.__file__).parent
    imported: set[str] = set()
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
    nexus = {m for m in imported if m == "nexus" or m.startswith("nexus.")}
    assert nexus <= {"nexus.config", "nexus.governance.ssrf_protection", "nexus.voice"} | {
        m for m in nexus if m.startswith("nexus.voice")
    }
    assert not {
        m for m in imported if m.split(".")[0] in {"sqlalchemy", "asyncpg", "psycopg", "aiosqlite"}
    }


def test_unknown_event_fails_closed():
    with pytest.raises(pt.SpeechProviderError) as err:
        pt.check_event(object(), pt.STT_EVENTS)
    assert err.value.code == pt.VOICE_UNKNOWN_EVENT
    with pytest.raises(pt.SpeechProviderError):
        pt.check_event(
            pt.AudioChunk(generation=1, request_id="r", pcm=b"", sample_rate=1), pt.STT_EVENTS
        )


def test_session_usage_aggregates_and_clamps():
    usage = pt.SessionUsage()
    usage.add("stt", "audio_ms", 100)
    usage.add("stt", "audio_ms", 50)
    usage.add("tts", "characters", 20)
    usage.add("tts", "characters", -5)
    assert usage.snapshot() == {"stt.audio_ms": 150, "tts.characters": 20}


def test_classify_script():
    assert pt.classify_script("नमस्ते") == "devanagari"
    assert pt.classify_script("Hello 42") == "latin"
    assert pt.classify_script("42") == "latin"
    assert pt.classify_script("اردو") is None
    assert pt.classify_script("hello اردو") is None
    assert pt.classify_script("...") is None


async def test_open_requires_generation_and_request_id(env):
    with pytest.raises(pt.SpeechProviderError):
        await env.stt.open("en", generation=-1, request_id="r")
    with pytest.raises(pt.SpeechProviderError):
        await env.tts.open("en", generation=1, request_id="")
