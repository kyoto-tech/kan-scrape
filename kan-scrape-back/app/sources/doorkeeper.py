"""Doorkeeper API adapter — requires DOORKEEPER_TOKEN, skipped when absent."""

import asyncio
import logging
from typing import Any

import httpx

from app.schemas import event as event_schema
from app.sources import base

logger = logging.getLogger(__name__)

API_URL = "https://api.doorkeeper.jp/events"
PREFECTURES = ("kyoto", "osaka", "hyogo")
_PREFECTURE_CITY = {"kyoto": "Kyoto", "osaka": "Osaka", "hyogo": "Kobe"}


def parse_events(payload: Any, prefecture: str | None = None) -> list[event_schema.Event]:
    """Parse a Doorkeeper `[{"event": {...}}, ...]` payload. Never raises."""
    if not isinstance(payload, list):
        logger.warning("Unexpected Doorkeeper payload type: %s", type(payload).__name__)
        return []

    events: list[event_schema.Event] = []
    for entry in payload:
        try:
            raw = entry.get("event") if isinstance(entry, dict) else None
            if not isinstance(raw, dict):
                continue
            title = raw.get("title")
            starts_at = base.parse_iso(raw.get("starts_at"))
            if not title or starts_at is None:
                continue
            location = raw.get("venue_name") or raw.get("address")
            description = base.clean_text(raw.get("description"))
            url = raw.get("public_url")
            fallback_city = _PREFECTURE_CITY.get(prefecture or "", "Other")
            events.append(
                event_schema.Event(
                    id=base.make_id(
                        "doorkeeper", raw.get("id") or f"{title}|{starts_at.isoformat()}"
                    ),
                    title=title,
                    starts_at=starts_at,
                    ends_at=base.parse_iso(raw.get("ends_at")),
                    location=base.clean_text(location, limit=200),
                    url=url if isinstance(url, str) and url.startswith("http") else None,
                    source="doorkeeper",
                    description=description,
                    city=base.guess_city(location, raw.get("address"), title) or fallback_city,
                    tags=["doorkeeper"] + ([prefecture] if prefecture else []),
                    lang=base.guess_lang(title, description),
                )
            )
        except Exception:  # noqa: BLE001 - skip the bad row, keep the feed
            logger.warning("Skipping malformed Doorkeeper event", exc_info=True)
    return events


class DoorkeeperSource:
    name = "doorkeeper"

    def __init__(self, token: str | None, timeout_s: float = 10.0) -> None:
        self.token = token
        self.timeout_s = timeout_s

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def _fetch_one(
        self, client: httpx.AsyncClient, prefecture: str
    ) -> list[event_schema.Event]:
        params = {
            "prefecture": prefecture,
            "since": base.now_jst().date().isoformat(),
            "sort": "starts_at",
            "locale": "en",
        }
        try:
            response = await client.get(API_URL, params=params)
            if response.status_code != 200:
                logger.info("Doorkeeper %s returned HTTP %s", prefecture, response.status_code)
                return []
            return parse_events(response.json(), prefecture)
        except (httpx.HTTPError, ValueError):
            logger.warning("Doorkeeper %s fetch failed", prefecture, exc_info=True)
            return []

    async def fetch(self) -> list[event_schema.Event]:
        if not self.enabled:
            logger.info("Doorkeeper source skipped (no DOORKEEPER_TOKEN)")
            return []
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, headers=headers) as client:
                results = await asyncio.gather(
                    *(self._fetch_one(client, pref) for pref in PREFECTURES),
                    return_exceptions=True,
                )
        except Exception:  # noqa: BLE001 - adapter must fail soft
            logger.exception("Doorkeeper source failed")
            return []

        events: list[event_schema.Event] = []
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("Doorkeeper prefecture fetch failed: %s", result)
                continue
            events.extend(result)
        logger.info("Doorkeeper source produced %d events", len(events))
        return events
