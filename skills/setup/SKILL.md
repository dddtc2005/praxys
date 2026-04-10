---
name: setup
description: >-
  Configure Trainsight: connect data sources (Garmin, Stryd, Oura), set training
  base (power/HR/pace), configure thresholds (CP, LTHR, pace), set race goals,
  and manage source preferences. Use this skill whenever the user asks to "connect
  garmin", "set up stryd", "add oura", "change training base", "set my CP",
  "set my goal", "configure preferences", "initial setup", "set threshold",
  "switch to HR-based training", or any request to configure the training system.
  Also use when the user reports missing credentials or sync failures due to
  missing config.
---

# Trainsight Setup

Guide the user through configuring their training system. Configuration is stored
in `data/config.json` and credentials in `sync/.env`.

## Before You Start

Read these two files to understand current state:

1. **`data/config.json`** — current configuration (may not exist yet for new users)
2. **`sync/.env`** — current credentials (may not exist; template at `sync/.env.example`)

Also read `analysis/config.py` for the valid types and defaults:
- `TrainingBase`: `"power"`, `"hr"`, `"pace"`
- `PlatformName`: `"garmin"`, `"stryd"`, `"oura"`, `"coros"`
- `PlanSource`: `"garmin"`, `"stryd"`, `"oura"`, `"coros"`, `"ai"`
- `PLATFORM_CAPABILITIES`: what each platform provides
- `DEFAULT_ZONES`: default zone boundaries per training base

## Configuration Areas

### 1. Data Source Connections

Each platform requires credentials in `sync/.env`:

| Platform | Required Env Vars | How to Get |
|----------|------------------|------------|
| Garmin | `GARMIN_EMAIL`, `GARMIN_PASSWORD` | Garmin Connect account |
| Garmin China | Above + `GARMIN_IS_CN=true` | Garmin Connect CN account |
| Stryd | `STRYD_EMAIL`, `STRYD_PASSWORD` | Stryd account (stryd.com) |
| Oura | `OURA_TOKEN` | Generate at cloud.ouraring.com/personal-access-tokens |

To add a connection:
1. Check if `sync/.env` exists; if not, copy from `sync/.env.example`
2. Add the credentials for the requested platform
3. Update `data/config.json` → `connections` array to include the platform
4. Set appropriate `preferences` (which platform provides activities, recovery, plan)

Platform capabilities determine valid preferences:
- **activities**: garmin, stryd, coros
- **recovery**: garmin, oura
- **fitness**: garmin, stryd, coros (auto-merged, no preference needed)
- **plan**: garmin, stryd, coros, ai

### 2. Training Base

The training base determines which metric drives all analysis:

| Base | Threshold | Load Metric | Best When |
|------|-----------|-------------|-----------|
| `power` | CP (watts) | RSS | User has Stryd or power meter |
| `hr` | LTHR (bpm) | TRIMP | User has HR monitor, no power |
| `pace` | Threshold pace (sec/km) | rTSS | GPS-only, no HR or power |

Update `training_base` in `data/config.json`. When changing base, remind the user
that zone boundaries will use the defaults for that base unless customized.

### 3. Thresholds

Thresholds can be auto-detected from connected platforms or set manually:

```json
"thresholds": {
  "cp_watts": null,           // Critical Power (auto from Stryd/Garmin)
  "lthr_bpm": null,           // Lactate Threshold HR (auto from Garmin)
  "threshold_pace_sec_km": null,  // Threshold pace (auto-calculated)
  "max_hr_bpm": null,         // Max HR (for TRIMP calculation)
  "rest_hr_bpm": null,        // Resting HR (for TRIMP calculation)
  "source": "auto"            // "auto" or "manual"
}
```

- `"source": "auto"` — system detects from connected platforms, manual values override
- `"source": "manual"` — only use manually entered values

When the user provides a threshold value, set it and change source to `"auto"` (manual
overrides still take precedence in auto mode).

### 4. Goal Configuration

```json
"goal": {
  "race_date": "",            // "YYYY-MM-DD" or empty for continuous mode
  "distance": "marathon",     // 5k, 10k, half_marathon, marathon, 50k, 50_mile, 100k, 100_mile
  "target_time_sec": 0        // Target finish time in seconds, or 0 for no target
}
```

- **Race mode**: set `race_date` + `distance` + optional `target_time_sec`
- **Continuous improvement**: leave `race_date` empty, set `distance` for predictions

Help the user convert times: e.g., "sub-3 marathon" = 10800 sec, "sub-45 10K" = 2700 sec.

### 5. Source Preferences

```json
"preferences": {
  "activities": "garmin",   // Which platform provides activity data
  "recovery": "oura",       // Which platform provides sleep/HRV
  "plan": "ai"              // Where training plan comes from
}
```

Only set preferences to platforms listed in `connections` (except `"ai"` for plan).

### 6. Zone Boundaries (Advanced)

Zone boundaries are fractions of the threshold value. Defaults from `analysis/config.py`:

```json
"zones": {
  "power": [0.55, 0.75, 0.90, 1.05],
  "hr": [0.72, 0.82, 0.89, 0.96],
  "pace": [1.29, 1.14, 1.06, 1.00]
}
```

4 boundaries define 5 zones. Only modify if the user has specific zone preferences.
For zone theory selection (Coggan vs Seiler etc.), use the `science` skill instead.

## Writing Config

Use `analysis/config.py` functions:
- `load_config()` → returns `UserConfig` dataclass
- `save_config(config)` → writes to `data/config.json`

Or edit `data/config.json` directly (simpler for targeted changes).

After any config change, remind the user to restart the API server if it's running
(the cache refreshes every 5 minutes, but a restart is instant).

## First-Time Setup Checklist

For new users, guide through this order:
1. Create `sync/.env` from `sync/.env.example` with their credentials
2. Set `connections` in config to match their platforms
3. Set `training_base` based on available data (power if they have Stryd)
4. Set `preferences` for each data category
5. Set `goal` if they have a race target
6. Run a data sync to verify everything works (suggest using the `sync-data` skill)
