"""Azure Speech STT/TTS adapters (ADR 0006, PR 3).

A transport only. Speech holds no tool, memory, approval or database surface; transcripts
leave through neutral events (``provider_types``) and synthesis renders governed text only.
No Azure SDK object appears outside this module.

Operator settings only (``azure_speech_*``), never agent config. Disabled by default and
every missing or invalid value fails closed with a stable ``AZURE_SPEECH_*`` code. Auth is
Entra only (local auth is expected to be disabled on the resource): the SDK itself requests
the one scope below, and ``_ScopedCredential`` refuses any other. No key, no scope setting,
no fallback to another scope or provider, no runtime probing.

Retries are narrow: at most one connect retry before audio starts, and at most one TTS
sentence retry before any audio of that sentence was emitted. A 429 is reported, not retried.
The SDK delivers callbacks on its own threads; each is bridged onto the event loop with
``call_soon_threadsafe`` and dropped if the session was cancelled or closed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import math
import re
import threading
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from nexus.config import settings
from nexus.voice import provider_types as pt
from nexus.voice.provider_types import (
    ALLOWED_LOCALES,
    PCM_ENCODING,
    STT_SAMPLE_RATE,
    TTS_SAMPLE_RATE,
    SessionUsage,
    SpeechProviderError,
)

CODE = "AZURE_SPEECH"
_log = logging.getLogger(__name__)

# Derived, never configured. It is the scope the Speech SDK itself requests for a token
# credential (azure.cognitiveservices.speech, _Constants.TokenRequestScopes) and the one
# Microsoft Learn documents for Speech. Live validation: docs/azure-speech-provider.md.
ENTRA_SCOPE = "https://cognitiveservices.azure.com/.default"
ENTRA_SCOPE_BASIS = "documented"
AUTH_MODE = "entra"

ENDPOINT_SHAPE = "https://<custom-subdomain>.cognitiveservices.azure.com"
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\.cognitiveservices\.azure\.com$")
# South India does not support speech processing (Microsoft Learn); not listed on purpose.
REGIONS = ("centralindia", "eastus2")
VOICES_HI = frozenset({"hi-IN-SwaraNeural", "hi-IN-MadhurNeural"})
VOICES_EN = frozenset({"en-IN-NeerjaNeural", "en-IN-PrabhatNeural"})

TIMEOUT_MAX_SECONDS = {"connect": 30.0, "tts_first_audio": 30.0, "stt_final": 60.0}
MAX_AUDIO_CHUNK_BYTES = 64_000  # 2 s of 16 kHz s16le
BYTES_PER_MS = 32  # 16 kHz * 2 bytes
STT_QUEUE_EVENTS = 64
TTS_QUEUE_EVENTS = 256
MAX_PENDING_SENTENCES = 16
MAX_SENTENCE_CHARS = 2000
SENTENCE_TOTAL_SECONDS = 30.0
CLEANUP_SECONDS = 5.0
CONNECT_RETRY_DELAY = 0.2

_sleep = asyncio.sleep

# The SDK's CancellationErrorCode names -> (stable suffix, retryable hint for the caller).
_ERRORS: dict[str, tuple[str, bool]] = {
    "AuthenticationFailure": ("AUTH_FAILED", False),
    "Forbidden": ("FORBIDDEN", False),
    "TooManyRequests": ("RATE_LIMITED", True),
    "BadRequest": ("BAD_REQUEST", False),
    "ConnectionFailure": ("CONNECTION_FAILED", True),
    "ServiceTimeout": ("TIMEOUT", True),
    "ServiceUnavailable": ("UNAVAILABLE", True),
}
# The only failures this adapter retries itself (once, before audio). 429 is never one.
_TRANSIENT = frozenset(f"{CODE}_{s}" for s in ("CONNECTION_FAILED", "TIMEOUT", "UNAVAILABLE"))


def _err(suffix: str, message: str, *, retryable: bool = False) -> SpeechProviderError:
    return SpeechProviderError(f"{CODE}_{suffix}", message, retryable=retryable)


def _mapped(name: object) -> SpeechProviderError:
    suffix, retryable = _ERRORS.get(str(name), ("SERVICE_ERROR", False))
    return _err(suffix, "the speech service reported a failure", retryable=retryable)


# --- configuration ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Config:
    endpoint: str
    region: str
    voice_hi: str
    voice_en: str
    connect_s: float
    first_audio_s: float
    stt_final_s: float


def _endpoint() -> str:
    """The operator's custom-subdomain endpoint: https, no port/path/query/userinfo."""
    from nexus.governance.ssrf_protection import guard_url

    raw = settings.azure_speech_endpoint.strip().rstrip("/")
    if not raw:
        raise _err("ENDPOINT_MISSING", "no endpoint configured")
    try:
        guard_url(raw, "azure_speech_endpoint")
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path
            or parts.port not in (None, 443)
            or not _HOST.match(host)
        ):
            raise ValueError
    except ValueError:
        raise _err("ENDPOINT_INVALID", f"endpoint must look like {ENDPOINT_SHAPE}") from None
    return f"https://{host}"


