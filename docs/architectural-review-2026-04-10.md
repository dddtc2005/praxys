# Trainsight — Architectural Review

> **Historical snapshot (2026-04-10).** This review was conducted before the database migration (CSV → SQLite), auth system, and multi-user architecture were implemented. Many issues identified here (CSV race conditions, no auth, single-user) have been resolved. Kept for historical context.

**Date:** 2026-04-10  
**Test suite:** 116 / 116 passing

---

## 1. Executive Summary

Trainsight is a self-hosted, power-based scientific training system for endurance athletes. The architecture is well-structured: a strict CSV → pure-function → cached-API → React-SPA pipeline with clear layer boundaries. Core computation is fully separated from I/O, the science framework is YAML-driven and extensible, and the frontend design system is consistent. The three major feature specs (multi-source architecture, zone-aware training analysis, AI-generated training plans) have all reached various stages of implementation — the zone-aware analysis is shipped, the AI plan module is functional, and the multi-source provider system is partially in place.

**Spec debt** — the main gaps between design specs and code are: (a) dynamic activity-type routing not yet implemented, (b) `data_loader.py` hard-codes CSV paths instead of routing through provider interfaces, and (c) `UserConfig` lacks the `activity_routing` dict.

**Runtime quality debt** — independent of specs, the codebase has: (d) a monolithic `deps.py` (1074 LOC) that is difficult to test and maintain, (e) no structured logging (all errors use `print()`), (f) race conditions on concurrent CSV writes during sync, (g) no frontend caching, polling, or error recovery, and (h) duplicated threshold detection and plan filtering logic.

**Architectural decisions validated** — CSV storage and YAML-based science framework are the right choices for the current scale and use case. Both need targeted hardening (file locking, schema validation) rather than replacement.

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

## 4. Runtime Quality Analysis

This section covers issues found through independent code review that are not captured in any design spec — they are about how the existing code behaves at runtime.

### 4.1 `deps.py` is a God Module (1074 LOC)

`get_dashboard_data()` is the single aggregation point for all dashboard metrics. At 335 lines, it computes ~15 derived datasets in one function: fitness/fatigue, recovery, training signal, diagnosis, race prediction, compliance, workout flags, and more.

**Impact:**
- Impossible to unit-test individual metric types — must run the entire pipeline
- Cache is all-or-nothing (5-min TTL on everything); no partial invalidation
- Adding a new metric means editing this function
- Several private builders (`_build_race_countdown`, `_build_compliance`, `_build_workout_flags`) contain significant computation that belongs in `metrics.py`

**Solution:** Split into domain-specific aggregators that can be cached and tested independently:
```python
# api/deps.py — thin orchestrator
def get_dashboard_data() -> dict:
    return {
        **get_fitness_metrics(data, config, science),
        **get_recovery_metrics(data, config, science),
        **get_training_signal(data, config, science),
        **get_diagnostics(data, config, science),
        **get_race_predictions(data, config, science),
    }
```
Move pure computation helpers (`_build_race_countdown`, `_build_compliance`) to `metrics.py`.

### 4.2 No Structured Logging

All Python modules use `print()` for errors and warnings — no log levels, no rotation, no structured output.

**Examples:**
- `api/routes/plan.py`: `print(f"ERROR: Stryd login failed: {e}")`
- `analysis/config.py`: `print(f"WARNING: Invalid platform...")`
- `api/routes/settings.py`: `print(f"WARNING: Corrupt push status...")`

**Impact:** Errors are mixed with stdout, invisible in production, and impossible to filter by severity.

**Solution:** Replace all `print()` calls with Python `logging` module. Use `logging.getLogger(__name__)` per module. Configure a single format in `api/main.py`:
```python
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
```

### 4.3 Bare Exception Handling

Several locations catch broad exceptions and silently continue:

- `api/deps.py` lines 85–95: `except (KeyError, Exception): continue`
- `analysis/config.py` `__post_init__`: prints warning but doesn't raise on invalid config
- `api/routes/science.py` PUT handler: `except FileNotFoundError: continue` (invalid theory ID silently ignored)

