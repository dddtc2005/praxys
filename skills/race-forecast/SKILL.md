---
name: race-forecast
description: >-
  Race time prediction and goal feasibility analysis. Shows predicted finish
  time, compares to target, calculates required threshold improvement, and
  assesses whether the goal is achievable. Use this skill when the user asks
  "can I hit sub-3", "race prediction", "what's my predicted marathon time",
  "race forecast", "goal feasibility", "how fast can I run", "time prediction",
  "will I make my goal", "what CP do I need", "how much do I need to improve",
  or any request about race time estimates and goal tracking.
---

# Race Forecast

Provide race time predictions and goal feasibility analysis without the web dashboard.

## Gathering Data

Run the forecast script from the project root:

```bash
python skills/race-forecast/scripts/race_forecast.py --pretty
```

This outputs JSON with race countdown, threshold data, and fitness snapshot.

## Presenting the Forecast

### 1. Race Countdown (if race goal set)

From `race_countdown`:
- `days_to_race`: days remaining
- `race_date`: the target date
- `distance_label`: e.g., "Marathon", "Half Marathon", "50K"

If no race date is set, note that the user is in continuous improvement mode
and predictions are still available.

### 2. Current Prediction

From `race_countdown`:
- `predicted_time_sec`: current predicted finish time based on threshold + model
- `predicted_time_formatted`: human-readable time (e.g., "3:05:22")

Present the predicted time prominently.

### 3. Goal Comparison (if target time set)

From `race_countdown`:
- `target_time_sec`: the user's goal time
- `target_time_formatted`: human-readable target
- `gap_sec`: difference between predicted and target (negative = ahead of goal)
- `gap_formatted`: human-readable gap

From `race_countdown`:
- `required_cp`: threshold value needed to hit the target time
- `current_cp`: current threshold value
- `cp_gap`: difference (how much improvement needed)
- `cp_gap_pct`: percentage improvement needed

### 4. Threshold Trend

From `threshold_trend`:
- `direction`: "improving", "stable", or "declining"
- `magnitude`: rate of change
- `recent_values`: recent threshold measurements

This tells the athlete whether they're moving toward or away from their goal.

### 5. Feasibility Assessment

From `race_countdown` (when available):
- `honesty_check`: assessment of whether the goal is realistic

Also from `fitness_snapshot`:
- Current CTL (fitness level), ATL (fatigue), TSB (form)

## AI Interpretation

After presenting the data, provide a brief assessment:

1. **Headline**: "On track" / "Behind target" / "Ahead of schedule"
2. **Time gap context**: How significant is the gap? (e.g., "2 minutes off target
   for a marathon is very achievable with 8 weeks of focused training")
3. **Threshold trajectory**: Is the trend heading the right direction? At what rate?
4. **Actionable insight**: What would close the gap (e.g., "Increasing supra-CP
   sessions from 1 to 2-3 per mesocycle would drive the CP improvement needed")

If no goal is set, focus on:
- Current predicted times across standard distances
- Recent threshold trend
- Suggest setting a goal if they want targeted analysis

## Time Formatting

Convert seconds to human-readable format:
- Marathon/ultra: "3:05:22" (H:MM:SS)
- 5K/10K: "22:15" (MM:SS) or "45:30" (MM:SS)

## Display Config

Use `display` for correct threshold labels:
- `threshold_abbrev`: "CP", "LTHR", or "T-Pace"
- `threshold_unit`: "W", "bpm", or "/km"
