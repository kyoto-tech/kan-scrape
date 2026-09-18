"""Connpass API v2 adapter — requires CONNPASS_API_KEY, skipped when absent.

Logic lives in the skill's scraper.
"""

import logging
from typing import Any

import httpx

from app.schemas import event as event_schema
from app.sources import scraper

logger = logging.getLogger(__name__)


def parse_events(payload: Any) -> list[event_schema.Event]:
    """Parse a Connpass v2 `{"events": [...]}` payload. Never raises."""
    return scraper.to_events(scraper.kansai_events.parse_connpass(payload))


class ConnpassSource:
    name = "connpass"

    def __init__(self, api_key: str | None, timeout_s: float = 10.0) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def fetch(self) -> list[event_schema.Event]:
        if not self.api_key:
            logger.info("Connpass source skipped (no CONNPASS_API_KEY)")
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                items = await scraper.kansai_events.fetch_connpass(client, self.api_key)
        except Exception:  # noqa: BLE001 - adapter must fail soft
            logger.warning("Connpass source failed", exc_info=True)
            return []
        events = scraper.to_events(items)
        logger.info("Connpass source produced %d events", len(events))
        return events
