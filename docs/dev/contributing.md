# Contributing

How to extend Trainsight with new features.

## Adding a New Metric

1. **Add a pure function** to `analysis/metrics.py`:
   - Type hints on all parameters and return value
   - Docstring explaining the metric and citing the source
   - No I/O, no side effects — data in, result out

2. **Call it from `api/deps.py`** in `get_dashboard_data()`:
   - Add the result to the returned dict

3. **Expose via API route** in `api/routes/`:
   - Add to an existing route, or create a new route file
   - Register in `api/routes/__init__.py`

4. **Add TypeScript type** to `web/src/types/api.ts`

5. **Build UI component** in `web/src/components/`

6. **Add to the relevant page** in `web/src/pages/`

7. **Add test** in `tests/`

8. **Update docs**: Add to `CLAUDE.md` if it changes the architecture, `docs/features.md` for user-facing description, `docs/dev/api-reference.md` for the endpoint.

## Adding a New Data Source

1. **Create sync script** `sync/{source}_sync.py`:
   - Follow the pattern in `garmin_sync.py`
   - Use `csv_utils.append_rows()` for idempotent writes
   - Accept `data_dir` and `from_date` parameters

2. **Define CSV schema** in `data/{source}/` and add sample data to `data/sample/{source}/`

3. **Register in `data_loader.py`** — add to both `load_all_data()` (raw CSV paths) and `load_data()` (provider-based loading)

4. **Add credentials** to `sync/.env.example`

5. **Add platform capabilities** to `analysis/config.py` `PLATFORM_CAPABILITIES`

6. **Update sample data generator** `scripts/generate_sample_data.py`

7. **Update docs**: `CLAUDE.md` data sources table, `docs/features.md`, `docs/getting-started.md` credentials section.

## Adding a New Skill

1. **Create skill directory** `skills/{skill-name}/`

2. **Write `SKILL.md`** with frontmatter:
   ```yaml
   ---
   name: skill-name
   description: >-
     When to trigger this skill. Be specific about trigger phrases.
   ---
   ```

3. **Add helper script** (if needed) in `skills/{skill-name}/scripts/`:
   - Follow the `build_training_context.py` pattern
   - Set `sys.path` to project root
   - Output JSON to stdout
   - Accept `--pretty` flag

4. **Symlink** to `~/.claude/skills/` (junctions on Windows):
   ```bash
   mklink /J "%USERPROFILE%\.claude\skills\skill-name" "skills\skill-name"
   ```

5. **Update docs**: `docs/skills.md`, `CLAUDE.md` skills table.

## Adding a New Science Theory

1. **Create YAML file** in `data/science/{pillar}/{theory_id}.yaml`:
   ```yaml
   id: theory_id
   pillar: load|recovery|prediction|zones
   name: "Display Name"
   description: Brief description
   simple_description: Plain-language explanation
   advanced_description: |
     Detailed technical explanation with formulas and tables.
   citations:
     - key: author2020
       title: "Paper Title"
       year: 2020
   params:
     # Theory-specific parameters
   ```

2. **No code changes needed** — the science framework auto-discovers YAML files

3. **Test** by selecting the theory in Settings or via `/science` skill

## Keeping UI and CLI Skills in Sync

The web API routes and CLI skill scripts share the same computation layer (`get_dashboard_data()` in `api/deps.py`). They also share **view helpers** in `api/views.py` for extracting presentation-ready data:

- `last_activity()` — most recent activity summary
- `upcoming_workouts()` — next N planned workouts
- `week_load()` — current week load vs plan
- `fitness_summary()` — latest CTL/ATL/TSB values

When adding a new field or changing how data is extracted for display:
1. Add or modify the function in `api/views.py`
2. Both API routes and CLI scripts get the change automatically
3. Never duplicate extraction logic between routes and scripts

## Code Conventions

### Python
- Type hints on all function signatures
- Docstrings on public functions
- Metrics in `analysis/metrics.py` must be pure functions
- Data loading in `analysis/data_loader.py`
- API routes are thin wrappers

### Frontend
- TypeScript strict mode
- All API responses typed in `web/src/types/api.ts`
- `useApi<T>` hook for data fetching
- shadcn/ui components (never raw HTML elements)
- Tailwind CSS v4 with OKLCH color variables
- Recharts with colors from `@/lib/chart-theme.ts`
- Data numbers use `font-data` CSS class

### Git
- Commit messages reference the project folder: `trail-running: add zone distribution chart`
- Never put sensitive content in commit messages

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_metrics.py -v

# Run with coverage
python -m pytest tests/ --cov=analysis --cov=api
```

## Documentation Updates

When making changes, update the relevant docs:

| Change | Update |
|--------|--------|
| New module or page | `CLAUDE.md` module map, `docs/dev/architecture.md` |
| New/changed endpoint | `docs/dev/api-reference.md` |
| New skill | `docs/skills.md`, `CLAUDE.md` skills table |
| New user feature | `docs/features.md` |
| Setup changes | `README.md`, `docs/getting-started.md` |
| Convention changes | `CLAUDE.md` |
| CSV schema changes | `CLAUDE.md` data sources |
