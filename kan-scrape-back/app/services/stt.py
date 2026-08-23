"""Local-first speech-to-text.

`faster-whisper` runs on an NVIDIA GPU when one is available. On Apple Silicon it degrades to
CPU/int8 unless the optional `mlx` extra is installed, which routes inference through
`mlx-whisper` on the Metal GPU instead. Any backend failure falls back to CPU.

Mistral Voxtral is an opt-in fallback (`STT_FALLBACK=voxtral`) used only when the local model
cannot load or raises — never while Whisper works.

The module-level `transcribe()` / `warmup()` helpers are the contract the match route codes
against; they delegate to the process-wide `SpeechToText` singleton.
"""

import asyncio
import contextlib
import ctypes
import logging
import pathlib
import platform
import subprocess
import sys
import tempfile
import threading
from collections import abc
from typing import Literal

import pydantic

from app.core import config

logger = logging.getLogger(__name__)

_WEBM_SUFFIXES = {".webm", ".ogg", ".oga", ".opus", ".mp3", ".m4a", ".mp4", ".wav", ".flac"}


class Transcript(pydantic.BaseModel):
    text: str
    language: str | None = None
    duration_s: float = 0.0
    provider: Literal["whisper", "voxtral", "none"] = "none"


class SttError(RuntimeError):
    """Transcription could not be produced (model missing, decode failure, ...)."""


class AudioTooLongError(SttError):
    """Clip exceeds `STT_MAX_SECONDS`."""


#: Devices that mean "use the machine's GPU". Everything else falls back to CPU/int8.
_GPU_DEVICES = frozenset({"cuda", "mlx"})


