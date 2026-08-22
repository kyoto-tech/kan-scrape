"""Shared plumbing for event source adapters."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Protocol, runtime_checkable

from app.schemas.event import JST, City, Event, Lang

logger = logging.getLogger(__name__)

__all__ = [
    "JST",
    "Source",
    "clean_text",
    "dedupe",
    "ensure_aware",
    "guess_city",
    "guess_lang",
    "make_id",
    "normalise_title",
    "now_jst",
    "parse_iso",
    "upcoming",
]

_CITY_HINTS: list[tuple[City, tuple[str, ...]]] = [
    ("Kyoto", ("kyoto", "京都", "kawaramachi", "gion", "arashiyama", "uji")),
    ("Osaka", ("osaka", "大阪", "umeda", "namba", "shinsaibashi", "tennoji", "sakai", "梅田")),
    ("Kobe", ("kobe", "神戸", "sannomiya", "三宮", "hyogo", "兵庫", "himeji")),
    ("Nara", ("nara", "奈良", "ikoma")),
    ("Online", ("online", "オンライン", "zoom", "remote")),
]

_JA_CHARS = re.compile(r"[぀-ヿ一-鿿]")
_LATIN_CHARS = re.compile(r"[A-Za-z]")
_WS = re.compile(r"\s+")


@runtime_checkable
class Source(Protocol):
    """Every adapter fetches a list of events and never raises."""

    name: str

    async def fetch(self) -> list[Event]: ...


def now_jst() -> datetime:
    return datetime.now(tz=JST)


def make_id(source: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{source}:{digest}"


def ensure_aware(value: datetime | date | None) -> datetime | None:
    """Normalise a date/datetime to a timezone-aware JST datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=JST)
        return value.astimezone(JST)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=JST)
    return None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return ensure_aware(datetime.fromisoformat(text))
    except ValueError:
        logger.debug("Could not parse datetime %r", value)
        return None


def guess_city(*texts: str | None) -> City | None:
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    for city, hints in _CITY_HINTS:
        if any(hint in blob for hint in hints):
            return city
    return None


def guess_lang(*texts: str | None) -> Lang | None:
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    has_ja = bool(_JA_CHARS.search(blob))
    has_en = len(_LATIN_CHARS.findall(blob)) > 8
    if has_ja and has_en:
        return "mixed"
    if has_ja:
        return "ja"
    if has_en:
        return "en"
    return None


def clean_text(value: str | None, limit: int = 600) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = _WS.sub(" ", text).strip()
    if not text:
        return None
    return text[:limit]


def normalise_title(title: str) -> str:
    return _WS.sub(" ", title).strip().casefold()


def dedupe(events: Iterable[Event]) -> list[Event]:
    """Drop duplicates sharing a normalised title and start date.

    The *first* occurrence wins, so filter and sort before deduping — otherwise a finished
    copy of an event can shadow the upcoming one that shares its title and day.
    """
    seen: set[tuple[str, date]] = set()
    unique: list[Event] = []
    for event in events:
        key = (normalise_title(event.title), event.starts_at.astimezone(JST).date())
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def upcoming(events: Iterable[Event], *, horizon_days: int | None = None) -> list[Event]:
    """Keep only events that have not started yet, sorted by start time."""
    now = now_jst()
    limit = now + timedelta(days=horizon_days) if horizon_days is not None else None
    kept = [
        event
        for event in events
        if event.starts_at.astimezone(JST) >= now
        and (limit is None or event.starts_at.astimezone(JST) <= limit)
    ]
    kept.sort(key=lambda event: event.starts_at.astimezone(JST))
    return kept
