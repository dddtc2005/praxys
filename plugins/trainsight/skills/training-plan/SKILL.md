---
name: training-plan
description: >-
  Generate a personalized 4-week AI training plan based on current fitness,
  training history, recovery state, and goals. Use this skill when the user
  asks to "generate a training plan", "create a plan", "what should I run
  this week", "plan my next 4 weeks", "regenerate my plan", "update my
  training plan", "build me a training plan", "plan my training", "make a
  plan for my marathon", or any request to create, modify, or update a
  running training plan. Also use when the user mentions their current plan
  is stale or outdated.
---

# Generate AI Training Plan

Follow these steps exactly. Use only MCP tools — no shell scripts.

## Step 1: Get Data

Call `get_training_context`. This returns everything needed in one call:
- `athlete_profile`: threshold, zones, training base, target distribution
- `current_fitness`: CTL, ATL, TSB
- `recent_training`: weekly summaries, individual sessions with splits
- `recovery_state`: HRV, sleep, readiness
- `current_plan`: existing future workouts (if any)
- `science`: active theories for load, zones, prediction

## Step 2: Analyze (do NOT call any tools — just reason)

From the context, determine:

1. **Working threshold**: Cross-check `athlete_profile.threshold` against best
   sustained power in recent splits. If device CP differs >5% from performance,
   note the working value to use.

2. **Where they are in the training cycle**: Read `recent_training.weekly_summary`
   — is volume building, peaking, or recovering? What comes next logically?

3. **Plan decision**: If existing plan exists and is recent → update remaining days.
   If stale or user asked for new → regenerate from current position.

4. **Start date**: Check if today has an activity → start tomorrow. Otherwise start today.

## Step 3: Generate Plan

Create a 28-day plan as a JSON array. Use the athlete's zone framework from `science.zones`:

```json
[
  {"date": "YYYY-MM-DD", "workout_type": "easy", "planned_duration_min": 50,
   "planned_distance_km": 10.0, "target_power_min": 150, "target_power_max": 190,
   "workout_description": "Easy aerobic run in Zone 2"}
]
```

Rules:
- Max 3 quality sessions per week, at least 1 rest day
- Volume anchored to recent weekly average (±10% per build week, 60-70% for recovery)
- Long run progresses from recent long run distance
- Power targets derived from zones in `athlete_profile`
- 3 build weeks + 1 recovery week (but adapt to where athlete is in cycle)

## Step 4: Present for Review

Show the plan as a table:

| Date | Day | Type | Duration | Distance | Power | Description |
|------|-----|------|----------|----------|-------|-------------|

Below the table, add a brief coaching note (3-5 sentences):
- Current assessment (fitness/fatigue state)
- Why this structure (volume progression logic)
- Key sessions to prioritize

Ask: "Does this look good? I can adjust intensity, swap workouts, or regenerate."

## Step 5: Save (on user approval only)

Convert the plan to CSV and call `push_training_plan`:

```
date,workout_type,planned_duration_min,planned_distance_km,target_power_min,target_power_max,workout_description
2026-04-18,easy,50,10.0,150,190,Easy aerobic run in Zone 2
```

Tell the user: "Plan saved. Set your plan source to 'AI' in Settings to see it on the dashboard."
