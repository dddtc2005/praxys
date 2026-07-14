"""Shared data loading and metric computation for the API."""
import logging
import os
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from analysis.config import load_config
from analysis.data_loader import load_data, select_preferred_source
from analysis.providers.models import ThresholdEstimate
from analysis.training_base import get_display_config
from analysis.science import load_active_science
from analysis.metrics import (
    compute_ewma_load,
    compute_tsb,
    compute_activity_load,
    compute_distribution_match_pct,
    compute_load_compliance_pct,
    has_sufficient_load_history,
    predict_marathon_time,
    predict_time_from_pace,
    daily_training_signal,
    compute_cp_trend,
    required_cp_for_time,
    required_pace_for_time,
    race_honesty_check,
    cp_milestone_check,
    diagnose_training,
    get_distance_config,
    compute_rss,
    compute_trimp,
    compute_rtss,
    analyze_recovery,
    project_tsb,
    is_hard_workout,
    is_rest_workout,
)

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

_env_loaded = False


def _ensure_env():
    global _env_loaded
    if not _env_loaded:
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", "sync", ".env"))
        _env_loaded = True


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _resolve_thresholds(
    config, data_dir: str = None, user_id: str = None, db=None,
) -> ThresholdEstimate:
    """Build ThresholdEstimate from sensor data.

    When ``user_id`` and ``db`` are provided, thresholds come from
    ``fitness_data`` rows written by the sync pipelines. No arbitrary
    user-entered numbers are accepted — every value traces back to a
    connected source (Stryd, Garmin, Oura) or a calculation we perform from
    that source's data. This is the "no guesswork" rule from CLAUDE.md's
    Scientific Rigor section, applied to threshold resolution.

    Source preference: when more than one provider writes the same metric
    (notably CP, where Stryd and Garmin disagree by ~30%), pick the row
    whose ``source`` matches the user's selection. Selection order:

        1. Explicit: ``preferences.threshold_sources[metric_type]`` if set.
        2. Default: whichever source produces the athlete's *activity* data
           (``preferences.activities``). This keeps CP consistent with the
           activities the user is viewing.
        3. Fallback: latest row by date regardless of source.
    """
    if user_id and db:
        result = ThresholdEstimate()
        from db.models import FitnessData

        activity_source = config.preferences.get("activities") or None
        threshold_sources = config.preferences.get("threshold_sources") or {}

        def _latest(metric_type: str) -> float | None:
            """Pick the best fitness_data row for this metric.

            Preferred-source-first, fall back to latest-by-date if the
            preferred source has no rows (or its rows have null/zero values).
            """
            preferred = (
                threshold_sources.get(metric_type)
                or activity_source
            )
            base = db.query(FitnessData).filter(
                FitnessData.user_id == user_id,
                FitnessData.metric_type == metric_type,
                FitnessData.value.isnot(None),
            )
            if preferred:
                row = (
                    base.filter(FitnessData.source == preferred)
                    .order_by(FitnessData.date.desc())
                    .first()
                )
                if row and row.value:
                    return float(row.value)
                # Preferred source exists in the user's preferences but has no
                # rows. Log at debug so the surprising-but-correct fallback
                # ("I picked Stryd, why am I seeing Garmin's value?") is
                # visible to anyone tailing the server log.
                logger.debug(
                    "_resolve_thresholds: preferred source %r for %s has no "
                    "data; falling back to latest-by-date", preferred, metric_type,
                )
            row = base.order_by(FitnessData.date.desc()).first()
            return float(row.value) if row and row.value else None

        _METRIC_MAP = {
            "cp_estimate": "cp_watts",
            "lthr_bpm": "lthr_bpm",
            "lt_pace_sec_km": "threshold_pace_sec_km",
            "max_hr_bpm": "max_hr_bpm",
            "rest_hr_bpm": "rest_hr_bpm",
        }
        for db_metric, est_attr in _METRIC_MAP.items():
            val = _latest(db_metric)
            if val is not None:
                setattr(result, est_attr, val)

        # Derived fallback: Garmin writes per-activity max_hr but no
        # max_hr_bpm fitness_data record, so TRIMP would be skipped for
        # HR-base users without this.
        if result.max_hr_bpm is None:
            from db.models import Activity
            from sqlalchemy import func
            max_hr = db.query(func.max(Activity.max_hr)).filter(
                Activity.user_id == user_id,
                Activity.max_hr.isnot(None),
            ).scalar()
            if max_hr:
                result.max_hr_bpm = float(max_hr)

        return result

    # File-based path (backward compatibility)
    from analysis.thresholds import resolve_thresholds_to_estimate
    return resolve_thresholds_to_estimate(
        config.thresholds, config.connections, data_dir
    )


def _compute_daily_load(
    merged_activities: pd.DataFrame,
    date_range: pd.DatetimeIndex,
    config,
    thresholds: ThresholdEstimate,
) -> pd.Series:
    """Build a daily load series using the configured training base.

    Falls back to RSS (power) if the required data/thresholds are missing.
    """
    base = config.training_base
    if merged_activities.empty:
        return pd.Series([0.0] * len(date_range), index=date_range)

    merged = merged_activities.copy()

    # Compute per-activity load based on training base
    loads = []
    for _, row in merged.iterrows():
        load = None

        # For power base: prefer Stryd's pre-computed RSS (more accurate than
        # our formula which uses diluted activity-average power)
        if base == "power" and "rss" in merged.columns:
            rss_val = pd.to_numeric(pd.Series([row.get("rss", 0)]), errors="coerce").iloc[0]
            if pd.notna(rss_val) and rss_val > 0:
                load = float(rss_val)

        # Compute from raw data if no pre-computed value (HR, pace, or missing RSS)
        if load is None:
            duration = pd.to_numeric(pd.Series([row.get("duration_sec", 0)]), errors="coerce").iloc[0]
            power = pd.to_numeric(pd.Series([row.get("avg_power")]), errors="coerce").iloc[0] if pd.notna(row.get("avg_power")) else None
            hr = pd.to_numeric(pd.Series([row.get("avg_hr")]), errors="coerce").iloc[0] if pd.notna(row.get("avg_hr")) else None
            dist = pd.to_numeric(pd.Series([row.get("distance_km", 0)]), errors="coerce").iloc[0]
            pace = (duration / dist) if dist and dist > 0 and duration and duration > 0 else None

            load = compute_activity_load(
                base, float(duration) if pd.notna(duration) else 0,
                thresholds,
                avg_power=float(power) if pd.notna(power) and power else None,
                avg_hr=float(hr) if pd.notna(hr) and hr else None,
                avg_pace_sec_km=float(pace) if pace else None,
            )

            # Cross-base fallback: if primary base can't compute, try other metrics
            # e.g., power base with no power → use HR-based TRIMP as approximation
            if load is None and pd.notna(duration) and duration > 0:
                if hr and pd.notna(hr) and thresholds.max_hr_bpm:
                    from analysis.metrics import compute_trimp
                    rest_hr = thresholds.rest_hr_bpm or 60
                    load = compute_trimp(float(duration), float(hr), rest_hr, thresholds.max_hr_bpm)

        loads.append(load or 0.0)

    merged["_load"] = loads
    daily = merged.groupby("date")["_load"].sum()
    daily = daily.reindex(date_range.date, fill_value=0.0)
    return daily.astype(float)


