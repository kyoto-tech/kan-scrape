# Kan Scrape Design System

Community-first, warm, practical, and easy to scan.

This design reference is based on the public Kyoto Tech Meetup website: <https://kyototechmeetup.com/>. It is intended for event discovery, community links, member feeds, calendars, and bilingual English/Japanese content.

## Visual direction

- Light canvas with white cards and quiet slate surfaces.
- Terracotta accent for event dates, links, icon accents, selected states, and hover borders.
- Dark slate for primary actions and utility surfaces.
- Friendly rounded controls and cards without excessive softness.
- Compact event metadata with clear date, venue, RSVP, and action hierarchy.
- Responsive layouts that support short mobile labels and longer English/Japanese content.

## Current interface challenge

The initial interface is deliberately only one action: a single toggle-to-speak button centered on the viewport, with the title `Kyoto Meetup Finder` and one short description above it. There is no navigation, form, dashboard, decorative card, or secondary CTA.

Interaction sequence:

1. Click the button once to start capture.
2. Keep speaking while the button is in its listening state.
3. Click the button again to stop capture and send `POST /api/scrape` with `{ "message": "..." }`.
4. Keep the same page and show the backend's `{ "result": "..." }` response when processing finishes.

The button is the only initial visible control. Its label and state may change between `Start speaking`, `Listening…`, `Stop and search`, `Searching…`, and a recoverable error. A result may appear after submission. An empty transcript must not show a persistent instructional message; the user can simply try again.

The content container is capped at 768px (`48rem`). Below 640px it uses the full available width with 16px horizontal padding, and the button fills that mobile width.

The page occupies exactly the viewport using `100dvh` and does not scroll. On first load, GSAP reveals the title first, then the description, then the button. The title and description use a long top fade-in; the button uses only a distinctive fade-in from a brief blur state and must not zoom or scale during entrance. The timeline skips animation when `prefers-reduced-motion: reduce` is active.

## Colors

### Brand

| Token | Value | Use |
| --- | --- | --- |
| `accent` | `#B83230` | Event emphasis, links, icons, selected accents |
| `accent-dark` | `#8F2624` | Hover and pressed accent state |
| `accent-soft` | `#FFF7ED` | Warm icon and highlight surface |
| `dark-surface` | `#020618` | Primary action and utility surface |

### Neutrals

The source site uses Tailwind Slate and Stone values:

| Token | Value | Use |
| --- | --- | --- |
| `slate-950` | `oklch(12.9% .042 264.695)` | Dark actions and utility surfaces |
| `slate-900` | `oklch(20.8% .042 265.755)` | Headings and primary action text |
| `slate-700` | `oklch(37.2% .044 257.287)` | Strong secondary text and focus outline |
| `slate-600` | `oklch(44.6% .043 257.281)` | Body and metadata text |
| `slate-500` | `oklch(55.4% .046 257.417)` | Muted labels and timestamps |
| `slate-200` | `oklch(92.9% .013 255.508)` | Default border |
| `slate-100` | `oklch(96.8% .007 247.896)` | Quiet border and controls |
| `slate-50` | `oklch(98.4% .003 247.858)` | Quiet card surface |
| `stone-950` | `oklch(14.7% .004 49.25)` | Footer and warm dark surface |
| `white` | `#FFFFFF` | Page, card, and control background |

### Semantic colors

| Token | Foreground | Background | Use |
| --- | --- | --- | --- |
| `success` | `oklch(69.6% .17 162.48)` | `#ECFDF5` | Live or confirmed event status |
| `warning` | `oklch(47.3% .137 46.201)` | `oklch(96.2% .059 95.617)` | Pending or caution state |
| `error` | `#B83230` | `#FEF2F2` | Validation and destructive feedback |

Color must never be the only semantic signal. Pair status with text and, when useful, an icon.

## Typography

The reference site uses one sans-serif family for headings and body content:

```css
--font-sans: Inter, "Helvetica Neue", Arial, sans-serif;
--font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
  "Liberation Mono", "Courier New", monospace;
```

Use the fixed site scale for new components:

| Token | Size | Line height | Use |
| --- | ---: | ---: | --- |
| `text-xs` | 12px | 1.333 | Metadata, dates, compact labels |
| `text-sm` | 14px | 1.429 | Navigation, event metadata, secondary copy |
| `text-base` | 16px | 1.5 | Body, card titles, controls |
| `text-lg` | 18px | 1.556 | Card and section headings |
| `text-xl` | 20px | 1.4 | Event titles |
| `text-2xl` | 24px | 1.333 | Section and feed headings |
| `text-3xl` | 30px | 1.2 | Main section headings |
| `text-4xl` | 36px | 1.111 | Large page headings |
| `text-5xl` | 48px | 1 | Large desktop headings |
| `text-6xl` | 60px | 1 | Wide desktop display |

Weights used by the source are 500, 600, and 700. Avoid italic display headings.

## Spacing

Use a 4px base unit (`--spacing: 0.25rem`). Common values:

