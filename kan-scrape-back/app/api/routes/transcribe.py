"""Standalone transcription endpoint. `/match/voice` uses the same service internally."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.stt import AudioTooLongError, SttError, Transcript, get_stt

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stt"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.post("/transcribe", response_model=Transcript)
async def transcribe_audio(
    audio: Annotated[UploadFile, File(description="webm/opus blob from MediaRecorder")],
) -> Transcript:
    try:
        data = await audio.read()
    except Exception as exc:  # noqa: BLE001 - malformed upload must not 500
        raise HTTPException(status_code=400, detail="Could not read the uploaded audio") from exc

    if not data:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio larger than 10 MB")

    try:
        return await get_stt().transcribe(data, audio.filename or "audio.webm")
    except AudioTooLongError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except SttError as exc:
        logger.warning("Transcription unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Transcription unavailable") from exc
    except Exception as exc:  # noqa: BLE001 - never leak a 500 from the model
        logger.exception("Unexpected transcription failure")
        raise HTTPException(status_code=503, detail="Transcription unavailable") from exc