def _parse_pace_str(value) -> float | None:
    """Parse a plan pace string ("4:30", "4:30/km", "4:30 min/km") → sec/km.

    Also accepts a bare number interpreted as sec/km. Returns None for
    empty / unparseable values.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if v > 0 else None
    text = str(value).strip()
    if not text:
        return None
    # Strip trailing units (most-specific first so "min/km" goes before "/km").
    for suffix in ("min/km", "mi/km", "/km", "min", "sec"):
        while text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    if ":" in text:
        try:
            minutes, seconds = text.split(":", 1)
            total = int(minutes) * 60 + float(seconds)
            return total if total > 0 else None
        except ValueError:
            return None
    try:
        v = float(text)
        return v if v > 0 else None
    except ValueError:
        return None


def _plan_workout_load(
    row, dur_sec: float, training_base: str, thresholds: ThresholdEstimate,
) -> float:
    """Estimate the load score (RSS / TRIMP / rTSS) for one planned workout.

    Uses the midpoint of the target range for the configured base. Falls
    back to a flat ~60 units/hour estimate when the plan row has no
    targets for the active base (we still don't want the CTL/ATL projection
    to flatline just because the plan lacks intensity hints).
    """
    if is_rest_workout(row.get("workout_type")):
        return 0.0
    if dur_sec <= 0:
        return 0.0

    def _midpoint(lo, hi) -> float | None:
        if lo is not None and hi is not None and lo > 0 and hi > 0:
            return (lo + hi) / 2
        if hi is not None and hi > 0:
            # ESTIMATE -- conservative midpoint proxy when only a ceiling exists.
            return hi * 0.85
        if lo is not None and lo > 0:
            return lo
        return None

    def _num(v) -> float | None:
        if v is None:
            return None
        try:
            n = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
        except (TypeError, ValueError):
            return None
        if pd.isna(n) or n <= 0:
            return None
        return float(n)

    if training_base == "power" and thresholds.cp_watts and thresholds.cp_watts > 0:
        avg_p = _midpoint(_num(row.get("target_power_min")), _num(row.get("target_power_max")))
        if avg_p:
            return compute_rss(dur_sec, avg_p, thresholds.cp_watts)
    elif training_base == "hr" and thresholds.max_hr_bpm and thresholds.max_hr_bpm > 0:
        avg_hr = _midpoint(_num(row.get("target_hr_min")), _num(row.get("target_hr_max")))
        if avg_hr:
            rest_hr = thresholds.rest_hr_bpm or 60
            return compute_trimp(dur_sec, avg_hr, rest_hr, thresholds.max_hr_bpm)
    elif training_base == "pace" and thresholds.threshold_pace_sec_km:
        p_fast = _parse_pace_str(row.get("target_pace_min"))
        p_slow = _parse_pace_str(row.get("target_pace_max"))
        avg_pace = _midpoint(p_fast, p_slow)
        if avg_pace:
            return compute_rtss(dur_sec, avg_pace, thresholds.threshold_pace_sec_km)

    # ESTIMATE -- plan row has no targets we can use for this base, so assume
    # a moderate ~60 units/hour. Note that RSS / TRIMP / rTSS are NOT
    # formally equated at 60 units/hour; 60 lands in a roughly tempo-ish
    # band for each scale (RSS and rTSS at IF ≈ 0.77; TRIMP at ~0.70 HR
    # reserve) which is coincidence, not derivation. Use this only so the
    # projection curve keeps moving when we have no better signal, and
    # flag the compliance chart via ``planned_estimated`` so the user
    # knows the number is a placeholder.
    return (dur_sec / 3600) * 60


def _plan_row_duration_sec(row) -> float:
    dur_min = pd.to_numeric(
        pd.Series([row.get("planned_duration_min", 0)]), errors="coerce"
    ).iloc[0]
    return float(dur_min) * 60 if pd.notna(dur_min) and dur_min > 0 else 0.0


def _has_base_targets(row, training_base: str) -> bool:
    """Whether the plan row provides usable intensity targets for ``training_base``.

    Used to flag ``planned_estimated`` when we had to fall back to a flat
    units-per-hour rate instead of computing from real targets.
    """
    def _pos(v) -> bool:
        try:
            n = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
        except (TypeError, ValueError):
            return False
        return bool(pd.notna(n) and n > 0)

    if training_base == "power":
        return _pos(row.get("target_power_min")) or _pos(row.get("target_power_max"))
    if training_base == "hr":
        return _pos(row.get("target_hr_min")) or _pos(row.get("target_hr_max"))
    if training_base == "pace":
        return (
            _parse_pace_str(row.get("target_pace_min")) is not None
            or _parse_pace_str(row.get("target_pace_max")) is not None
        )
    return False


def _positive_number(value) -> float | None:
    """Return a finite positive numeric value, otherwise ``None``."""
    try:
        number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except (TypeError, ValueError):
        return None
    if pd.isna(number) or number <= 0:
        return None
    return float(number)


def _plan_load_is_estimated(
    row,
    training_base: str,
    thresholds: ThresholdEstimate | None,
) -> bool:
    """Return whether a planned load lacks exact selected-base inputs."""
    if is_rest_workout(row.get("workout_type")):
        return False
    if thresholds is None or _plan_row_duration_sec(row) <= 0:
        return True
    if training_base == "power":
        return not (
            _positive_number(row.get("target_power_min"))
            and _positive_number(row.get("target_power_max"))
            and _positive_number(thresholds.cp_watts)
        )
    if training_base == "hr":
        return not (
            _positive_number(row.get("target_hr_min"))
            and _positive_number(row.get("target_hr_max"))
            and _positive_number(thresholds.rest_hr_bpm)
            and _positive_number(thresholds.max_hr_bpm)
        )
    if training_base == "pace":
        return not (
            _parse_pace_str(row.get("target_pace_min"))
            and _parse_pace_str(row.get("target_pace_max"))
            and _positive_number(thresholds.threshold_pace_sec_km)
        )
    return True


def _activity_load_is_estimated(
    row,
    training_base: str,
    thresholds: ThresholdEstimate | None,
) -> bool:
    """Return whether actual load used fallback or incomplete base inputs."""
    if thresholds is None:
        return True
    if training_base == "power":
        if _positive_number(row.get("rss")):
            return False
        return not (
            _positive_number(row.get("duration_sec"))
            and _positive_number(row.get("avg_power"))
            and _positive_number(thresholds.cp_watts)
        )
    if training_base == "hr":
        return not (
            _positive_number(row.get("duration_sec"))
            and _positive_number(row.get("avg_hr"))
            and _positive_number(thresholds.lthr_bpm)
            and _positive_number(thresholds.rest_hr_bpm)
            and _positive_number(thresholds.max_hr_bpm)
        )
    if training_base == "pace":
        return not (
            _positive_number(row.get("duration_sec"))
            and _positive_number(row.get("distance_km"))
            and _positive_number(thresholds.threshold_pace_sec_km)
        )
    return True


def _estimate_plan_daily_loads(
    plan: pd.DataFrame,
    start_date: date,
    days: int,
    thresholds: ThresholdEstimate,
    training_base: str,
) -> list[float]:
    """Estimate daily load for each of the next *days* days from the plan.

    For days with no planned workout, load is 0. The load unit follows
    ``training_base``: RSS for power, TRIMP for HR, rTSS for pace.
    """
    loads = [0.0] * days
    if plan.empty:
        return loads

    for i in range(days):
        d = start_date + timedelta(days=i + 1)
        day_plan = plan[plan["date"] == d]
        if day_plan.empty:
            continue
        day_load = 0.0
        for _, row in day_plan.iterrows():
            dur_sec = _plan_row_duration_sec(row)
            day_load += _plan_workout_load(row, dur_sec, training_base, thresholds)
        loads[i] = day_load
    return loads


def _get_hrv_trend(readiness: pd.DataFrame, days: int = 3) -> float:
    """Calculate HRV percentage change over the last *days* days."""
    if readiness.empty or "hrv_avg" not in readiness.columns:
        return 0.0
    recent = readiness.sort_values("date").tail(days + 1)
    if len(recent) < 2:
        return 0.0
    hrv_vals = pd.to_numeric(recent["hrv_avg"], errors="coerce").dropna()
    if len(hrv_vals) < 2 or hrv_vals.iloc[0] == 0:
        return 0.0
    return ((hrv_vals.iloc[-1] - hrv_vals.iloc[0]) / hrv_vals.iloc[0]) * 100


def _get_power_pace_pairs(
    merged: pd.DataFrame,
) -> list[tuple[float, float]]:
    """Extract recent (power, pace_sec_per_km) pairs from merged activities."""
    if merged.empty:
        return []
    cols_needed = ["avg_power", "distance_km", "duration_sec"]
    if not all(c in merged.columns for c in cols_needed):
        return []
    recent = merged.dropna(subset=["avg_power", "distance_km", "duration_sec"]).tail(10)
    pairs: list[tuple[float, float]] = []
    for _, row in recent.iterrows():
        power = float(row["avg_power"])
        dist = float(row["distance_km"])
        dur = float(row["duration_sec"])
        if dist > 0 and power > 0:
            pace = dur / dist  # sec per km
            pairs.append((power, pace))
    return pairs


def _build_compliance(
    merged: pd.DataFrame,
    plan: pd.DataFrame,
    training_base: str = "power",
    daily_load: pd.Series | None = None,
    thresholds: ThresholdEstimate | None = None,
    current_date: date | None = None,
) -> dict:
    """Build weekly load comparison with per-week evidence provenance.

    ``actual_load`` / ``planned_load`` carry the load in the unit appropriate
    to the training base (RSS for power, TRIMP for HR, rTSS for pace). Estimated
    flags identify weeks where either side lacks exact selected-base inputs.
    """
    if merged.empty:
        return {
            "weeks": [],
            "planned_load": [],
            "actual_load": [],
            "actual_estimated": False,
            "planned_estimated": False,
            "week_actual_estimated": [],
            "week_planned_estimated": [],
            "week_complete": [],
        }

    weekly_day_count = pd.Series(dtype=int)
    if daily_load is not None and not daily_load.empty:
        load_df = daily_load.reset_index()
        load_df.columns = ["date", "load"]
        load_df["_date"] = pd.to_datetime(load_df["date"])
        load_df["_week"] = load_df["_date"].dt.isocalendar().week
        load_df["_year"] = load_df["_date"].dt.isocalendar().year
        weekly_actual = load_df.groupby(["_year", "_week"])["load"].sum()
        weekly_day_count = load_df.groupby(
            ["_year", "_week"],
        )["_date"].nunique()
    elif "rss" in merged.columns:
        merged_copy = merged.copy()
        merged_copy["_date"] = pd.to_datetime(merged_copy["date"])
        merged_copy["_week"] = merged_copy["_date"].dt.isocalendar().week
        merged_copy["_year"] = merged_copy["_date"].dt.isocalendar().year
        weekly_actual = merged_copy.groupby(["_year", "_week"])["rss"].sum()
    else:
        weekly_actual = pd.Series(dtype=float)

    actual_evidence = merged.copy()
    actual_evidence["_date"] = pd.to_datetime(
        actual_evidence.get("date"), errors="coerce",
    )
    actual_evidence = actual_evidence.dropna(subset=["_date"])
    if not actual_evidence.empty:
        actual_evidence["_week"] = actual_evidence["_date"].dt.isocalendar().week
        actual_evidence["_year"] = actual_evidence["_date"].dt.isocalendar().year
        actual_evidence["_estimated"] = [
            _activity_load_is_estimated(row, training_base, thresholds)
            for _, row in actual_evidence.iterrows()
        ]
        weekly_actual_estimated = actual_evidence.groupby(
            ["_year", "_week"],
        )["_estimated"].any()
    else:
        weekly_actual_estimated = pd.Series(dtype=bool)

    weeks = [f"W{int(w)}" for _, w in weekly_actual.index]
    as_of_date = current_date or date.today()
    week_complete = [
        date.fromisocalendar(int(year), int(week), 7) < as_of_date
        and int(weekly_day_count.get((year, week), 0)) == 7
        for year, week in weekly_actual.index
    ]
    aligned_actual_estimated = [
        bool(weekly_actual_estimated.get(index, False))
        for index in weekly_actual.index
    ]

    plan_copy = pd.DataFrame()
    weekly_planned = pd.Series(dtype=float)
    weekly_planned_estimated = pd.Series(dtype=bool)
    if not plan.empty and "date" in plan.columns:
        plan_copy = plan.copy()
        plan_copy["_date"] = pd.to_datetime(plan_copy["date"], errors="coerce")
        plan_copy = plan_copy.dropna(subset=["_date"])
        if not plan_copy.empty:
            plan_copy["_week"] = plan_copy["_date"].dt.isocalendar().week
            plan_copy["_year"] = plan_copy["_date"].dt.isocalendar().year
            plan_copy["_load"] = [
                _plan_workout_load(
                    row,
                    _plan_row_duration_sec(row),
                    training_base,
                    thresholds,
                )
                for _, row in plan_copy.iterrows()
            ]
            plan_copy["_estimated"] = [
                _plan_load_is_estimated(row, training_base, thresholds)
                for _, row in plan_copy.iterrows()
            ]
            weekly_planned = plan_copy.groupby(
                ["_year", "_week"],
            )["_load"].sum()
            weekly_planned_estimated = plan_copy.groupby(
                ["_year", "_week"],
            )["_estimated"].any()

    aligned_planned = [
        round(float(weekly_planned.get(index, 0.0)), 1)
        for index in weekly_actual.index
    ]
    aligned_planned_estimated = [
        bool(weekly_planned_estimated.get(index, False))
        for index in weekly_actual.index
    ]

    return {
        "weeks": weeks[-8:],
        "actual_load": [round(float(v), 1) for v in weekly_actual.values][-8:],
        "planned_load": aligned_planned[-8:],
        "actual_estimated": any(aligned_actual_estimated[-8:]),
        "planned_estimated": any(aligned_planned_estimated[-8:]),
        "week_actual_estimated": aligned_actual_estimated[-8:],
        "week_planned_estimated": aligned_planned_estimated[-8:],
        "week_complete": week_complete[-8:],
    }


def _compute_load_compliance_summary(weekly_review: dict) -> int | None:
    """Compute compliance from completed weeks with exact evidence on both sides."""
    actual = weekly_review.get("actual_load", [])
    planned = weekly_review.get("planned_load", [])
    complete = weekly_review.get("week_complete", [])
    actual_estimated = weekly_review.get("week_actual_estimated", [])
    planned_estimated = weekly_review.get("week_planned_estimated", [])
    eligible = [
        bool(index < len(complete) and complete[index])
        and not bool(index < len(actual_estimated) and actual_estimated[index])
        and not bool(index < len(planned_estimated) and planned_estimated[index])
        for index in range(min(len(actual), len(planned)))
    ]
    return compute_load_compliance_pct(
        actual,
        planned,
        eligible_weeks=eligible,
    )


def _build_workout_flags(
    merged: pd.DataFrame, readiness: pd.DataFrame, training_base: str = "power"
) -> list:
    """Flag workouts where performance was notably better or worse than expected."""
    # Choose metric column and unit based on training base
    if training_base == "hr":
        metric_col, unit = "avg_hr", "bpm"
    elif training_base == "pace":
        metric_col, unit = "avg_pace_sec_km", "sec/km"
    else:
        metric_col, unit = "avg_power", "W"

    if merged.empty or readiness.empty or metric_col not in merged.columns:
        return []
    flags: list[dict] = []
    merged_copy = merged.copy()
    readiness_copy = readiness.copy()
    merged_copy["_date"] = pd.to_datetime(merged_copy["date"]).dt.date
    readiness_copy["_date"] = pd.to_datetime(readiness_copy["date"]).dt.date
    joined = merged_copy.merge(
        readiness_copy,
        left_on="_date",
        right_on="_date",
        how="inner",
        suffixes=("", "_r"),
    )
    if joined.empty:
        return []
    try:
        joined["_metric"] = pd.to_numeric(joined[metric_col], errors="coerce")
        joined["_readiness"] = pd.to_numeric(joined["readiness_score"], errors="coerce")
    except (KeyError, TypeError):
        return []
    avg_metric = joined["_metric"].mean()
    if avg_metric == 0:
        return []

    # For pace, lower = better (inverted comparison)
    invert = training_base == "pace"

    for _, row in joined.iterrows():
        val = row["_metric"]
        readiness_val = row["_readiness"]
        if pd.isna(val) or pd.isna(readiness_val):
            continue
        pct = (val - avg_metric) / avg_metric * 100
        # For pace, negative pct = faster = better
        is_strong = pct < -5 if invert else pct > 5
        is_excellent = pct < -10 if invert else pct > 10
        is_under = pct > 10 if invert else pct < -10

        if readiness_val < 70 and is_strong:
            flags.append({
                "type": "good",
                "date": str(row["_date"]),
                "description": f"Strong output ({val:.0f}{unit}, {abs(pct):.0f}% {'faster' if invert else 'above avg'}) despite low readiness ({readiness_val:.0f})",
            })
        elif is_excellent:
            flags.append({
                "type": "good",
                "date": str(row["_date"]),
                "description": f"Excellent performance ({val:.0f}{unit}, {abs(pct):.0f}% {'faster' if invert else 'above avg'})",
            })
        elif readiness_val > 80 and is_under:
            flags.append({
                "type": "bad",
                "date": str(row["_date"]),
                "description": f"Underperformed ({val:.0f}{unit}, {abs(pct):.0f}% {'slower' if invert else 'below avg'}) despite good readiness ({readiness_val:.0f})",
            })
    return flags[-10:]


def _build_sleep_perf(
    merged: pd.DataFrame, sleep: pd.DataFrame, training_base: str = "power",
) -> dict:
    """Build sleep score vs performance-metric scatter data.

    The Y-axis metric follows the user's training base:
      - power: ``avg_power`` (W)
      - hr:    ``avg_hr`` (bpm)
      - pace:  ``avg_pace_sec_km`` (lower = better)

    Returns ``{"pairs": [[sleep, metric], ...], "metric_label", "metric_unit"}``.
    An empty ``pairs`` list with the correct metadata is returned when no
    paired rows are available, so the frontend can still label the
    empty-state hint correctly.
    """
    if training_base == "hr":
        metric_col, unit, label = "avg_hr", "bpm", "Avg HR"
    elif training_base == "pace":
        metric_col, unit, label = "avg_pace_sec_km", "sec/km", "Avg Pace"
    else:
        metric_col, unit, label = "avg_power", "W", "Avg Power"

    empty: dict = {"pairs": [], "metric_label": label, "metric_unit": unit}
    if merged.empty or sleep.empty or metric_col not in merged.columns:
        return empty
    merged_copy = merged.copy()
    sleep_copy = sleep.copy()
    merged_copy["_date"] = pd.to_datetime(merged_copy["date"]).dt.date
    sleep_copy["_date"] = pd.to_datetime(sleep_copy["date"]).dt.date
    joined = merged_copy.merge(
        sleep_copy,
        left_on="_date",
        right_on="_date",
        how="inner",
        suffixes=("", "_sleep"),
    )
    if joined.empty or "sleep_score" not in joined.columns:
        return empty
    pairs: list[list] = []
    for _, row in joined.iterrows():
        try:
            score = float(row["sleep_score"])
            value = float(row[metric_col])
            if score > 0 and value > 0:
                pairs.append([score, round(value, 1)])
        except (ValueError, TypeError):
            continue
    return {"pairs": pairs, "metric_label": label, "metric_unit": unit}


def _select_prediction_method(
    training_base: str,
    prediction_theory_id: str | None,
    *,
    has_cp: bool,
    has_pace: bool,
) -> str | None:
    """Pick a race-prediction model for the given training base and data.

    This is a **data-provenance safety gate**, not a physiological claim.
    A CP-model prediction is scientifically fine for an HR-trained athlete
    who has a clean Stryd power meter; the reason we still refuse it is
    that we can't yet distinguish "real Stryd CP" from "Garmin native FTP
    estimate" in ``cp_watts``. Pairing an inflated Garmin FTP with
    Stryd-via-CIQ activity-level power produces wildly-fast bogus
    predictions (the 2:22 marathon bug), so for non-power bases we stay on
    Riegel until a proper ``cp_source`` provenance field exists.

    - **power** users run the CP model when CP watts are available. If they
      have explicitly picked ``riegel`` and have a threshold pace, honor it.
      Otherwise fall back to Riegel, or None.
    - **hr / pace** users only ever use Riegel. ``critical_power`` being
      the global default science theory is not a reliable opt-in signal,
      so we don't honor it here.
    """
    if training_base == "power":
        if prediction_theory_id == "riegel" and has_pace:
            return "riegel"
        if has_cp:
            return "critical_power"
        if has_pace:
            return "riegel"
        return None
    # HR / pace
    if has_pace:
        return "riegel"
    return None


def _build_race_countdown(
    race_date_str: str,
    target_time_sec: int | None,
    latest_threshold: float | None,
    latest_cp_watts: float | None,
    power_pace_pairs: list[tuple[float, float]],
    cp_trend_data: dict,
    today: date,
    distance_km: float = 42.195,
    power_fraction: float = 0.80,
    distance_label: str = "Marathon",
    distance_key: str = "marathon",
    training_base: str = "power",
    threshold_pace: float | None = None,
    riegel_exponent: float | None = None,
    prediction_method: str | None = None,
    prediction_theory_name: str | None = None,
) -> dict:
    """Build race countdown / CP milestone payload depending on config.

    ``training_base`` (power/hr/pace) controls display units and which target
    threshold (if any) is meaningful — LTHR is never a race-pace target, so
    HR-base users get no ``target_cp``. ``prediction_method`` selects the
    prediction MODEL ("critical_power" or "riegel") independently of the
    training base: a power-base user may have picked Riegel, and an HR-base
    user falls back to Riegel because the CP model needs watts.

    ``latest_threshold`` is the display value in base-native units
    (W / bpm / sec·km⁻¹). ``latest_cp_watts`` is CP in watts or ``None`` —
    used for all power-based formulas so LTHR/LT pace are never treated as
    watts.
    """
    is_inverted = training_base == "pace"

    # Predicted time — pick the MODEL requested, regardless of training_base
    predicted_time: float | None = None
    if prediction_method == "critical_power" and latest_cp_watts:
        predicted_time = predict_marathon_time(
            latest_cp_watts, power_pace_pairs, power_fraction, distance_km,
        )
    elif prediction_method == "riegel" and threshold_pace:
        predicted_time = predict_time_from_pace(
            threshold_pace, distance_km, riegel_exponent,
        )
    effective_method = prediction_method if predicted_time is not None else "none"

    common = {
        "distance": distance_key,
        "distance_label": distance_label,
        "prediction_method": effective_method,
        "prediction_theory": prediction_theory_name,
    }

    days_left = None
    if race_date_str:
        try:
            days_left = (date.fromisoformat(race_date_str) - today).days
        except ValueError:
            pass
    if days_left is not None:
        race_status = "unknown"
        if predicted_time and target_time_sec:
            if predicted_time <= target_time_sec:
                race_status = "on_track"
            elif predicted_time <= target_time_sec * 1.03:
                race_status = "close"
            else:
                race_status = "behind"

        # Needed threshold matches training_base display units.
        # Power: watts (needs CP + power-pace pairs). Pace: sec/km (Riegel
        # inversion). HR: no meaningful target — LTHR isn't a trainable
        # race-pace knob.
        needed_threshold: float | None = None
        current_for_check: float | None = None
        if training_base == "power" and latest_cp_watts and power_pace_pairs:
            current_for_check = latest_cp_watts
            if target_time_sec:
                needed_threshold = required_cp_for_time(
                    target_time_sec, power_pace_pairs, power_fraction, distance_km,
                )
        elif training_base == "pace" and threshold_pace:
            current_for_check = threshold_pace
            if target_time_sec:
                needed_threshold = required_pace_for_time(target_time_sec, distance_km)

        race_reality = race_honesty_check(
            current_for_check,
            needed_threshold,
            days_left,
            cp_trend_data,
            predicted_time,
            target_time_sec,
            threshold_inverted=is_inverted,
        )
        return {
            **common,
            "mode": "race_date",
            "race_date": race_date_str,
            "days_left": days_left,
            "predicted_time_sec": predicted_time,
            "target_time_sec": target_time_sec,
            "status": race_status,
            "reality_check": race_reality,
        }

    if target_time_sec:
        # Continuous improvement with a time target.
        # HR base: LTHR is not a trainable race-pace target — surface the
        # predicted time only and let the trend do the talking.
        if training_base == "hr":
            direction = cp_trend_data.get("direction", "unknown")
            severity = "on_track" if direction == "rising" else ("behind" if direction == "falling" else "close")
            return {
                **common,
                "mode": "cp_milestone",
                "current_cp": None,
                "target_cp": None,
                "target_time_sec": target_time_sec,
                "predicted_time_sec": predicted_time,
                "status": severity,
                "milestones": [],
                "reality_check": {
                    "assessment": "Tracking via time predictions. LTHR trend shown for training context.",
                    "severity": severity,
                    "trend_note": f"LTHR trending {direction} ({cp_trend_data.get('slope_per_month', 0):+.1f}bpm/month).",
                },
            }

        # Power / pace: derive the target threshold in base-native units.
        target_threshold: float | None = None
        current_for_milestone: float | None = None
        if training_base == "power" and latest_cp_watts and power_pace_pairs:
            target_threshold = required_cp_for_time(
                target_time_sec, power_pace_pairs, power_fraction, distance_km,
            )
            current_for_milestone = latest_cp_watts
        elif training_base == "pace" and threshold_pace:
            target_threshold = required_pace_for_time(target_time_sec, distance_km)
            current_for_milestone = threshold_pace

        if target_threshold and current_for_milestone:
            milestone_result = cp_milestone_check(
                current_for_milestone, target_threshold, cp_trend_data,
                threshold_inverted=is_inverted,
            )
        else:
            milestone_result = {
                "severity": "unknown",
                "assessment": "Insufficient threshold data.",
                "milestones": [],
            }
        return {
            **common,
            "mode": "cp_milestone",
            "current_cp": current_for_milestone,
            "target_cp": target_threshold,
            "target_time_sec": target_time_sec,
            "predicted_time_sec": predicted_time,
            "cp_gap_watts": milestone_result.get("cp_gap_watts"),
            "status": milestone_result.get("severity", "unknown"),
            "milestones": milestone_result.get("milestones", []),
            "estimated_months": milestone_result.get("estimated_months"),
            "reality_check": milestone_result,
        }

    # Continuous improvement, no target — show current threshold in base units.
    direction = cp_trend_data.get("direction", "unknown")
    slope = cp_trend_data.get("slope_per_month", 0)
    severity = "on_track" if direction == "rising" else ("behind" if direction == "falling" else "close")
    return {
        **common,
        "mode": "continuous",
        "status": severity,
        "current_cp": latest_threshold,
        "predicted_time_sec": predicted_time,
        "cp_trend_summary": {
            "direction": direction,
            "slope_per_month": slope,
        },
        "reality_check": {
            "assessment": "Tracking continuous improvement.",
            "severity": severity,
            "trend_note": f"Threshold trending {direction} ({slope:+.1f}/month).",
        },
    }


def _get_latest_readiness(
    readiness: pd.DataFrame,
) -> tuple[float | None, float | None]:
    """Return (latest_readiness_score, latest_hrv) from readiness data."""
    if readiness.empty or "readiness_score" not in readiness.columns:
        return None, None
    latest_row = readiness.sort_values("date").iloc[-1]
    readiness_val = pd.to_numeric(
        pd.Series([latest_row["readiness_score"]]), errors="coerce"
    ).iloc[0]
    latest_readiness = float(readiness_val) if pd.notna(readiness_val) else None
    latest_hrv = None
    if "hrv_avg" in readiness.columns:
        hrv_val = pd.to_numeric(
            pd.Series([latest_row.get("hrv_avg")]), errors="coerce"
        ).iloc[0]
        latest_hrv = float(hrv_val) if pd.notna(hrv_val) else None
    return latest_readiness, latest_hrv


def _get_todays_plan(
    plan: pd.DataFrame,
    today: date,
    *,
    fallback_plan: pd.DataFrame | None = None,
) -> tuple[str, dict | None]:
    """Return today's most consequential planned workout deterministically."""
    if plan.empty and (fallback_plan is None or fallback_plan.empty):
        return "", None

    def rows_for_today(frame: pd.DataFrame | None) -> pd.DataFrame:
        """Return rows whose ``date`` resolves to the requested calendar day.

        The plan frame may hold Python ``date`` objects, pandas timestamps,
        or ISO-ish strings depending on load path. ``to_datetime`` normalizes
        the usual cases, including mixed valid representations in the same
        frame. Unparseable rows become ``NaT`` and simply do not match today;
        only when every row is unparseable do we treat the frame as unusable
        for same-day guidance rather than guessing from opaque values.
        """
        if frame is None or frame.empty or "date" not in frame.columns:
            return pd.DataFrame()
        parsed_dates = pd.to_datetime(frame["date"], errors="coerce")
        if parsed_dates.isna().all():
            return pd.DataFrame()
        return frame.loc[parsed_dates.dt.date == today]

    today_plan = rows_for_today(plan)
    if today_plan.empty and fallback_plan is not None:
        today_plan = rows_for_today(fallback_plan)
    if today_plan.empty:
        return "", None

    def numeric(row: pd.Series, field: str) -> float:
        value = pd.to_numeric(row.get(field), errors="coerce")
        return float(value) if pd.notna(value) else 0.0

    def text_value(row: pd.Series, field: str) -> str:
        value = row.get(field)
        return "" if value is None or pd.isna(value) else str(value)

    def consequence(row: pd.Series) -> tuple:
        workout_type = text_value(row, "workout_type")
        normalized = "_".join(
            workout_type.strip().lower().replace("-", " ").split()
        )
        if is_hard_workout(workout_type):
            category = 3
        elif is_rest_workout(workout_type):
            category = 0
        elif normalized in {"recovery", "recovery_run"}:
            category = 1
        else:
            category = 2
        return (
            category,
            numeric(row, "planned_duration_min"),
            numeric(row, "planned_distance_km"),
            numeric(row, "target_power_max"),
            normalized,
            text_value(row, "source"),
            text_value(row, "external_id"),
            text_value(row, "workout_description"),
        )

    plan_row = max(
        (row for _, row in today_plan.iterrows()),
        key=consequence,
    )
    planned_today = text_value(plan_row, "workout_type")
    raw_dict = plan_row.to_dict()
    planned_detail = {k: (v if pd.notna(v) else None) for k, v in raw_dict.items()}
    return planned_today, planned_detail


