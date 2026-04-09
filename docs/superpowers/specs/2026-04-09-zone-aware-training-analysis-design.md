# Zone-Aware Training Analysis

## Problem

When a user selects a different zone theory on the Science page (e.g., Coggan 5-Zone → Polarized 3-Zone), nothing meaningful changes in the app:

1. **`config.zones` now updates correctly** (fixed in prior commit), but no analysis code reads it
2. **`diagnose_training()` hardcodes intensity boundaries** — lines 1084-1092 of `analysis/metrics.py` use fixed percentages (98%, 92%, 85%) regardless of the selected theory
3. **`DistributionBar` hardcodes 4 zones** — `supra_cp`, `threshold`, `tempo`, `easy` are baked into the component
4. **No zone ranges are shown anywhere** — the user can't see what power/HR/pace ranges correspond to each zone
5. **No target comparison** — theories define target distributions (e.g., Polarized 80/5/15) but these are never shown

## Design

### Backend Changes

#### 1. `diagnose_training()` accepts zone boundaries (`analysis/metrics.py`)

Add parameters:
- `zone_boundaries: list[float] | None` — boundary fractions from `config.zones[base]`
- `zone_names: list[str] | None` — names from the active zone theory
- `target_distribution: list[float] | None` — from the zone theory YAML

**Distribution classification (lines 1073-1101):** Replace the hardcoded 4-bucket classification with a dynamic loop. For N boundaries, produce N+1 buckets. Each activity's best split metric is compared against `threshold * boundary[i]` to assign it to a zone.

The distribution dict keys change from `{"supra_cp": 8, "threshold": 15, ...}` to a list format:
```python
"distribution": [
    {"name": "VO2max", "actual_pct": 8, "target_pct": 5},
    {"name": "Supra-CP", "actual_pct": 18, "target_pct": 10},
    ...
]
```

**Zone ranges:** Add a `zone_ranges` list to the result:
```python
"zone_ranges": [
    {"name": "VO2max", "lower": 263, "upper": None, "unit": "W"},
    {"name": "Supra-CP", "lower": 225, "upper": 263, "unit": "W"},
    ...
]
```

Reuse `compute_zones()` from `analysis/zones.py` to generate `zone_ranges`.

**Diagnostic text (`_add_diagnosis_items`):** The distribution-check section (lines 1191-1202) adapts to use the theory's target distribution for comparison rather than hardcoded 70-85% easy thresholds.

#### 2. `api/deps.py` passes zone config to `diagnose_training()`

Currently calls `diagnose_training(merged, splits, cp_trend_data, base=config.training_base, threshold_value=active_threshold)`.

Add: `zone_boundaries=config.zones.get(config.training_base)`, `zone_names` and `target_distribution` from the active science zones theory (already loaded as `science["zones"]` in deps.py).

#### 3. API response includes zone metadata

The training route already returns `diagnosis` dict. The new `distribution` (list format) and `zone_ranges` fields are included automatically. Also add `theory_name` (e.g., "Coggan 5-Zone") to the response.

### Frontend Changes

#### 4. New `ZoneAnalysisCard` component

Location: `web/src/components/ZoneAnalysisCard.tsx`

A shadcn `Card` with:
- **Header:** "Zone Analysis · {theory_name}" on the left, "{threshold_abbrev}: {value}{unit}" on the right
- **Table body:** One row per zone (top = highest intensity, bottom = lowest). Columns:
  - Zone name (colored with zone accent color)
  - Power/HR/pace range (muted text)
  - Actual % (bold white)
  - Target % (muted)
- **Footer alerts:** When actual diverges from target by >5pp for any zone, show an `Alert` with amber styling explaining the gap

Adapts to 3 or 5 zones — just renders N rows.

#### 5. Update `DistributionBar` to be dynamic

Change from hardcoded 4 `DIST_KEYS` to accepting a dynamic list from the API. The stacked bar renders N segments with N colors. Colors assigned from a palette array indexed by zone position.

#### 6. Update TypeScript types (`web/src/types/api.ts`)

Add to the diagnosis response type:
```typescript
interface ZoneDistribution {
  name: string;
  actual_pct: number;
  target_pct: number | null;
}

interface ZoneRange {
  name: string;
  lower: number;
  upper: number | null;
  unit: string;
}

// In DiagnosisResponse:
distribution: ZoneDistribution[];  // replaces old Record<string, number>
zone_ranges: ZoneRange[];
theory_name: string;
```

#### 7. Training page layout

Add `<ZoneAnalysisCard>` below the existing `<DiagnosisCard>` on the Training page. Both cards are in the same grid column.

### Files to Modify

| File | Change |
|------|--------|
| `analysis/metrics.py` | `diagnose_training()` + `_add_diagnosis_items()` — dynamic zone classification |
| `analysis/zones.py` | Already updated — `compute_zones()` handles variable counts |
| `api/deps.py` | Pass zone config + theory data to `diagnose_training()` |
| `api/routes/training.py` | Include `theory_name` in response (if not already in diagnosis dict) |
| `web/src/types/api.ts` | New `ZoneDistribution`, `ZoneRange` interfaces; update diagnosis type |
| `web/src/components/ZoneAnalysisCard.tsx` | **New file** — zone table + target comparison + alerts |
| `web/src/components/DistributionBar.tsx` | Make dynamic (N zones, N colors) |
| `web/src/pages/Training.tsx` | Add `<ZoneAnalysisCard>` |

### Backward Compatibility

The `distribution` field changes from `{supra_cp: N, ...}` (dict with fixed keys) to a list of objects. The `DistributionBar` component must be updated in the same change. No other consumers of the old format exist (checked: only `DistributionBar` reads it).

### Zone Colors

Zone colors are assigned by position (highest intensity → lowest):
- For 5-zone: `destructive`, `accent-amber`, `accent-blue`, `accent-blue/50`, `muted-foreground`
- For 3-zone: `destructive`, `accent-amber`, `muted-foreground`

These come from the existing `ZONE_COLORS` array in `DistributionBar.tsx`, extended to handle variable counts.

## Verification

1. `python -m pytest tests/ -v` — existing tests pass
2. Start API + frontend: `python -m uvicorn api.main:app --reload` and `cd web && npm run dev`
3. On Training page: verify the existing DiagnosisCard distribution bar shows dynamic zones
4. Verify new ZoneAnalysisCard shows zone names, ranges, actual vs target
5. Switch zone theory on Science page (Coggan → Polarized)
6. Return to Training page — verify card now shows 3 zones with 80/5/15 targets
7. Verify diagnostic alerts fire when actual diverges from target
8. Test with different training bases (power, HR, pace) — zone ranges should use correct units
