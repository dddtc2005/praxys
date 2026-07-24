import math

import pandas as pd
import pytest
from datetime import date
from analysis.metrics import (
    compute_distribution_match_pct,
    compute_ewma_load,
    compute_load_compliance_pct,
    compute_tsb,
    has_sufficient_load_history,
    predict_marathon_time,
    analyze_recovery,
    daily_training_signal,
    cp_milestone_check,
    diagnose_training,
)


def test_compute_distribution_match_pct_requires_complete_evidence():
    distribution = [
        {"actual_pct": 70, "target_pct": 80},
        {"actual_pct": 20, "target_pct": 5},
        {"actual_pct": 10, "target_pct": 15},
    ]

    assert compute_distribution_match_pct(distribution, True) == 85
    assert compute_distribution_match_pct(distribution, False) is None


def test_compute_distribution_match_pct_requires_every_target():
    distribution = [
        {"actual_pct": 80, "target_pct": 80},
        {"actual_pct": 20, "target_pct": None},
    ]

    assert compute_distribution_match_pct(distribution, True) is None


def test_compute_load_compliance_pct_is_descriptive_mean_ratio():
    assert compute_load_compliance_pct([80, 120], [100, 100]) == 100
    assert compute_load_compliance_pct([150, 90, 30], [100, 100, 0]) == 120
    assert compute_load_compliance_pct([150, 30], [100, 0]) is None
    assert compute_load_compliance_pct([80, 120], [100, 100], False) is None
    assert compute_load_compliance_pct(
        [80, 120, 100],
        [100, 100, 100],
        eligible_weeks=[True, True, False],
    ) == 100
    assert compute_load_compliance_pct([30], [0]) is None


def test_load_history_sufficiency_uses_active_ctl_window():
    assert has_sufficient_load_history(41, 42) is False
    assert has_sufficient_load_history(42, 42) is True
    assert has_sufficient_load_history(20, 20) is True
    assert has_sufficient_load_history(42, 0) is False


def test_daily_signal_preserves_unavailable_tsb_without_load_decision():
    recovery = {
        "status": "normal",
        "hrv": {"trend": "stable", "rolling_cv": 2.0},
        "sleep_score": None,
        "readiness_score": None,
        "rhr_trend": None,
    }

    signal = daily_training_signal(recovery, tsb=None, planned_workout="interval")

    assert signal["recommendation"] == "follow_plan"
    assert signal["recovery"]["tsb"] is None


def test_compute_ewma_load():
    daily_rss = pd.Series([80, 90, 85, 0, 70, 95, 88])
    atl = compute_ewma_load(daily_rss, time_constant=7)
    assert len(atl) == 7
    assert atl.iloc[-1] > 0


def test_compute_tsb():
    daily_rss = pd.Series([80] * 50)
    ctl = compute_ewma_load(daily_rss, time_constant=42)
    atl = compute_ewma_load(daily_rss, time_constant=7)
    tsb = compute_tsb(ctl, atl)
    assert abs(tsb.iloc[-1]) < 20


def test_predict_marathon_time():
    time_sec = predict_marathon_time(cp_watts=280, recent_power_pace_pairs=[(250, 255)])
    assert time_sec is not None
    assert 9000 < time_sec < 14400


def test_predict_marathon_time_no_data():
    time_sec = predict_marathon_time(cp_watts=280, recent_power_pace_pairs=[])
    assert time_sec is not None


def _make_hrv_series(baseline_ms: float = 50.0, n: int = 30) -> list[float]:
    """Generate a stable HRV series around a baseline for testing."""
    import random
    random.seed(42)
    return [baseline_ms + random.gauss(0, 5) for _ in range(n)]


def test_analyze_recovery_fresh():
    """HRV well above baseline → fresh status."""
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=65.0)
    assert analysis["status"] == "fresh"
    assert analysis["hrv"] is not None
    assert analysis["hrv"]["today_ln"] > analysis["hrv"]["baseline_mean_ln"]


def test_analyze_recovery_fatigued():
    """HRV well below baseline → fatigued status."""
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=30.0)
    assert analysis["status"] == "fatigued"
    assert analysis["hrv"]["today_ln"] < analysis["hrv"]["threshold_ln"]


def test_analyze_recovery_insufficient_data():
    """Too few data points → insufficient_data status, no HRV analysis."""
    analysis = analyze_recovery([50, 48, 52])
    assert analysis["status"] == "insufficient_data"
    assert analysis["hrv"] is None
    assert analysis["sleep_score"] is None
    assert analysis["resting_hr"] is None


def test_analyze_recovery_zero_variance_is_indeterminate():
    """Identical history must not fabricate a usable reference band."""
    analysis = analyze_recovery([50.0] * 14, today_hrv_ms=50.0)

    assert analysis["status"] == "insufficient_data"
    assert analysis["classification_reason"] == "zero_variance"
    assert analysis["hrv"] is not None
    assert analysis["hrv"]["baseline_sd_ln"] == 0


def test_analyze_recovery_rejects_invalid_window_configuration():
    with pytest.raises(ValueError, match="baseline_days"):
        analyze_recovery([50.0] * 7, today_hrv_ms=50.0, baseline_days=1)