def _build_activities_list(
    merged: pd.DataFrame, splits: pd.DataFrame,
) -> list[dict]:
    """Build a list of activity dicts from merged activities + their splits.

    Splits get bucketed by activity_id once via ``groupby`` instead of
    per-activity ``splits[splits["activity_id"].astype(str) == aid]``.
    The original shape paid an O(N_splits) scan and a full ``astype``
    cast for every activity returned, so a 130-activity / 600-split
    user spent ~80 ms here even when the route only kept the first 20.
    """
    if merged.empty:
        return []

    splits_by_aid: dict[str, list[dict]] = {}
    if not splits.empty and "activity_id" in splits.columns:
        for aid_str, group in splits.groupby(
            splits["activity_id"].astype(str), sort=False,
        ):
            splits_by_aid[aid_str] = [
                {
                    "split_num": int(s.get("split_num", 0)),
                    "distance_km": (
                        round(float(s.get("distance_km", 0)), 2)
                        if pd.notna(s.get("distance_km")) else None
                    ),
                    "duration_sec": (
                        int(s.get("duration_sec", 0))
                        if pd.notna(s.get("duration_sec")) else None
                    ),
                    "avg_power": (
                        round(float(s.get("avg_power", 0)), 1)
                        if pd.notna(s.get("avg_power")) else None
                    ),
                    "avg_hr": (
                        int(s.get("avg_hr", 0))
                        if pd.notna(s.get("avg_hr")) else None
                    ),
                    "avg_pace_min_km": (
                        str(s.get("avg_pace_min_km", ""))
                        if pd.notna(s.get("avg_pace_min_km")) else None
                    ),
                }
                for _, s in group.iterrows()
            ]

    activities: list[dict] = []
    merged_sorted = merged.sort_values("date", ascending=False)
    for _, row in merged_sorted.iterrows():
        aid = str(row.get("activity_id", ""))
        act: dict = {
            "activity_id": aid,
            "date": str(row["date"]),
            "source": str(row.get("source", "")),
            "activity_type": row.get("activity_type", "running"),
            "distance_km": (
                round(float(row.get("distance_km", 0)), 2)
                if pd.notna(row.get("distance_km")) else None
            ),
            "duration_sec": (
                int(row.get("duration_sec", 0))
                if pd.notna(row.get("duration_sec")) else None
            ),
            "avg_power": (
                round(float(row.get("avg_power", 0)), 1)
                if pd.notna(row.get("avg_power")) else None
            ),
            "avg_hr": (
                int(row.get("avg_hr", 0))
                if pd.notna(row.get("avg_hr")) else None
            ),
            "avg_pace_min_km": (
                str(row.get("avg_pace_min_km", ""))
                if pd.notna(row.get("avg_pace_min_km")) else None
            ),
            "elevation_gain_m": (
                round(float(row.get("elevation_gain_m", 0)), 1)
                if pd.notna(row.get("elevation_gain_m")) else None
            ),
            "rss": (
                round(float(row.get("rss", 0)), 1)
                if pd.notna(row.get("rss")) else None
            ),
            "cp_estimate": (
                round(float(row.get("cp_estimate", 0)), 1)
                if pd.notna(row.get("cp_estimate")) else None
            ),
            "splits": splits_by_aid.get(aid, []),
        }
        activities.append(act)
    return activities


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _compute_threshold_data(
    merged: pd.DataFrame, config, data_dir: str = None,
    user_id: str = None, db=None,
    fitness_data: pd.DataFrame | None = None,
) -> tuple[float | None, dict, pd.Series, list[tuple[float, float]]]:
    """Compute active threshold value, trend data, CP values, and power-pace pairs.

    Returns (latest_threshold, trend_data, cp_values, power_pace_pairs).
    When user_id and db are provided, queries fitness_data for CP estimates.
    When ``fitness_data`` is also provided (the wide-pivoted DataFrame from
    :func:`load_data_from_db`'s ``"fitness"`` key), it's used for the HR/pace
    threshold trend; otherwise the helper re-runs ``load_data_from_db`` as a
    fallback for callers that don't already hold the frame.
    """
    cp_values = (
        pd.to_numeric(merged["cp_estimate"], errors="coerce")
        if "cp_estimate" in merged.columns
        else pd.Series(dtype=float)
    )
    cp_values = cp_values[cp_values > 0].dropna()

    # Supplement with fitness_data CP estimates (includes profile CP from Stryd sync).
    # Honor the user's source preference (Settings → threshold sources). Without
    # this filter, a FitnessData row with source='activities' (our own
    # rolling-window write-back from sync_writer.py) routinely outdates and
    # overrides Stryd's profile CP, since the user-facing "latest_cp" then picks
    # the more recent date regardless of source.
    if user_id and db:
        from db.models import FitnessData as FDModel
        threshold_sources = config.preferences.get("threshold_sources") or {}
        activity_source = config.preferences.get("activities") or None
        preferred_source = threshold_sources.get("cp_estimate") or activity_source
        fd_q = db.query(FDModel.date, FDModel.value, FDModel.source).filter(
            FDModel.user_id == user_id,
            FDModel.metric_type == "cp_estimate",
            FDModel.value.isnot(None),
        )
        fd_rows = fd_q.all()
        # Prefer rows matching the user's source choice; fall back to all rows
        # only when the preferred source has nothing to say.
        if preferred_source:
            preferred_rows = [r for r in fd_rows if r.source == preferred_source]
            if preferred_rows:
                fd_rows = preferred_rows
        if fd_rows:
            fd_series = pd.Series(
                {r.date: r.value for r in fd_rows if r.value and r.value > 0}
            )
            # Merge: fitness_data values fill gaps and override activity-based CP
            if not fd_series.empty:
                act_cp = pd.Series(
                    dict(zip(
                        merged["date"].iloc[cp_values.index] if not cp_values.empty else [],
                        cp_values.values if not cp_values.empty else [],
                    ))
                )
                combined = pd.concat([act_cp, fd_series])
                combined = combined[~combined.index.duplicated(keep="last")]
                combined = combined.sort_index()
                cp_values = combined[combined > 0].dropna()

    power_pace_pairs = _get_power_pace_pairs(merged)

    if config.training_base == "power":
        # Latest CP shown to the user must match what the chart displays
        # (most recent per-activity cp_estimate). Pulling the latest from the
        # combined series can pick a stale FitnessData write-back from a
        # different source than the user's preference, so take it directly
        # from per-activity data when present and only fall back to combined
        # when activities have nothing to offer (e.g. brand-new user whose
        # only CP value is a synced Stryd profile row).
        activity_cp_values = (
            pd.to_numeric(merged["cp_estimate"], errors="coerce")
            if "cp_estimate" in merged.columns
            else pd.Series(dtype=float)
        )
        activity_cp_values = activity_cp_values[activity_cp_values > 0].dropna()
        if not activity_cp_values.empty:
            latest = float(activity_cp_values.iloc[-1])
        elif not cp_values.empty:
            latest = float(cp_values.iloc[-1])
        else:
            latest = None
        trend = (
            compute_cp_trend(
                [float(v) for v in cp_values.values],
                list(cp_values.index),
            )
            if not cp_values.empty
            else {"direction": "unknown"}
        )
    elif config.training_base in ("hr", "pace"):
        from analysis.metrics import compute_threshold_trend
        col = "lthr_bpm" if config.training_base == "hr" else "lt_pace_sec_km"

        if fitness_data is not None:
            lt_df = fitness_data
        elif user_id and db:
            from analysis.data_loader import load_data_from_db
            db_data = load_data_from_db(user_id, db)
            lt_df = db_data.get("fitness", pd.DataFrame())
        else:
            lt_df = pd.DataFrame()

        if not lt_df.empty and col in lt_df.columns:
            lt_df = lt_df.sort_values("date")
            vals = pd.to_numeric(lt_df[col], errors="coerce").dropna()
            latest = float(vals.iloc[-1]) if not vals.empty else None
            trend = (
                compute_threshold_trend(
                    [float(v) for v in vals.values],
                    list(vals.index),
                    invert_direction=(config.training_base == "pace"),
                )
                if not vals.empty
                else {"direction": "unknown"}
            )
        else:
            latest = None
            trend = {"direction": "unknown"}
    else:
        latest = None
        trend = {"direction": "unknown"}

    return latest, trend, cp_values, power_pace_pairs


