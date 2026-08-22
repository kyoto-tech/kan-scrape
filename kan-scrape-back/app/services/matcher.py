"""Match a spoken/typed wish against cached events with Mistral function calling."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, ValidationError

from app.schemas.event import Event, MatchResponse
from app.sources.base import JST

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.core.config import Settings

logger = logging.getLogger(__name__)

MIN_QUERY_CHARS = 3
TOOL_NAME = "pick_events"
OUT_OF_SCOPE_TERMS = (
    "tokyo",
    "yokohama",
    "nagoya",
    "sapporo",
    "sendai",
    "fukuoka",
    "okinawa",
    "new york",
    "london",
    "outside kansai",
)
MIN_PICK = 1
MAX_PICK = 5

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
                    "minItems": MIN_PICK,
                    "maxItems": MAX_PICK,
                    "description": "Ids of the best matching events, best first.",
                },
                "pitch": {
                    "type": "string",
                    "minLength": 1,
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
    "The user tells you what they feel like doing. Pick 1-5 events from the list that fit "
    "best, best first, "
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


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _trim_ids(value: object) -> object:
    """Too many ids is a formatting slip, not a failed match — keep the best few."""
    if isinstance(value, list):
        return value[:MAX_PICK]
    return value


class PickEvents(BaseModel):
    """Validated arguments of the `pick_events` tool call.

    The tool schema asks the model for `MIN_PICK`-`MAX_PICK` ids; validation here is
    deliberately looser. An over-long list is truncated rather than rejected, and a single
    id is accepted: falling back to a random event because the model returned 1 or 6 ids
    would be a worse answer than the one it actually gave us.
    """

    event_ids: Annotated[list[str], BeforeValidator(_trim_ids)] = Field(min_length=1)
    # A blank pitch would reach the frontend as `mode="match"` with nothing to speak, and
    # `/speech?text=` then 422s — silence in the demo. Reject it so we retry, then fall back.
    pitch: Annotated[str, BeforeValidator(_strip)] = Field(min_length=1)


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
        f"Call {TOOL_NAME} with the {MIN_PICK}-{MAX_PICK} best ids (best first) and a spoken pitch."
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
    # `async with` closes the SDK's httpx client; a fresh unclosed one per request leaks
    # sockets across a demo's worth of calls.
    async with get_mistral_client(settings) as client:
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


def is_kyoto_tech_meetup(event: Event) -> bool:
    """Identify the community's own Meetup group for guaranteed top placement."""
    return bool(
        event.url and "meetup.com/kyoto-tech-meetup/events/" in str(event.url).casefold()
    )


def prioritize_community_event(events: list[Event]) -> list[Event]:
    """Keep Kyoto Tech Meetup first, even when the response reaches the five-event cap."""
    unique = list({event.id: event for event in events}.values())
    featured = [event for event in unique if is_kyoto_tech_meetup(event)]
    remaining = [event for event in unique if not is_kyoto_tech_meetup(event)]
    return (featured + remaining)[:MAX_PICK]


def random_match(
    events: list[Event],
    *,
    transcript: str | None = None,
    language: str | None = None,
    apologetic: bool = True,
) -> MatchResponse:
    """Fallback answer: a random sample of upcoming events and a template pitch."""
    if not events:
        return MatchResponse(
            transcript=transcript,
            language=language,
            events=[],
            pitch="I don't have any upcoming events right now — try refreshing in a moment.",
            mode="random",
        )
    featured = [event for event in events if is_kyoto_tech_meetup(event)]
    remaining = [event for event in events if not is_kyoto_tech_meetup(event)]
    sample_size = min(len(remaining), MAX_PICK - min(len(featured), 1))
    chosen = prioritize_community_event(featured[:1] + random.sample(remaining, k=sample_size))
    event = chosen[0]
    where = event.city or event.location or "Kansai"
    tail = f"{event.title} on {format_when(event)} in {where}."
    opener = random.choice(_RANDOM_OPENERS) if apologetic else "Here's an idea:"
    return MatchResponse(
        transcript=transcript,
        language=language,
        events=chosen,
        pitch=f"{opener} {tail}",
        mode="random",
    )


def is_out_of_scope(query: str) -> bool:
    """Catch explicit requests for locations outside the current Kansai coverage."""
    normalized = query.casefold()
    return any(term in normalized for term in OUT_OF_SCOPE_TERMS)


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
    if is_out_of_scope(query):
        return MatchResponse(
            transcript=transcript,
            language=language,
            events=[],
            pitch=(
                "I am currently specialised in events across Kansai, including Kyoto, Osaka, "
                "Kobe, Nara and nearby areas."
            ),
            mode="match",
        )
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
            featured_candidates = [event for event in candidates if is_kyoto_tech_meetup(event)]
            return MatchResponse(
                transcript=transcript,
                language=language,
                events=prioritize_community_event(featured_candidates[:1] + chosen),
                pitch=picked.pitch,
                mode="match",
            )
        except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("Match attempt %d rejected: %s", attempt, exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Match attempt %d failed", attempt)

    return random_match(events, transcript=transcript, language=language)
