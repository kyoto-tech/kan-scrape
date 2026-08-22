from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

City = Literal["Kyoto", "Osaka", "Kobe", "Nara", "Online", "Other"]
Lang = Literal["ja", "en", "mixed"]


class Event(BaseModel):
    """A single upcoming event, normalised across every source adapter."""

    id: str
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    location: str | None = None
    url: HttpUrl | None = None
    source: str
    description: str | None = None
    city: City | None = None
    tags: list[str] = Field(default_factory=list)
    lang: Lang | None = None
    price: str | None = None
    image_url: HttpUrl | None = None


class MatchResponse(BaseModel):
    """Result of a voice/text match request (or of the random fallback)."""

    transcript: str | None = None
    language: str | None = None
    events: list[Event] = Field(default_factory=list)
    pitch: str
    mode: Literal["match", "random"]


class TextMatchRequest(BaseModel):
    query: str


class RefreshResponse(BaseModel):
    count: int
    per_source: dict[str, int]
