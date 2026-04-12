# CLI Skills

Trainsight includes 7 AI skills that provide terminal-based access to all training features. No web UI needed.

## Requirements

- [Claude Code](https://claude.com/claude-code) or [GitHub Copilot CLI](https://githubnext.com/projects/copilot-cli/)
- Python 3.11+ with project dependencies installed (`pip install -r requirements.txt`)
- Data synced to `data/` (via credentials in `sync/.env`)

## Available Skills

### /setup

Configure connections, training base, thresholds, and goals.

**When to use:** First-time setup, adding a new data source, changing your goal, switching training base.

**Examples:**
- "Connect my Garmin account"
- "Set my goal to sub-3 marathon"
- "Switch to HR-based training"
- "Set my CP to 250 watts"

### /science

Browse and select training science theories across 4 pillars.

**When to use:** Choosing between zone frameworks, understanding different load models, switching prediction methods.

**Examples:**
- "What zone theories are available?"
- "Explain Coggan 5-zone vs Seiler polarized"
- "Switch to the Riegel prediction model"
- "How does HRV-based recovery work?"

### /sync-data

Sync training data from Garmin, Stryd, and/or Oura Ring.

**When to use:** Pulling latest data, backfilling history, checking sync status.

**Examples:**
- "Sync my data"
- "Pull garmin data from last month"
- "Sync everything except oura"

### /daily-brief

Today's training signal with recovery status and upcoming workouts.

**When to use:** Start of the day, deciding whether to train, checking recovery.

**Examples:**
- "What should I do today?"
- "Am I recovered enough to train?"
- "Show me today's brief"

If data is stale (not synced today), the skill automatically syncs first.

### /training-review

Multi-week training analysis with diagnosis and suggestions.

**When to use:** Weekly check-in, understanding training gaps, checking zone balance.

**Examples:**
- "How's my training going?"
- "Why isn't my CP improving?"
- "Check my zone distribution"
- "Give me a training review for the last 8 weeks"

### /training-plan

Generate a personalized 4-week AI training plan.

**When to use:** Starting a new training block, plan expired, changing goals.

**Examples:**
- "Generate a training plan"
- "Plan my next 4 weeks"
- "My plan is stale, regenerate it"

The skill generates the plan, validates it, shows it for review, and saves to `data/ai/` on approval.

### /race-forecast

Race time prediction and goal feasibility.

**When to use:** Checking progress toward a race goal, comparing prediction methods.

**Examples:**
- "Can I hit sub-3?"
- "What's my predicted marathon time?"
- "How much CP do I need for my goal?"

## Installation

Skills are installed by symlinking the `skills/` directory to your AI tool's skill location:

### Claude Code

```bash
# Windows (admin terminal or Developer Mode)
mklink /J "%USERPROFILE%\.claude\skills\daily-brief" "skills\daily-brief"
# ... repeat for each skill

# Or use the link-skills skill if available:
# /link-skills
```

### GitHub Copilot CLI

```bash
# Same pattern, different target:
mklink /J "%USERPROFILE%\.copilot\skills\daily-brief" "skills\daily-brief"
```

## How Skills Work

Skills that need data (daily-brief, training-review, race-forecast, sync-data) include Python helper scripts in their `scripts/` directory. These scripts:

1. Import from the project's `api/deps.py` and `analysis/` modules
2. Run the same computations as the web dashboard
3. Output structured JSON to stdout
4. The AI reads the JSON and formats it as a readable brief

You can also run the scripts directly:

```bash
python scripts/daily_brief.py --pretty
python scripts/run_diagnosis.py --pretty
python scripts/race_forecast.py --pretty
python scripts/sync_report.py --pretty --skip oura
```