def _region() -> str:
    region = settings.azure_speech_region.strip().lower()
    if not region:
        raise _err("REGION_MISSING", "no region configured")
    if region not in REGIONS:
        raise _err("REGION_INVALID", f"region must be one of: {', '.join(REGIONS)}")
    return region


def _voice(value: str, allowed: frozenset[str], which: str) -> str:
    voice = value.strip()
    if voice not in allowed:
        raise _err("VOICE_INVALID", f"{which} voice must be one of: {', '.join(sorted(allowed))}")
    return voice


def _timeout(value: float, key: str) -> float:
    # `not (0 < x <= max)` also rejects NaN; zero, negative and infinite never disable a timeout.
    if not (0 < value <= TIMEOUT_MAX_SECONDS[key]):
        raise _err(
            "TIMEOUT_INVALID", f"{key} timeout must be within (0, {TIMEOUT_MAX_SECONDS[key]:g}]"
        )
    return float(value)


def _load_config() -> _Config:
    return _Config(
        endpoint=_endpoint(),
        region=_region(),
        voice_hi=_voice(settings.azure_speech_voice_hi, VOICES_HI, "hi-IN"),
        voice_en=_voice(settings.azure_speech_voice_en, VOICES_EN, "en-IN"),
        connect_s=_timeout(settings.azure_speech_connect_timeout_seconds, "connect"),
        first_audio_s=_timeout(
            settings.azure_speech_tts_first_audio_timeout_seconds, "tts_first_audio"
        ),
        stt_final_s=_timeout(settings.azure_speech_stt_final_timeout_seconds, "stt_final"),
    )


def _import_sdk() -> ModuleType:
    import azure.cognitiveservices.speech as sdk

    return sdk


def _default_credential() -> Any:
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:
        raise _err("IDENTITY_SDK_MISSING", "azure-identity is not installed") from None
    return DefaultAzureCredential()


def _installed(*modules: str) -> bool:
    try:
        return all(importlib.util.find_spec(m) is not None for m in modules)
    except ImportError:
        return False