async def _in_daemon_thread(func: abc.Callable[[], object]) -> object:
    """Like `asyncio.to_thread`, but on a daemon thread.

    The model load takes 30-120s on a cold cache, and the default executor's threads are
    joined on interpreter exit — so a Ctrl-C during the load would otherwise block until the
    weights finished loading. A daemon thread lets the process die immediately instead.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[object] = loop.create_future()

    def _settle(setter: abc.Callable[[object], None], value: object) -> None:
        if not future.done():
            setter(value)

    def _runner() -> None:
        try:
            result = func()
        except BaseException as exc:  # noqa: BLE001 - forwarded to the awaiting coroutine
            with contextlib.suppress(RuntimeError):  # loop already closed: nobody is waiting
                loop.call_soon_threadsafe(_settle, future.set_exception, exc)
        else:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(_settle, future.set_result, result)

    threading.Thread(target=_runner, name="whisper-load", daemon=True).start()
    return await future


def _is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() in {"arm64", "aarch64"}


def _resolve_device(settings: config.Settings) -> list[tuple[str, str]]:
    """Ordered (device, compute_type) candidates to try when loading the model.

    `auto` picks per platform: CUDA on Linux/Windows, MLX (Metal) on Apple Silicon, CPU on an
    Intel Mac. CPU/int8 is always the last resort, so an unavailable GPU is never fatal.
    """
    device = (settings.whisper_device or "auto").lower()
    compute = settings.whisper_compute_type or None

    def pair(dev: str) -> tuple[str, str]:
        return dev, compute or ("float16" if dev in _GPU_DEVICES else "int8")

    if device in {"mlx", "mps", "metal"}:
        return [pair("mlx"), pair("cpu")]
    if device == "cuda":
        return [pair("cuda"), pair("cpu")]
    if device == "cpu":
        return [pair("cpu")]
    if sys.platform == "darwin":
        # ctranslate2 has no Metal backend, so CUDA is never worth attempting here.
        return [pair("mlx"), pair("cpu")] if _is_apple_silicon() else [pair("cpu")]
    return [pair("cuda"), pair("cpu")]


#: faster-whisper model name -> mlx-community HF repo. The naming there is not a pattern:
#: turbo dropped the `-mlx` suffix that the others kept, so guessing gets you a 404.
#: Verified against the HF API — each repo holds a config.json plus MLX weights.
MLX_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-turbo",
}

#: Used when the configured model has no mlx-community counterpart. Matches the default
#: WHISPER_MODEL, so the two backends transcribe with the same model out of the box.
MLX_DEFAULT_REPO = "mlx-community/whisper-large-v3-turbo"


class _MlxSegment:
    """faster-whisper-shaped segment."""

    __slots__ = ("end", "start", "text")

    def __init__(self, text: str, start: float, end: float) -> None:
        self.text, self.start, self.end = text, start, end


class _MlxInfo:
    """faster-whisper-shaped transcription info."""

    __slots__ = ("duration", "language")

    def __init__(self, language: str | None, duration: float) -> None:
        self.language, self.duration = language, duration


class _MlxModel:
    """Adapter presenting `mlx-whisper` with the faster-whisper `WhisperModel` interface.

    Keeping the same `(segments, info)` shape means the transcription, priming and
    duration-limit paths stay backend-agnostic.
    """

    def __init__(self, repo: str) -> None:
        import mlx_whisper  # noqa: PLC0415 - optional, Apple-Silicon-only dependency

        self._mlx = mlx_whisper
        self.repo = repo

    def transcribe(self, audio: object, **kwargs: object) -> tuple[list[_MlxSegment], _MlxInfo]:
        # mlx-whisper has no beam_size/vad_filter knobs; drop what it does not understand.
        options: dict[str, object] = {}
        if kwargs.get("language"):
            options["language"] = kwargs["language"]

        result = self._mlx.transcribe(audio, path_or_hf_repo=self.repo, **options)
        segments = [
            _MlxSegment(item.get("text", ""), item.get("start", 0.0), item.get("end", 0.0))
            for item in result.get("segments") or []
        ]
        # mlx-whisper reports no clip duration, so use the last speech timestamp. That
        # under-reports trailing silence, which only makes the length limit more lenient.
        duration = max((segment.end for segment in segments), default=0.0)
        return segments, _MlxInfo(result.get("language"), float(duration))


class SpeechToText:
    """One Whisper model, loaded once, with calls serialized behind a lock."""

    def __init__(self, settings: config.Settings | None = None) -> None:
        self._settings = settings or config.get_settings()
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
    def model_name(self) -> str:
        return self._settings.whisper_model

    @property
    def device(self) -> str | None:
        return self._device

    @property
    def compute_type(self) -> str | None:
        return self._compute_type

    async def warmup(self) -> None:
        """Load the model. Idempotent, never raises — `ready` stays False on failure."""
        if not self._settings.stt_warmup:
            logger.info("STT warmup disabled; the model loads on the first request")
            return
        try:
            await self._ensure_model()
        except Exception:  # noqa: BLE001 - startup must survive a broken model
            logger.warning("Whisper warmup failed; STT stays unavailable", exc_info=True)

    async def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                self._model = await _in_daemon_thread(self._load_model)
        return self._model

    def _load_model(self) -> object:
        name = self._settings.whisper_model
        errors: list[str] = []
        candidates = _resolve_device(self._settings)
        if self._force_cpu:
            candidates = [pair for pair in candidates if pair[0] not in _GPU_DEVICES] or [
                ("cpu", "int8")
            ]
        if any(device == "cuda" for device, _ in candidates):
            _preload_cuda_libs()
        for device, compute_type in candidates:
            try:
                model = self._build_backend(name, device, compute_type)
            except Exception as exc:  # noqa: BLE001 - try the next candidate device
                errors.append(f"{device}/{compute_type}: {exc}")
                logger.warning("Whisper failed to load on %s/%s: %s", device, compute_type, exc)
                continue
            self._device, self._compute_type = device, compute_type
            logger.info("Whisper %r loaded on %s/%s", name, device, compute_type)
            self._prime(model)
            return model
        raise SttError(f"Could not load Whisper model {name!r} ({'; '.join(errors)})")

    def _build_backend(self, name: str, device: str, compute_type: str) -> object:
        if device == "mlx":
            return _MlxModel(self._mlx_repo())

        import faster_whisper  # noqa: PLC0415 - keeps import cost off startup

        return self._build(faster_whisper.WhisperModel, name, device, compute_type)

    def _mlx_repo(self) -> str:
        """Map the configured model name onto an mlx-community HF repo."""
        name = self._settings.whisper_model
        if "/" in name:  # already a full HF repo id
            return name
        repo = MLX_REPOS.get(name)
        if repo is None:
            logger.warning(
                "No mlx-community repo known for %r — falling back to %s", name, MLX_DEFAULT_REPO
            )
            return MLX_DEFAULT_REPO
        return repo

    @staticmethod
    def _prime(model: object) -> None:
        """Run one inference on silence so the GPU kernels are ready before the first request.

        Loading the weights is not the same as being warm: the first real call otherwise pays
        ~0.6s of cuDNN/cuBLAS (or Metal shader) init. A second of zeros forces that work now,
        and on CUDA it is also what actually moves the weights into VRAM.
        """
        try:
            import numpy as np

            segments, _ = model.transcribe(  # type: ignore[attr-defined]
                np.zeros(16_000, dtype=np.float32), beam_size=1
            )
            for _ in segments:
                pass
        except Exception:  # noqa: BLE001 - priming is an optimisation, never a requirement
            logger.debug("Whisper priming skipped", exc_info=True)

    @staticmethod
    def _build(factory: object, name: str, device: str, compute_type: str) -> object:
        """Load from the local HF cache first.

        The default path pings huggingface.co for the current revision on every boot, which
        costs seconds of startup and fails outright offline. Only reach for the network when
        the model genuinely is not cached yet.
        """
        try:
            return factory(  # type: ignore[operator]
                name, device=device, compute_type=compute_type, local_files_only=True
            )
        except TypeError:
            # A stand-in (tests) that does not take the kwarg.
            return factory(name, device=device, compute_type=compute_type)  # type: ignore[operator]
        except Exception:  # noqa: BLE001 - not cached yet; allow the download
            logger.info("Whisper %r is not in the local cache — downloading", name)
            return factory(name, device=device, compute_type=compute_type)  # type: ignore[operator]

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

        suffix = pathlib.Path(filename or "").suffix.lower()
        if suffix not in _WEBM_SUFFIXES:
            suffix = ".webm"

        with tempfile.TemporaryDirectory(prefix="kan-stt-") as tmpdir:
            path = pathlib.Path(tmpdir) / f"clip{suffix}"
            path.write_bytes(audio)
            async with self._infer_lock:
                try:
                    return await asyncio.to_thread(self._run, model, path)
                except AudioTooLongError:
                    raise
                except Exception as exc:  # noqa: BLE001 - decode/inference failure
                    logger.warning("Whisper transcription failed: %s", exc)
                    # A GPU backend can look healthy at load time and only break on the first
                    # kernel call (missing cuBLAS/cuDNN, unsupported Metal op). Demote once.
                    if self._device in _GPU_DEVICES:
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
        logger.warning("Whisper failed on %s at inference time — reloading on CPU", self._device)
        async with self._load_lock:
            self._force_cpu = True
            self._model = None
            try:
                self._model = await _in_daemon_thread(self._load_model)
            except Exception:  # noqa: BLE001 - nothing left to try
                logger.warning("CPU reload failed", exc_info=True)
                return None
        return self._model

    def _run(self, model: object, path: pathlib.Path) -> Transcript:
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
        for lib in sorted(pathlib.Path(root).glob("*/lib/lib*.so*")):
            if not any(key in lib.name for key in ("cublas", "cudnn")):
                continue
            try:
                ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
            except OSError:  # a dependency of this lib is missing; ctranslate2 will report it
                continue


def _to_wav(path: pathlib.Path) -> pathlib.Path:
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
        _singleton = SpeechToText(config.get_settings())
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
