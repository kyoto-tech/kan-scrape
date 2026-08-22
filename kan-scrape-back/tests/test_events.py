from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.services.events import EventStore
from app.sources.base import now_jst


def test_list_events_returns_seed_events(client: TestClient) -> None:
    response = client.get("/api/events")
    assert response.status_code == 200
    events = response.json()
    assert len(events) >= 15
    assert {"id", "title", "starts_at", "source"} <= set(events[0])
    assert all(event["source"] == "seed" for event in events)


def test_list_events_are_future_only_and_sorted(client: TestClient) -> None:
    events = client.get("/api/events").json()
    starts = [event["starts_at"] for event in events]
    assert starts == sorted(starts)
    now = now_jst() - timedelta(minutes=1)
    assert all(datetime.fromisoformat(s) >= now for s in starts)


def test_list_events_filters_and_limits(client: TestClient) -> None:
    kyoto = client.get("/api/events", params={"city": "kyoto", "limit": 3}).json()
    assert 0 < len(kyoto) <= 3
    assert all(event["city"] == "Kyoto" for event in kyoto)


def test_random_event(client: TestClient) -> None:
    response = client.get("/api/events/random")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "random"
    assert len(body["events"]) == 1
    assert body["pitch"]


def test_refresh_without_remote_sources(client: TestClient) -> None:
    response = client.post("/api/events/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] > 0
    assert body["per_source"]["seed"] > 0


def test_store_dedupes_and_drops_past_events() -> None:
    from app.schemas.event import Event

    now = now_jst()
    store = EventStore(remote_sources=[])
    store.set_seed_events(
        [
            Event(id="a:1", title="Same Title", starts_at=now + timedelta(days=1), source="a"),
            Event(id="b:1", title="same   title", starts_at=now + timedelta(days=1), source="b"),
            Event(id="c:1", title="Old", starts_at=now - timedelta(days=1), source="c"),
        ]
    )
    events = store.all()
    assert [event.id for event in events] == ["a:1"]


def test_no_events_random_is_graceful() -> None:
    from app.services.matcher import random_match

    response = random_match([])
    assert response.mode == "random"
    assert response.events == []
    assert response.pitch
