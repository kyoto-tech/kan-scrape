from fastapi import APIRouter

from app.schemas.event import Event

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[Event])
def list_events() -> list[Event]:
    """List scraped events. Scrapers are not wired yet, so this returns an empty list."""
    return []
