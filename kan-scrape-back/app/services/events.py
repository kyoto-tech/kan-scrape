"""In-memory event registry: runs every source adapter and caches the result."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from app.schemas.event import City, Event
from app.sources.base import Source, dedupe, upcoming
from app.sources.connpass import ConnpassSource
from app.sources.doorkeeper import DoorkeeperSource
from app.sources.meetup_ical import MeetupICalSource
from app.sources.seed import SeedSource

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.core.config import Settings

logger = logging.getLogger(__name__)


def build_remote_sources(settings: Settings) -> list[Source]:
    """Every network-backed adapter. Disabled ones still report a 0 count."""
    return [
        MeetupICalSource(settings.meetup_groups, timeout_s=settings.http_timeout_s),
        DoorkeeperSource(settings.doorkeeper_token, timeout_s=settings.http_timeout_s),
        ConnpassSource(settings.connpass_api_key, timeout_s=settings.http_timeout_s),
    ]


class EventStore:
    """Process-wide event cache.

    The seed source loads synchronously (no network, always available); remote adapters are
    refreshed in the background so startup never blocks on the network.
    """

    def __init__(
        self,
        seed: SeedSource | None = None,
        remote_sources: list[Source] | None = None,
    ) -> None:
        self._seed = seed if seed is not None else SeedSource()
        self._remote_sources = remote_sources if remote_sources is not None else []
        self._seed_events: list[Event] = []
        self._remote_events: list[Event] = []
        self._per_source: dict[str, int] = {}
        self._lock = asyncio.Lock()

    # --- loading -------------------------------------------------------------

    def set_seed_events(self, events: list[Event]) -> None:
        """Replace the always-on event set. Handy for tests and manual seeding."""
        self._seed_events = list(events)
        self._per_source["seed"] = len(self._seed_events)

    def load_seed(self) -> int:
        """Synchronous, offline seed load. Safe to call during app startup."""
        self._seed_events = self._seed.load()
        self._per_source[self._seed.name] = len(self._seed_events)
        return len(self._seed_events)

    async def refresh(self) -> dict[str, int]:
        """Re-run every adapter concurrently. Fails soft: a broken adapter contributes 0."""
        async with self._lock:
            self.load_seed()
            if not self._remote_sources:
                return self.per_source
            results = await asyncio.gather(
                *(source.fetch() for source in self._remote_sources),
                return_exceptions=True,
            )
            collected: list[Event] = []
            for source, result in zip(self._remote_sources, results, strict=True):
                if isinstance(result, BaseException):
                    logger.warning("Source %s failed: %s", source.name, result)
                    self._per_source[source.name] = 0
                    continue
                self._per_source[source.name] = len(result)
                collected.extend(result)
            self._remote_events = collected
            logger.info("Refreshed events: %s", self._per_source)
            return self.per_source

    # --- reading -------------------------------------------------------------

    @property
    def per_source(self) -> dict[str, int]:
        return dict(self._per_source)

    def all(self, *, city: str | None = None, limit: int | None = None) -> list[Event]:
        """Deduped, future-only, sorted by start time."""
        events = upcoming(dedupe([*self._seed_events, *self._remote_events]))
        if city:
            wanted = city.strip().casefold()
            events = [e for e in events if e.city and e.city.casefold() == wanted]
        if limit is not None and limit >= 0:
            events = events[:limit]
        return events

    def count(self) -> int:
        return len(self.all())

    def random_event(self, *, city: City | None = None) -> Event | None:
        events = self.all(city=city)
        if not events:
            return None
        return random.choice(events)


def build_store(settings: Settings, *, with_remote: bool = True) -> EventStore:
    remote = build_remote_sources(settings) if with_remote else []
    return EventStore(SeedSource(), remote)
