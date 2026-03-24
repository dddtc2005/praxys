# AI Training Plan Generation — Design Spec

**Date:** 2026-03-24
**Status:** Draft

## Problem

The athlete has shifted from a race-date goal (sub-3 marathon by specific date) to continuous improvement targeting sub-3 hours. The app computes rich training metrics and provides daily signals, but cannot generate or suggest structured training plans. Currently, plans come only from Stryd's CSV — there's no way for the system to create a personalized, adaptive plan based on the athlete's actual fitness state, training history, and goal.

## Solution

Build an AI-powered training plan generator with two layers:

1. **Training context builder** (`api/ai.py`) — serializes all computed metrics into a structured format optimized for LLM consumption
2. **Claude Code skill** (`/training-plan`) — invokes the context builder, sends to Claude, generates a 4-week rolling plan

The skill writes output to `data/ai/training_plan.csv`, which is served by a new `AiPlanProvider` through the existing plan provider interface. All downstream UI (UpcomingPlanCard, daily signal, compliance) works automatically.

## Architecture

```
analysis/metrics.py (existing pure functions)
        ↓
api/ai.py → build_training_context()
        ↓ (serialized athlete context)
Claude Code skill: /training-plan
        ↓ (Claude API call)
data/ai/training_plan.csv  ← AiPlanProvider reads this
data/ai/plan_narrative.md  ← coaching rationale
data/ai/plan_meta.json     ← generation metadata
        ↓
Existing plan pipeline (UpcomingPlanCard, daily signal, compliance)
```

## Component Design

### 1. Training Context Builder — `api/ai.py`

**File:** `api/ai.py` (new)

**Functions:**

- `build_training_context() -> dict` — calls `get_dashboard_data()` and reshapes into LLM-optimized structure

**Context structure:**

```python
{
    "athlete_profile": {
        "training_base": "power",          # from config
        "cp_watts": 268.5,                 # latest threshold
        "goal": {
            "distance": "marathon",
            "target_time_sec": 10800,
            "mode": "continuous"            # no race_date = continuous
        },
        "zones": {                          # from config.zones
            "power": [0.55, 0.75, 0.90, 1.05]
        }
    },
    "current_fitness": {
        "ctl": 45.2,                       # chronic training load (42-day)
        "atl": 38.1,                       # acute training load (7-day)
        "tsb": 7.1,                        # training stress balance
        "cp_trend": {
            "direction": "rising",
            "slope_per_month": 2.3
        },
        "predicted_time_sec": 11200,       # current marathon prediction
        "race_countdown": { ... }          # full race countdown payload
    },
    "recent_training": {
        "diagnosis": { ... },              # from diagnose_training()
        "weekly_summary": [                # last 8 weeks
            {"week": "W10", "volume_km": 48, "load": 320, "sessions": 5}
        ],
        "sessions": [                      # last 8 weeks of individual workouts
            {
                "date": "2026-03-22",
                "type": "threshold",
                "distance_km": 12.5,
                "duration_sec": 3600,
                "avg_power": 220,
                "splits": [                # per-lap data (critical for interval analysis)
                    {"split_num": 1, "avg_power": 185, "duration_sec": 600},
                    {"split_num": 2, "avg_power": 248, "duration_sec": 1200},
                    ...
                ]
            }
        ]
    },
    "recovery_state": {
        "readiness": 75,
        "hrv_ms": 42,
        "hrv_trend_pct": +3.2,
        "sleep_score": 82
    },
    "current_plan": [                      # existing plan workouts (if any)
        {"date": "2026-03-25", "workout_type": "easy", ...}
    ]
}
```

**Key design decisions:**
- Reuses `get_dashboard_data()` — no new computation
- Includes individual sessions with splits (not just aggregates) so AI can assess actual interval quality
- Includes current plan so AI can see what was scheduled vs. what was done
- When re-generating an AI plan, `current_plan` shows the *previous* AI plan. The prompt instructs the AI to treat this as context (what was attempted) rather than iterating on it — the new plan should be generated fresh from current fitness state.

### 2. AI Plan Provider — `analysis/providers/ai.py`

**File:** `analysis/providers/ai.py` (new)

**Class:** `AiPlanProvider(PlanProvider)`

- `name = "ai"`
- `load_plan()` reads `data/ai/training_plan.csv` using the same schema as Stryd's plan
- Registered in `analysis/providers/__init__.py` alongside Stryd

**Plan CSV schema** (full `PLAN_REQUIRED` + `PLAN_OPTIONAL` from `models.py`):
```
date,workout_type,planned_duration_min,planned_distance_km,target_power_min,target_power_max,target_hr_min,target_hr_max,target_pace_min,target_pace_max,workout_description
```
The AI populates target columns matching the athlete's `training_base` (power targets for power-based, HR targets for HR-based, pace targets for pace-based).

**Config integration — `PlanSource` type:**

The existing `PlatformName` type is `"garmin" | "stryd" | "oura" | "coros"` — a closed union for hardware platforms. AI is not a platform, so we introduce a new type:
- Add `PlanSource = Literal["garmin", "stryd", "oura", "coros", "ai"]` in `analysis/config.py`
- `config.preferences["plan"]` uses `PlanSource` instead of `PlatformName`
- Add `PlanSourceName` type in `web/src/types/api.ts`: `"garmin" | "stryd" | "oura" | "coros" | "ai"`
- `PLATFORM_CAPABILITIES` is NOT modified — AI is not a platform. Instead, the plan preference allows `"ai"` as a special value.
- Settings UI shows "AI" as a plan source option when `data/ai/training_plan.csv` exists