class _ScopedCredential:
    """Sync ``TokenCredential`` for the SDK that only ever serves the approved scope.

    Never stores a token. ``token_requests`` counts calls so acceptance can show how many
    were made; any other scope is refused rather than forwarded.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.token_requests = 0

    def get_token(self, *scopes: str, **_ignored: Any) -> Any:
        if scopes != (ENTRA_SCOPE,):
            raise _err("SCOPE_REJECTED", "only the Speech Entra scope may be requested")
        self.token_requests += 1
        try:
            return self._inner.get_token(ENTRA_SCOPE)
        except Exception:
            raise _err("AUTH_FAILED", "could not acquire an Entra token") from None

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                _log.debug("azure_speech credential close failed")


class AzureSpeechRuntime:
    """Shared configuration, lazily imported SDK and one cached credential.

    ``sdk_loader`` and ``credential_factory`` are the injection points for tests; production
    imports the real SDK and builds ``DefaultAzureCredential`` on first use.
    """

    def __init__(
        self,
        *,
        sdk_loader: Callable[[], Any] | None = None,
        credential_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._sdk_loader = sdk_loader
        self._credential_factory = credential_factory
        self._sdk: Any = None
        self._credential: _ScopedCredential | None = None
        self._lock = threading.Lock()

    def sdk_installed(self) -> bool:
        return self._sdk_loader is not None or _installed("azure.cognitiveservices.speech")

    def identity_installed(self) -> bool:
        return self._credential_factory is not None or _installed("azure.identity", "azure.core")

    def check(self) -> _Config:
        """The validated configuration, or the first stable failure. Makes no request."""
        if not settings.azure_speech_enabled:
            raise _err("DISABLED", "Azure Speech is off (operator setting)")
        cfg = _load_config()
        if not self.sdk_installed():
            raise _err(
                "SDK_MISSING", "azure-cognitiveservices-speech is not installed (extra: speech)"
            )
        if not self.identity_installed():
            raise _err("IDENTITY_SDK_MISSING", "azure-identity is not installed")
        return cfg

    def unavailable_reason(self) -> str | None:
        try:
            self.check()
        except SpeechProviderError as exc:
            return str(exc)
        return None

    def load_sdk(self) -> Any:
        with self._lock:
            if self._sdk is None:
                try:
                    self._sdk = (self._sdk_loader or _import_sdk)()
                except ImportError:
                    raise _err(
                        "SDK_MISSING", "azure-cognitiveservices-speech is not installed"
                    ) from None
            return self._sdk

    def credential(self) -> _ScopedCredential:
        with self._lock:
            if self._credential is None:
                self._credential = _ScopedCredential(
                    (self._credential_factory or _default_credential)()
                )
            return self._credential

    def close(self) -> None:
        with self._lock:
            credential, self._credential = self._credential, None
        if credential is not None:
            credential.close()

    def status(self) -> dict[str, Any]:
        """Non-secret diagnostics. Makes no network request; shows no token or credential."""

        def ok(check: Callable[[], Any]) -> bool:
            try:
                check()
            except SpeechProviderError:
                return False
            return True

        def value(check: Callable[[], str]) -> str | None:
            try:
                return check()
            except SpeechProviderError:
                return None

        reason = self.unavailable_reason()
        return {
            "enabled": settings.azure_speech_enabled,
            "sdk_installed": self.sdk_installed(),
            "identity_sdk_installed": self.identity_installed(),
            "endpoint_valid": ok(_endpoint),
            "endpoint_shape": ENDPOINT_SHAPE,
            "region": value(_region),
            "auth": AUTH_MODE,
            "entra_scope": ENTRA_SCOPE,
            "entra_scope_basis": ENTRA_SCOPE_BASIS,
            "voices": {
                "hi-IN": value(lambda: _voice(settings.azure_speech_voice_hi, VOICES_HI, "hi-IN")),
                "en-IN": value(lambda: _voice(settings.azure_speech_voice_en, VOICES_EN, "en-IN")),
            },
            "locale_mapping": {
                **{m: list(locales) for m, locales in pt.LOCALES_BY_MODE.items()},
                pt.MODE_HINGLISH: None,
            },
            "hinglish": "gated_off",
            "timeouts_valid": all(
                ok(lambda v=v, k=k: _timeout(v, k))
                for k, v in (
                    ("connect", settings.azure_speech_connect_timeout_seconds),
                    ("tts_first_audio", settings.azure_speech_tts_first_audio_timeout_seconds),
                    ("stt_final", settings.azure_speech_stt_final_timeout_seconds),
                )
            ),
            "output": {"format": PCM_ENCODING, "sample_rate": TTS_SAMPLE_RATE},
            "available": reason is None,
            "unavailable_reason": reason,
        }


def status() -> dict[str, Any]:
    """Doctor output for the real runtime; no network, no secret."""
    return AzureSpeechRuntime().status()


# --- SSML -------------------------------------------------------------------------------
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")


def build_ssml(text: str, voice: str) -> str:
    """SSML from escaped governed text and an allow-listed voice; text cannot add tags."""
    lang = voice[:5]
    body = escape(_XML_INVALID.sub("", text))
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xml:lang="{lang}"><voice name="{voice}">{body}</voice></speak>'
    )


# --- sessions ---------------------------------------------------------------------------
def _safe(fn: Callable[..., None]) -> Callable[..., None]:
    """SDK callbacks must never raise into the SDK thread; log a code, never a payload."""

    def wrapper(*args: Any) -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            _log.warning("azure_speech callback failed")

    return wrapper


class _Session:
    """Loop-side state shared by STT and TTS sessions: queue, executor, cancel, cleanup."""

    def __init__(
        self,
        runtime: AzureSpeechRuntime,
        cfg: _Config,
        *,
        generation: int,
        request_id: str,
        usage: SessionUsage | None,
        maxsize: int,
    ) -> None:
        self.generation = generation
        self.request_id = request_id
        self._rt = runtime
        self._cfg = cfg
        self._usage = usage
        self._loop = asyncio.get_running_loop()
        self._queue = pt.EventQueue(maxsize)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="azure-speech")
        self._cancelled = False
        self._closed = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._cleanup: asyncio.Task[None] | None = None

    # events
    def _stamp(self, cls: type, **fields: Any) -> Any:
        return cls(generation=self.generation, request_id=self.request_id, **fields)

    def _emit(self, event: Any) -> None:
        if self._cancelled or self._closed:
            return  # late callback after cancel/close
        if not self._queue.put(event):
            self._fail(_err("BACKPRESSURE", "the consumer is not draining speech events"))

    def _from_thread(self, event: Any) -> None:
        try:
            self._loop.call_soon_threadsafe(self._emit, event)
        except RuntimeError:  # loop already closed
            pass

    def _before_terminal(self) -> None:
        """Hook: settle usage before the session ends (emits the Usage event)."""

    def _fail(self, exc: SpeechProviderError, *, fatal: bool = True) -> None:
        if self._cancelled or self._closed:
            return
        _log.warning(
            "azure_speech session error code=%s generation=%s request_id=%s",
            exc.code,
            self.generation,
            self.request_id,
        )
        self._before_terminal()
        self._queue.put_force(
            self._stamp(
                pt.Error, code=exc.code, message=str(exc), retryable=exc.retryable, fatal=fatal
            )
        )
        self._end()

    def _end(self) -> None:
        self._closed = True
        self._queue.close()
        self._schedule_cleanup()

    # cancel and cleanup
    def cancel(self) -> None:
        """Idempotent and non-blocking: drop queued output, stop tasks, clean up in background."""
        if self._cancelled:
            return
        self._cancelled = True
        self._queue.clear()
        self._queue.close()
        self._settle_cancelled()
        for task in self._tasks:
            task.cancel()
        self._schedule_cleanup()

    def _settle_cancelled(self) -> None:
        """Hook: record usage already incurred when cancelled (no event is emitted)."""

    def _schedule_cleanup(self) -> None:
        if self._cleanup is None:
            self._cleanup = self._loop.create_task(self._run_cleanup())

    async def _run_cleanup(self) -> None:
        try:
            await self._loop.run_in_executor(self._executor, self._teardown)
        except Exception:  # noqa: BLE001
            _log.debug("azure_speech teardown failed")
        finally:
            self._executor.shutdown(wait=False)

    def _teardown(self) -> None:
        """Blocking, idempotent SDK release; runs on the session's own executor thread."""

    async def aclose(self) -> None:
        if not self._cancelled and not self._closed:
            self._end()
        self._schedule_cleanup()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        assert self._cleanup is not None
        try:
            await asyncio.wait_for(asyncio.shield(self._cleanup), CLEANUP_SECONDS)
        except (TimeoutError, asyncio.CancelledError):
            _log.warning("azure_speech cleanup did not finish in time")

    def _blocking(self, fn: Callable[..., Any], *args: Any) -> asyncio.Future[Any]:
        return self._loop.run_in_executor(self._executor, fn, *args)

    async def _connect_with_retry(self, build: Callable[[], None]) -> SpeechProviderError | None:
        """Run ``build`` with the connect timeout; one retry for a transient failure."""
        exc: SpeechProviderError
        for attempt in (1, 2):
            try:
                await asyncio.wait_for(self._blocking(build), self._cfg.connect_s)
                return None
            except TimeoutError:
                exc = _err("TIMEOUT", "connecting to the speech service timed out", retryable=True)
            except SpeechProviderError as caught:
                exc = caught
            except Exception:  # noqa: BLE001 - SDK errors are never surfaced verbatim
                exc = _err("CONNECTION_FAILED", "could not start the speech client", retryable=True)
            if attempt == 2 or exc.code not in _TRANSIENT:
                break
            await _sleep(CONNECT_RETRY_DELAY)
        return exc

    async def events(self) -> AsyncIterator[Any]:
        async for event in self._queue:
            yield event


