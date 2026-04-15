# Zone-Aware Training Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make training zone theories actually affect intensity classification, distribution analysis, and visualization on the Training page.

**Architecture:** `diagnose_training()` receives zone boundaries + names + target distribution from config/science. Distribution becomes a dynamic list of N+1 zones. A new `ZoneAnalysisCard` component displays zone ranges, actual vs target %, and diagnostic alerts. `DistributionBar` adapts to variable zone counts.

**Tech Stack:** Python (FastAPI, pandas), React (TypeScript, shadcn/ui, Tailwind)

**Spec:** `docs/superpowers/specs/2026-04-09-zone-aware-training-analysis-design.md`

---

### Task 1: Make `diagnose_training()` accept and use zone boundaries

**Files:**
- Modify: `analysis/metrics.py:888-1104` (diagnose_training + distribution section)
- Modify: `analysis/metrics.py:1115-1203` (_add_diagnosis_items distribution check)
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write failing test for dynamic zone distribution**

Add to `tests/test_metrics.py` after the existing diagnosis tests (line ~345):

```python
def test_diagnose_distribution_uses_zone_boundaries():
    """Distribution should use provided zone boundaries, not hardcoded values."""
    today = date(2026, 3, 23)
    dates = [date(2026, 3, d) for d in [2, 4, 7, 9, 11, 14, 16, 18, 20, 21]]
    activities = _make_activities(dates, [8, 10, 25, 8, 10, 8, 10, 25, 8, 10])
    # Activity 2 and 7 have 25km — their splits will have high power
    splits = _make_splits(
        ["2", "2", "7", "7"],
        [260, 220, 255, 210],  # above and below various thresholds
        [600, 600, 600, 600],
    )
    trend = {"current": 250.0, "direction": "flat", "slope_per_month": 0.5}

    # Polarized 3-zone: boundaries [0.82, 1.00] → 3 zones
    result = diagnose_training(
        activities, splits, trend,
        lookback_weeks=4, current_date=today,
        zone_boundaries=[0.82, 1.00],
        zone_names=["Easy", "Moderate", "Hard"],
        target_distribution=[0.80, 0.05, 0.15],
    )

    dist = result["distribution"]
    # Should be a list of dicts, not the old dict format
    assert isinstance(dist, list)
    assert len(dist) == 3
    assert dist[0]["name"] == "Easy"
    assert dist[1]["name"] == "Moderate"
    assert dist[2]["name"] == "Hard"
    # Each entry has actual_pct and target_pct
    assert all("actual_pct" in d and "target_pct" in d for d in dist)
    # Targets match what we passed
    assert dist[0]["target_pct"] == 80
    assert dist[1]["target_pct"] == 5
    assert dist[2]["target_pct"] == 15


def test_diagnose_distribution_default_5zone():
    """Without zone_boundaries, should still produce 5-zone distribution as list."""
    today = date(2026, 3, 23)
    dates = [date(2026, 3, d) for d in [2, 4, 7, 9, 11]]
    activities = _make_activities(dates, [8, 10, 15, 8, 10])
    splits = _make_splits(["2"], [260], [600])
    trend = {"current": 250.0, "direction": "flat", "slope_per_month": 0.5}

    result = diagnose_training(
        activities, splits, trend,
        lookback_weeks=4, current_date=today,
    )

    dist = result["distribution"]
    assert isinstance(dist, list)
    assert len(dist) == 5  # Default Coggan 5-zone
    # Default names for power base
    names = [d["name"] for d in dist]
    assert names == ["Easy", "Tempo", "Threshold", "Supra-CP", "VO2max"]


def test_diagnose_zone_ranges_included():
    """Result should include zone_ranges and theory_name."""
    today = date(2026, 3, 23)
    dates = [date(2026, 3, d) for d in [2, 4, 7]]
    activities = _make_activities(dates, [8, 10, 15])
    splits = _make_splits(["0"], [200], [600])
    trend = {"current": 250.0, "direction": "flat", "slope_per_month": 0.5}

    result = diagnose_training(
        activities, splits, trend,
        lookback_weeks=4, current_date=today,
        zone_boundaries=[0.82, 1.00],
        zone_names=["Easy", "Moderate", "Hard"],
        theory_name="Seiler Polarized 3-Zone",
    )

    assert "zone_ranges" in result
    assert len(result["zone_ranges"]) == 3
    assert result["zone_ranges"][0]["name"] == "Easy"
    assert result["zone_ranges"][0]["unit"] == "W"
    assert result["theory_name"] == "Seiler Polarized 3-Zone"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics.py::test_diagnose_distribution_uses_zone_boundaries tests/test_metrics.py::test_diagnose_distribution_default_5zone tests/test_metrics.py::test_diagnose_zone_ranges_included -v`
