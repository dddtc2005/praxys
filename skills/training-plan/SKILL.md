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

Generate a personalized 4-week rolling training plan based on the athlete's
current fitness data, training history, recovery state, and goal.

## Step 1: Gather Training Context

Run the context builder to get current training data:

```bash
python scripts/build_training_context.py --pretty
```

Read the JSON output carefully. This is the athlete's complete training profile
including: current fitness (CTL/ATL/TSB), threshold (CP/LTHR/pace), recent
training history with splits, recovery state (HRV/sleep), and current plan.

## Step 2: Analyze and Generate Plan

Using the training context, generate a 4-week (28-day) training plan following
these exercise science principles:

### Periodization
- Use rolling 4-week mesocycles: 3 progressive build weeks + 1 recovery week
- Build weeks increase weekly load by 5-10% over the previous week
- Recovery week reduces volume to ~60-70% of peak build week

### Workout Distribution (80/20 Polarized Model)
- ~80% of sessions should be easy/aerobic (Zone 1-2)
- ~20% should be quality sessions: tempo (Zone 3), threshold (Zone 4), intervals (Zone 5)
- Maximum 3 quality sessions per week
- At least 1 full rest or recovery day per week
- Reference: Seiler (2010) "What is Best Practice for Training Intensity and Duration Distribution?"

### Power Zone Targets (relative to threshold/CP)
- Recovery: < 55% CP
- Easy/Aerobic: 55-75% CP
- Tempo: 75-90% CP
- Threshold: 90-105% CP
- Intervals/VO2max: 105-120% CP
- Reference: Coggan power zones; Stryd race power model

### Key Considerations
- **Use split-level data** from recent sessions to assess if the athlete is
  actually hitting prescribed intensities (activity avg_power is diluted by
  warmup/cooldown)
- **Respect recovery state**: if HRV is declining or readiness is low, prescribe
  easier sessions early in the plan
- **Consider TSB**: if TSB is very negative (high fatigue), start with a recovery
  mini-block
- **Goal-specific**: for marathon targeting, include weekly long runs progressing
  to 30-35km, threshold sessions at marathon-specific power, and tempo runs

### Output Format

Generate the plan as a JSON array of workout objects:

```json
[
  {
    "date": "YYYY-MM-DD",
    "workout_type": "easy|recovery|tempo|threshold|interval|long_run|rest|steady_aerobic|speed",
    "planned_duration_min": 60,
    "planned_distance_km": 12.0,
    "target_power_min": 150,
    "target_power_max": 200,
    "workout_description": "Easy aerobic run. Keep power in Zone 1-2. Focus on relaxed form."
  }
]
```

For rest days, use `workout_type: "rest"` with no duration/distance/power targets.

## Step 3: Generate Coaching Narrative

Write a coaching narrative explaining:
1. **Current Assessment** — where the athlete is right now (fitness, fatigue, CP trend)
2. **4-Week Phase** — what this mesocycle focuses on and why
3. **Key Sessions** — explain the 2-3 most important workouts and their purpose
4. **Watch-For Signals** — when the athlete should modify the plan (signs of overreaching, illness, etc.)
5. **Expected Outcomes** — what improvement to expect if the plan is followed

## Step 4: Validate the Plan

Save the plan JSON to a temporary variable, then validate it:

```bash
python -c "
import json, sys
sys.path.insert(0, '.')
from api.ai import validate_plan, build_training_context
context = build_training_context()
plan = json.loads('''PASTE_PLAN_JSON_HERE''')
valid, errors = validate_plan(plan, context)
if valid:
    print('Plan is valid.')
else:
    print('Validation errors:')
    for e in errors:
        print(f'  - {e}')
"
```

If validation fails, fix the issues and re-validate. Common issues:
- Dates not starting from today or tomorrow
- Power targets outside 40-130% of current CP
- Missing rest days
- More than 3 quality sessions in a week

## Step 5: Display for Review

Present the plan to the user as a formatted table:

| Date | Day | Type | Duration | Distance | Power Target | Description |
|------|-----|------|----------|----------|-------------|-------------|

Include the coaching narrative below the table.

Ask the user: "Does this plan look good? I can adjust specific workouts,
change the overall intensity, or regenerate."

## Step 6: Write Plan Files (on approval)

Once the user approves, write three files:

### 1. Training Plan CSV
Write to `data/ai/training_plan.csv`:
```
date,workout_type,planned_duration_min,planned_distance_km,target_power_min,target_power_max,workout_description
```

### 2. Plan Narrative
Write to `data/ai/plan_narrative.md` — the coaching narrative from Step 3.

### 3. Plan Metadata
Write to `data/ai/plan_meta.json`:
```json
{
  "generated_at": "ISO timestamp",
  "plan_start": "first workout date",
  "plan_end": "last workout date",
  "cp_at_generation": <current CP from context>,
  "goal_at_generation": <goal from context>,
  "model": "claude model used"
}
```

Create the `data/ai/` directory if it doesn't exist.

After writing, remind the user: "To use this plan in the dashboard, set your
plan source to 'AI' in Settings (or use the `setup` skill)."

## Optional: Push to Stryd

If the user wants to sync the plan to their Stryd watch, they can use the
dashboard's push-to-Stryd feature, or run:

```bash
python -c "
import sys, json
sys.path.insert(0, '.')
from api.routes.plan import _push_to_stryd
# Push specific dates
results = _push_to_stryd(['YYYY-MM-DD', ...])
print(json.dumps(results, indent=2))
"
```

This requires Stryd credentials in `sync/.env`.
