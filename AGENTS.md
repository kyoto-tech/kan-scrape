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
- Use GSAP for the initial entrance only: the title fades down from above and the button zooms in. Respect `prefers-reduced-motion` and clean up the GSAP context on unmount.
- Keep backend communication behind a small request boundary; the current frontend endpoint is `POST /api/scrape` with `{ message }` and a `{ result }` response.
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
