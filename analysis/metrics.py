"""Derived training metrics: load, fatigue, race prediction, training signal."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal, TypedDict

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from analysis.config import TrainingBase
    from analysis.providers.models import ThresholdEstimate

from analysis.zones import compute_zones, _DEFAULT_NAMES as _ZONE_DEFAULT_NAMES
from analysis.config import DEFAULT_ZONES

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


class HrvAnalysisResult(TypedDict):
    """Structured HRV analysis output."""
    today_ms: float | None
    today_ln: float
    baseline_mean_ln: float
    baseline_sd_ln: float
    threshold_ln: float
    swc_upper_ln: float
    rolling_mean_ln: float
    rolling_cv: float
    trend: Literal["stable", "improving", "declining"]


class RecoveryResult(TypedDict):
    """Structured recovery analysis output."""
    status: Literal["fresh", "normal", "fatigued", "insufficient_data"]
    hrv: HrvAnalysisResult | None
    sleep_score: float | None
    # Readiness is a separate platform-emitted score. It remains
    # informational and is never combined with HRV into a composite.
    readiness_score: float | None
    resting_hr: float | None
    rhr_trend: Literal["stable", "elevated", "low"] | None
    classification_reason: Literal[
        "missing_hrv", "insufficient_history", "zero_variance", "stale_hrv"
    ] | None


def analyze_recovery(
    hrv_series: list[float],
    today_hrv_ms: float | None = None,
    today_sleep: float | None = None,
    today_rhr: float | None = None,
    *,
    today_readiness: float | None = None,
    rhr_series: list[float] | None = None,
    rolling_days: int = 7,
    baseline_days: int = 30,
    cv_threshold: float = 10.0,
) -> RecoveryResult:
    """Analyze recovery with a documented Praxys adaptation of HRV research.

    Plews et al. (2012) supports monitoring ln(RMSSD) rolling means and
    variability, while Kiviniemi et al. (2007) supports individualized
    HRV-guided training adjustment. The exact status bands below are Praxys
    operational guardrails, not thresholds validated by either paper.

    References:
    - Plews et al. 2012, Eur J Appl Physiol, DOI: 10.1007/s00421-012-2354-4
    - Kiviniemi et al. 2007, Eur J Appl Physiol, DOI: 10.1007/s00421-007-0552-2

    Sleep, readiness, and RHR remain informational signals. They are not
    combined with HRV into a weighted score because no controlled study
    validates a specific weighting formula.

    Args:
        hrv_series: Historical RMSSD observations in ms, oldest first. The
            current observation must not be included.
        today_hrv_ms: Current RMSSD observation in ms.
        today_sleep: Sleep quality score (0-100), informational.
        today_rhr: Current resting heart rate in bpm, informational.
        today_readiness: Platform readiness score, informational.
        rhr_series: Historical RHR observations, oldest first. The current
            observation must not be included.
        rolling_days: Number of valid HRV observations in the rolling window.
        baseline_days: Maximum valid observations in the personal baseline.
        cv_threshold: Product caution threshold for rolling CV.
    """
    if rolling_days < 2:
        raise ValueError("rolling_days must be at least 2")
    if baseline_days < 2:
        raise ValueError("baseline_days must be at least 2")
    if cv_threshold <= 0:
        raise ValueError("cv_threshold must be positive")

    def insufficient_result(
        reason: Literal["missing_hrv", "insufficient_history"],
    ) -> RecoveryResult:
        return {
            "status": "insufficient_data",
            "hrv": None,
            "sleep_score": today_sleep,
            "readiness_score": today_readiness,
            "resting_hr": today_rhr,
            "rhr_trend": None,
            "classification_reason": reason,
        }

    history = [float(v) for v in hrv_series if v is not None and v > 0]
    today_valid = today_hrv_ms if (today_hrv_ms is not None and today_hrv_ms > 0) else None
    minimum_history = max(5, rolling_days)
    if today_valid is None:
        return insufficient_result("missing_hrv")
    if len(history) < minimum_history:
        return insufficient_result("insufficient_history")

    ln_history = [math.log(v) for v in history]
    today_ln = math.log(today_valid)

    baseline_pool = ln_history[-baseline_days:]
    baseline_n = len(baseline_pool)
    baseline_mean = sum(baseline_pool) / baseline_n
    baseline_sd = (
        sum((x - baseline_mean) ** 2 for x in baseline_pool) / (baseline_n - 1)
    ) ** 0.5

    recent = (ln_history + [today_ln])[-rolling_days:]
    rolling_mean = sum(recent) / len(recent)
    rolling_sd = (
        sum((x - rolling_mean) ** 2 for x in recent) / max(1, len(recent) - 1)
    ) ** 0.5
    rolling_cv = (rolling_sd / abs(rolling_mean) * 100) if rolling_mean != 0 else 0

    trend: Literal["stable", "improving", "declining"] = "stable"
    all_ln = ln_history + [today_ln]
    if baseline_sd > 0 and len(all_ln) >= rolling_days + 7:
        rolling_means = []
        for i in range(min(14, len(all_ln) - rolling_days + 1)):
            end = len(all_ln) - i
            start = end - rolling_days
            window = all_ln[start:end]
            rolling_means.append(sum(window) / len(window))
        rolling_means.reverse()
        if len(rolling_means) >= 3:
            n = len(rolling_means)
            x_mean = (n - 1) / 2
            y_mean = sum(rolling_means) / n
            numerator = sum(
                (i - x_mean) * (value - y_mean)
                for i, value in enumerate(rolling_means)
            )
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            slope = numerator / denominator if denominator > 0 else 0
            # ESTIMATE -- Plews supports rolling-trend monitoring but not this
            # numeric slope cutoff. Praxys uses half an SD over 14 observations
            # as a conservative operational change band.
            swc_per_observation = 0.5 * baseline_sd / 14
            if slope > swc_per_observation:
                trend = "improving"
            elif slope < -swc_per_observation:
                trend = "declining"

    threshold_ln = baseline_mean - baseline_sd
    swc_upper_ln = baseline_mean + 0.5 * baseline_sd
    status: Literal["fresh", "normal", "fatigued", "insufficient_data"] = "normal"
    classification_reason: Literal["zero_variance"] | None = None
    if baseline_sd <= 1e-12:
        # Identical history does not provide a defensible dispersion estimate.
        # Preserve the observation for display, but suppress HRV classification.
        status = "insufficient_data"
        classification_reason = "zero_variance"
    elif today_ln < threshold_ln:
        status = "fatigued"
    elif today_ln > swc_upper_ln:
        status = "fresh"

    # ESTIMATE -- Plews tracked CV trends rather than validating one universal
    # cutoff. The active recovery theory supplies this product caution band.
    if rolling_cv > cv_threshold and status == "fresh":
        status = "normal"
    if trend == "declining" and status == "fresh":
        status = "normal"

    hrv_result: HrvAnalysisResult = {
        "today_ms": today_valid,
        "today_ln": round(today_ln, 2),
        "baseline_mean_ln": round(baseline_mean, 2),
        "baseline_sd_ln": round(baseline_sd, 2),
        "threshold_ln": round(threshold_ln, 2),
        "swc_upper_ln": round(swc_upper_ln, 2),
        "rolling_mean_ln": round(rolling_mean, 2),
        "rolling_cv": round(rolling_cv, 1),
        "trend": trend,
    }

    result: RecoveryResult = {
        "status": status,
        "hrv": hrv_result,
        "sleep_score": today_sleep,
        "readiness_score": today_readiness,
        "resting_hr": today_rhr,
        "rhr_trend": None,
        "classification_reason": classification_reason,
    }

    valid_rhr_history = [
        float(v) for v in (rhr_series or []) if v is not None and v > 0
    ]
    if len(valid_rhr_history) >= 5 and today_rhr is not None and today_rhr > 0:
        rhr_recent = valid_rhr_history[-baseline_days:]
        rhr_mean = sum(rhr_recent) / len(rhr_recent)
        rhr_sd = (
            sum((x - rhr_mean) ** 2 for x in rhr_recent)
            / max(1, len(rhr_recent) - 1)
        ) ** 0.5
        if rhr_sd > 0:
            if today_rhr > rhr_mean + rhr_sd:
                result["rhr_trend"] = "elevated"
            elif today_rhr < rhr_mean - rhr_sd:
                result["rhr_trend"] = "low"
            else:
                result["rhr_trend"] = "stable"

    return result

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


def has_sufficient_load_history(
    data_days: int,
    ctl_time_constant_days: int,
) -> bool:
    """Return whether modeled load balance has enough history for display.

    Banister-style impulse-response models motivate the CTL time constant, but
    they do not validate a universal minimum-history cutoff for product display.
    """
    if data_days < 0 or ctl_time_constant_days <= 0:
        return False
    # ESTIMATE -- one active CTL time constant is a Praxys stability guardrail,
    # not a physiologically validated sufficiency threshold.
    return data_days >= ctl_time_constant_days


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
    *,
    k_male: float = 1.92,
    k_female: float = 1.67,
) -> float:
    """Banister TRIMP (HR-based load).

    Exponential weighting of HR reserve:
        TRIMP = minutes × HRR_frac × 0.64 × exp(k × HRR_frac)

    Sex-specific ``k`` reflects the blood-lactate → HR response (males have
    a steeper curve). Defaults 1.92 / 1.67 from Banister's 1991 formulation;
    theories may override via YAML params.

    Source: Banister EW (1991), "Modeling elite athletic performance." In
    *Physiological Testing of Elite Athletes*, Human Kinetics, pp. 403-424.
    See also Morton, Fitz-Clarke & Banister (1990),
    https://doi.org/10.1152/jappl.1990.69.3.1171 for the impulse-response
    model that consumes TRIMP.
    """
    if duration_sec <= 0 or max_hr <= rest_hr:
        return 0.0
    duration_min = duration_sec / 60
    delta_ratio = (avg_hr - rest_hr) / (max_hr - rest_hr)
    delta_ratio = max(0.0, min(1.0, delta_ratio))
    k = k_male if sex == "male" else k_female
    return duration_min * delta_ratio * 0.64 * math.exp(k * delta_ratio)


def compute_rtss(
    duration_sec: float,
    avg_pace_sec_km: float,
    threshold_pace_sec_km: float,
) -> float:
    """Running TSS from normalized graded pace (pace-based load).

    rTSS = (duration/3600) × (threshold_pace / actual_pace)² × 100

    Faster pace = lower sec/km, so threshold/actual > 1 when running hard.
    Mirrors TrainingPeaks' rTSS definition (Skiba / McGregor), the pace-side
    equivalent of power-based TSS.

    Source: Skiba PF, "Calculation of Power Output and Quantification of
    Training Stress in Distance Runners" (PhysFarm technical note),
    https://www.physfarm.com/rtss.pdf — see also TrainingPeaks' rTSS
    explainer https://www.trainingpeaks.com/learn/articles/running-training-stress-score/.
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


