"""FastAPI app factory.

Startup loads the seed synchronously and refreshes remote sources in the background.
"""

import asyncio
import contextlib
import inspect
import logging
import time
from collections import abc

import fastapi
from fastapi.middleware import cors

from app.api import router
from app.core import config
from app.core.logging import configure_logging
from app.services import events as event_service

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


@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI) -> abc.AsyncIterator[None]:
    settings: config.Settings = config.get_settings()
    store = event_service.build_store(settings, with_remote=settings.fetch_remote_sources)
    store.load_seed()
    app.state.event_store = store

    tasks: list[asyncio.Task[object]] = []
    if settings.fetch_remote_sources:
        tasks.append(asyncio.create_task(store.refresh(), name="events-refresh"))

    # Preload Whisper into VRAM, but off the startup path: the model loads on a daemon
    # thread (see app/services/stt.py) so Ctrl-C during the 30-120s cold load exits at once
    # instead of waiting for it. /api/transcribe/status reports when the model is ready;
    # a request arriving earlier simply waits for the same load. STT_WARMUP=false = lazy.
    tasks.append(asyncio.create_task(_warmup_stt(), name="stt-warmup"))

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


def create_app() -> fastapi.FastAPI:
    settings = config.get_settings()
    configure_logging(settings)
    app = fastapi.FastAPI(
        title=settings.app_name,
        version=settings.version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        cors.CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router.api_router, prefix=settings.api_prefix)
    return app


app = create_app()