### 3. Plan Metadata — `data/ai/plan_meta.json`

Tracks when and how the plan was generated:
```json
{
    "generated_at": "2026-03-24T10:30:00",
    "plan_start": "2026-03-24",
    "plan_end": "2026-04-20",
    "cp_at_generation": 268.5,
    "goal_at_generation": {"distance": "marathon", "target_time_sec": 10800},
    "model": "claude-sonnet-4-6",
    "context_hash": "abc123"
}
```

### 4. Claude Code Skill — `/training-plan`

**File:** Skill markdown file in the repo (exact location TBD based on skill structure)

**Workflow:**
1. Run `scripts/build_training_context.py` via bash — a CLI entry point that imports `build_training_context()` and outputs JSON to stdout. The skill reads this JSON as the training context. (Claude Code skills are markdown instruction files — they cannot import Python directly.)
2. The skill (Claude) receives the context JSON and uses it as grounding for plan generation
3. System prompt encodes exercise science:
   - Periodization: rolling 4-week mesocycles (3 build + 1 recovery)
   - Progressive overload: ~5-10% weekly load increase during build weeks
   - Distribution: ~80/20 polarized (easy/quality), adapted to continuous improvement
   - Power zones: easy 55-75% CP, tempo 75-90%, threshold 90-105%, intervals 105%+
   - Recovery constraints: respect TSB, HRV trends, readiness scores
   - Split-level analysis: use per-lap power (not diluted activity avg) for interval assessment
4. Claude generates structured JSON matching plan CSV schema
5. Display plan summary in terminal for review
6. On approval: write `data/ai/training_plan.csv`, `plan_narrative.md`, `plan_meta.json`

**System prompt principles:**
- Cite exercise science sources (Lydiard, Fitzgerald 80/20, Seiler polarized model)
- Flag estimates vs. well-researched values
- Explain the "why" for each workout prescription
- Consider the athlete's actual performance (splits) vs. prescribed intensity

### 5. Plan Narrative — `data/ai/plan_narrative.md`

Human-readable coaching document generated alongside the plan:
- Current assessment (where you are)
- 4-week phase description (what we're focusing on)
- Key workouts explained (why this specific session)
- Watch-for signals (when to modify the plan)
- Expected outcomes (what improvement to expect)

### 6. Plan Validation

Before writing the AI-generated plan to CSV, validate:
- **Date range:** all dates are in the future (today or later), spanning exactly 28 days
- **Power targets:** within 40-130% of current CP (rejects absurd values like 500W for a 268W CP athlete)
- **Required fields:** every row has `date` and `workout_type`
- **Completeness:** no missing days in the 4-week window
- **Distribution sanity:** at least 1 rest day per week, no more than 3 quality sessions per week

Validation is a pure function in `api/ai.py`: `validate_plan(plan_json, context) -> (valid, errors)`. The skill shows errors and asks Claude to regenerate if validation fails.

### 7. Plan Staleness Warning

`AiPlanProvider.load_plan()` checks `plan_meta.json` and adds a warning if:
- Plan is older than 4 weeks
- Current CP has drifted > 3% from `cp_at_generation`

The warning flows through the existing `warnings` list in `get_dashboard_data()` and displays in the dashboard.

## Data Flow

```
User runs /training-plan skill
    ↓
Skill runs: python scripts/build_training_context.py
    ↓
Script calls build_training_context() → outputs JSON to stdout
    ↓
Skill (Claude) reads context JSON → generates plan
    ↓
Claude returns structured plan JSON
    ↓
Skill displays plan in terminal
    ↓
User approves → writes to data/ai/
    ↓
User sets plan source to "ai" in Settings (if not already)
    ↓
AiPlanProvider.load_plan() serves the plan
    ↓
UpcomingPlanCard, daily_training_signal(), compliance all work automatically
```

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `api/ai.py` | Create | Training context builder + plan validation |
| `scripts/build_training_context.py` | Create | CLI entry point: outputs context JSON to stdout |
| `analysis/providers/ai.py` | Create | `AiPlanProvider` implementing `PlanProvider` |
| `analysis/providers/__init__.py` | Modify | Register AI plan provider |
| `analysis/config.py` | Modify | Add `PlanSource` type (extends `PlatformName` with `"ai"`) |
| `web/src/types/api.ts` | Modify | Add `PlanSourceName` type |
| `data/ai/` | Create dir | Storage for AI-generated plans |
| `data/sample/ai/` | Create dir | Sample AI plan for tests |
| Skill file (TBD) | Create | `/training-plan` Claude Code skill |
| `scripts/generate_sample_data.py` | Modify | Add sample AI plan generation |
| `tests/test_ai_plan.py` | Create | Tests for context builder + plan provider |

## What This Does NOT Include (Future Work)

- **API endpoints** (`/api/ai/context`, `/api/ai/generate-plan`) — deferred until in-app UI
- **In-app chat UI** — future feature, uses same `build_training_context()`
- **Push to Stryd/Garmin calendars** — future integration
- **Plan editing UI** — future (edit individual workouts in the dashboard)
- **Automatic re-generation** — future (detect when plan is stale based on fitness changes)
- **Biomechanics in context** — could add Stryd cadence/oscillation/ground time later for form-aware coaching

## Verification

1. **Unit tests:** `build_training_context()` returns expected structure with sample data
2. **Provider tests:** `AiPlanProvider.load_plan()` reads CSV correctly
3. **Integration test:** Generate a plan with sample data, verify it writes valid CSV
4. **Manual test:** Run `/training-plan` skill with real data, review output quality
5. **Pipeline test:** After generating plan, verify UpcomingPlanCard displays AI workouts
