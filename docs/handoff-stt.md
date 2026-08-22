# Handoff — STT (speech-to-text) for kan-scrape backend

Part of the hack-day plan in `docs/handoff-backend.md` (read its "Goal" + "Provider policy" first). This agent owns **only the STT
slice**. Other agents work on event sources / matcher / frontend in parallel — stay inside the files listed under "You own".

## What to build
A local, GPU-accelerated transcription service in the FastAPI backend (`kan-scrape-back/`):
browser `MediaRecorder` blob (webm/opus, a few seconds of speech, EN or JP) → `faster-whisper` → `{text, language, duration_s}`.

**Provider policy: local first.** `faster-whisper` is the default and must work. Mistral Voxtral (`POST /v1/audio/transcriptions`,
model `voxtral-mini-latest`, `MISTRAL_API_KEY`) may be wired ONLY as an opt-in fallback (`STT_FALLBACK=voxtral`) when the local
model fails to load or raises. Never call the API when Whisper works.

## You own (create/edit only these)
- `app/services/stt.py` — the service
- `app/api/routes/transcribe.py` — `POST /api/transcribe` (+ register in `app/api/router.py`, one line)
- `app/core/config.py` — add the STT settings listed below (append, don't restructure)
- `.env.example` — add the STT vars
- `tests/test_stt.py`, `tests/fixtures/` (small audio fixture)
- `pyproject.toml`/`uv.lock` via `uv add faster-whisper python-multipart` (+ `httpx` only if you implement the Voxtral fallback)
Do NOT touch `schemas/event.py`, `routes/events.py`, matcher, sources. The matcher agent will import your service.

## Service interface (contract — other agents code against this)
```python
# app/services/stt.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Transcript:
    text: str            # stripped; "" if nothing recognized
    language: str | None # ISO-639-1 from whisper detection ("en", "ja", ...)
    duration_s: float
    provider: str        # "whisper" | "voxtral"

class SpeechToText:
    def __init__(self, settings): ...          # reads WHISPER_* from Settings
    async def warmup(self) -> None: ...        # load model (idempotent); call from app lifespan, must not raise
    async def transcribe(self, audio: bytes, filename: str = "audio.webm") -> Transcript: ...
    @property
    def ready(self) -> bool: ...

def get_stt() -> SpeechToText: ...             # process-wide singleton, FastAPI dependency-friendly
```
- Model loaded once, lazily or via `warmup()` hooked into `create_app()` lifespan (startup must NOT block >1 s on download — run
  warmup as a background task; `ready=False` until loaded; `transcribe()` before ready → loads synchronously/awaits warmup).
- Inference is blocking → `await asyncio.to_thread(...)`, guarded by an `asyncio.Lock` (one model, serialize calls).
- Decode: write bytes to a temp file, pass path to `model.transcribe(path, beam_size=1, vad_filter=True, language=None)`; if
  PyAV fails on webm, fallback `ffmpeg -i in -ar 16000 -ac 1 -f wav out.wav` (ffmpeg is on PATH). Join segment texts, strip.
- Device: `WHISPER_DEVICE=auto` → try `cuda`+`float16`, on any exception fall back to `cpu`+`int8` and log a warning. Never crash.
- Limits: reject audio > 10 MB or > 60 s with HTTP 413/400; empty upload → 400.

## Endpoint
`POST /api/transcribe` — multipart field `audio` (UploadFile). Response:
`{"text": "...", "language": "en", "duration_s": 3.2, "provider": "whisper"}`. Errors as JSON `{"detail": ...}`; model failure → 503
(unless Voxtral fallback enabled and succeeds).

## Settings (`Settings` in `app/core/config.py`)
```
WHISPER_MODEL=large-v3-turbo        # faster-whisper name; "small" for weak machines
WHISPER_DEVICE=auto                 # auto|cuda|cpu
WHISPER_COMPUTE_TYPE=auto           # auto→float16 on cuda / int8 on cpu
STT_FALLBACK=none                   # none|voxtral
STT_MAX_SECONDS=60
```

## Machine facts
- GPU: NVIDIA RTX 3080 Ti Laptop (WSL2). `whisper-ctranslate2` (uv tool, same engine) already runs here with `--device cuda
  --compute_type float16` — if CUDA libs aren't found in the fresh venv, look at how that tool's env resolves them
  (`~/.local/share/uv/tools/whisper-ctranslate2/`; typically `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` wheels, add with `uv add`).
  CPU int8 fallback is mandatory regardless.
- `large-v3-turbo` download (~1.6 GB, HF repo `mobiuslabsgmbh/faster-whisper-large-v3-turbo`) is already downloaded to
  `~/.cache/huggingface/hub/` (1.6 GB, verified loading on `cuda`/`float16` from the whisper-ctranslate2 tool env). `tiny`/`small` download fast for tests.
- `ffmpeg` on PATH. Python 3.12, uv, ruff (line-length 100), pytest. Run: `cd kan-scrape-back && uv sync && uv run uvicorn app.main:app --reload`.

## Tests (`uv run pytest`, default run = no GPU, no big download)
- Unit: `SpeechToText.transcribe` with `WhisperModel` monkeypatched (fake segments) → text joined, language passed through.
- Route: `POST /api/transcribe` with fake service → 200 JSON; empty file → 400; oversize → 413; service raising → 503.
- Device fallback: cuda init raising → cpu/int8 chosen.
- Integration (marked `@pytest.mark.integration`, skipped unless `RUN_STT_INTEGRATION=1`): real `tiny` model on a fixture clip.
  Make the fixture yourself: `edge-tts --voice en-US-AvaNeural --text "I want a Python meetup in Kyoto this weekend" --write-media tests/fixtures/sample.mp3`
  then `ffmpeg -i tests/fixtures/sample.mp3 -c:a libopus tests/fixtures/sample.webm` (edge-tts is installed as a uv tool). Keep fixtures < 200 KB.

## Done criteria
- `uv run pytest` green, `uv run ruff check .` clean.
- Real check: server up, `curl -F audio=@tests/fixtures/sample.webm localhost:8000/api/transcribe` → correct English text, `provider=whisper`,
  < 2 s on GPU. Report measured latency and which device/compute type was actually used.
- README endpoint table: add `/api/transcribe`. `.env.example` updated.
- Commit on branch `miro`: `feat(back): local whisper STT service + /transcribe`. Don't commit model files or audio > 200 KB.

## Don'ts
No Voxtral by default, no OpenAI, no DB, no changes outside "You own", no blocking startup on model download, no `print` (use `logging`).
