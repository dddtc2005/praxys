import math

import pandas as pd
from datetime import date
from analysis.metrics import (
    compute_ewma_load,
    compute_tsb,
    predict_marathon_time,
    analyze_recovery,
    daily_training_signal,
    cp_milestone_check,
    diagnose_training,
)


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


def test_daily_training_signal_rest():
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=30.0)  # fatigued
    signal = daily_training_signal(analysis, tsb=-10, planned_workout="tempo")
    assert signal["recommendation"] in ["rest", "easy"]
    assert "hrv" in signal["reason"].lower()


def test_daily_training_signal_follow_plan():
    series = _make_hrv_series(50.0, 30)
    analysis = analyze_recovery(series, today_hrv_ms=60.0, today_sleep=85)  # fresh
    signal = daily_training_signal(analysis, tsb=5, planned_workout="tempo")
    assert signal["recommendation"] == "follow_plan"


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
    assert "requires hrv" in signal["reason"].lower()
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
    assert result["volume"]["weekly_avg_km"] > 0
    assert any(d["type"] == "positive" for d in result["diagnosis"])


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
    # Should flag missing supra-CP work
    warnings = [d for d in result["diagnosis"] if d["type"] == "warning"]
    assert any("supra-CP" in w["message"] or "above CP" in w["message"] for w in warnings)
    assert len(result["suggestions"]) > 0


def test_diagnose_empty_splits():
    today = date(2026, 3, 23)
    dates = [date(2026, 3, d) for d in [2, 4, 7]]
    activities = _make_activities(dates, [8, 10, 20])
    splits = pd.DataFrame()
    trend = {"current": 270.0, "direction": "flat", "slope_per_month": 0.5}
    result = diagnose_training(activities, splits, trend, lookback_weeks=4, current_date=today)

    # Should handle gracefully
    assert "interval_power" in result
    assert any("split" in d["message"].lower() or "interval" in d["message"].lower() for d in result["diagnosis"])


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
