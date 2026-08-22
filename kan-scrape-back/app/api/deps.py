"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.services.events import EventStore, build_store


def get_event_store(request: Request) -> EventStore:
    """The process-wide event cache, created in the app lifespan.

    Falls back to a lazily-built seed-only store so tests that skip the lifespan still work.
    """
    store: EventStore | None = getattr(request.app.state, "event_store", None)
    if store is None:
        store = build_store(get_settings(), with_remote=False)
        store.load_seed()
        request.app.state.event_store = store
    return store


StoreDep = Annotated[EventStore, Depends(get_event_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
