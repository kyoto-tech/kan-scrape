"""Event listing, refresh and random-pick routes."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BeforeValidator

from app.api.deps import StoreDep
from app.schemas.event import Event, MatchResponse, RefreshResponse
from app.services.matcher import random_match

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def _lenient_limit(value: object) -> int | None:
    """Never 422 on `?limit=`: the frontend's URLSearchParams happily emits empty params.

    Empty or unparseable -> None (meaning "default"), negative -> None, oversized -> clamped.
    `limit=0` survives as 0, which legitimately means "no events".
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return min(parsed, MAX_LIMIT)


LenientLimit = Annotated[
    int | None,
    BeforeValidator(_lenient_limit),
    Query(description=f"0..{MAX_LIMIT}; empty or unparseable means {DEFAULT_LIMIT}"),
]


@router.get("", response_model=list[Event])
def list_events(
    store: StoreDep,
    city: Annotated[str | None, Query(description="Kyoto | Osaka | Kobe | Nara | Online")] = None,
    limit: LenientLimit = None,
) -> list[Event]:
    """Cached upcoming events, deduped and sorted by start time."""
    return store.all(city=city, limit=DEFAULT_LIMIT if limit is None else limit)


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
    """A random sample of upcoming events with a template pitch (no LLM involved)."""
    return random_match(store.all(), apologetic=False)
