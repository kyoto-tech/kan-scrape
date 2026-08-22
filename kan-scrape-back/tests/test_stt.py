"""STT service + `/api/transcribe`. The default run never loads a model or touches the GPU."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import faster_whisper
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services import stt
from app.services.stt import AudioTooLongError, SpeechToText, SttError, Transcript, get_stt

FIXTURE = Path(__file__).parent / "fixtures" / "sample.webm"


class FakeInfo:
    def __init__(self, language: str = "en", duration: float = 3.2) -> None:
        self.language = language
        self.duration = duration


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModel:
    """Stands in for `WhisperModel`; records how it was constructed and called."""

    def __init__(self, name: str, device: str, compute_type: str) -> None:
        self.name = name
        self.device = device
        self.compute_type = compute_type
        self.calls: list[dict[str, Any]] = []
        self.info = FakeInfo()
        self.segments = [FakeSegment(" I want a Python meetup"), FakeSegment(" in Kyoto.")]

    def transcribe(self, path: str, **kwargs: Any) -> tuple[list[FakeSegment], FakeInfo]:
        self.calls.append({"path": path, **kwargs})
        return self.segments, self.info


@pytest.fixture(autouse=True)
def _reset_singleton() -> Iterator[None]:
    stt.reset_stt()
    yield
    stt.reset_stt()


def _settings(**overrides: Any) -> Settings:
    return Settings(**overrides)


def _install(monkeypatch: pytest.MonkeyPatch, factory: Any) -> None:
    monkeypatch.setattr(faster_whisper, "WhisperModel", factory)


# --- service -------------------------------------------------------------------------


async def test_transcribe_joins_segments_and_passes_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models: list[FakeModel] = []

    def factory(name: str, device: str, compute_type: str) -> FakeModel:
        model = FakeModel(name, device, compute_type)
        models.append(model)
        return model

    _install(monkeypatch, factory)
    service = SpeechToText(_settings(whisper_device="cpu", whisper_model="tiny"))

    result = await service.transcribe(b"fake-bytes", "clip.webm")

    assert result == Transcript(
        text="I want a Python meetup in Kyoto.", language="en", duration_s=3.2, provider="whisper"
    )
    assert service.ready is True
    call = models[0].calls[0]
    assert call["beam_size"] == 1 and call["vad_filter"] is True and call["language"] is None
    assert call["path"].endswith(".webm")


async def test_model_is_loaded_once(monkeypatch: pytest.MonkeyPatch) -> None:
    built = 0

    def factory(name: str, device: str, compute_type: str) -> FakeModel:
        nonlocal built
        built += 1
        return FakeModel(name, device, compute_type)

    _install(monkeypatch, factory)
    service = SpeechToText(_settings(whisper_device="cpu"))

    assert service.ready is False
    await service.warmup()
    await service.warmup()
    await service.transcribe(b"bytes")

    assert built == 1


async def test_cuda_failure_falls_back_to_cpu_int8(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(name: str, device: str, compute_type: str) -> FakeModel:
        if device == "cuda":
            raise RuntimeError("no cudnn here")
        return FakeModel(name, device, compute_type)

    _install(monkeypatch, factory)
    service = SpeechToText(_settings(whisper_device="auto"))

    await service.transcribe(b"bytes")

    assert (service.device, service.compute_type) == ("cpu", "int8")


async def test_warmup_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(name: str, device: str, compute_type: str) -> FakeModel:
        raise RuntimeError("model file is missing")

    _install(monkeypatch, factory)
    service = SpeechToText(_settings(whisper_device="cpu"))

    await service.warmup()

    assert service.ready is False
    with pytest.raises(SttError):
        await service.transcribe(b"bytes")


async def test_clip_over_the_limit_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(name: str, device: str, compute_type: str) -> FakeModel:
        model = FakeModel(name, device, compute_type)
        model.info = FakeInfo(duration=120.0)
        return model

    _install(monkeypatch, factory)
    service = SpeechToText(_settings(whisper_device="cpu", stt_max_seconds=60))

    with pytest.raises(AudioTooLongError):
        await service.transcribe(b"bytes")


async def test_empty_audio_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SpeechToText(_settings(whisper_device="cpu"))
    with pytest.raises(SttError):
        await service.transcribe(b"")


async def test_module_level_helpers_use_the_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, FakeModel)
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")

    await stt.warmup()
    result = await stt.transcribe(b"bytes", "clip.webm", "audio/webm")

    assert result.provider == "whisper"
    assert get_stt().ready is True


# --- route ---------------------------------------------------------------------------


class FakeService:
    def __init__(self, result: Transcript | Exception) -> None:
        self.result = result

    async def transcribe(self, audio: bytes, filename: str = "audio.webm") -> Transcript:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _use(monkeypatch: pytest.MonkeyPatch, result: Transcript | Exception) -> None:
    monkeypatch.setattr("app.api.routes.transcribe.get_stt", lambda: FakeService(result))


def test_route_returns_the_transcript(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(
        monkeypatch,
        Transcript(text="hello kansai", language="en", duration_s=1.5, provider="whisper"),
    )

    response = client.post("/api/transcribe", files={"audio": ("c.webm", b"x", "audio/webm")})

    assert response.status_code == 200
    assert response.json() == {
        "text": "hello kansai",
        "language": "en",
        "duration_s": 1.5,
        "provider": "whisper",
    }


def test_route_rejects_empty_upload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, Transcript(text="unused"))

    response = client.post("/api/transcribe", files={"audio": ("c.webm", b"", "audio/webm")})

    assert response.status_code == 400


def test_route_rejects_oversize_upload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, Transcript(text="unused"))
    blob = b"0" * (10 * 1024 * 1024 + 1)

    response = client.post("/api/transcribe", files={"audio": ("c.webm", blob, "audio/webm")})

    assert response.status_code == 413


def test_route_rejects_too_long_clip(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, AudioTooLongError("Clip is 120.0s, limit is 60s"))

    response = client.post("/api/transcribe", files={"audio": ("c.webm", b"x", "audio/webm")})

    assert response.status_code == 413


def test_route_returns_503_when_the_model_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, SttError("model failed to load"))

    response = client.post("/api/transcribe", files={"audio": ("c.webm", b"x", "audio/webm")})

    assert response.status_code == 503
    assert response.json() == {"detail": "Transcription unavailable"}


# --- integration ---------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_STT_INTEGRATION") != "1", reason="set RUN_STT_INTEGRATION=1"
)
async def test_real_tiny_model_on_the_fixture() -> None:
    service = SpeechToText(_settings(whisper_model="tiny", whisper_device="auto"))

    result = await service.transcribe(FIXTURE.read_bytes(), "sample.webm")

    assert result.provider == "whisper"
    assert result.language == "en"
    assert "kyoto" in result.text.lower()
