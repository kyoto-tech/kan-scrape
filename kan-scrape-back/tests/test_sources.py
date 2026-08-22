"""Adapter parsing tests — pure string/JSON fixtures, no network."""

from datetime import timedelta

from app.sources import connpass, doorkeeper
from app.sources.base import dedupe, guess_city, guess_lang, make_id, now_jst, upcoming
from app.sources.meetup_ical import parse_ical
from app.sources.seed import SeedSource

ICAL_FIXTURE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Meetup//EN
BEGIN:VEVENT
DTSTAMP:20260801T090000Z
DTSTART;TZID=Asia/Tokyo:20260905T190000
DTEND;TZID=Asia/Tokyo:20260905T210000
SUMMARY:Kyoto Tech Meetup #42
DESCRIPTION:<p>Talks about Python and Go</p>
LOCATION:Kyoto Research Park\\, Kyoto
URL:https://www.meetup.com/kyoto-tech-meetup/events/1/
UID:event-1@meetup.com
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Asia/Tokyo:20260906T100000
SUMMARY:Osaka Castle Walk
LOCATION:Osaka Castle Park
UID:event-2@meetup.com
END:VEVENT
BEGIN:VEVENT
SUMMARY:Broken event without a start
UID:event-3@meetup.com
END:VEVENT
END:VCALENDAR
"""

DOORKEEPER_FIXTURE = [
    {
        "event": {
            "id": 12345,
            "title": "Kyoto Rust Meetup",
            "starts_at": "2026-09-10T19:00:00.000+09:00",
            "ends_at": "2026-09-10T21:00:00.000+09:00",
            "venue_name": "Kyoto Research Park",
            "address": "Kyoto, Shimogyo-ku",
            "description": "<p>Rust talks</p>",
            "public_url": "https://kyoto.doorkeeper.jp/events/12345",
        }
    },
    {"event": {"title": "No start time"}},
    {"not_an_event": {}},
]

CONNPASS_FIXTURE = {
    "results_available": 2,
    "results_returned": 2,
    "events": [
        {
            "id": 777,
            "title": "大阪もくもく会",
            "catch": "もくもく作業しましょう",
            "started_at": "2026-09-12T13:00:00+09:00",
            "ended_at": "2026-09-12T17:00:00+09:00",
            "place": "Umeda, Osaka",
            "address": "大阪府大阪市北区",
            "event_url": "https://connpass.com/event/777/",
            "image_url": "https://connpass.com/image/777.png",
        },
        {"title": "no date"},
    ],
}


def test_parse_ical() -> None:
    events = parse_ical(ICAL_FIXTURE, "kyoto-tech-meetup")
    assert len(events) == 2
    first = events[0]
    assert first.title == "Kyoto Tech Meetup #42"
    assert first.starts_at.isoformat().startswith("2026-09-05T19:00")
    assert first.ends_at is not None
    assert first.city == "Kyoto"
    assert first.source == "meetup"
    assert first.id.startswith("meetup:")
    assert "<p>" not in (first.description or "")
    assert events[1].city == "Osaka"


REAL_ICAL_FIXTURE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Meetup//Meetup Calendar 1.0//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
NAME:OKTech - Tackle tech together in Kansai
X-WR-CALNAME:OKTech - Tackle tech together in Kansai
BEGIN:VTIMEZONE
TZID:Asia/Tokyo
X-LIC-LOCATION:Asia/Tokyo
BEGIN:STANDARD
TZOFFSETFROM:+0900
TZOFFSETTO:+0900
TZNAME:JST
DTSTART:19700101T000000
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:event_314843745@meetup.com
SEQUENCE:1
DTSTAMP:20260822T054327Z
DTSTART;TZID=Asia/Tokyo:20260829T170000
DTEND;TZID=Asia/Tokyo:20260829T200000
SUMMARY:Git Workshop Day
DESCRIPTION:OKTech - Tackle tech together in Kansai\\nGrab your laptop and 
 join us to level up your skills!\\n\\nGit is the backbone of modern software
  development\\, yet many people still only scratch the surface.
URL;VALUE=URI:https://www.meetup.com/oktech/events/314843745/
STATUS:CONFIRMED
CLASS:PUBLIC
END:VEVENT
END:VCALENDAR
"""


