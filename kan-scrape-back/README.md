# Kan Scrape API

FastAPI backend for the Kan Scrape monorepo — a one-button Kansai event finder.
Speak (or type) what you feel like doing, the backend transcribes it, asks Mistral to pick the
best-fitting upcoming events, and speaks the pitch back with edge-tts.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- `ffmpeg` on PATH (audio decoding for STT) — `brew install ffmpeg` on macOS

### Speech-to-text hardware

Transcription is local (`faster-whisper`) and picks its device automatically. Nothing here is
required: every path falls back to CPU/int8, which works everywhere.

| Platform                | `WHISPER_DEVICE=auto` picks | Install                       |
|-------------------------|-----------------------------|-------------------------------|
| Linux/Windows + NVIDIA  | `cuda` / float16            | `uv sync`                     |
| Apple Silicon           | `mlx` / float16 (Metal GPU) | `uv sync --extra mlx`         |
| Apple Silicon, no extra | `cpu` / int8                | `uv sync`                     |
| Intel Mac               | `cpu` / int8                | `uv sync`                     |

The CUDA runtime wheels are Linux/Windows-only (`sys_platform != 'darwin'`), so a plain
`uv sync` on a Mac installs neither them nor MLX. `--extra mlx` adds `mlx-whisper`, which pulls
torch/numba/scipy (~2 GB) and only resolves on darwin/arm64.

ctranslate2 — the engine behind faster-whisper — has no Metal backend, which is why Apple GPU
support goes through a separate `mlx-whisper` backend rather than a device flag. Both are hidden
behind the same `SpeechToText` service, so nothing downstream changes.

## Local development

```bash
cd kan-scrape-back
uv sync
cp .env.example .env   # optional — the app boots and serves seed events with no keys at all
uv run uvicorn app.main:app --reload
```

API runs at http://localhost:8000 — docs at http://localhost:8000/docs.

```bash
uv run pytest        # tests (offline: no network, no model download)
uv run ruff check .  # lint
uv run ruff format . # format
```

## Endpoints

| Method | Path                  | Description                                                                 |
|--------|-----------------------|-----------------------------------------------------------------------------|
| GET    | `/api/health`         | Liveness check                                                              |
| GET    | `/api/events`         | Cached upcoming events. Query: `city` (Kyoto/Osaka/Kobe/Nara/Online), `limit` |
| POST   | `/api/events/refresh` | Re-run every source adapter → `{count, per_source}`                          |
| GET    | `/api/events/random`  | One random upcoming event + template pitch (`MatchResponse`, `mode=random`)  |
| POST   | `/api/match/text`     | JSON `{query}` → `MatchResponse` (LLM match, random fallback)                 |
| POST   | `/api/match/voice`    | multipart `audio` (webm/opus) → STT → `MatchResponse`                         |
| GET    | `/api/speech`         | `?text=&voice=` → `audio/mpeg` via edge-tts (503 if unavailable)              |
| POST   | `/api/transcribe`     | multipart `audio` (webm/opus) → `{text, language, duration_s, provider}`      |
| GET    | `/api/transcribe/status` | `{ready, model, device, compute_type}` — is Whisper loaded, and on what?   |

`MatchResponse` = `{transcript, language, events[], pitch, mode: "match" | "random"}`.
No endpoint returns 500: STT/LLM/source failures degrade to `mode="random"`, and only `/api/speech`
and `/api/transcribe` can answer 503 (the frontend then falls back to browser `speechSynthesis`).
`/api/transcribe` also answers 400 (empty upload) and 413 (over 10 MB or longer than `STT_MAX_SECONDS`).

## Event sources

Adapters live in `app/sources/`, all fail soft (log + return `[]`) and run concurrently:

| Source          | Key needed          | Notes                                                        |
|-----------------|---------------------|--------------------------------------------------------------|
| `seed`          | none                | `seed_events.json`, 20 Kansai events, dates relative to *now* |
| `meetup`        | none                | public iCal feeds of the groups in `MEETUP_GROUPS`            |
| `doorkeeper`    | `DOORKEEPER_TOKEN`  | skipped when the token is missing                             |
| `connpass`      | `CONNPASS_API_KEY`  | skipped when the key is missing                               |

Results are deduped by (normalised title, start date), filtered to the future and sorted by start
time. Startup loads the seed synchronously and refreshes the remote adapters in a background task,
so the app never blocks on the network.

## Configuration

Settings come from the environment or `.env` (see `.env.example`).

| Variable                | Default                        | Purpose                                        |
|-------------------------|--------------------------------|------------------------------------------------|
| `APP_NAME`              | `Kan Scrape API`               | OpenAPI title                                  |
| `DEBUG`                 | `false`                        | Debug mode + verbose logging                   |
| `CORS_ORIGINS`          | `http://localhost:5173`        | Comma-separated allowed origins                |
| `MISTRAL_API_KEY`       | —                              | Matching + pitch. Missing → always random mode  |
| `MISTRAL_CHAT_MODEL`    | `mistral-small-latest`         | Chat model used for `pick_events`              |
| `WHISPER_MODEL`         | `large-v3-turbo`               | faster-whisper model name (`small`/`tiny` on weak machines) |
| `WHISPER_DEVICE`        | `auto`                         | `auto` \| `cuda` \| `mlx` \| `cpu`               |
| `WHISPER_COMPUTE_TYPE`  | —                              | e.g. `float16`, `int8`                          |
| `MLX_WHISPER_REPO`      | —                              | Override the guessed `mlx-community` HF repo    |
| `STT_MAX_SECONDS`       | `60`                           | Longer clips are rejected with 413              |
| `STT_WARMUP`            | `true`                         | Preload Whisper into VRAM in the background at boot; `false` = lazy |
| `STT_FALLBACK`          | —                              | `voxtral` to enable the API fallback            |
| `EDGE_TTS_VOICE`        | `en-US-AvaMultilingualNeural`  | Default `/api/speech` voice                    |
| `DOORKEEPER_TOKEN`      | —                              | Enables the Doorkeeper adapter                 |
| `CONNPASS_API_KEY`      | —                              | Enables the Connpass adapter                   |
| `MEETUP_GROUPS`         | 9 verified Kansai slugs        | Comma-separated meetup.com group slugs         |
| `HTTP_TIMEOUT_S`        | `10`                           | Per-request timeout for source adapters        |
| `MAX_EVENTS_FOR_LLM`    | `40`                           | Events shown to the model per match            |
| `FETCH_REMOTE_SOURCES`  | `true`                         | `false` → seed only, fully offline             |

## Structure

```text
kan-scrape-back/
├── app/
│   ├── main.py             # App factory, CORS, lifespan (seed sync + remotes in background)
│   ├── core/config.py      # Settings (env / .env via pydantic-settings)
│   ├── api/
│   │   ├── router.py       # Aggregates all routes under /api
│   │   ├── deps.py         # Event-store / settings dependencies
│   │   └── routes/         # health, events, match, speech
│   ├── schemas/event.py    # Event, MatchResponse, ...
│   ├── services/
│   │   ├── events.py       # In-memory registry + cache over all adapters
│   │   ├── matcher.py      # Mistral function calling (`pick_events`) + random fallback
│   │   ├── stt.py          # Speech-to-text (owned by the STT agent)
│   │   └── tts.py          # edge-tts synthesis with a sha1 cache
│   └── sources/            # base, seed, meetup_ical, doorkeeper, connpass
└── tests/
```
