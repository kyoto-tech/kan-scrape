"""Shared plumbing for event source adapters.

The helpers come from the skill's scraper (see `scraper.py`), so the app and the skill
normalise, dedupe and filter events identically.
"""

from typing import Protocol, runtime_checkable

from app.schemas import event as event_schema
from app.sources import scraper

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

JST = event_schema.JST

_ke = scraper.kansai_events
clean_text = _ke.clean_text
dedupe = _ke.dedupe
ensure_aware = _ke.ensure_aware
guess_city = _ke.guess_city
guess_lang = _ke.guess_lang
make_id = _ke.make_id
normalise_title = _ke.normalise_title
now_jst = _ke.now_jst
parse_iso = _ke.parse_iso
upcoming = _ke.upcoming


@runtime_checkable
class Source(Protocol):
    """Every adapter fetches a list of events and never raises."""

    name: str

    async def fetch(self) -> list[event_schema.Event]: ...
