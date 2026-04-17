"""Shared data loading and metric computation for the API."""
import logging
import os
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from analysis.config import load_config
from analysis.data_loader import load_data
from analysis.providers.models import ThresholdEstimate
from analysis.training_base import get_display_config
from analysis.science import load_active_science
from analysis.metrics import (
    compute_ewma_load,
    compute_tsb,
    compute_activity_load,
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
    analyze_recovery,
    project_tsb,
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
    """Build ThresholdEstimate from config + auto-detect from fitness providers.

    When user_id and db are provided, extracts thresholds from the DB fitness
    data. Otherwise falls back to file-based provider detection.
    """
    if user_id and db:
        # DB path: extract latest thresholds from fitness_data table
        result = ThresholdEstimate()
        from db.models import FitnessData
        _METRIC_MAP = {
            "cp_estimate": "cp_watts",
            "lthr_bpm": "lthr_bpm",
            "lt_pace_sec_km": "threshold_pace_sec_km",
        }
        for db_metric, est_attr in _METRIC_MAP.items():
            row = (
                db.query(FitnessData)
                .filter(
                    FitnessData.user_id == user_id,
                    FitnessData.metric_type == db_metric,
                    FitnessData.value.isnot(None),
                )
                .order_by(FitnessData.date.desc())
                .first()
            )
            if row and row.value:
                setattr(result, est_attr, float(row.value))

        # Also look for max_hr and resting_hr
        for db_metric, est_attr in [("max_hr_bpm", "max_hr_bpm"), ("rest_hr_bpm", "rest_hr_bpm")]:
            row = (
                db.query(FitnessData)
                .filter(
                    FitnessData.user_id == user_id,
                    FitnessData.metric_type == db_metric,
                    FitnessData.value.isnot(None),
                )
                .order_by(FitnessData.date.desc())
                .first()
            )
            if row and row.value:
                setattr(result, est_attr, float(row.value))

        # Apply manual overrides from config
        t = config.thresholds
        if t.get("cp_watts"):
            result.cp_watts = float(t["cp_watts"])
        if t.get("lthr_bpm"):
            result.lthr_bpm = float(t["lthr_bpm"])
        if t.get("threshold_pace_sec_km"):
            result.threshold_pace_sec_km = float(t["threshold_pace_sec_km"])
        if t.get("max_hr_bpm"):
            result.max_hr_bpm = float(t["max_hr_bpm"])
        if t.get("rest_hr_bpm"):
            result.rest_hr_bpm = float(t["rest_hr_bpm"])

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


def _estimate_plan_daily_loads(
    plan: pd.DataFrame,
    start_date: date,
    days: int,
    thresholds: ThresholdEstimate,
    training_base: str,
) -> list[float]:
    """Estimate daily load for each of the next *days* days from the plan.

    For days with no planned workout, load is 0.
    Uses target power midpoint × planned duration to estimate RSS.
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
            dur_min = pd.to_numeric(
                pd.Series([row.get("planned_duration_min", 0)]), errors="coerce"
            ).iloc[0]
            dur_sec = float(dur_min) * 60 if pd.notna(dur_min) and dur_min > 0 else 0
            if dur_sec <= 0:
                continue

            # Estimate power from plan targets
            p_min = pd.to_numeric(pd.Series([row.get("target_power_min")]), errors="coerce").iloc[0]
            p_max = pd.to_numeric(pd.Series([row.get("target_power_max")]), errors="coerce").iloc[0]
            if pd.notna(p_min) and pd.notna(p_max) and p_min > 0:
                avg_power = (float(p_min) + float(p_max)) / 2
            elif pd.notna(p_max) and p_max > 0:
                avg_power = float(p_max) * 0.85  # conservative estimate
            else:
                avg_power = None

            if avg_power and thresholds.cp_watts and thresholds.cp_watts > 0:
                day_load += compute_rss(dur_sec, avg_power, thresholds.cp_watts)
            elif dur_sec > 0:
                # Fallback: estimate ~60 RSS per hour (moderate effort)
                day_load += (dur_sec / 3600) * 60
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
    thresholds: "ThresholdConfig | None" = None,
) -> dict:
    """Build weekly compliance data for chart using the configured training base."""
    if merged.empty:
        return {"weeks": [], "planned_rss": [], "actual_rss": []}

    # Use the computed daily load series if available
    if daily_load is not None and not daily_load.empty:
        load_df = daily_load.reset_index()
        load_df.columns = ["date", "load"]
        load_df["_date"] = pd.to_datetime(load_df["date"])
        load_df["_week"] = load_df["_date"].dt.isocalendar().week
        load_df["_year"] = load_df["_date"].dt.isocalendar().year
        weekly_actual = load_df.groupby(["_year", "_week"])["load"].sum()
    elif "rss" in merged.columns:
        merged_copy = merged.copy()
        merged_copy["_date"] = pd.to_datetime(merged_copy["date"])
        merged_copy["_week"] = merged_copy["_date"].dt.isocalendar().week
        merged_copy["_year"] = merged_copy["_date"].dt.isocalendar().year
        weekly_actual = merged_copy.groupby(["_year", "_week"])["rss"].sum()
    else:
        weekly_actual = pd.Series(dtype=float)

    weeks = (
        [f"W{int(w)}" for (_, w) in weekly_actual.index]
        if not weekly_actual.empty
        else []
    )

    # Compute planned weekly RSS from training plan
    planned_weekly: list[float] = []
    planned_estimated = False
    if not plan.empty and "date" in plan.columns:
        plan_copy = plan.copy()
        plan_copy["_date"] = pd.to_datetime(plan_copy["date"], errors="coerce")
        plan_copy = plan_copy.dropna(subset=["_date"])
        if not plan_copy.empty:
            plan_copy["_week"] = plan_copy["_date"].dt.isocalendar().week
            plan_copy["_year"] = plan_copy["_date"].dt.isocalendar().year

            # Estimate per-workout load from plan targets
            plan_loads = []
            for _, row in plan_copy.iterrows():
                dur_min = pd.to_numeric(
                    pd.Series([row.get("planned_duration_min", 0)]), errors="coerce"
                ).iloc[0]
                dur_sec = float(dur_min) * 60 if pd.notna(dur_min) and dur_min > 0 else 0
                if dur_sec <= 0:
                    plan_loads.append(0.0)
                    continue
                p_min = pd.to_numeric(pd.Series([row.get("target_power_min")]), errors="coerce").iloc[0]
                p_max = pd.to_numeric(pd.Series([row.get("target_power_max")]), errors="coerce").iloc[0]
                if pd.notna(p_min) and pd.notna(p_max) and p_min > 0:
                    avg_power = (float(p_min) + float(p_max)) / 2
                elif pd.notna(p_max) and p_max > 0:
                    avg_power = float(p_max) * 0.85
                else:
                    avg_power = None
                cp = thresholds.cp_watts if thresholds and thresholds.cp_watts else None
                if avg_power and cp and cp > 0:
                    plan_loads.append(compute_rss(dur_sec, avg_power, cp))
                else:
                    # Fallback: ~60 RSS per hour. This is a rough estimate
                    # when power targets are unavailable.
                    plan_loads.append((dur_sec / 3600) * 60)
                    planned_estimated = True
            plan_copy["_load"] = plan_loads
            weekly_planned = plan_copy.groupby(["_year", "_week"])["_load"].sum()

            # Build planned list for all weeks that have either actuals or plan
            all_indices = set(weekly_actual.index) | set(weekly_planned.index)
            for idx in sorted(all_indices):
                if idx in weekly_planned.index:
                    planned_weekly.append(round(float(weekly_planned[idx]), 1))
                else:
                    planned_weekly.append(0)

    # Align planned to actual weeks
    aligned_planned: list[float] = []
    if not weekly_actual.empty and not plan.empty and "_load" in plan_copy.columns:
        weekly_planned_series = plan_copy.groupby(["_year", "_week"])["_load"].sum()
        for idx in weekly_actual.index:
            if idx in weekly_planned_series.index:
                aligned_planned.append(round(float(weekly_planned_series[idx]), 1))
            else:
                aligned_planned.append(0)

    return {
        "weeks": weeks[-8:],
        "actual_rss": [round(float(v), 1) for v in weekly_actual.values][-8:],
        "planned_rss": aligned_planned[-8:] if aligned_planned else [],
        "planned_estimated": planned_estimated,
    }


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


def _build_sleep_perf(merged: pd.DataFrame, sleep: pd.DataFrame) -> list:
    """Build sleep score vs power output scatter data."""
    if merged.empty or sleep.empty or "avg_power" not in merged.columns:
        return []
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
        return []
    pairs: list[list] = []
    for _, row in joined.iterrows():
        try:
            score = float(row["sleep_score"])
            power = float(row["avg_power"])
            if score > 0 and power > 0:
                pairs.append([score, round(power, 1)])
        except (ValueError, TypeError):
            continue
    return pairs


def _build_race_countdown(
    race_date_str: str,
    target_time_sec: int | None,
    latest_cp: float | None,
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
    prediction_theory_name: str | None = None,
) -> dict:
    """Build race countdown / CP milestone payload depending on config.

    For power base: uses power-pace model for predictions.
    For HR/pace bases: uses Riegel formula from threshold pace.
    The prediction method is determined by the user's science theory selection.
    """
    is_inverted = training_base == "pace"

    # Predicted time — uses prediction theory selection
    predicted_time: float | None = None
    prediction_method = "none"
    if training_base == "power" and latest_cp:
        predicted_time = predict_marathon_time(latest_cp, power_pace_pairs, power_fraction, distance_km)
        prediction_method = "critical_power"
    elif threshold_pace:
        predicted_time = predict_time_from_pace(threshold_pace, distance_km, riegel_exponent)
        prediction_method = "riegel"

    common = {
        "distance": distance_key,
        "distance_label": distance_label,
        "prediction_method": prediction_method,
        "prediction_theory": prediction_theory_name,
    }

    if race_date_str:
        days_left = (date.fromisoformat(race_date_str) - today).days
        race_status = "unknown"
        if predicted_time and target_time_sec:
            if predicted_time <= target_time_sec:
                race_status = "on_track"
            elif predicted_time <= target_time_sec * 1.03:
                race_status = "close"
            else:
                race_status = "behind"

        # Needed threshold — only for power/pace (LTHR can't be meaningfully targeted)
        needed_threshold: float | None = None
        if target_time_sec and training_base != "hr":
            if training_base == "power" and power_pace_pairs:
                needed_threshold = required_cp_for_time(target_time_sec, power_pace_pairs, power_fraction, distance_km)
            elif threshold_pace:
                needed_threshold = required_pace_for_time(target_time_sec, distance_km)

        race_reality = race_honesty_check(
            latest_cp,
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
        # Continuous improvement with a time target
        # For HR base: show time predictions only (LTHR can't be meaningfully targeted)
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

        # For power/pace: derive threshold target and track progress
        target_threshold: float | None = None
        if training_base == "power" and power_pace_pairs:
            target_threshold = required_cp_for_time(target_time_sec, power_pace_pairs, power_fraction, distance_km)
        elif threshold_pace:
            target_threshold = required_pace_for_time(target_time_sec, distance_km)

        if target_threshold and latest_cp:
            milestone_result = cp_milestone_check(
                latest_cp, target_threshold, cp_trend_data, threshold_inverted=is_inverted,
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
            "current_cp": latest_cp,
            "target_cp": target_threshold,
            "target_time_sec": target_time_sec,
            "predicted_time_sec": predicted_time,
            "cp_gap_watts": milestone_result.get("cp_gap_watts"),
            "status": milestone_result.get("severity", "unknown"),
            "milestones": milestone_result.get("milestones", []),
            "estimated_months": milestone_result.get("estimated_months"),
            "reality_check": milestone_result,
        }

    # Continuous improvement, no target
    direction = cp_trend_data.get("direction", "unknown")
    slope = cp_trend_data.get("slope_per_month", 0)
    severity = "on_track" if direction == "rising" else ("behind" if direction == "falling" else "close")
    return {
        **common,
        "mode": "continuous",
        "status": severity,
        "current_cp": latest_cp,
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
    latest_readiness = float(latest_row["readiness_score"])
    latest_hrv = None
    if "hrv_avg" in readiness.columns:
        hrv_val = pd.to_numeric(
            pd.Series([latest_row.get("hrv_avg")]), errors="coerce"
        ).iloc[0]
        latest_hrv = float(hrv_val) if pd.notna(hrv_val) else None
    return latest_readiness, latest_hrv


def _get_todays_plan(
    plan: pd.DataFrame, today: date
) -> tuple[str, dict | None]:
    """Return (planned_workout_type, planned_detail_dict) for today."""
    if plan.empty:
        return "", None
    today_plan = plan[plan["date"] == today]
    if today_plan.empty:
        return "", None
    plan_row = today_plan.iloc[0]
    planned_today = plan_row.get("workout_type", "")
    raw_dict = plan_row.to_dict()
    planned_detail = {k: (v if pd.notna(v) else None) for k, v in raw_dict.items()}
    return planned_today, planned_detail


def _build_activities_list(
    merged: pd.DataFrame, splits: pd.DataFrame
) -> list[dict]:
    """Build a list of activity dicts from merged activities + splits."""
    if merged.empty:
        return []
    activities: list[dict] = []
    merged_sorted = merged.sort_values("date", ascending=False)
    for _, row in merged_sorted.iterrows():
        act: dict = {
            "activity_id": str(row.get("activity_id", "")),
            "date": str(row["date"]),
            "source": str(row.get("source", "")),
            "activity_type": row.get("activity_type", "running"),
            "distance_km": (
                round(float(row.get("distance_km", 0)), 2)
                if pd.notna(row.get("distance_km"))
                else None
            ),
            "duration_sec": (
                int(row.get("duration_sec", 0))
                if pd.notna(row.get("duration_sec"))
                else None
            ),
            "avg_power": (
                round(float(row.get("avg_power", 0)), 1)
                if pd.notna(row.get("avg_power"))
                else None
            ),
            "avg_hr": (
                int(row.get("avg_hr", 0))
                if pd.notna(row.get("avg_hr"))
                else None
            ),
            "avg_pace_min_km": (
                str(row.get("avg_pace_min_km", ""))
                if pd.notna(row.get("avg_pace_min_km"))
                else None
            ),
            "elevation_gain_m": (
                round(float(row.get("elevation_gain_m", 0)), 1)
                if pd.notna(row.get("elevation_gain_m"))
                else None
            ),
            "rss": (
                round(float(row.get("rss", 0)), 1)
                if pd.notna(row.get("rss"))
                else None
            ),
            "cp_estimate": (
                round(float(row.get("cp_estimate", 0)), 1)
                if pd.notna(row.get("cp_estimate"))
                else None
            ),
        }
        # Add splits for this activity
        if not splits.empty and "activity_id" in splits.columns:
            act_splits = splits[
                splits["activity_id"].astype(str) == str(row.get("activity_id", ""))
            ]
            act["splits"] = [
                {
                    "split_num": (
                        int(s.get("split_num", 0))
                    ),
                    "distance_km": (
                        round(float(s.get("distance_km", 0)), 2)
                        if pd.notna(s.get("distance_km"))
                        else None
                    ),
                    "duration_sec": (
                        int(s.get("duration_sec", 0))
                        if pd.notna(s.get("duration_sec"))
                        else None
                    ),
                    "avg_power": (
                        round(float(s.get("avg_power", 0)), 1)
                        if pd.notna(s.get("avg_power"))
                        else None
                    ),
                    "avg_hr": (
                        int(s.get("avg_hr", 0))
                        if pd.notna(s.get("avg_hr"))
                        else None
                    ),
                    "avg_pace_min_km": (
                        str(s.get("avg_pace_min_km", ""))
                        if pd.notna(s.get("avg_pace_min_km"))
                        else None
                    ),
                }
                for _, s in act_splits.iterrows()
            ]
        else:
            act["splits"] = []
        activities.append(act)
    return activities


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _compute_threshold_data(
    merged: pd.DataFrame, config, data_dir: str = None,
    user_id: str = None, db=None,
) -> tuple[float | None, dict, pd.Series, list[tuple[float, float]]]:
    """Compute active threshold value, trend data, CP values, and power-pace pairs.

    Returns (latest_threshold, trend_data, cp_values, power_pace_pairs).
    When user_id and db are provided, uses DB-based fitness data for HR/pace trends.
    """
    cp_values = (
        pd.to_numeric(merged["cp_estimate"], errors="coerce")
        if "cp_estimate" in merged.columns
        else pd.Series(dtype=float)
    )
    cp_values = cp_values[cp_values > 0].dropna()

    # Supplement with fitness_data CP estimates (includes profile CP from Stryd sync)
    if user_id and db:
        from db.models import FitnessData as FDModel
        fd_rows = db.query(FDModel.date, FDModel.value).filter(
            FDModel.user_id == user_id,
            FDModel.metric_type == "cp_estimate",
            FDModel.value.isnot(None),
        ).all()
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
        latest = float(cp_values.iloc[-1]) if not cp_values.empty else None
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

        lt_df = pd.DataFrame()
        if user_id and db:
            from analysis.data_loader import load_data_from_db
            db_data = load_data_from_db(user_id, db)
            lt_df = db_data.get("fitness", pd.DataFrame())

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


def _compute_recovery_analysis(recovery: pd.DataFrame) -> tuple[dict, float | None, float | None, float | None]:
    """Extract recovery time series and run analyze_recovery().

    Returns (recovery_analysis, today_hrv, today_sleep, today_rhr).
    """
    recovery_sorted = recovery.sort_values("date") if not recovery.empty else recovery
    hrv_series: list[float] = []
    rhr_series: list[float] = []
    today_hrv = None
    today_sleep = None
    today_rhr = None

    if not recovery_sorted.empty:
        if "hrv_avg" in recovery_sorted.columns:
            hrv_vals = pd.to_numeric(recovery_sorted["hrv_avg"], errors="coerce")
            hrv_series = [float(v) for v in hrv_vals.dropna() if v > 0]
        if "resting_hr" in recovery_sorted.columns:
            rhr_vals = pd.to_numeric(recovery_sorted["resting_hr"], errors="coerce")
            rhr_series = [float(v) for v in rhr_vals.dropna() if v > 0]

        latest_row = recovery_sorted.iloc[-1]
        hrv_val = pd.to_numeric(
            pd.Series([latest_row.get("hrv_avg")]), errors="coerce"
        ).iloc[0]
        today_hrv = float(hrv_val) if pd.notna(hrv_val) and hrv_val > 0 else None

        sleep_val = pd.to_numeric(
            pd.Series([latest_row.get("sleep_score")]), errors="coerce"
        ).iloc[0]
        today_sleep = float(sleep_val) if pd.notna(sleep_val) else None

        rhr_val = pd.to_numeric(
            pd.Series([latest_row.get("resting_hr")]), errors="coerce"
        ).iloc[0]
        today_rhr = float(rhr_val) if pd.notna(rhr_val) and rhr_val > 0 else None

    analysis = analyze_recovery(
        hrv_series,
        today_hrv_ms=today_hrv,
        today_sleep=today_sleep,
        today_rhr=today_rhr,
        rhr_series=rhr_series if rhr_series else None,
    )
    return analysis, today_hrv, today_sleep, today_rhr


def _build_threshold_trend_chart(
    merged: pd.DataFrame, config, data_dir: str = None,
    user_id: str = None, db=None,
) -> dict:
    """Build threshold trend chart data based on training base.

    When user_id and db are provided, uses DB-based fitness data.
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
        lt_df = pd.DataFrame()
        if user_id and db:
            from analysis.data_loader import load_data_from_db
            db_data = load_data_from_db(user_id, db)
            lt_df = db_data.get("fitness", pd.DataFrame())

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
    recovery_analysis: dict, current_tsb: float,
    config, data_dir: str = None, latest_cp: float | None = None,
) -> list[str]:
    """Collect health/training warnings."""
    warnings: list[str] = []
    hrv_info = recovery_analysis.get("hrv") or {}
    if hrv_info.get("trend") == "declining":
        warnings.append("HRV rolling mean declining — monitor recovery")
    if hrv_info.get("rolling_cv", 0) > 10:
        warnings.append(f"HRV variability high (CV {hrv_info['rolling_cv']:.0f}%) — autonomic disturbance")
    if current_tsb < -25:
        warnings.append(f"High fatigue (TSB = {current_tsb:.0f})")
    if config.preferences.get("plan") == "ai" and data_dir:
        from api.ai import check_plan_staleness
        warnings.extend(check_plan_staleness(data_dir, latest_cp))
    return warnings


