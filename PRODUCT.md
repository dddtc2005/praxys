# Product

## Register

product

## Users

Endurance runners across the full spectrum — from the casual 3 hr/week jogger to the serious 15 hr/week trail / ultra athlete. Self-coached. Multi-user (each account is one athlete; coaches are not the primary persona).

The job to be done: **interpret my training data into a clear next action**. Users don't want another data viewer; they want a system that takes a position. Today's signal (go / modify / rest), this week's diagnosis, where I'm trending, what to do about my goal.

Physical context matters and shapes design choices: the app is opened outdoors, on a phone, often pre- or post-run. Bright sunlight, dawn light, sweaty hands, distracted attention. Design for that, not for the comfortable office desk.

The mini program (`miniapp/`) serves the WeChat-native CN audience; it's a view + manage companion to the web app, not a thin port. Feature parity for daily-use surfaces (signal, training, goal, sync, settings); registration + platform connection happens once on praxys.run.

## Product Purpose

Scientific training system for endurance runners. Praxys ingests multi-source data — Garmin, Stryd, Oura Ring — and produces interpreted, methodology-cited outputs. The user picks their **training base** (power, heart rate, or pace); the system computes thresholds (CP, LTHR, threshold pace), zones, and load against whichever modality fits their gear and preference. Power is supported well because Stryd / Garmin power exists, but it's one option of three, not a prerequisite.

- **Today's signal:** go / modify / rest, grounded in HRV, sleep, resting HR, recent load.
- **Training diagnosis:** zone distribution, CP / threshold trend, fitness-fatigue balance, suggestions.
- **AI training plans:** 4-week plans regenerated against current state and goals.
- **Race forecast:** prediction + goal feasibility, with the gap quantified.
- **Configurable science:** four-pillar theory framework (load model, recovery, race prediction, zones); users can swap theories.

Success looks like: the user trusts a one-line signal in the morning, understands why when they want to, and trains better over a season because of it. Every metric on screen has a verifiable source.

## Brand Personality

**Default voice: sharp, opinionated, scientific.** The system holds research-grounded views and shows its work. It is willing to disagree with the user's instinct and cite the paper that says so. It does not hedge for politeness. It uses the right technical word — *threshold*, *CTL*, *polarized* — and explains it inline, once, the first time it appears.

**Adaptive modulation:** when training data indicates the user is currently casual (low weekly volume, sparse history, no race goal set), tone softens toward **considered, honest, encouraging** — but the methodology never leaves. The casual runner gets warmth and an invitation to learn; the serious runner gets directness. Same truth underneath, calibrated delivery.

Three-word anchor: **sharp · opinionated · scientific**, with adaptive **warmth** for casual-detected users.

What the personality is *not*: cheerleader (Strava-style kudos), lifestyle-coach (Apple Fitness rings energy), neutral data viewer (Garmin Connect tabs).

## Anti-references

- **Crypto / wearable neon-on-black dark UI.** Glassmorphism, neon-on-black, animated gradients, "performance" as aesthetic. Trains the AI-slop reflex; signals "fitness tech demo" not "instrument."
- **Generic SaaS hero-metric template.** Big number, small label, four supporting stats, gradient accent. The default chart-it-and-call-it-done layout. Already in impeccable's absolute bans; flagged again here because dashboards drift toward it by gravity.
- **Garmin Connect** style data-dump with no opinion. Endless tabs, no narrative, no methodology, no synthesis. Praxys's job is the opposite — interpret first, expose the data underneath.

## Design Principles

1. **Interpret, don't just display.** Every screen takes a position — a signal, a recommendation, a trend call, a feasibility verdict. A chart without a takeaway is a failure mode, not a deliverable. The user came for the answer; the data is supporting evidence.

2. **Show the work.** Cite the science in-context, not in a footer. The `ScienceNote` reasoning surface is a first-class citizen, not a tooltip. Casual users verify their trust this way; serious users learn from it.

3. **Two-track semantics: action vs reasoning.** Green (`primary`) means signals to act, positive deltas, follow-the-plan recommendations. Cobalt (`accent-cobalt`) means the system explaining itself — methodology, citations, why-this-recommendation. Never blur them. A user should know at a glance whether they're being told to *do* something or being shown *why*.

4. **Adaptive tone, fixed truth.** Rigor is constant; warmth scales to the user. The same VO2-max plateau is a "stalled adaptation, here's the protocol" for the 12 hr/week runner and a "you've been consistent, here's how to push next" for the casual one. The system's confidence in the underlying number doesn't change.

5. **Light first, outdoors-aware.** Bright sun, dawn pre-run, sweaty thumbs. Light theme is the default because that's the realistic context for half the use cases. Tap targets sized for movement, contrast tested for direct sunlight, no 4px tertiary text. Dark theme is for the post-dinner couch debrief, not a flex.

## Accessibility & Inclusion

- **WCAG AA** across both light and dark themes — contrast, keyboard navigation, focus states.
- **Outdoor / sweat realism** as a Praxys-specific bar: light-theme legibility under direct sunlight, mobile thumb reach (especially miniapp's bottom-tab IA), large tap targets, no 4px tertiary text.
- **Bilingual (EN + 中文)** is structural, not decorative. Brand surfaces use both together; product chrome respects user locale; marketing copy uses primary + subtitle. Never always-both by reflex.
- **Reduced motion** respected via `prefers-reduced-motion`; motion is purposeful (state changes, signal transitions) not decorative.
- **Color blindness:** semantic palette is anchored in green (primary) + cobalt (reasoning), which separates well across deuteranopia / protanopia. Don't encode meaning in red-vs-green alone — pair color with shape, weight, or label.
