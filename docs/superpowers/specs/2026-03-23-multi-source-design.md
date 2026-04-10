# Multi-Source Data Architecture & Training Base System

**Date:** 2026-03-23
**Updated:** 2026-03-24 (connections-first model, 4 data categories)
**Status:** Approved
**Scope:** Sub-project 1 of 3 (core backend + settings API)

## Problem

The dashboard is hardcoded to Garmin + Stryd + Oura with power as the only training base. This prevents:
- Runners with different gear from using the app (e.g., Garmin-only, Polar+Stryd)
- Switching data sources without rewriting code
- HR-based or pace-based training approaches

## Solution: Connections-First Provider Pattern

Users connect platforms (Garmin, Stryd, Oura, etc.), and the system fetches all available data from each. Users then set preferences for which source to trust per data category where multiple sources overlap.

```
Layer 1: Connections — which platforms are linked (garmin, stryd, oura, coros, polar...)
Layer 2: Sync — fetch ALL available data from each connected platform
Layer 3: Preferences — user chooses which source to trust per data type (where needed)
```

Providers output canonical data models. User selects training base (power/HR/pace) which cascades through zones, load calculation, diagnosis, and display.

## Data Categories

| Category | What | Example sources | User preference? |
|----------|------|-----------------|-----------------|
| **Activities** | Workouts + splits (all sport types) | Garmin, Stryd, Coros, Polar | Yes — pick primary, others auto-enrich |
| **Recovery** | Sleep, HRV, readiness | Oura, Garmin, Whoop | Yes — pick one source |
| **Fitness** | VO2max, training status, CP, LTHR, LT pace | Garmin, Stryd | No — auto-merge all connected sources |
| **Plan** | Training plan / planned workouts | Stryd, TrainingPeaks | Yes — pick one source |

### Why 4 categories instead of 3

- Recovery (sleep/HRV) and Fitness (VO2max/CP/training status) come from different device types
- Oura is great for recovery but has zero fitness data
- Garmin/Stryd provide fitness metrics but their recovery data is secondary
- Combining them into "Health" would force users to pick one source and lose the other's unique data

### Why Fitness has no preference

- Garmin provides VO2max, LTHR, training status, training readiness
- Stryd provides CP estimate, form power trends
- These are complementary, not competing — just merge everything
- `training_base` (power/HR/pace) already determines which threshold drives zones/load/diagnosis

### Activity handling

**Auto-merge with primary wins conflicts:**
- Primary source (e.g., Garmin) provides the base record (HR, GPS, elevation, cadence)
- Secondary sources (e.g., Stryd) add missing fields (power, form metrics, RSS, CP)
- For conflicting fields (distance, duration), primary source wins
- Uses existing `match_activities()` merge logic (date + timestamp proximity)

**Fetch all sport types, analyze running:**
- Garmin sync fetches all activity types (running, swimming, strength, cycling, etc.)
- Non-running activities are stored with `activity_type` field
- Non-running activities contribute to total training load via HR-based TRIMP
- All detailed analysis (power zones, splits, CP, pace) remains running-only
- Dashboard can show activity calendar with all types, load charts include all types

**Per-activity-type source routing (dynamic discovery):**

Instead of a single `preferences.activities` pointer, the system supports routing each activity type to the best available source. The UI is data-driven: no hardcoded type lists.

1. `discover_activity_types(connections, data_dir) -> dict[str, list[str]]` — reads each connected provider's CSV and returns distinct `activity_type` values actually present, e.g.:
   ```json
   { "garmin": ["running", "cycling", "hiking"], "stryd": ["running"] }
   ```
2. `activity_routing: dict[str, str]` in UserConfig stores explicit per-type choices, e.g.:
   ```json
   { "running": "stryd", "default": "garmin" }
   ```
   Types not in the dict fall through to `"default"`.
3. `_load_activities_routed()` in `data_loader.py` replaces the single-source `match_activities()` path — it routes each type's rows to the appropriate provider before merging.

Settings UI behaviour:
- Types appearing in **multiple** connected providers → interactive toggle row (e.g., `Running: [Garmin] [Stryd]`)
- Types appearing in only **one** provider → non-interactive badge (e.g., `Cycling: Garmin only`)
- A final **"All others"** row shows the default provider
- If only one activity provider is connected, the entire routing section is hidden
- **Empty state:** if `discovered_activity_types` is empty (no data synced yet), show: *"Sync your data first to configure per-activity routing."*

