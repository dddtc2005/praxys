"""Derived training metrics: load, fatigue, race prediction, training signal."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from analysis.config import TrainingBase
    from analysis.providers.models import ThresholdEstimate

# Distance configs: km, sustainable power fraction of CP, display label.
# Power fractions for 5K–marathon from Stryd Race Power Calculator
# (https://help.stryd.com/en/articles/6879547-race-power-calculator).
# Ultra fractions are estimates — less research available.
DISTANCE_CONFIGS: dict[str, dict] = {
    "5k":       {"km": 5.0,     "power_fraction": 1.038, "label": "5K"},
    "10k":      {"km": 10.0,    "power_fraction": 1.00,  "label": "10K"},
    "half":     {"km": 21.0975, "power_fraction": 0.946, "label": "Half Marathon"},
    "marathon": {"km": 42.195,  "power_fraction": 0.899, "label": "Marathon"},
    "50k":      {"km": 50.0,    "power_fraction": 0.88,  "label": "50K"},
    "50mi":     {"km": 80.467,  "power_fraction": 0.85,  "label": "50 Mile"},
    "100k":     {"km": 100.0,   "power_fraction": 0.82,  "label": "100K"},
    "100mi":    {"km": 160.934, "power_fraction": 0.78,  "label": "100 Mile"},
}

# Riegel fatigue exponent — validated for 1K through marathon.
# Pete Riegel, "Athletic Records and Human Endurance", American Scientist, 1981.
# https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html
RIEGEL_EXPONENT = 1.06

# Threshold pace ≈ 10K race pace (~1-hour effort) for most recreational runners.
THRESHOLD_REFERENCE_KM = 10.0


def get_distance_config(distance: str) -> dict:
    """Return distance config, defaulting to marathon."""
    return DISTANCE_CONFIGS.get(distance, DISTANCE_CONFIGS["marathon"])


def compute_ewma_load(daily_rss: pd.Series, time_constant: int) -> pd.Series:
    """Compute EWMA of daily load using the standard PMC time constant.

    Uses alpha = 1/τ to match the industry-standard Performance Management
    Chart model used by TrainingPeaks, Stryd, and Intervals.icu.
    The continuous-time exact form (alpha = 1 - exp(-1/τ)) differs by ~7%
    for ATL (τ=7), causing 5-10 point TSB discrepancies vs platforms.

    Reference: Banister impulse-response model (1975);
    https://help.trainingpeaks.com/hc/en-us/articles/204071944
    """
    alpha = 1.0 / time_constant
    return daily_rss.ewm(alpha=alpha, adjust=False).mean()


def compute_tsb(ctl: pd.Series, atl: pd.Series) -> pd.Series:
    """Training Stress Balance = CTL - ATL."""
    return ctl - atl


def project_tsb(
    current_ctl: float,
    current_atl: float,
    future_daily_loads: list[float],
    ctl_tc: int = 42,
    atl_tc: int = 7,
) -> tuple[list[float], list[float], list[float]]:
    """Project CTL/ATL/TSB forward given estimated future daily loads.

    Uses the same EWMA recurrence as compute_ewma_load (alpha = 1/tau).
    Returns (projected_ctl, projected_atl, projected_tsb) lists.
    """
    alpha_ctl = 1.0 / ctl_tc
    alpha_atl = 1.0 / atl_tc
    ctl, atl = current_ctl, current_atl
    proj_ctl, proj_atl, proj_tsb = [], [], []
    for load in future_daily_loads:
        ctl = ctl + alpha_ctl * (load - ctl)
        atl = atl + alpha_atl * (load - atl)
        proj_ctl.append(round(ctl, 1))
        proj_atl.append(round(atl, 1))
        proj_tsb.append(round(ctl - atl, 1))
    return proj_ctl, proj_atl, proj_tsb


def compute_rss(duration_sec: float, avg_power: float, cp: float) -> float:
    """Running Stress Score (power-based load).

    RSS = (duration/3600) * (power/CP)^2 * 100
    """
    if cp <= 0 or avg_power <= 0 or duration_sec <= 0:
        return 0.0
    return (duration_sec / 3600) * (avg_power / cp) ** 2 * 100


def compute_trimp(
    duration_sec: float,
    avg_hr: float,
    rest_hr: float,
    max_hr: float,
    sex: str = "male",
) -> float:
    """Banister TRIMP (HR-based load).

    Uses exponential weighting of HR intensity.
    """
    if duration_sec <= 0 or max_hr <= rest_hr:
        return 0.0
    duration_min = duration_sec / 60
    delta_ratio = (avg_hr - rest_hr) / (max_hr - rest_hr)
    delta_ratio = max(0.0, min(1.0, delta_ratio))
    k = 1.92 if sex == "male" else 1.67
    return duration_min * delta_ratio * 0.64 * math.exp(k * delta_ratio)


def compute_rtss(
    duration_sec: float,
    avg_pace_sec_km: float,
    threshold_pace_sec_km: float,
) -> float:
    """Running TSS from normalized graded pace (pace-based load).

    rTSS = (duration/3600) * (threshold_pace/actual_pace)^2 * 100
    Faster pace = lower sec/km, so threshold/actual > 1 when running hard.
    """
    if duration_sec <= 0 or avg_pace_sec_km <= 0 or threshold_pace_sec_km <= 0:
        return 0.0
    intensity_factor = threshold_pace_sec_km / avg_pace_sec_km
    return (duration_sec / 3600) * intensity_factor ** 2 * 100


def compute_activity_load(
    base: TrainingBase,
    duration_sec: float,
    thresholds: ThresholdEstimate,
    avg_power: float | None = None,
    avg_hr: float | None = None,
    avg_pace_sec_km: float | None = None,
) -> float | None:
    """Compute load score for a single activity using the selected training base.

    Returns None if required data is missing for the chosen base.
    """
    if base == "power" and avg_power and thresholds.cp_watts:
        return compute_rss(duration_sec, avg_power, thresholds.cp_watts)
    elif base == "hr" and avg_hr and thresholds.lthr_bpm and thresholds.max_hr_bpm:
        rest_hr = thresholds.rest_hr_bpm or 60
        return compute_trimp(
            duration_sec, avg_hr, rest_hr, thresholds.max_hr_bpm
        )
    elif base == "pace" and avg_pace_sec_km and thresholds.threshold_pace_sec_km:
        return compute_rtss(
            duration_sec, avg_pace_sec_km, thresholds.threshold_pace_sec_km
        )
    return None


def predict_marathon_time(
    cp_watts: float,
    recent_power_pace_pairs: list[tuple[float, float]],
    marathon_power_fraction: float = 0.80,
    marathon_distance_km: float = 42.195,
) -> float | None:
    if not cp_watts or cp_watts <= 0:
        return None

    target_power = cp_watts * marathon_power_fraction

    if recent_power_pace_pairs and len(recent_power_pace_pairs) >= 1:
        # Power and pace have inverse relationship: more power = faster (lower sec/km)
        # Compute average (power * pace) product as constant k, then pace = k / power
        k_values = [power * pace for power, pace in recent_power_pace_pairs]
        avg_k = sum(k_values) / len(k_values)
        predicted_pace = avg_k / target_power
    else:
        # Fallback: rough estimate ~4:15/km at 250W baseline
        baseline_pace = 255  # sec/km at 250W
        baseline_power = 250
        predicted_pace = baseline_pace * (baseline_power / target_power)

    return predicted_pace * marathon_distance_km


def daily_training_signal(
    readiness_score: float | None,
    tsb: float,
    hrv_trend_pct: float,
    planned_workout: str,
    *,
    planned_detail: dict | None = None,
    sleep_score: float | None = None,
    hrv_value: float | None = None,
) -> dict:
    """Generate today's training recommendation from recovery + plan data.

    Args:
        readiness_score: Oura readiness (0-100)
        tsb: Training Stress Balance
        hrv_trend_pct: HRV % change over last 3 days
        planned_workout: workout type string (e.g. "steady aerobic")
        planned_detail: full plan row dict with duration, distance, power targets
        sleep_score: last night's Oura sleep score
        hrv_value: today's HRV in ms
    """
    # Classify workout difficulty
    hard_types = {"threshold", "tempo", "interval", "race", "long"}
    is_hard = planned_workout.lower() in hard_types if planned_workout else False

    # Build recovery context
    recovery = {}
    if readiness_score is not None:
        recovery["readiness"] = readiness_score
    if hrv_value is not None:
        recovery["hrv_ms"] = hrv_value
    if hrv_trend_pct != 0:
        recovery["hrv_trend_pct"] = round(hrv_trend_pct, 1)
    if sleep_score is not None:
        recovery["sleep_score"] = sleep_score
    recovery["tsb"] = round(tsb, 1)

    # Build plan context
    plan = {}
    if planned_workout:
        plan["workout_type"] = planned_workout
    if planned_detail:
        if planned_detail.get("planned_duration_min"):
            plan["duration_min"] = planned_detail["planned_duration_min"]
        if planned_detail.get("planned_distance_km"):
            plan["distance_km"] = planned_detail["planned_distance_km"]
        if planned_detail.get("target_power_min"):
            plan["power_min"] = planned_detail["target_power_min"]
        if planned_detail.get("target_power_max"):
            plan["power_max"] = planned_detail["target_power_max"]
        if planned_detail.get("workout_description"):
            plan["description"] = planned_detail["workout_description"]

    # Decision logic
    if readiness_score is not None and readiness_score < 60:
        rec = "rest"
        reason = f"Readiness is low ({readiness_score:.0f}). Prioritize recovery."
        alternatives = []
        if is_hard and planned_workout:
            alternatives.append(f"Shift {planned_workout} to tomorrow if possible")
            alternatives.append("If you must move, walk 30min only")
    elif readiness_score is not None and readiness_score < 70 and is_hard:
        rec = "modify"
        reason = f"Readiness moderate ({readiness_score:.0f}) but planned workout is hard ({planned_workout})."
        alternatives = [
            "Drop to easy run (keep power at recovery zone)",
            f"Push {planned_workout} to tomorrow if tomorrow is rest/easy",
            "Run as planned but cap at low end of power range, bail if HR drifts high",
        ]
    elif readiness_score is not None and readiness_score < 70 and tsb < -20:
        rec = "easy"
        reason = f"Readiness moderate ({readiness_score:.0f}) with high fatigue (TSB={tsb:.0f}). Go easy."
        alternatives = []
    elif hrv_trend_pct < -15:
        rec = "reduce_intensity"
        reason = f"HRV has declined {hrv_trend_pct:.0f}% over 3 days. Reduce intensity to prevent overtraining."
        alternatives = []
        if is_hard:
            alternatives.append(f"Swap {planned_workout} for easy run")
    else:
        rec = "follow_plan"
        reason = "Recovery looks good. Follow plan as written."
        alternatives = []

    return {
        "recommendation": rec,
        "reason": reason,
        "alternatives": alternatives,
        "recovery": recovery,
        "plan": plan,
    }


# --- Race reality check ---


def compute_cp_trend(cp_values: list[float], cp_dates: list, months: int = 3) -> dict:
    """Analyze CP trend direction and magnitude.

    Returns dict with: current, avg_recent, direction, months_flat, slope_per_month.
    """
    if not cp_values or len(cp_values) < 2:
        return {"current": cp_values[-1] if cp_values else None, "direction": "unknown"}

    current = cp_values[-1]

    # Use last N months of data
    cutoff = len(cp_values) - min(len(cp_values), months * 30)
    recent = cp_values[cutoff:]

    avg_recent = sum(recent) / len(recent)

    # Simple linear slope: (last - first) / count, normalized per ~30 entries (month)
    if len(recent) >= 2:
        slope = (recent[-1] - recent[0]) / max(len(recent) - 1, 1)
        slope_per_month = slope * 30  # approximate monthly change
    else:
        slope_per_month = 0.0

    # Determine direction
    if abs(slope_per_month) < 2:
        direction = "flat"
    elif slope_per_month > 0:
        direction = "rising"
    else:
        direction = "falling"

    # How many months has CP been within 3W of current?
    months_flat = 0
    for v in reversed(cp_values):
        if abs(v - current) <= 3:
            months_flat += 1
        else:
            break
    months_flat = months_flat // 30  # approximate

    return {
        "current": round(current, 1),
        "avg_recent": round(avg_recent, 1),
        "direction": direction,
        "slope_per_month": round(slope_per_month, 1),
        "months_flat": months_flat,
    }


def compute_threshold_trend(
    values: list[float],
    dates: list,
    months: int = 3,
    invert_direction: bool = False,
) -> dict:
    """Generalized threshold trend analysis — works for CP, LTHR, or pace.

    Same logic as compute_cp_trend, but with optional direction inversion
    for pace (lower = better).

    Args:
        values: threshold values over time
        dates: corresponding dates
        months: lookback period
        invert_direction: if True, lower values mean "rising" (for pace)
    """
    result = compute_cp_trend(values, dates, months)
    if invert_direction and result.get("direction") in ("rising", "falling"):
        # For pace, "rising" means getting slower (bad), so invert
        result["direction"] = (
            "rising" if result["direction"] == "falling" else "falling"
        )
    return result


def required_cp_for_time(
    target_time_sec: float,
    power_pace_pairs: list[tuple[float, float]],
    marathon_power_fraction: float = 0.80,
    marathon_distance_km: float = 42.195,
) -> float | None:
    """Estimate the CP needed to achieve a target marathon time.

    Inverts the predict_marathon_time logic: given target pace, what CP is needed?
    """
    if not power_pace_pairs:
        return None

    target_pace = target_time_sec / marathon_distance_km  # sec/km

    # From predict_marathon_time: pace = avg_k / (cp * fraction)
    # So: cp = avg_k / (target_pace * fraction)
    k_values = [power * pace for power, pace in power_pace_pairs]
    avg_k = sum(k_values) / len(k_values)

    needed_cp = avg_k / (target_pace * marathon_power_fraction)
    return round(needed_cp, 1)


# --- Pace-based prediction (Riegel formula) ---


def predict_time_from_pace(
    threshold_pace_sec_km: float,
    distance_km: float = 42.195,
) -> float:
    """Predict race time using Riegel's formula from threshold pace.

    Threshold pace is treated as ~10K race pace (1-hour effort).
    Riegel: T2 = T1 * (D2/D1)^1.06
    Source: https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html
    """
    reference_time = threshold_pace_sec_km * THRESHOLD_REFERENCE_KM
    return reference_time * (distance_km / THRESHOLD_REFERENCE_KM) ** RIEGEL_EXPONENT


def required_pace_for_time(
    target_time_sec: float,
    distance_km: float = 42.195,
) -> float:
    """Compute threshold pace needed to achieve a target time (inverse Riegel)."""
    reference_time = target_time_sec / (distance_km / THRESHOLD_REFERENCE_KM) ** RIEGEL_EXPONENT
    return reference_time / THRESHOLD_REFERENCE_KM


def race_honesty_check(
    current_cp: float | None,
    needed_cp: float | None,
    days_left: int | None,
    cp_trend: dict,
    predicted_time_sec: float | None,
    target_time_sec: float | None,
    threshold_inverted: bool = False,
) -> dict:
    """Generate an honest race readiness assessment.

    Args:
        threshold_inverted: If True, lower threshold = better (pace base).
            Gap logic is inverted so positive gap still means "behind".
    """
    if current_cp is None:
        return {"assessment": "Insufficient data for race assessment.", "severity": "unknown"}

    result: dict = {
        "current_cp": current_cp,
        "days_left": days_left,
        "predicted_time_sec": predicted_time_sec,
    }

    # No target time — simplified trend-based assessment
    if target_time_sec is None:
        direction = cp_trend.get("direction", "unknown")
        slope = cp_trend.get("slope_per_month", 0)
        severity = "on_track" if direction == "rising" else ("behind" if direction == "falling" else "close")
        result["severity"] = severity
        result["assessment"] = f"No target time set. Threshold trending {direction} ({slope:+.1f}/month)."
        if direction == "rising":
            result["trend_note"] = f"Trending up ({slope:+.1f}/month). Keep doing what you're doing."
        elif direction == "flat":
            result["trend_note"] = f"Trend is flat ({slope:+.1f}/month). Current plan may not be providing enough stimulus."
        elif direction == "falling":
            result["trend_note"] = f"Declining ({slope:+.1f}/month). Possible overtraining or insufficient quality sessions."
        return result

    result["needed_cp"] = needed_cp
    result["target_time_sec"] = target_time_sec

    # Threshold gap analysis
    # For pace base (inverted), higher value = slower = worse, so gap direction flips.
    if needed_cp and current_cp:
        gap_watts = (current_cp - needed_cp) if threshold_inverted else (needed_cp - current_cp)
        gap_pct = (gap_watts / current_cp) * 100
        result["cp_gap_watts"] = round(gap_watts, 1)
        result["cp_gap_pct"] = round(gap_pct, 1)

        if gap_watts <= 0:
            result["severity"] = "on_track"
            result["assessment"] = "Fitness supports the target. Focus on execution and taper."
        elif gap_watts <= 5 and days_left and days_left > 14:
            result["severity"] = "close"
            result["assessment"] = "Gap is small. Achievable with consistent training and a good taper."
        elif gap_pct > 10 or (days_left and days_left < 28):
            direction = cp_trend.get("direction", "unknown")
            months_flat = cp_trend.get("months_flat", 0)

            if direction == "flat" and months_flat >= 3:
                result["severity"] = "unlikely"
                result["assessment"] = (
                    f"Threshold has been flat for {months_flat} months. "
                    f"A {gap_pct:.0f}% change in {days_left} days is very unlikely."
                )
            elif gap_pct > 15:
                result["severity"] = "unlikely"
                result["assessment"] = (
                    f"Gap is {gap_pct:.0f}%. With {days_left} days left, this is too large to close. "
                    "A change this big typically requires 3-6 months of progressive work."
                )
            else:
                result["severity"] = "behind"
                result["assessment"] = (
                    f"Gap: {gap_pct:.0f}%. With {days_left} days left, closing this gap is very difficult."
                )

            # Suggest realistic alternatives
            if predicted_time_sec:
                comfortable = predicted_time_sec * 0.98  # slightly faster than predicted
                stretch = (predicted_time_sec + target_time_sec) / 2  # midpoint
                result["realistic_targets"] = {
                    "comfortable": round(comfortable),
                    "stretch": round(stretch),
                }
        else:
            result["severity"] = "behind"
            result["assessment"] = (
                f"Gap: {gap_pct:.0f}%. Achievable with focused threshold work, but requires consistency."
            )
    else:
        result["severity"] = "unknown"
        result["assessment"] = "Cannot determine gap — insufficient data."

    # Add trend interpretation
    direction = cp_trend.get("direction", "unknown")
    slope = cp_trend.get("slope_per_month", 0)
    if direction == "flat":
        result["trend_note"] = f"Threshold trend is flat ({slope:+.1f}/month). Current plan may not be providing enough stimulus."
    elif direction == "rising":
        result["trend_note"] = f"Threshold trending up ({slope:+.1f}/month). Keep doing what you're doing."
    elif direction == "falling":
        result["trend_note"] = f"Threshold declining ({slope:+.1f}/month). Possible overtraining or insufficient quality sessions."

    return result


# --- CP milestone tracking (no race date) ---

# Approximate marathon time at a given CP, assuming 80% fraction and current power-pace
_MARATHON_ESTIMATES = [
    (270, "~3:50"),
    (275, "~3:40"),
    (280, "~3:30"),
    (285, "~3:20"),
    (290, "~3:08"),
    (295, "~3:00"),
    (300, "~2:55"),
]


def cp_milestone_check(
    current_cp: float, target_cp: float, cp_trend: dict,
    threshold_inverted: bool = False,
) -> dict:
    """Generate threshold milestone progress assessment (no race date needed).

    Args:
        current_cp: latest threshold value (CP watts, LTHR bpm, or pace sec/km)
        target_cp: goal threshold value
        cp_trend: dict from compute_cp_trend / compute_threshold_trend
        threshold_inverted: if True, lower value = better (pace base)

    Returns dict with:
        cp_gap_watts, cp_gap_pct, severity, assessment, estimated_months, milestones
    """
    gap_watts = (current_cp - target_cp) if threshold_inverted else (target_cp - current_cp)
    gap_pct = (gap_watts / current_cp) * 100 if current_cp > 0 else 0

    slope = cp_trend.get("slope_per_month", 0)
    direction = cp_trend.get("direction", "unknown")

    # Estimate months to target based on trend slope
    if slope > 0.5:
        estimated_months = round(gap_watts / slope, 1) if gap_watts > 0 else 0
    elif gap_watts <= 0:
        estimated_months = 0
    else:
        estimated_months = None  # can't estimate — flat or declining

    # Determine severity (assessments use generic language — UI adds base-specific labels)
    if gap_watts <= 0:
        severity = "on_track"
        assessment = "Threshold has reached the target. Time to pick a race and execute."
    elif gap_watts <= 5:
        severity = "close"
        assessment = "Within striking distance of target. Achievable with continued threshold work."
    elif direction == "rising" and slope >= 2:
        severity = "on_track"
        eta_str = f" (~{estimated_months:.0f} months at current rate)" if estimated_months else ""
        assessment = f"Trending up at {slope:+.1f}/month. Gap: {gap_pct:.0f}%{eta_str}. Keep building."
    elif direction == "flat":
        severity = "behind"
        assessment = (
            f"Threshold has been flat. Gap: {gap_pct:.0f}%. "
            "Current training may not be providing enough stimulus."
        )
    elif direction == "falling":
        severity = "unlikely"
        assessment = (
            f"Threshold declining ({slope:+.1f}/month) — moving away from target. "
            "Re-evaluate training load and recovery."
        )
    else:
        severity = "behind"
        assessment = f"Gap: {gap_pct:.0f}%. Stay consistent with threshold work."

    # Build milestone list with marathon equivalents
    milestones = []
    for cp_val, marathon_est in _MARATHON_ESTIMATES:
        if current_cp - 5 < cp_val <= target_cp + 5:
            milestones.append({
                "cp": cp_val,
                "marathon": marathon_est,
                "reached": current_cp >= cp_val,
            })

    # Trend note
    if direction == "flat":
        trend_note = f"Threshold trend is flat ({slope:+.1f}/month). Need more stimulus."
    elif direction == "rising":
        trend_note = f"Threshold trending up ({slope:+.1f}/month). Keep it up."
    elif direction == "falling":
        trend_note = f"Threshold declining ({slope:+.1f}/month). Check recovery and training quality."
    else:
        trend_note = "Insufficient data to determine threshold trend."

    return {
        "cp_gap_watts": round(gap_watts, 1),
        "cp_gap_pct": round(gap_pct, 1),
        "severity": severity,
        "assessment": assessment,
        "estimated_months": estimated_months,
        "milestones": milestones,
        "trend_note": trend_note,
    }


# --- Training diagnosis ---


def diagnose_training(
    merged_activities: pd.DataFrame,
    splits: pd.DataFrame,
    cp_trend: dict,
    lookback_weeks: int = 6,
    current_date: date | None = None,
    base: TrainingBase = "power",
    threshold_value: float | None = None,
) -> dict:
    """Analyze recent training and diagnose issues holding back threshold progression.

    Uses split-level data for accurate intensity analysis. Supports power, HR, and pace bases.

    Args:
        merged_activities: merged activity data
        splits: per-split data (has activity_id, avg_power, avg_hr, duration_sec)
        cp_trend: dict from compute_cp_trend/compute_threshold_trend
        lookback_weeks: how many weeks to analyze
        current_date: override for testing (defaults to today)
        base: training base ("power", "hr", or "pace")
        threshold_value: threshold for the active base (CP watts, LTHR bpm, or threshold pace sec/km)
    """
    today = current_date or date.today()
    cutoff = today - timedelta(weeks=lookback_weeks)

    # Use provided threshold, or fall back to CP from trend
    current_cp = threshold_value or cp_trend.get("current") or 0

    result = {
        "lookback_weeks": lookback_weeks,
        "interval_power": {},
        "volume": {},
        "distribution": {},
        "consistency": {},
        "diagnosis": [],
        "suggestions": [],
    }

    if current_cp <= 0:
        result["diagnosis"].append({"type": "warning", "message": "No CP data available — cannot diagnose."})
        return result

    # Filter to lookback period
    if merged_activities.empty:
        result["diagnosis"].append({"type": "warning", "message": "No activity data in lookback period."})
        return result

    recent = merged_activities.copy()
    recent["_date"] = pd.to_datetime(recent["date"]).dt.date
    recent = recent[recent["_date"] >= cutoff]

    if recent.empty:
        result["diagnosis"].append({"type": "warning", "message": "No activities in the last {lookback_weeks} weeks."})
        return result

    # --- Volume analysis ---
    recent["_week"] = pd.to_datetime(recent["_date"]).apply(
        lambda d: d.isocalendar()[1]
    )
    recent["_year"] = pd.to_datetime(recent["_date"]).apply(
        lambda d: d.isocalendar()[0]
    )
    if "distance_km" in recent.columns:
        recent["_dist"] = pd.to_numeric(recent["distance_km"], errors="coerce").fillna(0)
    else:
        recent["_dist"] = 0.0

    weekly_vol = recent.groupby(["_year", "_week"]).agg(
        km=("_dist", "sum"),
        sessions=("_dist", "count"),
    )
    weekly_avg_km = round(float(weekly_vol["km"].mean()), 1) if not weekly_vol.empty else 0
    weeks_data = weekly_vol["km"].values

    if len(weeks_data) >= 2:
        first_half = weeks_data[: len(weeks_data) // 2].mean()
        second_half = weeks_data[len(weeks_data) // 2 :].mean()
        if second_half > first_half * 1.1:
            vol_trend = "increasing"
        elif second_half < first_half * 0.9:
            vol_trend = "decreasing"
        else:
            vol_trend = "stable"
    else:
        vol_trend = "insufficient_data"

    result["volume"] = {"weekly_avg_km": weekly_avg_km, "trend": vol_trend}

    # --- Consistency analysis ---
    weeks_with_gaps = int((weekly_vol["sessions"] < 3).sum()) if not weekly_vol.empty else 0
    # Find longest gap between activities
    activity_dates = sorted(recent["_date"].unique())
    longest_gap = 0
    for i in range(1, len(activity_dates)):
        gap = (activity_dates[i] - activity_dates[i - 1]).days
        longest_gap = max(longest_gap, gap)

    result["consistency"] = {
        "weeks_with_gaps": weeks_with_gaps,
        "longest_gap_days": longest_gap,
        "total_sessions": len(recent),
    }

    # --- Interval intensity analysis (from splits) ---
    # Determine which metric column to use based on training base
    if base == "hr":
        metric_col = "avg_hr"
    elif base == "pace":
        metric_col = "avg_pace_sec_km"  # may need to compute from distance/duration
    else:
        metric_col = "avg_power"

    if splits.empty or metric_col not in splits.columns:
        # Fall back to avg_power if the base metric isn't in splits
        if "avg_power" in splits.columns if not splits.empty else False:
            metric_col = "avg_power"
        else:
            result["diagnosis"].append({"type": "warning", "message": "No split data available — interval analysis skipped."})
            result["interval_power"] = {"max": None, "avg_work": None, "supra_cp_sessions": 0, "total_quality_sessions": 0}
            result["distribution"] = {"supra_cp": 0, "threshold": 0, "tempo": 0, "easy": 100}
            _add_diagnosis_items(result, current_cp)
            return result

    # Join splits with activity dates
    splits_copy = splits.copy()
    splits_copy[metric_col] = pd.to_numeric(splits_copy[metric_col], errors="coerce")
    splits_copy["duration_sec"] = pd.to_numeric(splits_copy["duration_sec"], errors="coerce")

    if "activity_id" in splits_copy.columns and "activity_id" in recent.columns:
        recent_ids = set(recent["activity_id"].astype(str).values)
        splits_copy["_aid"] = splits_copy["activity_id"].astype(str)
        recent_splits = splits_copy[splits_copy["_aid"].isin(recent_ids)]
    else:
        recent_splits = splits_copy

    # Identify "work" splits: duration 120-1800s, intensity > 80% of threshold
    # For pace, lower value = harder, so comparison is inverted
    if base == "pace" and current_cp > 0:
        work_threshold = current_cp * 1.14  # pace slower than 114% of threshold is easy
        work_splits = recent_splits[
            (recent_splits["duration_sec"] >= 120)
            & (recent_splits["duration_sec"] <= 1800)
            & (recent_splits[metric_col] < work_threshold)
            & (recent_splits[metric_col] > 0)
        ].copy()
    else:
        work_threshold = current_cp * 0.80
        work_splits = recent_splits[
            (recent_splits["duration_sec"] >= 120)
            & (recent_splits["duration_sec"] <= 1800)
            & (recent_splits[metric_col] > work_threshold)
        ].copy()

    max_interval = round(float(work_splits[metric_col].max()), 1) if not work_splits.empty else None
    avg_work = round(float(work_splits[metric_col].mean()), 1) if not work_splits.empty else None

    # Count sessions with supra-threshold splits
    if base == "pace" and current_cp > 0:
        supra_threshold = current_cp * 1.00  # at or faster than threshold pace
        if not work_splits.empty and "activity_id" in work_splits.columns:
            work_splits["_aid"] = work_splits["activity_id"].astype(str)
            session_best = work_splits.groupby("_aid")[metric_col].min()  # min pace = fastest
            supra_cp_sessions = int((session_best <= supra_threshold).sum())
            total_quality_sessions = len(session_best)
        else:
            supra_cp_sessions = 0
            total_quality_sessions = 0
    else:
        supra_threshold = current_cp * 0.98
        if not work_splits.empty and "activity_id" in work_splits.columns:
            work_splits["_aid"] = work_splits["activity_id"].astype(str)
            session_best = work_splits.groupby("_aid")[metric_col].max()
            supra_cp_sessions = int((session_best >= supra_threshold).sum())
            total_quality_sessions = int((session_best >= work_threshold).sum())
        else:
            supra_cp_sessions = 0
            total_quality_sessions = 0

    result["interval_power"] = {
        "max": max_interval,
        "avg_work": avg_work,
        "supra_cp_sessions": supra_cp_sessions,
        "total_quality_sessions": total_quality_sessions,
    }

    # --- Training distribution ---
    if "activity_id" in recent_splits.columns:
        if base == "pace":
            activity_best = recent_splits.groupby(recent_splits["activity_id"].astype(str))[metric_col].min()
        else:
            activity_best = recent_splits.groupby(recent_splits["activity_id"].astype(str))[metric_col].max()
    else:
        activity_best = pd.Series(dtype=float)

    total_activities = len(recent)
    if total_activities > 0 and not activity_best.empty and current_cp > 0:
        if base == "pace":
            # For pace: faster (lower) = harder intensity
            supra = int((activity_best <= current_cp * 1.00).sum())
            threshold_count = int(((activity_best > current_cp * 1.00) & (activity_best <= current_cp * 1.06)).sum())
            tempo = int(((activity_best > current_cp * 1.06) & (activity_best <= current_cp * 1.14)).sum())
        else:
            supra = int((activity_best >= current_cp * 0.98).sum())
            threshold_count = int(((activity_best >= current_cp * 0.92) & (activity_best < current_cp * 0.98)).sum())
            tempo = int(((activity_best >= current_cp * 0.85) & (activity_best < current_cp * 0.92)).sum())
        easy = total_activities - supra - threshold_count - tempo
        result["distribution"] = {
            "supra_cp": round(supra / total_activities * 100),
            "threshold": round(threshold_count / total_activities * 100),
            "tempo": round(tempo / total_activities * 100),
            "easy": round(easy / total_activities * 100),
        }
    else:
        result["distribution"] = {"supra_cp": 0, "threshold": 0, "tempo": 0, "easy": 100}

    _add_diagnosis_items(result, current_cp, base)
    return result


# Training base display labels for diagnosis text
_BASE_LABELS = {
    "power": {"threshold": "CP", "unit": "W", "metric": "power"},
    "hr": {"threshold": "LTHR", "unit": "bpm", "metric": "heart rate"},
    "pace": {"threshold": "threshold pace", "unit": "sec/km", "metric": "pace"},
}


def _add_diagnosis_items(result: dict, current_threshold: float, base: TrainingBase = "power") -> None:
    """Generate diagnosis findings and suggestions based on computed metrics."""
    diag = result["diagnosis"]
    suggestions = result["suggestions"]
    interval = result["interval_power"]
    volume = result["volume"]
    dist = result["distribution"]
    consistency = result["consistency"]

    labels = _BASE_LABELS.get(base, _BASE_LABELS["power"])
    t_name = labels["threshold"]
    t_unit = labels["unit"]

    # Volume assessment
    avg_km = volume.get("weekly_avg_km", 0)
    if avg_km >= 60:
        diag.append({"type": "positive", "message": f"Volume is strong at {avg_km} km/week."})
    elif avg_km >= 40:
        diag.append({"type": "neutral", "message": f"Volume is moderate at {avg_km} km/week."})
    else:
        diag.append({"type": "warning", "message": f"Volume is low at {avg_km} km/week — may limit {t_name} progression."})
        suggestions.append("Gradually increase weekly volume toward 50-60 km for better aerobic base.")

    if volume.get("trend") == "decreasing":
        diag.append({"type": "warning", "message": "Weekly volume is trending down."})

    # Consistency
    if consistency.get("longest_gap_days", 0) >= 7:
        diag.append({
            "type": "warning",
            "message": f"Training gap of {consistency['longest_gap_days']} days detected — breaks disrupt {t_name} adaptation.",
        })
    if consistency.get("weeks_with_gaps", 0) > 0:
        diag.append({
            "type": "neutral",
            "message": f"{consistency['weeks_with_gaps']} week(s) with fewer than 3 sessions.",
        })

    # Supra-threshold stimulus
    supra = interval.get("supra_cp_sessions", 0)
    quality = interval.get("total_quality_sessions", 0)
    max_val = interval.get("max")

    if supra == 0:
        diag.append({
            "type": "warning",
            "message": f"No sessions with intervals at or above {t_name} — this is the likely reason {t_name} is flat.",
        })
        if base == "power":
            suggestions.append(f"Add supra-{t_name} intervals: 5x4min @ {current_threshold:.0f}-{current_threshold * 1.05:.0f}{t_unit} every other week.")
        elif base == "hr":
            suggestions.append(f"Add threshold intervals: 3x10min @ {current_threshold:.0f}+ {t_unit} every other week.")
        else:
            suggestions.append(f"Add threshold intervals: 3x10min at or faster than {current_threshold:.0f} {t_unit}.")
    elif supra <= 1:
        diag.append({
            "type": "warning",
            "message": f"Only {supra} session with supra-{t_name} intervals — not enough stimulus.",
        })
        suggestions.append(f"Increase threshold sessions to 2-3 per {result['lookback_weeks']} weeks.")
    else:
        diag.append({
            "type": "positive",
            "message": f"{supra} sessions with supra-{t_name} intervals — good stimulus.",
        })

    if quality > 0 and max_val:
        if base == "pace":
            pct = current_threshold / max_val * 100 if max_val > 0 else 0
        else:
            pct = max_val / current_threshold * 100 if current_threshold > 0 else 0
        diag.append({
            "type": "positive" if pct >= 95 else "neutral",
            "message": f"Peak interval {labels['metric']}: {max_val:.0f}{t_unit} ({pct:.0f}% of {t_name}) across {quality} quality sessions.",
        })

    # Distribution check
    easy_pct = dist.get("easy", 0)
    hard_pct = dist.get("supra_cp", 0) + dist.get("threshold", 0)
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
