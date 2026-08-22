# Kan Scrape API

FastAPI backend for the Kan Scrape monorepo. Serves scraped Kansai tech events to the frontend.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Local development

```bash
cd kan-scrape-back
uv sync
cp .env.example .env   # optional, defaults work for local dev
uv run uvicorn app.main:app --reload
```

API runs at http://localhost:8000 — docs at http://localhost:8000/docs.

Available commands:

```bash
uv run pytest        # tests
uv run ruff check .  # lint
uv run ruff format . # format
```

## Structure

```text
kan-scrape-back/
├── app/
│   ├── main.py          # App factory, CORS, router mounting
│   ├── core/config.py   # Settings (env / .env via pydantic-settings)
│   ├── api/
│   │   ├── router.py    # Aggregates all routes under /api
│   │   └── routes/      # One module per resource (health, events)
│   └── schemas/         # Pydantic models
└── tests/
```

## Endpoints

| Method | Path          | Description                      |
|--------|---------------|----------------------------------|
| GET    | `/api/health` | Liveness check                   |
| GET    | `/api/events` | List events (scrapers pending)   |
