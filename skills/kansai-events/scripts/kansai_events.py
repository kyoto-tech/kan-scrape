#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28", "icalendar>=6"]
# ///
"""Scrape upcoming Kansai (Kyoto/Osaka/Kobe/Nara) events from Meetup, Doorkeeper, Connpass.

Single source of truth for Kan Scrape's event scraping: the backend (kan-scrape-back/app/sources)
loads this file and wraps it, so it must stay importable (no side effects at import) and
depend only on httpx and icalendar. Every source fails soft: a dead feed contributes 0 events
and a log line, never an exception.
"""

import argparse
import asyncio
import dataclasses
import datetime
import hashlib
import json
import logging
import os
import re
import sys
import zoneinfo
from collections import abc
from typing import Any, Protocol, TypeVar

import httpx
import icalendar

logger = logging.getLogger("kansai_events")

JST = zoneinfo.ZoneInfo("Asia/Tokyo")

# Live-verified public iCal feeds (HTTP 200 + VCALENDAR), busiest first.
DEFAULT_MEETUP_GROUPS = [
    "kyoto-tech-meetup",
    "local-kyoto-english-meetup",
    "osaka-web-designers-and-developers-meetup",
    "entrepreneurs_tech_ai-careers_venture_capital",
    "osaka-friends-english-japanese-language-exchange",
    "kyoto-language-interaction",
    "kansaihikes",
    "Hacker-News-Kansai",
    "osaka-coffee-and-tech-morning",
    "Kyoto-Language-Lovers",
]
MEETUP_ICAL_URL = "https://www.meetup.com/{slug}/events/ical/"
DOORKEEPER_URL = "https://api.doorkeeper.jp/events"
DOORKEEPER_PREFECTURES = {"kyoto": "Kyoto", "osaka": "Osaka", "hyogo": "Kobe"}
CONNPASS_URL = "https://connpass.com/api/v2/events/"
USER_AGENT = "Mozilla/5.0 (compatible; kan-scrape/0.1)"

CITY_HINTS = [
    ("Kyoto", ("kyoto", "京都", "kawaramachi", "gion", "arashiyama", "uji")),
    ("Osaka", ("osaka", "大阪", "umeda", "namba", "shinsaibashi", "tennoji", "sakai", "梅田")),
    ("Kobe", ("kobe", "神戸", "sannomiya", "三宮", "hyogo", "兵庫", "himeji")),
    ("Nara", ("nara", "奈良", "ikoma")),
    ("Online", ("online", "オンライン", "zoom", "remote")),
]
CITIES = [city for city, _ in CITY_HINTS] + ["Other"]
_JA = re.compile(r"[぀-ヿ一-鿿]")
_LATIN = re.compile(r"[A-Za-z]")
_WS = re.compile(r"\s+")


