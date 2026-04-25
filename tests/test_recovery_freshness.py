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


def test_yesterday_only_is_stale():
    """When latest row is yesterday, is_stale is True and latest_date is yesterday.

    This is the bug from #130: the Today page used to render yesterday's
    reading as if it were today's. Now the analysis exposes the actual date
    so the UI can label it.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    rows = [(today - timedelta(days=i), 45.0) for i in range(10, 1, -1)]
    rows.append((yesterday, 50.0))
    df = _build_recovery_df(rows)

    analysis, _, _, _ = _compute_recovery_analysis(df)

    assert analysis["is_stale"] is True
    assert analysis["latest_date"] == yesterday.isoformat()


def test_no_recovery_data_returns_none_latest_date():
    """Empty dataframe → latest_date is None and is_stale is False."""
    analysis, _, _, _ = _compute_recovery_analysis(pd.DataFrame())

    assert analysis["latest_date"] is None
    assert analysis["is_stale"] is False
    assert analysis["status"] == "insufficient_data"


def test_stale_data_still_classifies_status():
    """Stale data still drives the status field — the UI just labels it.

    Behavior change scope: this PR surfaces staleness; it doesn't suppress
    the signal. Yesterday's "fatigued" reading still classifies as fatigued
    until today's data syncs (#130 acceptance criteria).
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    # 30 days of high HRV → low yesterday → fatigued classification
    rows = [(today - timedelta(days=i), 60.0) for i in range(30, 1, -1)]
    rows.append((yesterday, 30.0))  # well below baseline
    df = _build_recovery_df(rows)

    analysis, _, _, _ = _compute_recovery_analysis(df)

    assert analysis["is_stale"] is True
    assert analysis["latest_date"] == yesterday.isoformat()
    assert analysis["status"] == "fatigued"
