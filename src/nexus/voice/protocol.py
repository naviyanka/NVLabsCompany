"""Binary audio framing between the browser and the gateway (protocol version 1).

Up (browser -> server), 8-byte header ``!BBHI`` = version, kind, reserved, seq, then
16 kHz mono s16le PCM. Down (server -> browser), 12-byte header ``!BBHII`` = version,
kind, flags, seq, sample_rate, then s16le PCM. Sequence numbers start at 0 and
increase by one per direction; anything else is rejected. All other traffic is JSON
text events. Audio is never carried as JSON or base64.
"""

from __future__ import annotations

import struct

VERSION = 1
KIND_PCM_UP = 1
KIND_PCM_DOWN = 3
FLAG_LAST = 1  # last chunk of a spoken sentence
UP = struct.Struct("!BBHI")
DOWN = struct.Struct("!BBHII")
MAX_PAYLOAD = 8192
SAMPLE_RATE_IN = 16_000
BYTES_PER_SECOND_IN = SAMPLE_RATE_IN * 2
MODES = ("auto", "hi", "en", "mixed")


class FrameError(ValueError):
    """A malformed or out-of-order frame; the connection is closed."""


def parse_up(data: bytes, expected_seq: int) -> bytes:
    if len(data) <= UP.size:
        raise FrameError("empty frame")
    ver, kind, _, seq = UP.unpack_from(data)
    payload = data[UP.size :]
    if ver != VERSION or kind != KIND_PCM_UP:
        raise FrameError("bad header")
    if seq != expected_seq:
        raise FrameError("out-of-order frame")
    if len(payload) > MAX_PAYLOAD or len(payload) % 2:
        raise FrameError("bad payload size")
    return payload


def pack_up(seq: int, pcm: bytes) -> bytes:
    return UP.pack(VERSION, KIND_PCM_UP, 0, seq) + pcm


def pack_down(seq: int, sample_rate: int, pcm: bytes, last: bool = False) -> bytes:
    return DOWN.pack(VERSION, KIND_PCM_DOWN, FLAG_LAST if last else 0, seq, sample_rate) + pcm