Expected: FAIL — `diagnose_training()` doesn't accept the new parameters yet.

- [ ] **Step 3: Update `diagnose_training()` signature and distribution logic**

In `analysis/metrics.py`, update the function signature (line 888) to accept new parameters:

```python
def diagnose_training(
    merged_activities: pd.DataFrame,
    splits: pd.DataFrame,
    cp_trend: dict,
    lookback_weeks: int = 6,
    current_date: date | None = None,
    base: TrainingBase = "power",
    threshold_value: float | None = None,
    zone_boundaries: list[float] | None = None,
    zone_names: list[str] | None = None,
    target_distribution: list[float] | None = None,
    theory_name: str | None = None,
) -> dict:
```

Add these imports at the top of the file (near existing imports):

```python
from analysis.zones import compute_zones
from analysis.config import DEFAULT_ZONES
```

Replace the distribution section (lines 1073-1101) with dynamic zone classification:

```python
    # --- Training distribution ---
    # Resolve zone boundaries: use provided, or defaults for the base
    bounds = zone_boundaries or DEFAULT_ZONES.get(base, DEFAULT_ZONES["power"])
    n_zones = len(bounds) + 1

    # Default zone names if not provided
    _default_names = {
        "power": ["Easy", "Tempo", "Threshold", "Supra-CP", "VO2max"],
        "hr": ["Recovery", "Aerobic", "Tempo", "Threshold", "VO2max"],
        "pace": ["Recovery", "Easy", "Tempo", "Threshold", "Interval"],
    }
    names = zone_names if (zone_names and len(zone_names) == n_zones) else _default_names.get(base, [f"Zone {i+1}" for i in range(n_zones)])
    # Trim or pad names to match zone count
    if len(names) != n_zones:
        names = [f"Zone {i+1}" for i in range(n_zones)]

    # Target distribution as percentages (None if not provided)
    targets_pct: list[float | None] = [None] * n_zones
    if target_distribution and len(target_distribution) == n_zones:
        targets_pct = [round(t * 100) for t in target_distribution]

    if "activity_id" in recent_splits.columns:
        if base == "pace":
            activity_best = recent_splits.groupby(recent_splits["activity_id"].astype(str))[metric_col].min()
        else:
            activity_best = recent_splits.groupby(recent_splits["activity_id"].astype(str))[metric_col].max()
    else:
        activity_best = pd.Series(dtype=float)

    total_activities = len(recent)
    zone_counts = [0] * n_zones

    if total_activities > 0 and not activity_best.empty and current_cp > 0:
        for val in activity_best:
            if base == "pace":
                # For pace: lower value = harder. Compare ratio = threshold / val.
                ratio = current_cp / val if val > 0 else 0
                # Pace bounds are inverted fractions (e.g., [1.14, 1.00]).
                # Invert them so comparison is: ratio >= 1/bound means in that zone.
                assigned = 0  # default to easiest zone
                for i, b in enumerate(bounds):
                    inv_b = 1.0 / b if b > 0 else 0
                    if ratio >= inv_b:
                        assigned = i + 1
                zone_counts[assigned] += 1
            else:
                ratio = val / current_cp if current_cp > 0 else 0
                assigned = 0  # default to easiest zone
                for i, b in enumerate(bounds):
                    if ratio >= b:
                        assigned = i + 1
                zone_counts[assigned] += 1

        result["distribution"] = [
            {
                "name": names[i],
                "actual_pct": round(zone_counts[i] / total_activities * 100),
                "target_pct": targets_pct[i],
            }
            for i in range(n_zones)
        ]
    else:
        result["distribution"] = [
            {"name": names[i], "actual_pct": 100 if i == 0 else 0, "target_pct": targets_pct[i]}
            for i in range(n_zones)
        ]

    # Compute zone ranges for display
    if current_cp > 0:
        result["zone_ranges"] = compute_zones(base, current_cp, bounds, names)
    else:
        result["zone_ranges"] = []

    result["theory_name"] = theory_name or ("Coggan 5-Zone" if len(bounds) == 4 else f"{n_zones}-Zone")

    _add_diagnosis_items(result, current_cp, base)
    return result
```

