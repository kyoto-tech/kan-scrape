"""Meetup.com public iCal feeds — no API key required. Logic lives in the skill's scraper."""

import logging

import httpx

from app.schemas import event as event_schema
from app.sources import scraper

logger = logging.getLogger(__name__)


def parse_ical(payload: str | bytes, slug: str = "meetup") -> list[event_schema.Event]:
    """Parse an iCal feed into events. Never raises — bad feeds yield []."""
    return scraper.to_events(scraper.kansai_events.parse_meetup_ical(payload, slug))


class MeetupICalSource:
    """Fetches the configured Kansai Meetup groups."""

    name = "meetup"

    def __init__(self, slugs: list[str], timeout_s: float = 10.0) -> None:
        self.slugs = slugs
        self.timeout_s = timeout_s

    async def fetch(self) -> list[event_schema.Event]:
        if not self.slugs:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as client:
                items = await scraper.kansai_events.fetch_meetup(client, self.slugs)
        except Exception:  # noqa: BLE001 - adapter must fail soft
            logger.exception("Meetup source failed")
            return []
        events = scraper.to_events(items)
        logger.info("Meetup source produced %d events", len(events))
        return events
