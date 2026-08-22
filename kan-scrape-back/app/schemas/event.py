from datetime import datetime

from pydantic import BaseModel, HttpUrl


class Event(BaseModel):
    id: str
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    location: str | None = None
    url: HttpUrl | None = None
    source: str