# ``recovery`` is an active low-power workout in the Stryd taxonomy.
REST_WORKOUT_TYPES = frozenset({"rest", "off"})

# ESTIMATE -- conservative source-label taxonomy for sessions that should be
# protected when recovery is impaired. This is not an intensity model;
# exact interval intensity still comes from activity splits elsewhere.
HARD_WORKOUT_TYPES = frozenset({
    "fartlek",
    "hill_repeat",
    "hill_repeats",
    "interval",
    "intervals",
    "long",
    "long_run",
    "race",
    "repetition",
    "repetitions",
    "speed",
    "tempo",
    "threshold",
    "time_trial",
    "vo2_max",
    "vo2max",
})


def _normalize_workout_type(workout_type: object) -> str:
    """Normalize common source separators without changing label meaning."""
    return "_".join(str(workout_type or "").strip().lower().replace("-", " ").split())


def is_rest_workout(workout_type: object) -> bool:
    """Return whether a planned workout is a passive rest/off day."""
    return _normalize_workout_type(workout_type) in REST_WORKOUT_TYPES


def is_hard_workout(workout_type: object) -> bool:
    """Return whether a planned workout uses a known demanding-session label."""
    return _normalize_workout_type(workout_type) in HARD_WORKOUT_TYPES


def daily_training_signal(
    recovery_analysis: RecoveryResult,
    tsb: float | None,
    planned_workout: str,
    *,
    planned_detail: dict | None = None,
    signal_thresholds: dict | None = None,
    recovery_thresholds: dict | None = None,
    hrv_only: bool = False,
) -> dict:
    """Generate today's deterministic recommendation from recovery and plan.

    Stable reason and alternative codes let each client localize the guidance
    without changing its decision or scientific meaning.

    Args:
        recovery_analysis: Output of analyze_recovery().
        tsb: Training Stress Balance from the selected load model, or ``None``
            until the model has enough history for display and decisions.
        planned_workout: Workout type string (for example, `tempo`).
        planned_detail: Full plan row with duration, distance, and targets.
        signal_thresholds: Selected load-theory signal parameters.
        recovery_thresholds: Selected recovery-theory parameters.
        hrv_only: If true, sleep and RHR never modify the HRV decision.
    """
    st = signal_thresholds or {}
    # ESTIMATE -- Banister PMC motivates the TSB construct, but no controlled
    # study defines a universal daily cutoff. The selected load theory owns this
    # operational threshold. https://doi.org/10.1152/jappl.1990.69.3.1171
    fatigue_thresh = st.get("tsb_high_fatigue", -20)
    cv_threshold = (recovery_thresholds or {}).get("cv_threshold", 10)

    workout_type = _normalize_workout_type(planned_workout)
    is_unscheduled = not workout_type
    is_rest_day = is_rest_workout(workout_type)
    is_hard = is_hard_workout(workout_type)

    status = recovery_analysis.get("status", "normal")
    hrv_info = recovery_analysis.get("hrv") or {}
    hrv_trend = hrv_info.get("trend", "stable")
    hrv_cv = hrv_info.get("rolling_cv", 0)
    sleep_score = recovery_analysis.get("sleep_score")
    readiness_score = recovery_analysis.get("readiness_score")
    today_hrv = hrv_info.get("today_ms")
    rhr_trend = recovery_analysis.get("rhr_trend")

    recovery = {"tsb": round(tsb, 1) if tsb is not None else None}
    if today_hrv is not None:
        recovery["hrv_ms"] = today_hrv
    if hrv_trend != "stable":
        if hrv_info.get("baseline_mean_ln") and hrv_info.get("today_ln"):
            # ln difference approximates fractional change for small deviations.
            hrv_pct = (hrv_info["today_ln"] - hrv_info["baseline_mean_ln"]) * 100
            recovery["hrv_trend_pct"] = round(hrv_pct, 1)
    if sleep_score is not None:
        recovery["sleep_score"] = sleep_score
    if readiness_score is not None:
        recovery["readiness"] = readiness_score

    plan = {}
    if workout_type:
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

    if is_unscheduled:
        rec = "unscheduled"
        if status == "fatigued":
            reason_code = "unscheduled_hrv_caution"
            reason_args = {}
            reason = (
                "No workout is scheduled, and HRV is below your personal "
                "caution band. Keep the day restorative rather than adding a hard session."
            )
            alternatives = ["Rest, walk, or do gentle mobility"]
            alternative_codes = [{"code": "restorative_movement", "args": {}}]
        elif status == "normal" and tsb is not None and tsb < fatigue_thresh:
            reason_code = "unscheduled_high_load"
            reason_args = {"tsb": round(tsb)}
            reason = (
                f"No workout is scheduled, and modeled load balance is low (TSB {tsb:.0f}). "
                "Avoid adding intensity today."
            )
            alternatives = ["Keep any optional movement easy and short"]
            alternative_codes = [{"code": "optional_easy_short", "args": {}}]
        else:
            reason_code = "unscheduled_open"
            reason_args = {}
            reason = "No workout is scheduled. Add a session only if it fits your broader plan."
            alternatives = []
            alternative_codes = []

    elif is_rest_day:
        rec = "rest"
        reason_code = "rest_scheduled"
        reason_args = {}
        reason = "Rest day scheduled. Follow the plan and prioritize recovery."
        alternatives = []
        alternative_codes = []

    elif status == "insufficient_data":
        rec = "follow_plan"
        reason_args = {}
        classification_reason = recovery_analysis.get("classification_reason")
        if recovery_analysis.get("hrv_is_stale"):
            reason_code = "hrv_stale"
            reason = (
                "The latest HRV reading is out of date. Follow the plan without "
                "an HRV-based recovery adjustment."
            )
        elif classification_reason == "zero_variance":
            reason_code = "hrv_zero_variance"
            reason = (
                "Recent HRV observations have no measurable variation, so Praxys "
                "cannot form a reliable recovery band yet. Follow the plan without "
                "an HRV-based adjustment."
            )
        elif classification_reason == "insufficient_history":
            reason_code = "hrv_history_insufficient"
            reason = (
                "More historical HRV observations are needed before Praxys can form "
                "a personal recovery band. Follow the plan without an HRV-based adjustment."
            )
        else:
            reason_code = "hrv_unavailable"
            reason = (
                "Recovery requires current HRV data. Connect or sync an HRV-capable "
                "device to receive recovery suggestions."
            )
        alternatives = []
        alternative_codes = []

    elif status == "fatigued":
        reason_args = {}
        if is_hard:
            rec = "rest"
            reason_code = "hrv_below_hard"
            reason = (
                "HRV is below your personal caution band. Treat this as a recovery "
                "signal, not a diagnosis."
            )
            alternatives = [
                "Make today a full recovery day and reassess the hard session tomorrow",
            ]
            alternative_codes = [{"code": "full_recovery_reassess", "args": {}}]
        else:
            rec = "easy"
            reason_code = "hrv_below_easy"
            reason = "HRV is below your personal caution band. Keep today easy to support recovery."
            alternatives = []
            alternative_codes = []

    elif (
        status == "normal"
        and is_hard
        and tsb is not None
        and tsb < fatigue_thresh
    ):
        rec = "modify"
        reason_code = "high_load_hard"
        reason_args = {"tsb": round(tsb), "workout": planned_workout}
        reason = (
            f"HRV is within your personal reference band, but modeled load balance is low (TSB {tsb:.0f}). "
            "Modify the hard session."
        )
        alternatives = [
            "Drop to easy run (keep power in recovery zone)",
            f"Push {planned_workout} to tomorrow if tomorrow is rest/easy",
            "Run as planned but cap at low end of power range",
        ]
        alternative_codes = [
            {"code": "drop_to_easy", "args": {}},
            {"code": "push_to_tomorrow_if_easy", "args": {"workout": planned_workout}},
            {"code": "cap_low_power", "args": {}},
        ]

    elif hrv_trend == "declining":
        if is_hard:
            rec = "reduce_intensity"
            reason_code = "hrv_declining_hard"
            reason_args = {"workout": planned_workout}
            reason = (
                "HRV rolling mean is declining. Reduce intensity as a conservative "
                "coaching adjustment."
            )
            alternatives = [f"Swap {planned_workout} for easy run"]
            alternative_codes = [{"code": "swap_for_easy", "args": {"workout": planned_workout}}]
        else:
            rec = "easy"
            reason_code = "hrv_declining_easy"
            reason_args = {}
            reason = "HRV rolling mean is lower than its prior window. Stay easy today."
            alternatives = []
            alternative_codes = []

    # ESTIMATE -- Plews supports tracking ln(RMSSD) CV, but the selected
    # threshold is a product caution band, not a validated universal cutoff.
    elif hrv_cv > cv_threshold and is_hard:
        rec = "modify"
        reason_code = "hrv_variability_high"
        reason_args = {"cv": round(hrv_cv), "workout": planned_workout}
        reason = (
            f"HRV variability is high (CV {hrv_cv:.0f}%), above the selected "
            "coaching caution threshold."
        )
        alternatives = [
            "Drop intensity by one zone",
            f"Push {planned_workout} to tomorrow",
        ]
        alternative_codes = [
            {"code": "drop_one_zone", "args": {}},
            {"code": "push_to_tomorrow", "args": {"workout": planned_workout}},
        ]

    # ESTIMATE -- 55 is a conservative platform-score heuristic. Sleep remains
    # secondary because no validated weighting with HRV exists.
    elif not hrv_only and sleep_score is not None and sleep_score < 55 and is_hard:
        rec = "modify"
        reason_code = "sleep_low_hard"
        reason_args = {"sleep": round(sleep_score)}
        reason = f"Sleep score is low ({sleep_score:.0f}). Consider reducing today's intensity."
        alternatives = [
            "Run as planned but monitor how you feel",
            "Shorten the session if fatigue develops",
        ]
        alternative_codes = [
            {"code": "proceed_monitor_body", "args": {}},
            {"code": "shorten_if_fatigued", "args": {}},
        ]

    elif not hrv_only and rhr_trend == "elevated" and is_hard:
        rec = "modify"
        reason_code = "resting_hr_elevated_hard"
        reason_args = {}
        reason = (
            "Resting heart rate is elevated above your baseline. This can be a "
            "caution signal, but it is not diagnostic."
        )
        alternatives = [
            "Run easy instead",
            "Proceed but monitor heart-rate drift during the session",
        ]
        alternative_codes = [
            {"code": "run_easy", "args": {}},
            {"code": "monitor_hr_drift", "args": {}},
        ]

    else:
        rec = "follow_plan"
        reason_args = {}
        if status == "fresh":
            reason_code = "hrv_above_baseline"
            reason = "HRV is above your personal reference band. Follow the plan as written."
        else:
            reason_code = "recovery_normal"
            reason = "Recovery signals are within their recent reference bands. Follow the plan as written."
        alternatives = []
        alternative_codes = []

    return {
        "recommendation": rec,
        "reason": reason,
        "reason_code": reason_code,
        "reason_args": reason_args,
        "alternatives": alternatives,
        "alternative_codes": alternative_codes,
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
    riegel_exponent: float | None = None,
) -> float:
    """Predict race time using Riegel's formula from threshold pace.

    Threshold pace is treated as ~10K race pace (1-hour effort).
    Riegel: T2 = T1 * (D2/D1)^exponent
    Source: https://runningwritings.com/2024/01/critical-speed-guide-for-runners.html
    """
    exponent = riegel_exponent or RIEGEL_EXPONENT
    reference_time = threshold_pace_sec_km * THRESHOLD_REFERENCE_KM
    return reference_time * (distance_km / THRESHOLD_REFERENCE_KM) ** exponent


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


