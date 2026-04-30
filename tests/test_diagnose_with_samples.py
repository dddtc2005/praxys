"""Tests for diagnose_training() using per-second activity_samples."""
import pandas as pd
import pytest
from datetime import date, timedelta

from analysis.metrics import diagnose_training


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _activities(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _splits(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _samples(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _today() -> date:
    return date.today()


def _recent(weeks_ago: int = 1) -> str:
    return (_today() - timedelta(weeks=weeks_ago)).isoformat()


def _cp_trend(cp: float = 250.0) -> dict:
    return {"current": cp, "avg_recent": cp, "direction": "stable",
            "slope_per_month": 0.0, "months_flat": 3}


# ---------------------------------------------------------------------------
# 1. samples=None falls back to splits (no regression)
# ---------------------------------------------------------------------------

def test_no_samples_uses_splits():
    """With samples=None, zone distribution comes from splits unchanged."""
    today = _today()
    acts = _activities([{
        "activity_id": "act-1", "date": _recent(1),
        "distance_km": 10, "duration_sec": 3600,
        "avg_power": 200, "source": "stryd",
    }])
    sp = _splits([
        {"activity_id": "act-1", "split_num": 1,
         "avg_power": 175, "duration_sec": 1800},  # endurance
        {"activity_id": "act-1", "split_num": 2,
         "avg_power": 175, "duration_sec": 1800},
    ])
    result = diagnose_training(acts, sp, _cp_trend(250), samples=None, threshold_value=250)
    assert result["distribution"]
    assert result["data_meta"]["distribution_resolution"] == "splits"


# ---------------------------------------------------------------------------
# 2. samples provided — resolution switches to "samples"
# ---------------------------------------------------------------------------

def test_samples_resolution_reported():
    """When samples with valid power exist, resolution is 'samples'."""
    acts = _activities([{
        "activity_id": "act-1", "date": _recent(1),
        "distance_km": 10, "duration_sec": 3600,
        "avg_power": 200, "source": "stryd",
    }])
    sp = _splits([
        {"activity_id": "act-1", "split_num": 1,
         "avg_power": 175, "duration_sec": 1800},
    ])
    samp = _samples([
        {"activity_id": "act-1", "t_sec": 1_000_000 + i,
         "power_watts": 175.0, "hr_bpm": 150.0, "pace_sec_km": None, "source": "stryd"}
        for i in range(100)
    ])
    result = diagnose_training(acts, sp, _cp_trend(250), samples=samp, threshold_value=250)
    assert result["data_meta"]["distribution_resolution"] == "samples"


# ---------------------------------------------------------------------------
# 3. Samples produce correct zone distribution (all in endurance zone)
# ---------------------------------------------------------------------------

def test_samples_all_endurance():
    """100 seconds at 70% CP → 100% endurance zone (Coggan zone 2)."""
    cp = 250.0
    acts = _activities([{
        "activity_id": "act-1", "date": _recent(1),
        "distance_km": 5, "duration_sec": 100,
        "avg_power": 175, "source": "stryd",
    }])
    # No splits — all zone info from samples
    sp = _splits([])
    samp = _samples([
        {"activity_id": "act-1", "t_sec": 1_000_000 + i,
         "power_watts": cp * 0.70,  # 175W = 70% CP → endurance
         "hr_bpm": None, "pace_sec_km": None, "source": "stryd"}
        for i in range(100)
    ])
    result = diagnose_training(acts, sp, _cp_trend(cp), samples=samp, threshold_value=cp)
    dist = {d["name"]: d["actual_pct"] for d in result["distribution"]}
    # Zone 1 (recovery) < 55% CP; zone 2 (endurance) 55-75%; 70% → zone 2
    assert dist.get("Endurance", 0) == 100


# ---------------------------------------------------------------------------
# 4. Mixed: samples for one activity, splits fallback for another
# ---------------------------------------------------------------------------

def test_mixed_samples_and_splits():
    """act-1 has samples (endurance); act-2 has only splits (threshold).
    Both contribute to the distribution correctly.
    """
    cp = 250.0
    acts = _activities([
        {"activity_id": "act-1", "date": _recent(1),
         "distance_km": 5, "duration_sec": 1800,
         "avg_power": 175, "source": "stryd"},
        {"activity_id": "act-2", "date": _recent(2),
         "distance_km": 5, "duration_sec": 1800,
         "avg_power": 240, "source": "garmin"},
    ])
    # Splits only for act-2 (threshold zone)
    sp = _splits([
        {"activity_id": "act-2", "split_num": 1,
         "avg_power": 240.0, "duration_sec": 1800},  # 96% CP → threshold
    ])
    # Samples only for act-1 (endurance zone), 1800 seconds
    samp = _samples([
        {"activity_id": "act-1", "t_sec": 1_000_000 + i,
         "power_watts": 175.0, "hr_bpm": None, "pace_sec_km": None, "source": "stryd"}
        for i in range(1800)
    ])
    result = diagnose_training(acts, sp, _cp_trend(cp), samples=samp, threshold_value=cp)
    assert result["data_meta"]["distribution_resolution"] == "samples"
    dist = {d["name"]: d["actual_pct"] for d in result["distribution"]}
    # 1800s endurance + 1800s threshold → ~50% each
    assert dist.get("Endurance", 0) > 0
    assert dist.get("Threshold", 0) > 0


# ---------------------------------------------------------------------------
# 5. Samples with all-null power column → graceful fallback to splits
# ---------------------------------------------------------------------------

def test_samples_all_null_power_falls_back_to_splits():
    """Samples present but power_watts all NaN → falls back to splits path."""
    cp = 250.0
    acts = _activities([{
        "activity_id": "act-1", "date": _recent(1),
        "distance_km": 5, "duration_sec": 1800,
        "avg_power": 175, "source": "garmin",
    }])
    sp = _splits([
        {"activity_id": "act-1", "split_num": 1,
         "avg_power": 175.0, "duration_sec": 1800},
    ])
    samp = _samples([
        {"activity_id": "act-1", "t_sec": 1_000_000 + i,
         "power_watts": None, "hr_bpm": None, "pace_sec_km": None, "source": "garmin"}
        for i in range(100)
    ])
    result = diagnose_training(acts, sp, _cp_trend(cp), samples=samp, threshold_value=cp)
    assert result["data_meta"]["distribution_resolution"] == "splits"


# ---------------------------------------------------------------------------
# 6. Empty samples DataFrame → fallback to splits, no crash
# ---------------------------------------------------------------------------

def test_empty_samples_df_no_crash():
    """Empty samples DataFrame should not crash and should use splits."""
    cp = 250.0
    acts = _activities([{
        "activity_id": "act-1", "date": _recent(1),
        "distance_km": 5, "duration_sec": 1800,
        "avg_power": 175, "source": "stryd",
    }])
    sp = _splits([
        {"activity_id": "act-1", "split_num": 1,
         "avg_power": 175.0, "duration_sec": 1800},
    ])
    result = diagnose_training(acts, sp, _cp_trend(cp),
                               samples=pd.DataFrame(), threshold_value=cp)
    assert result["data_meta"]["distribution_resolution"] == "splits"
    assert result["distribution"]


# ---------------------------------------------------------------------------
# 7. HR base uses hr_bpm column from samples
# ---------------------------------------------------------------------------

def test_samples_hr_base():
    """When base='hr', samples use hr_bpm for zone classification."""
    lthr = 172.0
    acts = _activities([{
        "activity_id": "act-1", "date": _recent(1),
        "distance_km": 5, "duration_sec": 1800,
        "avg_hr": 145, "source": "garmin",
    }])
    sp = _splits([
        {"activity_id": "act-1", "split_num": 1,
         "avg_hr": 145.0, "duration_sec": 1800},
    ])
    samp = _samples([
        {"activity_id": "act-1", "t_sec": 1_000_000 + i,
         "power_watts": None, "hr_bpm": 145.0, "pace_sec_km": None, "source": "garmin"}
        for i in range(100)
    ])
    result = diagnose_training(acts, sp, _cp_trend(lthr), base="hr",
                               samples=samp, threshold_value=lthr)
    assert result["data_meta"]["distribution_resolution"] == "samples"
    assert result["distribution"]