def test_daily_signal_explains_zero_variance_baseline():
    analysis = analyze_recovery([50.0] * 14, today_hrv_ms=50.0)

    signal = daily_training_signal(analysis, tsb=0, planned_workout="easy")

    assert signal["recommendation"] == "follow_plan"
    assert signal["reason_code"] == "hrv_zero_variance"
    assert "no measurable variation" in signal["reason"]


def test_analyze_recovery_insufficient_hrv_preserves_context():
    """Sleep, readiness, and RHR remain visible when HRV is insufficient."""
    analysis = analyze_recovery(
        [50, 48, 52],
        today_sleep=76,
        today_readiness=81,
        today_rhr=54,
    )

    assert analysis["status"] == "insufficient_data"
    assert analysis["hrv"] is None
    assert analysis["sleep_score"] == 76
    assert analysis["readiness_score"] == 81
    assert analysis["resting_hr"] == 54


def test_daily_training_signal_rest():
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=30.0)  # fatigued
    signal = daily_training_signal(analysis, tsb=-10, planned_workout="tempo")
    assert signal["recommendation"] in ["rest", "easy"]
    assert "hrv" in signal["reason"].lower()


def test_daily_training_signal_hard_aliases_keep_rest_alternative_safe():
    """Known demanding labels must all protect a fatigued athlete."""
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=30.0)

    for workout_type in (
        "long",
        "long_run",
        "long run",
        "intervals",
        "time trial",
        "hill-repeats",
        "hill_repeat",
        "fartlek",
        "repetition",
        "repetitions",
    ):
        signal = daily_training_signal(
            analysis,
            tsb=-10,
            planned_workout=workout_type,
        )

        assert signal["recommendation"] == "rest", workout_type
        assert signal["alternatives"] == [
            "Make today a full recovery day and reassess the hard session tomorrow",
        ]


def test_daily_training_signal_follow_plan():
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=60.0, today_sleep=85)  # fresh
    signal = daily_training_signal(analysis, tsb=5, planned_workout="tempo")
    assert signal["recommendation"] == "follow_plan"


def test_daily_training_signal_unscheduled_day_is_neutral():
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=60.0, today_sleep=85)

    signal = daily_training_signal(analysis, tsb=5, planned_workout="")

    assert signal["recommendation"] == "unscheduled"
    assert signal["reason"] == (
        "No workout is scheduled. Add a session only if it fits your broader plan."
    )
    assert signal["alternatives"] == []
    assert signal["plan"] == {}


def test_daily_training_signal_unscheduled_day_respects_recovery_and_load():
    """Missing plan data must not invite intensity under restrictive signals."""
    series = _make_hrv_series(50.0, 30)
    fatigued = analyze_recovery(series, today_hrv_ms=30.0)

    recovery_signal = daily_training_signal(
        fatigued,
        tsb=-5,
        planned_workout="",
    )
    assert recovery_signal["recommendation"] == "unscheduled"
    assert "restorative" in recovery_signal["reason"].lower()
    assert recovery_signal["alternatives"] == [
        "Rest, walk, or do gentle mobility",
    ]

    normal = analyze_recovery(series, today_hrv_ms=50.0)
    load_signal = daily_training_signal(
        normal,
        tsb=-25,
        planned_workout="",
    )
    assert load_signal["recommendation"] == "unscheduled"
    assert "avoid adding intensity" in load_signal["reason"].lower()
    assert load_signal["alternatives"] == [
        "Keep any optional movement easy and short",
    ]


def test_daily_training_signal_rest_aliases_stay_rest_when_fatigued():
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=30.0)

    for workout_type in ("rest", "off"):
        signal = daily_training_signal(
            analysis,
            tsb=-10,
            planned_workout=workout_type,
            planned_detail={"workout_description": "Full recovery day."},
        )

        assert signal["recommendation"] == "rest"
        assert signal["reason"] == (
            "Rest day scheduled. Follow the plan and prioritize recovery."
        )
        assert signal["alternatives"] == []
        assert signal["plan"] == {
            "workout_type": workout_type,
            "description": "Full recovery day.",
        }


def test_daily_training_signal_recovery_run_remains_active():
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=60.0, today_sleep=85)

    signal = daily_training_signal(
        analysis,
        tsb=5,
        planned_workout="recovery",
        planned_detail={"planned_duration_min": 30},
    )

    assert signal["recommendation"] == "follow_plan"
    assert signal["plan"] == {"workout_type": "recovery", "duration_min": 30}


def test_daily_training_signal_hrv_warning():
    # Create a declining HRV series to trigger trend warning
    series = [55 - i * 0.8 for i in range(30)]  # declining from 55 to ~31
    analysis = analyze_recovery(series, today_hrv_ms=32.0)
    signal = daily_training_signal(analysis, tsb=-5, planned_workout="interval")
    assert signal["recommendation"] in ["rest", "easy", "reduce_intensity"]
    assert "hrv" in signal["reason"].lower() or "declining" in signal["reason"].lower()


