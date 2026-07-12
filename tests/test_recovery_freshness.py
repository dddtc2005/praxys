"""Tests for the recovery-data staleness signal added in #130.

Guards the contract that `_compute_recovery_analysis` exposes the date of
the latest available reading and an `is_stale` flag — so the Today page UI
no longer renders yesterday's HRV/sleep/RHR as if they were today's.
"""
from datetime import date, timedelta

import pandas as pd

from analysis.metrics import daily_training_signal
from api.deps import _compute_recovery_analysis, _recovery_for_guidance


def _build_recovery_df(rows: list[tuple[date, float]]) -> pd.DataFrame:
    """Build a recovery dataframe from (date, hrv_avg) rows."""
    return pd.DataFrame([
        {"date": pd.Timestamp(d), "hrv_avg": h, "resting_hr": 55.0, "sleep_score": 75.0}
        for d, h in rows
    ])


def test_fresh_data_is_not_stale():
    """When the latest row is today, is_stale is False and latest_date is today."""
    today = date.today()
    rows = [(today - timedelta(days=i), 45.0) for i in range(10, 0, -1)]
    rows.append((today, 50.0))
    df = _build_recovery_df(rows)

    analysis, _, _, _ = _compute_recovery_analysis(df)

    assert analysis["is_stale"] is False
    assert analysis["latest_date"] == today.isoformat()


