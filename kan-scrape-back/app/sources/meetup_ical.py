"""Meetup.com public iCal feeds — no API key required."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from icalendar import Calendar

from app.schemas.event import Event
from app.sources.base import (
    clean_text,
    ensure_aware,
    guess_city,
    guess_lang,
    make_id,
)

logger = logging.getLogger(__name__)

ICAL_URL = "https://www.meetup.com/{slug}/events/ical/"
USER_AGENT = "kan-scrape/0.1 (+https://github.com/) python-httpx"


def _component_str(component: Any, key: str) -> str | None:
    value = component.get(key)
    if value is None:
        return None
    return str(value)


def parse_ical(payload: str | bytes, slug: str = "meetup") -> list[Event]:
    """Parse an iCal feed into events. Never raises — bad feeds yield []."""
    try:
        calendar = Calendar.from_ical(payload)
    except Exception:  # noqa: BLE001 - third-party parser, any failure is "no events"
        logger.warning("Unparseable iCal feed for %s", slug)
        return []

    events: list[Event] = []
    for component in calendar.walk("VEVENT"):
        try:
            title = _component_str(component, "SUMMARY")
            starts_at = ensure_aware(getattr(component.get("DTSTART"), "dt", None))
            if not title or starts_at is None:
                continue
            ends_at = ensure_aware(getattr(component.get("DTEND"), "dt", None))
            location = clean_text(_component_str(component, "LOCATION"), limit=200)
            description = clean_text(_component_str(component, "DESCRIPTION"))
            url = _component_str(component, "URL")
            uid = _component_str(component, "UID") or f"{title}|{starts_at.isoformat()}"
            events.append(
                Event(
                    id=make_id("meetup", uid),
                    title=title,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    location=location,
                    url=url if url and url.startswith("http") else None,
                    source="meetup",
                    description=description,
                    city=guess_city(location, title, description) or "Other",
                    tags=["meetup", slug],
                    lang=guess_lang(title, description),
                )
            )
        except Exception:  # noqa: BLE001 - skip the bad row, keep the feed
            logger.warning("Skipping malformed VEVENT in %s", slug, exc_info=True)
    return events


class MeetupICalSource:
    """Fetches a handful of hardcoded Kansai Meetup groups."""

    name = "meetup"

    def __init__(self, slugs: list[str], timeout_s: float = 10.0) -> None:
        self.slugs = slugs
        self.timeout_s = timeout_s

    async def _fetch_one(self, client: httpx.AsyncClient, slug: str) -> list[Event]:
        try:
            response = await client.get(ICAL_URL.format(slug=slug))
            if response.status_code != 200:
                logger.info("Meetup feed %s returned HTTP %s", slug, response.status_code)
                return []
            return parse_ical(response.content, slug)
        except httpx.HTTPError:
            logger.warning("Meetup feed %s failed", slug, exc_info=True)
            return []

    async def fetch(self) -> list[Event]:
        if not self.slugs:
            return []
        headers = {"User-Agent": USER_AGENT, "Accept": "text/calendar,*/*"}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_s, headers=headers, follow_redirects=True
            ) as client:
                results = await asyncio.gather(
                    *(self._fetch_one(client, slug) for slug in self.slugs),
                    return_exceptions=True,
                )
        except Exception:  # noqa: BLE001 - adapter must fail soft
            logger.exception("Meetup source failed")
            return []

        events: list[Event] = []
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("Meetup group fetch failed: %s", result)
                continue
            events.extend(result)
        logger.info("Meetup source produced %d events", len(events))
        return events
