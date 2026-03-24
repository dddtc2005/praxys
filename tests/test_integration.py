# trail-running/tests/test_integration.py
"""Integration test: create sample CSVs, run metrics pipeline, verify output."""
import csv
import os
import tempfile
from datetime import date, timedelta

import pandas as pd
import pytest


def _write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def sample_data_dir():
    """Create a temporary data directory with sample CSV data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        today = date.today()

        # Garmin activities (last 14 days)
        activities = []
        for i in range(14):
            d = today - timedelta(days=14 - i)
            activities.append({
                "activity_id": str(1000 + i),
                "date": d.isoformat(),
                "start_time": f"{d.isoformat()} 07:00:00",
                "activity_type": "running",
                "distance_km": str(round(8 + (i % 5) * 2, 1)),
                "duration_sec": str(3000 + i * 120),
                "avg_hr": str(140 + i % 10),
                "max_hr": str(165 + i % 10),
                "elevation_gain_m": str(50 + i * 5),
                "avg_cadence": str(170 + i % 5),
                "calories": str(600 + i * 30),
            })
        _write_csv(os.path.join(tmpdir, "garmin", "activities.csv"), activities)

        # Garmin daily metrics
        _write_csv(os.path.join(tmpdir, "garmin", "daily_metrics.csv"), [{
            "date": today.isoformat(), "vo2max": "52.0", "training_status": "productive", "resting_hr": "48",
        }])

        # Stryd power data
        power_data = []
        for i in range(14):
            d = today - timedelta(days=14 - i)
            power_data.append({
                "date": d.isoformat(),
                "start_time": f"{d.isoformat()}T07:01:00Z",
                "avg_power": str(round(235 + i * 2, 1)),
                "max_power": str(round(300 + i * 3, 1)),
                "leg_spring_stiffness": str(round(10.0 + i * 0.1, 1)),
                "ground_time_ms": str(210 + i),
                "rss": str(round(70 + i * 3, 1)),
                "cp_estimate": str(round(265 + i * 0.5, 1)),
            })
        _write_csv(os.path.join(tmpdir, "stryd", "power_data.csv"), power_data)

        # Stryd training plan
        _write_csv(os.path.join(tmpdir, "stryd", "training_plan.csv"), [{
            "date": today.isoformat(), "workout_type": "tempo",
            "planned_duration_min": "60", "planned_distance_km": "12",
            "target_power_min": "235", "target_power_max": "255",
        }])

        # Oura sleep
        sleep_data = []
        for i in range(14):
            d = today - timedelta(days=14 - i)
            sleep_data.append({
                "date": d.isoformat(),
                "sleep_score": str(75 + i % 15),
                "total_sleep_sec": str(25200 + i * 600),
                "deep_sleep_sec": str(5400 + i * 100),
                "rem_sleep_sec": str(5400 + i * 50),
                "light_sleep_sec": str(14400 + i * 200),
                "efficiency": str(85 + i % 10),
            })
        _write_csv(os.path.join(tmpdir, "oura", "sleep.csv"), sleep_data)

        # Oura readiness
        readiness_data = []
        for i in range(14):
            d = today - timedelta(days=14 - i)
            readiness_data.append({
                "date": d.isoformat(),
                "readiness_score": str(70 + i % 20),
                "hrv_avg": str(40 + i % 10),
                "resting_hr": str(50 + i % 5),
                "body_temperature_delta": str(round(-0.1 + i * 0.02, 2)),
            })
        _write_csv(os.path.join(tmpdir, "oura", "readiness.csv"), readiness_data)

        yield tmpdir


def test_compute_daily_rss(sample_data_dir):
    """Test daily RSS computation from merged activity data."""
    from analysis.data_loader import load_all_data, match_activities

    data = load_all_data(sample_data_dir)
    merged = match_activities(data["garmin_activities"], data["stryd_power"])
    date_range = pd.date_range(date.today() - timedelta(days=30), date.today())
    merged["rss"] = pd.to_numeric(merged["rss"], errors="coerce").fillna(0)
    daily_rss = merged.groupby("date")["rss"].sum().reindex(date_range.date, fill_value=0.0).astype(float)
    assert len(daily_rss) == len(date_range)
    assert daily_rss.sum() > 0


def test_get_hrv_trend(sample_data_dir):
    """Test HRV trend calculation."""
    from analysis.data_loader import load_all_data
    from api.deps import _get_hrv_trend

    data = load_all_data(sample_data_dir)
    trend = _get_hrv_trend(data["oura_readiness"], days=3)
    assert isinstance(trend, float)
    assert abs(trend) < 200


def test_build_workout_flags(sample_data_dir):
    """Test workout flags generation."""
    from analysis.data_loader import load_all_data, match_activities
    from api.deps import _build_workout_flags

    data = load_all_data(sample_data_dir)
    merged = match_activities(data["garmin_activities"], data["stryd_power"])
    flags = _build_workout_flags(merged, data["oura_readiness"])
    assert isinstance(flags, list)
    for f in flags:
        assert "type" in f
        assert "date" in f
        assert "description" in f


def test_full_pipeline(sample_data_dir, tmp_path):
    """Test the full data → metrics → dashboard pipeline."""
    from analysis.data_loader import load_all_data, match_activities
    from analysis.metrics import compute_ewma_load, compute_tsb, predict_marathon_time, daily_training_signal
    from analysis.dashboard_renderer import render_dashboard
    from analysis.report_renderer import render_weekly_report

    # Load
    data = load_all_data(sample_data_dir)
    assert not data["garmin_activities"].empty
    assert not data["oura_readiness"].empty

    # Merge
    merged = match_activities(data["garmin_activities"], data["stryd_power"])
    assert len(merged) == 14
    assert "avg_power" in merged.columns

    # Metrics
    date_range = pd.date_range(date.today() - timedelta(days=30), date.today())
    daily_rss = merged.groupby("date")["rss"].sum().reindex(date_range.date, fill_value=0.0).astype(float)
    ctl = compute_ewma_load(daily_rss, 42)
    atl = compute_ewma_load(daily_rss, 7)
    tsb = compute_tsb(ctl, atl)
    assert len(tsb) == len(date_range)

    # Race prediction
    latest_cp = float(merged["cp_estimate"].dropna().iloc[-1])
    predicted = predict_marathon_time(latest_cp, [(245, 255)])
    assert predicted is not None

    # Training signal
    signal = daily_training_signal(readiness_score=80, tsb=float(tsb.iloc[-1]), hrv_trend_pct=2, planned_workout="tempo")
    assert "recommendation" in signal

    # Dashboard
    dashboard_path = os.path.join(str(tmp_path), "dashboard.html")
    render_dashboard(
        dashboard_path,
        training_signal=signal,
        race_countdown={"race_date": "2026-04-15", "days_left": 30, "predicted_time_sec": predicted, "target_time_sec": 10800, "status": "behind"},
        fitness_fatigue={"dates": [], "ctl": [], "atl": [], "tsb": []},
        weekly_review={"weeks": [], "actual_rss": [], "planned_rss": []},
        insights={"sleep_perf": [], "warnings": []},
    )
    assert os.path.exists(dashboard_path)
    html = open(dashboard_path, encoding="utf-8").read()
    assert "Training Dashboard" in html
    assert "Chart" in html

    # Report
    report_path = render_weekly_report(
        str(tmp_path),
        date.today(),
        summary={"num_activities": 14, "volume_km": 150.0, "total_rss": 1200, "planned_rss": 1100},
        training_signal=signal,
        race_countdown={"race_date": "2026-04-15", "days_left": 30, "predicted_time_sec": predicted, "target_time_sec": 10800, "status": "behind"},
        insights={"warnings": ["Test warning"]},
    )
    assert os.path.exists(report_path)
    report = open(report_path, encoding="utf-8").read()
    assert "Weekly Training Report" in report
    assert "Test warning" in report
