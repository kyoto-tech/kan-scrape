"""FastAPI app factory.

Startup loads the seed synchronously and refreshes remote sources in the background.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.services.events import build_store

logger = logging.getLogger(__name__)


async def _warmup_stt() -> None:
    """Best-effort STT preload. Owned by the STT agent, so stay defensive about its shape."""
    try:
        from app.services import stt

        warmup = getattr(stt, "warmup", None)
        if warmup is None:
            return
        started = time.perf_counter()
        result = warmup()
        if inspect.isawaitable(result):
            await result
        logger.info("STT warmup finished in %.1fs", time.perf_counter() - started)
    except Exception:  # noqa: BLE001 - never break startup on STT
        logger.warning("STT warmup failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    store = build_store(settings, with_remote=settings.fetch_remote_sources)
    store.load_seed()
    app.state.event_store = store

    tasks: list[asyncio.Task[object]] = []
    if settings.fetch_remote_sources:
        tasks.append(asyncio.create_task(store.refresh(), name="events-refresh"))

    # Blocking on purpose: the server should not report itself ready until Whisper can
    # answer, so the first /api/transcribe never pays the model load. STT_WARMUP=false
    # restores lazy loading (tests use that). Never raises — a dead model just means 503s.
    await _warmup_stt()

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
