from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services import tts


class _FakeCommunicate:
    calls: list[tuple[str, str]] = []

    def __init__(self, text: str, voice: str, **kwargs: Any) -> None:
        self.text = text
        self.voice = voice
        _FakeCommunicate.calls.append((text, voice))

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "WordBoundary", "offset": 0}
        yield {"type": "audio", "data": b"ID3-fake-"}
        yield {"type": "audio", "data": b"mp3-bytes"}


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    tts.cache_clear()
    _FakeCommunicate.calls = []


@pytest.fixture
def fake_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _FakeCommunicate)


def test_speech_returns_audio(client: TestClient, fake_edge: None) -> None:
    response = client.get("/api/speech", params={"text": "hello there"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3-fake-mp3-bytes"


def test_speech_uses_cache(client: TestClient, fake_edge: None) -> None:
    client.get("/api/speech", params={"text": "cache me"})
    client.get("/api/speech", params={"text": "cache me"})
    assert len(_FakeCommunicate.calls) == 1


def test_speech_custom_voice(client: TestClient, fake_edge: None) -> None:
    client.get("/api/speech", params={"text": "hi", "voice": "ja-JP-NanamiNeural"})
    assert _FakeCommunicate.calls[0][1] == "ja-JP-NanamiNeural"


def test_speech_failure_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import edge_tts

    class _Broken:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("no websocket")

        async def stream(self) -> AsyncIterator[dict[str, Any]]:  # pragma: no cover
            yield {}

    monkeypatch.setattr(edge_tts, "Communicate", _Broken)
    response = client.get("/api/speech", params={"text": "hello"})
    assert response.status_code == 503


def test_speech_requires_text(client: TestClient) -> None:
    assert client.get("/api/speech").status_code == 422


async def test_synthesize_empty_text_raises() -> None:
    with pytest.raises(tts.TTSError):
        await tts.synthesize("   ", "en-US-AvaMultilingualNeural")
