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

Generate or update a personalized training plan based on the athlete's current
fitness data, training history, recovery state, and goal.

## Step 1: Gather Training Context

Run the context builder to get current training data:

```bash
python scripts/build_training_context.py --pretty
```

Read the JSON output carefully. This is the athlete's complete training profile
including: current fitness (CTL/ATL/TSB), threshold (CP/LTHR/pace), recent
training history with splits, recovery state (HRV/sleep), and current plan.

## Step 1.5: Assess Existing Plan

Check `current_plan` in the context. This contains remaining future workouts
from the existing plan (if any).

**If there IS an existing plan**, compare planned vs actual:
- Which workouts were completed as planned? (match `current_plan` dates against
  `recent_training.sessions` dates)
- Which were missed or substituted?
- Has the athlete's fitness/recovery changed significantly since the plan was
  generated? (check `current_fitness.tsb`, recovery state, CP trend)
- Is the plan stale? (check warnings for staleness alerts)

Then decide:
- **Update** — if the plan is recent and mostly on track, modify the remaining
  workouts to account for what actually happened (e.g., missed a threshold session
  → reschedule it, volume was low → adjust progression). Keep the overall
  mesocycle structure.
- **Extend** — if the plan is nearing its end (fewer than 7 days left), generate
  the next 4-week block as a continuation, building on the current mesocycle phase.
- **Regenerate** — if the plan is stale (>4 weeks old), CP has drifted significantly,
  the athlete missed most sessions, or the user explicitly asks for a fresh plan.

Ask the user which approach they want if it's ambiguous. If the user said
"update my plan" → update. If "generate a new plan" → regenerate.

**Regardless of which approach you choose** — update, extend, or regenerate —
the new plan must connect logically to the athlete's recent training. Even a
"regenerate" is not a blank slate. The athlete has training history, momentum,
and a position in their training cycle. Step 2's "Continuity First" section
explains how to determine where they are and what comes next.

**If there is NO existing plan**, proceed to generate a plan — but still treat
the athlete's recent training history as the "previous plan." They've been
training; the new plan picks up from where their self-directed training left off.

## Step 1.75: Validate Threshold Estimate

Auto-calculated thresholds (Stryd auto-CP, Garmin threshold estimates) can be
unreliable. A bad threshold cascades into wrong zone boundaries, misleading
zone distribution diagnoses, and incorrectly targeted workouts. Before building
the plan, cross-reference the reported threshold against actual performance.

### Check for recalibration artifacts

Look at `cp_estimate` (or equivalent threshold) across recent sessions. If the
value drops >10W within a few days without a corresponding performance decline
in the quality sessions, it's likely a device recalibration artifact — not a
real fitness change. Signs of an artifact:
- Sudden step-change in CP (e.g., 271→255→248 over a week)
- Quality session power outputs remain consistent before and after the drop
- Athlete reports no change in perceived effort on easy or hard runs

### Estimate working threshold from performance data

Scan recent sessions for sustained hard efforts (splits >230W held for 5+
minutes). The best recent 20-minute sustained power is the gold standard:
- **Working CP ≈ best 20-minute power × 0.95–1.00**
- If no 20-minute effort exists, use the best 15-minute power × 0.97 or
  10-minute power × 0.92

Also consider: if the athlete holds X watts for a 30-minute block inside a
long run, their CP is likely ≥ X.

### Cross-check with subjective effort

If the athlete provides feedback on how efforts feel:
- Runs at 75-80% of reported CP "feel easy" → CP is probably understated
- Threshold sessions at 95% CP feel moderate → CP is probably understated
- Easy runs feel hard at 70% CP → CP might be overstated (or non-CP fatigue)

### Decide which threshold to use

Compare the reported threshold (`athlete_profile.threshold`) against your
estimated working threshold:
- **Within 5%**: Use the reported value. It's close enough.
- **Working threshold is 5-15% higher**: Use the working threshold for all zone
  calculations and power targets. Tell the athlete: "Your device CP (XXX W)
  appears understated based on recent efforts. Using a working CP of YYY W for
  this plan."