def _ms(ticks: object) -> int:
    return int(ticks) // 10_000 if isinstance(ticks, int) else 0  # 100 ns ticks


def _confidence(sdk: Any, result: Any) -> float | None:
    try:
        raw = result.properties.get(sdk.PropertyId.SpeechServiceResponse_JsonResult)
        value = json.loads(raw)["NBest"][0]["Confidence"]
        value = float(value)
        return value if math.isfinite(value) else None
    except Exception:  # noqa: BLE001 - confidence is optional
        return None


class _SttSession(_Session):
    def __init__(
        self, runtime: AzureSpeechRuntime, cfg: _Config, plan: pt.ModePlan, **kw: Any
    ) -> None:
        super().__init__(runtime, cfg, maxsize=STT_QUEUE_EVENTS, **kw)
        self._plan = plan
        self._push: Any = None
        self._reco: Any = None
        self._bytes = 0
        self._finishing = False
        self._settled = False
        self._ready = asyncio.Event()
        self._connect_error: SpeechProviderError | None = None
        self._stopped = asyncio.Event()
        self._tasks.append(self._loop.create_task(self._connect()))

    # connect
    async def _connect(self) -> None:
        exc = await self._connect_with_retry(self._start)
        if exc is not None:
            self._connect_error = exc
            self._fail(exc)
        else:
            self._emit(self._stamp(pt.Ready))
        self._ready.set()

    def _start(self) -> None:
        """Executor thread: build the recognizer around a headerless 16 kHz mono PCM push stream."""
        self._teardown()  # a retry starts clean
        sdk = self._rt.load_sdk()
        config = sdk.SpeechConfig(
            endpoint=self._cfg.endpoint, token_credential=self._rt.credential()
        )
        config.output_format = sdk.OutputFormat.Detailed
        fmt = sdk.audio.AudioStreamFormat(
            samples_per_second=STT_SAMPLE_RATE, bits_per_sample=16, channels=1
        )
        self._push = sdk.audio.PushAudioInputStream(stream_format=fmt)
        audio = sdk.audio.AudioConfig(stream=self._push)
        if self._plan.identify:  # Auto: at-start identification over the allow-list only
            config.set_property(sdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "AtStart")
            auto = sdk.AutoDetectSourceLanguageConfig(languages=list(self._plan.requested_locales))
            reco = sdk.SpeechRecognizer(
                speech_config=config, audio_config=audio, auto_detect_source_language_config=auto
            )
        else:
            reco = sdk.SpeechRecognizer(
                speech_config=config, audio_config=audio, language=self._plan.requested_locales[0]
            )
        reco.speech_start_detected.connect(_safe(self._on_speech_start))
        reco.recognizing.connect(_safe(self._on_recognizing))
        reco.recognized.connect(_safe(self._on_recognized))
        reco.canceled.connect(_safe(self._on_canceled))
        reco.session_stopped.connect(_safe(self._on_stopped))
        self._reco = reco
        reco.start_continuous_recognition_async().get()

    def _teardown(self) -> None:
        push, reco, self._push, self._reco = self._push, self._reco, None, None
        for step in (
            (lambda: push.close()) if push is not None else None,
            (lambda: reco.stop_continuous_recognition_async().get()) if reco is not None else None,
        ):
            if step is not None:
                try:
                    step()
                except Exception:  # noqa: BLE001 - best-effort release
                    _log.debug("azure_speech stt teardown step failed")

    # SDK callbacks (SDK threads)
    def _on_speech_start(self, _evt: Any) -> None:
        self._from_thread(self._stamp(pt.SpeechStart))

    def _on_recognizing(self, evt: Any) -> None:
        if evt.result.text:
            self._from_thread(self._stamp(pt.Partial, text=evt.result.text))

    def _on_recognized(self, evt: Any) -> None:
        sdk, result = self._rt.load_sdk(), evt.result
        if result.reason == sdk.ResultReason.RecognizedSpeech and result.text:
            self._from_thread(self._final(sdk, result))
        elif result.reason in (sdk.ResultReason.RecognizedSpeech, sdk.ResultReason.NoMatch):
            self._from_thread(self._stamp(pt.NoMatch))

    def _final(self, sdk: Any, result: Any) -> pt.Final:
        detected: str | None = None
        notice: str | None = None
        if self._plan.identify:
            language = sdk.AutoDetectSourceLanguageResult(result).language
            if language in ALLOWED_LOCALES:
                detected = language
            else:  # outside the allow-list (e.g. ur-IN) or absent: unknown, never relabelled
                notice = pt.VOICE_LANGUAGE_UNRECOGNIZED
        return self._stamp(
            pt.Final,
            text=result.text,
            selected_mode=self._plan.selected,
            requested_locales=self._plan.requested_locales,
            detected_locale=detected,
            confidence=_confidence(sdk, result),
            offset_ms=_ms(result.offset),
            duration_ms=_ms(result.duration),
            notice=notice,
        )

    def _on_canceled(self, evt: Any) -> None:
        sdk, details = self._rt.load_sdk(), evt.cancellation_details
        if details.reason == sdk.CancellationReason.Error:
            self._loop.call_soon_threadsafe(self._fail, _mapped(getattr(details.code, "name", "")))
        self._loop.call_soon_threadsafe(self._stopped.set)

    def _on_stopped(self, _evt: Any) -> None:
        self._loop.call_soon_threadsafe(self._stopped.set)

    # usage
    def _audio_ms(self) -> int:
        return self._bytes // BYTES_PER_MS

    def _settle_cancelled(self) -> None:
        self._settle(emit=False)

    def _before_terminal(self) -> None:
        self._settle(emit=True)

    def _settle(self, *, emit: bool) -> None:
        if self._settled or self._bytes == 0:
            return
        self._settled = True
        if self._usage is not None:
            self._usage.add("stt", "audio_ms", self._audio_ms())
        if emit:
            self._emit(
                self._stamp(pt.Usage, operation="stt", unit="audio_ms", quantity=self._audio_ms())
            )

    # contract
    async def send_audio(self, pcm: bytes) -> None:
        if (
            not isinstance(pcm, (bytes, bytearray, memoryview))
            or not 0 < len(pcm) <= MAX_AUDIO_CHUNK_BYTES
            or len(pcm) % 2
        ):
            raise SpeechProviderError(
                pt.VOICE_AUDIO_INVALID, "audio must be non-empty 16-bit PCM frames"
            )
        if self._cancelled:
            return
        if self._finishing:
            raise SpeechProviderError(pt.VOICE_SESSION_CLOSED, "audio was sent after finish")
        await self._ready.wait()
        if self._connect_error is not None:
            raise self._connect_error
        if self._cancelled or self._closed:
            return
        data = bytes(pcm)
        self._bytes += len(data)  # counted once handed to the stream (audio has started)
        await self._blocking(self._write, data)

    def _write(self, data: bytes) -> None:
        push = self._push
        if push is not None:
            push.write(data)

    async def finish(self) -> None:
        if self._cancelled or self._closed or self._finishing:
            return
        self._finishing = True
        await self._ready.wait()
        if self._cancelled or self._closed:
            return
        if self._bytes:
            await self._blocking(self._close_push)
            try:
                await asyncio.wait_for(self._stopped.wait(), self._cfg.stt_final_s)
            except TimeoutError:
                self._fail(_err("TIMEOUT", "no final transcript within the limit", retryable=True))
                return
        self._before_terminal()
        self._end()

    def _close_push(self) -> None:
        if self._push is not None:
            self._push.close()


