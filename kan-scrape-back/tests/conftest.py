import os
from collections import abc

import pytest
from fastapi import testclient

# Tests must never touch the network: only the offline seed source is enabled,
# and the lifespan must not pull the Whisper model in (see docs/handoff-stt.md).
# Setting the keys to "" instead of popping them matters: pydantic-settings falls back to
# kan-scrape-back/.env when a variable is absent, so a developer's real key would leak into
# the test run. An empty environment variable wins over the dotenv file.
os.environ["FETCH_REMOTE_SOURCES"] = "false"
os.environ["STT_WARMUP"] = "false"
os.environ["MISTRAL_API_KEY"] = ""
os.environ["DOORKEEPER_TOKEN"] = ""
os.environ["CONNPASS_API_KEY"] = ""
os.environ["STT_FALLBACK"] = ""

from app import main  # noqa: E402
from app.core import config  # noqa: E402
from app.services import events as event_service  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_settings() -> abc.Iterator[None]:
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Second net against live Mistral calls; tests that need the LLM path re-patch these."""

    async def _blocked_call(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("tests must not call the live Mistral API")

    def _blocked_client(*args: object, **kwargs: object) -> object:
        raise AssertionError("tests must not build a real Mistral client")

    monkeypatch.setattr("app.services.matcher.call_llm", _blocked_call)
    monkeypatch.setattr("app.services.matcher.get_mistral_client", _blocked_client)


@pytest.fixture
def client() -> abc.Iterator[testclient.TestClient]:
    with testclient.TestClient(main.create_app()) as test_client:
        yield test_client


@pytest.fixture
def store(client: testclient.TestClient) -> event_service.EventStore:
    return client.app.state.event_store
