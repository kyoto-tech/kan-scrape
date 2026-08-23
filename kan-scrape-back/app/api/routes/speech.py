"""edge-tts speech endpoint. Returns 503 so the frontend can use browser speechSynthesis."""

import logging
from typing import Annotated

import fastapi
from fastapi import responses

from app.api import deps
from app.services import tts

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(tags=["speech"])


@router.get("/speech")
async def speech(
    settings: deps.SettingsDep,
    text: Annotated[str, fastapi.Query(min_length=1, max_length=800)],
    voice: Annotated[str | None, fastapi.Query(description="edge-tts voice name")] = None,
) -> responses.StreamingResponse:
    try:
        audio = await tts.synthesize(text, voice or settings.edge_tts_voice)
    except tts.TTSError as exc:
        logger.warning("Speech synthesis unavailable: %s", exc)
        raise fastapi.HTTPException(status_code=503, detail="Speech synthesis unavailable") from exc
    return responses.StreamingResponse(
        tts.iter_chunks(audio),
        media_type="audio/mpeg",
        headers={"Content-Length": str(len(audio)), "Cache-Control": "public, max-age=3600"},
    )