class _TtsSession(_Session):
    def __init__(self, runtime: AzureSpeechRuntime, cfg: _Config, **kw: Any) -> None:
        super().__init__(runtime, cfg, maxsize=TTS_QUEUE_EVENTS, **kw)
        self._texts: asyncio.Queue[str | None] = asyncio.Queue()
        self._ended = False
        self._synth: Any = None
        self._chars = 0
        self._reported = False
        self._audio_emitted = False
        self._progress = asyncio.Event()  # first audio or terminal of the current attempt
        self._terminal: asyncio.Future[str | None] | None = None
        self._tasks.append(self._loop.create_task(self._run()))

    # contract
    async def write_text(self, text: str) -> None:
        if not isinstance(text, str):
            raise SpeechProviderError(pt.VOICE_TEXT_TOO_LONG, "text must be a string")
        if self._cancelled or not text.strip():
            return
        if self._ended or self._closed:
            raise SpeechProviderError(pt.VOICE_SESSION_CLOSED, "text was written after end_text")
        if self._texts.qsize() >= MAX_PENDING_SENTENCES:
            raise SpeechProviderError(pt.VOICE_BACKPRESSURE, "too many sentences are waiting")
        self._texts.put_nowait(text)

    async def end_text(self) -> None:
        if not self._ended and not self._cancelled:
            self._ended = True
            self._texts.put_nowait(None)

    # runner
    async def _run(self) -> None:
        try:
            exc = await self._connect_with_retry(self._build)
            if exc is not None:
                self._fail(exc)
                return
            while (text := await self._texts.get()) is not None:
                if not await self._speak(text):
                    return
            self._before_terminal()
            self._emit(self._stamp(pt.Done))
            self._end()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            self._fail(_err("SERVICE_ERROR", "speech synthesis failed"))

    def _build(self) -> None:
        self._teardown()
        sdk = self._rt.load_sdk()
        config = sdk.SpeechConfig(
            endpoint=self._cfg.endpoint, token_credential=self._rt.credential()
        )
        config.set_speech_synthesis_output_format(
            sdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
        )
        synth = sdk.SpeechSynthesizer(speech_config=config, audio_config=None)  # None: no speaker
        synth.synthesizing.connect(_safe(self._on_synthesizing))
        synth.synthesis_completed.connect(_safe(self._on_completed))
        synth.synthesis_canceled.connect(_safe(self._on_canceled))
        self._synth = synth

    def _teardown(self) -> None:
        synth, self._synth = self._synth, None
        if synth is not None:
            try:
                synth.stop_speaking_async().get()
            except Exception:  # noqa: BLE001 - best-effort release
                _log.debug("azure_speech tts teardown failed")

    def _notice(self, code: str, message: str) -> None:
        self._emit(self._stamp(pt.Error, code=code, message=message, fatal=False))

    async def _speak(self, text: str) -> bool:
        """Synthesize one sentence. False means the session failed and the runner must stop."""
        if len(text) > MAX_SENTENCE_CHARS:
            self._notice(pt.VOICE_TEXT_TOO_LONG, "sentence is too long to speak")
            return True
        script = pt.classify_script(text)
        voice = {"devanagari": self._cfg.voice_hi, "latin": self._cfg.voice_en}.get(script or "")
        if voice is None:  # e.g. Urdu/Arabic script: no approved voice, so no synthesis at all
            self._notice(pt.VOICE_SCRIPT_UNSUPPORTED, "no approved voice for this script")
            return True
        ssml = build_ssml(text, voice)
        self._chars += len(text)  # billed on request; a retry is not counted twice
        if self._usage is not None:
            self._usage.add("tts", "characters", len(text))
        sentence_audio = False
        for attempt in (1, 2):
            self._progress = asyncio.Event()
            terminal = self._terminal = self._loop.create_future()
            failure: SpeechProviderError | None = None
            try:
                await self._blocking(self._start, ssml)
                await asyncio.wait_for(self._progress.wait(), self._cfg.first_audio_s)
                if not terminal.done():
                    await asyncio.wait_for(asyncio.shield(terminal), SENTENCE_TOTAL_SECONDS)
                code = terminal.result() if terminal.done() else None
                if code is not None:
                    failure = _mapped(code)
            except TimeoutError:
                failure = _err("TIMEOUT", "no audio within the limit", retryable=True)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                failure = _err("CONNECTION_FAILED", "could not start synthesis", retryable=True)
            if failure is None:
                return True
            sentence_audio = self._audio_emitted
            await self._stop_current()
            if sentence_audio or attempt == 2 or failure.code not in _TRANSIENT:
                self._fail(failure)
                return False
            self._audio_emitted = False  # nothing was emitted: one retry of this sentence only
        return False

    def _start(self, ssml: str) -> None:
        self._synth.start_speaking_ssml_async(ssml).get()

    async def _stop_current(self) -> None:
        try:
            await asyncio.wait_for(self._blocking(self._stop), CLEANUP_SECONDS)
        except Exception:  # noqa: BLE001
            _log.debug("azure_speech stop failed")

    def _stop(self) -> None:
        if self._synth is not None:
            self._synth.stop_speaking_async().get()

    # SDK callbacks (SDK threads)
    def _on_synthesizing(self, evt: Any) -> None:
        data = evt.result.audio_data
        if data:
            self._loop.call_soon_threadsafe(self._audio, bytes(data))

    def _on_completed(self, _evt: Any) -> None:
        self._loop.call_soon_threadsafe(self._finish_attempt, None)

    def _on_canceled(self, evt: Any) -> None:
        sdk, details = self._rt.load_sdk(), evt.result.cancellation_details
        if details.reason == sdk.CancellationReason.CancelledByUser:
            return  # our own stop; the attempt's outcome was already decided
        self._loop.call_soon_threadsafe(
            self._finish_attempt, getattr(details.error_code, "name", "x")
        )

    # loop-thread handlers
    def _audio(self, data: bytes) -> None:
        if self._cancelled or self._closed:
            return
        self._audio_emitted = True
        self._progress.set()
        self._emit(self._stamp(pt.AudioChunk, pcm=data, sample_rate=TTS_SAMPLE_RATE))

    def _finish_attempt(self, code: str | None) -> None:
        terminal = self._terminal
        if terminal is not None and not terminal.done() and not (self._cancelled or self._closed):
            terminal.set_result(code)
        self._progress.set()

    def _before_terminal(self) -> None:
        if self._chars and not self._reported:
            self._reported = True
            self._emit(
                self._stamp(pt.Usage, operation="tts", unit="characters", quantity=self._chars)
            )


