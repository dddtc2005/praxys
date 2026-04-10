# CLAUDE.md

## What This Is

Power-based scientific training system for self-coached endurance athletes. Syncs data from Garmin, Stryd, and Oura Ring into CSVs, computes training metrics, and serves a modern web dashboard (FastAPI + React) with weekly reports.

## Architecture

```
Garmin/Stryd/Oura APIs → sync/*.py → data/**/*.csv
                                          ↓
                                   analysis/metrics.py (pure computation)
                                          ↓
                                   api/deps.py (cached data layer)
                                          ↓
                                   api/routes/*.py (JSON endpoints)
                                          ↓
                                   web/ (React SPA)
```

### Module Map

| Directory | Owns | Key Files |
|-----------|------|-----------|
| `sync/` | API sync scripts | `garmin_sync.py`, `stryd_sync.py`, `oura_sync.py`, `csv_utils.py` |
| `analysis/` | Metric computation | `metrics.py` (pure functions), `data_loader.py` (CSV loading + merge) |
| `api/` | FastAPI backend | `main.py` (app), `deps.py` (cached data layer), `views.py` (shared view helpers), `routes/` (endpoints) |
| `web/src/` | React frontend | `pages/` (4 pages), `components/` (UI), `hooks/` (data fetching), `types/` (API contracts) |
| `tests/` | pytest suite | `test_metrics.py`, `test_integration.py`, etc. |
| `data/` | User CSV data | `garmin/`, `stryd/`, `oura/` (gitignored), `sample/` (tracked) |
| `skills/` | AI skills (CLI) | 7 skills for terminal-based training workflows |
| `scripts/` | Utility scripts | `seed_sample_data.py`, `generate_sample_data.py`, `build_training_context.py` |
| `docs/` | Documentation | `docs/` (user guides), `docs/dev/` (developer docs) |

### Data Sources

- `data/garmin/activities.csv` — activity-level data (distance, duration, HR, training effect)
- `data/garmin/activity_splits.csv` — per-interval data within activities (split power, duration, pace)
- `data/garmin/daily_metrics.csv` — VO2max, training status, resting HR
- `data/stryd/power_data.csv` — power metrics per activity (avg/max power, RSS, CP estimate)
- `data/stryd/training_plan.csv` — planned workouts from Stryd
- `data/oura/sleep.csv` — sleep scores and stages
- `data/oura/readiness.csv` — readiness score, HRV

## Scientific Rigor

All training metrics, predictions, and insights must be grounded in exercise science:
- **Cite sources** in code comments for formulas and constants (paper DOI or URL)
- **Show methodology** in the UI — every prediction/insight should have an expandable "How this is calculated" note with source links (use `ScienceNote` component)
- **Use published values** over guesswork (e.g., Stryd's race power percentages, Riegel's formula, Banister TRIMP)
- **Flag estimates** — if a value lacks strong research backing (e.g., ultra distance fractions), note it as an estimate in both code and UI

## Conventions

### Python
- **Type hints** on all function signatures
- **Docstrings** on public functions
- Metrics in `analysis/metrics.py` must be **pure functions** (no I/O, no side effects)
- Data loading in `analysis/data_loader.py` — all CSV I/O goes here
- API routes are thin wrappers calling `get_dashboard_data()` from `api/deps.py`
- Shared view helpers in `api/views.py` — used by both API routes and CLI skill scripts to avoid duplication

### Frontend
- **TypeScript strict** — all API responses typed in `web/src/types/api.ts`
- **`useApi<T>` hook** for data fetching (loading/error/data states)
- **shadcn/ui** as the component library (base-nova style, dark-first)
- **Tailwind CSS v4** with OKLCH color variables in `web/src/index.css`
- **Recharts** for all charts — colors from `web/src/lib/chart-theme.ts`
- Data numbers use `font-data` CSS class (JetBrains Mono, tabular-nums)

## Frontend Design System

### Theme
- **Light + dark** themes via `.dark` class on `<html>`. Default stored preference is dark.
- `:root` = light theme (warm paper tones), `.dark` = dark theme (deep navy tones)
- Theme toggle in sidebar footer cycles: Dark → Light → System
- User preference persisted in `localStorage` key `trainsight-theme`
- Inline script in `index.html` prevents flash of wrong theme on load
- shadcn's CSS variable system (`--background`, `--card`, `--primary`, etc.) is the **single source of truth** for surface colors
- Brand accent: `--primary` is darkened green in light, vivid neon-green in dark
- Semantic accent colors (`--color-accent-green`, etc.) use CSS custom property indirection (`--accent-green-val`) so `.dark` can override them
- Chart colors use `useChartColors()` hook which returns theme-appropriate hex values for Recharts