def test_analyze_recovery_cv_override():
    """High CV (>10%) should downgrade fresh → normal."""
    # Create a series with high variability in the last 7 days
    stable = [50.0] * 23
    volatile = [30.0, 70.0, 25.0, 75.0, 35.0, 65.0, 40.0]  # high CV
    series = stable + volatile
    # Today is high (would be "fresh" by threshold alone)
    analysis = analyze_recovery(series, today_hrv_ms=70.0)
    # CV should be high from the volatile week
    assert analysis["hrv"] is not None
    assert analysis["hrv"]["rolling_cv"] > 10
    # Status should NOT be "fresh" due to CV override
    assert analysis["status"] != "fresh"


def test_analyze_recovery_cv_threshold_is_configurable():
    """The selected recovery theory owns the operational CV threshold."""
    stable = [50.0] * 23
    volatile = [30.0, 70.0, 25.0, 75.0, 35.0, 65.0, 40.0]
    analysis = analyze_recovery(
        stable + volatile,
        today_hrv_ms=70.0,
        cv_threshold=100.0,
    )

    assert analysis["hrv"]["rolling_cv"] > 10
    assert analysis["status"] == "fresh"


def test_daily_training_signal_uses_recovery_cv_threshold():
    analysis = {
        "status": "normal",
        "hrv": {
            "today_ms": 50,
            "today_ln": 3.9,
            "baseline_mean_ln": 3.85,
            "baseline_sd_ln": 0.15,
            "threshold_ln": 3.7,
            "swc_upper_ln": 3.93,
            "rolling_mean_ln": 3.9,
            "rolling_cv": 15.0,
            "trend": "stable",
        },
        "sleep_score": 80,
        "resting_hr": 52,
        "rhr_trend": "stable",
    }

    signal = daily_training_signal(
        analysis,
        tsb=-5,
        planned_workout="interval",
        recovery_thresholds={"cv_threshold": 20.0},
    )

    assert signal["recommendation"] == "follow_plan"


def test_analyze_recovery_declining_trend_override():
    """Declining trend should downgrade fresh → normal."""
    # Build a series with clear downward slope over 14+ days
    # but set today high enough to pass the fresh threshold
    baseline = [60.0] * 16
    declining = [60 - i * 2.5 for i in range(14)]  # 60 → 27.5
    series = baseline + declining
    # Today is high (would classify as "fresh" vs the now-lower recent baseline)
    analysis = analyze_recovery(series, today_hrv_ms=65.0)
    assert analysis["hrv"] is not None
    assert analysis["hrv"]["trend"] == "declining"
    # Fresh should be overridden to normal
    assert analysis["status"] != "fresh"


def test_analyze_recovery_zero_hrv_values():
    """Series with zero/negative values should be handled gracefully."""
    # Mix of valid and invalid values
    series = [50.0, 0.0, 48.0, -5.0, 52.0, 0.0, 47.0, 51.0, 49.0, 53.0]
    analysis = analyze_recovery(series, today_hrv_ms=50.0)
    # Should work — zeros/negatives filtered out, enough valid data remains
    assert analysis["hrv"] is not None
    assert analysis["status"] in ["fresh", "normal", "fatigued"]


def test_analyze_recovery_invalid_today():
    """today_hrv_ms of 0 should return insufficient_data, not stale value."""
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=0.0)
    assert analysis["status"] == "insufficient_data"
    assert analysis["hrv"] is None


def test_analyze_recovery_rhr_trend():
    """RHR trend classification should work correctly."""
    series = _make_hrv_series(50.0, 30)
    # RHR with natural variance (SD ≈ 2 bpm)
    import random
    random.seed(99)
    rhr = [52.0 + random.gauss(0, 2) for _ in range(30)]

    # Elevated RHR
    analysis = analyze_recovery(series, today_hrv_ms=50.0, today_rhr=62.0, rhr_series=rhr)
    assert analysis["rhr_trend"] == "elevated"

    # Low RHR
    analysis = analyze_recovery(series, today_hrv_ms=50.0, today_rhr=44.0, rhr_series=rhr)
    assert analysis["rhr_trend"] == "low"

    # Stable RHR
    analysis = analyze_recovery(series, today_hrv_ms=50.0, today_rhr=52.0, rhr_series=rhr)
    assert analysis["rhr_trend"] == "stable"


def test_daily_training_signal_fatigued_easy_workout():
    """Fatigued + easy workout → easy (not rest)."""
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=30.0)  # fatigued
    signal = daily_training_signal(analysis, tsb=-10, planned_workout="easy")
    assert signal["recommendation"] == "easy"


def test_daily_training_signal_high_cv():
    """High CV + hard workout → modify."""
    analysis = {
        "status": "normal",
        "hrv": {"today_ms": 50, "today_ln": 3.9, "baseline_mean_ln": 3.85,
                "baseline_sd_ln": 0.15, "threshold_ln": 3.7, "swc_upper_ln": 3.93,
                "rolling_mean_ln": 3.9, "rolling_cv": 15.0, "trend": "stable"},
        "sleep_score": 80, "resting_hr": 52, "rhr_trend": "stable",
    }
    signal = daily_training_signal(analysis, tsb=-5, planned_workout="interval")
    assert signal["recommendation"] == "modify"
    assert "cv" in signal["reason"].lower()


