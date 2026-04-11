---
name: daily-brief
description: >-
  Get today's training brief: training signal (Go/Modify/Rest), recovery
  status (HRV, sleep, resting HR), upcoming planned workouts, last activity
  summary, and weekly load comparison. Use this skill when the user asks
  "what should I do today", "daily brief", "am I ready to train", "today's
  training", "should I run today", "recovery status", "training signal",
  "how's my recovery", "am I recovered", or any request about today's
  training readiness or upcoming workouts.
---

# Daily Training Brief

Provide the user with today's training signal and recovery status without
needing the web dashboard.

## Gathering Data

Run the daily brief script from the project root:

```bash
python skills/daily-brief/scripts/daily_brief.py --pretty
```

This outputs JSON with everything needed for the brief.

## Check Data Freshness First

The output includes a `data_freshness` field that reports the latest date in each
data source and whether any source is stale (no data from today). Example:

```json
"data_freshness": {
  "today": "2026-04-10",
  "sources": {
    "activities": {"latest_date": "2026-04-09", "stale": true},
    "recovery": {"latest_date": "2026-04-10", "stale": false},
    "power": {"latest_date": "2026-04-09", "stale": true}
  },
  "any_stale": true
}
```

**If `any_stale` is true**, sync data before presenting the brief:

```bash
python skills/sync-data/scripts/sync_report.py --pretty
```

Then re-run the daily brief script to get fresh data. Tell the user you're
syncing first: "Data is from yesterday — syncing latest before generating
your brief."

If sync fails (e.g., credentials not set), proceed with stale data but note
the staleness in the brief header.

## Presenting the Brief

Format the output as a concise training brief. Structure it as:

### 1. Training Signal

The `signal` object contains:
- `recommendation`: "Go", "Modify", or "Rest"
- `reason`: Why this recommendation was made
- `detail`: Additional context (e.g., "TSB is -15, moderate fatigue")

Present this prominently — it's the headline answer to "should I run today?"

### 2. Recovery Status

The `recovery_analysis` object contains:
- `status`: "Fresh", "Normal", or "Fatigued"
- `hrv`: HRV metrics (today's value, baseline, trend, CV)
- `sleep`: Sleep score (if available)
- `rhr`: Resting HR metrics (if available)

Format as a compact summary:
- Recovery: Fresh/Normal/Fatigued
- HRV: today's value vs baseline, trend direction
- Sleep: score (if available)
- RHR: today's value vs baseline (if available)

**Show the methodology.** The `science` object has the active theories. Include
the recovery theory name in the header (e.g., "Recovery (HRV-Based Recovery)")
and after the recovery data, add a brief methodology note:

- For `hrv_based`: "Recovery status uses ln(RMSSD) compared to your personal
  baseline. Fresh = above SWC (Plews et al, 2012). Fatigued = below baseline
  minus 1 SD (Kiviniemi et al, 2007). Recovery requires HRV; if HRV data is
  missing/insufficient, recovery status and suggestions are not provided."

Include the citation from `science.recovery.citations` (title + year).
This matters because the system's value proposition is scientific rigor —
users should see the same methodology transparency in the CLI as in the web UI.

### 3. Upcoming Workouts

The `upcoming_workouts` array has the next 3 planned workouts:
- `date`, `workout_type`, `duration_min`, `description`

Show as a simple list with day-of-week, type, and duration.

### 4. Last Activity

The `last_activity` object has:
- `date`, `distance_km`, `duration_sec`, `avg_power`/`avg_pace_min_km`, `rss`

One-line summary of the most recent workout.

### 5. Weekly Load

The `week_load` object compares this week's load to plan:
- `actual`: current week's accumulated load
- `planned`: planned load (if available)

### 6. Warnings

The `warnings` array contains active alerts:
- HRV declining, high fatigue, plan staleness, etc.

Show any warnings prominently.

## Scientific Rigor

The CLI should convey the same scientific transparency as the web dashboard.
The `science` object in the output contains the active theory for each pillar
(load, recovery, prediction, zones) with name, description, and citations.

For each section of the brief, show how the metric is calculated:

- **Training Signal**: Note the load model (e.g., "Banister PMC: CTL tau=42d,
  ATL tau=7d") and how TSB feeds into the recommendation
- **Recovery**: Show the recovery theory name and protocol (see above)
- **Weekly Load**: Note the load metric (RSS = power-based, TRIMP = HR-based)

Keep methodology notes concise — one line per metric, not paragraphs. The goal
is transparency, not a textbook. Format as small-text notes below each section,
similar to the web UI's expandable "How this is calculated" notes.

## Interpretation

After presenting the data, add a brief AI interpretation:
- Connect recovery status to the training signal
- If upcoming workout is hard and recovery is low, flag the conflict
- If weekly load is significantly above/below plan, note it
- Keep it to 2-3 sentences — actionable, not verbose

## Display Config

The `display` object tells you units and labels for the active training base:
- `threshold_unit`: "W", "bpm", or "/km"
- `threshold_abbrev`: "CP", "LTHR", or "T-Pace"
- `load_label`: "RSS", "TRIMP", or "rTSS"

Use these for correct unit display.
