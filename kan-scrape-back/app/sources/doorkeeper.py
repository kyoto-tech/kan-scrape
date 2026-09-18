"""Doorkeeper API adapter — requires DOORKEEPER_TOKEN, skipped when absent.

Logic lives in the skill's scraper.
"""

import logging
from typing import Any

import httpx

from app.schemas import event as event_schema
from app.sources import scraper

logger = logging.getLogger(__name__)


def parse_events(payload: Any, prefecture: str | None = None) -> list[event_schema.Event]:
    """Parse a Doorkeeper `[{"event": {...}}, ...]` payload. Never raises."""
    return scraper.to_events(scraper.kansai_events.parse_doorkeeper(payload, prefecture))


class DoorkeeperSource:
    name = "doorkeeper"

    def __init__(self, token: str | None, timeout_s: float = 10.0) -> None:
        self.token = token
        self.timeout_s = timeout_s

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def fetch(self) -> list[event_schema.Event]:
        if not self.token:
            logger.info("Doorkeeper source skipped (no DOORKEEPER_TOKEN)")
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                items = await scraper.kansai_events.fetch_doorkeeper(client, self.token)
        except Exception:  # noqa: BLE001 - adapter must fail soft
            logger.exception("Doorkeeper source failed")
            return []
        events = scraper.to_events(items)
        logger.info("Doorkeeper source produced %d events", len(events))
        return events
