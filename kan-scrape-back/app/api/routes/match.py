"""Voice and text matching routes. Both degrade to a random pick, never to a 500."""

import logging
from typing import Annotated

import fastapi

from app.api import deps
from app.schemas import event as event_schema
from app.services import matcher, stt

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/match", tags=["match"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.post("/text", response_model=event_schema.MatchResponse)
async def match_text(
    payload: event_schema.TextMatchRequest,
    store: deps.StoreDep,
    settings: deps.SettingsDep,
) -> event_schema.MatchResponse:
    """Same match path as `/match/voice`, minus the transcription step."""
    return await matcher.match(payload.query, store.all(), settings)


@router.post("/voice", response_model=event_schema.MatchResponse)
async def match_voice(
    store: deps.StoreDep,
    settings: deps.SettingsDep,
    audio: Annotated[
        fastapi.UploadFile, fastapi.File(description="webm/opus blob from MediaRecorder")
    ],
) -> event_schema.MatchResponse:
    """Transcribe the upload, then match. Any STT failure falls back to a random pick."""
    events = store.all()
    # Starlette knows the part size after parsing the form, so check it before pulling a
    # possibly huge spooled file into memory.
    size = getattr(audio, "size", None)
    if isinstance(size, int) and size > MAX_AUDIO_BYTES:
        logger.info("Audio upload too large (%d bytes) — random mode", size)
        return matcher.random_match(events)

    try:
        data = await audio.read()
    except Exception:  # noqa: BLE001 - malformed upload must not 500
        logger.exception("Could not read uploaded audio")
        return matcher.random_match(events)

    if not data:
        logger.info("Empty audio upload — random mode")
        return matcher.random_match(events)
    if len(data) > MAX_AUDIO_BYTES:
        logger.info("Audio upload too large (%d bytes) — random mode", len(data))
        return matcher.random_match(events)

    text, language = "", None
    try:
        transcript = await stt.transcribe(data, audio.filename, audio.content_type)
        text = (transcript.text or "").strip()
        language = transcript.language
    except Exception:  # noqa: BLE001 - STT is optional; degrade instead of failing
        logger.exception("Transcription failed — random mode")
        return matcher.random_match(events)

    if not text:
        logger.info("Empty transcript — random mode")
        return matcher.random_match(events, transcript=text or None, language=language)

    return await matcher.match(text, events, settings, transcript=text, language=language)