- [ ] **Step 4: Update `_add_diagnosis_items()` for list-format distribution**

Replace the distribution check section (lines 1191-1203) in `_add_diagnosis_items`:

```python
    # Distribution check — use target comparison if available
    dist_list = dist if isinstance(dist, list) else []
    if dist_list:
        # Find easy zone (first/lowest) and hard zones (top 1-2)
        easy_entry = dist_list[0] if dist_list else None
        easy_pct = easy_entry["actual_pct"] if easy_entry else 0

        # Sum top zones as "hard" (everything above the second-to-last boundary)
        hard_pct = sum(d["actual_pct"] for d in dist_list[2:]) if len(dist_list) > 2 else 0

        # Check against targets if available
        has_targets = any(d.get("target_pct") is not None for d in dist_list)
        if has_targets:
            deviations = []
            for d in dist_list:
                if d["target_pct"] is not None:
                    diff = d["actual_pct"] - d["target_pct"]
                    if abs(diff) > 5:
                        direction = "above" if diff > 0 else "below"
                        deviations.append(f"{d['name']}: {d['actual_pct']}% ({direction} {d['target_pct']}% target)")
            if deviations:
                diag.append({
                    "type": "warning",
                    "message": f"Distribution deviates from target — " + ", ".join(deviations) + ".",
                })
            else:
                diag.append({
                    "type": "positive",
                    "message": f"Training distribution is close to target across all zones.",
                })
        else:
            # No targets — use generic polarization check
            if easy_pct > 85 and hard_pct < 10:
                diag.append({
                    "type": "warning",
                    "message": f"Training is {easy_pct}% easy — insufficient hard sessions for {t_name} adaptation.",
                })
            elif 70 <= easy_pct <= 85:
                diag.append({
                    "type": "positive",
                    "message": f"Good polarization: {easy_pct}% easy, {hard_pct}% hard.",
                })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: All tests PASS including the 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add analysis/metrics.py tests/test_metrics.py
git commit -m "feat: make diagnose_training() use dynamic zone boundaries

Distribution is now a list of N zones with actual_pct and target_pct.
Zone ranges and theory name included in result."
```

---

### Task 2: Pass zone config from deps.py to diagnose_training()

**Files:**
- Modify: `api/deps.py:1016-1020`

- [ ] **Step 1: Update the `diagnose_training()` call in deps.py**

In `api/deps.py`, find the `diagnose_training()` call (around line 1016). The `science` dict is already loaded at line 756. Replace the call:

