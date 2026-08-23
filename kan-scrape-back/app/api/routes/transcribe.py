"""Standalone transcription endpoint. `/match/voice` uses the same service internally."""

import logging
from typing import Annotated

import fastapi
import pydantic

from app.services import stt

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(tags=["stt"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.post("/transcribe", response_model=stt.Transcript)
async def transcribe_audio(
    audio: Annotated[
        fastapi.UploadFile, fastapi.File(description="webm/opus blob from MediaRecorder")
    ],
) -> stt.Transcript:
    try:
        data = await audio.read()
    except Exception as exc:  # noqa: BLE001 - malformed upload must not 500
        raise fastapi.HTTPException(
            status_code=400, detail="Could not read the uploaded audio"
        ) from exc

    if not data:
        raise fastapi.HTTPException(status_code=400, detail="Empty audio upload")
    if len(data) > MAX_AUDIO_BYTES:
        raise fastapi.HTTPException(status_code=413, detail="Audio larger than 10 MB")

    try:
        return await stt.get_stt().transcribe(data, audio.filename or "audio.webm")
    except stt.AudioTooLongError as exc:
        raise fastapi.HTTPException(status_code=413, detail=str(exc)) from exc
    except stt.SttError as exc:
        logger.warning("Transcription unavailable: %s", exc)
        raise fastapi.HTTPException(status_code=503, detail="Transcription unavailable") from exc
    except Exception as exc:  # noqa: BLE001 - never leak a 500 from the model
        logger.exception("Unexpected transcription failure")
        raise fastapi.HTTPException(status_code=503, detail="Transcription unavailable") from exc


class SttStatus(pydantic.BaseModel):
    ready: bool
    model: str
    device: str | None = None
    compute_type: str | None = None


@router.get("/transcribe/status", response_model=SttStatus)
async def transcribe_status() -> SttStatus:
    """Is Whisper loaded, and on what? `ready` is true once the model can answer."""
    service = stt.get_stt()
    return SttStatus(
        ready=service.ready,
        model=service.model_name,
        device=service.device,
        compute_type=service.compute_type,
    )
