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
    """Too few data points → default normal status, no HRV analysis."""
    analysis = analyze_recovery([50, 48, 52])
    assert analysis["status"] == "normal"
    assert analysis["hrv"] is None


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
