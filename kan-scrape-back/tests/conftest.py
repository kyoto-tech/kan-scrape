import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# Tests must never touch the network: only the offline seed source is enabled,
# and the lifespan must not pull the Whisper model in (see docs/handoff-stt.md).
os.environ["FETCH_REMOTE_SOURCES"] = "false"
os.environ["STT_WARMUP"] = "false"
os.environ.pop("MISTRAL_API_KEY", None)

from app.core.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.events import EventStore  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def store(client: TestClient) -> EventStore:
    return client.app.state.event_store
