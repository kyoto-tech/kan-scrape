"""Voice and text matching routes. Both degrade to a random pick, never to a 500."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.api.deps import SettingsDep, StoreDep
from app.schemas.event import MatchResponse, TextMatchRequest
from app.services.matcher import match, random_match

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/match", tags=["match"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.post("/text", response_model=MatchResponse)
async def match_text(
    payload: TextMatchRequest,
    store: StoreDep,
    settings: SettingsDep,
) -> MatchResponse:
    """Same match path as `/match/voice`, minus the transcription step."""
    return await match(payload.query, store.all(), settings)


@router.post("/voice", response_model=MatchResponse)
async def match_voice(
    store: StoreDep,
    settings: SettingsDep,
    audio: Annotated[UploadFile, File(description="webm/opus blob from MediaRecorder")],
) -> MatchResponse:
    """Transcribe the upload, then match. Any STT failure falls back to a random pick."""
    events = store.all()
    # Starlette knows the part size after parsing the form, so check it before pulling a
    # possibly huge spooled file into memory.
    size = getattr(audio, "size", None)
    if isinstance(size, int) and size > MAX_AUDIO_BYTES:
        logger.info("Audio upload too large (%d bytes) — random mode", size)
        return random_match(events)

    try:
        data = await audio.read()
    except Exception:  # noqa: BLE001 - malformed upload must not 500
        logger.exception("Could not read uploaded audio")
        return random_match(events)

    if not data:
        logger.info("Empty audio upload — random mode")
        return random_match(events)
    if len(data) > MAX_AUDIO_BYTES:
        logger.info("Audio upload too large (%d bytes) — random mode", len(data))
        return random_match(events)

    text, language = "", None
    try:
        from app.services.stt import transcribe

        transcript = await transcribe(data, audio.filename, audio.content_type)
        text = (transcript.text or "").strip()
        language = transcript.language
    except Exception:  # noqa: BLE001 - STT is optional; degrade instead of failing
        logger.exception("Transcription failed — random mode")
        return random_match(events)

    if not text:
        logger.info("Empty transcript — random mode")
        return random_match(events, transcript=text or None, language=language)

    return await match(text, events, settings, transcript=text, language=language)
