# Trainsight — Architectural Review

**Date:** 2026-04-10  
**Branch reviewed:** `copilot/review-repo-architecture`  
**Test suite:** 116 / 116 passing

---

## 1. Executive Summary

Trainsight is a self-hosted, power-based scientific training system for endurance athletes. The architecture is well-structured: a strict CSV → pure-function → cached-API → React-SPA pipeline with clear layer boundaries. Core computation is fully separated from I/O, the science framework is YAML-driven and extensible, and the frontend design system is consistent. The three major feature specs (multi-source architecture, zone-aware training analysis, AI-generated training plans) have all reached various stages of implementation — the zone-aware analysis is shipped, the AI plan module is functional, and the multi-source provider system is partially in place.

The main areas of debt are (a) the dynamic activity-type routing described in the updated design spec is not yet implemented, (b) `data_loader.py` still hard-codes the Garmin+Stryd+Oura CSV paths rather than routing through the provider interfaces, and (c) the `UserConfig` dataclass still holds the old single-pointer `preferences.activities` field rather than the `activity_routing` dict.

---

## 2. Architecture Overview

```
sync/*.py → data/**/*.csv
                 ↓
         analysis/data_loader.py  (CSV I/O, merge)
                 ↓
         analysis/metrics.py      (pure functions, no I/O)
         analysis/zones.py
         analysis/science.py      (YAML-driven theory loader)
                 ↓
         api/deps.py              (5-min cache, get_dashboard_data())
                 ↓
         api/routes/*.py          (thin wrappers, /api/ prefix)
                 ↓
         web/src/                 (React + TS + Tailwind v4 + Recharts)
```

### Layer Boundaries — Compliance

| Rule | Status |
|------|--------|
| Metrics functions are pure (no I/O, no global state) | ✅ Upheld across all of `metrics.py` |
| All CSV I/O in `data_loader.py` | ✅ No direct `pd.read_csv` outside `data_loader.py` |
| Routes are thin (no computation in handlers) | ✅ All routes delegate to `deps.py` |
| All frontend data via `useApi<T>` hook | ✅ No direct fetch calls in components |
| Data numbers use `font-data` class | ✅ Consistent in all pages |

---

## 3. Module-by-Module Analysis

### 3.1 `sync/` — Data Pipeline

**Strengths**
- `csv_utils.append_csv()` is used by all sync scripts for dedup-on-write. ✅
- Stryd sync is API-only (email/password); the Playwright/token fallback was cleanly removed.
- `sync_all.py` orchestrates all three sources with shared error handling and optional `--from-date` argument.

**Gaps**
- `sync/stryd_sync.py` is 884 lines — significantly larger than `garmin_sync.py` (402) and `oura_sync.py` (122). Some extraction of helper functions would reduce review surface.
- No sync script for Coros despite `PLATFORM_CAPABILITIES` declaring Coros support. The capability matrix is ahead of the implementation.

---

### 3.2 `analysis/data_loader.py` — Data Loading & Merge

**Strengths**
- `load_all_data()` returns a well-named dict of DataFrames. Type safety is maintained at boundaries with `_read_csv_safe()` (returns empty DataFrame on missing file).
- `match_activities()` correctly handles multi-activity days and timezone ambiguity (matches by date first, falls back to timestamp proximity).
- `load_data()` applies the `UserConfig` source preferences before returning, so callers receive the correctly routed data.

**Gaps / Design Debt**

1. **Hard-coded CSV paths.** `load_all_data()` directly maps platform names to CSV paths. The provider interfaces defined in `analysis/providers/` (`ActivityProvider`, `RecoveryProvider`, etc.) are not yet wired into the data loading path — they exist as adapters around the same CSV paths, but `data_loader.py` bypasses them. The intent from the multi-source design spec was for `load_data()` to delegate to provider objects.

