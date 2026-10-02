"""Test doubles for the speech provider (no network, no real SDK).

``FakeSttProvider`` / ``FakeTtsProvider`` implement the neutral contracts directly.
``FakeSdk`` mimics the slice of the Azure Speech SDK the adapter touches: signals fire
on whatever thread the test chooses, and ``.get()`` futures resolve synchronously.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from enum import Enum
from types import SimpleNamespace
from typing import Any

from nexus.voice import provider_types as pt


# --- neutral fakes (contract parity) ------------------------------------------------------
class _FakeSession:
    def __init__(self, generation: int, request_id: str) -> None:
        self.generation = generation
        self.request_id = request_id
        self._queue = pt.EventQueue(64)
        self._cancelled = False
        self.closed = False

    def _emit(self, event: Any) -> None:
        if not self._cancelled:
            self._queue.put(event)

    def _stamp(self, cls: type, **kw: Any) -> Any:
        return cls(generation=self.generation, request_id=self.request_id, **kw)

    def cancel(self) -> None:
        if not self._cancelled:
            self._cancelled = True
            self._queue.clear()
            self._queue.close()

    async def events(self) -> AsyncIterator[Any]:
        async for event in self._queue:
            yield event

    async def aclose(self) -> None:
        self.closed = True
        self._queue.close()


class FakeSttSession(_FakeSession):
    def __init__(self, plan: pt.ModePlan, generation: int, request_id: str) -> None:
        super().__init__(generation, request_id)
        self._plan = plan
        self._bytes = 0
        self._emit(self._stamp(pt.Ready))

    async def send_audio(self, pcm: bytes) -> None:
        if not pcm or len(pcm) % 2:
            raise pt.SpeechProviderError(pt.VOICE_AUDIO_INVALID, "bad audio")
        self._bytes += len(pcm)

    async def finish(self) -> None:
        self._emit(
            self._stamp(
                pt.Final,
                text="hello",
                selected_mode=self._plan.selected,
                requested_locales=self._plan.requested_locales,
            )
        )
        self._emit(
            self._stamp(pt.Usage, operation="stt", unit="audio_ms", quantity=self._bytes // 32)
        )
        self._queue.close()


class FakeTtsSession(_FakeSession):
    def __init__(self, generation: int, request_id: str) -> None:
        super().__init__(generation, request_id)
        self._chars = 0

    async def write_text(self, text: str) -> None:
        self._chars += len(text)
        self._emit(self._stamp(pt.AudioChunk, pcm=b"\x00\x00", sample_rate=pt.TTS_SAMPLE_RATE))

    async def end_text(self) -> None:
        self._emit(self._stamp(pt.Usage, operation="tts", unit="characters", quantity=self._chars))
        self._emit(self._stamp(pt.Done))
        self._queue.close()


class FakeSttProvider:
    async def open(self, mode, *, generation, request_id, usage=None):
        return FakeSttSession(pt.resolve_mode(mode), generation, request_id)

    def status(self) -> dict[str, Any]:
        return {"available": True}


class FakeTtsProvider:
    async def open(self, mode, *, generation, request_id, usage=None):
        pt.resolve_mode(mode)
        return FakeTtsSession(generation, request_id)

    def status(self) -> dict[str, Any]:
        return {"available": True}


# --- fake Azure SDK -----------------------------------------------------------------------
class Signal:
    def __init__(self) -> None:
        self.handlers: list[Any] = []

    def connect(self, handler: Any) -> None:
        self.handlers.append(handler)

    def fire(self, evt: Any = None) -> None:
        for handler in list(self.handlers):
            handler(evt)


class _Done:
    def __init__(self, value: Any = None, exc: Exception | None = None) -> None:
        self._value, self._exc = value, exc

    def get(self, timeout: float | None = None) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._value


ResultReason = Enum("ResultReason", "RecognizedSpeech NoMatch")
CancellationReason = Enum("CancellationReason", "Error EndOfStream CancelledByUser")
CancellationErrorCode = Enum(
    "CancellationErrorCode",
    "AuthenticationFailure Forbidden TooManyRequests BadRequest ConnectionFailure "
    "ServiceTimeout ServiceUnavailable RuntimeError",
)
PropertyId = Enum(
    "PropertyId", "SpeechServiceResponse_JsonResult SpeechServiceConnection_LanguageIdMode"
)


class FakeSdk:
    """Records constructor arguments and lets a test drive callbacks."""

    ResultReason = ResultReason
    CancellationReason = CancellationReason
    CancellationErrorCode = CancellationErrorCode
    PropertyId = PropertyId
    OutputFormat = SimpleNamespace(Detailed="detailed")
    SpeechSynthesisOutputFormat = SimpleNamespace(Raw24Khz16BitMonoPcm="raw24")

    def __init__(self) -> None:
        self.configs: list[FakeSpeechConfig] = []
        self.recognizers: list[FakeRecognizer] = []
        self.synthesizers: list[FakeSynthesizer] = []
        self.pushes: list[FakePush] = []
        self.start_error: Exception | None = None
        self.start_errors: list[Exception] = []  # popped one per start attempt
        self.language_result = "en-IN"
        self.on_push_close: Any = None  # test hook: runs when the audio stream is closed
        self.audio = SimpleNamespace(
            AudioStreamFormat=lambda **kw: SimpleNamespace(**kw),
            PushAudioInputStream=self._push,
            AudioConfig=lambda stream: SimpleNamespace(stream=stream),
        )
        sdk = self
        self.SpeechConfig = lambda **kw: sdk._config(**kw)
        self.AutoDetectSourceLanguageConfig = lambda languages: SimpleNamespace(languages=languages)
        self.AutoDetectSourceLanguageResult = lambda result: SimpleNamespace(
            language=sdk.language_result
        )
        self.SpeechRecognizer = lambda **kw: sdk._recognizer(**kw)
        self.SpeechSynthesizer = lambda **kw: sdk._synth(**kw)

    def _push(self, stream_format: Any) -> FakePush:
        push = FakePush(stream_format, lambda: self.on_push_close and self.on_push_close())
        self.pushes.append(push)
        return push

    def _config(self, **kw: Any) -> FakeSpeechConfig:
        cfg = FakeSpeechConfig(**kw)
        self.configs.append(cfg)
        return cfg

    def _recognizer(self, **kw: Any) -> FakeRecognizer:
        reco = FakeRecognizer(self, **kw)
        self.recognizers.append(reco)
        return reco

    def _synth(self, **kw: Any) -> FakeSynthesizer:
        synth = FakeSynthesizer(self, **kw)
        self.synthesizers.append(synth)
        return synth

    def next_start_error(self) -> Exception | None:
        if self.start_errors:
            return self.start_errors.pop(0)
        return self.start_error


class FakeSpeechConfig:
    def __init__(self, **kw: Any) -> None:
        self.kw = kw
        self.props: dict[Any, Any] = {}
        self.output_format: Any = None
        self.synthesis_format: Any = None

    def set_property(self, key: Any, value: Any) -> None:
        self.props[key] = value

    def set_speech_synthesis_output_format(self, fmt: Any) -> None:
        self.synthesis_format = fmt


class FakePush:
    def __init__(self, stream_format: Any, on_close: Any = None) -> None:
        self.format = stream_format
        self.writes: list[bytes] = []
        self.closed = False
        self._on_close = on_close

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))

    def close(self) -> None:
        first, self.closed = not self.closed, True
        if first and self._on_close is not None:
            self._on_close()


class FakeRecognizer:
    def __init__(self, sdk: FakeSdk, **kw: Any) -> None:
        self.sdk = sdk
        self.kw = kw
        self.speech_start_detected = Signal()
        self.recognizing = Signal()
        self.recognized = Signal()
        self.canceled = Signal()
        self.session_stopped = Signal()
        self.started = 0
        self.stopped = 0

    def start_continuous_recognition_async(self) -> _Done:
        self.started += 1
        return _Done(exc=self.sdk.next_start_error())

    def stop_continuous_recognition_async(self) -> _Done:
        self.stopped += 1
        return _Done()


class FakeSynthesizer:
    def __init__(self, sdk: FakeSdk, **kw: Any) -> None:
        self.sdk = sdk
        self.kw = kw
        self.synthesizing = Signal()
        self.synthesis_completed = Signal()
        self.synthesis_canceled = Signal()
        self.ssml: list[str] = []
        self.stops = 0
        self.on_start: Any = None  # test hook: called with (synth, ssml) on the executor thread

    def start_speaking_ssml_async(self, ssml: str) -> _Done:
        self.ssml.append(ssml)
        exc = self.sdk.next_start_error()
        if exc is None and self.on_start is not None:
            self.on_start(self, ssml)
        return _Done(exc=exc)

    def stop_speaking_async(self) -> _Done:
        self.stops += 1
        return _Done()


def audio_event(data: bytes) -> Any:
    return SimpleNamespace(result=SimpleNamespace(audio_data=data))


def canceled_tts(reason: Any, code: Any = None) -> Any:
    return SimpleNamespace(
        result=SimpleNamespace(cancellation_details=SimpleNamespace(reason=reason, error_code=code))
    )


def canceled_stt(reason: Any, code: Any = None) -> Any:
    return SimpleNamespace(cancellation_details=SimpleNamespace(reason=reason, code=code))


def recognized(text: str, *, reason: Any = None, offset: int = 0, duration: int = 0, nbest=None):
    import json

    props = {}
    if nbest is not None:
        props[PropertyId.SpeechServiceResponse_JsonResult] = json.dumps({"NBest": [nbest]})
    return SimpleNamespace(
        result=SimpleNamespace(
            text=text,
            reason=reason or ResultReason.RecognizedSpeech,
            offset=offset,
            duration=duration,
            properties=SimpleNamespace(get=lambda key: props.get(key)),
        )
    )


class FakeToken:
    token = "SECRET-TOKEN-VALUE"
    expires_on = 4_000_000_000


class FakeCredential:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.scopes: list[tuple[str, ...]] = []
        self.closed = False

    def get_token(self, *scopes: str, **kw: Any) -> Any:
        self.scopes.append(scopes)
        if self.fail:
            raise RuntimeError("boom SECRET-TOKEN-VALUE")
        return FakeToken()

    def close(self) -> None:
        self.closed = True


async def drain(session: Any, *, until_closed: bool = True, limit: float = 2.0) -> list[Any]:
    async def _collect() -> list[Any]:
        return [e async for e in session.events()]

    return await asyncio.wait_for(_collect(), limit)
