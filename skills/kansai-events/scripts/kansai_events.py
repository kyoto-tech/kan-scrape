#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28", "icalendar>=6"]
# ///
"""Scrape upcoming Kansai (Kyoto/Osaka/Kobe/Nara) events from Meetup, Doorkeeper, Connpass.

Standalone port of kan-scrape-back/app/sources (plus the default Meetup groups from
app/core/config.py) so the scraper runs without the app. Keep the two in sync when a source
changes. Every source fails soft: a dead feed contributes 0 events and a line on stderr, never
an exception.
"""

import argparse
import asyncio
import dataclasses
import datetime
import hashlib
import json
import os
import re
import sys
import zoneinfo
from typing import Any

import httpx
import icalendar

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


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


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


def parse_meetup_ical(payload: bytes, slug: str) -> list[Event]:
    try:
        calendar = icalendar.Calendar.from_ical(payload)
    except Exception:  # noqa: BLE001 - any parser failure means "no events"
        log(f"meetup {slug}: unparseable iCal feed")
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
            log(f"meetup {slug}: skipping malformed VEVENT ({exc})")
    return events


async def fetch_meetup(client: httpx.AsyncClient, slugs: list[str]) -> list[Event]:
    async def one(slug: str) -> list[Event]:
        try:
            resp = await client.get(
                MEETUP_ICAL_URL.format(slug=slug),
                headers={"User-Agent": USER_AGENT, "Accept": "text/calendar,*/*"},
            )
        except httpx.HTTPError as exc:
            log(f"meetup {slug}: {type(exc).__name__}")
            return []
        if resp.status_code != 200:
            log(f"meetup {slug}: HTTP {resp.status_code}")
            return []
        return parse_meetup_ical(resp.content, slug)

    results = await asyncio.gather(*(one(slug) for slug in slugs))
    return [event for batch in results for event in batch]


def parse_doorkeeper(payload: Any, prefecture: str) -> list[Event]:
    events = []
    for entry in payload if isinstance(payload, list) else []:
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
                or DOORKEEPER_PREFECTURES[prefecture],
                tags=["doorkeeper", prefecture],
                lang=guess_lang(title, description),
            )
        )
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
                log(f"doorkeeper {prefecture}: HTTP {resp.status_code}")
                return []
            return parse_doorkeeper(resp.json(), prefecture)
        except (httpx.HTTPError, ValueError) as exc:
            log(f"doorkeeper {prefecture}: {type(exc).__name__}")
            return []

    results = await asyncio.gather(*(one(p) for p in DOORKEEPER_PREFECTURES))
    return [event for batch in results for event in batch]


def parse_connpass(payload: Any) -> list[Event]:
    events = []
    for raw in payload.get("events") or [] if isinstance(payload, dict) else []:
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
    return events


async def fetch_connpass(client: httpx.AsyncClient, api_key: str) -> list[Event]:
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    params = {"prefecture": "kyoto,osaka,hyogo", "count": 100, "order": 2}
    try:
        resp = await client.get(CONNPASS_URL, params=params, headers=headers)
        if resp.status_code != 200:
            log(f"connpass: HTTP {resp.status_code}")
            return []
        return parse_connpass(resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        log(f"connpass: {type(exc).__name__}")
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
                log("doorkeeper: skipped (no DOORKEEPER_TOKEN)")
        if "connpass" in args.sources:
            if connpass_key:
                jobs["connpass"] = fetch_connpass(client, connpass_key)
            else:
                log("connpass: skipped (no CONNPASS_API_KEY)")
        results = await asyncio.gather(*jobs.values())
    per_source = {name: len(batch) for name, batch in zip(jobs, results, strict=True)}
    return [event for batch in results for event in batch], per_source


def select(events: list[Event], args: argparse.Namespace) -> list[Event]:
    """Filter to upcoming, sort, THEN dedupe: first occurrence wins, so a finished copy of an
    event must not be allowed to shadow the upcoming one sharing its title and day."""
    now = now_jst()
    horizon = now + datetime.timedelta(days=args.days) if args.days is not None else None
    kept = sorted(
        (e for e in events if e.starts_at >= now and (horizon is None or e.starts_at <= horizon)),
        key=lambda e: e.starts_at,
    )
    seen: set[tuple[str, datetime.date]] = set()
    unique = []
    for event in kept:
        key = (_WS.sub(" ", event.title).strip().casefold(), event.starts_at.date())
        if key not in seen:
            seen.add(key)
            unique.append(event)
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
    # Windows consoles/pipes default to cp1252, which cannot encode Japanese titles.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    events, per_source = asyncio.run(scrape(args))
    selected = select(events, args)
    log(f"fetched {per_source}; {len(selected)} upcoming after filters")
    if args.format == "md":
        print(to_markdown(selected))
    else:
        print(json.dumps([e.to_json() for e in selected], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