**Impact:** Programming bugs are masked. A misspelled theory ID, missing CSV column, or type error produces no error — just wrong/missing data.

**Solution:** Catch specific expected exceptions only. Let unexpected exceptions propagate. Validate config at load time with strict checks (raise `ValueError` for invalid states).

### 4.4 Sync Race Conditions

`/api/routes/sync.py` uses `threading.Lock()` to protect the in-memory `_sync_status` dict, but CSV file writes in `csv_utils.append_rows()` have no locking. Since `append_rows()` does read-all → merge-in-memory → rewrite-all, concurrent syncs to overlapping files can lose data:

1. Garmin sync reads `activities.csv` (state A)
2. Stryd sync reads `activities.csv` (also state A)
3. Garmin writes merged result (state B)
4. Stryd writes its merged result from state A — **overwrites Garmin's write**

In practice, each source writes to its own directory (`garmin/*.csv`, `stryd/*.csv`), so the risk is low but not zero (e.g., if both sources ever write to a shared file).

**Solution:** Add file-level locking in `csv_utils.append_rows()`:
```python
import portalocker  # cross-platform file locking

def append_rows(path, new_rows, key_column):
    with portalocker.Lock(path + ".lock", timeout=30):
        existing = read_csv(path)
        merged = _merge(existing, new_rows, key_column)
        _write_csv(path, merged)
```

### 4.5 Frontend Architecture Gaps

The frontend passes design system compliance (shadcn/ui, `font-data`, chart theme) but has structural issues:

**No caching or polling.** Each page independently calls `useApi('/api/today')`, `useApi('/api/training')`, etc. There is no shared cache — navigating between pages re-fetches data. Sync status is fetched once and never polls for updates.

**No error recovery.** When a fetch fails, the error message persists permanently. No retry button, no stale-while-revalidate fallback.

**`UpcomingPlanCard.tsx` is 465 LOC** — the largest component by far. It mixes Stryd plan push logic, workout form editing, push status tracking, plan generation UI, and example workout suggestions. Should be split into 3–4 focused components.

