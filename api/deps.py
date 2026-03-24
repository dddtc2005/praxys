"""Shared data loading and metric computation for the API."""
import os
import time
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv

from analysis.config import load_config
from analysis.data_loader import load_data
from analysis.providers.models import ThresholdEstimate
from analysis.training_base import get_display_config
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
# Cache
# ---------------------------------------------------------------------------

_cache: dict = {}
_cache_time: float = 0
CACHE_TTL = 300  # 5 minutes


def invalidate_cache():
    """Force data reload on next request."""
    global _cache, _cache_time
    _cache = {}
    _cache_time = 0


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _resolve_thresholds(config, data_dir: str) -> ThresholdEstimate:
    """Build ThresholdEstimate from config + auto-detect from fitness providers."""
    from analysis.config import PLATFORM_CAPABILITIES
    from analysis.providers import get_fitness_provider

    result = ThresholdEstimate()

    # Auto-detect from connected fitness providers
    for conn in config.connections:
        caps = PLATFORM_CAPABILITIES.get(conn, {})
        if not caps.get("fitness"):
            continue
        try:
            provider = get_fitness_provider(conn)
            detected = provider.detect_thresholds(data_dir)
            if result.cp_watts is None and detected.cp_watts:
                result.cp_watts = detected.cp_watts
            if result.lthr_bpm is None and detected.lthr_bpm:
                result.lthr_bpm = detected.lthr_bpm
            if result.threshold_pace_sec_km is None and detected.threshold_pace_sec_km:
                result.threshold_pace_sec_km = detected.threshold_pace_sec_km
        except (KeyError, Exception):
            continue

    # Manual overrides from config
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
    return {
        "weeks": weeks[-8:],
        "actual_rss": [round(float(v), 1) for v in weekly_actual.values][-8:],
        "planned_rss": [],  # TODO: compute from plan when available
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
) -> dict:
    """Build race countdown / CP milestone payload depending on config.

    For power base: uses power-pace model for predictions.
    For HR/pace bases: uses Riegel formula from threshold pace.
    """
    common = {
        "distance": distance_key,
        "distance_label": distance_label,
    }
    is_inverted = training_base == "pace"

    # Predicted time — base-aware
    predicted_time: float | None = None
    if training_base == "power" and latest_cp:
        predicted_time = predict_marathon_time(latest_cp, power_pace_pairs, power_fraction, distance_km)
    elif threshold_pace:
        predicted_time = predict_time_from_pace(threshold_pace, distance_km)

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


