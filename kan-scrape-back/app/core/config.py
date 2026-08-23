import functools
from typing import Annotated

import pydantic
import pydantic_settings

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


class Settings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Kan Scrape API"
    version: str = "0.1.0"
    debug: bool = False
    log_file: str | None = "logs/kan-scrape.log"
    api_prefix: str = "/api"
    cors_origins: Annotated[list[str], pydantic_settings.NoDecode] = ["http://localhost:5173"]

    # --- LLM (matching + pitch) ---
    mistral_api_key: str | None = None
    mistral_chat_model: str = "mistral-small-latest"

    # --- STT (local first) ---
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "auto"  # auto | cuda | mlx (Apple Silicon) | cpu
    whisper_compute_type: str | None = None  # default: float16 on cuda, int8 on cpu
    stt_fallback: str | None = None  # None | "voxtral"
    voxtral_model: str = "voxtral-mini-latest"
    stt_max_seconds: int = 60
    stt_warmup: bool = True  # False keeps the model unloaded until the first request

    # --- TTS ---
    edge_tts_voice: str = "en-US-AvaMultilingualNeural"

    # --- Event sources ---
    seed_events: bool | None = None  # None = follow `debug`: fixture events only in dev
    doorkeeper_token: str | None = None
    connpass_api_key: str | None = None
    meetup_groups: Annotated[list[str], pydantic_settings.NoDecode] = DEFAULT_MEETUP_GROUPS
    http_timeout_s: float = 10.0
    fetch_remote_sources: bool = True
    max_events_for_llm: int = 40

    @property
    def seed_enabled(self) -> bool:
        """Whether the offline demo fixture ships as real events."""
        return self.debug if self.seed_events is None else self.seed_events

    @pydantic.field_validator("cors_origins", "meetup_groups", mode="before")
    @classmethod
    def split_csv(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @pydantic.field_validator("seed_events", mode="before")
    @classmethod
    def empty_seed_events(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @pydantic.field_validator("log_file", mode="before")
    @classmethod
    def empty_log_file(cls, value: str | None) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
