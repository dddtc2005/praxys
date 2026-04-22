# Frontend Design System

Aligned with the **Praxys Brand Guideline v1.0** (`docs/brand/index.html`) — the interactive guide is the authoritative visual source. This doc translates it into implementation rules for `web/src/`.

If the code in `web/src/index.css` diverges from this, the brand guide wins and the code is pending an update; items still in transition are marked **→ brand target**.

## Theme

- Light + dark themes via `.dark` class on `<html>`. Default stored preference is dark (the brand guide shows light as the print default; the product runs dark-first).
- Theme is 3-state (`light` | `dark` | `system`) via `useTheme`; toggle in the sidebar footer cycles Dark → Light → System.
- `localStorage` key: `praxys-theme` (legacy `trainsight-theme` dual-read for 90 days post-rebrand).
- An inline script in `index.html` prevents flash-of-wrong-theme on load.
- shadcn's CSS variable system (`--background`, `--card`, `--primary`, etc.) is the single source of truth for surface colors.

## Color system

Two-track palette — a single green carries *action*, cobalt is reserved for *reasoning* surfaces. The separation is deliberate: the user should see at a glance whether something is a signal to act or a signal to reflect.

| Role | Token | Usage |
|------|-------|-------|
| **Action** | `primary` (green) | Positive signals, active states, brand accent, go/follow-plan recommendations, positive deltas |
| **Reasoning** | `accent-cobalt` | "Why this recommendation", citations, science notes, methodology hints — anywhere the system explains itself |
| **Caution** | `accent-amber` | Warnings, threshold zones, caution signals |
| **Rest / high-intensity** | `accent-red` *(→ brand target: `rust`)* | Rest signals and high-intensity zones share a visual weight — "this costs you" |
| Surface | `background` / `card` | Paper tones — warm, slightly off-white in light; deep navy in dark |
| Text | `foreground` / `muted-foreground` | Primary + secondary text |

**Rule:** never use raw hex in components. Use CSS variables, Tailwind color utilities, or the `chartColors` constants from `@/lib/chart-theme.ts`.

**Deprecated (do not use in new code):** `accent-blue`, `accent-purple`. The brand guide consolidates the palette; blue's informational role moved to cobalt when it's reasoning, or to `muted-foreground` when it's just metadata. Existing usages should migrate as components are touched.

## Typography

- **Body / UI / headings:** currently DM Sans (`--font-sans`). **→ brand target: Geist** (to be swapped across `index.html` font preconnects and `--font-sans`).
- **Data numbers:** `.font-data` class — JetBrains Mono, `tabular-nums`, `font-feature-settings: 'tnum' 1, 'zero' 1`. Use for **every** numeric value: metrics, dates, percentages, chart labels. Tabular digits matter because column alignment is the point.
- **Chinese:** body uses Noto Sans SC (via the `--font-sans` fallback chain and explicit `.font-sc` class); quotes / display uses Noto Serif SC (`.font-serif-sc` in the brand guide, should be added to `index.css`).
- **Section labels:** `text-xs font-semibold uppercase tracking-wider text-muted-foreground` (JetBrains Mono also acceptable per brand guide for eyebrow labels).
- **Headings:** same family as body.

## Bilingual rules

Surface purpose determines language strategy — never always-both by default.

| Context | Strategy | Example |
|---------|----------|---------|
| Brand moments | **Always both** | Hero, App Store splash, brand posters — EN + 中文 together |
| Product chrome | **Locale only** | Sidebar, page headers, toasts, onboarding — respect user's selected locale |
| Marketing copy | **Primary with subtitle** | One language primary, the other as a smaller subtitle |

Detection: `LocaleContext` + `detectBrowserLocale`. Stored preference overrides browser.

## Wordmark & mark

- **Wordmark:** `Pra` + `x` + `ys`. The `x` uses the primary green accent color; all other letters use `foreground`. Geist weight 500, letter-spacing `-0.055em` at display size.
- **Mark:** a stylized race flag — cobalt pole + green flag with inward-pinched trailing edge. Defined on a 48×48 grid; scales from a 16px favicon to hero marketing without re-drawing. SVG assets in `public/logos/`; construction and clear-space rules in `docs/brand/index.html` § II.
- **Full form:** "Praxys Endurance" — used where discovery needs the category signal (App Store, marketing headers, cold introductions). Short form "Praxys" elsewhere.

## Component patterns (shadcn/ui)

| Pattern | Component |
|---------|-----------|
| Page sections | `Card` with `CardHeader` + `CardContent` |
| Loading states | `Skeleton` matching the shape of content (never "Loading..." text) |
| Error states | `Alert variant="destructive"` |
| Warnings | `Alert` with amber accent styling |
| Editing forms | `Dialog` (modal overlay) |
| Expandable sections | `Collapsible` |
| Data tables | `Table` / `TableHeader` / `TableBody` / `TableRow` / `TableCell` |
| Dropdowns | `Select` (never raw `<select>`) |
| Buttons | `Button` with variants (never raw `<button>`) |
| Form fields | `Input` + `Label` (never raw `<input>`) |
| Status indicators | `Badge` with severity-based variants |
| Progress bars | `Progress` |
| Navigation | `Sidebar` (collapsible, sheet drawer on mobile) |

### The Science Note

The reasoning surface. Used by the `ScienceNote` component to answer "why did the system recommend this?" — plan rationale, metric explanations, citation of the underlying theory.

Visual spec (brand guide § V):
- Cobalt tint background: `bg-[color-mix(in_oklab,var(--accent-cobalt)_5%,var(--card))]` (or the semantic class once tokenized).
- Cobalt-tinted border; solid cobalt 3px left border (the "reasoning rail").
- Eyebrow label in cobalt, uppercase, JetBrains Mono, wide tracking: *WHY THIS RECOMMENDATION* / *METHODOLOGY* / *CITATION*.
- Body in `foreground` text at normal weight.
- Dashed border separator above the citation block; citation in `muted-foreground` with italicized source titles.

Never use the cobalt-bordered note style for anything that isn't reasoning / methodology / citation. Don't tint user-actionable surfaces with cobalt.

## Chart conventions

- Import colors from `@/lib/chart-theme.ts` — single source of truth for chart colors.
- Tooltips use `bg-popover border-border text-popover-foreground rounded-lg shadow-xl`.
- Grid lines use `chartColors.grid`; axis ticks use `chartColors.tick` with `font-data`.
- All charts wrapped in a shadcn `Card`.
- Gradient stops reference `chartColors.*` constants (not raw hex).

## Mobile patterns

- Sidebar renders as a Sheet drawer on mobile (shadcn Sidebar with `collapsible="icon"`).
- Sticky mobile header with `SidebarTrigger` (hamburger menu).
- Content uses a responsive grid: `grid-cols-1 lg:grid-cols-2`.
- Cards stack vertically on mobile.
- Padding: `px-4 py-6 sm:px-6 lg:px-8`.

## Brand-alignment open items

Tracked here so they don't get lost. When picking up any of these, update this section and mark the brand-target line in the relevant table.

- [ ] Swap body font from DM Sans to Geist across `index.html` preconnects and `--font-sans`.
- [ ] Rename `--accent-red-val` → `--accent-rust-val` (and the semantic class) to match brand naming, or accept the rename as alias only.
- [ ] Remove `--accent-blue-val` / `--accent-purple-val` usages: migrate TSB/form displays to cobalt (if reasoning) or primary (if positive), move sleep/recovery off purple.
- [ ] Add the `.font-serif-sc` utility class for Chinese display/quote contexts.
- [ ] Verify all existing `ScienceNote` callers render with the cobalt-rail treatment from brand § V.