def get_dashboard_data() -> dict:
    """Load all data, compute all metrics. Cached for CACHE_TTL seconds."""
    global _cache, _cache_time
    now = time.time()
    if _cache and (now - _cache_time) < CACHE_TTL:
        return _cache

    _ensure_env()
    config = load_config()
    base_dir = os.path.join(os.path.dirname(__file__), "..")
    data_dir = os.path.join(base_dir, "data")

    data = load_data(config, data_dir)
    merged = data["activities"]  # Already merged by load_data()
    thresholds = _resolve_thresholds(config, data_dir)

    today = date.today()

    # Use ALL historical data for EWMA so CTL/ATL stabilize correctly.
    # The 42-day CTL time constant needs months of history to be accurate.
    earliest = today - timedelta(days=365)  # default if no data
    if not merged.empty and "date" in merged.columns:
        first_date = pd.to_datetime(merged["date"]).min()
        if pd.notna(first_date):
            earliest = first_date.date()
    full_range = pd.date_range(earliest, today)
    daily_load = _compute_daily_load(merged, full_range, config, thresholds)
    ctl = compute_ewma_load(daily_load, time_constant=42)
    atl = compute_ewma_load(daily_load, time_constant=7)
    tsb = compute_tsb(ctl, atl)

    # Display window for charts (last 60 days)
    display_days = 60
    date_range = pd.date_range(today - timedelta(days=display_days), today)

    # CP / power data (always needed for power-based predictions)
    cp_values = (
        pd.to_numeric(merged["cp_estimate"], errors="coerce")
        if "cp_estimate" in merged.columns
        else pd.Series(dtype=float)
    )
    cp_values = cp_values[cp_values > 0].dropna()
    power_pace_pairs = _get_power_pace_pairs(merged)

    # latest_cp = active threshold for the configured training base
    # cp_trend_data = trend analysis for the active threshold
    if config.training_base == "power":
        latest_cp = float(cp_values.iloc[-1]) if not cp_values.empty else None
        cp_trend_data = (
            compute_cp_trend(
                [float(v) for v in cp_values.values],
                list(cp_values.index),
            )
            if not cp_values.empty
            else {"direction": "unknown"}
        )
    elif config.training_base in ("hr", "pace"):
        from analysis.data_loader import _read_csv_safe
        from analysis.metrics import compute_threshold_trend
        lt_df = _read_csv_safe(os.path.join(data_dir, "garmin", "lactate_threshold.csv"))
        col = "lthr_bpm" if config.training_base == "hr" else "lt_pace_sec_km"
        if not lt_df.empty and col in lt_df.columns:
            lt_df = lt_df.sort_values("date")
            vals = pd.to_numeric(lt_df[col], errors="coerce").dropna()
            latest_cp = float(vals.iloc[-1]) if not vals.empty else None
            cp_trend_data = (
                compute_threshold_trend(
                    [float(v) for v in vals.values],
                    list(vals.index),
                    invert_direction=(config.training_base == "pace"),
                )
                if not vals.empty
                else {"direction": "unknown"}
            )
        else:
            latest_cp = None
            cp_trend_data = {"direction": "unknown"}
    else:
        latest_cp = None
        cp_trend_data = {"direction": "unknown"}

    # Goal config — from config.json only (managed via UI)
    race_date_str = str(config.goal.get("race_date", "")).strip()
    raw_target = config.goal.get("target_time_sec") or config.goal.get("race_target_time_sec")
    target_time_sec = int(raw_target) if raw_target else None

    # Distance config
    distance_key = str(config.goal.get("distance", "marathon")).strip() or "marathon"
    dist_config = get_distance_config(distance_key)

    # For HR/pace bases, use threshold pace for predictions (Riegel formula)
    threshold_pace = thresholds.threshold_pace_sec_km if config.training_base in ("hr", "pace") else None

    # Race / CP goal
    race_countdown = _build_race_countdown(
        race_date_str,
        target_time_sec,
        latest_cp,
        power_pace_pairs,
        cp_trend_data,
        today,
        distance_km=dist_config["km"],
        power_fraction=dist_config["power_fraction"],
        distance_label=dist_config["label"],
        distance_key=distance_key,
        training_base=config.training_base,
        threshold_pace=threshold_pace,
    )

    # Recovery data (sleep, HRV, readiness)
    recovery = data["recovery"]
    latest_readiness, latest_hrv = _get_latest_readiness(recovery)
    latest_sleep = (
        float(recovery.sort_values("date").iloc[-1]["sleep_score"])
        if not recovery.empty and "sleep_score" in recovery.columns
        else None
    )
    hrv_trend = _get_hrv_trend(recovery)
    current_tsb = float(tsb.iloc[-1]) if not tsb.empty else 0.0

    plan = data["plan"]
    planned_today, planned_detail = _get_todays_plan(plan, today)

    signal = daily_training_signal(
        latest_readiness,
        current_tsb,
        hrv_trend,
        planned_today,
        planned_detail=planned_detail,
        sleep_score=latest_sleep,
        hrv_value=latest_hrv,
    )

    # Chart data — fitness/fatigue (last 60 days from display window)
    # Slice the full-history EWMA to the display window
    display_ctl = ctl.iloc[-len(date_range):]
    display_atl = atl.iloc[-len(date_range):]
    display_tsb = tsb.iloc[-len(date_range):]
    ff_dates = [d.strftime("%Y-%m-%d") for d in date_range]
    fitness_fatigue = {
        "dates": ff_dates,
        "ctl": [round(float(v), 1) for v in display_ctl.values],
        "atl": [round(float(v), 1) for v in display_atl.values],
        "tsb": [round(float(v), 1) for v in display_tsb.values],
    }

    # TSB sparkline (last 14 days)
    tsb_sparkline = {
        "dates": ff_dates[-14:],
        "values": [round(float(v), 1) for v in display_tsb.values][-14:],
    }

    # Threshold trend chart — varies by training base
    cp_trend_chart: dict = {"dates": [], "values": []}
    if config.training_base == "power":
        if not merged.empty and "cp_estimate" in merged.columns:
            cp_data = merged.dropna(subset=["cp_estimate"]).sort_values("date")
            cp_trend_chart = {
                "dates": [str(d) for d in cp_data["date"].values],
                "values": [round(float(v), 1) for v in cp_data["cp_estimate"].values],
            }
    elif config.training_base in ("hr", "pace"):
        # Use Garmin lactate threshold CSV for LTHR/pace trend
        from analysis.data_loader import _read_csv_safe
        lt_df = _read_csv_safe(os.path.join(data_dir, "garmin", "lactate_threshold.csv"))
        if not lt_df.empty:
            lt_df = lt_df.sort_values("date")
            if config.training_base == "hr" and "lthr_bpm" in lt_df.columns:
                lt_vals = pd.to_numeric(lt_df["lthr_bpm"], errors="coerce")
                valid = lt_vals.dropna()
                if not valid.empty:
                    cp_trend_chart = {
                        "dates": [str(lt_df.loc[i, "date"]) for i in valid.index],
                        "values": [round(float(v), 1) for v in valid.values],
                    }
            elif config.training_base == "pace" and "lt_pace_sec_km" in lt_df.columns:
                lt_vals = pd.to_numeric(lt_df["lt_pace_sec_km"], errors="coerce")
                valid = lt_vals.dropna()
                if not valid.empty:
                    cp_trend_chart = {
                        "dates": [str(lt_df.loc[i, "date"]) for i in valid.index],
                        "values": [round(float(v), 1) for v in valid.values],
                    }

    weekly_review = _build_compliance(merged, plan, config.training_base, daily_load)
    workout_flags = _build_workout_flags(merged, recovery, config.training_base)
    sleep_perf = _build_sleep_perf(merged, recovery)

    warnings: list[str] = []
    if hrv_trend < -10:
        warnings.append(f"HRV declining ({hrv_trend:.0f}% over 3 days)")
    if current_tsb < -25:
        warnings.append(f"High fatigue (TSB = {current_tsb:.0f})")

    # AI plan staleness check
    if config.preferences.get("plan") == "ai":
        from api.ai import check_plan_staleness
        warnings.extend(check_plan_staleness(data_dir, latest_cp))

    splits = data["splits"]

    # Get threshold value for the active training base
    if config.training_base == "power":
        active_threshold = thresholds.cp_watts
    elif config.training_base == "hr":
        active_threshold = thresholds.lthr_bpm
    else:
        active_threshold = thresholds.threshold_pace_sec_km

    diagnosis = diagnose_training(
        merged, splits, cp_trend_data,
        base=config.training_base,
        threshold_value=active_threshold,
    )

    # Activities for history
    activities_list = _build_activities_list(merged, splits)

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
        # Multi-source: display config for frontend dynamic labels
        "training_base": config.training_base,
        "display": get_display_config(config.training_base),
        "plan": plan,
    }

    _cache = result
    _cache_time = now
    return result