- **Working threshold is >15% higher**: Something unusual is going on (device
  issue, very stale CP, or the hard efforts were short enough to be above true
  CP). Flag this to the athlete and ask for confirmation before proceeding.
- **Working threshold is lower**: The reported value may be stale from a fitter
  period. Use the working threshold.

**Carry the validated working threshold forward into all subsequent steps.**
Zone boundaries, power targets, and zone distribution analysis must use this
value, not the raw device number.

## Step 2: Analyze and Generate Plan

Using the training context, generate or update the training plan. The context
includes a `science` section with the user's active training theories — use these
instead of assuming a specific framework.

### Continuity First — This Is Not a Fresh Start

The athlete is always mid-training. A new plan is a continuation of their
existing training arc, not a reset. Before deciding structure:

1. **Read the training arc.** Look at `recent_training.weekly_summary` (6-8
   weeks back) and identify the pattern:
   - Has volume been building, stable, or declining?
   - Was the most recent full week a build week, a peak, or a recovery?
   - Are there signs of an existing periodization rhythm (e.g., 3 hard weeks
     then a lighter week)?

2. **Determine where they are in the cycle.** Examples:
   - Just finished a peak week (highest volume/load in the window) → next week
     should be recovery or a slight step-back, then resume building
   - In the middle of a build phase with stable volume → continue the build,
     adding 5-10% per week
   - Just had a recovery/light week → ready to build again
   - Coming off illness/travel gap → re-entry week at ~80% of pre-gap volume

3. **Continue the progression, don't restart it.** If the athlete has been
   building from 55→60→65→70km, the plan should pick up from where that
   leaves off (e.g., recovery week at 48km, then next build starting at 60km).
   Don't drop them to 45km "Week 1" just because the plan is new.

4. **Respect what's working.** If the athlete's current workout pattern is
   producing good results (consistent sessions, hitting power targets, good
   recovery), preserve it. Change what needs changing, not everything.

### Volume Anchoring — Anchor to Recent History

Extract the athlete's recent baselines from `recent_training.weekly_summary`
and individual sessions:
- **Recent weekly average** (last 4-6 full weeks of consistent training)
- **Recent peak week** (highest volume in that window)
- **Recent long run distances** (longest run each week from session data)
- **Current week status** (partial week — how much has already been done?)

These baselines anchor the plan. Never prescribe volumes dramatically different
from what the athlete has been doing unless there's a specific reason (injury
return, taper, overreaching recovery). Rules of thumb:
- **First full week** should relate logically to the last full week — if the
  last full week was a peak, this week is recovery; if it was moderate, this
  week continues the build
- **Peak build week** can exceed the recent peak by up to ~10%
- **Recovery week** should be ~60-70% of the peak build week
- **Long runs** should progress from the athlete's recent long run distance, not
  start from scratch. If they've been doing 25-28km long runs, don't prescribe
  18km. Continue from where they are.

Show your reasoning: when presenting the plan, include a note like "You've been
averaging 62km/week with a 70km peak in W14. Plan continues: 63→70→48→60km."
This helps the athlete verify the plan connects to their training reality.

### Periodization
- Use rolling 4-week mesocycles — but adapt the structure to where the athlete
  is in their current cycle. Don't force "3 build + 1 recovery" if they just
  finished 3 build weeks and need recovery first. The pattern might be
  "1 recovery + 3 build" or "2 build + 1 recovery + 1 build" depending on
  context.
- Build weeks increase weekly load by 5-10% over the previous week
- Recovery week reduces volume to ~60-70% of peak build week

### Workout Distribution — Read from Science Context

The context includes `science.zones` with the user's active zone framework:
- `science.zones.name`: the theory name (e.g., "Coggan 5-Zone" or "Seiler Polarized 3-Zone")
- `athlete_profile.zone_names`: zone names for the active training base (e.g., ["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"])
- `athlete_profile.target_distribution`: target fraction per zone (e.g., [0.80, 0.10, 0.05, 0.03, 0.02])
- `athlete_profile.zones`: zone boundary fractions of threshold (e.g., [0.55, 0.75, 0.90, 1.05])