def _compute_recovery_analysis(
    recovery: pd.DataFrame,
    recovery_params: dict | None = None,
    current_date: date | None = None,
) -> tuple[dict, float | None, float | None, float | None]:
    """Analyze the latest current HRV reading against prior observations.

    The current HRV and RHR observations are excluded from their historical
    baseline pools, which are limited to the configured prior calendar window.
    Recovery classification also requires HRV recorded today
    or yesterday; older HRV remains displayable context but cannot drive a
    same-day recommendation.

    Returns `(analysis, latest_hrv, latest_sleep, latest_rhr)`. `latest_date`
    is the newest valid recovery metric date, while `hrv_latest_date` and
    `hrv_is_stale` expose HRV-specific provenance explicitly. `current_date`
    anchors all staleness decisions to the request date.
    """
    recovery_sorted = recovery.sort_values("date") if not recovery.empty else recovery
    params = recovery_params or {}
    rolling_days = int(params.get("rolling_days", 7))
    baseline_days = int(params.get("baseline_days", 30))
    cv_threshold = float(params.get("cv_threshold", 10))
    as_of_date = current_date or date.today()
    hrv_history: list[float] = []
    rhr_history: list[float] = []
    latest_hrv = None
    latest_sleep = None
    latest_readiness = None
    latest_rhr = None
    hrv_latest_date: date | None = None
    rhr_latest_date: date | None = None
    sleep_latest_date: date | None = None
    readiness_latest_date: date | None = None

    def _coerce_date(value: object) -> date | None:
        if pd.isna(value):
            return None
        if hasattr(value, "date") and callable(getattr(value, "date", None)):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return pd.to_datetime(value).date()
        except (TypeError, ValueError):
            return None

    def _metric_values(
        column: str,
        *,
        positive_only: bool = True,
        history_days: int | None = None,
    ) -> tuple[list[float], float | None, date | None]:
        if column not in recovery_sorted.columns:
            return [], None, None
        numeric = pd.to_numeric(recovery_sorted[column], errors="coerce")
        positions = [
            position
            for position, value in enumerate(numeric.tolist())
            if pd.notna(value) and (not positive_only or float(value) > 0)
        ]
        if not positions:
            return [], None, None
        current_position = positions[-1]
        current = float(numeric.iloc[current_position])
        metric_date = _coerce_date(recovery_sorted.iloc[current_position].get("date"))
        history: list[float] = []
        for position in positions[:-1]:
            history_date = _coerce_date(recovery_sorted.iloc[position].get("date"))
            if history_days is not None:
                if metric_date is None or history_date is None:
                    continue
                cutoff = metric_date - timedelta(days=history_days)
                if history_date < cutoff or history_date >= metric_date:
                    continue
            history.append(float(numeric.iloc[position]))
        return history, current, metric_date

    recovery_metric_dates: list[date] = []
    if not recovery_sorted.empty:
        hrv_history, latest_hrv, hrv_latest_date = _metric_values(
            "hrv_avg", history_days=baseline_days,
        )
        rhr_history, latest_rhr, rhr_latest_date = _metric_values(
            "resting_hr", history_days=baseline_days,
        )
        _, latest_sleep, sleep_latest_date = _metric_values(
            "sleep_score", positive_only=False,
        )
        _, latest_readiness, readiness_latest_date = _metric_values(
            "readiness_score", positive_only=False,
        )
        recovery_metric_dates = [
            metric_date
            for metric_date in (
                hrv_latest_date,
                rhr_latest_date,
                sleep_latest_date,
                readiness_latest_date,
            )
            if metric_date is not None
        ]

    grace_date = as_of_date - timedelta(days=1)

    def _is_stale(value: float | None, metric_date: date | None) -> bool:
        return value is not None and (
            metric_date is None
            or metric_date < grace_date
            or metric_date > as_of_date
        )

    hrv_is_stale = _is_stale(latest_hrv, hrv_latest_date)
    sleep_is_stale = _is_stale(latest_sleep, sleep_latest_date)
    readiness_is_stale = _is_stale(latest_readiness, readiness_latest_date)
    rhr_is_stale = _is_stale(latest_rhr, rhr_latest_date)

    display_analysis = analyze_recovery(
        hrv_history,
        today_hrv_ms=latest_hrv,
        today_sleep=latest_sleep,
        today_rhr=latest_rhr,
        today_readiness=latest_readiness,
        rhr_series=rhr_history if rhr_history else None,
        rolling_days=rolling_days,
        baseline_days=baseline_days,
        cv_threshold=cv_threshold,
    )
    if hrv_is_stale:
        current_analysis = analyze_recovery(
            hrv_history,
            today_hrv_ms=None,
            today_sleep=None if sleep_is_stale else latest_sleep,
            today_rhr=None if rhr_is_stale else latest_rhr,
            today_readiness=None if readiness_is_stale else latest_readiness,
            rhr_series=rhr_history if rhr_history else None,
            rolling_days=rolling_days,
            baseline_days=baseline_days,
            cv_threshold=cv_threshold,
        )
        display_analysis["status"] = current_analysis["status"]
        display_analysis["classification_reason"] = "stale_hrv"

    latest_date = max(recovery_metric_dates) if recovery_metric_dates else None
    is_stale = latest_date is not None and latest_date < grace_date
    augmented = {
        **display_analysis,
        "latest_date": latest_date.isoformat() if latest_date else None,
        "is_stale": is_stale,
        "hrv_latest_date": hrv_latest_date.isoformat() if hrv_latest_date else None,
        "hrv_is_stale": hrv_is_stale,
        "sleep_latest_date": sleep_latest_date.isoformat() if sleep_latest_date else None,
        "sleep_is_stale": sleep_is_stale,
        "readiness_latest_date": (
            readiness_latest_date.isoformat() if readiness_latest_date else None
        ),
        "readiness_is_stale": readiness_is_stale,
        "rhr_latest_date": rhr_latest_date.isoformat() if rhr_latest_date else None,
        "rhr_is_stale": rhr_is_stale,
    }
    return augmented, latest_hrv, latest_sleep, latest_rhr


