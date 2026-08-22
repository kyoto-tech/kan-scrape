"""The voice route only relies on this module-level contract — keep it stable."""

import inspect

from app.services import stt


def test_module_exposes_the_voice_route_contract() -> None:
    assert inspect.iscoroutinefunction(stt.transcribe)
    assert inspect.iscoroutinefunction(stt.warmup)

    params = list(inspect.signature(stt.transcribe).parameters)
    assert params == ["data", "filename", "content_type"]

    fields = stt.Transcript.model_fields
    assert set(fields) == {"text", "language", "duration_s", "provider"}