def test_daily_training_signal_poor_sleep():
    """Poor sleep + hard workout → modify when contextual modifiers are enabled."""
    analysis = {
        "status": "normal",
        "hrv": {"today_ms": 50, "today_ln": 3.9, "baseline_mean_ln": 3.85,
                "baseline_sd_ln": 0.15, "threshold_ln": 3.7, "swc_upper_ln": 3.93,
                "rolling_mean_ln": 3.9, "rolling_cv": 5.0, "trend": "stable"},
        "sleep_score": 40, "resting_hr": 52, "rhr_trend": "stable",
    }
    signal = daily_training_signal(analysis, tsb=-5, planned_workout="threshold")
    assert signal["recommendation"] == "modify"
    assert "sleep" in signal["reason"].lower()


def test_daily_training_signal_poor_sleep_hrv_only():
    """In HRV-only mode, poor sleep does NOT modify the recommendation."""
    analysis = {
        "status": "normal",
        "hrv": {"today_ms": 50, "today_ln": 3.9, "baseline_mean_ln": 3.85,
                "baseline_sd_ln": 0.15, "threshold_ln": 3.7, "swc_upper_ln": 3.93,
                "rolling_mean_ln": 3.9, "rolling_cv": 5.0, "trend": "stable"},
        "sleep_score": 40, "resting_hr": 52, "rhr_trend": "stable",
    }
    signal = daily_training_signal(analysis, tsb=-5, planned_workout="threshold", hrv_only=True)
    assert signal["recommendation"] == "follow_plan"


def test_daily_training_signal_elevated_rhr():
    """Elevated RHR + hard workout → modify when contextual modifiers are enabled."""
    analysis = {
        "status": "normal",
        "hrv": {"today_ms": 50, "today_ln": 3.9, "baseline_mean_ln": 3.85,
                "baseline_sd_ln": 0.15, "threshold_ln": 3.7, "swc_upper_ln": 3.93,
                "rolling_mean_ln": 3.9, "rolling_cv": 5.0, "trend": "stable"},
        "sleep_score": 80, "resting_hr": 62, "rhr_trend": "elevated",
    }
    signal = daily_training_signal(analysis, tsb=-5, planned_workout="interval")
    assert signal["recommendation"] == "modify"
    assert "heart rate" in signal["reason"].lower()


def test_daily_training_signal_insufficient_data():
    """Insufficient data → follow plan with caveat."""
    analysis = {"status": "insufficient_data", "hrv": None, "sleep_score": None,
                "resting_hr": None, "rhr_trend": None}
    signal = daily_training_signal(analysis, tsb=0, planned_workout="tempo")
    assert signal["recommendation"] == "follow_plan"
    assert signal["reason_code"] == "hrv_unavailable"
    assert "current hrv" in signal["reason"].lower()
    assert signal["alternatives"] == []


def test_cp_milestone_on_track():
    trend = {"direction": "rising", "slope_per_month": 3.0, "current": 285.0}
    result = cp_milestone_check(285, 295, trend)
    assert result["severity"] == "on_track"
    assert result["cp_gap_watts"] == 10.0
    assert result["estimated_months"] is not None
    assert result["estimated_months"] > 0
    assert len(result["milestones"]) > 0


def test_cp_milestone_reached():
    trend = {"direction": "rising", "slope_per_month": 2.0, "current": 296.0}
    result = cp_milestone_check(296, 295, trend)
    assert result["severity"] == "on_track"
    assert result["cp_gap_watts"] < 0
    assert result["estimated_months"] == 0


def test_cp_milestone_flat():
    trend = {"direction": "flat", "slope_per_month": 0.5, "current": 271.0}
    result = cp_milestone_check(271, 295, trend)
    assert result["severity"] == "behind"
    assert "flat" in result["assessment"].lower()


def test_cp_milestone_declining():
    trend = {"direction": "falling", "slope_per_month": -1.5, "current": 268.0}
    result = cp_milestone_check(268, 295, trend)
    assert result["severity"] == "unlikely"
    assert "declining" in result["assessment"].lower()


def test_cp_milestone_close():
    trend = {"direction": "rising", "slope_per_month": 1.0, "current": 292.0}
    result = cp_milestone_check(292, 295, trend)
    assert result["severity"] == "close"
    assert result["cp_gap_watts"] == 3.0


# --- diagnose_training tests ---

def _make_activities(dates, distances):
    """Helper: create minimal merged activities DataFrame."""
    return pd.DataFrame({
        "date": dates,
        "activity_id": [str(i) for i in range(len(dates))],
        "distance_km": distances,
    })


def _make_splits(activity_ids, powers, durations):
    """Helper: create minimal splits DataFrame."""
    return pd.DataFrame({
        "activity_id": activity_ids,
        "avg_power": powers,
        "duration_sec": durations,
    })


