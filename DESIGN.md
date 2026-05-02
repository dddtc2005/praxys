---
name: Praxys
description: Scientific training system for endurance runners — the Field Lab.
colors:
  paper: "oklch(0.975 0.008 85)"
  paper-warm: "oklch(0.955 0.012 85)"
  ink: "oklch(0.18 0.02 260)"
  ink-soft: "oklch(0.40 0.02 260)"
  ink-ghost: "oklch(0.60 0.015 260)"
  rule: "oklch(0.85 0.008 85)"
  rule-soft: "oklch(0.92 0.006 85)"
  card: "oklch(0.99 0.004 85)"
  primary: "oklch(0.55 0.16 155)"
  primary-ink: "oklch(0.35 0.14 155)"
  cobalt: "oklch(0.50 0.18 258)"
  amber: "oklch(0.72 0.15 75)"
  rust: "oklch(0.55 0.18 30)"
  paper-dark: "oklch(0.17 0.013 260)"
  paper-warm-dark: "oklch(0.20 0.014 260)"
  ink-dark: "oklch(0.96 0.006 260)"
  card-dark: "oklch(0.22 0.014 260)"
  primary-dark: "oklch(0.82 0.18 155)"
  cobalt-dark: "oklch(0.74 0.14 258)"
  amber-dark: "oklch(0.80 0.14 75)"
  rust-dark: "oklch(0.72 0.18 30)"
typography:
  display:
    fontFamily: "Geist Variable, DM Sans Variable, Noto Sans SC Variable, system-ui, sans-serif"
    fontSize: "clamp(2rem, 4vw, 3rem)"
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Geist Variable, DM Sans Variable, Noto Sans SC Variable, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Geist Variable, DM Sans Variable, Noto Sans SC Variable, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0"
  body:
    fontFamily: "Geist Variable, DM Sans Variable, Noto Sans SC Variable, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
  label:
    fontFamily: "JetBrains Mono Variable, Noto Sans SC Variable, ui-monospace, monospace"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.05em"
  data:
    fontFamily: "JetBrains Mono Variable, Noto Sans SC Variable, ui-monospace, monospace"
    fontSize: "inherit"
    fontWeight: "inherit"
    lineHeight: "inherit"
    fontFeature: "'tnum' 1, 'zero' 1"
rounded:
  sm: "0.375rem"
  md: "0.5rem"
  lg: "0.625rem"
  xl: "0.875rem"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "1rem"
  lg: "1.5rem"
  xl: "2rem"
  2xl: "3rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "0.5rem 1rem"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "{colors.primary-ink}"
    textColor: "{colors.paper}"
  button-ghost:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.md}"
    padding: "0.5rem 1rem"
  button-ghost-hover:
    backgroundColor: "{colors.rule-soft}"
    textColor: "{colors.ink}"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "1.5rem"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.75rem"
  input-focus:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
  badge-positive:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    padding: "0.125rem 0.5rem"
    typography: "{typography.label}"
  badge-caution:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.125rem 0.5rem"
    typography: "{typography.label}"
  badge-rest:
    backgroundColor: "{colors.rust}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    padding: "0.125rem 0.5rem"
    typography: "{typography.label}"
  science-note:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.md}"
    padding: "0.75rem 1rem"
    typography: "{typography.body}"
---

# Design System: Praxys

## 1. Overview

**Creative North Star: "The Field Lab"**

Praxys looks like a rigorous instrument that travels outdoors with you. Warm paper instead of clinical white. Precise typography instead of marketing flourish. Citations in the margins, not in a footer. The interface respects that the reader is a person making real decisions about real training, often in real sunlight, often with a sweaty thumb. It does not perform.

The system has two voices, separated by color: green carries action — *follow this plan, run today, this is your signal* — and cobalt carries reasoning — *this is why, this is the paper, this is the methodology*. The user always knows whether they are being told to *do* or being shown *why*. The two-track palette is the design system's central commitment; everything else flows from it.

