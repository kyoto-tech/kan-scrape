# Handoff — kan-scrape backend (hack-day, ~90 min budget)

## Goal
One-button Kansai event finder. User presses a button, speaks ("I want a Python meetup in Kyoto this weekend"),
backend transcribes (local Whisper) → Mistral picks best-fit events → returns events + short pitch → pitch spoken via edge-tts. Voice in, voice out.
Hack-day: working demo beats completeness. Every endpoint must degrade gracefully (random event fallback), never 500.

## Repo state
- `kan-scrape-back/` FastAPI + uv, py3.12, ruff, pytest. App factory `app/main.py`, settings `app/core/config.py`
  (pydantic-settings, `.env`), routes under `/api` (`app/api/router.py`), `Event` schema in `app/schemas/event.py`.
- `GET /api/events` currently returns `[]`. Tests: `tests/` with `client` fixture (`TestClient(create_app())`).
- Run: `uv sync && uv run uvicorn app.main:app --reload` · test: `uv run pytest` · lint: `uv run ruff check .`
- Frontend (separate agent) is Vite/React on :5173, CORS already allowed.

## Provider policy (read first)
- **LLM (matching + pitch): API.** Mistral, free tier. No local LLM.
- **Speech (STT + TTS): local first, API only as fallback.** STT = `faster-whisper` on GPU; TTS = `edge-tts`. Voxtral/OpenAI/etc. are NOT defaults.