```python
    # Get zone theory data for diagnosis
    zones_theory = science.get("zones")
    zone_boundaries = config.zones.get(config.training_base)
    zone_names_list: list[str] | None = None
    target_dist: list[float] | None = None
    zone_theory_name: str | None = None
    if zones_theory:
        zone_theory_name = zones_theory.name
        zn = zones_theory.zone_names
        if isinstance(zn, dict):
            zone_names_list = zn.get(config.training_base)
        elif isinstance(zn, list):
            zone_names_list = zn
        target_dist = zones_theory.target_distribution or None

    diagnosis = diagnose_training(
        merged, splits, cp_trend_data,
        base=config.training_base,
        threshold_value=active_threshold,
        zone_boundaries=zone_boundaries,
        zone_names=zone_names_list,
        target_distribution=target_dist,
        theory_name=zone_theory_name,
    )
```

- [ ] **Step 2: Run existing tests**

Run: `python -m pytest tests/ -v`
Expected: All 113+ tests PASS.

- [ ] **Step 3: Commit**

```bash
git add api/deps.py
git commit -m "feat: pass zone theory config to diagnose_training()"
```

---

### Task 3: Update TypeScript types for new distribution format

**Files:**
- Modify: `web/src/types/api.ts:219-244` (DiagnosisData)

- [ ] **Step 1: Add new interfaces and update DiagnosisData**

In `web/src/types/api.ts`, add the new interfaces before `DiagnosisData` (around line 214):

```typescript
export interface ZoneDistribution {
  name: string;
  actual_pct: number;
  target_pct: number | null;
}

export interface ZoneRange {
  name: string;
  lower: number;
  upper: number | null;
  unit: string;
}
```

Update `DiagnosisData` — replace the `distribution` field and add new fields:

```typescript
export interface DiagnosisData {
  lookback_weeks: number;
  interval_power: {
    max: number | null;
    avg_work: number | null;
    supra_cp_sessions: number;
    total_quality_sessions: number;
  };
  volume: {
    weekly_avg_km: number;
    trend: string;
  };
  distribution: ZoneDistribution[];
  zone_ranges: ZoneRange[];
  theory_name: string;
  consistency: {
    weeks_with_gaps: number;
    longest_gap_days: number;
    total_sessions: number;
  };
  diagnosis: DiagnosisFinding[];
  suggestions: string[];
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit 2>&1 | head -30`
Expected: Type errors in `DistributionBar.tsx` and `DiagnosisCard.tsx` (expected — we'll fix them next).

- [ ] **Step 3: Commit**

```bash
git add web/src/types/api.ts
git commit -m "feat: update DiagnosisData types for dynamic zone distribution"
```

---

### Task 4: Update DistributionBar for dynamic zones

**Files:**
- Modify: `web/src/components/DistributionBar.tsx`

- [ ] **Step 1: Rewrite DistributionBar to accept dynamic zone list**

Replace the entire content of `web/src/components/DistributionBar.tsx`:

```tsx
import type { ZoneDistribution } from '@/types/api';

interface Props {
  distribution: ZoneDistribution[];
}

// Zone colors from highest intensity to lowest. Indexed from the end of the array.
const ZONE_COLORS = [
  { color: 'bg-destructive', textColor: 'text-destructive' },
  { color: 'bg-accent-amber', textColor: 'text-accent-amber' },
  { color: 'bg-accent-blue', textColor: 'text-accent-blue' },
  { color: 'bg-accent-blue/50', textColor: 'text-accent-blue' },
  { color: 'bg-muted-foreground', textColor: 'text-muted-foreground' },
];

function getZoneColor(index: number, total: number) {
  // Map zone index (0=easiest) to colors (last=easiest)
  const colorIdx = total - 1 - index;
  return ZONE_COLORS[Math.min(colorIdx, ZONE_COLORS.length - 1)] ?? ZONE_COLORS[ZONE_COLORS.length - 1];
}

export default function DistributionBar({ distribution }: Props) {
  const total = distribution.reduce((sum, d) => sum + d.actual_pct, 0);

  // Reverse so highest intensity is first in the bar
  const zones = [...distribution].reverse().map((d, i) => ({
    name: d.name,
    pct: total > 0 ? d.actual_pct : 0,
    ...getZoneColor(distribution.length - 1 - i, distribution.length),
  }));

  return (
    <div>
      {/* Stacked bar */}
      <div className="flex h-6 w-full overflow-hidden rounded-full">
        {zones.map((zone) => {
          if (zone.pct === 0) return null;
          return (
            <div
              key={zone.name}
              className={`${zone.color} flex items-center justify-center text-[10px] font-semibold text-base`}
              style={{ width: `${zone.pct}%` }}
              title={`${zone.name}: ${zone.pct}%`}
            >
              {zone.pct >= 8 ? `${zone.pct}%` : ''}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs">
        {zones.map((zone) => (
          <span key={zone.name} className="flex items-center gap-1.5">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${zone.color}`} />
            <span className="text-muted-foreground">{zone.name}</span>
            <span className={`font-data font-semibold ${zone.textColor}`}>{zone.pct}%</span>
          </span>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update DiagnosisCard to pass new distribution format**