def test_diagnose_with_supra_cp_intervals():
    today = date(2026, 3, 23)
    dates = [date(2026, 3, d) for d in [2, 4, 7, 9, 11, 14, 16, 18, 20, 21]]
    activities = _make_activities(dates, [8, 10, 25, 8, 10, 8, 10, 25, 8, 10])
    splits = _make_splits(
        ["1", "1", "1", "6", "6", "6"],  # activity_ids for Tue sessions
        [200, 280, 200, 200, 275, 200],   # warmup, supra-CP interval, cooldown
        [600, 240, 600, 600, 240, 600],   # durations
    )
    trend = {"current": 270.0, "direction": "flat", "slope_per_month": 0.5}
    result = diagnose_training(activities, splits, trend, lookback_weeks=4, current_date=today)

    assert result["interval_power"]["supra_cp_sessions"] >= 1
    assert result["interval_power"]["evidence_complete"] is False
    assert result["volume"]["weekly_avg_km"] > 0
    assert any(
        "conclusions are withheld" in item["message"]
        for item in result["diagnosis"]
    )


def test_diagnose_no_intensity():
    today = date(2026, 3, 23)
    dates = [date(2026, 3, d) for d in [2, 4, 7, 9, 11, 14, 16, 18, 20, 21]]
    activities = _make_activities(dates, [8, 8, 20, 8, 8, 8, 8, 20, 8, 8])
    # All splits well below CP
    splits = _make_splits(
        ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"],
        [190, 195, 200, 185, 190, 195, 190, 205, 185, 190],
        [2400, 2400, 6000, 2400, 2400, 2400, 2400, 6000, 2400, 2400],
    )
    trend = {"current": 270.0, "direction": "flat", "slope_per_month": 0.3}
    result = diagnose_training(activities, splits, trend, lookback_weeks=4, current_date=today)

    assert result["interval_power"]["supra_cp_sessions"] == 0
    observations = [item["message"] for item in result["diagnosis"]]
    assert any("No intervals at or above CP" in message for message in observations)
    assert not any("likely reason" in message for message in observations)
    assert len(result["suggestions"]) > 0


def test_diagnose_empty_splits():
    today = date(2026, 3, 23)
    dates = [date(2026, 3, d) for d in [2, 4, 7]]
    activities = _make_activities(dates, [8, 10, 20])
    activities["avg_power"] = [400, 410, 420]
    activities["duration_sec"] = [3600, 3600, 7200]
    splits = pd.DataFrame()
    trend = {"current": 270.0, "direction": "flat", "slope_per_month": 0.5}
    result = diagnose_training(activities, splits, trend, lookback_weeks=4, current_date=today)

    # Should handle gracefully
    assert "interval_power" in result
    assert all(zone["actual_pct"] == 0 for zone in result["distribution"])
    assert any("split-level intensity" in item["message"].lower() for item in result["diagnosis"])


def test_diagnose_distribution_uses_zone_boundaries():
    """Distribution should use provided zone boundaries, not hardcoded values."""
    today = date(2026, 3, 23)
    dates = [date(2026, 3, d) for d in [2, 4, 7, 9, 11, 14, 16, 18, 20, 21]]
    activities = _make_activities(dates, [8, 10, 25, 8, 10, 8, 10, 25, 8, 10])
    splits = _make_splits(
        ["2", "2", "7", "7"],
        [260, 220, 255, 210],
        [600, 600, 600, 600],
    )
    trend = {"current": 250.0, "direction": "flat", "slope_per_month": 0.5}

    result = diagnose_training(
        activities, splits, trend,
        lookback_weeks=4, current_date=today,
        zone_boundaries=[0.82, 1.00],
        zone_names=["Easy", "Moderate", "Hard"],
        target_distribution=[0.80, 0.05, 0.15],
    )

    dist = result["distribution"]
    assert isinstance(dist, list)
    assert len(dist) == 3
    assert dist[0]["name"] == "Easy"
    assert dist[1]["name"] == "Moderate"
    assert dist[2]["name"] == "Hard"
    assert all("actual_pct" in d and "target_pct" in d for d in dist)
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
    assert len(dist) == 5
    names = [d["name"] for d in dist]
    assert names == ["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"]


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