### Platform Capability Matrix

Each platform declares what data types it can provide:

```python
PLATFORM_CAPABILITIES = {
    "garmin":  {"activities": True, "recovery": True, "fitness": True, "plan": False},
    "stryd":   {"activities": True, "recovery": False, "fitness": True, "plan": True},
    "oura":    {"activities": False, "recovery": True, "fitness": False, "plan": False},
    "coros":   {"activities": True, "recovery": False, "fitness": True, "plan": False},
}
```

The Settings UI uses this to:
- Show only valid options in preference dropdowns (e.g., can't pick Stryd for recovery)
- Auto-suggest preferences based on connected platforms
- Show what data each connection provides

## Provider Interfaces

```python
class ActivityProvider(ABC):
    name: str
    def load_activities(self, data_dir: str, since: date | None = None) -> pd.DataFrame: ...
    def load_splits(self, data_dir: str, activity_ids: list[str] | None = None) -> pd.DataFrame: ...

class RecoveryProvider(ABC):
    name: str
    def load_recovery(self, data_dir: str, since: date | None = None) -> pd.DataFrame: ...

class FitnessProvider(ABC):
    name: str
    def load_fitness(self, data_dir: str, since: date | None = None) -> pd.DataFrame: ...

class PlanProvider(ABC):
    name: str
    def load_plan(self, data_dir: str, since: date | None = None) -> pd.DataFrame: ...
```

Threshold auto-detection folds into FitnessProvider — each fitness provider can contribute threshold estimates, and the system merges them (Stryd -> CP, Garmin -> LTHR).

Registry: simple dict lookup in `analysis/providers/__init__.py`. No plugin framework.

## Canonical Data Models

All providers map platform-specific columns to these canonical names. Data stays as DataFrames.

**Activity columns:**
- Required: `activity_id`, `date`, `distance_km`, `duration_sec`, `activity_type`
- Optional: `start_time`, `avg_power`, `max_power`, `avg_hr`, `max_hr`, `avg_pace_sec_km`, `elevation_gain_m`, `avg_cadence`, `rss`, `trimp`, `rtss`, `cp_estimate`, `load_score`
- activity_type values: `running`, `trail_running`, `cycling`, `swimming`, `strength`, `walking`, `hiking`, `other`

**Split columns:**
- Required: `activity_id`, `split_num`, `duration_sec`
- Optional: `distance_km`, `avg_power`, `avg_hr`, `max_hr`, `avg_pace_sec_km`, `avg_cadence`, `elevation_change_m`

**Recovery columns:**
- Required: `date`
- Optional: `sleep_score`, `readiness_score`, `hrv_avg`, `resting_hr`, `total_sleep_sec`, `deep_sleep_sec`, `rem_sleep_sec`, `body_temp_delta`

**Fitness columns:**
- Required: `date`
- Optional: `vo2max`, `training_status`, `training_readiness`, `cp_estimate`, `lthr_bpm`, `lt_pace_sec_km`, `leg_spring_stiffness`, `avg_oscillation`, `avg_stride_length`

**Planned workout columns:**
- Required: `date`, `workout_type`
- Optional: `planned_duration_min`, `planned_distance_km`, `target_power_min/max`, `target_hr_min/max`, `target_pace_min/max`, `workout_description`

**ThresholdEstimate:**
- `cp_watts`, `lthr_bpm`, `threshold_pace_sec_km`, `max_hr_bpm`, `rest_hr_bpm`, `source` ("auto"|"manual"), `detected_date`

## Training Base System

User's foundational choice: `power | hr | pace`

### Load Formulas (computed internally)

- **Power -> RSS:** `(duration/3600) * (power/CP)^2 * 100`
- **HR -> TRIMP:** `duration_min * delta_ratio * 0.64 * exp(k * delta_ratio)` where k=1.92 male, delta_ratio = (avg_hr - rest_hr) / (max_hr - rest_hr)
- **Pace -> rTSS:** `(duration/3600) * (threshold_pace/actual_pace)^2 * 100`

All three computed when data available. Training base selects which drives CTL/ATL/TSB.

TRIMP is also computed for non-running activities (if HR data available) to include cross-training load in CTL/ATL/TSB.

### Configurable Zone Boundaries

4 boundaries define 5 zones. Stored in config as fractions of threshold.

| Base | Z1/Z2 | Z2/Z3 | Z3/Z4 | Z4/Z5 | Note |
|------|-------|-------|-------|-------|------|
| Power | 0.55 | 0.75 | 0.90 | 1.05 | Coggan-style |
| HR | 0.72 | 0.82 | 0.89 | 0.96 | Friel-style |
| Pace | 1.29 | 1.14 | 1.06 | 1.00 | Inverted (slower->faster) |

### Display Config

Included in every API response so frontend never hardcodes labels:

```json
{
  "threshold_label": "Critical Power",
  "threshold_abbrev": "CP",
  "threshold_unit": "W",
  "load_label": "RSS",
  "intensity_metric": "Power",
  "zone_names": ["Easy", "Tempo", "Threshold", "Supra-CP", "VO2max"],
  "trend_label": "CP Trend"
}
```

### Intensity Classification

Generalized from power-only to any base:

```python
def classify_intensity(base: TrainingBase, value: float, threshold: float) -> str:
    # Returns: "easy", "tempo", "threshold", "supra_threshold"
    # Uses configurable zone boundaries
```

Zone keys change from `supra_cp` to `supra_threshold` (base-agnostic).

## User Config

Stored as `data/config.json`. Database deferred to Sub-project 2.

```json
{
  "connections": ["garmin", "stryd", "oura"],
  "preferences": {
    "recovery": "oura",
    "plan": "stryd"
  },
  "activity_routing": {
    "running": "stryd",
    "default": "garmin"
  },
  "training_base": "power",
  "thresholds": {
    "cp_watts": null,
    "lthr_bpm": null,
    "threshold_pace_sec_km": null,
    "max_hr_bpm": 190,
    "rest_hr_bpm": 55,
    "source": "auto"
  },
  "zones": {
    "power": [0.55, 0.75, 0.90, 1.05],
    "hr": [0.72, 0.82, 0.89, 0.96],
    "pace": [1.29, 1.14, 1.06, 1.00]
  },
  "goal": {"race_date": "2026-04-15", "race_target_time_sec": 10800, "cp_target": 295}
}
```

No `fitness` preference needed — auto-merged from all connections that provide fitness data.

### Settings API

- `GET /api/settings` — config + platform capabilities + auto-detected thresholds + display config + **`discovered_activity_types`** (dict of provider → list of activity types found in that provider's synced data)
- `PUT /api/settings` — partial update (accepts `activity_routing` alongside other fields), invalidates dashboard cache

### Threshold Resolution

1. Auto-detect from all connected FitnessProviders (Stryd -> CP, Garmin -> LTHR)
2. Manual overrides win
3. Settings UI shows both auto-detected and manual values

## New File Structure

```
analysis/
    config.py                    # UserConfig dataclass + JSON persistence
    zones.py                     # Zone calculation for all 3 bases
    training_base.py             # Display config per training base
    providers/
        __init__.py              # Registry + platform capabilities
        base.py                  # ABCs (Activity, Recovery, Fitness, Plan)
        models.py                # Canonical column defs + ThresholdEstimate
        garmin.py                # Garmin adapters (Activity, Recovery, Fitness)
        stryd.py                 # Stryd adapters (Activity, Plan, Fitness)
        oura.py                  # Oura adapter (Recovery)
    data_loader.py               # discover_activity_types() + _load_activities_routed()
api/routes/
    settings.py                  # GET/PUT /api/settings
data/
    config.json                  # User configuration (gitignored)
web/src/
    contexts/SettingsContext.tsx  # App-wide display config
    hooks/useSettings.ts         # Settings fetch/update
    pages/Settings.tsx           # Settings page
```

## Migration Phases

1. **Config layer** — Add config module + settings endpoint. Migrate `sources` -> `connections` + `preferences`.
2. **Provider interfaces** — Abstract providers wrapping existing CSV reading. `HealthProvider` -> `RecoveryProvider` + `FitnessProvider`.
3. **Training base system** — Add TRIMP/rTSS, parameterize diagnosis, configurable zones.
4. **Frontend adaptation** — Settings page, dynamic labels, SettingsContext.
5. **Threshold auto-detect** — FitnessProviders contribute thresholds, resolution logic, override UI.

Each phase independently deployable. System works at every intermediate state.

## Future Sub-projects

- **Sub-project 2:** User auth (JWT), multi-user (SQLAlchemy + PostgreSQL), cloud deployment
- **Sub-project 3:** Mobile app, WeChat miniprogram (consume same API)
