# Trainsight

Skills-based training insights for technical athletes.

Trainsight is built for engineers who train seriously and prefer terminal-native workflows with tools like [Claude Code](https://claude.com/claude-code) and [GitHub Copilot CLI](https://githubnext.com/projects/copilot-cli/). It combines Garmin, Stryd, and Oura data into training metrics, race predictions, and daily recommendations through AI skills.

Skills in CLI and the local web dashboard are both supported, so you can choose workflow-first interaction in the terminal and visual exploration in the browser.

![Trainsight Dashboard](data/screenshots/product-showcase.png)

## Who This Is For

- Endurance athletes comfortable with CLI workflows
- Engineers who want reproducible, scriptable training analysis
- Users who prefer skill-driven interaction over point-and-click UI
- People comfortable managing Python dependencies and API credentials

## CLI Skills

Trainsight ships with 8 AI skills:

| Skill | Purpose |
|-------|---------|
| `/setup` | Configure connections, thresholds, and goals |
| `/science` | Select training science theories |
| `/sync-data` | Sync Garmin / Stryd / Oura data |
| `/daily-brief` | Get today's training + recovery signal |
| `/training-review` | Analyze multi-week trends and diagnosis |
| `/training-plan` | Generate a 4-week plan |
| `/race-forecast` | Predict race outcomes and goal feasibility |
| `/add-metric` | Scaffold a new metric end-to-end |

See [docs/skills.md](docs/skills.md) for usage details.

## Quickstart (Skills + Optional Web)

Choose one data path:
- **Sample data path:** run step 2 and skip credential setup/sync steps.
- **Real data path:** skip step 2 and run steps 3-4.

```bash
# 1) Install Python deps
pip install -r requirements.txt

# 2) Sample data path (no credentials required)
python scripts/seed_sample_data.py

# 3) Real data path: set up credentials (Garmin/Stryd/Oura)
cp sync/.env.example sync/.env
# edit sync/.env

# 4) Real data path: sync data
python -m sync.sync_all --from-date 2025-12-01

# 5) Use skills from Claude Code / Copilot CLI
# e.g. run /setup, /sync-data, /daily-brief, /training-review
```

## Typical CLI Workflow

1. `/setup` once to configure sources and training settings
2. `/sync-data` to refresh training and recovery data
3. `/daily-brief` each morning for train/modify/rest guidance
4. `/training-review` weekly for diagnosis and adjustments
5. `/training-plan` when starting a new block
6. `/race-forecast` as race goals approach

## Web Dashboard (Optional)

If you want local visualization:

```bash
python -m uvicorn api.main:app --reload
cd web && npm install && npm run dev
```

Then open `http://localhost:5173`.

## Architecture (High-Level)

```
sync/*.py            -> pulls source data into CSVs
analysis/metrics.py  -> pure computation
api/deps.py          -> cached data layer used by API + skills
api/routes/*.py      -> JSON endpoints
web/                 -> optional local visualization UI
.claude/skills/      -> AI skill definitions (auto-discovered)
```

## Validation

```bash
python -m pytest tests/ -v
cd web && npm run build
```

## Documentation

- [CLI Skills](docs/skills.md) — primary usage guide
- [Getting Started](docs/getting-started.md)
- [Features](docs/features.md)
- [Architecture](docs/dev/architecture.md)
- [API Reference](docs/dev/api-reference.md)
- [Contributing](docs/dev/contributing.md)

For detailed architecture and conventions, see [CLAUDE.md](CLAUDE.md).