2. **No `discover_activity_types()`.** The updated design spec (2026-03-23) calls for `discover_activity_types(connections, data_dir) -> dict[str, list[str]]` and `_load_activities_routed()` to live here. Neither exists yet.

3. **`activity_routing` not in `UserConfig`.** The `UserConfig` dataclass still has `preferences["activities"]` as a single string, not the `activity_routing: dict[str, str]` design. The spec update was reflected in the design doc but not propagated to code.

---

### 3.3 `analysis/metrics.py` — Computation Core

**Strengths**
- All public functions have type hints and docstrings. ✅
- Formulas cite their sources (Riegel exponent, Stryd race power fractions, Banister TRIMP). ✅
- `diagnose_training()` was successfully updated (zone-aware PR #10) to accept `zone_boundaries`, `zone_names`, and `target_distribution` parameters, replacing hardcoded 4-zone classification with a dynamic loop.
- `distribution` output changed from a fixed dict (`{supra_cp: N, ...}`) to a list of `{name, actual_pct, target_pct}` dicts, enabling the frontend to render any zone count without hardcoding.
- `analyze_recovery()` implements a two-protocol HRV methodology (log-normal baseline + Smallest Worthwhile Change) with proper citations.
- `compute_cp_trend()` uses linear regression over recent CP estimates. Slope and direction are passed to the AI context builder and displayed in the dashboard.

**Minor Issues**
- `DISTANCE_CONFIGS` ultra fractions (50K–100mi) are explicitly flagged as estimates — good practice. However, the flag is only in a code comment; the `ScienceNote` component pattern used in the frontend is not applied to the ultra-distance predictions page.
- `_add_diagnosis_items()` (the text-based diagnosis generator) adapts to zone theory targets when provided, but falls back to generic polarisation checks (70–85% easy threshold) when no target is given. This is fine today but should be documented explicitly since the fallback behaviour may surprise future contributors.

---

### 3.4 `analysis/zones.py` — Zone Calculation

**Strengths**
- `compute_zones()` supports variable zone counts (N boundaries → N+1 zones) for both ascending (power/HR) and descending (pace) metrics. ✅
- `classify_intensity()` maintains backward-compatible legacy key names (`easy`, `tempo`, `threshold`, `supra_threshold`) for 4-boundary configs, and falls back to `zone_N` for other counts.
- Default names per base (`_DEFAULT_NAMES`) are driven by the Coggan 5-zone model and are overridable.

**Gap**
- The "All others" / `default` routing concept from the dynamic activity-type spec requires `classify_intensity()` to work across non-running activity types (e.g., HR-based TRIMP for cycling). Currently the function assumes a single active `TrainingBase`. No structural issue, but cross-sport load classification will need a small wrapper.

---

### 3.5 `analysis/science.py` — YAML-Driven Theory Framework

**Strengths**
- Four pillars (load, recovery, prediction, zones) each have multiple YAML-defined theories.
- Theory objects carry citations, `params`, and optional `tsb_zones` fields.
- `recommend_science()` provides data-driven recommendations (e.g., suggest Polarized if athlete skews easy-heavy, suggest Banister Ultra for high weekly volume).
- `load_active_science()` merges the four active theories into a single dict passed to `deps.py`, so the analysis layer always gets the currently-selected scientific framework.

**Current theories:**

| Pillar | Theories |
|--------|----------|
| Load | Banister PMC, Banister Ultra |
| Recovery | Composite (HRV + sleep + readiness), HRV-weighted |
| Prediction | Critical Power (Stryd), Riegel (pace) |
| Zones | Coggan 5-Zone, Seiler Polarized 3-Zone |

**Gap**
- Only two zone theories are provided. A "Threshold/Pyramidal" theory (commonly used by Lydiard-based coaches) would complete the set discussed in `docs/studies/openai.md` and give users a meaningful three-way choice.

---

### 3.6 `analysis/config.py` — User Configuration

**Strengths**
- `UserConfig` is a clean Python dataclass with `__post_init__` validation.
- `_migrate_config()` handles the old `sources` format seamlessly.
- `PlanSource` correctly includes `"ai"` as a special value separate from `PLATFORM_CAPABILITIES`.
- `DEFAULT_ZONES` matches the boundaries in `coggan_5zone.yaml` exactly — no drift.

**Gap**
- `activity_routing: dict[str, str]` is not yet in `UserConfig`. The field is described in the updated spec but absent in code. Until implemented, per-type routing will not survive a settings save/reload.
- The `science` field (active theory per pillar) is present and correct. No issues here.

---

### 3.7 `analysis/providers/` — Provider Adapters

**Strengths**
- ABCs (`ActivityProvider`, `RecoveryProvider`, `FitnessProvider`, `PlanProvider`) are defined with typed signatures.
- All four platform adapters (Garmin, Stryd, Oura, AI) are implemented.
- `AiPlanProvider` reads `data/ai/training_plan.csv` and checks staleness via `plan_meta.json`.
- `PLATFORM_CAPABILITIES` is defined in `config.py` (not scattered across providers).

**Gap**
- Provider instances are not registered in `analysis/providers/__init__.py` as a live registry. The design spec calls for `dict` lookup; currently the providers are plain classes that must be instantiated manually. No dispatch mechanism ties `UserConfig.preferences` to the correct provider at runtime — `data_loader.py` still uses its own path logic.

---

### 3.8 `api/deps.py` — Cached Data Layer

**Strengths**
- `get_dashboard_data()` is the single entry point for all computed data. Routes call nothing else directly. ✅
- 5-minute TTL cache with explicit `invalidate_cache()` called on settings writes.
- Zone config and active science theories are correctly threaded into `diagnose_training()` after PR #10.
- `_resolve_thresholds()` merges auto-detected values (from Stryd CP estimates, Garmin LTHR) with manual overrides — matching the spec's resolution order.

**Minor Issues**
- `get_dashboard_data()` is 335 lines (lines 739–1074). Several private builders (`_build_race_countdown`, `_build_compliance`, `_build_workout_flags`) are large enough that they could be moved to `metrics.py` as pure functions. The current arrangement is functional but harder to unit-test.
- No `discovered_activity_types` field in the settings API response yet (needed by the frontend routing UI described in the spec).

---

### 3.9 `api/ai.py` — AI Training Context Builder

**Strengths**
- `build_training_context()` correctly includes individual sessions with per-split data — the critical detail that allows an LLM to assess actual interval quality vs. diluted activity averages.
- `validate_plan()` applies all checks from the design spec (date range, power bounds 40–130% CP, completeness, distribution sanity).
- `check_plan_staleness()` checks both age (>4 weeks) and CP drift (>3%).
- Graceful: nothing in the core API requires `api/ai.py` to succeed; the module is only called from the Claude Code skill and the `/api/ai/context` endpoint.

**Gap**
- `scripts/build_training_context.py` (the CLI entry point referenced by the `/training-plan` skill) exists in the spec but is not yet created. The skill cannot be invoked until this script is present.

---

### 3.10 `web/src/` — Frontend

**Design System Compliance**

| Rule | Status |
|------|--------|
| All components use shadcn/ui primitives | ✅ |
| Data numbers use `font-data` class | ✅ |
| Chart colors from `@/lib/chart-theme.ts` | ✅ |
| No raw hex colors in components | ✅ |
| `useApi<T>` hook for all data fetching | ✅ |
| TypeScript strict — API responses typed in `types/api.ts` | ✅ |
| Light + dark theme via `.dark` class | ✅ |

**Implemented Pages:** Today, Training, History, Goal, Settings, Science  

**Key components added in recent PRs**
- `ZoneAnalysisCard.tsx` — dynamic N-zone table with actual vs. target percentages and amber alert for >5pp deviation.
- `DistributionBar.tsx` — updated to accept dynamic zone list (no longer hardcodes 4 keys).
- `ScienceNote.tsx` — expandable citation block used on prediction-related cards.

**TypeScript Types (`api.ts`)**
- `ZoneDistribution`, `ZoneRange` interfaces added after PR #10. ✅
- `PlanSourceName` includes `"ai"`. ✅
- `SettingsResponse` does not yet include `discovered_activity_types`. ❌ (pending)

---

## 4. Science Grounding

The `docs/studies/openai.md` literature review covers five domains: training load models (Banister, PMC), intensity distribution (polarized, threshold, HIIT), periodization (linear, block, reverse), recovery (sleep, nutrition, HRV), and monitoring tools. This review directly informed the science framework implementation:

| Literature finding | Implementation |
|--------------------|----------------|
| Banister impulse-response (fitness + fatigue exponentials) | `banister_pmc.yaml`, `compute_ewma_load()` with 42-day CTL / 7-day ATL |
| Polarized ≈80/20 distribution (Seiler) | `polarized_3zone.yaml` with `target_distribution: [0.80, 0.05, 0.15]` |
| CTL/ATL/TSB (PMC) fresh = TSB +5–+10 | `compute_tsb()`, TSB zone config in `banister_pmc.yaml` |
| HRV-guided training (small but positive effect on submaximal adaptations) | `analyze_recovery()` using log-normal SWC protocol |
| Split-level power analysis (activity avg diluted by warmup/cooldown) | `diagnose_training()` uses `activity_splits.csv`, not `avg_power` |
| Stryd race power fractions | `DISTANCE_CONFIGS` in `metrics.py` with Stryd calculator citation |
| Riegel fatigue exponent 1.06 | `RIEGEL_EXPONENT` constant with paper citation |

**Gap:** The literature review discusses block periodization, 3-week mesocycles, and progressive overload (~5–10% weekly increase). These principles are referenced in the AI plan generation system prompt (design spec) but are not encoded as configurable parameters in the science framework. A `periodization.yaml` theory pillar would make these principles explicit and user-selectable.

---

## 5. Open Design Debt (Spec vs. Implementation)

The following items are in the approved or draft design specs but not yet in code:

### 5.1 Dynamic Activity-Type Routing (High Priority)
**Spec:** `2026-03-23-multi-source-design.md` (updated 2026-04-10)  
**Status:** Not implemented

- `discover_activity_types(connections, data_dir) -> dict[str, list[str]]` — missing from `data_loader.py`
- `_load_activities_routed()` — missing from `data_loader.py`
- `activity_routing: dict[str, str]` — missing from `UserConfig`
- `discovered_activity_types` — missing from `GET /api/settings` response
- Settings UI routing section — not yet built in `Settings.tsx`

### 5.2 Provider Registry Dispatch (Medium Priority)
**Spec:** `2026-03-23-multi-source-design.md`  
**Status:** Partial — providers exist as classes but are not wired to `data_loader.py`

The `analysis/providers/__init__.py` does not expose a lookup that maps `UserConfig.preferences` → provider instance. Until this is wired, adding a new data source still requires modifying `data_loader.py` directly.

### 5.3 AI Plan CLI Entry Point (Medium Priority)
**Spec:** `2026-03-24-ai-training-plan-design.md`  
**Status:** Not implemented

`scripts/build_training_context.py` does not exist. The Claude Code `/training-plan` skill cannot be invoked without it. This is a one-file, low-effort item.

### 5.4 Threshold / Pyramidal Zone Theory (Low Priority)
**Spec:** Discussed in `docs/studies/openai.md`  
**Status:** Not implemented

Adding a third zone theory would give users the full set of scientifically-documented distribution models. The YAML schema and `compute_zones()` already support it — only the YAML file is missing.

### 5.5 `ScienceNote` on Ultra Distance Predictions (Low Priority)
**Status:** Ultra fractions flagged as estimates in code but not surfaced in the UI.

The `ScienceNote` component pattern is established. Adding a note to the race prediction card for 50K+ distances is a small, targeted UI change.

---

## 6. Recommendations

### Immediate (unblocks planned work)

1. **Add `scripts/build_training_context.py`** — 20-line CLI wrapper around `api/ai.build_training_context()` that prints JSON to stdout. Required for the `/training-plan` skill.

2. **Add `activity_routing` to `UserConfig`** — replace `preferences["activities"]` with `activity_routing: dict[str, str]` defaulting to `{"default": "garmin"}`. Update `_migrate_config()` to convert the old field.

3. **Implement `discover_activity_types()`** in `data_loader.py` — read each connected provider's activities CSV, return distinct `activity_type` values per provider. This unlocks the settings UI routing section.

### Near-Term (architectural health)

4. **Wire providers to `data_loader.load_data()`** — instead of hand-coding paths in `load_all_data()`, instantiate providers from the registry and call `provider.load_activities(data_dir)`. This makes adding Coros (or any new source) a matter of adding one YAML + one provider class, with zero changes to the loading pipeline.

5. **Extract large builders from `deps.py` into `metrics.py`** — `_build_race_countdown()` and `_build_compliance()` contain significant computation logic that would benefit from unit tests. Moving them to `metrics.py` as pure functions follows the established pattern.

6. **Add `discovered_activity_types` to `GET /api/settings`** — needed by the frontend routing UI.

### Longer-Term (science framework)

7. **Add `polarized_pyramidal.yaml`** (Threshold/Pyramidal zone theory) to complete the literature-grounded theory set.

8. **Add a `periodization` science pillar** — encode block periodization, progressive overload, and taper parameters as YAML-driven, selectable theories that the AI plan builder can reference.

---

## 7. Test Coverage Summary

All 116 tests pass. Coverage spans:

| Test file | What it covers |
|-----------|----------------|
| `test_metrics.py` | EWMA load, TSB, marathon prediction, recovery analysis, CP milestone, diagnosis |
| `test_ai_plan.py` | Context builder structure, plan validation, staleness checks |
| `test_data_loader.py` | CSV loading, activity merge, threshold resolution |
| `test_integration.py` | End-to-end: sample data → metrics → dashboard data |
| `test_garmin_sync.py` | Garmin sync parsing and dedup |
| `test_stryd_sync.py` | Stryd API response parsing |
| `test_oura_sync.py` | Oura readiness and sleep parsing |
| `test_csv_utils.py` | Dedup-on-write append utility |
| `test_compute_lap_splits.py` | Per-lap split computation |
| `test_stryd_upload.py` | Stryd plan upload parsing |

**Coverage gaps:**
- No tests for `analysis/science.py` (theory loading, recommendation logic).
- No tests for the zone-aware diagnosis path added in PR #10 (dynamic zone distribution).
- No tests for `analysis/zones.py` edge cases (pace zones, >5-zone configs).

---

## 8. Summary Table

| Area | Health | Key Action |
|------|--------|------------|
| Layer separation (pure functions, I/O, API, UI) | 🟢 Strong | — |
| Test suite | 🟢 116/116 | Add zone + science tests |
| Zone-aware training analysis | 🟢 Shipped (PR #10) | — |
| AI plan context builder & validation | 🟢 Functional | Add CLI script |
| Science framework (YAML theories) | 🟢 Extensible | Add pyramidal zone theory |
| Provider interfaces | 🟡 Defined, not wired | Wire to data_loader |
| Dynamic activity-type routing | 🔴 Not started | Implement spec |
| `UserConfig` schema | 🟡 Partial | Add `activity_routing` field |
| Settings API (`discovered_activity_types`) | 🔴 Missing | Add to GET response |
| Coros sync | 🟡 Capability declared | Sync script not built |
