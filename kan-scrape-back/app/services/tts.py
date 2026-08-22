"""edge-tts speech synthesis with a small in-memory cache."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict
from collections.abc import Iterator

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 800
CACHE_SIZE = 64
# edge-tts talks to a Microsoft websocket that can hang instead of failing. Without a
# deadline the request stalls forever and the frontend never gets its 503 to fall back
# to browser speechSynthesis.
TIMEOUT_S = 15.0
_CACHE: OrderedDict[str, bytes] = OrderedDict()


class TTSError(RuntimeError):
    """edge-tts could not produce audio (network, throttling, bad voice)."""


def cache_key(text: str, voice: str) -> str:
    return hashlib.sha1(f"{voice}\n{text}".encode()).hexdigest()


def cache_clear() -> None:
    _CACHE.clear()


def _cache_get(key: str) -> bytes | None:
    audio = _CACHE.get(key)
    if audio is not None:
        _CACHE.move_to_end(key)
    return audio


def _cache_put(key: str, audio: bytes) -> None:
    _CACHE[key] = audio
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_SIZE:
        _CACHE.popitem(last=False)


async def synthesize(text: str, voice: str) -> bytes:
    """Return MP3 bytes for `text`. Raises `TTSError` so the route can answer 503."""
    clean = text.strip()[:MAX_TEXT_CHARS]
    if not clean:
        raise TTSError("empty text")

    key = cache_key(clean, voice)
    cached = _cache_get(key)
    if cached is not None:
        logger.debug("TTS cache hit for %s", key[:8])
        return cached

    import edge_tts

    chunks: list[bytes] = []
    try:
        async with asyncio.timeout(TIMEOUT_S):
            communicate = edge_tts.Communicate(clean, voice)
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
    except TimeoutError as exc:
        raise TTSError(f"edge-tts timed out after {TIMEOUT_S:.0f}s") from exc
    except Exception as exc:  # noqa: BLE001 - edge-tts raises a wide family of errors
        raise TTSError(f"edge-tts failed: {exc}") from exc

    audio = b"".join(chunks)
    if not audio:
        raise TTSError("edge-tts returned no audio")
    _cache_put(key, audio)
    logger.info("Synthesised %d bytes of speech (%s)", len(audio), voice)
    return audio


def iter_chunks(audio: bytes, size: int = 16 * 1024) -> Iterator[bytes]:
    """Yield the buffer in chunks for a StreamingResponse."""
    for offset in range(0, len(audio), size):
        yield audio[offset : offset + size]
