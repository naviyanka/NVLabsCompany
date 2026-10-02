"""Provider-neutral speech contracts (ADR 0006, PR 3).

No provider SDK type appears here or crosses this boundary. A speech provider is a
transport only: it turns audio into text and governed text into audio. It has no tool,
memory, approval or database surface, and nothing it returns authorizes an action.

Every event carries the ``generation`` and ``request_id`` of the session that produced it,
so a consumer can drop late output after Stop or barge-in. ``cancel()`` is idempotent and
never blocks; cleanup runs in the background and is awaited by ``aclose()``.

Events deliberately hide audio bytes and transcript text from ``repr`` so an accidental
log line cannot leak them.
"""

from __future__ import annotations

import asyncio
import unicodedata
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

# --- stable codes -----------------------------------------------------------------------
VOICE_MODE_UNKNOWN = "VOICE_MODE_UNKNOWN"
HINGLISH_UNVERIFIED = "HINGLISH_UNVERIFIED"
VOICE_SCRIPT_UNSUPPORTED = "VOICE_SCRIPT_UNSUPPORTED"
VOICE_LANGUAGE_UNRECOGNIZED = "VOICE_LANGUAGE_UNRECOGNIZED"
VOICE_AUDIO_INVALID = "VOICE_AUDIO_INVALID"
VOICE_TEXT_TOO_LONG = "VOICE_TEXT_TOO_LONG"
VOICE_SESSION_CLOSED = "VOICE_SESSION_CLOSED"
VOICE_BACKPRESSURE = "VOICE_BACKPRESSURE"
VOICE_UNKNOWN_EVENT = "VOICE_UNKNOWN_EVENT"

STT_SAMPLE_RATE = 16_000  # 16 kHz mono s16le PCM, headerless (voice protocol v1)
TTS_SAMPLE_RATE = 24_000  # Raw24Khz16BitMonoPcm
PCM_ENCODING = "pcm_s16le"