What this is not: it is not a wearable-app neon dashboard, not a SaaS hero-metric template, not a Garmin-Connect data dump with a thousand tabs and no opinion. Praxys takes positions and shows its work; the visuals follow.

**Key Characteristics:**
- Warm paper surfaces (`oklch(0.975 0.008 85)`), never `#fff`. Light theme is the default — runners use this in sunlight.
- Two-track semantic palette: green for action, cobalt for reasoning. Amber for caution. Rust for rest and high-intensity ("this costs you").
- Tabular monospace numerals everywhere a number lives. Column alignment is the point.
- Flat-by-default surfaces; thin rules separate; elevation is a response to state, not ambient decoration.
- Bilingual (EN + 中文) is structural, with three explicit modes — never always-both by reflex.

## 2. Colors: The Two-Track Palette

A restrained five-color system: warm-paper neutrals plus four named role colors (primary, cobalt, amber, rust). Roles are *semantic*, not decorative — each color says what kind of message it is.

### Primary
- **Field Green** (`{colors.primary}` — light theme; `{colors.primary-dark}` — dark): the action color. Used for positive signals, active states, follow-the-plan recommendations, positive deltas, the brand wordmark's `x` accent. The single most loaded color in the system; it earns its weight by appearing only where action is implied.

### Secondary
- **Cobalt** (`{colors.cobalt}` — light; `{colors.cobalt-dark}` — dark): the reasoning color. Used wherever the system explains itself — the Praxys Coach receipt's banner and recommendation arrows, the `ScienceNote`'s expand-trigger, citation links, methodology eyebrows. Cobalt encodes reasoning through *color*, not through any specific rail or border geometry. The mark's flag pole is cobalt for this reason — the brand carries reasoning at its base.

### Tertiary
- **Amber** (`{colors.amber}`): caution. Threshold zones, warning states, "watch this" callouts.
- **Rust** (`{colors.rust}`): rest and high-intensity zones. The shared visual weight is intentional — both signals say *this costs you something*.

### Neutral
- **Paper** (`{colors.paper}`) and **Paper-warm** (`{colors.paper-warm}`): the warm-paper background — chroma-tinted toward an 85° hue, off-white, never `#fff`.
- **Card** (`{colors.card}`): the surface that floats on paper — slightly lighter, almost imperceptible, the second layer in a flat hierarchy.
- **Ink** (`{colors.ink}` / `ink-soft` / `ink-ghost`): foreground tones — three weights of cool-blue ink (260° hue), tinted slightly toward the brand's reasoning side.
- **Rule** and **Rule-soft** (`{colors.rule}` / `{colors.rule-soft}`): hairline borders that separate flat surfaces.

### Named Rules

**The Two-Track Rule.** Green means *act*; cobalt means *the system explaining itself*. Never blur them. A green ScienceNote is a bug. A cobalt CTA button is a bug. The user must be able to tell at a glance whether they are being told to do something or being shown why.

**The Warm Paper Rule.** Surfaces are tinted toward 85° hue at low chroma (≤0.012). Pure `#fff` and pure `#000` are forbidden — they are clinical and they punish the eye in real sunlight. Tint every neutral toward the brand's warm side.

**The Restraint Rule.** Primary green appears on ≤10% of any given screen. Its rarity is the point. Plastering green everywhere flattens its meaning into chrome, and the moment of action loses its signal.

**The Rust = Cost Rule.** Rust marks rest and high-intensity zones with the same color because both say *this costs you*. Don't give rest its own gentler color. Recovery is not a soft message; it is the system stopping you from breaking yourself.

## 3. Typography

**Display / Body Font:** Geist Variable (target — currently DM Sans Variable, transition pending in `web/src/index.css`).
**Data / Label Font:** JetBrains Mono Variable, with `font-variant-numeric: tabular-nums` and `font-feature-settings: 'tnum' 1, 'zero' 1`.
**Chinese:** Noto Sans SC Variable for body; Noto Serif SC for display and pull-quotes (`.font-serif-sc` utility pending — see `design-system.md` open items).

