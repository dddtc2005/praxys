# CLAUDE.md

## What This Is

Power-based scientific training system for self-coached endurance athletes. Syncs data from Garmin, Stryd, and Oura Ring, computes training metrics, and serves a modern web dashboard (FastAPI + React + SQLite) with weekly reports. Multi-user with JWT auth and invitation-based registration.

## Architecture

```
Garmin/Stryd/Oura APIs → sync/*.py → db/sync_writer.py → SQLite (trainsight.db)
                                                              ↓
                                                       analysis/metrics.py (pure computation)
                                                              ↓
                                                       api/deps.py (data layer)
                                                              ↓
                                                       api/routes/*.py (JSON endpoints, JWT auth)
                                                              ↓
                                                       web/ (React SPA)
```

### Module Map

| Directory | Owns | Key Files |
|-----------|------|-----------|
| `sync/` | API sync scripts | `garmin_sync.py`, `stryd_sync.py`, `oura_sync.py`, `csv_utils.py`, `sync_all.py` (orchestrator), `bootstrap_garmin_tokens.py` |
| `analysis/` | Metric computation | `metrics.py` (pure functions), `data_loader.py` (CSV I/O + merge), `science.py` (theory YAML loader), `config.py` (UserConfig dataclass), `zones.py`, `thresholds.py`, `training_base.py` |
| `analysis/providers/` | Pluggable data sources | `base.py` (abstract provider ABCs), `garmin.py`, `stryd.py`, `oura.py`, `ai.py` (AI plan CSV loader), `models.py` |
| `db/` | Database layer (SQLite) | `models.py` (SQLAlchemy models), `session.py` (engine + session factory), `crypto.py` (Fernet credential encryption), `sync_writer.py` (upsert sync data), `csv_import.py` (one-time CSV migration), `sync_scheduler.py` (background sync jobs) |
| `api/` | FastAPI backend | `main.py` (app), `deps.py` (data layer), `auth.py` (JWT auth), `users.py`, `views.py` (shared view helpers), `routes/` (endpoints incl. `admin.py`, `register.py`) |
| `web/src/` | React frontend | `pages/` (6 pages: Today, Training, Goal, History, Science, Settings), `components/` (UI + `charts/` sub-dir), `hooks/` (`useApi`, `useChartColors`, `useTheme`, `use-mobile`), `contexts/` (`ScienceContext`, `SettingsContext`), `types/` (API contracts), `lib/` (`chart-theme`, `format`, `utils`, `workout-parser`) |
| `plugins/` | Trainsight plugin | `trainsight/skills/` (8 SKILL.md files), `trainsight/mcp-server/` (MCP server: `server.py`, `auth.py`) |
| `tests/` | pytest suite | `test_metrics.py`, `test_integration.py`, etc. |
| `data/` | Sample + science data | `sample/` (tracked synthetic CSVs), `science/` (theory YAMLs: load, recovery, prediction, zones, labels) |
| `scripts/` | Utility + skill helper scripts | `seed_sample_data.py`, `generate_sample_data.py`, `build_training_context.py`, `daily_brief.py`, `race_forecast.py`, `sync_report.py`, `run_diagnosis.py` |
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
- **All API endpoints require JWT auth** (`Authorization: Bearer <token>` header) except `/api/register` and `/api/token`
- `api/deps.py` recomputes all data fresh on each request (`get_dashboard_data()`)
- User config (goal, thresholds, sources) stored in the database, managed via Settings/Goal page UI
- Platform credentials (Garmin/Stryd/Oura) encrypted at rest via `db/crypto.py` (Fernet)

## Critical: Split-Level Power Analysis

**Activity `avg_power` is diluted by warmup, cooldown, and recovery jogs.** A threshold session with 2x20min intervals at 248W will show ~210-220W activity average because it includes 15min warmup at 180W and recovery jogs at 130W.

**Always use `activity_splits.csv` for intensity analysis.** This file has per-split power and duration, which reveals actual interval power. The `diagnose_training()` function in `metrics.py` does this correctly.

## Dashboard Modes

Goal configuration is managed via the Goal page UI and stored in the database:
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
2. Add SQLAlchemy model to `db/models.py` and upsert logic to `db/sync_writer.py`
3. Register in `data_loader.py` `load_all_data()` dict
4. Update `data/sample/{source}/` with synthetic CSVs for testing
5. Update `scripts/generate_sample_data.py` with the new source

## Running

**Always use the project venv for Python commands.** The venv is at `.venv/`.

```bash
# Activate venv first (all Python commands below assume venv is active)
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate

# First-time setup: copy .env.example and generate encryption key
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(f'TRAINSIGHT_LOCAL_ENCRYPTION_KEY={Fernet.generate_key().decode()}')" >> .env

# API server
pip install -r requirements.txt
python -m uvicorn api.main:app --reload

# Frontend dev server (separate terminal)
cd web && npm install && npm run dev

# Tests
python -m pytest tests/ -v
```

### First-time setup

1. Copy `.env.example` to `.env` and generate an encryption key (see commands above)
2. Start the server and frontend dev server
3. Open the app, register -- the first user on a fresh DB becomes admin (no invitation code needed)
4. Admin can generate invitation codes for others via the Admin page (`/admin`)

### Invitation system and admin

- Registration requires a valid invitation code (except for the first user and `TRAINSIGHT_ADMIN_EMAIL`)
- Admin page (`/admin`) lets admins generate invitation codes and manage users
- Admin status is granted to: the first registered user, and any user matching `TRAINSIGHT_ADMIN_EMAIL`

## Documentation

Keep docs in sync with code — stale docs are worse than no docs. See `docs/dev/contributing.md` for which files to update when making changes.

Key files: `README.md` (quick start), `docs/*.md` (user guides), `docs/dev/*.md` (architecture + API reference + contributing), `plugins/trainsight/skills/*/SKILL.md` (skill instructions).

## AI Skills

8 skills in `plugins/trainsight/skills/` provide training features via the Trainsight plugin (MCP server + skills):

| Skill | Purpose |
|-------|---------|
| `setup` | Configure connections, training base, thresholds, goals |
| `science` | Browse and select training science theories |
| `sync-data` | Sync data from Garmin/Stryd/Oura |
| `daily-brief` | Today's training signal, recovery, upcoming workouts |
| `training-review` | Multi-week training diagnosis and suggestions |
| `training-plan` | Generate 4-week AI training plan |
| `race-forecast` | Race time prediction and goal feasibility |
| `add-metric` | Scaffold a new metric end-to-end (7-step guide) |

Skills use MCP tools provided by the Trainsight plugin MCP server (`plugins/trainsight/mcp-server/server.py`). The server runs in dual mode: local (direct DB access) or remote (HTTP API with JWT auth via `TRAINSIGHT_URL`).

## AI Features

### Implemented
- **`api/ai.py`** — `build_training_context()` serializes all computed metrics to a structured dict for LLM consumption; `validate_plan()` checks AI-generated plans (date ranges, power targets, distribution) before CSV write; `check_plan_staleness()` detects stale plans (>28 days or CP drift >3%)
- **`analysis/providers/ai.py`** — `AiPlanProvider` loads AI-generated plans from `data/ai/training_plan.csv`
- **`analysis/science.py`** — Theory framework loads YAML from `data/science/` (10 theories across 4 pillars + 2 label sets)
- **Design principle:** AI is always optional. The app must function fully without `ANTHROPIC_API_KEY`

### Not yet built
- **Frontend:** `useAiStatus()` hook to gate AI UI — not implemented yet
- **Possible features:** AI coaching narratives, natural language training queries, AI-enhanced weekly summaries
