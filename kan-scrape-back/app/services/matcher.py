"""Match a spoken/typed wish against cached events with Mistral function calling."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

from app.schemas.event import Event, MatchResponse
from app.sources.base import JST

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.core.config import Settings

logger = logging.getLogger(__name__)

MIN_QUERY_CHARS = 3
TOOL_NAME = "pick_events"

PICK_EVENTS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Pick the best matching events and produce a short spoken pitch.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 3,
                    "description": "Ids of the best matching events, best first.",
                },
                "pitch": {
                    "type": "string",
                    "description": (
                        "One or two sentences, spoken style, mentioning the day, the place "
                        "and why it fits. Same language as the user."
                    ),
                },
            },
            "required": ["event_ids", "pitch"],
            "additionalProperties": False,
        },
    },
}

SYSTEM_PROMPT = (
    "You are a friendly Kansai (Kyoto/Osaka/Kobe/Nara) events concierge. "
    "The user tells you what they feel like doing. Pick 1-3 events from the list that fit best "
    "and call the tool `pick_events`. Only ever use ids that appear in the list, copied "
    "verbatim including the `source:` prefix (for example `seed:1a2b3c4d5e6f`). "
    "The pitch is read aloud: 1-2 sentences, warm and concrete, mention the weekday, the place "
    "and why it fits. Answer in the language the user used (English by default). "
    "Never invent events."
)

_RANDOM_OPENERS = [
    "I couldn't quite catch that, so here's a surprise:",
    "I didn't catch that one, so here's a surprise pick:",
]


class PickEvents(BaseModel):
    """Validated arguments of the `pick_events` tool call."""

    event_ids: list[str] = Field(min_length=1, max_length=3)
    pitch: str


def format_when(event: Event) -> str:
    return event.starts_at.astimezone(JST).strftime("%a %d %b %H:%M")


def compact_event(event: Event) -> str:
    """One line per event: id | title | city | date | tags | 1-line description."""
    description = (event.description or "").replace("\n", " ").strip()
    if len(description) > 140:
        description = description[:137].rstrip() + "..."
    tags = ",".join(event.tags[:4])
    return " | ".join(
        [
            event.id,
            event.title.replace("\n", " ").strip(),
            event.city or "Other",
            format_when(event),
            tags,
            description,
        ]
    )


def build_user_prompt(query: str, events: list[Event]) -> str:
    lines = "\n".join(compact_event(event) for event in events)
    return (
        f"User request: {query.strip()}\n\n"
        "Upcoming events (id | title | city | date | tags | description):\n"
        f"{lines}\n\n"
        f"Call {TOOL_NAME} with the 1-3 best ids and a spoken pitch."
    )


def get_mistral_client(settings: Settings) -> Any:
    """Isolated so tests can monkeypatch the SDK away."""
    from mistralai.client import Mistral

    return Mistral(api_key=settings.mistral_api_key)


def _tool_arguments(response: Any) -> dict[str, Any]:
    choice = response.choices[0]
    tool_calls = getattr(choice.message, "tool_calls", None) or []
    if not tool_calls:
        raise ValueError("Mistral returned no tool call")
    raw = tool_calls[0].function.arguments
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, dict):
        return raw
    raise ValueError(f"Unexpected tool arguments type: {type(raw).__name__}")


async def call_llm(query: str, events: list[Event], settings: Settings) -> dict[str, Any]:
    """Single Mistral round-trip returning the raw `pick_events` arguments.

    Kept as a module-level function so tests can monkeypatch it wholesale.
    """
    client = get_mistral_client(settings)
    response = await client.chat.complete_async(
        model=settings.mistral_chat_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(query, events)},
        ],
        tools=[PICK_EVENTS_TOOL],
        tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        temperature=0.3,
        max_tokens=500,
    )
    return _tool_arguments(response)


def resolve_ids(event_ids: list[str], by_id: dict[str, Event]) -> list[Event]:
    """Map model-returned ids onto real events, tolerating a dropped `source:` prefix."""
    by_suffix: dict[str, Event] = {}
    for eid, event in by_id.items():
        by_suffix.setdefault(eid.split(":", 1)[-1], event)

    chosen: list[Event] = []
    for raw in event_ids:
        candidate = raw.strip().strip("`'\"")
        event = by_id.get(candidate) or by_suffix.get(candidate.split(":", 1)[-1])
        if event is None:
            logger.info("Dropping unknown event id %r", raw)
            continue
        if event not in chosen:
            chosen.append(event)
    return chosen


def random_match(
    events: list[Event],
    *,
    transcript: str | None = None,
    language: str | None = None,
    apologetic: bool = True,
) -> MatchResponse:
    """Fallback answer: one random upcoming event and a template pitch."""
    if not events:
        return MatchResponse(
            transcript=transcript,
            language=language,
            events=[],
            pitch="I don't have any upcoming events right now — try refreshing in a moment.",
            mode="random",
        )
    event = random.choice(events)
    where = event.city or event.location or "Kansai"
    tail = f"{event.title} on {format_when(event)} in {where}."
    opener = random.choice(_RANDOM_OPENERS) if apologetic else "Here's an idea:"
    return MatchResponse(
        transcript=transcript,
        language=language,
        events=[event],
        pitch=f"{opener} {tail}",
        mode="random",
    )


async def match(
    query: str,
    events: list[Event],
    settings: Settings,
    *,
    transcript: str | None = None,
    language: str | None = None,
) -> MatchResponse:
    """Never raises. Returns `mode="match"` on success, `mode="random"` on any failure."""
    transcript = transcript if transcript is not None else query
    if len(query.strip()) < MIN_QUERY_CHARS:
        logger.info("Query too short (%r) — random mode", query)
        return random_match(events, transcript=transcript, language=language)
    if not events:
        return random_match(events, transcript=transcript, language=language)
    if not settings.mistral_api_key:
        logger.warning("MISTRAL_API_KEY missing — random mode")
        return random_match(events, transcript=transcript, language=language)

    candidates = events[: settings.max_events_for_llm]
    by_id = {event.id: event for event in candidates}

    for attempt in (1, 2):
        try:
            arguments = await call_llm(query, candidates, settings)
            picked = PickEvents.model_validate(arguments)
            chosen = resolve_ids(picked.event_ids, by_id)
            if not chosen:
                raise ValueError("LLM returned no known event ids")
            return MatchResponse(
                transcript=transcript,
                language=language,
                events=chosen,
                pitch=picked.pitch.strip(),
                mode="match",
            )
        except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("Match attempt %d rejected: %s", attempt, exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Match attempt %d failed", attempt)

    return random_match(events, transcript=transcript, language=language)