def _recovery_for_guidance(recovery_analysis: dict) -> dict:
    """Remove stale observations from same-day recommendation inputs."""
    current = dict(recovery_analysis)
    if current.get("hrv_is_stale"):
        current["hrv"] = None
    if current.get("sleep_is_stale"):
        current["sleep_score"] = None
    if current.get("readiness_is_stale"):
        current["readiness_score"] = None
    if current.get("rhr_is_stale"):
        current["resting_hr"] = None
        current["rhr_trend"] = None
    return current

def _build_threshold_trend_chart(
    merged: pd.DataFrame, config, data_dir: str = None,
    user_id: str = None, db=None,
    fitness_data: pd.DataFrame | None = None,
) -> dict:
    """Build threshold trend chart data based on training base.

    For HR/pace base, ``fitness_data`` (the wide-pivoted DataFrame from
    :func:`load_data_from_db`'s ``"fitness"`` key) is used when supplied;
    otherwise the helper re-runs ``load_data_from_db`` as a fallback.
    """
    chart: dict = {"dates": [], "values": []}
    if config.training_base == "power":
        if not merged.empty and "cp_estimate" in merged.columns:
            cp_data = merged.dropna(subset=["cp_estimate"]).sort_values("date")
            chart = {
                "dates": [str(d) for d in cp_data["date"].values],
                "values": [round(float(v), 1) for v in cp_data["cp_estimate"].values],
            }
    elif config.training_base in ("hr", "pace"):
        if fitness_data is not None:
            lt_df = fitness_data
        elif user_id and db:
            from analysis.data_loader import load_data_from_db
            db_data = load_data_from_db(user_id, db)
            lt_df = db_data.get("fitness", pd.DataFrame())
        else:
            lt_df = pd.DataFrame()

        if not lt_df.empty:
            lt_df = lt_df.sort_values("date")
            col = "lthr_bpm" if config.training_base == "hr" else "lt_pace_sec_km"
            if col in lt_df.columns:
                lt_vals = pd.to_numeric(lt_df[col], errors="coerce")
                valid = lt_vals.dropna()
                if not valid.empty:
                    chart = {
                        "dates": [str(lt_df.loc[i, "date"]) for i in valid.index],
                        "values": [round(float(v), 1) for v in valid.values],
                    }
    return chart


