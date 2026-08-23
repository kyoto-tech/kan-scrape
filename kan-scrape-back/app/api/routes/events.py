"""Event listing, refresh and random-pick routes."""

import logging
from typing import Annotated

import fastapi
import pydantic

from app.api import deps
from app.schemas import event as event_schema
from app.services import matcher

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/events", tags=["events"])

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
    pydantic.BeforeValidator(_lenient_limit),
    fastapi.Query(description=f"0..{MAX_LIMIT}; empty or unparseable means {DEFAULT_LIMIT}"),
]


@router.get("", response_model=list[event_schema.Event])
def list_events(
    store: deps.StoreDep,
    city: Annotated[
        str | None, fastapi.Query(description="Kyoto | Osaka | Kobe | Nara | Online")
    ] = None,
    limit: LenientLimit = None,
) -> list[event_schema.Event]:
    """Cached upcoming events, deduped and sorted by start time."""
    return store.all(city=city, limit=DEFAULT_LIMIT if limit is None else limit)


@router.post("/refresh", response_model=event_schema.RefreshResponse)
async def refresh_events(store: deps.StoreDep) -> event_schema.RefreshResponse:
    """Re-run every adapter. Adapters fail soft, so this never errors."""
    try:
        per_source = await store.refresh()
    except Exception:  # noqa: BLE001 - the endpoint must never 500
        logger.exception("Refresh failed")
        per_source = store.per_source
    return event_schema.RefreshResponse(count=store.count(), per_source=per_source)


@router.get("/random", response_model=event_schema.MatchResponse)
def random_event(store: deps.StoreDep) -> event_schema.MatchResponse:
    """A random sample of upcoming events with a template pitch (no LLM involved)."""
    return matcher.random_match(store.all(), apologetic=False)