def test_diagnose_distribution_is_time_in_zone():
    """Distribution must be split-duration-weighted time-in-zone, not
    activity-count-by-peak-zone.

    Coggan / Seiler target distributions (70/10/10/5/5) are defined as the
    fraction of TIME an athlete spends in each zone. Classifying an activity
    by its single hardest split and then counting activities per zone
    inflates higher zones whenever the athlete does any short stride or
    interval — a mostly-easy run with one 20-second sprint gets tallied as
    VO2max. See Seiler 2006 and Filipas et al. 2022 (both cited by
    `data/science/zones/coggan_5zone.yaml`), which measure training
    intensity distribution in minutes, not sessions.

    Scenario: a 2-session week with CP = 250 W, Coggan 5-zone boundaries
    [0.55, 0.75, 0.90, 1.05].
      - Day 1: 60 min easy @ 175 W (70% CP → Endurance).
      - Day 2: classic interval workout — 10 min warmup @ 175 W (Endurance),
        10 × 1 min @ 280 W (112% CP → VO2max) with 1 min recovery @ 130 W
        (52% CP → Recovery), 10 min cooldown @ 175 W (Endurance).
    Total split time is 100 min: 80 min Endurance, 10 min VO2max, 10 min
    Recovery. Peak-based classification would instead report one activity
    per zone → ~50% Endurance / 50% VO2max, which is scientifically wrong.
    """
    today = date(2026, 3, 23)
    dates = [date(2026, 3, 20), date(2026, 3, 22)]
    activities = _make_activities(dates, [12, 15])
    easy_splits = [("0", 175, 3600)]
    interval_splits = [("1", 175, 600)]
    for _ in range(10):
        interval_splits.append(("1", 280, 60))
        interval_splits.append(("1", 130, 60))
    interval_splits.append(("1", 175, 600))
    aids, powers, durations = zip(*(easy_splits + interval_splits))
    splits = _make_splits(list(aids), list(powers), list(durations))
    trend = {"current": 250.0, "direction": "flat", "slope_per_month": 0.5}

    result = diagnose_training(
        activities, splits, trend,
        lookback_weeks=4, current_date=today,
    )
    dist = {d["name"]: d["actual_pct"] for d in result["distribution"]}

    # Endurance dominates — 80 of 100 minutes — not 50%.
    assert dist["Endurance"] >= 75, f"expected Endurance ~80%, got {dist}"
    assert dist["VO2max"] <= 15, f"expected VO2max ~10%, got {dist}"
    assert dist["Recovery"] <= 15, f"expected Recovery ~10%, got {dist}"
    assert dist["Tempo"] == 0
    assert dist["Threshold"] == 0


def test_diagnose_distribution_pace_base_inverts_ratio():
    """Pace base: lower value = faster = harder zone. The classifier must
    invert the ratio (threshold_pace / split_pace) and compare against
    reciprocal boundary fractions, otherwise a 5:00 min/km split vs a
    4:20 threshold pace would read as Endurance instead of Recovery.

    Scenario: threshold pace = 260 s/km (4:20/km), Coggan pace boundaries
    [1.29, 1.14, 1.06, 1.00] (multipliers of threshold pace — higher =
    slower, so values well above 1.29x belong to Recovery).
      - Day 1: 60 min easy @ 350 s/km (5:50/km, 350/260 = 1.35x → Recovery).
      - Day 2: tempo workout — 10 min warmup @ 350 s/km (Recovery),
        20 min @ 285 s/km (285/260 = 1.10x → Tempo), 10 min cooldown
        @ 350 s/km (Recovery).
    Total split time is 100 min: 80 min Recovery, 20 min Tempo. A
    non-inverted (power-style) ratio would misplace these in the opposite
    end of the scale, so this test locks in the inversion.
    """
    today = date(2026, 3, 23)
    dates = [date(2026, 3, 20), date(2026, 3, 22)]
    activities = _make_activities(dates, [10, 12])
    rows = [
        ("0", 350.0, 3600),
        ("1", 350.0, 600),
        ("1", 285.0, 1200),
        ("1", 350.0, 600),
    ]
    aids, paces, durations = zip(*rows)
    splits = pd.DataFrame({
        "activity_id": list(aids),
        "avg_pace_sec_km": list(paces),
        "duration_sec": list(durations),
    })
    trend = {"current": 260.0, "direction": "flat", "slope_per_month": 0.0}

    result = diagnose_training(
        activities, splits, trend,
        lookback_weeks=4, current_date=today,
        base="pace",
    )
    dist = {d["name"]: d["actual_pct"] for d in result["distribution"]}

    assert result["interval_power"]["max"] == 285.0
    # Recovery dominates because splits are slower than threshold.
    assert dist["Recovery"] >= 75, f"expected Recovery ~80%, got {dist}"
    assert dist["Tempo"] >= 15, f"expected Tempo ~20%, got {dist}"
    assert dist["VO2max"] == 0
    assert dist["Endurance"] == 0
    assert dist["Threshold"] == 0

def test_diagnose_invalid_split_intensity_is_unavailable():
    """Null and non-positive split power must not become zero completed work."""
    today = date(2026, 3, 23)
    activities = _make_activities([date(2026, 3, 20)], [10])
    splits = _make_splits(["0", "0"], [None, 0], [600, 600])
    trend = {"current": 250.0, "direction": "flat", "slope_per_month": 0.0}

    result = diagnose_training(
        activities, splits, trend, lookback_weeks=4, current_date=today,
    )

    interval = result["interval_power"]
    assert interval["data_available"] is False
    assert interval["supra_cp_sessions"] is None
    assert interval["total_quality_sessions"] is None
    assert result["data_meta"]["distribution_resolution"] == "unavailable"
    assert all(zone["actual_pct"] == 0 for zone in result["distribution"])
    messages = [item["message"] for item in result["diagnosis"]]
    assert not any("likely reason" in message for message in messages)
    assert not any("supra-CP intervals" in suggestion for suggestion in result["suggestions"])