def _build_warnings(
    recovery_analysis: dict, current_tsb: float | None,
    config, data_dir: str = None, latest_cp_watts: float | None = None,
    cv_threshold: float = 10.0,
    tsb_caution_threshold: float = -20.0,
) -> list[str]:
    """Collect health/training warnings.

    ``latest_cp_watts`` must be CP in watts (not a base-native threshold):
    ``check_plan_staleness`` compares it against ``cp_at_generation`` which
    is stored in watts at plan-generation time. Passing an LTHR in bpm here
    produces a nonsense drift percentage and a "power targets may be
    inaccurate" warning on HR-base users who have no power targets at all.
    """
    warnings: list[str] = []
    hrv_info = recovery_analysis.get("hrv") or {}
    if hrv_info.get("trend") == "declining":
        warnings.append("HRV rolling mean declining: monitor recovery")
    if hrv_info.get("rolling_cv", 0) > cv_threshold:
        warnings.append(
            f"HRV variability high (CV {hrv_info['rolling_cv']:.0f}%): "
            "above the coaching caution threshold"
        )
    if current_tsb is not None and current_tsb < tsb_caution_threshold:
        warnings.append(
            f"Modeled load balance below the coaching caution band (TSB = {current_tsb:.0f})"
        )
    if config.preferences.get("plan") == "ai" and data_dir:
        from api.ai import check_plan_staleness
        warnings.extend(check_plan_staleness(data_dir, latest_cp_watts))
    return warnings


