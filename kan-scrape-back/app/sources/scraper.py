"""Loads the event scraper shipped with the `kansai-events` agent skill.

`skills/kansai-events/scripts/kansai_events.py` is the single source of truth for fetching and
parsing Meetup, Doorkeeper and Connpass. The skill runs it standalone; the adapters in this
package wrap it and convert its dataclass events into `event_schema.Event`.
"""

import dataclasses
import importlib.util
import logging
import pathlib
import sys
from collections import abc
from types import ModuleType
from typing import TYPE_CHECKING

import pydantic

from app.schemas import event as event_schema

logger = logging.getLogger(__name__)

SCRIPT_PATH = (
    pathlib.Path(__file__).resolve().parents[3]
    / "skills"
    / "kansai-events"
    / "scripts"
    / "kansai_events.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("kansai_events", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load the kansai-events scraper from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: dataclasses resolve their module through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if TYPE_CHECKING:
    # Type checkers read the script directly (mypy_path in pyproject.toml).
    import kansai_events
else:
    kansai_events = _load()


def to_events(items: abc.Iterable["kansai_events.Event"]) -> list[event_schema.Event]:
    """Convert scraper events to API events, dropping (not raising on) any that fail validation."""
    events: list[event_schema.Event] = []
    for item in items:
        try:
            events.append(event_schema.Event(**dataclasses.asdict(item)))
        except pydantic.ValidationError:
            logger.warning("Skipping scraped event that failed validation", exc_info=True)
    return events