class SpeechProviderError(Exception):
    """A stable ``CODE: message`` failure. The message never carries a token, key or audio."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.retryable = retryable


# --- language modes ---------------------------------------------------------------------
MODE_EN, MODE_HI, MODE_AUTO, MODE_HINGLISH = "en", "hi", "auto", "hinglish"
# Explicit Hindi is hi-IN only. ur-IN is never a candidate for hi or auto, so Hindi can
# never be reclassified as Urdu. Auto is at-start identification over this allow-list.
LOCALES_BY_MODE: dict[str, tuple[str, ...]] = {
    MODE_EN: ("en-IN",),
    MODE_HI: ("hi-IN",),
    MODE_AUTO: ("en-IN", "hi-IN"),
}
ALLOWED_LOCALES = frozenset({"en-IN", "hi-IN"})


@dataclass(frozen=True, slots=True)
class ModePlan:
    """Selected mode and the locales requested of the provider (never the detected one)."""

    selected: str
    requested_locales: tuple[str, ...]

    @property
    def identify(self) -> bool:
        return len(self.requested_locales) > 1


def resolve_mode(mode: object) -> ModePlan:
    """Map a mode to its plan. Unknown modes fail closed; Hinglish is gated off."""
    if not isinstance(mode, str):
        raise SpeechProviderError(VOICE_MODE_UNKNOWN, "unsupported language mode")
    name = mode.strip().lower()
    if name == MODE_HINGLISH:
        raise SpeechProviderError(
            HINGLISH_UNVERIFIED, "Hinglish is experimental and not enabled; pick English or Hindi"
        )
    locales = LOCALES_BY_MODE.get(name)
    if locales is None:
        raise SpeechProviderError(VOICE_MODE_UNKNOWN, "unsupported language mode")
    return ModePlan(selected=name, requested_locales=locales)


def classify_script(text: str) -> str | None:
    """``"devanagari"``, ``"latin"`` or None when the text cannot be voiced safely.

    Any letter outside Devanagari and Latin (Arabic/Urdu, CJK, ...) makes the whole text
    unsupported rather than guessing a voice. Digits and punctuation alone read as Latin.
    """
    devanagari = latin = other = digits = 0
    for ch in text:
        if "ऀ" <= ch <= "ॿ":
            if ch.isalpha() or unicodedata.category(ch).startswith("M"):
                devanagari += 1
        elif ch.isalpha():
            if unicodedata.name(ch, "").startswith("LATIN"):
                latin += 1
            else:
                other += 1
        elif ch.isdigit():
            digits += 1
    if other or not (devanagari or latin or digits):
        return None
    return "devanagari" if devanagari else "latin"


# --- events -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True, kw_only=True)
class Stamped:
    generation: int
    request_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Ready(Stamped):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechStart(Stamped):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Partial(Stamped):
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class Final(Stamped):
    """A transcript. Selected, requested and detected language stay separate fields.

    ``detected_locale`` is set only when the provider identified a language (Auto) and it
    is inside the allow-list; otherwise None, with ``notice`` naming why when it was unknown.
    """

    text: str = field(repr=False)
    selected_mode: str
    requested_locales: tuple[str, ...]
    detected_locale: str | None = None
    confidence: float | None = None
    offset_ms: int = 0
    duration_ms: int = 0
    notice: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NoMatch(Stamped):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Usage(Stamped):
    operation: str  # "stt" | "tts"
    unit: str  # "audio_ms" | "characters"
    quantity: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Error(Stamped):
    code: str
    message: str
    retryable: bool = False
    fatal: bool = True  # False: a notice for one item; the session continues


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioChunk(Stamped):
    pcm: bytes = field(repr=False)
    sample_rate: int
    encoding: str = PCM_ENCODING
    channels: int = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class Boundary(Stamped):
    text: str = field(repr=False)
    offset_ms: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Done(Stamped):
    pass


SttEvent = Ready | SpeechStart | Partial | Final | NoMatch | Usage | Error
TtsEvent = AudioChunk | Boundary | Usage | Done | Error
STT_EVENTS = (Ready, SpeechStart, Partial, Final, NoMatch, Usage, Error)
TTS_EVENTS = (AudioChunk, Boundary, Usage, Done, Error)


def check_event(event: object, allowed: tuple[type, ...]) -> Any:
    """Return a known event or fail closed: an unrecognized event is never passed along."""
    if type(event) not in allowed:
        raise SpeechProviderError(VOICE_UNKNOWN_EVENT, "unrecognized provider event")
    return event


# --- per-session usage ------------------------------------------------------------------
class SessionUsage:
    """Aggregates usage across the STT and TTS sessions of one voice session.

    Quantities only: audio milliseconds and synthesized characters, which are Azure's
    billing units. Pricing and durable settlement belong to the gateway/ledger, not here.
    """

    def __init__(self) -> None:
        self._totals: dict[str, int] = {}

    def add(self, operation: str, unit: str, quantity: int) -> None:
        key = f"{operation}.{unit}"
        self._totals[key] = self._totals.get(key, 0) + max(0, int(quantity))

    def snapshot(self) -> dict[str, int]:
        return dict(self._totals)


# --- bounded event queue ----------------------------------------------------------------
class EventQueue:
    """Single-loop bounded queue. Partials may be dropped oldest-first; nothing else is.

    ``put`` returns False when the queue is full of undroppable events, so the owner can
    fail the session instead of growing without bound or corrupting the audio order.
    """

    def __init__(self, maxsize: int) -> None:
        self._max = maxsize
        self._items: deque[Any] = deque()
        self._wake = asyncio.Event()
        self._closed = False

    def __len__(self) -> int:
        return len(self._items)

    def put(self, event: Any) -> bool:
        if self._closed:
            return True  # late event after close/cancel: dropped on purpose
        if len(self._items) >= self._max:
            for i, item in enumerate(self._items):
                if isinstance(item, Partial):
                    del self._items[i]
                    break
            else:
                return False
        self._items.append(event)
        self._wake.set()
        return True

    def put_force(self, event: Any) -> None:
        """Terminal events (errors) bypass the bound so a failure is never lost."""
        if not self._closed:
            self._items.append(event)
            self._wake.set()

    def clear(self) -> None:
        self._items.clear()

    def close(self) -> None:
        self._closed = True
        self._wake.set()

    async def get(self) -> Any | None:
        while True:
            if self._items:
                return self._items.popleft()
            if self._closed:
                return None
            self._wake.clear()
            await self._wake.wait()

    async def __aiter__(self) -> AsyncIterator[Any]:
        while (item := await self.get()) is not None:
            yield item


# --- provider protocols -----------------------------------------------------------------
class SttSession(Protocol):
    generation: int
    request_id: str

    async def send_audio(self, pcm: bytes) -> None: ...
    async def finish(self) -> None: ...
    def cancel(self) -> None: ...
    def events(self) -> AsyncIterator[SttEvent]: ...
    async def aclose(self) -> None: ...


class SttProvider(Protocol):
    async def open(
        self, mode: str, *, generation: int, request_id: str, usage: SessionUsage | None = None
    ) -> SttSession: ...

    def status(self) -> dict[str, Any]: ...


class TtsSession(Protocol):
    generation: int
    request_id: str

    async def write_text(self, text: str) -> None: ...
    async def end_text(self) -> None: ...
    def cancel(self) -> None: ...
    def events(self) -> AsyncIterator[TtsEvent]: ...
    async def aclose(self) -> None: ...


class TtsProvider(Protocol):
    async def open(
        self, mode: str, *, generation: int, request_id: str, usage: SessionUsage | None = None
    ) -> TtsSession: ...

    def status(self) -> dict[str, Any]: ...