### Color Usage Rules
| Token | Usage |
|-------|-------|
| `primary` | Positive signals, active states, brand accent (green) |
| `destructive` | Negative signals, errors, high-intensity zones, rest signals |
| `accent-amber` | Warnings, threshold zones, caution signals |
| `accent-blue` | Informational, TSB/form, moderate zones |
| `accent-purple` | Projections, sleep/recovery data, AI features |
| `muted-foreground` | Secondary text, labels, descriptions |
| `foreground` | Primary text, data values, headings |

**Rule:** Never use raw hex colors in components. Use CSS variables, Tailwind color utilities, or the `chartColors` constants from `@/lib/chart-theme.ts`.

### Typography
- **Body text:** DM Sans (via `--font-sans`, loaded from Google Fonts in `index.html`)
- **Data numbers:** `.font-data` class (JetBrains Mono, `tabular-nums`). Use for **all** numeric values: metrics, dates, percentages, chart labels
- **Section headers:** `text-xs font-semibold uppercase tracking-wider text-muted-foreground`
- **Headings:** Same as body font (DM Sans)

### Component Rules (shadcn/ui)
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

### Chart Conventions
- Import colors from `@/lib/chart-theme.ts` — **single source of truth** for chart colors
- Chart tooltips use `bg-popover border-border text-popover-foreground rounded-lg shadow-xl`
- Grid lines use `chartColors.grid`, axis ticks use `chartColors.tick` with `font-data`
- All charts wrapped in a shadcn `Card`
- Gradient stops reference `chartColors.*` constants (not raw hex)

### Mobile Patterns
- Sidebar renders as Sheet drawer on mobile (via shadcn Sidebar component with `collapsible="icon"`)
- Sticky mobile header with `SidebarTrigger` (hamburger menu)
- Content uses responsive grid: `grid-cols-1 lg:grid-cols-2`
- Cards stack vertically on mobile
- Padding: `px-4 py-6 sm:px-6 lg:px-8`

### API
- All endpoints under `/api/` prefix
- `api/deps.py` caches all computed data for 5 minutes (`get_dashboard_data()`)
- User config (goal, thresholds, sources) stored in `data/config.json`, API credentials in `sync/.env`

## Critical: Split-Level Power Analysis

**Activity `avg_power` is diluted by warmup, cooldown, and recovery jogs.** A threshold session with 2x20min intervals at 248W will show ~210-220W activity average because it includes 15min warmup at 180W and recovery jogs at 130W.

**Always use `activity_splits.csv` for intensity analysis.** This file has per-split power and duration, which reveals actual interval power. The `diagnose_training()` function in `metrics.py` does this correctly.

## Dashboard Modes

Goal configuration is managed via the Goal page UI and stored in `data/config.json`:
- **Race Goal:** race date + optional target time + distance — shows countdown, predicted time, CP gap
- **Continuous Improvement (default):** optional target time + distance — shows CP progress, milestones, trend
- Distance options: 5K, 10K, Half Marathon, Marathon, 50K, 50 Mile, 100K, 100 Mile

## How to Add a New Metric

1. Add a pure function to `analysis/metrics.py` (with type hints + docstring)
2. Call it from `api/deps.py` `get_dashboard_data()`, add result to the returned dict
3. Expose via the appropriate route in `api/routes/` (or create a new route file)
4. Add TypeScript interface to `web/src/types/api.ts`
5. Build component in `web/src/components/`
6. Add to the relevant page in `web/src/pages/`
7. Add test in `tests/`

## How to Add a New Data Source

1. Create `sync/{source}_sync.py` following the pattern in `garmin_sync.py`
2. Add CSV schema to `data/{source}/` and update `data/sample/{source}/` with synthetic data
3. Register in `data_loader.py` `load_all_data()` dict
4. Add credentials to `sync/.env.example`
5. Update `scripts/generate_sample_data.py` with the new source

## Running