def test_parse_ical_real_meetup_feed() -> None:
    """Shape of a live Meetup feed: TZID start, no LOCATION, folded/escaped description,
    `URL;VALUE=URI` whose urlname differs from the feed slug, `event_<id>@meetup.com` uid."""
    events = parse_ical(REAL_ICAL_FIXTURE, "osaka-web-designers-and-developers-meetup")
    assert len(events) == 1
    event = events[0]
    assert event.title == "Git Workshop Day"
    assert event.starts_at.isoformat() == "2026-08-29T17:00:00+09:00"
    assert event.ends_at is not None
    assert event.location is None
    # City falls back to the calendar name / feed slug when the event carries no location.
    assert event.city == "Osaka"
    assert str(event.url) == "https://www.meetup.com/oktech/events/314843745/"
    assert event.id == make_id("meetup", "event_314843745@meetup.com")
    description = event.description or ""
    assert "\\n" not in description and "\\," not in description
    assert "Grab your laptop and join us" in description
    assert "many people still only scratch the surface" in description


def test_parse_ical_garbage_returns_empty() -> None:
    assert parse_ical("not a calendar at all") == []


def test_parse_doorkeeper() -> None:
    events = doorkeeper.parse_events(DOORKEEPER_FIXTURE, "kyoto")
    assert len(events) == 1
    event = events[0]
    assert event.title == "Kyoto Rust Meetup"
    assert event.source == "doorkeeper"
    assert event.city == "Kyoto"
    assert event.location == "Kyoto Research Park"
    assert str(event.url).startswith("https://kyoto.doorkeeper.jp/")
    assert "kyoto" in event.tags


def test_parse_doorkeeper_bad_payload() -> None:
    assert doorkeeper.parse_events({"unexpected": True}) == []


def test_parse_connpass() -> None:
    events = connpass.parse_events(CONNPASS_FIXTURE)
    assert len(events) == 1
    event = events[0]
    assert event.title == "大阪もくもく会"
    assert event.city == "Osaka"
    assert event.lang == "ja"
    assert event.source == "connpass"
    assert str(event.image_url).endswith("777.png")


def test_parse_connpass_bad_payload() -> None:
    assert connpass.parse_events([1, 2, 3]) == []


async def test_disabled_remote_adapters_return_empty() -> None:
    assert await doorkeeper.DoorkeeperSource(None).fetch() == []
    assert await connpass.ConnpassSource(None).fetch() == []


def test_seed_source_is_relative_to_now() -> None:
    events = SeedSource().load()
    assert len(events) >= 15
    now = now_jst()
    assert all(event.starts_at > now for event in events)
    assert all(event.starts_at < now + timedelta(days=40) for event in events)
    assert len({event.id for event in events}) == len(events)
    assert {event.city for event in events} >= {"Kyoto", "Osaka", "Kobe"}


def test_helpers() -> None:
    assert guess_city("Sannomiya, Kobe") == "Kobe"
    assert guess_city("") is None
    assert guess_lang("完全に日本語のイベント") == "ja"
    assert guess_lang("A fully English event description here") == "en"
    events = SeedSource().load()
    assert dedupe(events + events) == events
    assert upcoming(events, horizon_days=3) == [
        e for e in events if e.starts_at <= now_jst() + timedelta(days=3)
    ]


async def test_meetup_source_without_slugs() -> None:
    from app.sources.meetup_ical import MeetupICalSource

    assert await MeetupICalSource([]).fetch() == []


def test_malformed_urls_do_not_drop_the_event() -> None:
    """A junk image_url costs the field, not the whole event."""
    payload = {
        "events": [
            {
                "id": 42,
                "title": "Osaka Go Night",
                "started_at": "2999-01-01T19:00:00+09:00",
                "image_url": "not a url",
                "event_url": "https://connpass.com/event/42/",
            }
        ]
    }
    events = connpass.parse_events(payload)
    assert len(events) == 1
    assert events[0].image_url is None
    assert str(events[0].url) == "https://connpass.com/event/42/"


def test_upcoming_with_zero_horizon_keeps_nothing_later() -> None:
    """`horizon_days=0` means "nothing after now", not "no horizon at all"."""
    from app.schemas.event import Event

    later = Event(id="a:1", title="Later", starts_at=now_jst() + timedelta(days=1), source="a")
    assert upcoming([later], horizon_days=0) == []
    assert upcoming([later]) == [later]
