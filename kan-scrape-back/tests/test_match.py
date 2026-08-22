from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services import matcher
from app.services.stt import Transcript


@pytest.fixture
def keyed_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client whose settings carry a (fake) Mistral key, so the LLM path is taken."""
    from app.core.config import get_settings

    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def test_match_text_without_api_key_is_random(client: TestClient) -> None:
    response = client.post("/api/match/text", json={"query": "python meetup in kyoto"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "random"
    assert len(body["events"]) == 1


def test_match_text_with_mocked_llm(
    keyed_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    known_id = keyed_client.get("/api/events").json()[0]["id"]

    async def fake_call_llm(query: str, events: list[Any], settings: Settings) -> dict[str, Any]:
        assert "kyoto" in query.lower()
        assert events
        return {"event_ids": [known_id, "bogus:id"], "pitch": "Go to this one on Friday."}

    monkeypatch.setattr(matcher, "call_llm", fake_call_llm)
    response = keyed_client.post("/api/match/text", json={"query": "python meetup in Kyoto"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "match"
    assert [event["id"] for event in body["events"]] == [known_id]
    assert body["pitch"] == "Go to this one on Friday."


def test_match_text_llm_raising_falls_back_to_random(
    keyed_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    async def boom(query: str, events: list[Any], settings: Settings) -> dict[str, Any]:
        calls.append(1)
        raise RuntimeError("mistral is down")

    monkeypatch.setattr(matcher, "call_llm", boom)
    response = keyed_client.post("/api/match/text", json={"query": "something fun in Osaka"})
    assert response.status_code == 200
    assert response.json()["mode"] == "random"
    assert len(calls) == 2  # retried once


def test_match_text_unknown_ids_fall_back_to_random(
    keyed_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hallucinate(query: str, events: list[Any], settings: Settings) -> dict[str, Any]:
        return {"event_ids": ["nope:1"], "pitch": "made up"}

    monkeypatch.setattr(matcher, "call_llm", hallucinate)
    body = keyed_client.post("/api/match/text", json={"query": "hiking near Kobe"}).json()
    assert body["mode"] == "random"


def test_match_text_short_query_is_random(keyed_client: TestClient) -> None:
    body = keyed_client.post("/api/match/text", json={"query": "a"}).json()
    assert body["mode"] == "random"


def test_match_voice_with_transcript(
    keyed_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    known_id = keyed_client.get("/api/events").json()[0]["id"]

    async def fake_transcribe(
        data: bytes, filename: str | None = None, content_type: str | None = None
    ) -> Transcript:
        assert data == b"webm-bytes"
        return Transcript(text="I want a python meetup in Kyoto", language="en", provider="whisper")

    async def fake_call_llm(query: str, events: list[Any], settings: Settings) -> dict[str, Any]:
        return {"event_ids": [known_id], "pitch": "Perfect fit."}

    monkeypatch.setattr("app.services.stt.transcribe", fake_transcribe)
    monkeypatch.setattr(matcher, "call_llm", fake_call_llm)

    response = keyed_client.post(
        "/api/match/voice",
        files={"audio": ("clip.webm", b"webm-bytes", "audio/webm")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "match"
    assert body["language"] == "en"
    assert body["transcript"] == "I want a python meetup in Kyoto"


def test_match_voice_empty_transcript_is_random(
    keyed_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def silent(
        data: bytes, filename: str | None = None, content_type: str | None = None
    ) -> Transcript:
        return Transcript(text="", language=None, provider="whisper")

    monkeypatch.setattr("app.services.stt.transcribe", silent)
    body = keyed_client.post(
        "/api/match/voice", files={"audio": ("clip.webm", b"x", "audio/webm")}
    ).json()
    assert body["mode"] == "random"
    assert len(body["events"]) == 1


def test_match_voice_stt_raising_is_random(
    keyed_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(
        data: bytes, filename: str | None = None, content_type: str | None = None
    ) -> Transcript:
        raise RuntimeError("no cuda")

    monkeypatch.setattr("app.services.stt.transcribe", broken)
    response = keyed_client.post(
        "/api/match/voice", files={"audio": ("clip.webm", b"x", "audio/webm")}
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "random"


def test_match_voice_empty_upload_is_random(keyed_client: TestClient) -> None:
    response = keyed_client.post(
        "/api/match/voice", files={"audio": ("clip.webm", b"", "audio/webm")}
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "random"


def test_call_llm_parses_tool_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK response unpacking works for both string and dict arguments."""

    class _Function:
        name = "pick_events"

        def __init__(self, arguments: Any) -> None:
            self.arguments = arguments

    class _ToolCall:
        def __init__(self, arguments: Any) -> None:
            self.function = _Function(arguments)

    class _Message:
        def __init__(self, arguments: Any) -> None:
            self.tool_calls = [_ToolCall(arguments)]

    class _Choice:
        def __init__(self, arguments: Any) -> None:
            self.message = _Message(arguments)

    class _Response:
        def __init__(self, arguments: Any) -> None:
            self.choices = [_Choice(arguments)]

    parsed = matcher._tool_arguments(_Response('{"event_ids": ["a"], "pitch": "hi"}'))
    assert parsed == {"event_ids": ["a"], "pitch": "hi"}
    assert matcher._tool_arguments(_Response({"event_ids": ["a"], "pitch": "hi"})) == parsed


def test_resolve_ids_tolerates_missing_prefix() -> None:
    from datetime import timedelta

    from app.schemas.event import Event
    from app.sources.base import now_jst

    event = Event(
        id="seed:abc123", title="X", starts_at=now_jst() + timedelta(days=1), source="seed"
    )
    by_id = {event.id: event}
    assert matcher.resolve_ids(["abc123"], by_id) == [event]
    assert matcher.resolve_ids(["seed:abc123"], by_id) == [event]
    assert matcher.resolve_ids(["`seed:abc123`", "seed:abc123"], by_id) == [event]
    assert matcher.resolve_ids(["nope"], by_id) == []
