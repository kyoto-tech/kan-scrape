from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_MEETUP_GROUPS = [
    "kyoto-tech-meetup",
    "osaka-international-friends",
    "kyoto-hiking",
    "kansai-hikers",
    "kyoto-english-club",
    "osaka-running-club",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Kan Scrape API"
    version: str = "0.1.0"
    debug: bool = False
    api_prefix: str = "/api"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # --- LLM (matching + pitch) ---
    mistral_api_key: str | None = None
    mistral_chat_model: str = "mistral-small-latest"

    # --- STT (local first) ---
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "auto"  # auto | cuda | mlx (Apple Silicon) | cpu
    whisper_compute_type: str | None = None  # default: float16 on cuda, int8 on cpu
    stt_fallback: str | None = None  # None | "voxtral"
    voxtral_model: str = "voxtral-mini-latest"
    mlx_whisper_repo: str | None = None  # override the mlx-community repo guess
    stt_max_seconds: int = 60
    stt_warmup: bool = True  # False keeps the model unloaded until the first request

    # --- TTS ---
    edge_tts_voice: str = "en-US-AvaMultilingualNeural"

    # --- Event sources ---
    doorkeeper_token: str | None = None
    connpass_api_key: str | None = None
    meetup_groups: Annotated[list[str], NoDecode] = DEFAULT_MEETUP_GROUPS
    http_timeout_s: float = 10.0
    fetch_remote_sources: bool = True
    max_events_for_llm: int = 40

    @field_validator("cors_origins", "meetup_groups", mode="before")
    @classmethod
    def split_csv(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
