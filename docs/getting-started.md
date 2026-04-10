# Getting Started

Full setup guide for Trainsight.

## Prerequisites

- Python 3.11+
- Node.js 18+ (for the web dashboard)
- At least one of: Garmin Connect account, Stryd account, Oura Ring

## 1. Install Dependencies

```bash
# Python
pip install -r requirements.txt

# Frontend (optional, only if using the web dashboard)
cd web && npm install
```

## 2. Configure Credentials

Copy the example env file and fill in your credentials:

```bash
cp sync/.env.example sync/.env
```

Edit `sync/.env`:

| Variable | Required | How to Get |
|----------|----------|------------|
| `GARMIN_EMAIL` | If using Garmin | Your Garmin Connect email |
| `GARMIN_PASSWORD` | If using Garmin | Your Garmin Connect password |
| `GARMIN_IS_CN` | China users only | Set to `true` for connect.garmin.cn |
| `STRYD_EMAIL` | If using Stryd | Your Stryd account email |
| `STRYD_PASSWORD` | If using Stryd | Your Stryd account password |
| `OURA_TOKEN` | If using Oura | Generate at [cloud.ouraring.com/personal-access-tokens](https://cloud.ouraring.com/personal-access-tokens) |

You only need credentials for the platforms you use. Unconfigured sources are skipped automatically.

### Garmin Token Bootstrap (first time only)

Garmin uses OAuth tokens that need to be bootstrapped once:

```bash
python -m sync.bootstrap_garmin_tokens
```

This caches tokens in `.garmin_tokens/` (gitignored). If you get rate-limited, the script will prompt for manual token import.

## 3. Initial Configuration

Edit `data/config.json` (created automatically on first run, or copy defaults):

```json
{
  "connections": ["garmin", "stryd", "oura"],
  "preferences": {
    "activities": "garmin",
    "recovery": "oura",
    "plan": "ai"
  },
  "training_base": "power",
  "goal": {
    "distance": "marathon",
    "target_time_sec": 10800
  }
}
```

Key settings:
- **`connections`**: Which platforms you have (only include ones with credentials)
- **`training_base`**: `"power"` (requires Stryd), `"hr"` (requires HR monitor), or `"pace"` (GPS only)
- **`goal.distance`**: `5k`, `10k`, `half_marathon`, `marathon`, `50k`, `50_mile`, `100k`, `100_mile`
- **`goal.target_time_sec`**: Your target finish time in seconds (e.g., 10800 = 3:00:00)

Or use the CLI: if you have Claude Code, run `/setup` for guided configuration.

## 4. Sync Your Data

```bash
# Sync last 7 days from all sources
python -m sync.sync_all

# Backfill historical data
python -m sync.sync_all --from-date 2025-01-01

# Sync specific source only
python -m sync.garmin_sync --from-date 2025-01-01
```

## 5. Run the Dashboard

```bash
# Terminal 1: API server
python -m uvicorn api.main:app --reload

# Terminal 2: Frontend
cd web && npm run dev
```

Open http://localhost:5173.

## 6. Or Use CLI Skills

If you have Claude Code or GitHub Copilot CLI installed, you can use all features from the terminal without the web dashboard. See [skills.md](skills.md) for the full guide.

## Try With Sample Data

If you want to explore without setting up real credentials:

```bash
python scripts/seed_sample_data.py
```

This populates `data/` with 60 days of synthetic training data across all sources.

## Folder Structure

```
data/
  garmin/          Synced Garmin data (gitignored)
  stryd/           Synced Stryd data (gitignored)
  oura/            Synced Oura data (gitignored)
  ai/              AI-generated plans (gitignored)
  sample/          Sample data (tracked in git)
  config.json      User configuration
  science/         Training science theory definitions (YAML)
sync/
  .env             Your API credentials (gitignored)
  .env.example     Credential template
```