def test_yesterday_only_is_not_stale():
    """Yesterday's reading is within the 1-day grace window — not stale.

    Recovery data (sleep, HRV) is recorded under the night it was measured,
    which Oura/Garmin expose under the wake-day. Until ≥2 days have passed,
    yesterday's reading is the "today" signal, so we don't badge it stale.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    rows = [(today - timedelta(days=i), 45.0) for i in range(10, 1, -1)]
    rows.append((yesterday, 50.0))
    df = _build_recovery_df(rows)

    analysis, _, _, _ = _compute_recovery_analysis(df)

    assert analysis["is_stale"] is False
    assert analysis["latest_date"] == yesterday.isoformat()


def test_two_days_old_is_stale():
    """Once the latest reading is two days old, recovery becomes stale."""
    today = date.today()
    two_days_ago = today - timedelta(days=2)
    rows = [(today - timedelta(days=i), 45.0) for i in range(10, 2, -1)]
    rows.append((two_days_ago, 50.0))
    df = _build_recovery_df(rows)

    analysis, _, _, _ = _compute_recovery_analysis(df)

    assert analysis["is_stale"] is True
    assert analysis["latest_date"] == two_days_ago.isoformat()


def test_no_recovery_data_returns_none_latest_date():
    """Empty dataframe → latest_date is None and is_stale is False."""
    analysis, _, _, _ = _compute_recovery_analysis(pd.DataFrame())

    assert analysis["latest_date"] is None
    assert analysis["is_stale"] is False
    assert analysis["status"] == "insufficient_data"


def test_stale_hrv_cannot_drive_same_day_classification():
    """HRV older than yesterday remains provenance, not a coaching input."""
    today = date.today()
    two_days_ago = today - timedelta(days=2)
    rows = [(today - timedelta(days=i), 60.0) for i in range(30, 2, -1)]
    rows.append((two_days_ago, 30.0))
    df = _build_recovery_df(rows)

    analysis, latest_hrv, _, _ = _compute_recovery_analysis(df)

    assert latest_hrv == 30.0
    assert analysis["is_stale"] is True
    assert analysis["hrv_is_stale"] is True
    assert analysis["hrv_latest_date"] == two_days_ago.isoformat()
    assert analysis["latest_date"] == two_days_ago.isoformat()
    assert analysis["status"] == "insufficient_data"
    assert analysis["hrv"] is not None
    assert _recovery_for_guidance(analysis)["hrv"] is None


def test_current_observation_is_excluded_from_hrv_and_rhr_baselines():
    """The latest observation must not contaminate its own comparison pool."""
    today = date.today()
    rows = [
        {
            "date": pd.Timestamp(today - timedelta(days=8 - index)),
            "hrv_avg": 49.0 + (index % 3),
            "resting_hr": 49.0 + (index % 3),
            "sleep_score": 75.0,
        }
        for index in range(8)
    ]
    rows.append({
        "date": pd.Timestamp(today),
        "hrv_avg": 25.0,
        "resting_hr": 70.0,
        "sleep_score": 75.0,
    })

    analysis, _, _, _ = _compute_recovery_analysis(pd.DataFrame(rows))

    assert analysis["status"] == "fatigued"
    assert analysis["hrv"]["baseline_mean_ln"] > analysis["hrv"]["today_ln"]

def test_staleness_uses_explicit_request_date_anchor():
    reading_date = date(2026, 7, 10)
    df = _build_recovery_df([
        (reading_date - timedelta(days=i), 45.0 + (i % 2))
        for i in range(7, 0, -1)
    ] + [(reading_date, 50.0)])

    current, _, _, _ = _compute_recovery_analysis(
        df, current_date=date(2026, 7, 11),
    )
    stale, _, _, _ = _compute_recovery_analysis(
        df, current_date=date(2026, 7, 12),
    )

    assert current["hrv_is_stale"] is False
    assert stale["hrv_is_stale"] is True
    assert stale["classification_reason"] == "stale_hrv"


def test_latest_date_tracks_newest_recovery_metric_not_only_hrv():
    today = date(2026, 7, 12)
    rows = [
        {
            "date": pd.Timestamp(today - timedelta(days=2)),
            "hrv_avg": 50.0,
            "resting_hr": 50.0,
            "sleep_score": None,
            "readiness_score": None,
        },
        {
            "date": pd.Timestamp(today),
            "hrv_avg": None,
            "resting_hr": None,
            "sleep_score": 82.0,
            "readiness_score": 76.0,
        },
    ]

    analysis, _, latest_sleep, _ = _compute_recovery_analysis(
        pd.DataFrame(rows), current_date=today,
    )

    assert latest_sleep == 82.0
    assert analysis["latest_date"] == today.isoformat()
    assert analysis["is_stale"] is False
    assert analysis["hrv_latest_date"] == (today - timedelta(days=2)).isoformat()
    assert analysis["hrv_is_stale"] is True
    assert analysis["sleep_latest_date"] == today.isoformat()
    assert analysis["sleep_is_stale"] is False
    assert analysis["readiness_latest_date"] == today.isoformat()
    assert analysis["readiness_is_stale"] is False
    assert analysis["rhr_latest_date"] == (today - timedelta(days=2)).isoformat()
    assert analysis["rhr_is_stale"] is True

def test_stale_sleep_and_rhr_remain_displayable_but_not_actionable():
    """Metric dates gate guidance without erasing the last observed values."""
    today = date(2026, 7, 12)
    rows = [
        {
            "date": pd.Timestamp(today - timedelta(days=10 - index)),
            "hrv_avg": 49.0 + (index % 3),
            "resting_hr": None,
            "sleep_score": None,
            "readiness_score": None,
        }
        for index in range(10)
    ]
    rows.append({
        "date": pd.Timestamp(today - timedelta(days=3)),
        "hrv_avg": None,
        "resting_hr": 80.0,
        "sleep_score": 20.0,
        "readiness_score": 15.0,
    })
    rows.append({
        "date": pd.Timestamp(today),
        "hrv_avg": 50.0,
        "resting_hr": None,
        "sleep_score": None,
        "readiness_score": None,
    })

    analysis, _, _, _ = _compute_recovery_analysis(
        pd.DataFrame(rows), current_date=today,
    )
    current = _recovery_for_guidance(analysis)

    assert analysis["sleep_score"] == 20.0
    assert analysis["resting_hr"] == 80.0
    assert analysis["readiness_score"] == 15.0
    assert analysis["sleep_is_stale"] is True
    assert analysis["rhr_is_stale"] is True
    assert analysis["readiness_is_stale"] is True
    assert current["sleep_score"] is None
    assert current["resting_hr"] is None
    assert current["rhr_trend"] is None
    assert current["readiness_score"] is None

    signal = daily_training_signal(
        current,
        tsb=0,
        planned_workout="threshold",
        hrv_only=False,
    )
    assert signal["recommendation"] == "follow_plan"
    assert signal["reason_code"] == "recovery_normal"


def test_old_observations_do_not_form_a_current_recovery_baseline():
    """A fresh reading cannot be compared with arbitrarily old history."""
    today = date(2026, 7, 12)
    rows = [
        (today - timedelta(days=60 - i), 50.0 + (i % 2))
        for i in range(7)
    ]
    rows.append((today, 35.0))

    analysis, _, _, _ = _compute_recovery_analysis(
        _build_recovery_df(rows),
        recovery_params={"rolling_days": 7, "baseline_days": 30},
        current_date=today,
    )

    assert analysis["status"] == "insufficient_data"
    assert analysis["classification_reason"] == "insufficient_history"