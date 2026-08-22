"""Connpass API v2 adapter — requires CONNPASS_API_KEY, skipped when absent."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.schemas.event import Event
from app.sources.base import clean_text, guess_city, guess_lang, make_id, parse_iso

logger = logging.getLogger(__name__)

API_URL = "https://connpass.com/api/v2/events/"
PREFECTURES = "kyoto,osaka,hyogo"


def parse_events(payload: Any) -> list[Event]:
    """Parse a Connpass v2 `{"events": [...]}` payload. Never raises."""
    if not isinstance(payload, dict):
        logger.warning("Unexpected Connpass payload type: %s", type(payload).__name__)
        return []

    events: list[Event] = []
    for raw in payload.get("events") or []:
        try:
            if not isinstance(raw, dict):
                continue
            title = raw.get("title")
            starts_at = parse_iso(raw.get("started_at"))
            if not title or starts_at is None:
                continue
            location = raw.get("place") or raw.get("address")
            description = clean_text(raw.get("catch") or raw.get("description"))
            url = raw.get("event_url") or raw.get("url")
            image_url = raw.get("image_url")
            events.append(
                Event(
                    id=make_id("connpass", raw.get("id") or raw.get("event_id") or url or title),
                    title=title,
                    starts_at=starts_at,
                    ends_at=parse_iso(raw.get("ended_at")),
                    location=clean_text(location, limit=200),
                    url=url if isinstance(url, str) and url.startswith("http") else None,
                    source="connpass",
                    description=description,
                    city=guess_city(location, raw.get("address"), title) or "Other",
                    tags=["connpass", "tech"],
                    lang=guess_lang(title, description),
                    image_url=image_url if isinstance(image_url, str) else None,
                )
            )
        except Exception:  # noqa: BLE001 - skip the bad row, keep the feed
            logger.warning("Skipping malformed Connpass event", exc_info=True)
    return events


class ConnpassSource:
    name = "connpass"

    def __init__(self, api_key: str | None, timeout_s: float = 10.0) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def fetch(self) -> list[Event]:
        if not self.enabled:
            logger.info("Connpass source skipped (no CONNPASS_API_KEY)")
            return []
        headers = {"X-API-Key": self.api_key or "", "Accept": "application/json"}
        params = {"prefecture": PREFECTURES, "count": 100, "order": 2}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, headers=headers) as client:
                response = await client.get(API_URL, params=params)
            if response.status_code != 200:
                logger.info("Connpass returned HTTP %s", response.status_code)
                return []
            events = parse_events(response.json())
        except Exception:  # noqa: BLE001 - adapter must fail soft
            logger.warning("Connpass source failed", exc_info=True)
            return []
        logger.info("Connpass source produced %d events", len(events))
        return events
