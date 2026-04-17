# CLI Skills

Trainsight includes 8 AI skills that provide access to all training features via Claude Code and Copilot CLI. No web UI needed.

## Requirements

- [Claude Code](https://claude.com/claude-code) or [GitHub Copilot CLI](https://githubnext.com/projects/copilot-cli/)
- Python 3.11+ with project dependencies installed (`pip install -r requirements.txt`)
- A running Trainsight backend (cloud or local) with at least one connected platform

## Plugin Installation

Skills are packaged as a Claude Code plugin in `plugins/trainsight/`.

```bash
# Register the local marketplace (one-time)
claude plugin marketplace add ./plugins/marketplace.json

# Install the plugin
claude plugin install trainsight

# Reload plugins (in Claude Code)
/reload-plugins
```

## Plugin Setup

### Cloud Mode (Recommended)

If Trainsight is deployed, the MCP server's `TRAINSIGHT_URL` env var (configured in `plugins/trainsight/.mcp.json`) points at the deployed backend. All requests route through the API with JWT authentication. Your token is cached at `~/.trainsight/token`.

To authenticate with the cloud backend:

```bash
# Login and cache token (done automatically by the MCP server auth helper)
python plugins/trainsight/mcp-server/auth.py
```

### Local Mode

If running locally, remove or leave blank the `TRAINSIGHT_URL` env var in `.mcp.json`. The MCP server uses direct database access:

```bash
# Start the backend server (needed for sync operations)
python -m uvicorn api.main:app --reload
```

In local mode, the MCP server imports project modules directly and uses the first registered user's data.

## MCP Tools

The plugin provides an MCP server (`plugins/trainsight/mcp-server/server.py`) that exposes these tools to the AI agent:

| Tool | Description |
|------|-------------|
| `get_daily_brief` | Today's training signal, recovery, upcoming workouts |
| `get_training_review` | Zone distribution, fitness/fatigue, diagnosis, suggestions |
| `get_race_forecast` | Race prediction, goal feasibility, threshold trend |
| `get_training_context` | Full training context for AI plan generation |
| `get_settings` | Current user settings and display config |
| `update_settings` | Update training base, thresholds, zones, goal, science |
| `get_connections` | Connected platforms and their status |
| `connect_platform` | Store encrypted credentials for a platform |
| `disconnect_platform` | Remove a platform connection |
| `push_training_plan` | Save an AI-generated training plan |
| `trigger_sync` | Sync data from connected platforms |
| `get_sync_status` | Check sync status per platform |

Each tool works in both remote mode (HTTP to the deployed API) and local mode (direct Python imports). The mode is determined by the `TRAINSIGHT_URL` environment variable.

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

The skill generates the plan, validates it, shows it for review, and saves to the database on approval.

### /race-forecast

Race time prediction and goal feasibility.

**When to use:** Checking progress toward a race goal, comparing prediction methods.

**Examples:**
- "Can I hit sub-3?"
- "What's my predicted marathon time?"
- "How much CP do I need for my goal?"

### /add-metric

Scaffold a new training metric end-to-end (7-step guide).

**When to use:** Adding a new computed metric, prediction, or insight to the dashboard.

**Examples:**
- "Add a new efficiency metric"
- "Scaffold a pace decay metric"
- "I want to add a new insight to the dashboard"

## How Skills Work

Skills are defined in `plugins/trainsight/skills/` — each skill has a `SKILL.md` file with instructions that Claude Code and Copilot CLI auto-discover when the plugin is installed.

Skills that need training data call the MCP tools listed above. The MCP server handles mode detection (remote vs local) transparently, so the same skill works whether you are connected to a cloud deployment or running locally.

### Architecture

```
User invokes /daily-brief
    → Claude Code reads plugins/trainsight/skills/daily-brief/SKILL.md
    → Skill instructions tell the AI to call get_daily_brief MCP tool
    → MCP server (plugins/trainsight/mcp-server/server.py) handles the call:
        Remote mode: GET /api/today (with JWT auth)
        Local mode:  Direct Python import → get_dashboard_data()
    → JSON response returned to the AI
    → AI formats the data as a readable brief
```

### Plugin Structure

```
plugins/trainsight/
  plugin.json          Plugin manifest (name, version, component directories)
  .mcp.json            MCP server configuration
  skills/              8 skill directories (auto-discovered)
    setup/SKILL.md
    science/SKILL.md
    sync-data/SKILL.md
    daily-brief/SKILL.md
    training-review/SKILL.md
    training-plan/SKILL.md
    race-forecast/SKILL.md
    add-metric/SKILL.md
  hooks/               Event hooks (e.g., session-start)
  mcp-server/          MCP server implementation
    server.py          Dual-mode tool handlers
    auth.py            JWT token management
```