def compute_distribution_match_pct(
    distribution: list[dict], evidence_complete: bool,
) -> int | None:
    """Return Bray-Curtis similarity between actual and target zone shares.

    The score is descriptive: 100 means the observed and configured
    distributions are identical, while 0 means they do not overlap. It is
    unavailable when the intensity evidence is incomplete or any zone lacks a
    target. Formula: Bray & Curtis (1957), DOI: 10.2307/1942268.
    """
    if not evidence_complete or not distribution:
        return None

    actual: list[float] = []
    target: list[float] = []
    for zone in distribution:
        actual_value = zone.get("actual_pct")
        target_value = zone.get("target_pct")
        if (
            not isinstance(actual_value, (int, float))
            or not isinstance(target_value, (int, float))
            or not math.isfinite(float(actual_value))
            or not math.isfinite(float(target_value))
            or actual_value < 0
            or target_value < 0
        ):
            return None
        actual.append(float(actual_value))
        target.append(float(target_value))

    denominator = sum(actual) + sum(target)
    if denominator <= 0:
        return None
    similarity = 1.0 - sum(
        abs(actual_value - target_value)
        for actual_value, target_value in zip(actual, target)
    ) / denominator
    return round(max(0.0, min(1.0, similarity)) * 100)


def compute_load_compliance_pct(
    actual_load: list[float | None],
    planned_load: list[float | None],
    evidence_complete: bool = True,
    eligible_weeks: list[bool] | None = None,
) -> int | None:
    """Return Praxys weekly actual-to-planned load compliance percentage.

    Weeks without a positive planned load are excluded, and at least two
    comparable completed weeks are required. Estimated or otherwise incomplete
    evidence must pass ``evidence_complete=False`` or an ``eligible_weeks`` mask.
    This is a Praxys-defined operational execution ratio, not a physiological
    quality, safety, recovery, or readiness score.
    """
    if not evidence_complete:
        return None

    ratios: list[float] = []
    for index, (actual, planned) in enumerate(zip(actual_load, planned_load)):
        if (
            eligible_weeks is not None
            and (index >= len(eligible_weeks) or not eligible_weeks[index])
        ):
            continue
        if (
            not isinstance(actual, (int, float))
            or not isinstance(planned, (int, float))
            or not math.isfinite(float(actual))
            or not math.isfinite(float(planned))
            or actual < 0
            or planned <= 0
        ):
            continue
        ratios.append(float(actual) / float(planned) * 100)
    # ESTIMATE -- two comparable weeks is a product data-sufficiency guardrail,
    # not a validated physiological threshold.
    if len(ratios) < 2:
        return None
    return round(sum(ratios) / len(ratios))