**Character:** A neutral, technical sans for prose paired with a tabular monospace for every number. The pairing is deliberate: Geist's restraint lets the numbers carry the rhythm, and JetBrains Mono's tabular figures make columns of data align without effort. Together they read like a working notebook, not marketing copy.

### Hierarchy

- **Display** (Geist 500, `clamp(2rem, 4vw, 3rem)`, line-height 1.1, letter-spacing -0.02em): brand moments, the wordmark, hero numbers on the Today signal hero. Used sparingly.
- **Headline** (Geist 600, 1.5rem, line-height 1.2): page titles ("Today", "Goal", "History").
- **Title** (Geist 600, 1.125rem, line-height 1.3): card headers, section titles inside pages.
- **Body** (Geist 400, 0.875rem, line-height 1.5): the working text. Cap line length at 65–75ch for prose blocks (rare in this product — most surfaces are dashboards).
- **Label** (JetBrains Mono 600, 0.6875rem, uppercase, letter-spacing 0.05em): section eyebrow labels, table headers, ScienceNote section markers ("WHY THIS RECOMMENDATION", "METHODOLOGY", "CITATION").
- **Data** (JetBrains Mono, inherits size/weight, `tabular-nums`): every numeric value. Metrics, dates, percentages, chart labels. This is non-negotiable — applied via the `.font-data` utility class.

### Named Rules

**The Tabular Numerals Rule.** Every digit on every screen renders in JetBrains Mono with `tabular-nums`. Mixing proportional and tabular numerals across a column is a bug. If a number lives in a list, table, chart label, KPI, or even inline in body prose where alignment matters — it gets `.font-data`.

**The Right Word Rule.** Use the technical term — *threshold*, *CTL*, *polarized*, *RPE*, *zone 2* — and explain it inline once, the first time it appears in a flow. Don't dumb it down to "your fitness number." Don't hover-tooltip it either; the explanation belongs in a `ScienceNote`, not behind a question mark.

**The Section Label Rule.** Section labels are JetBrains Mono, uppercase, tracking 0.05em, in `ink-soft` or `muted-foreground`. They are eyebrows above content blocks. Not body, not headings, not buttons.

## 4. Elevation

Praxys is **flat by default**. Cards sit on warm paper with hairline `rule-soft` borders. Surfaces don't float ambiently. Depth is communicated through tonal layering (`paper` → `card`) and rule lines, not shadows.

Shadows appear only as a **response to state**: hover on an interactive surface, focus on an input, the lift of a `Dialog` or `DropdownMenu` over the page. The flat default makes the lifted state mean something — when a popover appears, you notice it. If everything floats, nothing floats.

The miniapp doubles down on this: WeChat Skyline's shadow rendering is patchy, so cards there are pure tonal layering plus a 1rpx border on light theme, no shadows at all. The web should match this discipline; if a web card shows an ambient drop shadow at rest, that's drift toward the SaaS dashboard cliché.

### Named Rules

**The Flat-By-Default Rule.** Surfaces are flat at rest. Shadows are responses, not decoration. If you can't articulate which user state caused the shadow, remove it.

**The Rule-Line Rule.** Use `rule-soft` (hairline) to separate flat surfaces. Use `rule` only where the boundary needs to be unmistakable (table header → body, sticky nav bottom). Heavier borders read as cards-within-cards, which is the absolute-banned nested-card pattern in disguise.

## 5. Components

### Buttons

- **Primary** (`button-primary`): Field Green background, paper text, `rounded.md`. The action button. Hover deepens to `primary-ink`. Used sparingly — one primary button per surface, ideally one per page.
- **Ghost** (`button-ghost`): no background, `ink-soft` text, hover fills with `rule-soft`. The default for navigation links and secondary actions. Inputs the most common "click here" affordance.
- **Destructive**: rust background only for irreversible destructive actions (delete account, disconnect platform, abandon goal). Not for "discard changes" — that's ghost.

