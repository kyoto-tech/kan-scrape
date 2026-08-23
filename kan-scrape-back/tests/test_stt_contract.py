"""The voice route only relies on this module-level contract — keep it stable."""

import asyncio
import inspect
import threading
import time

import pytest
from fastapi import testclient

from app import main
from app.core import config
from app.services import stt


def test_module_exposes_the_voice_route_contract() -> None:
    assert inspect.iscoroutinefunction(stt.transcribe)
    assert inspect.iscoroutinefunction(stt.warmup)

    params = list(inspect.signature(stt.transcribe).parameters)
    assert params == ["data", "filename", "content_type"]

    fields = stt.Transcript.model_fields
    assert set(fields) == {"text", "language", "duration_s", "provider"}


async def test_model_loads_on_a_daemon_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cold Whisper load takes 30-120s; on a pool thread it would delay Ctrl-C by that long."""
    seen: dict[str, object] = {}

    def fake_load() -> object:
        current = threading.current_thread()
        seen["daemon"] = current.daemon
        return object()

    service = stt.SpeechToText(config.get_settings())
    monkeypatch.setattr(service, "_load_model", fake_load)

    await service._ensure_model()

    assert seen["daemon"] is True


def test_lifespan_does_not_block_on_stt_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Warmup is a background task: startup (and shutdown) must not wait for the model."""

    async def slow_warmup() -> None:
        await asyncio.sleep(30)

    monkeypatch.setattr(stt, "warmup", slow_warmup)

    started = time.perf_counter()
    with testclient.TestClient(main.create_app()) as client:
        assert client.get("/api/health").status_code == 200
    assert time.perf_counter() - started < 5
