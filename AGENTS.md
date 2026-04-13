# AGENTS.md — Multi-Agent Workflow Guide

## Agent Roles

### Data Pipeline Agent
- **Focus:** `sync/`, `analysis/data_loader.py`, `sync/csv_utils.py`
- **Tasks:** Add new data sources, fix sync issues, extend CSV schemas
- **Context needed:** `sync/.env.example` for API patterns, `data_loader.py` for loading conventions
- **Key rule:** All sync scripts must use `csv_utils.append_csv()` for dedup-on-write

### Analysis Agent
- **Focus:** `analysis/metrics.py`, `api/deps.py`
- **Tasks:** Add new metrics, improve predictions, fix computation bugs
- **Context needed:** Read the "Split-Level Power Analysis" section in CLAUDE.md first
- **Key rule:** All metric functions must be **pure** — no file I/O, no side effects, no global state. Data flows in via parameters, results flow out via return values.

### Frontend Agent
- **Focus:** `web/src/`
- **Tasks:** Add UI components, new pages, improve visualizations
- **Context needed:** `web/src/types/api.ts` for API contracts, `useApi` hook pattern
- **Key rule:** All data comes from API via `useApi<T>` hook. No direct file reads. Data numbers use `font-data` class.

### API Agent
- **Focus:** `api/main.py`, `api/deps.py`, `api/routes/`
- **Tasks:** Add endpoints, modify data layer
- **Context needed:** `api/deps.py` `get_dashboard_data()` is the central data function — all routes call it fresh per request
- **Key rule:** Routes are thin — computation belongs in `analysis/metrics.py`, not in route handlers

### AI Features Agent (Future)
- **Focus:** `api/ai.py` (to be created), frontend AI components
- **Tasks:** Implement LLM-powered coaching, natural language queries
- **Context needed:** `api/deps.py` for data access, existing metrics for context injection
- **Key rule:** AI features must be optional — guard with `is_available()`, app works fully without API key

## Workflow Patterns

### Adding a Feature End-to-End
1. **Analysis Agent** adds metric to `metrics.py` + test
2. **API Agent** exposes via `deps.py` + route
3. **Frontend Agent** adds types, component, page integration
4. Run `python -m pytest tests/` and `cd web && npm run build` to verify

### Debugging a Data Issue
1. **Data Pipeline Agent** checks sync output and CSV integrity
2. **Analysis Agent** traces through `data_loader.py` → `metrics.py` with sample data
3. Use `tests/test_integration.py` fixture pattern for reproducible test cases

### Working with Sample Data
- `data/sample/` contains tracked synthetic CSVs for all 7 data sources
- `python scripts/seed_sample_data.py` copies sample → data/ for local testing
- `python scripts/generate_sample_data.py` regenerates sample data after schema changes
