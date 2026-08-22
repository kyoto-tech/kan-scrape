"""Event listing, refresh and random-pick routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from app.api.deps import StoreDep
from app.schemas.event import Event, MatchResponse, RefreshResponse
from app.services.matcher import random_match

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[Event])
def list_events(
    store: StoreDep,
    city: str | None = Query(default=None, description="Kyoto | Osaka | Kobe | Nara | Online"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Event]:
    """Cached upcoming events, deduped and sorted by start time."""
    return store.all(city=city, limit=limit)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_events(store: StoreDep) -> RefreshResponse:
    """Re-run every adapter. Adapters fail soft, so this never errors."""
    try:
        per_source = await store.refresh()
    except Exception:  # noqa: BLE001 - the endpoint must never 500
        logger.exception("Refresh failed")
        per_source = store.per_source
    return RefreshResponse(count=store.count(), per_source=per_source)


@router.get("/random", response_model=MatchResponse)
def random_event(store: StoreDep) -> MatchResponse:
    """One random upcoming event with a template pitch (no LLM involved)."""
    return random_match(store.all(), apologetic=False)