```bash
# API server
pip install -r requirements.txt
python -m uvicorn api.main:app --reload

# Frontend dev server (separate terminal)
cd web && npm install && npm run dev

# Quick start with sample data (no API credentials needed)
python scripts/seed_sample_data.py

# Tests
python -m pytest tests/ -v
```

## Documentation

### Doc Types

| Doc | Audience | Purpose | Update Trigger |
|-----|----------|---------|----------------|
| `README.md` | Everyone | High-level overview, quick start, what this is | Major feature additions, setup changes |
| `docs/*.md` | Users | Feature guides, skill usage, configuration | New features, UI changes, new skills |
| `docs/dev/*.md` | Developers | Architecture deep dives, API reference, contributing | Architecture changes, new modules, API changes |
| `CLAUDE.md` | AI + developers | Living architecture doc, conventions, design system | Any code change that affects architecture, conventions, or patterns |
| `skills/*/SKILL.md` | AI tools | Skill instructions for Claude Code / Copilot CLI | When the skill's underlying code or data format changes |

### Documentation Rules

1. **Keep docs in sync with code.** When a code change affects behavior, API shape, architecture, or conventions, update the relevant docs in the same PR. Stale docs are worse than no docs.

2. **Match doc type to audience:**
   - `README.md` — Write for someone who just found the project. No jargon, no internals. Quick start in under 2 minutes.
   - `docs/*.md` — Write for users who want to understand features. How-to oriented, task-focused. Include examples.
   - `docs/dev/*.md` — Write for developers who want to contribute or understand internals. Include architecture decisions, data flows, and API contracts.
   - `CLAUDE.md` — Write for AI assistants and developers reading code. Terse, precise, pattern-oriented. This is the single source of truth for conventions and architecture.

3. **What triggers a doc update:**
   - New module, endpoint, or page → update `CLAUDE.md` module map + `docs/dev/architecture.md`
   - New or changed API endpoint → update `docs/dev/api-reference.md`
   - New skill → update `docs/skills.md`
   - New user-facing feature → update `docs/features.md`
   - Changed setup steps → update `README.md` + `docs/getting-started.md`
   - Changed conventions or design patterns → update `CLAUDE.md`
   - Changed data format or CSV schema → update `CLAUDE.md` data sources section

4. **Don't over-document.** Code comments explain *why*, not *what*. Docs explain *how to use*, not *how it works internally* (that's what the code is for). If a doc section just restates the code, delete it.

### Current Doc Files

```
README.md                    — Project overview + quick start
CLAUDE.md                    — AI instructions + living architecture doc
docs/
  getting-started.md         — User: full setup guide (credentials, config, first sync)
  features.md                — User: feature overview (dashboard, diagnosis, predictions)
  skills.md                  — User: CLI skill usage guide (all 7 skills)
  dev/
    architecture.md          — Dev: system architecture, data flow, module responsibilities
    api-reference.md         — Dev: all API endpoints with request/response shapes
    contributing.md          — Dev: how to add metrics, data sources, skills
```

## AI Skills (CLI)

7 skills in `skills/` provide terminal-based access to all training features without the web UI:

| Skill | Purpose |
|-------|---------|
| `setup` | Configure connections, training base, thresholds, goals |
| `science` | Browse and select training science theories |
| `sync-data` | Sync data from Garmin/Stryd/Oura |
| `daily-brief` | Today's training signal, recovery, upcoming workouts |
| `training-review` | Multi-week training diagnosis and suggestions |
| `training-plan` | Generate 4-week AI training plan |
| `race-forecast` | Race time prediction and goal feasibility |

Skills with helper scripts (`sync-data`, `daily-brief`, `training-review`, `race-forecast`) have a `scripts/` subdirectory with Python CLI tools that output JSON to stdout, following the same pattern as `scripts/build_training_context.py`.

## Future: AI Features

The architecture is designed to support LLM-powered features. Planned extension points:

- **`api/ai.py`** — Claude API integration module with `is_available()` for graceful degradation and `build_training_context()` for serializing computed metrics to LLM context
- **Planned endpoints:** `GET /api/ai/status`, `POST /api/coach` (AI coaching narrative), `POST /api/ask` (NL training queries)
- **Frontend pattern:** `useAiStatus()` hook gates all AI UI — components render nothing when unavailable
- **Design principle:** AI is always optional. The app must function fully without `ANTHROPIC_API_KEY`
- **Possible features:** AI coaching insights, natural language training queries, AI-enhanced weekly summaries
