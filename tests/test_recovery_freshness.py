"""Tests for the recovery-data staleness signal added in #130.

Guards the contract that `_compute_recovery_analysis` exposes the date of
the latest available reading and an `is_stale` flag — so the Today page UI
no longer renders yesterday's HRV/sleep/RHR as if they were today's.
"""
from datetime import date, timedelta

import pandas as pd

from api.deps import _compute_recovery_analysis


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


def test_stale_data_still_classifies_status():
    """Stale data still drives the status field — the UI just labels it.

    Behavior change scope: this PR surfaces staleness; it doesn't suppress
    the signal. The latest reading still classifies fatigued/normal/fresh
    based on the HRV value, even when stale (#130 acceptance criteria).
    """
    today = date.today()
    two_days_ago = today - timedelta(days=2)
    # 30 days of high HRV → low two-days-ago → fatigued classification
    rows = [(today - timedelta(days=i), 60.0) for i in range(30, 2, -1)]
    rows.append((two_days_ago, 30.0))  # well below baseline
    df = _build_recovery_df(rows)

    analysis, _, _, _ = _compute_recovery_analysis(df)

    assert analysis["is_stale"] is True
    assert analysis["latest_date"] == two_days_ago.isoformat()
    assert analysis["status"] == "fatigued"