@dataclasses.dataclass
class Event:
    id: str
    title: str
    starts_at: datetime.datetime
    ends_at: datetime.datetime | None
    location: str | None
    url: str | None
    source: str
    description: str | None
    city: str
    tags: list[str]
    lang: str | None
    image_url: str | None = None

    def to_json(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["starts_at"] = self.starts_at.isoformat()
        data["ends_at"] = self.ends_at.isoformat() if self.ends_at else None
        return data


# --- helpers ---------------------------------------------------------------------------------


def now_jst() -> datetime.datetime:
    return datetime.datetime.now(tz=JST)


def make_id(source: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{source}:{hashlib.sha1(raw.encode()).hexdigest()[:12]}"


def ensure_aware(value: Any) -> datetime.datetime | None:
    """Normalise a date/datetime to a timezone-aware JST datetime; naive means JST."""
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=JST) if value.tzinfo is None else value.astimezone(JST)
    if isinstance(value, datetime.date):
        return datetime.datetime(value.year, value.month, value.day, tzinfo=JST)
    return None


def parse_iso(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return ensure_aware(datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def guess_city(*texts: str | None) -> str | None:
    blob = " ".join(t for t in texts if t).lower()
    for city, hints in CITY_HINTS:
        if blob and any(hint in blob for hint in hints):
            return city
    return None


def guess_lang(*texts: str | None) -> str | None:
    blob = " ".join(t for t in texts if t)
    has_ja = bool(_JA.search(blob))
    has_en = len(_LATIN.findall(blob)) > 8
    if has_ja and has_en:
        return "mixed"
    return "ja" if has_ja else "en" if has_en else None


def clean_text(value: str | None, limit: int = 600) -> str | None:
    if not value:
        return None
    text = _WS.sub(" ", re.sub(r"<[^>]+>", " ", value)).strip()
    return text[:limit] or None


def http_url(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith("http") else None


# --- sources ---------------------------------------------------------------------------------


def parse_meetup_ical(payload: str | bytes, slug: str = "meetup") -> list[Event]:
    """Parse a Meetup iCal feed. Never raises: a bad feed yields []."""
    try:
        calendar = icalendar.Calendar.from_ical(payload)
    except Exception:  # noqa: BLE001 - any parser failure means "no events"
        logger.warning("meetup %s: unparseable iCal feed", slug)
        return []
    # Meetup VEVENTs often lack LOCATION; the calendar name and slug are the fallback hints.
    group_name = str(calendar.get("X-WR-CALNAME") or calendar.get("NAME") or "")
    slug_hint = slug.replace("-", " ").replace("_", " ")
    events = []
    for comp in calendar.walk("VEVENT"):
        try:
            title = str(comp.get("SUMMARY") or "")
            starts_at = ensure_aware(getattr(comp.get("DTSTART"), "dt", None))
            if not title or starts_at is None:
                continue
            location = clean_text(str(comp.get("LOCATION") or ""), limit=200)
            description = clean_text(str(comp.get("DESCRIPTION") or ""))
            uid = str(comp.get("UID") or f"{title}|{starts_at.isoformat()}")
            events.append(
                Event(
                    id=make_id("meetup", uid),
                    title=title,
                    starts_at=starts_at,
                    ends_at=ensure_aware(getattr(comp.get("DTEND"), "dt", None)),
                    location=location,
                    url=http_url(str(comp.get("URL") or "")),
                    source="meetup",
                    description=description,
                    city=guess_city(location, title, description)
                    or guess_city(group_name, slug_hint)
                    or "Other",
                    tags=["meetup", slug],
                    lang=guess_lang(title, description),
                )
            )
        except Exception as exc:  # noqa: BLE001 - skip the bad row, keep the feed
            logger.warning("meetup %s: skipping malformed VEVENT (%s)", slug, exc)
    return events


async def fetch_meetup(client: httpx.AsyncClient, slugs: list[str]) -> list[Event]:
    async def one(slug: str) -> list[Event]:
        try:
            resp = await client.get(
                MEETUP_ICAL_URL.format(slug=slug),
                headers={"User-Agent": USER_AGENT, "Accept": "text/calendar,*/*"},
            )
        except httpx.HTTPError as exc:
            logger.warning("meetup %s: %s", slug, type(exc).__name__)
            return []
        if resp.status_code != 200:
            logger.info("meetup %s: HTTP %s", slug, resp.status_code)
            return []
        return parse_meetup_ical(resp.content, slug)

    results = await asyncio.gather(*(one(slug) for slug in slugs))
    return [event for batch in results for event in batch]


def parse_doorkeeper(payload: Any, prefecture: str | None = None) -> list[Event]:
    """Parse a Doorkeeper `[{"event": {...}}, ...]` payload. Never raises."""
    if not isinstance(payload, list):
        logger.warning("doorkeeper: unexpected payload type %s", type(payload).__name__)
        return []
    events = []
    for entry in payload:
        try:
            raw = entry.get("event") if isinstance(entry, dict) else None
            if not isinstance(raw, dict):
                continue
            title = raw.get("title")
            starts_at = parse_iso(raw.get("starts_at"))
            if not title or starts_at is None:
                continue
            location = raw.get("venue_name") or raw.get("address")
            description = clean_text(raw.get("description"))
            events.append(
                Event(
                    id=make_id("doorkeeper", raw.get("id") or f"{title}|{starts_at.isoformat()}"),
                    title=title,
                    starts_at=starts_at,
                    ends_at=parse_iso(raw.get("ends_at")),
                    location=clean_text(location, limit=200),
                    url=http_url(raw.get("public_url")),
                    source="doorkeeper",
                    description=description,
                    city=guess_city(location, raw.get("address"), title)
                    or DOORKEEPER_PREFECTURES.get(prefecture or "", "Other"),
                    tags=["doorkeeper"] + ([prefecture] if prefecture else []),
                    lang=guess_lang(title, description),
                )
            )
        except Exception as exc:  # noqa: BLE001 - skip the bad row, keep the feed
            logger.warning("doorkeeper: skipping malformed event (%s)", exc)
    return events


async def fetch_doorkeeper(client: httpx.AsyncClient, token: str) -> list[Event]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def one(prefecture: str) -> list[Event]:
        params = {
            "prefecture": prefecture,
            "since": now_jst().date().isoformat(),
            "sort": "starts_at",
            "locale": "en",
        }
        try:
            resp = await client.get(DOORKEEPER_URL, params=params, headers=headers)
            if resp.status_code != 200:
                logger.info("doorkeeper %s: HTTP %s", prefecture, resp.status_code)
                return []
            return parse_doorkeeper(resp.json(), prefecture)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("doorkeeper %s: %s", prefecture, type(exc).__name__)
            return []

    results = await asyncio.gather(*(one(p) for p in DOORKEEPER_PREFECTURES))
    return [event for batch in results for event in batch]


def parse_connpass(payload: Any) -> list[Event]:
    """Parse a Connpass v2 `{"events": [...]}` payload. Never raises."""
    if not isinstance(payload, dict):
        logger.warning("connpass: unexpected payload type %s", type(payload).__name__)
        return []
    events = []
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
            url = http_url(raw.get("event_url") or raw.get("url"))
            events.append(
                Event(
                    id=make_id("connpass", raw.get("id") or raw.get("event_id") or url or title),
                    title=title,
                    starts_at=starts_at,
                    ends_at=parse_iso(raw.get("ended_at")),
                    location=clean_text(location, limit=200),
                    url=url,
                    source="connpass",
                    description=description,
                    city=guess_city(location, raw.get("address"), title) or "Other",
                    tags=["connpass", "tech"],
                    lang=guess_lang(title, description),
                    image_url=http_url(raw.get("image_url")),
                )
            )
        except Exception as exc:  # noqa: BLE001 - skip the bad row, keep the feed
            logger.warning("connpass: skipping malformed event (%s)", exc)
    return events


async def fetch_connpass(client: httpx.AsyncClient, api_key: str) -> list[Event]:
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    params = {"prefecture": "kyoto,osaka,hyogo", "count": 100, "order": 2}
    try:
        resp = await client.get(CONNPASS_URL, params=params, headers=headers)
        if resp.status_code != 200:
            logger.info("connpass: HTTP %s", resp.status_code)
            return []
        return parse_connpass(resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("connpass: %s", type(exc).__name__)
        return []


# --- pipeline --------------------------------------------------------------------------------


async def scrape(args: argparse.Namespace) -> tuple[list[Event], dict[str, int]]:
    jobs: dict[str, Any] = {}
    doorkeeper_token = os.environ.get("DOORKEEPER_TOKEN")
    connpass_key = os.environ.get("CONNPASS_API_KEY")
    async with httpx.AsyncClient(timeout=args.timeout, follow_redirects=True) as client:
        if "meetup" in args.sources:
            jobs["meetup"] = fetch_meetup(client, args.groups)
        if "doorkeeper" in args.sources:
            if doorkeeper_token:
                jobs["doorkeeper"] = fetch_doorkeeper(client, doorkeeper_token)
            else:
                logger.info("doorkeeper: skipped (no DOORKEEPER_TOKEN)")
        if "connpass" in args.sources:
            if connpass_key:
                jobs["connpass"] = fetch_connpass(client, connpass_key)
            else:
                logger.info("connpass: skipped (no CONNPASS_API_KEY)")
        results = await asyncio.gather(*jobs.values())
    per_source = {name: len(batch) for name, batch in zip(jobs, results, strict=True)}
    return [event for batch in results for event in batch], per_source


class Dated(Protocol):
    """Anything with a title and a start: this script's Event or the backend's pydantic one."""

    title: str
    starts_at: datetime.datetime


E = TypeVar("E", bound=Dated)


def normalise_title(title: str) -> str:
    return _WS.sub(" ", title).strip().casefold()


def upcoming(events: abc.Iterable[E], *, horizon_days: int | None = None) -> list[E]:
    """Keep only events that have not started yet, sorted by start time."""
    now = now_jst()
    limit = now + datetime.timedelta(days=horizon_days) if horizon_days is not None else None
    kept = [e for e in events if e.starts_at >= now and (limit is None or e.starts_at <= limit)]
    kept.sort(key=lambda e: e.starts_at)
    return kept


def dedupe(events: abc.Iterable[E]) -> list[E]:
    """Drop duplicates sharing a normalised title and JST start date.

    The *first* occurrence wins, so filter and sort before deduping, otherwise a finished copy
    of an event can shadow the upcoming one that shares its title and day.
    """
    seen: set[tuple[str, datetime.date]] = set()
    unique = []
    for event in events:
        key = (normalise_title(event.title), event.starts_at.astimezone(JST).date())
        if key not in seen:
            seen.add(key)
            unique.append(event)
    return unique


def select(events: list[Event], args: argparse.Namespace) -> list[Event]:
    unique = dedupe(upcoming(events, horizon_days=args.days))
    if args.city:
        wanted = {c.casefold() for c in args.city}
        unique = [e for e in unique if e.city.casefold() in wanted]
    if args.grep:
        pattern = re.compile("|".join(re.escape(term) for term in args.grep), re.IGNORECASE)
        unique = [
            e
            for e in unique
            if pattern.search(" ".join(filter(None, [e.title, e.description, e.location])))
        ]
    return unique[: args.limit] if args.limit else unique


def to_markdown(events: list[Event]) -> str:
    lines = []
    for e in events:
        when = e.starts_at.strftime("%a %Y-%m-%d %H:%M")
        if e.ends_at:
            when += e.ends_at.strftime("–%H:%M")
        lines.append(f"- **{e.title}** — {when} JST · {e.city} · {e.source}")
        if e.location:
            lines.append(f"  - {e.location}")
        if e.url:
            lines.append(f"  - {e.url}")
    return "\n".join(lines) or "(no events)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", nargs="+", choices=CITIES, help="keep only these cities")
    parser.add_argument("--days", type=int, help="only events starting within N days")
    parser.add_argument("--grep", nargs="+", help="keep events matching ANY term (title/desc/loc)")
    parser.add_argument("--limit", type=int, help="max events after filtering")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["meetup", "doorkeeper", "connpass"],
        choices=["meetup", "doorkeeper", "connpass"],
    )
    parser.add_argument(
        "--groups",
        nargs="+",
        default=DEFAULT_MEETUP_GROUPS,
        help="Meetup group URL slugs (default: built-in Kansai list)",
    )
    parser.add_argument("--format", choices=["json", "md"], default="json")
    parser.add_argument("--timeout", type=float, default=10.0, help="per-request seconds")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logger.setLevel(logging.INFO)
    # Windows consoles/pipes default to cp1252, which cannot encode Japanese titles.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    events, per_source = asyncio.run(scrape(args))
    selected = select(events, args)
    logger.info("fetched %s; %d upcoming after filters", per_source, len(selected))
    if args.format == "md":
        print(to_markdown(selected))
    else:
        print(json.dumps([e.to_json() for e in selected], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