**Use these values to define workout targets.** For example:
- If Coggan 5-Zone with boundaries [0.55, 0.75, 0.90, 1.05] and CP=250W:
  Zone 1 (Easy): <138W, Zone 2 (Tempo): 138-188W, Zone 3 (Threshold): 188-225W, etc.
- If Seiler 3-Zone with boundaries [0.80, 1.00] and CP=250W:
  Zone 1 (Easy): <200W, Zone 2 (Moderate): 200-250W, Zone 3 (Hard): >250W

**Distribution rules** (universal regardless of theory):
- Maximum 3 quality sessions per week
- At least 1 full rest or recovery day per week
- If `target_distribution` is provided, match it. Otherwise default to ~80% easy / ~20% quality
  (Seiler 2010, "What is Best Practice for Training Intensity and Duration Distribution?")

### Power/Intensity Zone Targets

Calculate zone ranges from `athlete_profile.zones` (boundary fractions) and
`athlete_profile.threshold` (current CP/LTHR/pace). Present workout targets
using the zone names from `athlete_profile.zone_names`.

Do NOT hardcode zone boundaries — always derive from the context.

### Key Considerations
- **Use the validated working threshold from Step 1.75** for all zone boundaries
  and power targets — never blindly trust auto-CP or device-reported thresholds.
  A deflated CP leads to deflated targets, false zone distribution warnings, and
  a plan that's too easy. An inflated CP leads to unachievable targets.
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

### Scientific Methodology

When presenting the plan, note the science framework driving it:
- **Zone framework**: Name the active theory (from `science.zones.name`) and show
  the zone boundaries used. E.g., "Zones: Coggan 5-Zone (Easy <55% CP, Tempo 55-75%, ...)"
- **Load model**: Name the model (from `science.load.name`) and its parameters.
  E.g., "Load: Banister PMC (CTL tau=42d, ATL tau=7d)"
- **Distribution target**: Show the target zone distribution from the theory.
  E.g., "Target: 5% Recovery, 70% Endurance, 10% Tempo, 10% Threshold, 5% VO2max"

This ensures the user knows which scientific framework is shaping their plan.

## Step 3: Generate Coaching Narrative

Write a coaching narrative explaining:
1. **Current Assessment** — where the athlete is right now (fitness, fatigue, CP trend).
   If the working threshold differs from the device-reported value, explain why and
   what evidence supports the working estimate.
2. **Volume & Structure Rationale** — explain _why_ each week has the volume it
   does, anchored to recent history. Cover: why week 1 is build/transition/recovery,
   how weekly km progresses and why, how long run distances progress, and what the
   recovery week ratio is. The athlete should be able to see the logic connecting
   their recent training to the prescribed volumes.
3. **4-Week Phase** — what this mesocycle focuses on and why
4. **Key Sessions** — explain the 2-3 most important workouts and their purpose
5. **Watch-For Signals** — when the athlete should modify the plan (signs of overreaching, illness, etc.)
6. **Expected Outcomes** — what improvement to expect if the plan is followed

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
  "generated_at": "ISO timestamp (first generation)",
  "revised_at": "ISO timestamp (if this is an update, set to now; omit on fresh generation)",
  "plan_start": "first workout date",
  "plan_end": "last workout date",
  "cp_at_generation": <current CP from context>,
  "goal_at_generation": <goal from context>,
  "model": "claude model used"
}
```

For updates: preserve `generated_at` from the existing meta, add/update `revised_at`.
For fresh plans: set `generated_at` to now, omit `revised_at`.

Create the `data/ai/` directory if it doesn't exist.

After writing, remind the user: "To use this plan in the dashboard, set your
plan source to 'AI' in Settings (or use the `setup` skill)."

## Optional: Push to Stryd

If the user wants to sync the plan to their Stryd watch, they can either:

1. **Use the dashboard** — the plan page has a push-to-Stryd button per workout
2. **Call the API** (if the server is running):
   ```bash
   curl -X POST http://localhost:8000/api/plan/push-stryd \
     -H "Content-Type: application/json" \
     -d '{"workout_dates": ["2026-04-11", "2026-04-12"]}'
   ```

This requires Stryd credentials in `sync/.env`.