def _compute_diagnosis(
    merged: pd.DataFrame, splits: pd.DataFrame,
    cp_trend_data: dict, config, thresholds, science: dict,
    samples: pd.DataFrame | None = None,
    current_date: date | None = None,
) -> dict:
    """Run zone-aware training diagnosis."""
    if config.training_base == "power":
        active_threshold = thresholds.cp_watts
    elif config.training_base == "hr":
        active_threshold = thresholds.lthr_bpm
    else:
        active_threshold = thresholds.threshold_pace_sec_km

    zones_theory = science.get("zones")
    load_theory = science.get("load")
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

    return diagnose_training(
        merged, splits, cp_trend_data,
        base=config.training_base,
        threshold_value=active_threshold,
        zone_boundaries=zone_boundaries,
        zone_names=zone_names_list,
        target_distribution=target_dist,
        theory_name=zone_theory_name,
        samples=samples,
        current_date=current_date,
        diagnosis_params=load_theory.diagnosis if load_theory else None,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def get_dashboard_data(user_id: str = None, db=None) -> dict:
    """Load all data and compute all metrics.

    If user_id and db are provided, loads from database.
    Otherwise falls back to file-based loading (backward compatibility).
    """
    _ensure_env()

    if user_id and db:
        from analysis.data_loader import load_data_from_db
        from analysis.config import load_config_from_db
        config = load_config_from_db(user_id, db)
        data = load_data_from_db(user_id, db)
        data_dir = None  # Signal to helpers that we're in DB mode
    else:
        config = load_config()
        base_dir = os.path.join(os.path.dirname(__file__), "..")
        data_dir = os.path.join(base_dir, "data")
        data = load_data(config, data_dir)

    data["recovery"] = select_preferred_source(
        data["recovery"], config.preferences.get("recovery"),
    )
    all_plans = data["plan"].copy()
    data["plan"] = select_preferred_source(
        data["plan"], config.preferences.get("plan"),
    )
    merged = data["activities"]

    # Deduplicate activities by primary source preference.
    # When multiple sources (e.g., Garmin + Stryd) sync the same run,
    # keep the primary source version to avoid double-counting in metrics.
    primary_source = config.preferences.get("activities")
    if primary_source and not merged.empty and "source" in merged.columns:
        merged = merged.copy()
        merged["_date"] = pd.to_datetime(merged["date"]).dt.date
        merged["_dur"] = pd.to_numeric(merged.get("duration_sec", 0), errors="coerce").fillna(0)
        merged["_is_primary"] = merged["source"] == primary_source

        keep_mask = pd.Series(True, index=merged.index)
        for dt, group in merged.groupby("_date"):
            if len(group) <= 1:
                continue
            primary = group[group["_is_primary"]]
            others = group[~group["_is_primary"]]
            for oidx, orow in others.iterrows():
                for _, prow in primary.iterrows():
                    if prow["_dur"] > 0 and orow["_dur"] > 0:
                        ratio = abs(prow["_dur"] - orow["_dur"]) / max(prow["_dur"], orow["_dur"])
                        if ratio < 0.10:  # Same activity (duration within 10%)
                            keep_mask[oidx] = False
                            break
        merged = merged[keep_mask].drop(columns=["_date", "_dur", "_is_primary"], errors="ignore").reset_index(drop=True)

    thresholds = _resolve_thresholds(config, data_dir=data_dir, user_id=user_id, db=db)

    # Science framework
    # Load theory text in the user's configured language so zone names,
    # diagnosis thresholds, and recovery theory prose render in zh when the
    # user has set Chinese in Settings. Silently falls back to English when a
    # translated YAML is missing (see analysis/science.py:load_theory).
    science_locale = config.language if config.language in {"en", "zh"} else None
    science = load_active_science(
        config.science, config.zone_labels, locale=science_locale
    )
    load_theory = science.get("load")
    load_params = load_theory.params if load_theory else {}
    ctl_tc = int(load_params.get("ctl_time_constant", 42))
    atl_tc = int(load_params.get("atl_time_constant", 7))

    today = date.today()

    # EWMA load (full history for stable CTL/ATL)
    earliest = today - timedelta(days=365)
    if not merged.empty and "date" in merged.columns:
        first_date = pd.to_datetime(merged["date"]).min()
        if pd.notna(first_date):
            earliest = first_date.date()
    full_range = pd.date_range(earliest, today)
    daily_load = _compute_daily_load(merged, full_range, config, thresholds)
    ctl = compute_ewma_load(daily_load, time_constant=ctl_tc)
    atl = compute_ewma_load(daily_load, time_constant=atl_tc)
    tsb = compute_tsb(ctl, atl)

    # TSB projection (14 days forward from plan)
    plan = data["plan"]
    projection_days = 14
    future_loads = _estimate_plan_daily_loads(
        plan, today, projection_days, thresholds, config.training_base,
    )
    current_ctl = float(ctl.iloc[-1]) if not ctl.empty else 0.0
    current_atl = float(atl.iloc[-1]) if not atl.empty else 0.0
    proj_ctl, proj_atl, proj_tsb = project_tsb(
        current_ctl, current_atl, future_loads,
        ctl_tc=ctl_tc, atl_tc=atl_tc,
    )
    proj_dates = [
        (today + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        for i in range(projection_days)
    ]

    # Threshold data (CP / LTHR / pace trend). ``latest_cp`` here is the
    # base-native threshold: watts for power, bpm for HR, sec/km for pace.
    latest_cp, cp_trend_data, cp_values, power_pace_pairs = _compute_threshold_data(
        merged, config, data_dir=data_dir, user_id=user_id, db=db,
        fitness_data=data.get("fitness"),
    )

    # CP-in-watts for power-based formulas. HR/pace users' ``latest_cp`` is
    # NOT watts (it's LTHR or LT pace), so we must never feed it into
    # predict_marathon_time / required_cp_for_time. The source of truth for
    # actual CP watts is the resolved threshold from sensor data.
    latest_cp_watts = (
        thresholds.cp_watts if thresholds.cp_watts and thresholds.cp_watts > 0 else None
    )

    # Goal + race prediction
    race_date_str = str(config.goal.get("race_date", "")).strip()
    raw_target = config.goal.get("target_time_sec") or config.goal.get("race_target_time_sec")
    target_time_sec = int(raw_target) if raw_target else None
    distance_key = str(config.goal.get("distance", "marathon")).strip() or "marathon"
    dist_config = get_distance_config(distance_key)
    # Threshold pace — always resolve if available (needed for Riegel prediction)
    threshold_pace = thresholds.threshold_pace_sec_km

    # Use prediction theory params if available (from science framework)
    prediction_theory = science.get("prediction")
    prediction_theory_id = config.science.get("prediction", "critical_power")
    theory_exponent = None
    if prediction_theory and prediction_theory.params:
        theory_fractions = prediction_theory.params.get("distance_power_fractions", {})
        theory_fraction = theory_fractions.get(distance_key)
        if theory_fraction:
            dist_config = {**dist_config, "power_fraction": theory_fraction}
        theory_exponent = prediction_theory.params.get("riegel_exponent")

    prediction_method = _select_prediction_method(
        config.training_base,
        prediction_theory_id,
        has_cp=bool(latest_cp_watts),
        has_pace=bool(threshold_pace),
    )

    race_countdown = _build_race_countdown(
        race_date_str, target_time_sec,
        latest_threshold=latest_cp,
        latest_cp_watts=latest_cp_watts,
        power_pace_pairs=power_pace_pairs,
        cp_trend_data=cp_trend_data,
        today=today,
        distance_km=dist_config["km"],
        power_fraction=dist_config["power_fraction"],
        distance_label=dist_config["label"],
        distance_key=distance_key,
        training_base=config.training_base,
        threshold_pace=threshold_pace,
        riegel_exponent=theory_exponent,
        prediction_method=prediction_method,
        prediction_theory_name=prediction_theory.name if prediction_theory else None,
    )

    # Recovery
    recovery = data["recovery"]
    recovery_theory = science.get("recovery")
    recovery_params = recovery_theory.params if recovery_theory else {}
    recovery_analysis, _, _, _ = _compute_recovery_analysis(
        recovery,
        recovery_params=recovery_params,
        current_date=today,
    )
    current_tsb = float(tsb.iloc[-1]) if not tsb.empty else 0.0
    data_days = (today - earliest).days if not merged.empty else 0
    pmc_sufficient = has_sufficient_load_history(data_days, ctl_tc)
    guidance_tsb = current_tsb if pmc_sufficient else None

    # Daily training signal
    planned_today, planned_detail = _get_todays_plan(
        plan, today, fallback_plan=all_plans,
    )
    # Recovery is standardized to a single HRV-based theory.
    hrv_only_mode = True
    guidance_recovery = _recovery_for_guidance(recovery_analysis)
    signal = daily_training_signal(
        guidance_recovery, guidance_tsb, planned_today,
        planned_detail=planned_detail,
        signal_thresholds=load_theory.signal if load_theory else None,
        recovery_thresholds=recovery_params,
        hrv_only=hrv_only_mode,
    )

    # Chart data
    display_days = 60
    date_range = pd.date_range(today - timedelta(days=display_days), today)
    display_ctl = ctl.iloc[-len(date_range):]
    display_atl = atl.iloc[-len(date_range):]
    display_tsb = tsb.iloc[-len(date_range):]
    ff_dates = [d.strftime("%Y-%m-%d") for d in date_range]

    fitness_fatigue = {
        "dates": ff_dates,
        "ctl": [round(float(v), 1) for v in display_ctl.values],
        "atl": [round(float(v), 1) for v in display_atl.values],
        "tsb": [round(float(v), 1) for v in display_tsb.values],
        "projected_dates": proj_dates,
        "projected_ctl": proj_ctl,
        "projected_atl": proj_atl,
        "projected_tsb": proj_tsb,
    }
    tsb_sparkline = {
        "dates": ff_dates[-14:],
        "values": [round(float(v), 1) for v in display_tsb.values][-14:],
        "projected_dates": proj_dates[:7],
        "projected_values": proj_tsb[:7],
    }
    cp_trend_chart = _build_threshold_trend_chart(
        merged, config, data_dir=data_dir, user_id=user_id, db=db,
        fitness_data=data.get("fitness"),
    )

    # Supplementary data
    weekly_review = _build_compliance(
        merged,
        plan,
        config.training_base,
        daily_load,
        thresholds,
        current_date=today,
    )
    workout_flags = _build_workout_flags(merged, recovery, config.training_base)
    sleep_perf = _build_sleep_perf(merged, recovery, config.training_base)
    warnings = _build_warnings(
        guidance_recovery,
        guidance_tsb,
        config,
        data_dir=data_dir,
        latest_cp_watts=latest_cp_watts,
        cv_threshold=float(recovery_params.get("cv_threshold", 10)),
        tsb_caution_threshold=float(
            (load_theory.signal if load_theory else {}).get("tsb_high_fatigue", -20)
        ),
    )

    # Diagnosis — use per-second samples when available for 1s zone resolution
    splits = data["splits"]
    samples = pd.DataFrame()
    if user_id and db:
        from analysis.data_loader import load_activity_samples
        # Load samples only for recent activities to avoid reading all history
        _lookback_cutoff = today - timedelta(weeks=8)
        if not merged.empty and "activity_id" in merged.columns and "date" in merged.columns:
            _recent_aids = list(
                merged[pd.to_datetime(merged["date"]).dt.date >= _lookback_cutoff]["activity_id"]
                .astype(str).unique()
            )
            if _recent_aids:
                samples = load_activity_samples(user_id, db, _recent_aids)
    diagnosis = _compute_diagnosis(
        merged, splits, cp_trend_data, config, thresholds, science,
        samples=samples, current_date=today,
    )
    training_summary = {
        "current_tsb": round(current_tsb, 1) if pmc_sufficient else None,
        "distribution_match_pct": compute_distribution_match_pct(
            diagnosis.get("distribution", []),
            evidence_complete=diagnosis.get("data_meta", {}).get(
                "distribution_complete", False,
            ),
        ),
        "load_compliance_pct": _compute_load_compliance_summary(weekly_review),
    }

    # Activities for history
    activities_list = _build_activities_list(merged, splits)

    # Data sufficiency metadata — helps frontend decide what to show
    activity_count = len(merged) if not merged.empty else 0

    cp_point_count = len(cp_trend_chart.get("dates", [])) if cp_trend_chart else 0
    has_recovery = not recovery.empty if hasattr(recovery, 'empty') else bool(recovery)

    data_meta = {
        "activity_count": activity_count,
        "data_days": data_days,
        "cp_points": cp_point_count,
        "has_recovery": has_recovery,
        "load_time_constant_days": ctl_tc,
        "pmc_sufficient": pmc_sufficient,
        "cp_trend_sufficient": cp_point_count >= 3,
    }

    result = {
        "signal": signal,
        "race_countdown": race_countdown,
        "fitness_fatigue": fitness_fatigue,
        "tsb_sparkline": tsb_sparkline,
        "weekly_review": weekly_review,
        "summary": training_summary,
        "cp_trend": cp_trend_chart,
        "cp_trend_data": cp_trend_data,
        "workout_flags": workout_flags,
        "sleep_perf": sleep_perf,
        "warnings": warnings,
        "diagnosis": diagnosis,
        "latest_cp": latest_cp,
        "activities": activities_list,
        "training_base": config.training_base,
        "display": get_display_config(config.training_base),
        "plan": plan,
        "all_plans": all_plans,
        "recovery_analysis": recovery_analysis,
        "science": science,
        "science_notes": {
            pillar: {
                "name": theory.name,
                "description": getattr(theory, 'simple_description', '') or '',
                "citations": [
                    {"label": getattr(c, 'title', getattr(c, 'key', '')), "url": getattr(c, 'url', '')}
                    for c in (getattr(theory, 'citations', None) or [])
                    if getattr(c, 'url', None)
                ],
            }
            for pillar, theory in science.items()
            if theory and hasattr(theory, 'name')
        },
        "data_meta": data_meta,
        "tsb_zones": [
            {**({"key": z.key} if z.key else {}), "min": z.min, "max": z.max, "label": z.label, "color": z.color}
            for z in (load_theory.tsb_zones_labeled if load_theory else [])
        ],
    }

    return result