**Solution:** Migrate from raw `useApi` to React Query (TanStack Query):
- Automatic refetch on stale data and window focus
- Shared cache across pages (navigating doesn't re-fetch)
- Built-in retry with exponential backoff
- Manual invalidation after sync completes
- `refetchInterval` for polling sync status

### 4.6 Duplicated Code

**Threshold detection** exists in two places:
- `api/deps.py` `_resolve_thresholds()` (lines 73–110)
- `api/routes/settings.py` `_detect_thresholds()` (lines 29–60)

Both iterate over connected platforms and detect CP/LTHR values with similar logic.

**Plan date filtering** is duplicated between `api/views.py` and `api/routes/plan.py`.

**Solution:** Extract shared utilities:
```python
# analysis/thresholds.py
def detect_from_providers(connections: list[str], data_dir: str) -> dict

# analysis/filtering.py
def filter_plan_after_date(plan: pd.DataFrame, start_date: date) -> pd.DataFrame
```

### 4.7 Data Integrity

**No CSV schema validation.** `csv_utils.append_rows()` accepts any dict of columns. Missing columns become empty strings, which downstream code converts to NaN via `pd.to_numeric(errors="coerce")`. No warning is raised.

**Fragile timezone parsing.** `data_loader.py` `_parse_time()` uses a string hack (`replace("+00:00", "Z")`) to normalize timezones. Three fallback format strings are tried silently.

**No physiological bounds checking.** HR, power, and pace values are accepted without validation. Negative power, HR > 300, or pace < 1 min/km would silently flow into metrics.

**Solution:** Add a lightweight schema check in `_read_csv_safe()`:
```python
REQUIRED_COLUMNS = {
    "activities": ["date", "distance_km", "duration_sec"],
    "power_data": ["date", "avg_power"],
    # ...
}

def _read_csv_safe(path, schema_key=None):
    df = pd.read_csv(path)
    if schema_key and schema_key in REQUIRED_COLUMNS:
        missing = set(REQUIRED_COLUMNS[schema_key]) - set(df.columns)
        if missing:
            logger.warning(f"{path} missing columns: {missing}")
    return df
```

---

## 5. Architectural Decisions

### 5.1 CSV vs Database: Keep CSV

**Decision: CSV is the right storage format. Do not migrate to a database.**

| Factor | Current State | Assessment |
|--------|--------------|------------|
| Data volume | ~3,000 rows across 9 files | Trivially small — fits in memory |
| Query pattern | Full-table load into pandas every time | No selective queries that would benefit from indexes |
| Write pattern | Append-only upsert, ~1 sync/day | Not write-heavy |
| Users | Single-user, self-hosted | No concurrent access in practice |
| Growth rate | ~365 rows/year | At 10 years: ~30K rows, still trivial |
| Joins | Date-based pandas merges | Simple, well-understood |
| Portability | Human-readable, git-friendly, copy-friendly | A database would be opaque |

The computation model loads everything into pandas DataFrames regardless — `compute_ewma_load()`, `diagnose_training()`, and all other metric functions are numpy/pandas operations. A database would add a dependency and migration tooling for zero query performance gain.

**The one real problem — concurrent sync writes — is a file-locking fix, not a migration** (see §4.4).

**Revisit if:** multi-user support is added, or sub-second queries on historical data are needed.

### 7.2 Science Framework: Keep YAML, Add Validation

**Decision: YAML is the right format for theory files. Add Pydantic schema validation.**

The 10 developer-authored theories are structured reference data — computation parameters, display text, and citations bundled together. They change infrequently and are loaded once at startup.

| Alternative | Why Not |
|-------------|---------|
| Markdown | Cannot express nested params (time constants, zone boundaries, distributions). Frontmatter + body is just worse YAML. |
| Skills | Skills are CLI interaction patterns, not data. A theory is a parameter set that feeds computation, not something you "invoke." |
| Database | 10 static records don't need a database. Loses human editability and git diffs. |
| JSON | Viable but worse to hand-edit. No comments, verbose syntax. |
| Python dataclasses | Sacrifices separation between "science content" and "code." |

**The real problem is untyped parameter access.** Theory params are consumed via `.get()` with silent defaults:
```python
ctl_tc = int(load_params.get("ctl_time_constant", 42))  # silent default if missing
```
If a new theory omits `ctl_time_constant`, it silently uses 42 — the wrong value.

**Solution:** Add Pydantic validators per pillar that run at load time:
```python
class LoadTheoryParams(BaseModel):
    ctl_time_constant: int
    atl_time_constant: int
    rss_exponent: float = 2.0

class ZoneTheoryParams(BaseModel):
    zone_count: int
    boundaries: dict[str, list[float]]
    zone_names: list[str] | dict[str, list[str]]
    target_distribution: list[float]
```

Keep theories as YAML files, but fail fast on load if required fields are missing or wrong type.

**Revisit if:** users need to create custom theories via the UI (would need a form + API + persistence layer).

---

## 6. Science Grounding

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

## 7. Open Design Debt (Spec vs. Implementation)

The following items are in the approved or draft design specs but not yet in code:

### 7.1 Dynamic Activity-Type Routing (High Priority)
**Spec:** `2026-03-23-multi-source-design.md` (updated 2026-04-10)  
**Status:** Not implemented

- `discover_activity_types(connections, data_dir) -> dict[str, list[str]]` — missing from `data_loader.py`
- `_load_activities_routed()` — missing from `data_loader.py`
- `activity_routing: dict[str, str]` — missing from `UserConfig`
- `discovered_activity_types` — missing from `GET /api/settings` response
- Settings UI routing section — not yet built in `Settings.tsx`

### 7.2 Provider Registry Dispatch (Medium Priority)
**Spec:** `2026-03-23-multi-source-design.md`  
**Status:** Partial — providers exist as classes but are not wired to `data_loader.py`

The `analysis/providers/__init__.py` does not expose a lookup that maps `UserConfig.preferences` → provider instance. Until this is wired, adding a new data source still requires modifying `data_loader.py` directly.

### 7.3 AI Plan CLI Entry Point (Medium Priority)
**Spec:** `2026-03-24-ai-training-plan-design.md`  
**Status:** Not implemented

`scripts/build_training_context.py` does not exist. The Claude Code `/training-plan` skill cannot be invoked without it. This is a one-file, low-effort item.

### 7.4 Threshold / Pyramidal Zone Theory (Low Priority)
**Spec:** Discussed in `docs/studies/openai.md`  
**Status:** Not implemented

Adding a third zone theory would give users the full set of scientifically-documented distribution models. The YAML schema and `compute_zones()` already support it — only the YAML file is missing.

### 7.5 `ScienceNote` on Ultra Distance Predictions (Low Priority)
**Status:** Ultra fractions flagged as estimates in code but not surfaced in the UI.

The `ScienceNote` component pattern is established. Adding a note to the race prediction card for 50K+ distances is a small, targeted UI change.

---

## 8. Test Coverage

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
- No tests for `analysis/science.py` (theory loading, recommendation logic)
- No tests for the zone-aware diagnosis path added in PR #10 (dynamic zone distribution)
- No tests for `analysis/zones.py` edge cases (pace zones, >5-zone configs)
- No tests for any API route (only sync modules, not route handlers)
- No tests for `analysis/config.py` (load/save/migration)
- No frontend tests

---

## 9. Consolidated Action Plan

All findings from sections 3–8 are merged into a single prioritized backlog. Items are grouped by effort and impact.

### Phase 1: Runtime Safety (quick wins, high impact)

These are targeted fixes to existing code — no new features, no architecture changes.

| # | Item | Files | Effort | Section |
|---|------|-------|--------|---------|
| 1 | **Replace `print()` with `logging`** — Add `logging.getLogger(__name__)` to all Python modules. Configure format in `api/main.py`. | All `.py` files | 1–2 hrs | §4.2 |
| 2 | **Add file locking to CSV writes** — Use `portalocker` in `csv_utils.append_rows()` to prevent concurrent write corruption. | `sync/csv_utils.py`, `requirements.txt` | 30 min | §4.4 |
| 3 | **Narrow exception handling** — Replace `except (KeyError, Exception)` with specific catches. Let unexpected errors propagate. | `api/deps.py`, `analysis/config.py`, `api/routes/science.py` | 1 hr | §4.3 |
| 4 | **Add Pydantic validators for YAML theories** — Validate theory params at load time. Fail fast on missing/wrong-type fields. | `analysis/science.py` (new: `analysis/theory_schema.py`) | 2 hrs | §5.2 |
| 5 | **Add CSV schema validation** — Check required columns in `_read_csv_safe()`. Log warnings for missing columns. | `analysis/data_loader.py` | 1 hr | §4.7 |

### Phase 2: Maintainability (medium effort, high impact)

Refactors that improve testability and reduce duplication without changing behavior.

| # | Item | Files | Effort | Section |
|---|------|-------|--------|---------|
| 6 | **Split `deps.py` into domain aggregators** — Extract `get_fitness_metrics()`, `get_recovery_metrics()`, `get_training_signal()`, `get_diagnostics()`, `get_race_predictions()`. Keep `get_dashboard_data()` as a thin orchestrator. Move pure computation helpers to `metrics.py`. | `api/deps.py` → `api/deps/*.py` or keep flat | 4–6 hrs | §4.1 |
| 7 | **Extract duplicated code** — Create `analysis/thresholds.py` (shared threshold detection) and consolidate plan date filtering. | `api/deps.py`, `api/routes/settings.py`, `api/views.py`, `api/routes/plan.py` | 2 hrs | §4.6 |
| 8 | **Break up `UpcomingPlanCard.tsx`** — Split into `PlanOverview`, `WorkoutEditor`, `StrydPushPanel` components. | `web/src/components/UpcomingPlanCard.tsx` | 2–3 hrs | §4.5 |
| 9 | **Add missing test coverage** — Tests for `science.py` (theory loading, recommendations), `zones.py` (pace zones, N-zone configs), `config.py` (load/save/migration), and at least one API route integration test. | `tests/` | 4–6 hrs | §8 |

### Phase 3: Frontend Architecture (medium effort, UX impact)

| # | Item | Files | Effort | Section |
|---|------|-------|--------|---------|
| 10 | **Migrate to React Query** — Replace `useApi` with TanStack Query for shared cache, automatic refetch, retry, and polling. Add `refetchInterval` for sync status polling. | `web/src/hooks/useApi.ts`, all pages | 4–6 hrs | §4.5 |
| 11 | **Add error recovery UI** — Retry buttons on failed fetches. Stale-while-revalidate for cached data. Loading skeletons already exist (good). | `web/src/pages/*`, `web/src/components/*` | 2 hrs | §4.5 |

### Phase 4: Spec Implementation (larger effort, new features)

These are the design-spec gaps identified in §7. They should be tackled after runtime quality is solid.

| # | Item | Files | Effort | Section |
|---|------|-------|--------|---------|
| 12 | **Add `scripts/build_training_context.py`** — CLI wrapper for `api/ai.build_training_context()`. Required for `/training-plan` skill. | `scripts/build_training_context.py` | 30 min | §7.3 |
| 13 | **Add `activity_routing` to `UserConfig`** — Replace `preferences["activities"]` with `activity_routing: dict[str, str]`. Update migration logic. | `analysis/config.py` | 1 hr | §7.1 |
| 14 | **Implement `discover_activity_types()`** — Read connected providers' CSVs, return distinct activity types per provider. | `analysis/data_loader.py` | 2 hrs | §7.1 |
| 15 | **Wire provider registry to `data_loader`** — Replace hard-coded CSV paths with provider dispatch. | `analysis/providers/__init__.py`, `analysis/data_loader.py` | 4–6 hrs | §7.2 |
| 16 | **Add `discovered_activity_types` to Settings API** + frontend routing UI. | `api/routes/settings.py`, `web/src/pages/Settings.tsx` | 3–4 hrs | §7.1 |

### Phase 5: Science Expansion (low effort, completeness)

| # | Item | Files | Effort | Section |
|---|------|-------|--------|---------|
| 17 | **Add Threshold/Pyramidal zone theory** — Third zone theory YAML file. Infrastructure already supports it. | `data/science/zones/pyramidal.yaml` | 1 hr | §7.4 |
| 18 | **Add `ScienceNote` for ultra predictions** — Flag 50K+ distance estimates in the race prediction UI. | `web/src/components/` (race prediction card) | 30 min | §7.5 |
| 19 | **Add `periodization` science pillar** — Encode block periodization, progressive overload, taper as YAML theories for AI plan builder. | `data/science/periodization/` | 2–3 hrs | §6 |

---

## 10. Summary

| Area | Health | Key Issue | Action Phase |
|------|--------|-----------|--------------|
| Layer separation | 🟢 Strong | — | — |
| Test suite | 🟢 116/116 passing | Coverage gaps in science, zones, config, routes | Phase 2 (#9) |
| Zone-aware analysis | 🟢 Shipped (PR #10) | — | — |
| AI plan module | 🟢 Functional | Missing CLI entry point | Phase 4 (#12) |
| Science framework | 🟢 Extensible | No param validation at load time | Phase 1 (#4) |
| CSV storage | 🟢 Right choice | No file locking on writes | Phase 1 (#2) |
| Error handling | 🔴 print() + bare except | Silent failures, no log levels | Phase 1 (#1, #3) |
| `deps.py` | 🟡 Functional but 1074 LOC | Untestable, all-or-nothing cache | Phase 2 (#6) |
| Frontend data layer | 🟡 Works but fragile | No cache, no retry, no polling | Phase 3 (#10, #11) |
| Code duplication | 🟡 2 duplicated patterns | Threshold detection, plan filtering | Phase 2 (#7) |
| Provider registry | 🟡 Defined, not wired | Hard-coded paths in data_loader | Phase 4 (#15) |
| Activity-type routing | 🔴 Not started | Full spec unimplemented | Phase 4 (#13–16) |
| `UserConfig` schema | 🟡 Partial | Missing `activity_routing` | Phase 4 (#13) |