def _compute_diagnosis(
    merged: pd.DataFrame, splits: pd.DataFrame,
    cp_trend_data: dict, config, thresholds, science: dict,
) -> dict:
    """Run zone-aware training diagnosis."""
    if config.training_base == "power":
        active_threshold = thresholds.cp_watts
    elif config.training_base == "hr":
        active_threshold = thresholds.lthr_bpm
    else:
        active_threshold = thresholds.threshold_pace_sec_km

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

    return diagnose_training(
        merged, splits, cp_trend_data,
        base=config.training_base,
        threshold_value=active_threshold,
        zone_boundaries=zone_boundaries,
        zone_names=zone_names_list,
        target_distribution=target_dist,
        theory_name=zone_theory_name,
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

    merged = data["activities"]

    # Deduplicate activities by primary source preference.
    # When multiple sources (e.g., Garmin + Stryd) sync the same run,
    # keep the primary source version to avoid double-counting in metrics.
    primary_source = config.preferences.get("activities")
    if primary_source and not merged.empty and "source" in merged.columns:
        import pandas as pd
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
    science = load_active_science(config.science, config.zone_labels)
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

    # Threshold data (CP / LTHR / pace trend)
    latest_cp, cp_trend_data, cp_values, power_pace_pairs = _compute_threshold_data(
        merged, config, data_dir=data_dir, user_id=user_id, db=db,
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

    # Determine prediction method based on science theory selection.
    # The prediction theory is independent of training base:
    # - "critical_power" theory → uses CP + power-pace model (requires power data)
    # - "riegel" theory → uses threshold pace + Riegel formula (requires pace data)
    # Falls back to the other model if the selected one lacks data.
    if prediction_theory_id == "critical_power" and latest_cp:
        prediction_base = "power"
    elif prediction_theory_id == "riegel" and threshold_pace:
        prediction_base = "pace"
    elif latest_cp:
        # Fallback: user selected Riegel but no pace data, use CP if available
        prediction_base = "power"
    elif threshold_pace:
        # Fallback: user selected CP but no power data, use Riegel if pace available
        prediction_base = "pace"
    else:
        prediction_base = config.training_base

    race_countdown = _build_race_countdown(
        race_date_str, target_time_sec, latest_cp, power_pace_pairs,
        cp_trend_data, today,
        distance_km=dist_config["km"],
        power_fraction=dist_config["power_fraction"],
        distance_label=dist_config["label"],
        distance_key=distance_key,
        training_base=prediction_base,
        threshold_pace=threshold_pace,
        riegel_exponent=theory_exponent,
        prediction_theory_name=prediction_theory.name if prediction_theory else None,
    )

    # Recovery
    recovery = data["recovery"]
    recovery_analysis, _, _, _ = _compute_recovery_analysis(recovery)
    current_tsb = float(tsb.iloc[-1]) if not tsb.empty else 0.0

    # Daily training signal
    planned_today, planned_detail = _get_todays_plan(plan, today)
    # Recovery is standardized to a single HRV-based theory.
    hrv_only_mode = True
    signal = daily_training_signal(
        recovery_analysis, current_tsb, planned_today,
        planned_detail=planned_detail,
        signal_thresholds=load_theory.signal if load_theory else None,
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
    )

    # Supplementary data
    weekly_review = _build_compliance(merged, plan, config.training_base, daily_load, thresholds)
    workout_flags = _build_workout_flags(merged, recovery, config.training_base)
    sleep_perf = _build_sleep_perf(merged, recovery)
    warnings = _build_warnings(recovery_analysis, current_tsb, config, data_dir=data_dir, latest_cp=latest_cp)

    # Diagnosis
    splits = data["splits"]
    diagnosis = _compute_diagnosis(merged, splits, cp_trend_data, config, thresholds, science)

    # Activities for history
    activities_list = _build_activities_list(merged, splits)

    # Data sufficiency metadata — helps frontend decide what to show
    activity_count = len(merged) if not merged.empty else 0
    data_days = (today - earliest).days if not merged.empty else 0
    cp_point_count = len(cp_trend_data.get("dates", [])) if cp_trend_data else 0
    has_recovery = not recovery.empty if hasattr(recovery, 'empty') else bool(recovery)

    data_meta = {
        "activity_count": activity_count,
        "data_days": data_days,
        "cp_points": cp_point_count,
        "has_recovery": has_recovery,
        "pmc_sufficient": data_days >= 42,
        "cp_trend_sufficient": cp_point_count >= 3,
    }

    result = {
        "signal": signal,
        "race_countdown": race_countdown,
        "fitness_fatigue": fitness_fatigue,
        "tsb_sparkline": tsb_sparkline,
        "weekly_review": weekly_review,
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
            {"min": z.min, "max": z.max, "label": z.label, "color": z.color}
            for z in (load_theory.tsb_zones_labeled if load_theory else [])
        ],
    }

    return result
