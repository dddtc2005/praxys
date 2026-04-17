# Copilot Instructions — Trainsight

## Architecture

```
sync/*.py → db/sync_writer.py → SQLite → analysis/metrics.py → api/deps.py → api/routes/*.py → web/ (React SPA)
```

- **sync/**: API sync scripts (Garmin, Stryd, Oura) → database via `db/sync_writer.py`
- **db/**: SQLAlchemy models, session factory, credential encryption (`crypto.py`), sync writer, CSV import, scheduler
- **analysis/metrics.py**: Pure computation functions (no I/O, no side effects)
- **analysis/data_loader.py**: All data loading lives here
- **api/deps.py**: Data layer — `get_dashboard_data()` is the central function
- **api/routes/**: Thin wrappers calling deps, all under `/api/` prefix; **all endpoints require JWT auth** except `/api/register` and `/api/token`
- **plugins/trainsight/**: Skills (8 SKILL.md files) and MCP server
- **web/src/**: React + TypeScript + Tailwind v4 + Recharts

## Critical Rule: Split-Level Power Analysis

**Never use activity `avg_power` for intensity analysis.** Activity averages are diluted by warmup/cooldown. Always use `activity_splits.csv` which has per-split power and duration revealing actual interval intensity. See `diagnose_training()` in `metrics.py`.

## Python Conventions

- Type hints on all function signatures
- Docstrings on public functions
- Metrics in `metrics.py` must be **pure functions** — data in via parameters, results out via return
- Data loading only in `data_loader.py`
- Cite sources (paper DOI or URL) for formulas and constants

## Frontend Conventions

- TypeScript strict — all API responses typed in `web/src/types/api.ts`
- `useApi<T>` hook for data fetching (handles loading/error/data states)
- Tailwind v4 with custom theme vars (see `web/src/index.css`)
- Recharts for charts with dark theme styling
- Data numbers use `font-data` CSS class (JetBrains Mono, tabular-nums)
- Every prediction/insight needs a `ScienceNote` component with source links

## Config

- User config (goals, thresholds) stored in the database, managed via Settings/Goal page UI
- Server config in `.env` (see `.env.example` for encryption key, JWT secret, admin email)
- Data recomputed fresh per request in `api/deps.py`

## For Full Details

See [CLAUDE.md](../CLAUDE.md) for complete conventions, how-to guides, and the module map.
See [AGENTS.md](../AGENTS.md) for multi-agent workflow patterns.