| Token | Value |
| --- | ---: |
| `space-1` | 4px |
| `space-2` | 8px |
| `space-3` | 12px |
| `space-4` | 16px |
| `space-5` | 20px |
| `space-6` | 24px |
| `space-8` | 32px |
| `space-12` | 48px |
| `space-16` | 64px |
| `space-20` | 80px |

Observed patterns:

- Navigation shell: 12px mobile padding, 16px from the `sm` breakpoint.
- Card padding: usually 12px, 16px, 20px, or 24px.
- Inline groups: 4px, 8px, 12px, or 16px gaps.
- Section spacing: 48–96px depending on viewport.
- Touch targets: minimum 44px where practical.

## Layout and responsive behavior

### Breakpoints

| Token | Width | Behavior |
| --- | ---: | --- |
| `sm` | 640px | Larger mobile and compact desktop transition |
| `md` | 768px | Tablet and two-column opportunities |
| `lg` | 1024px | Desktop navigation and grid |
| `xl` | 1280px | Wide layout |
| `2xl` | 1536px | Maximum wide-screen layout |

Use `max-w-6xl` (72rem / 1152px) for the main navigation shell and `max-w-5xl` (64rem / 1024px) for major content sections. Keep content centered and prevent uncontrolled growth on wide screens.

### Patterns

- Floating navigation: fixed, full-width shell with a centered rounded pill, light border, and soft shadow.
- Event feature: one clear primary RSVP action, with date, location, and status grouped nearby.
- Community links: cards collapse to one column on mobile and use multi-column spans on larger screens.
- Calendar: event rows remain scannable with date, title, venue, RSVP count, map, and RSVP action.
- Member feeds: horizontal cards may scroll on narrow screens; preserve a minimum card width around 280px.
- Footer: dark stone surface with wrapping social links.

## Shape, borders, and elevation

| Token | Value | Use |
| --- | --- | --- |
| `radius-md` | 6px | Compact controls |
| `radius-lg` | 8px | Inputs and small surfaces |
| `radius-xl` | 12px | Cards and menus |
| `radius-2xl` | 16px | Primary cards and panels |
| `radius-full` | 9999px | Pills, avatars, circular controls |

Use `1px solid slate-200` for default borders and `1px solid accent` for selected or hovered community surfaces. Use shadows mainly for floating navigation and elevated surfaces:

```css
--shadow-nav: 0 10px 15px -3px #0000001a, 0 4px 6px -4px #0000001a;
--shadow-xl: 0 20px 25px -5px #0000001a, 0 8px 10px -6px #0000001a;
```

## Motion and states

The source uses a standard 150ms transition with `cubic-bezier(.4, 0, .2, 1)` and occasional 300ms image transitions. Use restrained hover feedback: color, border, opacity, a maximum 2px lift, or a subtle image scale. Respect `prefers-reduced-motion`.

Every interactive component should define default, hover, focus-visible, active, disabled, loading, error, and success behavior where applicable. Focus must be visible, and keyboard behavior must remain correct.

The primary button uses a restrained 2px hover lift, a terracotta active/listening state, and a soft terracotta focus halo. Its listening indicator remains static during silence and scales only from the measured microphone signal after a small noise gate. Respect `prefers-reduced-motion`.

While the request is in flight, the button is disabled, uses a slate searching surface, displays a small circular loader, and reads `Searching…`. Until the backend is connected, the page uses a local fixture containing Kyoto meetup events to preview the final result presentation.

While listening, the button indicator uses the microphone's live audio level. Silence keeps the dot at its resting scale; speech increases it subtly up to a restrained maximum. The microphone stream and audio context must be released as soon as listening stops.

## Toast feedback

Use Sonner with a single `<Toaster position="top-right" theme="light" />`. Success, error, and empty-input feedback appear as toasts rather than persistent text below the button. Toast text is left aligned and the icon sits at the top-left of the toast content. Match the system with light surfaces, dark slate text, terracotta error accents, restrained motion, and short descriptions.

## Copy and typography rules

- Avoid em dashes. Use commas, periods, colons, or parentheses instead.
- Avoid all-uppercase interface copy. Use sentence case for headings, labels, statuses, categories, and toast titles.
- Avoid decorative letter spacing. Use the natural tracking of the selected font.

## Result presentation

The demo result is a compact, scroll-safe event panel. It contains a small uppercase result heading, event count, and cards with date, category, title, venue, time, and a one-line description. The panel is secondary to the primary action and may appear only after a search completes.

## Component guidance

- Use semantic HTML and keep semantic element choice independent from visual size.
- Use `className` as a consumer escape hatch, appended after defaults.
- Keep public variants as finite TypeScript unions.
- Keep event cards, buttons, links, chips, and navigation actions pill-shaped only when their role supports it.
- Keep metadata visually secondary to event names and primary actions.
- Support both English and Japanese text without fixed-width assumptions or forced truncation.
- Avoid gradients, gratuitous illustration, giant rounded containers, and dark-mode substitutions unless a product requirement calls for them.

## Implementation tokens

Shared tokens belong in `src/index.css` when the frontend is implemented. Keep this document and those variables synchronized.