In `web/src/components/DiagnosisCard.tsx`, update the DistributionBar usage. The `display` prop is no longer needed for DistributionBar since zone names now come from the distribution list itself.

Change line 66 from:
```tsx
<DistributionBar distribution={distribution} display={display} />
```
to:
```tsx
<DistributionBar distribution={distribution} />
```

Also update the `topZoneName` logic (line 25) to use the distribution list:

```tsx
const topZoneName = distribution.length > 0 ? distribution[distribution.length - 1].name : 'Supra-CP';
```

And remove the now-unused `display` prop from the import of `DisplayConfig` if it's only used for that.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/DistributionBar.tsx web/src/components/DiagnosisCard.tsx
git commit -m "feat: make DistributionBar dynamic for variable zone counts"
```

---

### Task 5: Create ZoneAnalysisCard component

**Files:**
- Create: `web/src/components/ZoneAnalysisCard.tsx`

- [ ] **Step 1: Create the ZoneAnalysisCard component**

Create `web/src/components/ZoneAnalysisCard.tsx`:

```tsx
import type { ZoneDistribution, ZoneRange, DisplayConfig } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';

interface Props {
  distribution: ZoneDistribution[];
  zoneRanges: ZoneRange[];
  theoryName: string;
  display?: DisplayConfig;
}

// Zone accent colors: index 0 = easiest, last = hardest
const ZONE_TEXT_COLORS = [
  'text-muted-foreground',
  'text-accent-blue/70',
  'text-accent-blue',
  'text-accent-amber',
  'text-destructive',
];

function getZoneTextColor(index: number, total: number) {
  // Map to color palette, scaling to available colors
  const scaled = Math.round((index / Math.max(total - 1, 1)) * (ZONE_TEXT_COLORS.length - 1));
  return ZONE_TEXT_COLORS[scaled] ?? ZONE_TEXT_COLORS[0];
}

function formatRange(range: ZoneRange): string {
  if (range.upper == null) return `> ${range.lower}${range.unit}`;
  if (range.lower === 0) return `< ${range.upper}${range.unit}`;
  return `${range.lower}–${range.upper}${range.unit}`;
}

