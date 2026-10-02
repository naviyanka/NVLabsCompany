"""Contract parity: the neutral fakes and the Azure adapter obey the same provider contract.

Also an offline smoke of the real Azure SDK (skipped when the optional ``speech`` extra is
not installed): it constructs the objects the adapter builds, without any network call.
"""

from __future__ import annotations

import threading

import pytest

from nexus.config import settings
from nexus.voice import azure_speech as az
from nexus.voice import provider_types as pt
from tests.voice_fakes import (
    FakeCredential,
    FakeSdk,
    FakeSttProvider,
    FakeTtsProvider,
    audio_event,
    drain,
    recognized,
)

PCM = b"\x01\x02" * 1600


def _in_thread(fn) -> None:
    thread = threading.Thread(target=fn)
    thread.start()
    thread.join()


@pytest.fixture
def azure(monkeypatch):
    for key, value in {
        "azure_speech_enabled": True,
        "azure_speech_endpoint": "https://nexus-speech-test.cognitiveservices.azure.com",
        "azure_speech_region": "centralindia",
    }.items():
        monkeypatch.setattr(settings, key, value)
    sdk = FakeSdk()

    def stt_done():
        reco = sdk.recognizers[0]
        _in_thread(
            lambda: (reco.recognized.fire(recognized("hello")), reco.session_stopped.fire(None))
        )

    sdk.on_push_close = stt_done

    def tts_hook(synth, _ssml):
        def run():
            synth.synthesizing.fire(audio_event(b"\x01\x00"))
            synth.synthesis_completed.fire(None)

        _in_thread(run)

    original = sdk.SpeechSynthesizer

    def synth(**kw):
        made = original(**kw)
        made.on_start = tts_hook
        return made

    sdk.SpeechSynthesizer = synth
    rt = az.AzureSpeechRuntime(sdk_loader=lambda: sdk, credential_factory=FakeCredential)
    return rt


@pytest.fixture(params=["fake", "azure"])
def providers(request, azure):
    if request.param == "fake":
        return FakeSttProvider(), FakeTtsProvider()
    return az.AzureSpeechSttProvider(azure), az.AzureSpeechTtsProvider(azure)


@pytest.mark.parametrize("mode", ["ur", "", None, "EN-US"])
async def test_unknown_mode_fails_closed(providers, mode):
    for provider in providers:
        with pytest.raises(pt.SpeechProviderError) as err:
            await provider.open(mode, generation=1, request_id="r")
        assert err.value.code == pt.VOICE_MODE_UNKNOWN


async def test_hinglish_is_gated(providers):
    for provider in providers:
        with pytest.raises(pt.SpeechProviderError) as err:
            await provider.open("hinglish", generation=1, request_id="r")
        assert err.value.code == pt.HINGLISH_UNVERIFIED


@pytest.mark.parametrize("mode", ["en", "hi", "auto"])
async def test_stt_session_contract(providers, mode):
    stt, _ = providers
    session = await stt.open(mode, generation=7, request_id="abc")
    assert (session.generation, session.request_id) == (7, "abc")
    await session.send_audio(PCM)
    await session.finish()
    events = await drain(session)
    await session.aclose()
    for event in events:
        pt.check_event(event, pt.STT_EVENTS)
        assert (event.generation, event.request_id) == (7, "abc")
    finals = [e for e in events if isinstance(e, pt.Final)]
    plan = pt.resolve_mode(mode)
    assert len(finals) == 1
    assert (finals[0].selected_mode, finals[0].requested_locales) == (
        plan.selected,
        plan.requested_locales,
    )
    assert [e for e in events if isinstance(e, pt.Usage)][0].quantity == 100  # 100 ms of audio
    with pytest.raises(pt.SpeechProviderError) as err:
        await session.send_audio(b"\x00")  # odd length
    assert err.value.code == pt.VOICE_AUDIO_INVALID


async def test_tts_session_contract(providers):
    _, tts = providers
    session = await tts.open("en", generation=2, request_id="xyz")
    await session.write_text("Hello")
    await session.end_text()
    events = await drain(session)
    await session.aclose()
    for event in events:
        pt.check_event(event, pt.TTS_EVENTS)
        assert (event.generation, event.request_id) == (2, "xyz")
    audio = [e for e in events if isinstance(e, pt.AudioChunk)]
    assert audio and all(
        (a.sample_rate, a.encoding, a.channels) == (24000, "pcm_s16le", 1) for a in audio
    )
    assert isinstance(events[-1], pt.Done)
    assert [e for e in events if isinstance(e, pt.Usage)][0].quantity == 5


async def test_cancel_is_idempotent_and_ends_events(providers):
    stt, tts = providers
    for session in (
        await stt.open("en", generation=1, request_id="r"),
        await tts.open("en", generation=1, request_id="r"),
    ):
        session.cancel()
        session.cancel()
        assert await drain(session) == []
        await session.aclose()
        await session.aclose()  # closing twice is harmless


def test_status_is_a_plain_non_secret_dict(providers):
    for provider in providers:
        status = provider.status()
        assert isinstance(status, dict) and "available" in status
        assert "secret" not in repr(status).lower()


def test_events_hide_audio_and_text_in_repr():
    stamp = {"generation": 1, "request_id": "r"}
    assert "SECRETWORDS" not in repr(pt.Partial(text="SECRETWORDS", **stamp))
    assert "SECRETWORDS" not in repr(
        pt.Final(text="SECRETWORDS", selected_mode="en", requested_locales=("en-IN",), **stamp)
    )
    assert "xde" not in repr(pt.AudioChunk(pcm=b"\xde\xad", sample_rate=24000, **stamp))


# --- real SDK, offline ---------------------------------------------------------------------
def test_real_sdk_accepts_the_objects_the_adapter_builds():
    speechsdk = pytest.importorskip("azure.cognitiveservices.speech")
    from azure.core.credentials import TokenCredential

    cred = az._ScopedCredential(FakeCredential())
    assert isinstance(cred, TokenCredential)
    config = speechsdk.SpeechConfig(
        endpoint=az.ENDPOINT_SHAPE.replace("<custom-subdomain>", "x"), token_credential=cred
    )
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
    auto_reco = speechsdk.SpeechRecognizer(
        speech_config=config, audio_config=audio, auto_detect_source_language_config=auto
    )
    synth = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
    for attr in (
        "speech_start_detected",
        "recognizing",
        "recognized",
        "canceled",
        "session_stopped",
    ):
        getattr(reco, attr).connect(lambda _evt: None)
    for attr in ("synthesizing", "synthesis_completed", "synthesis_canceled"):
        getattr(synth, attr).connect(lambda _evt: None)
    assert speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode is not None
    push.close()
    del auto_reco, reco, synth
    assert cred.token_requests == 0  # construction alone requests no token
