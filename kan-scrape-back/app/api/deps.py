"""Shared FastAPI dependencies."""

from typing import Annotated

import fastapi

from app.core import config
from app.services import events as event_service


def get_event_store(request: fastapi.Request) -> event_service.EventStore:
    """The process-wide event cache, created in the app lifespan.

    Falls back to a lazily-built seed-only store so tests that skip the lifespan still work.
    """
    store: event_service.EventStore | None = getattr(request.app.state, "event_store", None)
    if store is None:
        store = event_service.build_store(config.get_settings(), with_remote=False)
        store.load_seed()
        request.app.state.event_store = store
    return store


StoreDep = Annotated[event_service.EventStore, fastapi.Depends(get_event_store)]
SettingsDep = Annotated[config.Settings, fastapi.Depends(config.get_settings)]
