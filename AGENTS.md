# AGENTS.md

## Repository

`kan-scrape` is a monorepo for the Kyoto Tech Meetup community experience. The frontend lives in `kan-scrape-front/`, the backend (FastAPI) in `kan-scrape-back/`.

Read [`DESIGN.md`](./DESIGN.md) before changing visual tokens, typography, colors, spacing, responsive behavior, or interaction states. Read [`CONTRIBUTING.md`](./CONTRIBUTING.md) before contributing.

## Current stack

### Frontend

- React 19
- TypeScript 6
- Vite 8
- pnpm

The frontend is self-contained in `kan-scrape-front/`. Run frontend commands from that directory until shared root tooling is introduced.

### Backend

- Python 3.12, FastAPI, uv (deps + lockfile), ruff, pytest
- Event sources: seed fixture (always on), Meetup iCal, Doorkeeper / Connpass (optional API keys)
- Matching + pitch: Mistral (`MISTRAL_API_KEY`, function calling); STT: local faster-whisper (GPU); TTS: edge-tts
- Spec: [`docs/handoff-backend.md`](./docs/handoff-backend.md), STT: [`docs/handoff-stt.md`](./docs/handoff-stt.md); endpoints in [`kan-scrape-back/README.md`](./kan-scrape-back/README.md)

Run from `kan-scrape-back/`:

```bash
uv sync
cp .env.example .env            # add MISTRAL_API_KEY for /match (app boots without it: random mode only)
uv run uvicorn app.main:app --reload   # http://localhost:8000 — docs at /docs, API under /api
uv run pytest -q                # offline, no network/keys needed
uv run ruff check . && uv run ruff format --check .
```

Quick check: `curl -s -X POST localhost:8000/api/events/refresh` then `curl -s 'localhost:8000/api/events?limit=3'`.

## Repository conventions

- Keep frontend code inside `kan-scrape-front/`.
- Keep backend code inside `kan-scrape-back/`.
- Keep app-specific package files and lockfile ownership clear.
- Prefer small, focused changes and preserve unrelated work.
- Update documentation when a shared architecture, token, or workflow changes.
- Do not add root workspace tooling until it serves at least two active packages.

## Frontend conventions

- Keep React components and their styles close to their usage.
- Use semantic HTML and accessible keyboard interactions.
- Preserve `className` escape hatches when creating reusable components.
- Use finite TypeScript unions for public visual variants.
- Use the tokens and patterns in [`DESIGN.md`](./DESIGN.md); do not introduce arbitrary colors, fonts, spacing, radii, or animation timings.
- Support English and Japanese content without hard-coded widths or fragile truncation.
- Do not add a dependency for a small utility unless repeated use justifies it.

## Verification

From `kan-scrape-front/`:

```bash
pnpm install
pnpm lint
pnpm build
```

From `kan-scrape-back/`: `uv run pytest -q && uv run ruff check .`

For visual changes, verify narrow mobile, tablet, and desktop layouts, including long labels, focus-visible states, and reduced motion.

## Change boundaries

- Do not stage, commit, push, amend, rebase, or otherwise mutate Git history unless explicitly requested.
- Do not modify files outside this repository for a task scoped to `kan-scrape`.
- Do not replace existing APIs or visual tokens without checking their usage.
- Contributions are restricted to members of the `kyoto-tech` GitHub organization; see [`CONTRIBUTING.md`](./CONTRIBUTING.md).