class _Provider:
    def __init__(self, runtime: AzureSpeechRuntime | None = None) -> None:
        self._rt = runtime or AzureSpeechRuntime()

    def status(self) -> dict[str, Any]:
        return self._rt.status()

    def _prepare(self, mode: str, generation: int, request_id: str) -> tuple[pt.ModePlan, _Config]:
        plan = pt.resolve_mode(mode)  # unknown and Hinglish fail closed before anything else
        if (
            not isinstance(generation, int)
            or generation < 0
            or not isinstance(request_id, str)
            or not (0 < len(request_id) <= 128)
        ):
            raise SpeechProviderError(
                pt.VOICE_SESSION_CLOSED, "generation and request id are required"
            )
        return plan, self._rt.check()


class AzureSpeechSttProvider(_Provider):
    async def open(
        self, mode: str, *, generation: int, request_id: str, usage: SessionUsage | None = None
    ) -> _SttSession:
        plan, cfg = self._prepare(mode, generation, request_id)
        return _SttSession(
            self._rt, cfg, plan, generation=generation, request_id=request_id, usage=usage
        )


class AzureSpeechTtsProvider(_Provider):
    async def open(
        self, mode: str, *, generation: int, request_id: str, usage: SessionUsage | None = None
    ) -> _TtsSession:
        _, cfg = self._prepare(mode, generation, request_id)
        return _TtsSession(self._rt, cfg, generation=generation, request_id=request_id, usage=usage)
