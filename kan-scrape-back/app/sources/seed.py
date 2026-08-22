"""Seed fixture source — always on, zero network, guarantees the demo works."""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from app.schemas.event import Event
from app.sources.base import JST, make_id, now_jst

logger = logging.getLogger(__name__)

SEED_PATH = Path(__file__).with_name("seed_events.json")


def _parse_time(value: str) -> time:
    hour, _, minute = value.partition(":")
    return time(int(hour), int(minute or 0))


def _to_event(raw: dict[str, Any], reference: datetime) -> Event | None:
    try:
        day = (reference + timedelta(days=int(raw["day_offset"]))).date()
        starts_at = datetime.combine(day, _parse_time(raw.get("start_time", "19:00")), tzinfo=JST)
        duration = int(raw.get("duration_min", 120))
        return Event(
            id=make_id("seed", raw["slug"]),
            title=raw["title"],
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=duration),
            location=raw.get("location"),
            url=raw.get("url"),
            source="seed",
            description=raw.get("description"),
            city=raw.get("city"),
            tags=list(raw.get("tags", [])),
            lang=raw.get("lang"),
            price=raw.get("price"),
            image_url=raw.get("image_url"),
        )
    except Exception:  # noqa: BLE001 - fail soft, one bad row must not kill the seed
        logger.exception("Skipping malformed seed event %r", raw.get("slug"))
        return None


class SeedSource:
    """Loads `seed_events.json`, materialising dates relative to *now*."""

    name = "seed"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SEED_PATH

    def load(self) -> list[Event]:
        """Synchronous load — safe to call during startup, never touches the network."""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Could not read seed events from %s", self.path)
            return []
        reference = now_jst()
        events = [
            event
            for raw in payload.get("events", [])
            if (event := _to_event(raw, reference)) is not None
        ]
        logger.info("Seed source loaded %d events", len(events))
        return events

    async def fetch(self) -> list[Event]:
        return self.load()
