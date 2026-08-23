import datetime
import zoneinfo
from typing import Annotated, Any, Literal

import pydantic

JST = zoneinfo.ZoneInfo("Asia/Tokyo")

City = Literal["Kyoto", "Osaka", "Kobe", "Nara", "Online", "Other"]
Lang = Literal["ja", "en", "mixed"]


def _tolerant_url(value: Any, handler: pydantic.ValidatorFunctionWrapHandler) -> Any:
    """A malformed URL costs us the field, never the whole event.

    Upstream feeds happily ship `"image_url": "none"` or a bare path; without this the
    `Event(...)` call raises and the adapter drops an otherwise perfectly good event.
    """
    try:
        return handler(value)
    except pydantic.ValidationError:
        return None


MaybeUrl = Annotated[pydantic.HttpUrl | None, pydantic.WrapValidator(_tolerant_url)]


class Event(pydantic.BaseModel):
    """A single upcoming event, normalised across every source adapter."""

    id: str
    title: str
    starts_at: datetime.datetime
    ends_at: datetime.datetime | None = None
    location: str | None = None
    url: MaybeUrl = None
    source: str
    description: str | None = None
    city: City | None = None
    tags: list[str] = pydantic.Field(default_factory=list)
    lang: Lang | None = None
    price: str | None = None
    image_url: MaybeUrl = None

    @pydantic.field_validator("starts_at", "ends_at")
    @classmethod
    def _assume_jst(cls, value: datetime.datetime | None) -> datetime.datetime | None:
        """Naive input means JST.

        Every downstream comparison (filtering, sorting, dedupe) mixes events from several
        adapters, and comparing a naive datetime with an aware one raises TypeError — a 500
        on `/events`, `/events/random` and both match routes. Normalising here makes that
        impossible regardless of what a source (or a test) hands us.
        """
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=JST)
        return value


class MatchResponse(pydantic.BaseModel):
    """Result of a voice/text match request (or of the random fallback)."""

    transcript: str | None = None
    language: str | None = None
    events: list[Event] = pydantic.Field(default_factory=list)
    pitch: str
    mode: Literal["match", "random"]


class TextMatchRequest(pydantic.BaseModel):
    query: str


class RefreshResponse(pydantic.BaseModel):
    count: int
    per_source: dict[str, int]
