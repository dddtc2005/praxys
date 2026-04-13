# Architecture

## System Overview

```
Garmin/Stryd/Oura APIs
        |
   sync/*.py          Fetch + normalize → CSV files
        |
   data/**/*.csv      Flat-file data store (deduplication via csv_utils.py)
        |
   analysis/          Pure computation layer
   ├── data_loader.py    CSV loading + cross-source merging
   ├── metrics.py        All metric functions (pure, no I/O)
   ├── zones.py          Zone boundary calculation
   ├── config.py         User config (data/config.json)
   ├── science.py        Theory loading from YAML
   └── providers/        Platform-specific data adapters
        |
   api/               FastAPI application
   ├── deps.py           Cached data layer (get_dashboard_data())
   ├── ai.py             AI context builder + plan validation
   └── routes/           Thin endpoint handlers
        |
   ┌────┴────┐
   web/    .claude/skills/
   React    AI skill
   SPA      definitions
```

## Key Design Decisions

### Single Computation Entry Point

`api/deps.py:get_dashboard_data()` is the sole entry point for all computed data. It:
1. Loads config and data from CSVs
2. Resolves thresholds (auto-detect + manual overrides)
3. Loads active science theories
4. Computes all metrics (fitness/fatigue, diagnosis, predictions, recovery)
5. Caches results for 5 minutes

Both the API routes and CLI skill scripts call this function. This ensures web and CLI always show identical data.

### Pure Metric Functions

All functions in `analysis/metrics.py` are pure — they take data in, return results out, with no I/O or side effects. This makes them testable and composable. I/O is handled by `data_loader.py` (reading) and `api/deps.py` (orchestration).

### CSV as Data Store

Training data is stored as flat CSV files rather than a database. This is intentional:
- Portable: data files are human-readable and tool-agnostic
- Simple: no database setup, migrations, or connections
- Idempotent: `csv_utils.append_rows()` handles deduplication via key columns

### Pluggable Science Framework

Training theories (load models, zone frameworks, prediction methods, recovery protocols) are YAML files in `data/science/`. The user selects one theory per pillar in `data/config.json`. This means:
- Metrics adapt to the selected theory (zone boundaries, time constants, etc.)
- New theories can be added by creating a YAML file — no code changes
- Citations link back to the original research papers

### Multi-Source Data Merging

Activities can come from Garmin, Stryd, or Coros. `data_loader.py` merges them:
- Primary source set via `config.preferences.activities`
- Secondary sources enrich with additional columns (e.g., Stryd adds power to Garmin activities)
- Matching uses date + timestamp proximity (handles timezone differences)

## Module Responsibilities

### sync/

Each sync script (`garmin_sync.py`, `stryd_sync.py`, `oura_sync.py`) is self-contained:
- Authenticates with the platform API
- Fetches new data since last sync (or from `--from-date`)
- Normalizes to the CSV schema
- Calls `csv_utils.append_rows()` to merge with existing data

`sync_all.py` orchestrates all three with error isolation per source.

### analysis/

- **`config.py`**: `UserConfig` dataclass, `load_config()`/`save_config()`, platform capabilities, zone defaults
- **`data_loader.py`**: `load_data()` returns a dict of DataFrames: `activities`, `splits`, `recovery`, `fitness`, `plan`
- **`metrics.py`**: ~40 pure functions covering RSS, TRIMP, EWMA, TSB, predictions, diagnosis, recovery analysis
- **`zones.py`**: Computes zone ranges from threshold + boundary fractions
- **`science.py`**: Loads YAML theories, merges with label sets, provides `load_active_science()`
- **`training_base.py`**: Display config per training base (labels, units, abbreviations)
- **`providers/`**: Platform-specific adapters for threshold detection and plan loading

### api/

- **`deps.py`**: The big orchestrator. `get_dashboard_data()` is ~300 lines that loads everything, computes everything, and returns a dict consumed by all routes.
- **`ai.py`**: `build_training_context()` serializes dashboard data into LLM-optimized JSON. `validate_plan()` checks generated plans.
- **`routes/`**: Each route file is a thin wrapper extracting relevant keys from `get_dashboard_data()`.

### web/

React SPA (Vite + TypeScript + Tailwind v4 + shadcn/ui):
- **`pages/`**: 4 pages matching dashboard tabs (Today, Training, Goal, Settings) + Science
- **`components/`**: UI components, one per card/section
- **`hooks/`**: `useApi<T>` for data fetching with loading/error states
- **`types/api.ts`**: TypeScript interfaces matching API response shapes
- **`lib/chart-theme.ts`**: Single source of truth for chart colors

### .claude/skills/

8 skill directories, each with a `SKILL.md` (instructions for AI tools). Skills that need data have corresponding Python CLI tools in the top-level `scripts/` directory that output JSON to stdout.

## Data Flow Examples

### "What should I do today?"

```
daily_brief.py
  → get_dashboard_data()
    → load_data() → merge activities + recovery + plan
    → _resolve_thresholds() → auto-detect CP from Stryd
    → load_active_science() → get recovery theory params
    → analyze_recovery() → HRV status (Kiviniemi/Plews)
    → daily_training_signal() → Go/Modify/Rest
  → extract signal + recovery + upcoming + last activity
  → JSON to stdout
```

### "Diagnose my training"

```
run_diagnosis.py
  → get_dashboard_data()
    → load_data() → activities + splits
    → diagnose_training(merged, splits, cp_trend, ...)
      → volume analysis (weekly km, trend)
      → consistency check (gaps, session count)
      → interval intensity (split-level, supra-CP sessions)
      → zone distribution (actual vs target from theory)
      → _add_diagnosis_items() → findings + suggestions
  → JSON to stdout
```