**The One Primary Rule.** A surface has at most one primary green button. Two competing primaries means the user has to choose between two action paths, and that's a UX failure dressed as visual variety.

### Cards (`card`)

- **Shape**: `rounded.lg` corners. Background `card`, sitting on the `paper` page.
- **Border**: 1px `rule-soft` hairline on light theme; on dark theme the `card` ↔ `paper` lightness gap does the separation work and the border can drop to nothing.
- **Padding**: `lg` (1.5rem) interior, scales down to `md` on dense data tables.
- **No nested cards.** A card inside a card is always wrong; use a horizontal rule (`border-t border-rule-soft`) to subdivide instead.

### Inputs (`input`)

- **Default**: `card` background, `rounded.md`, 1px `rule` border, `ink` text. Caret in `primary` (the brand sneaks in here, where you're acting on the field).
- **Focus**: border shifts to `primary` (no glow, no offset shadow ring). The shift itself is the affordance.
- **Error**: border shifts to `destructive`, accompanying error text in `destructive` below the input — never inline-replacing the placeholder.

### Badges

Three semantic variants — positive (green), caution (amber), rest/destructive (rust). Tiny rounded-sm pills with JetBrains Mono uppercase labels. Used for signal indicators ("Go", "Modify", "Rest"), not for decorative tagging.

### The reasoning surfaces

Two complementary patterns carry the system's "show the work" commitment. They serve different jobs and shouldn't be conflated.

**1. The `ScienceNote` (inline progressive disclosure).** A small "How this is calculated" affordance that lives at the bottom of metric cards (`RecoveryPanel`, `FitnessFatigueChart`, `FormSparkline`, `Goal` predictions). Default-collapsed; cobalt trigger signals reasoning is available; expanding reveals the methodology paragraph and a citation link.

- **Trigger**: tiny `text-accent-cobalt` button — the cobalt color is the only signal that this is a reasoning surface.
- **Body** (when expanded): `text-muted-foreground`, small (10–12px), leading-relaxed.
- **Citation link**: `text-accent-cobalt` with underline on hover.

The component is deliberately *minimal* — it adds reasoning depth without claiming vertical space. Don't dress it up with eyebrows, banners, or rails; that's a different surface (the receipt).

**2. The `coach-receipt` (narrative reasoning surface).** A standalone block where reasoning *is* the content (Praxys Coach daily brief, currently). Square corners, thin border, flat cobalt banner header with brand attribution + timestamp, body with headline + findings + dashed rule + numbered recommendations, muted footer with theory citations.

- **Banner**: solid `var(--accent-cobalt-val)` background, `var(--card)` text. Mono-caps brand mark on the left, mono timestamp on the right.
- **Body**: `var(--card)` background, headline + structured lists. Findings get type-coded mono tags (`[+]` positive, `[!]` warning, `[·]` neutral); recommendations get cobalt `→` arrows.
- **Foot**: `var(--muted)` background, mono small-caps theory attribution, right-aligned.
- **Pattern**: full-bleed within its grid cell. Reusable on Goal / History / Settings whenever an LLM insight or narrative explanation is the primary content.

**The Reasoning Color Rule.** Cobalt encodes "the system explaining itself" through *color* — banner backgrounds, eyebrow labels, citation links, recommendation arrows, ScienceNote triggers. It does *not* encode reasoning through a 3px-left-rail-on-rounded-card geometry; that specific shape became the AI-generated-UI cliché in 2025–26 and is now retired. If you reach for a thicker-than-1px cobalt left border, you're recreating the exact pattern this rule was built to push back against. Use the receipt's banner header instead, or the ScienceNote's color-only treatment.

### Navigation

- **Web** (`AppSidebar`): collapsible sidebar on desktop, sheet drawer on mobile. Sticky mobile header with `SidebarTrigger` (hamburger). Active route shown by `primary` left-edge indicator and bolder weight, not background fill — the sidebar stays calm.
- **Miniapp**: custom Skyline `nav-bar` (top) + custom tab bar (bottom), both painted with the same paper / ink tokens. The mini program is mobile-first, so navigation density is higher than the web's sidebar.

### Charts (signature: trend, distribution, fitness-fatigue)

- All charts wrap in a `Card`.
- Colors come from `chartColors` constants in `web/src/lib/chart-theme.ts` — *never* `chart-1`/`chart-2` named generically in component code. Charts encode meaning in color: `fitness` → green, `fatigue` → rust/red, `form` → cobalt, `threshold` → amber, `projection` → ghost cobalt. Themed swap between light and dark.
- Tooltips: `bg-popover`, `border-border`, `rounded-lg`, soft shadow (this is a state response — see Elevation).
- Grid lines `chartColors.grid` (low contrast); axis ticks in JetBrains Mono with `font-data`.

## 6. Do's and Don'ts

### Do:
- **Do** use `oklch()` for color tokens; the project has an OKLCH-only doctrine. Hex appears only where downstream tools require it (chart libraries, miniapp WXSS).
- **Do** apply `.font-data` to every numeric value, including digits embedded inside body prose ("you ran <span class='font-data'>8.4 km</span>").
- **Do** encode reasoning through cobalt *color* — banner headers, eyebrow labels, citation links, recommendation arrows, ScienceNote triggers. Use the `coach-receipt` for narrative reasoning, the minimal `ScienceNote` for inline disclosure.
- **Do** keep one primary green button per surface. Other actions are ghost.
- **Do** treat the light theme as the default; design for outdoor / sunlight legibility first.
- **Do** codify bilingual treatment by surface purpose: brand surfaces always-both, product chrome locale-only, marketing primary-with-subtitle. Bake it into component variants.
- **Do** lead every dashboard screen with an interpretation — a signal, a verdict, a recommendation. The data underneath supports the interpretation; it does not replace it.

### Don't:
- **Don't** use `#fff` or `#000` anywhere. Surfaces tint toward 85° hue (warm paper); foregrounds tint toward 260° hue (cool ink).
- **Don't** use `border-left` greater than 1px as a colored accent on cards, list items, callouts, or alerts. *No exceptions* — the cobalt-3px-rail-on-rounded-card pattern that previously carved out the ScienceNote has been retired. It became the AI-generated-UI cliché. Reasoning is encoded through cobalt *color* (`coach-receipt` banner, ScienceNote trigger), never through rail-card geometry. (Impeccable absolute ban.)
- **Don't** drift toward the **crypto / wearable neon-on-black** aesthetic. No glassmorphism, no animated gradients, no neon-on-black hero surfaces. Light theme is the default for a reason.
- **Don't** assemble a **generic SaaS hero-metric template** — big number, small label, four supporting stats, gradient accent. Every metric on Praxys earns its position via interpretation, not by being big.
- **Don't** ship a **Garmin-Connect data dump** — endless tabs, no narrative, no opinion, no methodology. Charts without a takeaway are failures.
- **Don't** nest cards. A card inside a card is always wrong; use a horizontal rule, a section label, or a flat row instead.
- **Don't** use Strava-style social validation tropes (kudos, achievement explosions, segment leaderboard chrome). Praxys is self-coached, not socially validated.
- **Don't** use gradient text (`background-clip: text` + gradient) for headings. Decorative, never meaningful. Emphasis is by weight or size.
- **Don't** apply ambient drop shadows on cards at rest. Elevation is a response to state. If you can't say which user state caused the shadow, remove it.
- **Don't** use `--accent-blue` or `--accent-purple` in new code — they are deprecated. Reasoning roles move to cobalt; positive deltas to primary; metadata to `muted-foreground`.
- **Don't** show always-both EN + 中文 by reflex on product chrome. Surface purpose decides; the user's locale wins for app UI.