export default function ZoneAnalysisCard({ distribution, zoneRanges, theoryName, display }: Props) {
  const thresholdLabel = display ? `${display.threshold_abbrev}` : '';

  // Reverse to show highest intensity first
  const rows = [...distribution].reverse();
  const ranges = [...zoneRanges].reverse();

  // Find deviations > 5pp for alerts
  const alerts = distribution
    .filter((d) => d.target_pct != null && Math.abs(d.actual_pct - d.target_pct!) > 5)
    .map((d) => {
      const diff = d.actual_pct - d.target_pct!;
      const direction = diff > 0 ? 'above' : 'below';
      return `${d.name}: ${d.actual_pct}% (${Math.abs(diff)}pp ${direction} ${d.target_pct}% target)`;
    });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Zone Analysis · {theoryName}
          </CardTitle>
          {thresholdLabel && (
            <span className="text-xs text-muted-foreground font-data">{thresholdLabel}</span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {/* Header row */}
        <div className="flex items-center pb-2 mb-2 border-b border-border">
          <span className="w-20 text-[10px] uppercase tracking-wider text-muted-foreground">Zone</span>
          <span className="flex-1 text-[10px] uppercase tracking-wider text-muted-foreground">Range</span>
          <span className="w-14 text-right text-[10px] uppercase tracking-wider text-muted-foreground">Actual</span>
          <span className="w-14 text-right text-[10px] uppercase tracking-wider text-muted-foreground">Target</span>
        </div>

        {/* Zone rows */}
        <div className="space-y-1.5">
          {rows.map((d, i) => {
            const range = ranges[i];
            const colorClass = getZoneTextColor(distribution.length - 1 - i, distribution.length);
            return (
              <div key={d.name} className="flex items-center">
                <span className={`w-20 text-sm font-medium ${colorClass}`}>{d.name}</span>
                <span className="flex-1 text-sm text-muted-foreground font-data">
                  {range ? formatRange(range) : ''}
                </span>
                <span className="w-14 text-right text-sm font-semibold font-data text-foreground">
                  {d.actual_pct}%
                </span>
                <span className="w-14 text-right text-sm font-data text-muted-foreground">
                  {d.target_pct != null ? `${d.target_pct}%` : '—'}
                </span>
              </div>
            );
          })}
        </div>

        {/* Deviation alerts */}
        {alerts.length > 0 && (
          <Alert className="mt-4 border-accent-amber/30 bg-accent-amber/5">
            <AlertDescription className="text-sm text-accent-amber">
              Distribution deviates from target: {alerts.join('; ')}
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ZoneAnalysisCard.tsx
git commit -m "feat: add ZoneAnalysisCard component for zone ranges and target comparison"
```

---

### Task 6: Wire ZoneAnalysisCard into Training page

**Files:**
- Modify: `web/src/pages/Training.tsx`
- Modify: `web/src/types/api.ts` (TrainingResponse — add new fields)

- [ ] **Step 1: Ensure TrainingResponse includes zone data**

The `diagnosis` field in `TrainingResponse` already uses `DiagnosisData`, which now includes `zone_ranges` and `theory_name`. No change needed to `TrainingResponse` itself.

- [ ] **Step 2: Add ZoneAnalysisCard to Training page**

In `web/src/pages/Training.tsx`, add the import (after line 7):

```tsx
import ZoneAnalysisCard from '@/components/ZoneAnalysisCard';
```

Add the card after the DiagnosisCard section (after line 63):

```tsx
      {/* Zone analysis card */}
      {data.diagnosis.zone_ranges.length > 0 && (
        <div className="mb-6">
          <ZoneAnalysisCard
            distribution={data.diagnosis.distribution}
            zoneRanges={data.diagnosis.zone_ranges}
            theoryName={data.diagnosis.theory_name}
            display={activeDisplay ?? undefined}
          />
        </div>
      )}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/Training.tsx
git commit -m "feat: add ZoneAnalysisCard to Training page"
```

---

### Task 7: End-to-end verification

- [ ] **Step 1: Run all backend tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 2: Run frontend type check**

Run: `cd web && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Manual verification**

Start the API and frontend:
```bash
python -m uvicorn api.main:app --reload &
cd web && npm run dev
```

1. Open Training page — verify DiagnosisCard distribution bar shows dynamic zones
2. Verify ZoneAnalysisCard appears below DiagnosisCard with zone names, ranges, actual %, target %
3. Go to Science page → switch to "Seiler Polarized 3-Zone"
4. Return to Training page → verify:
   - Distribution bar now shows 3 segments (Hard / Moderate / Easy)
   - ZoneAnalysisCard shows 3 rows with 80/5/15 targets
   - Deviation alert appears if actual diverges from target
5. Switch back to Coggan 5-Zone → verify 5 zones restore

- [ ] **Step 4: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: address any issues from manual verification"
```