def test_diagnose_cold_start_keeps_stable_array_contracts():
    """Cold-start responses expose arrays and explicit unavailable provenance."""
    result = diagnose_training(
        pd.DataFrame(), pd.DataFrame(), {"current": 250.0},
        current_date=date(2026, 3, 23),
    )

    assert isinstance(result["diagnosis"], list)
    assert result["diagnosis"][0]["type"] == "warning"
    assert result["suggestions"] == []
    assert result["distribution"] == []
    assert result["zone_ranges"] == []
    assert result["volume"]["weeks"] == []
    assert result["volume"]["weekly_km"] == []
    assert result["interval_power"]["data_available"] is False
    assert result["data_meta"] == {
        "distribution_resolution": "unavailable",
        "distribution_complete": False,
        "distribution_coverage_pct": 0,
    }


def test_diagnose_pace_activity_average_fallback_uses_inverted_zones():
    """Pace-only fallback must classify slower averages into easier zones."""
    today = date(2026, 3, 23)
    activities = _make_activities(
        [date(2026, 3, 20), date(2026, 3, 22)], [10, 10],
    )
    activities["duration_sec"] = [3600, 3600]
    activities["avg_pace_sec_km"] = [350.0, 285.0]
    trend = {"current": 260.0, "direction": "flat", "slope_per_month": 0.0}

    result = diagnose_training(
        activities, pd.DataFrame(), trend,
        lookback_weeks=4, current_date=today, base="pace",
    )
    dist = {d["name"]: d["actual_pct"] for d in result["distribution"]}

    assert result["data_meta"]["distribution_resolution"] == "activity_averages"
    assert dist["Recovery"] == 50
    assert dist["Tempo"] == 50
    assert dist["VO2max"] == 0


def test_diagnose_honors_ultra_duration_and_volume_thresholds():
    """Selected load-theory diagnosis settings must change actual findings."""
    today = date(2026, 3, 23)
    activities = _make_activities(
        [date(2026, 3, 2), date(2026, 3, 9), date(2026, 3, 16), date(2026, 3, 20)],
        [70, 70, 70, 70],
    )
    splits = _make_splits(["0", "1", "2", "3"], [270, 270, 270, 270], [3600] * 4)
    trend = {"current": 250.0, "direction": "flat", "slope_per_month": 0.0}

    result = diagnose_training(
        activities, splits, trend,
        lookback_weeks=4,
        current_date=today,
        diagnosis_params={
            "work_split_min_sec": 120,
            "work_split_max_sec": 3600,
            "volume_strong_km": 80,
            "volume_moderate_km": 60,
        },
    )

    assert result["interval_power"]["max"] == 270.0
    assert any(
        item["message"] == "Weekly volume averaged 70.0 km, within the configured reference range."
        for item in result["diagnosis"]
    )

def test_diagnose_volume_average_includes_empty_weeks():
    """A rolling weekly average includes zero-activity weeks."""
    today = date(2026, 3, 23)
    activities = _make_activities([date(2026, 3, 20)], [40])
    splits = _make_splits(["0"], [200], [3600])

    result = diagnose_training(
        activities,
        splits,
        {"current": 250.0, "direction": "flat"},
        lookback_weeks=4,
        current_date=today,
    )

    assert result["volume"]["weekly_avg_km"] == 10.0
    assert result["volume"]["weeks"] == [
        "2026-03-02",
        "2026-03-09",
        "2026-03-16",
        "2026-03-23",
    ]
    assert result["volume"]["weekly_km"] == [0.0, 0.0, 0.0, 40.0]


def test_diagnose_volume_is_available_without_threshold_data():
    """Threshold-independent volume remains available when CP is missing."""
    today = date(2026, 3, 23)
    activities = _make_activities([date(2026, 3, 20)], [40])

    result = diagnose_training(
        activities,
        pd.DataFrame(),
        {},
        lookback_weeks=4,
        current_date=today,
    )

    assert result["volume"]["weekly_avg_km"] == 10.0
    assert result["volume"]["weekly_km"] == [0.0, 0.0, 0.0, 40.0]
    assert result["consistency"]["total_sessions"] == 1
    assert result["diagnosis"] == [{
        "type": "warning",
        "message": "No CP data available — cannot diagnose.",
    }]


def test_diagnose_volume_preserves_non_empty_all_zero_series():
    """Recorded zero distance is data, not an unavailable weekly series."""
    today = date(2026, 3, 23)
    activities = _make_activities([date(2026, 3, 20)], [0])

    result = diagnose_training(
        activities,
        pd.DataFrame(),
        {"current": 250.0, "direction": "flat"},
        lookback_weeks=4,
        current_date=today,
    )

    assert result["volume"]["weekly_avg_km"] == 0.0
    assert result["volume"]["weeks"] == [
        "2026-03-02",
        "2026-03-09",
        "2026-03-16",
        "2026-03-23",
    ]
    assert result["volume"]["weekly_km"] == [0.0, 0.0, 0.0, 0.0]
    assert result["volume"]["trend"] == "stable"


