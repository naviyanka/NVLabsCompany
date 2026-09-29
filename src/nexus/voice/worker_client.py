"""Connections from the gateway to the loopback voice worker."""

from __future__ import annotations

from urllib.parse import urlparse

from nexus.config import settings
from nexus.voice.tokens import mint_worker_token

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class WorkerUnavailableError(Exception):
    pass


def worker_url(path: str) -> str:
    base = urlparse(settings.voice_worker_url)
    if base.scheme not in ("ws", "http") or base.hostname not in LOOPBACK:
        raise WorkerUnavailableError("voice worker must be on loopback")
    if len(settings.voice_worker_secret) < 32:
        raise WorkerUnavailableError("voice worker secret is not configured")
    return f"ws://{base.netloc}{path}"


async def connect(scope: str, voice_session_id: str):
    """Open ``/v1/<scope>`` with a fresh single-use token; returns a websockets connection."""
    from websockets.asyncio.client import connect as ws_connect

    url = worker_url(f"/v1/{scope}")
    try:
        return await ws_connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {mint_worker_token(voice_session_id, scope)}"
            },
            max_size=1 << 20,
            open_timeout=5,
            proxy=None,
        )
    except (OSError, TimeoutError) as exc:
        raise WorkerUnavailableError("voice worker is not reachable") from exc
