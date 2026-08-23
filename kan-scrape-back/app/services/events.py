"""In-memory event registry: runs every source adapter and caches the result."""

import asyncio
import logging
import random

from app.core import config
from app.schemas import event as event_schema
from app.sources import base, connpass, doorkeeper, meetup_ical
from app.sources import seed as seed_source

logger = logging.getLogger(__name__)


def build_remote_sources(settings: config.Settings) -> list[base.Source]:
    """Every network-backed adapter. Disabled ones still report a 0 count."""
    return [
        meetup_ical.MeetupICalSource(settings.meetup_groups, timeout_s=settings.http_timeout_s),
        doorkeeper.DoorkeeperSource(settings.doorkeeper_token, timeout_s=settings.http_timeout_s),
        connpass.ConnpassSource(settings.connpass_api_key, timeout_s=settings.http_timeout_s),
    ]


class EventStore:
    """Process-wide event cache.

    The seed source loads synchronously (no network, dev/debug only by default); remote
    adapters are refreshed in the background so startup never blocks on the network.
    """

    def __init__(
        self,
        seed: seed_source.SeedSource | None = None,
        remote_sources: list[base.Source] | None = None,
        *,
        include_seed: bool = True,
    ) -> None:
        self._seed = seed if seed is not None else seed_source.SeedSource()
        self._include_seed = include_seed
        self._remote_sources = remote_sources if remote_sources is not None else []
        self._seed_events: list[event_schema.Event] = []
        self._remote_events: list[event_schema.Event] = []
        self._per_source: dict[str, int] = {}
        self._lock = asyncio.Lock()

    # --- loading -------------------------------------------------------------

    def set_seed_events(self, events: list[event_schema.Event]) -> None:
        """Replace the always-on event set. Handy for tests and manual seeding."""
        self._seed_events = list(events)
        self._per_source["seed"] = len(self._seed_events)

    def load_seed(self) -> int:
        """Synchronous, offline seed load. Safe to call during app startup.

        A no-op (0 events) when the store was built with ``include_seed=False`` —
        outside dev the fixture events must not mix with the scraped ones.
        """
        if not self._include_seed:
            self._seed_events = []
            self._per_source[self._seed.name] = 0
            return 0
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
            collected: list[event_schema.Event] = []
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

    def all(self, *, city: str | None = None, limit: int | None = None) -> list[event_schema.Event]:
        """Deduped, future-only, sorted by start time. Never raises — the demo must not 500.

        Filter first, dedupe second: `dedupe` keeps the first match, so running it on the raw
        list lets a past event shadow the upcoming one it shares a title and day with.
        """
        try:
            events = base.dedupe(base.upcoming([*self._seed_events, *self._remote_events]))
        except Exception:  # noqa: BLE001 - a poisoned cache entry must not take the API down
            logger.exception("Event cache is unreadable — serving no events")
            return []
        if city:
            wanted = city.strip().casefold()
            events = [item for item in events if item.city and item.city.casefold() == wanted]
        if limit is not None and limit >= 0:
            events = events[:limit]
        return events

    def count(self) -> int:
        return len(self.all())

    def random_event(self, *, city: event_schema.City | None = None) -> event_schema.Event | None:
        events = self.all(city=city)
        if not events:
            return None
        return random.choice(events)


def build_store(settings: config.Settings, *, with_remote: bool = True) -> EventStore:
    remote = build_remote_sources(settings) if with_remote else []
    return EventStore(seed_source.SeedSource(), remote, include_seed=settings.seed_enabled)