def test_diagnose_volume_handles_missing_distance_column():
    """An activity without distance produces recorded zeroes, not shape drift."""
    today = date(2026, 3, 23)
    activities = _make_activities([date(2026, 3, 20)], [10]).drop(
        columns=["distance_km"],
    )

    result = diagnose_training(
        activities,
        pd.DataFrame(),
        {"current": 250.0, "direction": "flat"},
        lookback_weeks=4,
        current_date=today,
    )

    assert result["volume"]["weekly_avg_km"] == 0.0
    assert result["volume"]["weekly_km"] == [0.0, 0.0, 0.0, 0.0]
    assert len(result["volume"]["weeks"]) == 4


def test_diagnose_withholds_conclusions_for_partial_split_evidence():
    """Missing activity intensity prevents whole-window conclusions."""
    today = date(2026, 3, 23)
    activities = _make_activities(
        [date(2026, 3, 20), date(2026, 3, 22)], [10, 10],
    )
    splits = _make_splits(["0"], [190], [3600])

    result = diagnose_training(
        activities,
        splits,
        {"current": 250.0, "direction": "flat"},
        lookback_weeks=4,
        current_date=today,
    )

    interval = result["interval_power"]
    assert interval["evidence_complete"] is False
    assert interval["activities_with_intensity_data"] == 1
    assert interval["activities_expected"] == 2
    messages = [item["message"] for item in result["diagnosis"]]
    assert any("conclusions are withheld" in message for message in messages)
    assert not any("No intervals at or above CP" in message for message in messages)
    assert result["data_meta"]["distribution_complete"] is False

def test_distribution_requires_ninety_percent_coverage_per_activity():
    """One long covered workout cannot mask a nearly uncovered short one."""
    today = date(2026, 3, 23)
    activities = _make_activities(
        [date(2026, 3, 20), date(2026, 3, 22)], [20, 2],
    )
    activities["duration_sec"] = [9000.0, 1000.0]
    splits = _make_splits(["0", "1"], [200.0, 200.0], [9000.0, 1.0])

    result = diagnose_training(
        activities,
        splits,
        {"current": 250.0, "direction": "flat"},
        lookback_weeks=4,
        current_date=today,
    )

    assert result["data_meta"]["distribution_coverage_pct"] == 90
    assert result["data_meta"]["distribution_complete"] is False
    assert result["interval_power"]["evidence_complete"] is False


@pytest.mark.parametrize(
    ("base", "column", "values", "threshold"),
    [
        ("hr", "avg_hr", [145.0, 155.0], 170.0),
        ("pace", "avg_pace_sec_km", [330.0, 300.0], 280.0),
    ],
)
def test_activity_average_distribution_never_counts_as_complete_evidence(
    base, column, values, threshold,
):
    """Activity averages may render a coarse chart but cannot prove zone mix."""
    today = date(2026, 3, 23)
    activities = _make_activities(
        [date(2026, 3, 20), date(2026, 3, 22)], [10, 10],
    )
    activities["duration_sec"] = [3600.0, 3600.0]
    activities[column] = values

    result = diagnose_training(
        activities,
        pd.DataFrame(),
        {"current": threshold, "direction": "flat"},
        lookback_weeks=4,
        current_date=today,
        base=base,
        threshold_value=threshold,
    )

    assert result["data_meta"]["distribution_resolution"] == "activity_averages"
    assert result["data_meta"]["distribution_complete"] is False
    assert result["interval_power"]["evidence_complete"] is False
    assert result["interval_power"]["activities_with_intensity_data"] == 2
    assert result["interval_power"]["activities_expected"] == 2
    assert any(
        "activity averages do not preserve interval-level zone exposure"
        in item["message"]
        for item in result["diagnosis"]
    )


def test_compute_diagnosis_wires_selected_load_theory_settings():
    """The API data layer must pass the active load theory into diagnosis."""
    from types import SimpleNamespace

    from api.deps import _compute_diagnosis

    today = date(2026, 3, 23)
    activities = _make_activities(
        [
            date(2026, 2, 16), date(2026, 2, 23), date(2026, 3, 2),
            date(2026, 3, 9), date(2026, 3, 16), date(2026, 3, 20),
        ],
        [70] * 6,
    )
    splits = _make_splits(
        ["0", "1", "2", "3", "4", "5"], [270] * 6, [3600] * 6,
    )
    config = SimpleNamespace(
        training_base="power",
        zones={"power": [0.55, 0.75, 0.90, 1.05]},
    )
    thresholds = SimpleNamespace(
        cp_watts=250.0,
        lthr_bpm=None,
        threshold_pace_sec_km=None,
    )
    load_theory = SimpleNamespace(diagnosis={
        "work_split_min_sec": 120,
        "work_split_max_sec": 3600,
        "volume_strong_km": 80,
        "volume_moderate_km": 60,
    })

    result = _compute_diagnosis(
        activities,
        splits,
        {"current": 250.0, "direction": "flat", "slope_per_month": 0.0},
        config,
        thresholds,
        {"load": load_theory},
        current_date=today,
    )

    assert result["interval_power"]["max"] == 270.0
    assert any(
        item["message"] == "Weekly volume averaged 70.0 km, within the configured reference range."
        for item in result["diagnosis"]
    )