## Stack decisions (fixed)
- **Match/pitch LLM: Mistral** (free Experiment tier, `MISTRAL_API_KEY`), `mistral-small-latest`, chat completions with
  **function calling** (tool schema = Pydantic) for reliable JSON. `response_format json_object` is NOT schema-guaranteed.
  Validate with Pydantic, retry once, then fallback. Use `mistralai` SDK (>=1.x) or plain `httpx`; check current request
  shape in docs (https://docs.mistral.ai/) — don't guess param names.
- **STT: owned by a separate agent — see `docs/handoff-stt.md`.** Import `app.services.stt.get_stt()` →
  `await stt.transcribe(bytes, filename)` → `Transcript(text, language, duration_s, provider)`. Until it lands, stub it. Details for reference:
  local `faster-whisper` (same engine as the `whisper-ctranslate2` CLI already on this machine; GPU = RTX 3080 Ti).
  `WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=...)` loaded once at startup (lazy on first call is ok),
  `device="cuda"`+`float16` if available else `cpu`+`int8`. Defaults: `WHISPER_MODEL=large-v3-turbo` (≈1.6 GB download on
  first run — trigger it at startup or via `uv run python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo')"`;
  if download is slow use `small`). Auto language detect (JP+EN). Browser sends webm/opus; faster-whisper decodes via PyAV
  (ffmpeg is on PATH as backup: `ffmpeg -i in.webm -ar 16000 -ac 1 out.wav`). Return `transcript` + detected `language`.
  **Provider order: local first, API only as fallback.** Voxtral STT (`/v1/audio/transcriptions`, `voxtral-mini-latest`) may be
  wired ONLY as a fallback behind `STT_FALLBACK=voxtral` when Whisper fails to load/run. Never the default.
- **TTS: `edge-tts`** (Microsoft neural voices, free, no key, needs internet; already used in /mnt/data/dev/transcript-to-podcast).
  `edge_tts.Communicate(text, voice).save(path)` or stream chunks → `audio/mpeg`. Default voice
  `EDGE_TTS_VOICE=en-US-AvaMultilingualNeural` (multilingual → handles JP names in an EN sentence). Cache by sha1(text+voice) in memory/tmp.
  Same rule: edge-tts is the default; no paid/keyed TTS API. If edge-tts errors, return 503 — frontend falls back to browser `speechSynthesis`.
- No DB. In-memory event cache, filled on startup + `POST /api/events/refresh`.
- No ScrapeGraphAI / Scrapling / Playwright. Structured sources only.

## Event sources (adapters, in priority order — stop when 2 work)
Implement `app/sources/base.py`: `class Source(Protocol): name: str; async def fetch(self) -> list[Event]`.
Each adapter must fail soft (log + return []). Use `httpx.AsyncClient`, 10 s timeout.
1. **Seed fixture** `app/sources/seed.py` — loads `app/sources/seed_events.json` with ~20 realistic upcoming Kansai events
   (Kyoto/Osaka/Kobe; mix of tech meetups, language exchange, hiking, food, music; EN+JP titles; dates within next 30 days
   relative to now). ALWAYS on. Guarantees demo works with zero network/keys.
2. **Meetup iCal** `app/sources/meetup_ical.py` — no key. Hardcode ~6 groups, URL pattern
   `https://www.meetup.com/<group-slug>/events/ical/`. Parse with `icalendar`. Find real slugs via web search
   (e.g. Kyoto/Osaka language exchange, hiking, tech/startup groups). If feed 403s, drop silently.
3. **Doorkeeper API** `app/sources/doorkeeper.py` — `https://api.doorkeeper.jp/events?prefecture=京都府` etc.,
   needs Bearer token (`DOORKEEPER_TOKEN`, optional). Skip adapter if env missing.
4. **Connpass API v2** `app/sources/connpass.py` — `https://connpass.com/api/v2/events/?prefecture=kyoto,osaka,hyogo`
   with `X-API-Key` (`CONNPASS_API_KEY`, optional; key requires application — may not be available today). Skip if missing.
Dedup by normalized (title, starts_at date). Keep only events with `starts_at >= now`. Sort by `starts_at`.

## Schema changes (`app/schemas/event.py`)
Extend `Event`: add `description: str | None`, `city: str | None` (Kyoto/Osaka/Kobe/Nara/Other), `tags: list[str] = []`,
`lang: Literal["ja","en","mixed"] | None`, `price: str | None`, `image_url: HttpUrl | None`. `id` = `f"{source}:{hash}"`.
Match response: `MatchResponse { transcript: str | None, language: str | None, events: list[Event], pitch: str, mode: Literal["match","random"] }`.

## Endpoints (all under `/api`)
| Method | Path | Behaviour |
|---|---|---|
| GET | `/events` | cached events, query `?city=&limit=` |
| POST | `/events/refresh` | re-run all adapters, return `{count, per_source}` |
| GET | `/events/random` | one random upcoming event + short pitch (no LLM needed; template string ok) |
| POST | `/match/voice` | multipart `audio` (webm/opus from browser MediaRecorder) → Whisper STT → match → `MatchResponse` |
| POST | `/match/text` | JSON `{query}` → same match path, no STT (for frontend dev + tests) |
| GET | `/speech?text=&voice=` | edge-tts → `audio/mpeg` (StreamingResponse). Frontend plays the pitch with it. |

Match logic (`app/services/matcher.py`): take up to 40 upcoming events, compact them to `id | title | city | date | tags | 1-line desc`,
prompt Mistral to call tool `pick_events(event_ids: list[str] (2-5), pitch: str)` — pitch = 1–2 sentences, spoken style,
mentions day + place + why it fits, in the language the user spoke (EN default). Unknown ids → drop. Empty/garbled transcript (<3 chars) or LLM failure → `mode="random"`,
pitch "I couldn't quite catch that, so here's a surprise: …".

## Config (`app/core/config.py` + `.env.example`)
`MISTRAL_API_KEY` (required for voice/match; app must still boot without it — random mode only),
`MISTRAL_CHAT_MODEL=mistral-small-latest`, `WHISPER_MODEL=large-v3-turbo`, `WHISPER_DEVICE=auto`, `EDGE_TTS_VOICE=en-US-AvaMultilingualNeural`,
`DOORKEEPER_TOKEN`, `CONNPASS_API_KEY`, `MEETUP_GROUPS` (comma list, default hardcoded). Update `.env.example`.

## Deps to add
`httpx`, `mistralai` (or just httpx), `icalendar`, `python-multipart`, `faster-whisper`, `edge-tts`. Keep `uv.lock` updated (`uv add`).

## Tests (keep them cheap — no network)
- `/events` returns seed events, sorted, only future.
- `/events/random` returns one event.
- `/speech` with edge-tts mocked returns audio/mpeg.
- `/match/text` with Mistral client mocked → `mode=match`, ids valid; with client raising → `mode=random`.
- Adapter parsing unit tests with small fixture strings (one iCal, one Doorkeeper JSON).

## Done criteria
`uv run pytest` green · `ruff check` clean · `curl -F audio=@sample.webm localhost:8000/api/match/voice` returns transcript + events + pitch
with a real Mistral key; `curl 'localhost:8000/api/speech?text=hello' -o x.mp3` plays · README endpoint table updated · `.env.example` updated. Commit on branch `miro` with message `feat(back): sources, whisper voice match, edge-tts speech`.

## Don'ts
No DB/ORM, no auth, no Docker, no background schedulers, no scraping of Peatix/Eventbrite/Facebook (ToS). Don't block startup on network.
