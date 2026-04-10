---
name: training-review
description: >-
  Analyze recent training: volume trends, consistency, interval quality,
  zone distribution vs targets, CP/threshold trend, fitness/fatigue balance,
  and actionable suggestions. Use this skill when the user asks "how's my
  training going", "diagnose my training", "analyze my running", "training
  analysis", "zone distribution", "why isn't my CP improving", "training
  review", "weekly report", "check my volume", "am I doing enough threshold
  work", "training summary", "what should I change", or any request to
  evaluate recent training patterns and get improvement suggestions.
---

# Training Review

Provide a comprehensive analysis of recent training without the web dashboard.

## Gathering Data

Run the diagnosis script from the project root:

```bash
python skills/training-review/scripts/run_diagnosis.py --pretty
```

This calls `get_dashboard_data()` and extracts the diagnosis, fitness summary,
threshold trend, weekly compliance, and workout flags.

## Presenting the Review

Structure the output in this order, using the `display` config for correct units:

### 1. Current Fitness Snapshot

From `fitness_summary`:
- **CTL** (Chronic Training Load / fitness): higher = fitter
- **ATL** (Acute Training Load / fatigue): higher = more tired
- **TSB** (Training Stress Balance / form): CTL - ATL. Negative = fatigued, positive = fresh

From `latest_threshold` + `threshold_trend`:
- Current threshold value (CP in watts, LTHR in bpm, or pace)
- Trend direction: improving / stable / declining + magnitude

### 2. Volume Analysis

From `diagnosis.volume`:
- `weekly_avg_km`: average weekly distance
- `trend`: increasing / stable / decreasing

### 3. Consistency

From `diagnosis.consistency`:
- `total_sessions`: how many sessions in the lookback period
- `weeks_with_gaps`: weeks with fewer than 3 sessions
- `longest_gap_days`: longest break between activities

### 4. Interval Intensity

From `diagnosis.interval_power` (or `interval_hr`/`interval_pace` depending on base):
- `max`: peak split intensity
- `avg_work`: average of work-intensity splits
- `supra_cp_sessions`: sessions with threshold-level stimulus (critical for progression)
- `total_quality_sessions`: sessions with >80% threshold intensity

This section is the most important for athletes asking "why isn't my CP improving" —
supra-threshold stimulus is the key driver.

### 5. Zone Distribution

From `diagnosis.distribution` (array of zone objects):
- Each entry: `name`, `actual_pct`, `target_pct`

Present as a table:

| Zone | Actual | Target | Status |
|------|--------|--------|--------|
| Easy | 72% | 80% | -8% under |
| Threshold | 15% | 8% | +7% over |

Flag any zone deviation >5 percentage points.

From `diagnosis.zone_ranges`:
- Show the actual intensity ranges for each zone (e.g., "Easy: 0-138W")

### 6. Findings & Suggestions

From `diagnosis.diagnosis` (array of finding objects):
- Each: `type` (positive/warning/neutral), `message`

From `diagnosis.suggestions` (array of strings):
- Actionable next steps

Present findings with visual indicators:
- Positive: checkmark or +
- Warning: exclamation or !
- Neutral: dash or -

### 7. Weekly Compliance (if available)

From `weekly_review`:
- `weeks`: week labels
- `actual_rss`: actual weekly load
- `planned_rss`: planned weekly load (if plan exists)

Show last 4-8 weeks as a compact comparison.

### 8. Workout Flags (if available)

From `workout_flags`:
- Sessions flagged as notably better or worse than expected
- Context: low readiness + high performance = breakthrough; high readiness + low performance = concern

## Scientific Methodology

The `science` object in the output contains active theories with names and citations.
Show methodology notes to maintain the same scientific transparency as the web dashboard:

- **Fitness/Fatigue**: Name the load model (e.g., "Banister PMC") and time constants
  (CTL tau, ATL tau). Note the load metric formula (RSS, TRIMP, or rTSS).
- **Zone Distribution**: Name the zone framework (e.g., "Coggan 5-Zone") and show
  zone boundaries as % of threshold. Note the target distribution source.
- **Threshold Trend**: Note how threshold is detected (e.g., "CP auto-detected from
  Stryd" or "LTHR from Garmin lactate threshold test").
- **Diagnosis**: When showing supra-threshold sessions, note the threshold used
  (>98% of CP/LTHR) and cite why this matters for progression.

Format as concise one-line notes after each section. Include the citation
(title + year) from `science.{pillar}.citations` where relevant.

## AI Interpretation

After presenting the data, provide a synthesized interpretation:

1. **Headline**: One sentence summarizing training state (e.g., "Training volume is strong but lacks threshold stimulus")
2. **Key insight**: Connect the most important finding to a concrete recommendation
3. **Priority action**: The single most impactful change the athlete should make

Keep interpretation to 3-5 sentences. Be direct and specific — reference actual
numbers from the data (e.g., "Only 1 supra-CP session in 6 weeks — aim for 2-3").

## Display Config

The `display` object provides dynamic labels:
- `threshold_unit`: "W", "bpm", or "/km"
- `threshold_abbrev`: "CP", "LTHR", or "T-Pace"
- `load_label`: "RSS", "TRIMP", or "rTSS"
- `zone_type`: "power", "hr", or "pace"

Always use these for unit display to match the user's configured training base.
