from datetime import datetime, timedelta

import pytest
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


def test_list_events_tolerates_empty_and_odd_limits(client: TestClient) -> None:
    """URLSearchParams from the frontend emits `?city=&limit=` — that must not 422."""
    default_count = len(client.get("/api/events").json())

    blank = client.get("/api/events?city=&limit=")
    assert blank.status_code == 200
    assert len(blank.json()) == default_count

    zero = client.get("/api/events", params={"limit": 0})
    assert zero.status_code == 200
    assert zero.json() == []

    for odd in ("abc", "-5", " "):
        response = client.get(f"/api/events?limit={odd}")
        assert response.status_code == 200, odd
        assert len(response.json()) == default_count

    clamped = client.get("/api/events", params={"limit": 100000})
    assert clamped.status_code == 200
    assert len(clamped.json()) <= 500


def test_random_event(client: TestClient) -> None:
    response = client.get("/api/events/random")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "random"
    assert 2 <= len(body["events"]) <= 5
    assert body["pitch"]


def test_random_match_samples_several_distinct_events() -> None:
    from app.schemas.event import Event
    from app.services.matcher import MAX_PICK, random_match

    now = now_jst()
    pool = [
        Event(
            id=f"seed:{index}",
            title=f"Event {index}",
            starts_at=now + timedelta(days=index + 1),
            source="seed",
        )
        for index in range(10)
    ]
    result = random_match(pool, apologetic=False)
    ids = [event.id for event in result.events]
    assert 2 <= len(ids) <= MAX_PICK
    assert len(ids) == len(set(ids))
    assert set(ids) <= {event.id for event in pool}


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


def test_upcoming_copy_survives_a_past_duplicate() -> None:
    """Dedupe must not let this morning's copy of an event hide tonight's."""
    from app.schemas.event import Event

    now = now_jst()
    store = EventStore(remote_sources=[])
    store.set_seed_events(
        [
            Event(id="a:past", title="Same Title", starts_at=now - timedelta(hours=3), source="a"),
            Event(id="a:next", title="Same Title", starts_at=now + timedelta(hours=3), source="a"),
        ]
    )
    assert [event.id for event in store.all()] == ["a:next"]


def test_naive_datetimes_do_not_break_listing() -> None:
    """A source handing us a naive datetime used to make every read raise TypeError."""
    from app.schemas.event import Event

    naive = (now_jst() + timedelta(days=2)).replace(tzinfo=None)
    store = EventStore(remote_sources=[])
    store.set_seed_events(
        [
            Event(id="a:naive", title="Naive", starts_at=naive, source="a"),
            Event(id="a:aware", title="Aware", starts_at=now_jst() + timedelta(days=1), source="a"),
        ]
    )
    assert [event.id for event in store.all()] == ["a:aware", "a:naive"]


def test_store_all_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever goes wrong in the cache, the API serves an empty list rather than a 500."""
    store = EventStore(remote_sources=[])
    store.load_seed()

    def boom(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("poisoned cache")

    monkeypatch.setattr("app.services.events.upcoming", boom)
    assert store.all() == []
    assert store.count() == 0
