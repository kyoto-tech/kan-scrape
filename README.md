# Kan Scrape

Kan Scrape monorepo. The project is organized into independent applications and services that share the same repository.

## Estructura

```text
kan-scrape/
├── kan-scrape-front/   # Web application (React + TypeScript + Vite)
└── kan-scrape-back/    # API and backend services (FastAPI + Python)
```

## Local development

### Frontend

```bash
cd kan-scrape-front
pnpm install
pnpm dev
```

Available commands:

```bash
pnpm build
pnpm lint
pnpm preview
```

### Backend

```bash
cd kan-scrape-back
uv sync
uv run uvicorn app.main:app --reload
```

Available commands:

```bash
uv run pytest
uv run ruff check .
```

See [kan-scrape-back/README.md](./kan-scrape-back/README.md) for details.

## Project status

Frontend and backend scaffolds are in place. Scrapers are not wired yet — `/api/events` returns an empty list.

## Project documentation

- [Design system](./DESIGN.md)
- [Agent instructions](./AGENTS.md)
- [Contributing](./CONTRIBUTING.md)

## License

This project is distributed under the [MIT License](./LICENSE).
