"""edge-tts speech endpoint. Returns 503 so the frontend can use browser speechSynthesis."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import SettingsDep
from app.services.tts import TTSError, iter_chunks, synthesize

logger = logging.getLogger(__name__)

router = APIRouter(tags=["speech"])


@router.get("/speech")
async def speech(
    settings: SettingsDep,
    text: Annotated[str, Query(min_length=1, max_length=800)],
    voice: Annotated[str | None, Query(description="edge-tts voice name")] = None,
) -> StreamingResponse:
    try:
        audio = await synthesize(text, voice or settings.edge_tts_voice)
    except TTSError as exc:
        logger.warning("Speech synthesis unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Speech synthesis unavailable") from exc
    return StreamingResponse(
        iter_chunks(audio),
        media_type="audio/mpeg",
        headers={"Content-Length": str(len(audio)), "Cache-Control": "public, max-age=3600"},
    )
