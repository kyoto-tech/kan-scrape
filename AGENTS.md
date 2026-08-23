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
- Event sources: seed fixture (dev only — `SEED_EVENTS=true` or `DEBUG=true`), Meetup iCal, Doorkeeper / Connpass (optional API keys)
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
# AGENTS.md

## Repository

`kan-scrape` is a monorepo for the Kyoto Tech Meetup community experience. The frontend currently lives in `kan-scrape-front/`; backend services will be added under a separate root directory when implemented.

The current product challenge is intentionally narrow: the frontend interface must expose one primary control only, with the title `Kyoto Meetup Finder` above it. The user clicks the button once to start speaking and clicks it again to stop and send the captured request to the backend. When the backend finishes thinking, its result is rendered on the same page.

Read [`DESIGN.md`](./DESIGN.md) before changing visual tokens, typography, colors, spacing, responsive behavior, or interaction states. Read [`CONTRIBUTING.md`](./CONTRIBUTING.md) before contributing.

## Current stack

### Frontend

- React 19
- TypeScript 6
- Vite 8
- pnpm

The frontend is self-contained in `kan-scrape-front/`. Run frontend commands from that directory until shared root tooling is introduced.

### Backend

The backend is not implemented yet. Do not create backend conventions or dependencies until the backend stack is chosen and documented.

## Repository conventions

- Keep frontend code inside `kan-scrape-front/`.
- Add backend code in a clearly named root-level directory such as `kan-scrape-back/` once it exists.
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
- Keep the initial surface to one visible button. Do not add navigation, forms, dashboards, decorative cards, or secondary actions.
- Keep the viewport locked to `100dvh` with no page scroll.
- The button must be a two-state toggle: first click starts listening, second click stops and submits. It needs `aria-pressed`, an accessible label, focus-visible styling, and a visible listening state.
- Use GSAP for the initial entrance only: the title and description fade down from above, then the button fades in without zooming. Respect `prefers-reduced-motion` and clean up the GSAP context on unmount.
- Keep backend communication behind a small request boundary; the current frontend endpoint is `POST /api/scrape` with `{ message }` and a `{ result }` response.
- Until the backend exists, use the local Kyoto meetup fixture in `App.tsx` to demonstrate the result state. Keep the fixture clearly replaceable by the backend response.
- Use Sonner mounted at `top-right` with a fixed light theme for success, error, and recoverable input feedback. Do not render persistent error copy under the primary button.
- Avoid em dashes, all-uppercase interface copy, and decorative letter spacing. Use normal sentence case and natural tracking.
- While a search is in flight, disable the button and show the `Searching…` label with an animated loader.
- While listening, use the microphone's live audio level to make the button indicator react subtly. Stop the animation, microphone tracks, and audio context when listening ends.
- Do not add a dependency for a small utility unless repeated use justifies it.

## Verification

From `kan-scrape-front/`:

```bash
pnpm install
pnpm lint
pnpm build
```

For visual changes, verify narrow mobile, tablet, and desktop layouts, including long labels, focus-visible states, and reduced motion.

## Change boundaries

- Do not stage, commit, push, amend, rebase, or otherwise mutate Git history unless explicitly requested.
- Do not modify files outside this repository for a task scoped to `kan-scrape`.
- Do not replace existing APIs or visual tokens without checking their usage.
- Contributions are restricted to members of the `kyoto-tech` GitHub organization; see [`CONTRIBUTING.md`](./CONTRIBUTING.md).