# --- Training diagnosis ---


def diagnose_training(
    merged_activities: pd.DataFrame,
    splits: pd.DataFrame,
    cp_trend: dict,
    current_date: date,
    lookback_weeks: int = 6,
    base: TrainingBase = "power",
    threshold_value: float | None = None,
    zone_boundaries: list[float] | None = None,
    zone_names: list[str] | None = None,
    target_distribution: list[float] | None = None,
    theory_name: str | None = None,
    samples: pd.DataFrame | None = None,
    diagnosis_params: dict | None = None,
) -> dict:
    """Analyze recent training and diagnose issues holding back threshold progression.

    Uses sufficiently complete per-second streams for 1-second zone resolution;
    otherwise falls back to split-duration weighting. Power intensity never uses
    activity averages. Training-intensity distribution is expressed as time in
    zone, following Seiler (2006):
    https://doi.org/10.1111/j.1600-0838.2004.00418.x

    Work-split and volume cutoffs come from the selected load theory. They are
    operational coaching heuristics, not validated outputs of the Banister model.
    Supports power, HR, and pace bases.

    Args:
        merged_activities: merged activity data
        splits: per-split data (has activity_id, avg_power, avg_hr, duration_sec)
        cp_trend: dict from compute_cp_trend/compute_threshold_trend
        lookback_weeks: how many weeks to analyze
        current_date: request-scoped date anchoring the analysis window
        base: training base ("power", "hr", or "pace")
        threshold_value: threshold for the active base (CP watts, LTHR bpm, or threshold pace sec/km)
        zone_boundaries: zone boundary fractions (N boundaries -> N+1 zones); defaults to Coggan 5-zone
        zone_names: names for each zone (must be len(boundaries)+1); defaults per base
        target_distribution: target fraction for each zone (must sum to ~1.0); optional
        theory_name: name of the zone theory (e.g. "Seiler Polarized 3-Zone"); optional
        samples: per-second stream DataFrame with columns activity_id, power_watts,
            hr_bpm, pace_sec_km (from activity_samples table); optional
        diagnosis_params: selected load theory's work-split duration and weekly
            volume thresholds; optional
    """
    today = current_date
    cutoff = today - timedelta(days=lookback_weeks * 7 - 1)
    params = diagnosis_params or {}
    work_split_min_sec = int(params.get("work_split_min_sec", 120))
    work_split_max_sec = int(params.get("work_split_max_sec", 1800))
    volume_strong_km = float(params.get("volume_strong_km", 60))
    volume_moderate_km = float(params.get("volume_moderate_km", 40))

    # Use provided threshold, or fall back to CP from trend.
    current_cp = threshold_value or cp_trend.get("current") or 0
    default_bounds = zone_boundaries or DEFAULT_ZONES.get(base, DEFAULT_ZONES["power"])
    default_theory_name = theory_name or (
        "Coggan 5-Zone" if len(default_bounds) == 4 else f"{len(default_bounds) + 1}-Zone"
    )

    result = {
        "lookback_weeks": lookback_weeks,
        "interval_power": {
            "max": None,
            "avg_work": None,
            "supra_cp_sessions": None,
            "total_quality_sessions": None,
            "data_available": False,
            "evidence_complete": False,
            "activities_with_intensity_data": 0,
            "activities_expected": 0,
        },
        "volume": {"weekly_avg_km": 0, "trend": "insufficient_data"},
        "distribution": [],
        "consistency": {
            "weeks_with_gaps": 0,
            "longest_gap_days": 0,
            "total_sessions": 0,
        },
        "diagnosis": [],
        "suggestions": [],
        "zone_ranges": [],
        "theory_name": default_theory_name,
        "data_meta": {
            "distribution_resolution": "unavailable",
            "distribution_complete": False,
            "distribution_coverage_pct": 0,
        },
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
    recent = recent[
        (recent["_date"] >= cutoff) & (recent["_date"] <= today)
    ]

    if recent.empty:
        result["diagnosis"].append({"type": "warning", "message": f"No activities in the last {lookback_weeks} weeks."})
        return result

    # --- Volume analysis ---
    # Rolling seven-day buckets include zero-activity weeks. Omitting empty
    # weeks would inflate the stated N-week average and hide consistency gaps.
    recent["_week_bucket"] = recent["_date"].apply(
        lambda activity_date: (today - activity_date).days // 7
    )
    if "distance_km" in recent.columns:
        recent["_dist"] = pd.to_numeric(
            recent["distance_km"], errors="coerce",
        ).fillna(0)
    else:
        recent["_dist"] = 0.0

    weekly_vol = recent.groupby("_week_bucket").agg(
        km=("_dist", "sum"),
        sessions=("_dist", "size"),
    ).reindex(range(lookback_weeks), fill_value=0)
    weekly_avg_km = round(float(weekly_vol["km"].mean()), 1)
    # Oldest bucket first so the trend comparison preserves chronology.
    weeks_data = weekly_vol.sort_index(ascending=False)["km"].to_numpy()

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

    sample_columns = {"power": "power_watts", "hr": "hr_bpm", "pace": "pace_sec_km"}
    sample_col = sample_columns.get(base, "power_watts")
    recent_ids = (
        set(recent["activity_id"].astype(str).values)
        if "activity_id" in recent.columns
        else set()
    )
    expected_duration_by_aid: dict[str, float] = {}
    if "activity_id" in recent.columns and "duration_sec" in recent.columns:
        activity_durations = pd.to_numeric(
            recent["duration_sec"], errors="coerce",
        )
        duration_frame = pd.DataFrame({
            "_aid": recent["activity_id"].astype(str),
            "_duration": activity_durations,
        })
        duration_frame = duration_frame[
            duration_frame["_duration"].notna()
            & (duration_frame["_duration"] > 0)
        ]
        expected_duration_by_aid.update(
            duration_frame.groupby("_aid")["_duration"].max().to_dict()
        )

    has_sample_metric = False
    if (
        samples is not None
        and not samples.empty
        and sample_col in samples.columns
        and "activity_id" in samples.columns
        and "t_sec" in samples.columns
        and recent_ids
    ):
        candidate_samples = samples[samples["activity_id"].astype(str).isin(recent_ids)].copy()
        candidate_samples[sample_col] = pd.to_numeric(
            candidate_samples[sample_col], errors="coerce",
        )
        has_sample_metric = bool(
            (candidate_samples[sample_col].notna() & (candidate_samples[sample_col] > 0)).any()
        )

    if (splits.empty or metric_col not in splits.columns) and not has_sample_metric:
        result["interval_power"] = {
            "max": None,
            "avg_work": None,
            "supra_cp_sessions": None,
            "total_quality_sessions": None,
            "data_available": False,
            "evidence_complete": False,
            "activities_with_intensity_data": 0,
            "activities_expected": 0,
        }
        bounds = zone_boundaries or DEFAULT_ZONES.get(base, DEFAULT_ZONES["power"])
        n_zones = len(bounds) + 1
        names = (
            zone_names
            if zone_names and len(zone_names) == n_zones
            else _ZONE_DEFAULT_NAMES.get(base, [f"Zone {i + 1}" for i in range(n_zones)])
        )
        targets = (
            [round(target * 100) for target in target_distribution]
            if target_distribution and len(target_distribution) == n_zones
            else [None] * n_zones
        )

        abs_bounds = [round(current_cp * factor) for factor in bounds]
        zone_time = [0.0] * n_zones
        total_time = 0.0
        covered_activity_ids: set[str] = set()
        # Activity-average power is intentionally never used for intensity
        # analysis because warmup, recovery, and cooldown dilute intervals.
        act_metric_col = (
            metric_col
            if base in {"hr", "pace"} and metric_col in recent.columns
            else None
        )
        if act_metric_col and "duration_sec" in recent.columns:
            for _, row in recent.iterrows():
                value = pd.to_numeric(row.get(act_metric_col), errors="coerce")
                duration = pd.to_numeric(row.get("duration_sec"), errors="coerce")
                if (
                    pd.isna(value) or value <= 0
                    or pd.isna(duration) or duration <= 0
                ):
                    continue
                total_time += duration
                if "activity_id" in recent.columns:
                    covered_activity_ids.add(str(row.get("activity_id")))
                if base == "pace":
                    ratio = current_cp / value if value > 0 else 0
                    inverted_bounds = [1.0 / boundary for boundary in bounds]
                    zone_idx = 0
                    for j in range(len(inverted_bounds) - 1, -1, -1):
                        if ratio >= inverted_bounds[j]:
                            zone_idx = j + 1
                            break
                else:
                    zone_idx = 0
                    for j, boundary in enumerate(abs_bounds):
                        if value >= boundary:
                            zone_idx = j + 1
                        else:
                            break
                zone_time[min(zone_idx, n_zones - 1)] += duration

        result["distribution"] = [
            {
                "name": names[i],
                "actual_pct": (
                    round(zone_time[i] / total_time * 100) if total_time > 0 else 0
                ),
                "target_pct": targets[i],
            }
            for i in range(n_zones)
        ]
        result["zone_ranges"] = compute_zones(
            base,
            current_cp,
            bounds,
            names if zone_names else None,
        )
        result["theory_name"] = theory_name or (
            "Coggan 5-Zone" if len(bounds) == 4 else f"{n_zones}-Zone"
        )
        if base == "power":
            message = "Power-zone distribution unavailable without split-level power data."
        elif total_time > 0:
            message = (
                "Zone distribution based on activity averages because split-level "
                "data is unavailable."
            )
        else:
            message = "Zone distribution unavailable because no valid intensity data exists."
        expected_total = sum(expected_duration_by_aid.values())
        coverage_pct = (
            min(100, round(total_time / expected_total * 100))
            if expected_total > 0 else 0
        )
        # Activity averages erase interval structure. They can support a coarse
        # HR/pace display, but never complete distribution-match evidence.
        distribution_complete = False
        result["interval_power"].update({
            "activities_with_intensity_data": len(covered_activity_ids),
            "activities_expected": len(recent_ids),
        })
        result["data_meta"] = {
            "distribution_resolution": "activity_averages" if total_time > 0 else "unavailable",
            "distribution_complete": distribution_complete,
            "distribution_coverage_pct": coverage_pct,
        }
        result["diagnosis"].append({"type": "neutral", "message": message})
        _add_diagnosis_items(
            result, current_cp, cp_trend.get("direction", "unknown"), base,
            diagnosis_params=params,
        )
        return result
    # Join splits with activity dates. Sample-only activities intentionally use
    # an empty split frame so their per-second data can still drive distribution.
    if splits.empty or metric_col not in splits.columns:
        splits_copy = pd.DataFrame(columns=["activity_id", metric_col, "duration_sec"])
    else:
        splits_copy = splits.copy()
        splits_copy[metric_col] = pd.to_numeric(splits_copy[metric_col], errors="coerce")
        if "duration_sec" in splits_copy.columns:
            splits_copy["duration_sec"] = pd.to_numeric(
                splits_copy["duration_sec"], errors="coerce",
            )
        else:
            splits_copy["duration_sec"] = np.nan

    if "activity_id" in splits_copy.columns and recent_ids:
        splits_copy["_aid"] = splits_copy["activity_id"].astype(str)
        recent_splits = splits_copy[splits_copy["_aid"].isin(recent_ids)]
    else:
        recent_splits = splits_copy.iloc[0:0].copy()

    positive_duration_splits = recent_splits[
        recent_splits["duration_sec"].notna()
        & (recent_splits["duration_sec"] > 0)
    ]
    if "_aid" in positive_duration_splits.columns:
        split_duration_by_aid = (
            positive_duration_splits.groupby("_aid")["duration_sec"].sum().to_dict()
        )
        for aid, duration in split_duration_by_aid.items():
            expected_duration_by_aid.setdefault(aid, float(duration))

    # ESTIMATE -- 90% per-activity duration coverage is a conservative Praxys
    # data-quality gate, not an exercise-science threshold.
    duration_coverage_ratio = 0.90
    valid_interval_splits = recent_splits[
        recent_splits[metric_col].notna()
        & (recent_splits[metric_col] > 0)
        & recent_splits["duration_sec"].notna()
        & (recent_splits["duration_sec"] > 0)
    ].copy()
    valid_split_aids = (
        set(valid_interval_splits["_aid"].unique())
        if "_aid" in valid_interval_splits.columns else set()
    )
    valid_split_duration_by_aid = (
        valid_interval_splits.groupby("_aid")["duration_sec"].sum().to_dict()
        if "_aid" in valid_interval_splits.columns else {}
    )
    interval_data_available = bool(valid_split_aids)
    interval_evidence_complete = bool(
        recent_ids
        and all(
            expected_duration_by_aid.get(aid, 0) > 0
            and float(valid_split_duration_by_aid.get(aid, 0))
            >= expected_duration_by_aid[aid] * duration_coverage_ratio
            for aid in recent_ids
        )
    )

    # Identify work splits using the selected load theory's operational window.
    # ESTIMATE -- 80% of power/HR threshold and 114% of threshold pace are
    # conservative product filters for excluding warmup and recovery splits;
    # they are not validated universal definitions of interval work.
    # For pace, lower value = harder, so comparison is inverted.
    if base == "pace" and current_cp > 0:
        work_threshold = current_cp * 1.14
        work_splits = valid_interval_splits[
            (valid_interval_splits["duration_sec"] >= work_split_min_sec)
            & (valid_interval_splits["duration_sec"] <= work_split_max_sec)
            & (valid_interval_splits[metric_col] < work_threshold)
        ].copy()
    else:
        work_threshold = current_cp * 0.80
        work_splits = valid_interval_splits[
            (valid_interval_splits["duration_sec"] >= work_split_min_sec)
            & (valid_interval_splits["duration_sec"] <= work_split_max_sec)
            & (valid_interval_splits[metric_col] > work_threshold)
        ].copy()

    if work_splits.empty:
        max_interval = None
    elif base == "pace":
        # Lower sec/km is faster, so the peak pace is the minimum value.
        max_interval = round(float(work_splits[metric_col].min()), 1)
    else:
        max_interval = round(float(work_splits[metric_col].max()), 1)
    avg_work = round(float(work_splits[metric_col].mean()), 1) if not work_splits.empty else None
    supra_cp_sessions: int | None = None
    total_quality_sessions: int | None = None

    # Count sessions only when valid split evidence exists. Missing evidence is
    # unavailable, not proof that the athlete completed zero quality sessions.
    if interval_data_available:
        supra_cp_sessions = 0
        total_quality_sessions = 0
        if base == "pace" and current_cp > 0:
            supra_threshold = current_cp
            if not work_splits.empty and "activity_id" in work_splits.columns:
                work_splits["_aid"] = work_splits["activity_id"].astype(str)
                session_best = work_splits.groupby("_aid")[metric_col].min()
                supra_cp_sessions = int((session_best <= supra_threshold).sum())
                total_quality_sessions = len(session_best)
        else:
            supra_threshold = current_cp
            if not work_splits.empty and "activity_id" in work_splits.columns:
                work_splits["_aid"] = work_splits["activity_id"].astype(str)
                session_best = work_splits.groupby("_aid")[metric_col].max()
                supra_cp_sessions = int((session_best >= supra_threshold).sum())
                total_quality_sessions = int((session_best >= work_threshold).sum())

    result["interval_power"] = {
        "max": max_interval,
        "avg_work": avg_work,
        "supra_cp_sessions": supra_cp_sessions,
        "total_quality_sessions": total_quality_sessions,
        "data_available": interval_data_available,
        "evidence_complete": interval_evidence_complete,
        "activities_with_intensity_data": len(valid_split_aids),
        "activities_expected": len(recent_ids),
    }

    # --- Training distribution (dynamic zones) ---
    bounds = zone_boundaries or DEFAULT_ZONES.get(base, DEFAULT_ZONES["power"])
    n_zones = len(bounds) + 1
    names = zone_names if (zone_names and len(zone_names) == n_zones) else _ZONE_DEFAULT_NAMES.get(base, [f"Zone {i+1}" for i in range(n_zones)])
    targets = [round(t * 100) for t in target_distribution] if target_distribution and len(target_distribution) == n_zones else [None] * n_zones

    # Build per-activity threshold lookup for date-relative zone classification.
    # For power base, use cp_estimate from each activity's date rather than a single
    # current CP — a session at 240W when CP was 260W is Threshold, not VO2max.
    _cp_by_aid: dict[str, float] = {}
    if base == "power" and "activity_id" in recent.columns and "cp_estimate" in recent.columns:
        cp_col = pd.to_numeric(recent["cp_estimate"], errors="coerce")
        for aid, cp_val in zip(recent["activity_id"].astype(str), cp_col):
            if pd.notna(cp_val) and cp_val > 0:
                _cp_by_aid[aid] = float(cp_val)

    # For pace, lower value = harder, so compare ratio (threshold/value)
    # against the reciprocal of the boundary fractions.
    inv_bounds = [1.0 / b if b > 0 else 0.0 for b in bounds] if base == "pace" else []

    def _classify(val: float, act_cp: float) -> int:
        if act_cp <= 0 or val <= 0:
            return 0
        if base == "pace":
            ratio = act_cp / val
            for i in range(len(inv_bounds) - 1, -1, -1):
                if ratio >= inv_bounds[i]:
                    return i + 1
            return 0
        ratio = val / act_cp
        for i in range(len(bounds) - 1, -1, -1):
            if ratio >= bounds[i]:
                return i + 1
        return 0

    # Time-in-zone computation. Target distributions (Coggan / Seiler 2006 /
    # Filipas 2022) are fractions of training TIME per zone.
    #
    # Sample streams are weighted by their timestamp cadence rather than row
    # count. Sparse streams fall back to split durations so an isolated sample
    # cannot stand in for a whole workout.
    # ESTIMATE -- a <=5-second median cadence is a conservative Praxys
    # data-quality gate, not an exercise-science threshold.
    sample_max_cadence_sec = 5.0
    aids_with_complete_samples: set[str] = set()
    complete_sample_seconds_by_aid: dict[str, float] = {}
    recent_samples_filtered = pd.DataFrame()
    if (
        samples is not None
        and not samples.empty
        and sample_col in samples.columns
        and "activity_id" in samples.columns
        and "t_sec" in samples.columns
    ):
        s = samples.copy()
        s["_aid"] = s["activity_id"].astype(str)
        s[sample_col] = pd.to_numeric(s[sample_col], errors="coerce")
        s["_t_sec"] = pd.to_numeric(s["t_sec"], errors="coerce")
        s = s[
            s["_aid"].isin(recent_ids) & s["_t_sec"].notna()
        ].sort_values(["_aid", "_t_sec"])
        if not s.empty:
            next_t = s.groupby("_aid", sort=False)["_t_sec"].shift(-1)
            delta = next_t - s["_t_sec"]
            positive_delta = delta.where(delta > 0)
            cadence_by_aid = positive_delta.groupby(s["_aid"], sort=False).median()
            s["_cadence_sec"] = s["_aid"].map(cadence_by_aid).fillna(1.0)
            s["_sample_weight_sec"] = np.where(
                delta > 0,
                np.minimum(delta, s["_cadence_sec"] * 2),
                s["_cadence_sec"],
            )
            s["_metric_valid"] = (
                s[sample_col].notna()
                & (s[sample_col] > 0)
                & np.isfinite(s[sample_col])
                & (s["_cadence_sec"] <= sample_max_cadence_sec)
            )
            sample_seconds = (
                s[s["_metric_valid"]]
                .groupby("_aid")["_sample_weight_sec"]
                .sum()
            )
            aids_with_complete_samples = {
                aid
                for aid, covered_seconds in sample_seconds.items()
                if expected_duration_by_aid.get(aid, 0) > 0
                and float(covered_seconds)
                >= expected_duration_by_aid[aid] * duration_coverage_ratio
            }
            complete_sample_seconds_by_aid = {
                str(aid): float(sample_seconds[aid])
                for aid in aids_with_complete_samples
            }
            recent_samples_filtered = s[
                s["_metric_valid"]
                & s["_aid"].isin(aids_with_complete_samples)
            ].copy()

    # Vectorized array form of the scalar ``_classify`` above —
    # bit-for-bit equivalent on every supported base, exercised by
    # tests/test_training_cold_start_perf.py against a scalar oracle.
    def _classify_array(
        val_arr: np.ndarray, cp_arr: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (zone_idx, valid_mask) for arrays of values and per-row CP."""
        valid = (
            (val_arr > 0) & (cp_arr > 0)
            & np.isfinite(val_arr) & np.isfinite(cp_arr)
        )
        zone_idx = np.zeros(val_arr.shape[0], dtype=np.int64)
        if base == "pace" and inv_bounds:
            ratio = np.zeros_like(val_arr, dtype=float)
            np.divide(cp_arr, val_arr, out=ratio, where=valid)
            # Preserve the original loop's first-match-from-high-index
            # behavior bit-for-bit so any pace-base output stays stable.
            unfilled = valid.copy()
            for i in range(len(inv_bounds) - 1, -1, -1):
                mask = unfilled & (ratio >= inv_bounds[i])
                zone_idx[mask] = i + 1
                unfilled[mask] = False
        elif bounds:
            ratio = np.zeros_like(val_arr, dtype=float)
            np.divide(val_arr, cp_arr, out=ratio, where=valid)
            # ``bounds`` is increasing; np.searchsorted with side='right'
            # matches the original "highest i such that ratio >= bounds[i]"
            # loop exactly: ratio < bounds[0] → 0, bounds[k-1] ≤ ratio <
            # bounds[k] → k, ratio ≥ bounds[-1] → n_bounds.
            searched = np.searchsorted(
                np.asarray(bounds, dtype=float), ratio, side="right",
            )
            zone_idx = np.where(valid, searched, 0).astype(np.int64)
        return zone_idx, valid

    def _build_per_row_cp(aid_arr: np.ndarray) -> np.ndarray:
        """Resolve per-activity CP via _cp_by_aid; default to current_cp."""
        if not _cp_by_aid:
            return np.full(aid_arr.shape[0], float(current_cp), dtype=float)
        cp_map = pd.Series(_cp_by_aid, dtype=float)
        return (
            cp_map.reindex(aid_arr)
            .fillna(float(current_cp))
            .to_numpy(dtype=float)
        )

    zone_time = [0.0] * n_zones
    total_time = 0.0
    sample_time = 0.0
    split_time = 0.0
    covered_activity_ids: set[str] = set()
    covered_seconds_by_aid: dict[str, float] = {}

    # Timestamp-weighted sample path.
    if not recent_samples_filtered.empty:
        s = recent_samples_filtered
        val_arr = pd.to_numeric(s[sample_col], errors="coerce").to_numpy(dtype=float)
        aid_arr = s["activity_id"].astype(str).to_numpy()
        cp_arr = _build_per_row_cp(aid_arr)
        zone_idx, valid = _classify_array(val_arr, cp_arr)
        if valid.any():
            sample_weights = s["_sample_weight_sec"].to_numpy(dtype=float)
            weighted = np.bincount(
                zone_idx[valid],
                weights=sample_weights[valid],
                minlength=n_zones,
            )
            for z in range(n_zones):
                zone_time[z] += float(weighted[z])
            sample_time = float(sample_weights[valid].sum())
            total_time += sample_time
            covered_activity_ids.update(aid_arr[valid].tolist())
            covered_seconds_by_aid.update(complete_sample_seconds_by_aid)

    # Split-duration fallback for activities that have no samples.
    if not recent_splits.empty:
        fallback_splits = recent_splits[
            ~recent_splits["activity_id"].astype(str).isin(aids_with_complete_samples)
        ] if aids_with_complete_samples else recent_splits
        if not fallback_splits.empty:
            val_arr = pd.to_numeric(
                fallback_splits[metric_col], errors="coerce",
            ).to_numpy(dtype=float)
            dur_arr = pd.to_numeric(
                fallback_splits.get("duration_sec", 0), errors="coerce",
            ).to_numpy(dtype=float)
            aid_arr = fallback_splits["activity_id"].astype(str).to_numpy()
            cp_arr = _build_per_row_cp(aid_arr)
            zone_idx, valid = _classify_array(val_arr, cp_arr)
            valid &= (dur_arr > 0) & np.isfinite(dur_arr)
            if valid.any():
                weighted = np.bincount(
                    zone_idx[valid],
                    weights=dur_arr[valid],
                    minlength=n_zones,
                )
                for z in range(n_zones):
                    zone_time[z] += float(weighted[z])
                split_time = float(dur_arr[valid].sum())
                total_time += split_time
                covered_activity_ids.update(aid_arr[valid].tolist())
                valid_durations = pd.Series(
                    dur_arr[valid],
                    index=aid_arr[valid],
                    dtype=float,
                ).groupby(level=0).sum()
                for aid, duration in valid_durations.items():
                    covered_seconds_by_aid[str(aid)] = (
                        covered_seconds_by_aid.get(str(aid), 0.0)
                        + float(duration)
                    )

    if sample_time > 0 and split_time > 0:
        resolution = "mixed"
    elif sample_time > 0:
        resolution = "samples"
    elif split_time > 0:
        resolution = "splits"
    else:
        resolution = "unavailable"

    if total_time > 0:
        result["distribution"] = [
            {
                "name": names[i],
                "actual_pct": round(zone_time[i] / total_time * 100),
                "target_pct": targets[i],
            }
            for i in range(n_zones)
        ]
    else:
        result["distribution"] = [
            {"name": names[i], "actual_pct": 0, "target_pct": targets[i]}
            for i in range(n_zones)
        ]

    expected_total = sum(expected_duration_by_aid.values())
    coverage_pct = (
        min(100, round(total_time / expected_total * 100))
        if expected_total > 0 else 0
    )
    every_activity_complete = bool(
        recent_ids
        and all(
            expected_duration_by_aid.get(aid, 0) > 0
            and covered_seconds_by_aid.get(aid, 0)
            >= expected_duration_by_aid[aid] * duration_coverage_ratio
            for aid in recent_ids
        )
    )
    distribution_complete = bool(
        total_time > 0
        and recent_ids
        and recent_ids.issubset(expected_duration_by_aid)
        and recent_ids.issubset(covered_activity_ids)
        and every_activity_complete
    )
    result["data_meta"] = {
        "distribution_resolution": resolution,
        "distribution_complete": distribution_complete,
        "distribution_coverage_pct": coverage_pct,
    }
    result["zone_ranges"] = compute_zones(base, current_cp, bounds, names if zone_names else None)
    result["theory_name"] = theory_name or ("Coggan 5-Zone" if len(bounds) == 4 else f"{n_zones}-Zone")

    _add_diagnosis_items(
        result, current_cp, cp_trend.get("direction", "unknown"), base,
        diagnosis_params=params,
    )
    return result


# Training base display labels for diagnosis text
_BASE_LABELS = {
    "power": {"threshold": "CP", "unit": "W", "metric": "power"},
    "hr": {"threshold": "LTHR", "unit": "bpm", "metric": "heart rate"},
    "pace": {"threshold": "threshold pace", "unit": "sec/km", "metric": "pace"},
}


def _add_diagnosis_items(
    result: dict,
    current_threshold: float,
    threshold_trend: str,
    base: TrainingBase = "power",
    diagnosis_params: dict | None = None,
) -> None:
    """Add evidence-qualified observations to a training diagnosis."""
    params = diagnosis_params or {}
    volume_moderate_km = float(params.get("volume_moderate_km", 40))
    volume_strong_km = float(params.get("volume_strong_km", 60))

    diag = result["diagnosis"]
    suggestions = result["suggestions"]
    interval = result["interval_power"]
    volume = result["volume"]
    dist = result["distribution"]
    consistency = result["consistency"]

    labels = _BASE_LABELS.get(base, _BASE_LABELS["power"])
    threshold_name = labels["threshold"]
    threshold_unit = labels["unit"]

    avg_km = volume.get("weekly_avg_km", 0)
    if avg_km >= volume_strong_km:
        diag.append({
            "type": "positive",
            "message": f"Weekly volume averaged {avg_km} km, above the configured {volume_strong_km:g} km reference.",
        })
    elif avg_km >= volume_moderate_km:
        diag.append({
            "type": "neutral",
            "message": f"Weekly volume averaged {avg_km} km, within the configured reference range.",
        })
    else:
        diag.append({
            "type": "neutral",
            "message": f"Weekly volume averaged {avg_km} km, below the configured {volume_moderate_km:g} km reference.",
        })

    if volume.get("trend") == "decreasing":
        diag.append({"type": "neutral", "message": "Weekly volume decreased across the analysis window."})

    if consistency.get("longest_gap_days", 0) >= 7:
        diag.append({
            "type": "warning",
            "message": f"A training gap of {consistency['longest_gap_days']} days was recorded.",
        })
    if consistency.get("weeks_with_gaps", 0) > 0:
        diag.append({
            "type": "neutral",
            "message": f"{consistency['weeks_with_gaps']} week(s) contained fewer than 3 sessions.",
        })

    supra = interval.get("supra_cp_sessions")
    quality = interval.get("total_quality_sessions")
    peak_value = interval.get("max")
    evidence_complete = interval.get("evidence_complete", False)

    if not interval.get("data_available", False):
        diag.append({
            "type": "neutral",
            "message": "Interval-quality assessment is unavailable without valid split-level intensity data.",
        })
    elif not evidence_complete:
        observed = interval.get("activities_with_intensity_data", 0)
        expected = interval.get("activities_expected", 0)
        diag.append({
            "type": "neutral",
            "message": (
                "Interval-quality conclusions are withheld because split-level "
                f"intensity evidence covers {observed} of {expected} activities."
            ),
        })
    else:
        if supra == 0:
            message = f"No intervals at or above {threshold_name} were observed in the complete split evidence."
            if threshold_trend in {"flat", "decreasing"}:
                message += (
                    f" The {threshold_name} trend was {threshold_trend}; these observations "
                    "coincide but do not establish causation."
                )
                suggestions.append(
                    f"If improving {threshold_name} is the current goal, review whether threshold-specific work fits the broader plan and current recovery."
                )
            diag.append({"type": "neutral", "message": message})
        elif supra is not None:
            diag.append({
                "type": "neutral",
                "message": f"{supra} session(s) included intervals at or above {threshold_name}.",
            })

        if quality and peak_value:
            if base == "pace":
                percentage = current_threshold / peak_value * 100 if peak_value > 0 else 0
            else:
                percentage = peak_value / current_threshold * 100 if current_threshold > 0 else 0
            diag.append({
                "type": "neutral",
                "message": (
                    f"Peak observed interval {labels['metric']}: {peak_value:.0f}{threshold_unit} "
                    f"({percentage:.0f}% of {threshold_name}) across {quality} quality sessions."
                ),
            })

    data_meta = result.get("data_meta", {})
    distribution_available = data_meta.get("distribution_resolution") != "unavailable"
    distribution_complete = data_meta.get("distribution_complete", False)
    coverage_pct = data_meta.get("distribution_coverage_pct", 0)
    if distribution_available and not distribution_complete:
        if data_meta.get("distribution_resolution") == "activity_averages":
            message = (
                "Zone-distribution conclusions are withheld because activity "
                "averages do not preserve interval-level zone exposure."
            )
        else:
            message = (
                "Zone-distribution conclusions are withheld because intensity "
                f"evidence covers {coverage_pct}% of expected activity duration "
                "and at least one activity is below the 90% coverage gate."
            )
        diag.append({"type": "neutral", "message": message})
    elif distribution_complete and isinstance(dist, list) and dist:
        has_targets = any(zone.get("target_pct") is not None for zone in dist)
        if has_targets:
            for zone in dist:
                target = zone.get("target_pct")
                actual = zone.get("actual_pct", 0)
                if target is not None and abs(actual - target) > 5:
                    direction = "above" if actual > target else "below"
                    diag.append({
                        "type": "warning",
                        "message": (
                            f"{zone['name']} was {actual}%, {direction} the configured "
                            f"{target}% target by more than 5 percentage points."
                        ),
                    })
        else:
            easy_pct = dist[0].get("actual_pct", 0)
            hard_pct = sum(zone.get("actual_pct", 0) for zone in dist[2:])
            diag.append({
                "type": "neutral",
                "message": (
                    f"Observed distribution was {easy_pct}% in {dist[0]['name']} and "
                    f"{hard_pct}% across zones 3 and above; no target distribution is configured."
                ),
            })