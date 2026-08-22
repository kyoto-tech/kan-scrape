"""Local-first speech-to-text.

`faster-whisper` runs on the GPU when one is available and silently degrades to CPU/int8
otherwise. Mistral Voxtral is an opt-in fallback (`STT_FALLBACK=voxtral`) used only when the
local model cannot load or raises — never while Whisper works.

The module-level `transcribe()` / `warmup()` helpers are the contract the match route codes
against; they delegate to the process-wide `SpeechToText` singleton.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_WEBM_SUFFIXES = {".webm", ".ogg", ".oga", ".opus", ".mp3", ".m4a", ".mp4", ".wav", ".flac"}


class Transcript(BaseModel):
    text: str
    language: str | None = None
    duration_s: float = 0.0
    provider: Literal["whisper", "voxtral", "none"] = "none"


class SttError(RuntimeError):
    """Transcription could not be produced (model missing, decode failure, ...)."""


class AudioTooLongError(SttError):
    """Clip exceeds `STT_MAX_SECONDS`."""


def _resolve_device(settings: Settings) -> list[tuple[str, str]]:
    """Ordered (device, compute_type) candidates to try when loading the model."""
    device = (settings.whisper_device or "auto").lower()
    compute = settings.whisper_compute_type or None

    def pair(dev: str) -> tuple[str, str]:
        return dev, compute or ("float16" if dev == "cuda" else "int8")

    if device == "cuda":
        return [pair("cuda"), pair("cpu")]
    if device == "cpu":
        return [pair("cpu")]
    return [pair("cuda"), pair("cpu")]


class SpeechToText:
    """One Whisper model, loaded once, with calls serialized behind a lock."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model: object | None = None
        self._device: str | None = None
        self._compute_type: str | None = None
        self._load_lock = asyncio.Lock()
        self._infer_lock = asyncio.Lock()
        self._force_cpu = False

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> str | None:
        return self._device

    @property
    def compute_type(self) -> str | None:
        return self._compute_type

    async def warmup(self) -> None:
        """Load the model. Idempotent, never raises — `ready` stays False on failure."""
        try:
            await self._ensure_model()
        except Exception:  # noqa: BLE001 - startup must survive a broken model
            logger.warning("Whisper warmup failed; STT stays unavailable", exc_info=True)

    async def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load_model)
        return self._model

    def _load_model(self) -> object:
        from faster_whisper import WhisperModel

        name = self._settings.whisper_model
        errors: list[str] = []
        candidates = _resolve_device(self._settings)
        if self._force_cpu:
            candidates = [pair for pair in candidates if pair[0] != "cuda"] or [("cpu", "int8")]
        if any(device == "cuda" for device, _ in candidates):
            _preload_cuda_libs()
        for device, compute_type in candidates:
            try:
                model = WhisperModel(name, device=device, compute_type=compute_type)
            except Exception as exc:  # noqa: BLE001 - try the next candidate device
                errors.append(f"{device}/{compute_type}: {exc}")
                logger.warning("Whisper failed to load on %s/%s: %s", device, compute_type, exc)
                continue
            self._device, self._compute_type = device, compute_type
            logger.info("Whisper %r loaded on %s/%s", name, device, compute_type)
            return model
        raise SttError(f"Could not load Whisper model {name!r} ({'; '.join(errors)})")

    async def transcribe(self, audio: bytes, filename: str = "audio.webm") -> Transcript:
        if not audio:
            raise SttError("Empty audio upload")

        try:
            model = await self._ensure_model()
        except Exception as exc:  # noqa: BLE001 - Voxtral may still rescue us
            transcript = await self._voxtral(audio, filename)
            if transcript is not None:
                return transcript
            raise SttError(str(exc)) from exc

        suffix = Path(filename or "").suffix.lower()
        if suffix not in _WEBM_SUFFIXES:
            suffix = ".webm"

        with tempfile.TemporaryDirectory(prefix="kan-stt-") as tmpdir:
            path = Path(tmpdir) / f"clip{suffix}"
            path.write_bytes(audio)
            async with self._infer_lock:
                try:
                    return await asyncio.to_thread(self._run, model, path)
                except AudioTooLongError:
                    raise
                except Exception as exc:  # noqa: BLE001 - decode/inference failure
                    logger.warning("Whisper transcription failed: %s", exc)
                    # CUDA can look healthy at load time and only break on the first kernel
                    # call (missing cuBLAS/cuDNN). Demote to CPU once and retry.
                    if self._device == "cuda":
                        cpu_model = await self._demote_to_cpu()
                        if cpu_model is not None:
                            try:
                                return await asyncio.to_thread(self._run, cpu_model, path)
                            except AudioTooLongError:
                                raise
                            except Exception as cpu_exc:  # noqa: BLE001
                                logger.warning("CPU retry also failed: %s", cpu_exc)
                                exc = cpu_exc
                    transcript = await self._voxtral(audio, filename)
                    if transcript is not None:
                        return transcript
                    raise SttError(str(exc)) from exc

    async def _demote_to_cpu(self) -> object | None:
        """Reload the model on CPU/int8 after a GPU runtime failure."""
        logger.warning("Whisper failed on the GPU at inference time — reloading on CPU")
        async with self._load_lock:
            self._force_cpu = True
            self._model = None
            try:
                self._model = await asyncio.to_thread(self._load_model)
            except Exception:  # noqa: BLE001 - nothing left to try
                logger.warning("CPU reload failed", exc_info=True)
                return None
        return self._model

    def _run(self, model: object, path: Path) -> Transcript:
        try:
            segments, info = model.transcribe(  # type: ignore[attr-defined]
                str(path), beam_size=1, vad_filter=True, language=None
            )
        except Exception as exc:  # noqa: BLE001 - PyAV chokes on some webm blobs
            logger.info("Direct decode failed (%s); retrying via ffmpeg", exc)
            wav = _to_wav(path)
            segments, info = model.transcribe(  # type: ignore[attr-defined]
                str(wav), beam_size=1, vad_filter=True, language=None
            )

        duration = float(getattr(info, "duration", 0.0) or 0.0)
        limit = self._settings.stt_max_seconds
        if limit and duration > limit:
            raise AudioTooLongError(f"Clip is {duration:.1f}s, limit is {limit}s")

        # Whisper segments already carry their leading space — a separator would double it.
        text = "".join(segment.text for segment in segments).strip()
        return Transcript(
            text=text,
            language=getattr(info, "language", None),
            duration_s=duration,
            provider="whisper",
        )

    async def _voxtral(self, audio: bytes, filename: str) -> Transcript | None:
        """Opt-in remote fallback. Returns None when disabled or unusable."""
        settings = self._settings
        if (settings.stt_fallback or "none").lower() != "voxtral":
            return None
        if not settings.mistral_api_key:
            logger.warning("STT_FALLBACK=voxtral but MISTRAL_API_KEY is unset")
            return None

        import httpx

        logger.info("Falling back to Voxtral for transcription")
        try:
            async with httpx.AsyncClient(timeout=settings.http_timeout_s * 3) as client:
                response = await client.post(
                    "https://api.mistral.ai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
                    files={"file": (filename or "audio.webm", audio, "application/octet-stream")},
                    data={"model": settings.voxtral_model},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:  # noqa: BLE001 - fallback is best-effort
            logger.warning("Voxtral fallback failed", exc_info=True)
            return None

        return Transcript(
            text=(payload.get("text") or "").strip(),
            language=payload.get("language"),
            duration_s=float(payload.get("duration") or 0.0),
            provider="voxtral",
        )


def _preload_cuda_libs() -> None:
    """Make the pip-installed CUDA 12 libs loadable by ctranslate2.

    The `nvidia-*-cu12` wheels drop their shared objects inside site-packages instead of a
    directory the dynamic loader searches, so we dlopen them once up front.
    """
    try:
        import nvidia
    except ImportError:
        return

    for root in nvidia.__path__:
        for lib in sorted(Path(root).glob("*/lib/lib*.so*")):
            if not any(key in lib.name for key in ("cublas", "cudnn")):
                continue
            try:
                ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
            except OSError:  # a dependency of this lib is missing; ctranslate2 will report it
                continue


def _to_wav(path: Path) -> Path:
    """Transcode to 16 kHz mono wav with ffmpeg when PyAV cannot read the container."""
    wav = path.with_suffix(".wav")
    result = subprocess.run(  # noqa: S603 - fixed argv, path is our own temp file
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            str(wav),
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not wav.exists():
        raise SttError(f"ffmpeg could not decode the audio: {result.stderr.decode()[:200]}")
    return wav


_singleton: SpeechToText | None = None


def get_stt() -> SpeechToText:
    """Process-wide singleton, FastAPI-dependency friendly."""
    global _singleton
    if _singleton is None:
        _singleton = SpeechToText(get_settings())
    return _singleton


def reset_stt() -> None:
    """Drop the singleton (tests)."""
    global _singleton
    _singleton = None


async def transcribe(
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> Transcript:
    """Return the spoken text of `data`. Raises `SttError` when no provider can answer."""
    return await get_stt().transcribe(data, filename or "audio.webm")


async def warmup() -> None:
    """Load the model ahead of the first request. Never raises."""
    await get_stt().warmup()
